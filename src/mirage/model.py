from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import math
import re
from typing import Any


MIN_CPUS = 2
MIN_MEMORY_MB = 2048


class Provider(StrEnum):
    BLUESTACKS = "bluestacks"
    LDPLAYER = "ldplayer"


class Power(StrEnum):
    OFF = "off"
    BOOTING = "booting"
    ONLINE = "online"
    UNKNOWN = "unknown"


class RunState(StrEnum):
    STOPPED = "stopped"
    WAIT_EMULATOR = "wait_emulator"
    WAIT_SLOT = "wait_slot"
    WAIT_ADAPTER = "wait_adapter"
    WAIT_GAME = "wait_game"
    PAUSED = "paused"
    RUNNING = "running"
    ERROR = "error"


@dataclass(frozen=True)
class Instance:
    id: str
    provider: Provider
    key: str
    name: str
    install_dir: str
    adb_path: str
    serial: str
    power: Power = Power.UNKNOWN
    cpus: int = 0
    memory_mb: int = 0
    width: int = 0
    height: int = 0
    dpi: int = 0


TASKS: dict[str, tuple[str, str]] = {
    "alliance_help": ("Помощь альянсу", "Альянс"),
    "gather_resources": ("Сбор ресурсов", "Фарм"),
    "gather_gems": ("Сбор гемов", "Фарм"),
    "barbarians": ("Варвары", "Бой"),
    "barbarian_chain": ("Фарм варваров цепочкой", "Бой"),
    "marauders": ("Мародёры", "Бой"),
    "join_rally": ("Присоединение к ралли", "Бой"),
    "create_rally": ("Создание ралли", "Бой"),
    "buildings": ("Улучшение зданий", "Город"),
    "research": ("Исследования", "Город"),
    "training_collect": ("Получение готовых войск", "Город"),
    "training": ("Обучение войск", "Город"),
    "healing": ("Лечение войск", "Город"),
    "materials": ("Производство материалов", "Город"),
    "city_resources": ("Сбор ресурсов в городе", "Город"),
    "scout_fog": ("Разведка тумана", "Разведка"),
    "caves": ("Пещеры", "Разведка"),
    "villages": ("Деревни", "Разведка"),
    "alliance_donate": ("Пожертвования альянсу", "Альянс"),
    "alliance_gifts": ("Подарки альянса", "Альянс"),
    "alliance_resources": ("Ресурсы территории", "Альянс"),
    "alliance_flags": ("Строительство флагов", "Альянс"),
    "quests": ("Ежедневные задания", "Награды"),
    "event_rewards": ("Награды событий", "Награды"),
    "vip_reward": ("Ежедневный VIP", "Награды"),
    "expedition": ("Награды экспедиции", "Награды"),
    "lucerne": ("Люцернские свитки", "Награды"),
    "mail": ("Почта", "Награды"),
    "tavern": ("Бесплатные сундуки таверны", "Награды"),
    "cave_rewards": ("Сундуки пещер", "Награды"),
    "supply_boxes": ("Ящики снабжения", "Предметы"),
    "vip_points": ("Использование VIP-очков", "Предметы"),
    "production_boost": ("Усиление производства", "Предметы"),
    "courier": ("Таинственная торговка", "Экономика"),
    "vip_shop": ("VIP-магазин", "Экономика"),
    "transport": ("Передача ресурсов", "Экономика"),
    "crystal_production": ("Производство кристаллов", "KvK"),
    "crystal_research": ("Кристальные исследования", "KvK"),
    "shield": ("Автощит", "Защита"),
    "repair_wall": ("Ремонт стены", "Защита"),
    "fill_pass": ("Заполнение прохода", "Бой"),
    "hero_chat": ("Общение с героем", "Город"),
    "switch_character": ("Смена персонажа", "Аккаунт"),
    "tutorial": ("Обучение новичка", "Аккаунт"),
}


def minute(value: str, *, end: bool = False) -> int:
    if end and value == "24:00":
        return 1440
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError(f"Некорректное время: {value}")
    hours, minutes = map(int, value.split(":"))
    return hours * 60 + minutes


@dataclass(frozen=True)
class Slot:
    id: str
    start: str
    end: str
    tasks: tuple[str, ...] = ()

    def __post_init__(self):
        start = minute(self.start)
        end = minute(self.end, end=True)
        if start == end:
            raise ValueError("Начало и конец совпадают; полный день задаётся 00:00–24:00")
        if len(set(self.tasks)) != len(self.tasks) or any(task not in TASKS for task in self.tasks):
            raise ValueError("Некорректный набор задач слота")
        if not self.id:
            raise ValueError("Отсутствует ID слота")

    def intervals(self) -> tuple[tuple[int, int], ...]:
        start, end = minute(self.start), minute(self.end, end=True)
        return ((start, end),) if start < end else ((start, 1440), (0, end))

    def contains(self, value: int) -> bool:
        return any(start <= value < end for start, end in self.intervals())


