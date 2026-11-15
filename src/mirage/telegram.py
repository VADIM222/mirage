from __future__ import annotations

import json
import hashlib
import queue
import re
import secrets
import threading
import time
from typing import Protocol
import uuid

import httpx

from .model import BUILDING_TYPES, BarbarianOptions, BuildingOptions, DonationOptions, GATHER_RESOURCES, GatherOptions, Instance, LucerneOptions, MATERIALS, MaterialOptions, Profile, RESEARCH_MODES, RESEARCH_TYPES, ResearchOptions, Slot, SupplyBoxOptions, TASKS, TrainingOptions, TutorialOptions, VIP_SHOP_ITEMS, VipShopOptions
from .secrets import decrypt, encrypt, redact
from .storage import Store
from .commanders import commander_catalog,commander_name,set_commander
from .i18n import LANGUAGES, Verbatim, language_for, translate


class TelegramError(RuntimeError):
    pass


class Api:
    def __init__(self, token: str, client: httpx.Client | None = None):
        if not re.fullmatch(r"\d{5,20}:[A-Za-z0-9_-]{20,}", token):
            raise ValueError("Токен Telegram имеет неверный формат")
        self.token = token
        self.client = client or httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False)
        self._owns_client = client is None

    def call(self, method: str, values: dict | None = None, photo: bytes | None = None):
        allowed = {"getMe", "getWebhookInfo", "getUpdates", "sendMessage", "sendPhoto", "answerCallbackQuery"}
        if method not in allowed:
            raise ValueError("Неподдерживаемый метод Telegram")
        try:
            url = f"https://api.telegram.org/bot{self.token}/{method}"
            if photo is not None:
                data = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict,list)) else str(value)
                        for key,value in (values or {}).items()}
                response = self.client.post(url, data=data, files={"photo": ("mirage.png", photo, "image/png")})
            else:
                response = self.client.post(url, json=values or {})
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise TelegramError("Telegram вернул некорректный ответ")
            if not payload.get("ok"):
                raise TelegramError(redact(payload.get("description", "Telegram отклонил запрос")))
            return payload["result"]
        except (httpx.HTTPError, ValueError, KeyError) as error:
            raise TelegramError(redact(error)) from None

    def close(self):
        if self._owns_client:
            self.client.close()


class Backend(Protocol):
    def instances(self) -> list[Instance]: ...
    def start(self, key: str) -> str: ...
    def stop(self, key: str) -> str: ...
    def screenshot(self, key: str) -> bytes: ...
    def status(self, key: str) -> str: ...
    def rotation(self, enabled: bool) -> str: ...
    def live_url(self) -> str: ...


def keyboard(rows):
    return {"inline_keyboard": [[{"text": text, "callback_data": data} for text,data in row] for row in rows]}