def validate_slots(slots: list[Slot]) -> None:
    ids = [slot.id for slot in slots]
    if len(set(ids)) != len(ids):
        raise ValueError("ID слотов должны быть уникальными")
    for index, left in enumerate(slots):
        for right in slots[index + 1:]:
            if any(max(a, c) < min(b, d)
                   for a, b in left.intervals() for c, d in right.intervals()):
                raise ValueError(f"Слоты {left.start}–{left.end} и {right.start}–{right.end} пересекаются")


def reserves_from_settings(settings: dict) -> tuple[int, ...]:
    reserves = settings.get("reserves", {})
    if (not isinstance(reserves, dict) or set(reserves)-{"1","2","3","4"}
            or any(type(value) is not int or not 0 <= value <= 2000000000 for value in reserves.values())):
        raise ValueError("Резерв каждого ресурса должен быть от 0 до 2 000 000 000")
    return tuple(reserves.get(str(i),0) for i in range(1,5))


@dataclass(frozen=True)
class TrainingOptions:
    units: tuple[int, ...] = ()
    tier: int = 1
    count: int = 1000
    reserves: tuple[int, ...] = (0, 0, 0, 0)

    @classmethod
    def from_settings(cls, settings: dict) -> TrainingOptions:
        units = settings.get("units", [])
        tier, count = settings.get("tier", 1), settings.get("count", 1000)
        if (not isinstance(units, (list, tuple)) or any(type(unit) is not int or unit not in (1,2,3,4) for unit in units)
                or len(set(units)) != len(units)):
            raise ValueError("Выберите типы обучаемых войск")
        if type(tier) is not int or not 1 <= tier <= 5:
            raise ValueError("Тир обучения должен быть от 1 до 5")
        if type(count) is not int or not 1 <= count <= 1000000:
            raise ValueError("Размер партии обучения должен быть от 1 до 1 000 000")
        return cls(tuple(sorted(units)), tier, count, reserves_from_settings(settings))


@dataclass(frozen=True)
class MaterialOptions:
    item_id: int = 412
    max_orders: int = 5

    @classmethod
    def from_settings(cls, settings: dict) -> MaterialOptions:
        item,limit = settings.get("item_id",412),settings.get("max_orders",5)
        if type(item) is not int or item not in MATERIALS:
            raise ValueError("Выберите материал: кожа, железная руда, эбеновое дерево или кость")
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError("Число заказов материалов должно быть от 1 до 5")
        return cls(item,limit)


MATERIALS = {412:"Кожа",413:"Железная руда",417:"Эбеновое дерево",414:"Кость"}

# Only resources with confirmed dispatch, natural collection and healthy return.
GATHER_RESOURCES = {1:"Еда",2:"Дерево",3:"Камень",4:"Золото"}


@dataclass(frozen=True)
class SupplyBoxOptions:
    max_boxes: int = 1

    @classmethod
    def from_settings(cls,settings):
        value=settings.get('max_boxes',1)
        if type(value) is not int or not 1<=value<=10:
            raise ValueError('За проверку можно открыть от 1 до 10 ящиков снабжения')
        return cls(value)


@dataclass(frozen=True)
class BarbarianOptions:
    primary: int = 3
    level: int = 1
    max_level: int = 1
    reserve_ap: int = 100
    max_battles: int = 3
    min_health: int = 50
    deputy: int = 0

    @property
    def heroes(self):
        return {'1':self.primary,**({'2':self.deputy} if self.deputy else {})}

    @classmethod
    def from_settings(cls,settings):
        values={key:settings.get(key,default) for key,default in
            (('primary',3),('level',1),('max_level',settings.get('level',1)),('reserve_ap',100),('max_battles',3),('min_health',50),('deputy',0))}
        limits={'primary':(1,1000000),'deputy':(0,1000000),'level':(1,25),'max_level':(1,25),'reserve_ap':(0,10000),'max_battles':(1,100),'min_health':(1,100)}
        for key,value in values.items():
            low,high=limits[key]
            if type(value) is not int or not low<=value<=high:raise ValueError('Некорректная настройка фарма: '+key)
        if values['level']>values['max_level']:raise ValueError('Максимальный уровень целей ниже уровня поиска')
        if values['primary']==values['deputy']:raise ValueError('Основной и второй командиры должны различаться')
        return cls(**values)


VIP_SHOP_ITEMS={124:'Восстановление100 AP',58:'Ускорение5 минут (покупка)',8011:'Сундук материалов',9998:'Новая звёздная скульптура'}


@dataclass(frozen=True)
class TutorialOptions:
    max_actions: int = 8

    @classmethod
    def from_settings(cls,settings):
        value=settings.get('max_actions',8)
        if type(value) is not int or not 1<=value<=32:raise ValueError('Обучение:1–32 действия за проверку')
        return cls(value)


@dataclass(frozen=True)
class LucerneOptions:
    max_claims: int = 32

    @classmethod
    def from_settings(cls,settings):
        value=settings.get('max_claims',32)
        if type(value) is not int or not 1<=value<=32:raise ValueError('Свитки: от1 до32 получений за проверку')
        return cls(value)


@dataclass(frozen=True)
class VipShopOptions:
    item_id: int = 124
    max_price: int = 12000
    reserve: int = 0

    @classmethod
    def from_settings(cls,settings):
        item=settings.get('item_id',124);price=settings.get('max_price',12000);reserve=settings.get('reserve',0)
        if type(item) is not int or item not in VIP_SHOP_ITEMS:raise ValueError('Выберите проверенный товар VIP-магазина')
        if type(price) is not int or not 1<=price<=2000000000:raise ValueError('Максимальная цена: 1–2000000000 еды')
        if type(reserve) is not int or not 0<=reserve<=2000000000:raise ValueError('Резерв еды: 0–2000000000')
        return cls(item,price,reserve)


@dataclass(frozen=True)
class BuildingOptions:
    max_level: int = 20
    reserves: tuple[int, ...] = (0,0,0,0)
    types: tuple[int, ...] = (4,)
    use_resource_packs: bool = False
    auto_prerequisites: bool = False
    create_missing: bool = False
    clear_plants: bool = False

    @classmethod
    def from_settings(cls,settings):
        level=settings.get('max_level',20)
        if type(level) is not int or not 1<=level<=24:
            raise ValueError('Целевой уровень зданий должен быть от 1 до 24')
        types=settings.get('types',[4])
        if (not isinstance(types,(list,tuple)) or any(type(kind) is not int or kind not in BUILDING_TYPES for kind in types)
                or len(set(types))!=len(types)):raise ValueError('Выберите типы обычных зданий без повторов')
        packs=settings.get('use_resource_packs',False)
        if type(packs) is not bool:raise ValueError('Пополнение ресурсами из сумки должно быть флажком')
        prerequisites=settings.get('auto_prerequisites',False)
        if type(prerequisites) is not bool:raise ValueError('Цепочки предпосылок должны быть флажком')
        create=settings.get('create_missing',False)
        if type(create) is not bool:raise ValueError('Постройка отсутствующих зданий должна быть флажком')
        plants=settings.get('clear_plants',False)
        if type(plants) is not bool:raise ValueError('Уборка растений должна быть флажком')
        return cls(level,reserves_from_settings(settings),tuple(types),packs,prerequisites,create,plants)


BUILDING_TYPES={1:'Ратуша',2:'Ферма',3:'Лесопилка',4:'Каменоломня',5:'Золотой рудник',6:'Стена',7:'Хижина строителя',
    8:'Сторожевая башня',9:'Казармы',10:'Конюшня',11:'Стрельбище',12:'Осадная мастерская',
    13:'Академия',14:'Госпиталь',15:'Склад',16:'Центр альянса',17:'Замок',18:'Таверна',
    19:'Торговый пост',20:'Магазин',21:'Курьерская станция',28:'Разведлагерь',30:'Монумент',31:'Кузница'}