class Router:
    def __init__(self, api: Api, store: Store, backend: Backend):
        self.api, self.store, self.backend = api, store, backend
        self.pair_code = secrets.token_urlsafe(16)
        self.pending: dict | None = None
        self._aliases: dict[str, tuple] = {}

    def _alias(self, *value):
        if len(self._aliases) >= 256:
            self._aliases.clear()
        key = secrets.token_hex(6)
        self._aliases[key] = value
        return key

    def _send(self, chat: int, text: str, markup: dict | None = None):
        language = language_for(self.store)
        values = {"chat_id": chat, "text": translate(text, language)[:4096]}
        if markup:
            values["reply_markup"] = {**markup, 'inline_keyboard': [
                [{**item, 'text': translate(item['text'], language)} for item in row]
                for row in markup.get('inline_keyboard', [])]}
        self.api.call("sendMessage", values)

    def _instances(self):
        return {instance.id: instance for instance in self.backend.instances()}

    def menu(self, chat):
        rows = [[(Verbatim(instance.name), f"instance:{instance.id}")] for instance in self.backend.instances()]
        rows.append([("Ротация", "rotation")])
        rows.append([("Язык интерфейса", "language")])
        markup = keyboard(rows)
        url = getattr(self.backend, "live_url", lambda: "")()
        if re.fullmatch(r"https://[a-z0-9-]+\.trycloudflare\.com", url):
            markup["inline_keyboard"].append([{"text":"Mirage Live · экран", "web_app":{"url":url}}])
        self._send(chat, "Mirage · выберите эмулятор", markup)

    def language_menu(self, owner):
        rows = [[(Verbatim(title), 'language:' + code)] for code, title in LANGUAGES]
        rows.append([('Назад', 'menu')])
        self._send(owner, 'Язык интерфейса', keyboard(rows))

    def instance_menu(self, chat, key):
        instance = self._instances().get(key)
        if instance is None:
            raise ValueError("Эмулятор больше не найден")
        rows = [[("▶ Задачи", f"run:{key}"), ("■ Стоп", f"stop:{key}")],
                [("Снимок экрана", f"screen:{key}"), ("Расписание", f"schedule:{key}")],
                 [("Выбор задач", f"tasks:{key}"), ("Пресеты", f"presets:{key}")],
                 [("Настройки обучения", f"training:{key}")],
                 [("Пожертвования альянсу", f"donation:{key}")],
                 [("Производство материалов", f"materials:{key}")],
                  [("Сбор ресурсов", f"gather:{key}")],
                  [('Варвары',f'barbarians:{key}'),('Цепочка',f'barbarianchain:{key}')],
                   [("Улучшение зданий", f"buildings:{key}")],
                   [('Исследования',f'research:{key}')],
                  [("Ящики снабжения", f"supply:{key}")],
                  [("Сундуки пещер", f"caveboxes:{key}")],
                  [("VIP-магазин", f"vipshop:{key}")],
                   [('Люцернские свитки',f'lucerne:{key}')],
                   [('Обучение новичка',f'tutorial:{key}')],
                [("Главное меню", "menu")]]
        self._send(chat, Verbatim(f"{instance.name}\n{translate(self.backend.status(key), language_for(self.store))}"), keyboard(rows))

    def schedule(self, chat, key):
        profile = self.store.profile(key)
        # Use short session-local callback keys for slots: Telegram limits data to 64 bytes.
        self._slot_map = getattr(self, "_slot_map", {})
        if len(self._slot_map) > 128:
            self._slot_map.clear()
        rows = []
        for slot in profile.slots:
            alias = secrets.token_hex(5)
            self._slot_map[alias] = (key, slot.id)
            rows.append([(f"{slot.start}–{slot.end}", f"slot:{alias}")])
        rows += [[("+ Добавить слот", f"add:{key}")],
                 [("Выключить расписание" if profile.schedule_enabled else "Включить расписание", f"toggle:{key}")],
                 [("Назад", f"instance:{key}")]]
        self._send(chat, "Расписание · только для уже работающего эмулятора", keyboard(rows))

    def tasks(self, owner, key):
        profile = self.store.profile(key)
        from .workflows import VERIFIED_WORKFLOWS
        rows = []
        for task, (name, group) in TASKS.items():
            enabled = profile.tasks.get(task, {}).get("enabled", False)
            alias = self._alias(key, task)
            state = "✓ " if enabled else "○ "
            suffix = "" if task in VERIFIED_WORKFLOWS else " · не проверен"
            rows.append([(state + name + suffix, f"task:{alias}"), ("Интервал", f"interval:{alias}")])
        rows.append([("Назад", f"instance:{key}")])
        self._send(owner, "Выбор задач профиля. Непроверенные сценарии сохраняются, но не запускаются.", keyboard(rows))

    def presets(self, owner, key):
        rows = [[(Verbatim(name), "preset:" + self._alias(key, name))] for name in self.store.presets()]
        rows += [[("Сохранить текущий профиль", f"savepreset:{key}")], [("Назад", f"instance:{key}")]]
        self._send(owner, "Пресеты · применение ставит задачи на ручную паузу", keyboard(rows))

    def material_menu(self, owner, key):
        options = MaterialOptions.from_settings(self.store.profile(key).tasks.get("materials",{}))
        rows = [[(("✓ " if item==options.item_id else "○ ")+name,"matitem:"+self._alias(key,item))]
                for item,name in MATERIALS.items()]
        rows += [[("Заказов: "+str(options.max_orders),f"matlimit:{key}")],[("Назад",f"instance:{key}")]]
        self._send(owner,"Обычные материалы · по 15 единиц, один заказ за проверку. Гемы не используются.",keyboard(rows))

    def gather_menu(self, owner, key):
        options=GatherOptions.from_settings(self.store.profile(key).tasks.get("gather_resources",{}))
        rows=[[(("✓ " if resource==options.resource else "○ ")+name,"gatherresource:"+self._alias(key,resource))]
              for resource,name in GATHER_RESOURCES.items()]
        rows += [[(title+str(getattr(options,field)),"gathervalue:"+self._alias(key,field))]
              for field,title in (("level","Уровень поиска: "),("max_level","Максимум уровня: "),
                                  ("max_travel","Переход, секунд: "),("max_marches","Лимит всех маршей: "))]
        rows.append([("Назад",f"instance:{key}")])
        self._send(owner,"Еда, дерево, камень и золото · один новый марш за проверку. Лимит учитывает все занятые марши. "
            "Командиров рекомендует игра; только осадные с достаточной вместимостью. Занятые цели пропускаются.",keyboard(rows))

    def barbarian_menu(self,owner,key,task='barbarians'):
        if task not in ('barbarians','barbarian_chain'):raise ValueError('Неизвестный режим фарма')
        options=BarbarianOptions.from_settings(self.store.profile(key).tasks.get(task,{}))
        catalog=commander_catalog(self.store,key)
        rows=[[(title+commander_name(getattr(options,slot),catalog),'battleheroes:'+self._alias(key,task,slot,0))]
            for slot,title in (('primary','Основной: '),('deputy','Второй: '))]
        rows.extend([[(title+str(getattr(options,field)),'battlevalue:'+self._alias(key,task,field))]
            for field,title in (('level','Мин. уровень на карте: ' if task=='barbarian_chain' else 'Уровень: '),
                ('max_level','Макс. уровень на карте: ' if task=='barbarian_chain' else 'Максимум соседей: '),('reserve_ap','Резерв AP: '),
                ('max_battles','Платных боёв за заход: '),('min_health','Порог численности, %: '))])
        rows.append([('Назад',f'instance:{key}')])
        self._send(owner,TASKS[task][0]+' · настройки отдельного режима. Удержание и повторное использование той же армии. '
            'Бот сам назначает пару и выводит отряд. Стоимость AP читается из игры.'+
            (' Широкий обзор «Ресурсы»,радиус450,до3 участков за проверку; '
                'без игрового поиска,приоритет3+,пропавшая цель не вызывает возврат.'
                if task=='barbarian_chain' else ''),keyboard(rows))

    def barbarian_commanders_menu(self,owner,key,task,slot,page=0):
        if task not in ('barbarians','barbarian_chain') or slot not in ('primary','deputy'):
            raise ValueError('Неизвестный выбор командира')
        options=BarbarianOptions.from_settings(self.store.profile(key).tasks.get(task,{}))
        catalog=commander_catalog(self.store,key);heroes=catalog['heroes'];rows=[]
        available=catalog['ready'] and (slot=='primary' or heroes.get(str(options.primary),{}).get('star',0)>=3)
        choices=sorted(heroes.values(),key=lambda row:(row['name'].casefold(),row['id'])) if available else []
        choices=[row for row in choices if slot=='primary' or row['id']!=options.primary]
        if slot=='deputy':rows.append([('Без второго командира','battlehero:'+self._alias(key,task,slot,0,catalog['player']))])
        if type(page) is not int or not 0<=page<=max(0,(len(choices)-1)//12):raise ValueError('Неизвестная страница')
        for row in choices[page*12:(page+1)*12]:
            title=('✓ ' if getattr(options,slot)==row['id'] else '')+row['name']+f" · ур.{row['level']} · {row['star']}★"
            rows.append([(title,'battlehero:'+self._alias(key,task,slot,row['id'],catalog['player']))])
        pages=[]
        if page:pages.append(('←','battleheroes:'+self._alias(key,task,slot,page-1)))
        if (page+1)*12<len(choices):pages.append(('→','battleheroes:'+self._alias(key,task,slot,page+1)))
        if pages:rows.append(pages)
        rows.append([('Назад',('barbarianchain:' if task=='barbarian_chain' else 'barbarians:')+key)])
        text='Основной командир' if slot=='primary' else 'Второй командир'
        if not catalog['ready']:text+=' · список аккаунта ещё не прочитан'
        elif not available:text+=' · основной командир должен иметь три звезды'
        self._send(owner,text,keyboard(rows))

    def building_menu(self,owner,key):
        options=BuildingOptions.from_settings(self.store.profile(key).tasks.get('buildings',{}))
        types=[[(('✓ ' if kind in options.types else '○ ')+title,'buildtype:'+self._alias(key,kind))]
               for kind,title in BUILDING_TYPES.items()]
        self._send(owner,'Обычное улучшение выбранных существующих зданий до уровня '+str(options.max_level)
            +'\nРезервы (еда / дерево / камень / золото): '+' / '.join(map(str,options.reserves))
            +'\nПостоянный строитель, без гемов и ускорений. Пакеты еды/дерева10000: '
            +('включены, до4 за проверку' if options.use_resource_packs else 'выключены'),keyboard(types+[
            [(('✓ ' if options.use_resource_packs else '○ ')+'Ресурсы из сумки','buildpacks:'+key)],
            [(('✓ ' if options.auto_prerequisites else '○ ')+'Цепочки предпосылок','buildprereqs:'+key)],
            [(('✓ ' if options.create_missing else '○ ')+'Строить отсутствующие','buildmissing:'+key)],
            [(('✓ ' if options.clear_plants else '○ ')+'Упаковывать растения для места','buildplants:'+key)],
                [('Целевой уровень',f'buildlevel:{key}')],[('Резервы',f'buildreserves:{key}')],
                [('Назад',f'instance:{key}')]]))

    def donation_menu(self, owner, key):
        options = DonationOptions.from_settings(self.store.profile(key).tasks.get("alliance_donate",{}))
        self._send(owner,"Ресурсные пожертвования · одно за проверку до дневной цели. Гемы не используются.\n"
            +"Цель очков: "+str(options.daily_goal)+"\nРезервы (еда / дерево / камень / золото): "
            +" / ".join(map(str,options.reserves)),keyboard([
                [("Дневная цель",f"donategoal:{key}")],[("Резерв ресурсов",f"donatereserves:{key}")],
                [("Назад",f"instance:{key}")]]))

    def research_menu(self,owner,key):
        options=ResearchOptions.from_settings(self.store.profile(key).tasks.get('research',{}))
        mode='custom' if options.priority_mode=='legacy' else options.priority_mode
        rows=[[(('✓ ' if name==mode else '○ ')+title,'researchmode:'+self._alias(key,name))]
            for name,title in RESEARCH_MODES.items()]
        for branch,title in ((('economy','Порядок экономики'),('military','Порядок военных')) if mode=='balanced' else (('all','Порядок технологий'),)):
            rows.append([(title,'researchorder:'+self._alias(key,mode,branch,0))])
        rows += [[('Целевой уровень: '+str(options.max_level),'researchlevel:'+key)],
            [(('✓ ' if options.use_resource_packs else '○ ')+'Ресурсы из сумки','researchpacks:'+key)],
            [(('✓ ' if options.auto_prerequisites else '○ ')+'Предпосылки: технологии и академия','researchprereqs:'+key)],
            [('Резервы ресурсов','researchreserves:'+key)],[('Назад','instance:'+key)]]
        self._send(owner,'Приоритет исследований: '+RESEARCH_MODES[mode]+'.\n'
            +'В 50/50 чередуются запуски веток; порядок внутри каждой ветки сохраняется отдельно.\n'
            +'Один обычный старт при свободной академии. '
            'Гемы и ускорения не используются.\nРезервы: '+' / '.join(map(str,options.reserves)),keyboard(rows))

    def research_order_menu(self,owner,key,mode,branch,page=0):
        if mode not in RESEARCH_MODES or branch not in ('all','economy','military'):
            raise ValueError('Неизвестная таблица приоритетов')
        options=ResearchOptions.from_settings(self.store.profile(key).tasks.get('research',{}))
        order=options.order_for(mode)
        if mode=='balanced':order=tuple(k for k in order if (k<200)==(branch=='economy'))
        pages=(len(order)+7)//8;page=max(0,min(pages-1,page));start=page*8
        lines=[RESEARCH_MODES[mode]+' · порядок '+('экономики' if branch=='economy' else 'военных' if branch=='military' else 'технологий')]
        rows=[]
        for i,kind in enumerate(order[start:start+8],start):
            lines.append(str(i+1)+'. '+RESEARCH_TYPES[kind]);buttons=[]
            if i:buttons.append(('↑ '+str(i+1),'researchmove:'+self._alias(key,mode,kind,'up',page)))
            if i+1<len(order):buttons.append(('↓ '+str(i+1),'researchmove:'+self._alias(key,mode,kind,'down',page)))
            if i:buttons.append(('В начало '+str(i+1),'researchmove:'+self._alias(key,mode,kind,'top',page)))
            rows.append(buttons)
        navigation=[]
        if page:navigation.append(('←','researchorder:'+self._alias(key,mode,branch,page-1)))
        if page+1<pages:navigation.append(('→','researchorder:'+self._alias(key,mode,branch,page+1)))
        if navigation:rows.append(navigation)
        rows.append([('Назад','research:'+key)])
        self._send(owner,'\n'.join(lines)+'\nСтраница '+str(page+1)+'/'+str(pages),keyboard(rows))

    def supply_menu(self,owner,key,task='supply_boxes'):
        options=SupplyBoxOptions.from_settings(self.store.profile(key).tasks.get(task,{}))
        title='Подтверждённые письма пещер и сундуки7014' if task=='cave_rewards' else 'Обычный Supply Box (7001)'
        action='cavelimit' if task=='cave_rewards' else 'supplylimit'
        self._send(owner,title+' · по одному с проверкой расхода и награды. '
            'После остановки завершается подтверждение уже полученной награды.',keyboard([
                [('Ящиков за проверку: '+str(options.max_boxes),f'{action}:{key}')],
                [('Назад',f'instance:{key}')]]))

    def vip_shop_menu(self,owner,key):
        options=VipShopOptions.from_settings(self.store.profile(key).tasks.get('vip_shop',{}))
        rows=[[(('✓ ' if item==options.item_id else '○ ')+title,'vipitem:'+self._alias(key,item))]
              for item,title in VIP_SHOP_ITEMS.items()]
        rows += [[('Максимальная цена: '+str(options.max_price),f'vipprice:{key}')],
                 [('Резерв еды: '+str(options.reserve),f'vipreserve:{key}')],[('Назад',f'instance:{key}')]]
        self._send(owner,'VIP-магазин · частично:4 товара за еду. Требуется переделка полного списка с прокруткой: '
            'всё за ресурсы, товары за гемы — по отдельным галочкам. Сейчас одна выбранная покупка за проверку.',keyboard(rows))

    def lucerne_menu(self,owner,key):
        options=LucerneOptions.from_settings(self.store.profile(key).tasks.get('lucerne',{}))
        self._send(owner,'Свитки · бесплатный пропуск: ежедневный опыт, готовые испытания, заработанные призы.',keyboard([
            [('Получений опыта за проверку: '+str(options.max_claims),f'lucernelimit:{key}')],
            [('Назад',f'instance:{key}')]]))

    def tutorial_menu(self,owner,key):
        options=TutorialOptions.from_settings(self.store.profile(key).tasks.get('tutorial',{}))
        self._send(owner,'Вступление slg_2_v4 · проверка этапа, стоимости и наград. '
            'Боевое обучение поддержано частично; неизвестный этап ожидает разработки.',keyboard([
            [('Действий за проверку: '+str(options.max_actions),f'tutoriallimit:{key}')],
            [('Назад',f'instance:{key}')]]))

    def training_menu(self, owner, key):
        options = TrainingOptions.from_settings(self.store.profile(key).tasks.get("training",{}))
        rows = [[(("✓ " if unit in options.units else "○ ")+name,"trainunit:"+self._alias(key,unit))]
                for unit,name in enumerate(("Пехота","Стрелки","Кавалерия","Осадные"),1)]
        rows += [[("Тир: T"+str(options.tier),"trainvalue:"+self._alias(key,"tier")),
                  ("Партия: "+str(options.count),"trainvalue:"+self._alias(key,"count"))],
                 [("Резерв ресурсов",f"trainreserves:{key}")],[("Назад",f"instance:{key}")]]
        self._send(owner,"Обычное обучение · выберите типы войск\n"
            +"Резервы (еда / дерево / камень / золото): "+" / ".join(map(str,options.reserves)),keyboard(rows))

    def slot_tasks(self, owner, instance, slot_id):
        profile = self.store.profile(instance)
        slot = next((s for s in profile.slots if s.id == slot_id), None)
        if slot is None:
            raise ValueError("Слот уже удалён")
        rows = [[(("✓ " if task in slot.tasks else "○ ") + name,
                  "slottask:" + self._alias(instance, slot_id, task))] for task,(name,group) in TASKS.items()]
        rows.append([("Назад", f"schedule:{instance}")])
        self._send(owner, f"Задачи слота {slot.start}–{slot.end}", keyboard(rows))

    def rotation_menu(self, owner):
        settings = self.store.preference("rotation", {})
        selected = set(settings.get("members", []))
        rows = [[(Verbatim(("✓ " if i.id in selected else "○ ") + i.name), "rotmember:" + self._alias(i.id))]
                for i in self.backend.instances()]
        rows += [[("Включить", "rotstart"), ("Остановить", "rotstop")],
                 [("Параллельность / время", "rotsettings")], [("Меню", "menu")]]
        self._send(owner, f"Пул ротации: {len(selected)} · параллельно {settings.get('parallel', 1)} · "
                         f"{settings.get('duration', 3600) // 60} мин на экземпляр", keyboard(rows))

    def handle(self, update: dict):
        callback = update.get("callback_query")
        message = callback.get("message", {}) if callback else update.get("message", {})
        sender = callback.get("from", {}) if callback else message.get("from", {})
        chat = message.get("chat", {})
        if chat.get("type") != "private" or not isinstance(sender.get("id"), int) or chat.get("id") != sender["id"]:
            return
        owner = self.store.preference("telegram_owner")
        text = message.get("text", "") if not callback else ""
        if owner is None:
            if text == "/start " + self.pair_code:
                owner = sender["id"]
                self.store.set_preference("telegram_owner", owner)
                self.pair_code = ""
                self._send(owner, "Владелец Mirage привязан.")
            else:
                return
        if sender["id"] != owner:
            return
        try:
            if callback:
                self.api.call("answerCallbackQuery", {"callback_query_id": callback["id"]})
                self._callback(owner, callback.get("data", ""))
            elif text in ("/start", "/menu", "/cancel"):
                self.pending = None
                self.menu(owner)
            elif self.pending:
                self._text(owner, text)
            else:
                self.menu(owner)
        except (ValueError, KeyError, RuntimeError) as error:
            self._send(owner, redact(str(error)))

    def _callback(self, owner: int, data: str):
        if not isinstance(data, str) or len(data.encode("utf-8")) > 64:
            raise ValueError("Некорректная команда")
        self.pending = None
        if data in ("menu", "rotation", "rotstart", "rotstop", "rotsettings"):
            self.pending = None
        if data == "menu":
            self.menu(owner)
            return
        if data == 'language':
            self.language_menu(owner)
            return
        if data in ('language:ru', 'language:en'):
            self.store.set_preference('language', data.split(':')[1])
            self.menu(owner)
            return
        if data == "rotation":
            self.rotation_menu(owner)
            return
        if data in ("rotstart", "rotstop"):
            self._send(owner, self.backend.rotation(data == "rotstart"))
            self.rotation_menu(owner)
            return
        if data == "rotsettings":
            self.pending = {"kind": "rotation"}
            self._send(owner, "Отправьте: число параллельных экземпляров и минуты на экземпляр. Например: 3 60")
            return
        action, key = data.split(":", 1)
        if action in ("task", "interval", "preset", "rotmember", "slottask", "trainunit", "trainvalue", "matitem", "gathervalue", "gatherresource", "vipitem",'buildtype','researchmode','researchorder','researchmove','battlevalue','battleheroes','battlehero'):
            value = self._aliases.get(key)
            if value is None:
                raise ValueError("Кнопка устарела: откройте меню заново")
            sizes = {"task":2, "interval":2, "preset":2, "rotmember":1, "slottask":3,"trainunit":2,"trainvalue":2,"matitem":2,"gathervalue":2,"gatherresource":2,"vipitem":2,'buildtype':2,'researchmode':2,'researchorder':4,'researchmove':5,'battlevalue':3,'battleheroes':4,'battlehero':5}
            if len(value) != sizes[action]:
                raise ValueError("Некорректная кнопка")
            if action in ("task", "interval", "slottask") and value[-1] not in TASKS:
                raise ValueError("Неизвестная задача")
            instance = value[0]
            if instance not in self._instances():
                raise ValueError("Экземпляр больше не найден")
            if action=='battleheroes':
                self.barbarian_commanders_menu(owner,*value);return
            if action=='battlehero':
                _,task,slot,id,player=value
                if task not in ('barbarians','barbarian_chain') or slot not in ('primary','deputy'):
                    raise ValueError('Неизвестный выбор командира')
                catalog=commander_catalog(self.store,instance)
                if id and (not catalog['ready'] or catalog['player']!=player or str(id) not in catalog['heroes']):
                    raise ValueError('Список командиров изменился: откройте меню заново')
                def change(profile):
                    settings=profile.tasks.setdefault(task,{})
                    if slot=='deputy' and id and catalog['heroes'].get(str(settings.get('primary',3)),{}).get('star',0)<3:
                        raise ValueError('Для второго командира нужны три звезды основного')
                    set_commander(settings,slot,id)
                    if slot=='primary' and catalog['heroes'][str(id)]['star']<3:settings['deputy']=0
                self.store.update_profile(instance,change);self.pending=None
                self.barbarian_menu(owner,instance,task);return
            if action=='battlevalue':
                if value[1] not in ('barbarians','barbarian_chain') or value[2] not in ('level','max_level','reserve_ap','max_battles','min_health'):
                    raise ValueError('Неизвестная настройка фарма')
                self.pending={'kind':'barbarian_value','instance':instance,'task':value[1],'field':value[2]}
                self._send(owner,'Отправьте целое значение параметра. /cancel — отмена.');return
            if action=='researchmode':
                if value[1] not in RESEARCH_MODES:raise ValueError('Неизвестный режим исследований')
                def change(profile):
                    settings=profile.tasks.setdefault('research',{});options=ResearchOptions.from_settings(settings)
                    settings.setdefault('priority_orders',{}).setdefault('custom',list(options.order_for('custom')))
                    settings['priority_mode']=value[1];settings.pop('types',None)
                self.store.update_profile(instance,change);self.research_menu(owner,instance)
            elif action=='researchorder':
                self.research_order_menu(owner,instance,value[1],value[2],value[3])
            elif action=='researchmove':
                _,mode,kind,direction,page=value
                if mode not in RESEARCH_MODES or kind not in RESEARCH_TYPES or direction not in ('up','down','top'):
                    raise ValueError('Неизвестная строка приоритета')
                branch='economy' if kind<200 else 'military'
                def change(profile):
                    settings=profile.tasks.setdefault('research',{});options=ResearchOptions.from_settings(settings)
                    order=list(options.order_for(mode));subset=[k for k in order if mode!='balanced' or (k<200)==(kind<200)]
                    if kind not in subset:raise ValueError('Технология не относится к этой таблице')
                    source=subset.index(kind);target=0 if direction=='top' else source+(-1 if direction=='up' else 1)
                    if not 0<=target<len(subset):raise ValueError('Граница таблицы приоритетов')
                    subset.insert(target,subset.pop(source))
                    if mode=='balanced':
                        iterator=iter(subset);order=[next(iterator) if (k<200)==(kind<200) else k for k in order]
                    else:order=subset
                    settings.setdefault('priority_orders',{})[mode]=order
                    settings['priority_mode']=mode;settings.pop('types',None)
                self.store.update_profile(instance,change)
                self.research_order_menu(owner,instance,mode,branch if mode=='balanced' else 'all',page)
            elif action == 'buildtype':
                if type(value[1]) is not int or value[1] not in BUILDING_TYPES:raise ValueError('Неизвестный тип здания')
                def change(profile):
                    settings=profile.tasks.setdefault('buildings',{});types=set(settings.get('types',[4]))
                    types.discard(value[1]) if value[1] in types else types.add(value[1])
                    settings['types']=sorted(types)
                self.store.update_profile(instance,change);self.building_menu(owner,instance)
            elif action == 'vipitem':
                if type(value[1]) is not int or value[1] not in VIP_SHOP_ITEMS:raise ValueError('Неизвестный товар VIP-магазина')
                self.store.update_profile(instance,lambda p:p.tasks.setdefault('vip_shop',{}).update(item_id=value[1]))
                self.vip_shop_menu(owner,instance)
            elif action == "trainunit":
                if type(value[1]) is not int or value[1] not in (1,2,3,4):
                    raise ValueError("Некорректный тип войск")
                def change(profile):
                    settings = profile.tasks.setdefault("training",{})
                    units = set(settings.get("units",[]))
                    units.discard(value[1]) if value[1] in units else units.add(value[1])
                    settings["units"] = sorted(units)
                self.store.update_profile(instance,change)
                self.training_menu(owner,instance)
            elif action == "matitem":
                if type(value[1]) is not int or value[1] not in MATERIALS:raise ValueError("Неизвестный материал")
                self.store.update_profile(instance,lambda p:p.tasks.setdefault("materials",{}).update(item_id=value[1]))
                self.material_menu(owner,instance)
            elif action == "gatherresource":
                if type(value[1]) is not int or value[1] not in GATHER_RESOURCES:raise ValueError("Ресурс ещё не подтверждён")
                self.store.update_profile(instance,lambda p:p.tasks.setdefault("gather_resources",{}).update(resource=value[1]))
                self.gather_menu(owner,instance)
            elif action == "gathervalue":
                if value[1] not in ("level","max_level","max_travel","max_marches"):raise ValueError("Неизвестный параметр сбора")
                self.pending={"kind":"gather_value","instance":instance,"field":value[1]}
                self._send(owner,"Отправьте максимум времени перехода (1–600 секунд). /cancel — отмена." if value[1]=="max_travel"
                    else "Отправьте общий лимит занятых маршей (1–5). /cancel — отмена." if value[1]=="max_marches"
                    else "Отправьте уровень (1–8). /cancel — отмена.")
            elif action == "trainvalue":
                if value[1] not in ("tier","count"):
                    raise ValueError("Некорректный параметр обучения")
                self.pending = {"kind":"training_value","instance":instance,"field":value[1]}
                self._send(owner,"Отправьте тир (1–5). /cancel — отмена." if value[1] == "tier" else
                           "Отправьте размер партии (1–1000000). /cancel — отмена.")
            elif action == "slottask":
                def change(profile):
                    slot = next((s for s in profile.slots if s.id == value[1]), None)
                    if slot is None:
                        raise ValueError("Слот уже удалён")
                    tasks = tuple(t for t in slot.tasks if t != value[2]) if value[2] in slot.tasks else slot.tasks + (value[2],)
                    profile.slots = [Slot(s.id, s.start, s.end, tasks) if s.id == slot.id else s for s in profile.slots]
                self.store.update_profile(instance, change)
                self.slot_tasks(owner, instance, value[1])
            elif action == "rotmember":
                def change(settings):
                    settings = settings or {"parallel":1,"duration":3600}
                    members = list(settings.get("members", []))
                    members = [member for member in members if member != instance] if instance in members else members + [instance]
                    return {**settings, "members":members}
                self.store.update_preference("rotation", change)
                self.rotation_menu(owner)
            elif action == "preset":
                self.backend.stop(instance)
                self.store.apply_preset(value[1], [instance])
                self._send(owner, "Пресет применён. Для продолжения нажмите «Задачи».")
                self.instance_menu(owner, instance)
            elif action == "interval":
                self.pending = {"kind":"interval", "instance":instance, "task":value[1]}
                self._send(owner, "Отправьте интервал задачи в секундах (1–86400). /cancel — отмена.")
            else:
                def change(profile):
                    settings = profile.tasks.setdefault(value[1], {})
                    settings["enabled"] = not settings.get("enabled", False)
                self.store.update_profile(instance, change)
                self.tasks(owner, instance)
            return
        if action in ("slot", "slottasks", "deleteslot"):
            instance, slot_id = getattr(self, "_slot_map", {}).get(key, (None, None))
            if instance is None:
                raise ValueError("Кнопка устарела: откройте расписание заново")
            profile = self.store.profile(instance)
            slot = next((slot for slot in profile.slots if slot.id == slot_id), None)
            if slot is None:
                raise ValueError("Слот уже удалён: откройте расписание заново")
            if action == "deleteslot":
                self.store.update_profile(instance, lambda current: setattr(current, "slots", [s for s in current.slots if s.id != slot_id]))
                self.schedule(owner, instance)
                return
            if action == "slottasks":
                self.slot_tasks(owner, instance, slot.id)
                return
            self.pending = {"instance": instance, "slot": slot.to_dict() if hasattr(slot,"to_dict") else
                            {"id": slot.id, "start":slot.start,"end":slot.end,"tasks":list(slot.tasks)}, "existing":True}
            self._send(owner, "Отправьте начало и окончание: ЧЧ:ММ ЧЧ:ММ. /cancel — отмена.",
                       keyboard([[("Задачи этого слота", f"slottasks:{key}"), ("Удалить слот", f"deleteslot:{key}")]]))
            return
        if key not in self._instances():
            raise ValueError("Неизвестный эмулятор")
        if action == "instance":
            self.instance_menu(owner, key)
        elif action == "run":
            self._send(owner, self.backend.start(key))
        elif action == "stop":
            self._send(owner, self.backend.stop(key))
        elif action == "screen":
            self.api.call("sendPhoto", {"chat_id":owner,"caption":self._instances()[key].name}, self.backend.screenshot(key))
        elif action == "schedule":
            self.schedule(owner,key)
        elif action == "tasks":
            self.tasks(owner,key)
        elif action == "training":
            self.training_menu(owner,key)
        elif action == "donation":
            self.donation_menu(owner,key)
        elif action == "materials":
            self.material_menu(owner,key)
        elif action == "gather":
            self.gather_menu(owner,key)
        elif action in ('barbarians','barbarianchain'):
            self.barbarian_menu(owner,key,'barbarian_chain' if action=='barbarianchain' else 'barbarians')
        elif action in ('buildpacks','buildprereqs','buildmissing','buildplants'):
            def change(profile):
                settings=profile.tasks.setdefault('buildings',{})
                field={'buildpacks':'use_resource_packs','buildprereqs':'auto_prerequisites',
                    'buildmissing':'create_missing','buildplants':'clear_plants'}[action]
                settings[field]=not getattr(BuildingOptions.from_settings(settings),field)
            self.store.update_profile(key,change);self.building_menu(owner,key)
        elif action == "buildings":
            self.building_menu(owner,key)
        elif action=='research':
            self.research_menu(owner,key)
        elif action in ('researchpacks','researchprereqs'):
            def change(profile):
                settings=profile.tasks.setdefault('research',{})
                field='use_resource_packs' if action=='researchpacks' else 'auto_prerequisites'
                settings[field]=not getattr(ResearchOptions.from_settings(settings),field)
            self.store.update_profile(key,change);self.research_menu(owner,key)
        elif action in ('researchlevel','researchreserves'):
            reserves=action=='researchreserves'
            self.pending={'kind':'research_reserves' if reserves else 'research_value','instance':key,'field':'max_level'}
            self._send(owner,'Отправьте четыре резерва: еда дерево камень золото.' if reserves else 'Отправьте целевой уровень1–10.')
        elif action == "supply":
            self.supply_menu(owner,key)
        elif action == 'caveboxes':
            self.supply_menu(owner,key,'cave_rewards')
        elif action == 'vipshop':
            self.vip_shop_menu(owner,key)
        elif action == 'lucerne':
            self.lucerne_menu(owner,key)
        elif action == 'tutorial':
            self.tutorial_menu(owner,key)
        elif action == 'tutoriallimit':
            self.pending={'kind':'tutorial_limit','instance':key}
            self._send(owner,'Отправьте число действий обучения1–32. /cancel — отмена.')
        elif action == 'lucernelimit':
            self.pending={'kind':'lucerne_limit','instance':key}
            self._send(owner,'Отправьте число получений опыта1–32. /cancel — отмена.')
        elif action in ('vipprice','vipreserve'):
            self.pending={'kind':'vip_shop_value','instance':key,'field':'max_price' if action=='vipprice' else 'reserve'}
            self._send(owner,'Отправьте целое число еды (цена1–2000000000, резерв0–2000000000). /cancel — отмена.')
        elif action in ("supplylimit","cavelimit"):
            self.pending={"kind":"supply_limit","instance":key,'task':'cave_rewards' if action=='cavelimit' else 'supply_boxes'}
            self._send(owner,"Отправьте число ящиков за проверку (1–10). /cancel — отмена.")
        elif action == "buildlevel":
            self.pending={"kind":"building_value","instance":key,"field":"max_level"}
            self._send(owner,"Отправьте целевой уровень каменоломен (1–24). /cancel — отмена.")
        elif action == "buildreserves":
            self.pending={"kind":"building_reserves","instance":key}
            self._send(owner,"Отправьте четыре минимальных остатка: еда дерево камень золото. Каждый 0–2000000000. /cancel — отмена.")
        elif action == "matlimit":
            self.pending={"kind":"material_limit","instance":key}
            self._send(owner,"Отправьте число заказов материалов (1–5). /cancel — отмена.")
        elif action == "donategoal":
            self.pending = {"kind":"donation_goal","instance":key}
            self._send(owner,"Отправьте дневную цель очков (1–100000). /cancel — отмена.")
        elif action == "donatereserves":
            self.pending = {"kind":"donation_reserves","instance":key}
            self._send(owner,"Отправьте четыре минимальных остатка: еда дерево камень золото. "
                "Каждый 0–2000000000. /cancel — отмена.")
        elif action == "trainreserves":
            self.pending = {"kind":"training_reserves","instance":key}
            self._send(owner,"Отправьте четыре минимальных остатка: еда дерево камень золото. "
                "Каждый 0–2000000000. Например: 100000 100000 0 0. /cancel — отмена.")
        elif action == "presets":
            self.presets(owner,key)
        elif action == "savepreset":
            self.pending = {"kind":"preset", "instance":key}
            self._send(owner, "Отправьте название пресета (до 80 символов). /cancel — отмена.")
        elif action == "toggle":
            self.store.update_profile(key, lambda profile: setattr(profile, "schedule_enabled", not profile.schedule_enabled))
            self.schedule(owner,key)
        elif action == "add":
            profile = self.store.profile(key)
            tasks = [task for task,settings in profile.tasks.items() if settings.get("enabled")]
            self.pending = {"instance": key, "slot":{"id":uuid.uuid4().hex,"tasks":tasks}}
            self._send(owner, "Отправьте начало и окончание: ЧЧ:ММ ЧЧ:ММ. Задачи берутся из сохранённого профиля. /cancel — отмена.")
        else:
            raise ValueError("Команда не поддерживается")

    def _text(self, owner, text):
        kind = self.pending.get("kind", "slot")
        if kind=='barbarian_value':
            key=self.pending['instance'];task=self.pending['task'];field=self.pending['field']
            if (key not in self._instances() or task not in ('barbarians','barbarian_chain')
                    or field not in ('level','max_level','reserve_ap','max_battles','min_health')
                    or not re.fullmatch(r'[0-9]{1,7}',text.strip())):raise ValueError('Введите целое значение настройки фарма')
            self.store.update_profile(key,lambda p:p.tasks.setdefault(task,{}).update({field:int(text.strip())}))
            self.pending=None;self.barbarian_menu(owner,key,task);return
        if kind == 'tutorial_limit':
            key=self.pending['instance']
            if key not in self._instances() or not re.fullmatch(r'[0-9]{1,2}',text.strip()):
                raise ValueError('Введите число действий1–32 для существующего экземпляра')
            self.store.update_profile(key,lambda p:p.tasks.setdefault('tutorial',{}).update(max_actions=int(text.strip())))
            self.pending=None;self.tutorial_menu(owner,key);return
        if kind == 'lucerne_limit':
            key=self.pending['instance']
            if key not in self._instances() or not re.fullmatch(r'[0-9]{1,2}',text.strip()):
                raise ValueError('Введите число получений1–32 для существующего экземпляра')
            self.store.update_profile(key,lambda p:p.tasks.setdefault('lucerne',{}).update(max_claims=int(text.strip())))
            self.pending=None;self.lucerne_menu(owner,key);return
        if kind == 'vip_shop_value':
            key=self.pending['instance'];field=self.pending['field']
            if key not in self._instances():raise ValueError('Экземпляр больше не найден')
            if field not in ('max_price','reserve') or not re.fullmatch(r'[0-9]{1,10}',text.strip()):
                raise ValueError('Введите целое значение цены или резерва еды')
            self.store.update_profile(key,lambda p:p.tasks.setdefault('vip_shop',{}).update({field:int(text.strip())}))
            self.pending=None;self.vip_shop_menu(owner,key);return
        if kind == "supply_limit":
            key=self.pending["instance"];task=self.pending.get('task','supply_boxes')
            if task not in ('supply_boxes','cave_rewards'):raise ValueError('Неизвестная настройка ящиков')
            if key not in self._instances():raise ValueError("Экземпляр больше не найден")
            if not re.fullmatch(r"[0-9]{1,2}",text.strip()):raise ValueError("Введите целое число ящиков (1–10)")
            self.store.update_profile(key,lambda p:p.tasks.setdefault(task,{}).update(max_boxes=int(text.strip())))
            self.pending=None
            self.supply_menu(owner,key,task)
            return
        if kind == "gather_value":
            key=self.pending["instance"]
            if key not in self._instances():raise ValueError("Экземпляр больше не найден")
            if not re.fullmatch(r"[0-9]{1,3}",text.strip()):raise ValueError("Введите целое значение параметра сбора")
            field=self.pending["field"]
            if field not in ("level","max_level","max_travel","max_marches"):raise ValueError("Неизвестный параметр сбора")
            self.store.update_profile(key,lambda p:p.tasks.setdefault("gather_resources",{}).update({field:int(text.strip())}))
            self.pending=None
            self.gather_menu(owner,key)
            return
        if kind == "material_limit":
            if not text.strip().isdecimal():raise ValueError("Введите целое число заказов (1–5)")
            key=self.pending["instance"]
            self.store.update_profile(key,lambda p:p.tasks.setdefault("materials",{}).update(max_orders=int(text.strip())))
            self.pending=None
            self.material_menu(owner,key)
            return
        if kind in ("training_value","training_reserves","donation_goal","donation_reserves","building_value","building_reserves",'research_value','research_reserves'):
            key = self.pending["instance"]
            if key not in self._instances():
                raise ValueError("Экземпляр больше не найден")
            pieces = text.split()
            if kind.endswith("reserves"):
                if len(pieces) != 4 or not all(re.fullmatch(r"[0-9]{1,10}",piece) for piece in pieces):
                    raise ValueError("Нужны четыре целых остатка: еда дерево камень золото")
                update = {"reserves":{str(i):int(piece) for i,piece in enumerate(pieces,1)}}
            else:
                if len(pieces) != 1 or not re.fullmatch(r"[0-9]{1,7}",pieces[0]):
                    raise ValueError("Нужно целое число в указанном диапазоне")
                update = {"daily_goal" if kind == "donation_goal" else self.pending["field"]:int(pieces[0])}
            task = ('research' if kind.startswith('research') else "alliance_donate" if kind.startswith("donation")
                else "buildings" if kind.startswith("building") else "training")
            self.store.update_profile(key,lambda profile:profile.tasks.setdefault(task,{}).update(update))
            self.pending = None
            {"alliance_donate":self.donation_menu,"training":self.training_menu,"buildings":self.building_menu,
                'research':self.research_menu}[task](owner,key)
            return
        if kind == "interval":
            if not text.isdecimal() or not 1 <= int(text) <= 86400:
                raise ValueError("Интервал должен быть целым числом от 1 до 86400")
            self.store.update_profile(self.pending["instance"], lambda profile:
                                      profile.tasks.setdefault(self.pending["task"], {}).update(interval=int(text)))
            self.pending = None
            self._send(owner, "Интервал сохранён")
            return
        if kind == "preset":
            self.store.save_preset(text, self.store.profile(self.pending["instance"]))
            self.pending = None
            self._send(owner, "Пресет сохранён")
            return
        if kind == "rotation":
            pieces = text.split()
            if len(pieces) != 2 or not all(piece.isdecimal() for piece in pieces):
                raise ValueError("Нужны два числа: параллельность и минуты")
            parallel, minutes = map(int, pieces)
            if not 1 <= parallel <= 50 or not 1 <= minutes <= 1440:
                raise ValueError("Параллельность 1–50, время 1–1440 минут")
            self.store.update_preference("rotation", lambda settings: {**(settings or {}), "parallel":parallel, "duration":minutes * 60})
            self.pending = None
            self.rotation_menu(owner)
            return
        pieces = text.strip().split()
        if len(pieces) != 2:
            raise ValueError("Нужны два времени: ЧЧ:ММ ЧЧ:ММ")
        draft = self.pending
        value = Slot(draft["slot"]["id"], pieces[0], pieces[1], tuple(draft["slot"]["tasks"]))
        def change(profile):
            if draft.get("existing"):
                original = draft["slot"]
                current = next((s for s in profile.slots if s.id == value.id), None)
                if (current is None or current.start != original["start"] or current.end != original["end"]
                        or current.tasks != tuple(original["tasks"])):
                    raise ValueError("Слот изменён через другое управление; откройте его заново")
            profile.slots = [slot for slot in profile.slots if slot.id != value.id] + [value]
        self.store.update_profile(draft["instance"], change)
        self.pending = None
        self._send(owner, "Слот сохранён.")
        self.schedule(owner,draft["instance"])


class Service:
    def __init__(self, store: Store, backend: Backend, on_status=lambda text: None):
        self.store, self.backend, self.on_status = store, backend, on_status
        self.thread: threading.Thread | None = None
        self.cancelled = threading.Event()
        self.api: Api | None = None
        self.router: Router | None = None
        self.notifications = queue.Queue(maxsize=100)
        self._last_notice: dict[tuple[str,str],float] = {}

    def notify(self, instance: str, message: str, level: str):
        if (not self.thread or not self.thread.is_alive()
                or not self.store.preference("telegram_notifications", True)):
            return
        key = (instance, message)
        now = time.monotonic()
        if now - self._last_notice.get(key, -100) < 60:
            return
        self._last_notice = {k:v for k,v in self._last_notice.items() if now - v < 60}
        self._last_notice[key] = now
        try:
            self.notifications.put_nowait(redact(f"Mirage · {instance}\n{message}"))
        except queue.Full:
            pass

    def _send_notifications(self):
        owner = self.store.preference("telegram_owner")
        for _ in range(5):
            try:
                message = self.notifications.get_nowait()
            except queue.Empty:
                return
            if owner:
                self.api.call("sendMessage", {"chat_id":owner, "text":translate(message, language_for(self.store))[:4096]})

    def save_token(self, token: str):
        Api(token).close()
        previous = self.store.preference("telegram_secret")
        if previous and decrypt(previous) == token:
            return
        self.store.set_preference("telegram_secret", encrypt(token))
        self.store.set_preference(self._offset_key(token), 0)

    @staticmethod
    def _offset_key(token):
        return "telegram_offset:" + hashlib.sha256(token.encode()).hexdigest()[:16]

    def start(self):
        if self.thread and self.thread.is_alive():
            raise TelegramError("Telegram уже запущен")
        secret = self.store.preference("telegram_secret")
        if not secret:
            raise TelegramError("Сначала введите токен @BotFather")
        self.api = Api(decrypt(secret))
        self.router = Router(self.api, self.store, self.backend)
        self.cancelled.clear()
        self.thread = threading.Thread(target=self._poll, name="mirage-telegram", daemon=True)
        self.thread.start()
        return self.router.pair_code

    def _poll(self):
        offset_key = self._offset_key(self.api.token)
        offset = int(self.store.preference(offset_key, self.store.preference("telegram_offset", 0)))
        try:
            me = self.api.call("getMe")
            if self.api.call("getWebhookInfo").get("url"):
                raise TelegramError("У токена уже настроен webhook; используйте отдельного бота Mirage")
            self.on_status(f"Подключён @{me['username']}")
            backoff = 1
            while not self.cancelled.is_set():
                try:
                    updates = self.api.call("getUpdates", {"offset":offset,"timeout":10,"allowed_updates":["message","callback_query"]})
                    self._send_notifications()
                    for update in updates:
                        if self.cancelled.is_set():
                            break
                        if update.get("update_id", -1) < offset:
                            continue
                        self.router.handle(update)
                        offset = update["update_id"] + 1
                        self.store.set_preference(offset_key, offset)
                    backoff = 1
                except TelegramError as error:
                    self.on_status(redact(error))
                    if self.cancelled.wait(backoff):
                        break
                    backoff = min(backoff * 2, 30)
        except Exception as error:
            self.on_status(redact(error))
        finally:
            self.api.close()
            self.on_status("Telegram остановлен")

    def stop(self):
        self.cancelled.set()