@dataclass(frozen=True)
class ResearchOptions:
    types: tuple[int, ...] = ()
    max_level: int = 10
    reserves: tuple[int, ...] = (0,0,0,0)
    use_resource_packs: bool = False
    auto_prerequisites: bool = False
    priority_mode: str = 'legacy'
    priority_orders: tuple[tuple[int, ...], ...] = ()
    next_branch: str = 'economy'

    def order_for(self,mode):
        if mode not in RESEARCH_MODES:raise ValueError('Неизвестный режим исследований')
        if self.priority_orders:return self.priority_orders[tuple(RESEARCH_MODES).index(mode)]
        order=research_default_order(mode)
        if mode=='custom' and self.priority_mode=='legacy':
            return tuple(k for k in self.types if k in RESEARCH_TYPES)+tuple(k for k in order if k not in self.types)
        return order

    def ordered_types(self):
        if self.priority_mode=='legacy':return self.types
        order=self.order_for(self.priority_mode)
        if self.priority_mode!='balanced':return order
        economy=self.next_branch=='economy'
        return tuple(k for k in order if (k<200)==economy)+tuple(k for k in order if (k<200)!=economy)

    @classmethod
    def from_settings(cls,settings):
        types=settings.get('types',[]);level=settings.get('max_level',10)
        if (not isinstance(types,(list,tuple)) or len(types)>128
                or any(type(kind) is not int or not 1<=kind<=9999 for kind in types)
                or len(set(types))!=len(types)):raise ValueError('Выберите до128 разных обычных технологий')
        if type(level) is not int or not 1<=level<=10:raise ValueError('Уровень исследований должен быть от1 до10')
        packs=settings.get('use_resource_packs',False)
        if type(packs) is not bool:raise ValueError('Пополнение ресурсами из сумки должно быть флажком')
        mode=settings.get('priority_mode','custom' if types else 'economy')
        if mode not in RESEARCH_MODES:raise ValueError('Выберите режим исследований')
        raw_orders=settings.get('priority_orders',{})
        if not isinstance(raw_orders,dict) or set(raw_orders)-set(RESEARCH_MODES):
            raise ValueError('Неизвестная таблица приоритетов исследований')
        orders=[]
        for name in RESEARCH_MODES:
            expected=research_default_order(name);order=raw_orders.get(name,expected)
            if (not isinstance(order,(list,tuple)) or any(type(k) is not int for k in order)
                    or len(order)!=len(expected) or set(order)!=set(expected)):
                raise ValueError('Таблица приоритетов должна содержать все технологии своей ветки без повторов')
            if name=='custom' and name not in raw_orders and 'priority_mode' not in settings:
                order=tuple(k for k in types if k in expected)+tuple(k for k in expected if k not in types)
            orders.append(tuple(order))
        next_branch=settings.get('next_branch','economy')
        if next_branch not in ('economy','military'):raise ValueError('Неизвестная следующая ветка исследований')
        types=orders[tuple(RESEARCH_MODES).index(mode)]
        prerequisites=settings.get('auto_prerequisites',True)
        if type(prerequisites) is not bool:raise ValueError('Предпосылки исследований должны быть флажком')
        return cls(tuple(types),level,reserves_from_settings(settings),packs,prerequisites,mode,tuple(orders),next_branch)


RESEARCH_TYPES={101:'Добыча камня',102:'Ирригация',103:'Ручная пила',104:'Серп',105:'Каменная кладка',106:'Топор'}
RESEARCH_TYPES.update(dict(enumerate((
    'Металлургия','Зубило','Работа с металлом','Письменность','Ручная тележка','Разработка приисков',
    'Прочная кладка','Колесо','Ювелирное дело','Плуг','Лесопилка','Коса','Маховая пила',
    'Инженерное дело','Математика','Открытая разработка','Чеканка','Пила по камню','Разработка шахт',
    'Механизмы','Повозка','Резьба и обработка'),107)))
RESEARCH_TYPES.update(dict(enumerate((
    'Военная дисциплина','Работа по железу','Улучшенное оперение','Разведение лошадей','Огненные снаряды',
    'T2 Пехота','T2 Лучники','T2 Кавалерия','T2 Баллисты','Выслеживание','Поиск пути',
    'Лёгкий щит','Кожаная броня','Кольчуга','Улучшенная ось','T3 Пехота','T3 Лучники','T3 Кавалерия',
    'T3 Баллисты','Маскировка','Боевая тактика','Защитный строй','Народные средства','Картография',
    'T4 Пехота','T4 Лучники','T4 Кавалерия','T4 Баллисты','Булатная сталь','Бронебойный наконечник',
    'Стремена','Баллистика','Щит скутум','Щит павеза','Латная броня','Прочная рама','Медицинские отряды',
    'Комбинированное оружие','Лагерь','T5 Пехота','T5 Лучники','T5 Кавалерия','T5 Баллисты'),201)))

RESEARCH_MODES={'economy':'Приоритет: экономика','military':'Приоритет: военные',
    'balanced':'50/50','custom':'Кастом'}


def research_default_order(mode):
    economy=tuple(k for k in RESEARCH_TYPES if k<200);military=tuple(k for k in RESEARCH_TYPES if k>=200)
    if mode=='economy':return economy
    if mode=='military':return military
    if mode=='balanced':
        return tuple(k for i in range(max(len(economy),len(military)))
            for branch in (economy,military) if i<len(branch) for k in (branch[i],))
    if mode=='custom':return economy+military
    raise ValueError('Неизвестный режим исследований')


@dataclass(frozen=True)
class GatherOptions:
    resource: int = 1
    level: int = 1
    max_level: int = 8
    max_marches: int = 1
    max_travel: int = 180
    primary: int = 0
    deputy: int = 0

    @classmethod
    def from_settings(cls,settings):
        values={key:settings.get(key,default) for key,default in (
            ('resource',1),('level',1),('max_level',8),('max_marches',1),('max_travel',180),('primary',0),('deputy',0))}
        for key,low,high in (('resource',1,4),('level',1,8),('max_level',1,8),
                            ('max_marches',1,5),('max_travel',1,600),('primary',0,100000),('deputy',0,100000)):
            if type(values[key]) is not int or not low<=values[key]<=high:
                raise ValueError('Некорректный параметр сбора: '+key)
        if values['level']>values['max_level']:raise ValueError('Минимальный уровень сбора выше максимального')
        if values['primary'] and values['primary']==values['deputy']:raise ValueError('Командиры должны различаться')
        return cls(**values)


@dataclass(frozen=True)
class DonationOptions:
    daily_goal: int = 100
    reserves: tuple[int, ...] = (0, 0, 0, 0)

    @classmethod
    def from_settings(cls, settings: dict) -> DonationOptions:
        goal = settings.get("daily_goal", 100)
        if type(goal) is not int or not 1 <= goal <= 100000:
            raise ValueError("Дневная цель пожертвований должна быть от 1 до 100 000 очков")
        return cls(goal, reserves_from_settings(settings))


@dataclass
class Profile:
    instance_id: str
    account_name: str = ""
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    schedule_enabled: bool = False
    slots: list[Slot] = field(default_factory=list)
    manual_pause: bool = False
    manual_run: bool = False

    def validate(self):
        if not self.instance_id:
            raise ValueError("Не указан эмулятор")
        if not isinstance(self.account_name, str):
            raise ValueError("Имя аккаунта должно быть строкой")
        if any(not isinstance(getattr(self, field), bool) for field in
               ("schedule_enabled", "manual_pause", "manual_run")):
            raise ValueError("Переключатели профиля должны быть логическими значениями")
        validate_slots(self.slots)
        for task, settings in self.tasks.items():
            if task not in TASKS or not isinstance(settings, dict):
                raise ValueError(f"Неизвестная задача: {task}")
            if "enabled" in settings and not isinstance(settings["enabled"], bool):
                raise ValueError("Переключатель задачи должен быть логическим значением")
            interval = settings.get("interval", 60)
            if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval < 1:
                raise ValueError("Интервал задачи должен быть конечным числом не меньше секунды")
            if task == "training":
                TrainingOptions.from_settings(settings)
            if task == "alliance_donate":
                DonationOptions.from_settings(settings)
            if task == "materials":
                MaterialOptions.from_settings(settings)
            if task == "gather_resources":
                GatherOptions.from_settings(settings)
            if task in ('barbarians','barbarian_chain'):
                BarbarianOptions.from_settings(settings)
            if task == "buildings":
                BuildingOptions.from_settings(settings)
            if task == 'research':
                ResearchOptions.from_settings(settings)
            if task in ("supply_boxes","cave_rewards"):
                SupplyBoxOptions.from_settings(settings)
            if task == "vip_shop":
                VipShopOptions.from_settings(settings)
            if task == "lucerne":
                LucerneOptions.from_settings(settings)
            if task == 'tutorial':
                TutorialOptions.from_settings(settings)

    def to_dict(self) -> dict:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict) -> Profile:
        if not isinstance(value, dict):
            raise ValueError("Профиль должен быть объектом")
        allowed = set(cls.__dataclass_fields__)
        if set(value) - allowed:
            raise ValueError("Профиль содержит неизвестные поля")
        data = dict(value)
        data["slots"] = [Slot(id=slot["id"], start=slot["start"], end=slot["end"],
                              tasks=tuple(slot.get("tasks", ()))) for slot in data.get("slots", [])]
        profile = cls(**data)
        profile.validate()
        return profile


@dataclass(frozen=True)
class Snapshot:
    instance_id: str
    pid: int
    player_id: int
    captured_at: float
    game_version: str
    values: dict[str, Any]

    def fresh(self, now: float, max_age: float = 10) -> bool:
        age = now - self.captured_at
        return self.pid > 0 and self.player_id > 0 and 0 <= age <= max_age
