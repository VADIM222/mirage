"""Bounded ordinary side-quest claims with exact per-quest receipts."""
from dataclasses import dataclass, replace

from .supply_boxes import balances, inventory, integer, table
from .workflows import (All, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, HUD_MENU,
    NotReady, Procedure, QUEUE_CLOSE, SELECTION_CLEAR, Tap, Workflow, WorkflowError)


FIELDS={'side_quests':['@side_quests'],'supply_inventory':['@item_counts']}


class SideAvailable:
    def matches(self,state):
        s=state.values.get('side_quests')
        return table(s) and s.get('ready') is True and integer(s.get('available'),1)


class MainPanel:
    def matches(self,state):
        return (state.values.get('quest_visible') is True and state.values.get('quest_tab')==1
            and state.values.get('reward_popup_visible') is False
            and set(state.values.get('views',{}))<=set(CITY_VIEWS+('QuestSystemMainPage','CommonBackground')))


MAIN=MainPanel()


@dataclass(frozen=True)
class SideReceipt:
    ids: frozenset
    completed: int
    money: dict
    items: dict
    remaining: frozenset

    @classmethod
    def capture(cls,state):
        s=state.values.get('side_quests');rows=s.get('display') if table(s) else None
        if (not MAIN.matches(state) or not SideAvailable().matches(state) or not table(rows)
                or not integer(s.get('completed')) or not table(s.get('rows'))):
            raise NotReady('Задания: обычный список побочных наград не подтверждён')
        if (rows.get('1',{}).get('param',{}).get('text')!='LC_COMMON_MAIN_MISSION'
                or rows.get('3',{}).get('param',{}).get('text')!='LC_COMMON_NORMAL_MISSION'
                or rows.get('2',{}).get('param',{}).get('questType')!=1
                or rows.get('2',{}).get('param',{}).get('Stat')==2
                or rows.get('4',{}).get('param',{}).get('Stat')!=2):
            raise NotReady('Задания: положение первой побочной награды не проверено')
        ids=set()
        for row in rows.values():
            if not table(row):raise NotReady('Задания: список неполон')
            quest=row.get('param')
            if row.get('type')!=1 or not table(quest) or quest.get('Stat')!=2:continue
            if quest.get('questType')!=2 or not integer(quest.get('Id'),1) or quest['Id'] in ids:
                raise NotReady('Задания: пакет содержит неподдержанную награду')
            ids.add(quest['Id'])
        if not 1<=len(ids)<=32 or set(map(str,ids))!=set(s['rows']):
            raise NotReady('Задания: отображаемый пакет не совпадает с готовыми заданиями')
        if s.get('available')!=len(ids) or s['completed']!=len(ids):
            raise NotReady('Задания: счётчик готовых наград не совпадает со списком')
        first=rows['4']['param']
        if first.get('questType')!=2 or first.get('Id') not in ids:
            raise NotReady('Задания: первая награда не является побочной')
        remaining=ids-{first['Id']};ids={first['Id']}
        money=balances(state);items=inventory(state)
        for id in ids:
            row=s['rows'][str(id)];cfg=row.get('config') if table(row) else None;loot=row.get('loot') if table(row) else None
            if (not table(cfg) or cfg.get('ID')!=id or not integer(cfg.get('RewardID'),1)
                    or not table(loot) or not loot):raise NotReady('Задания: конфигурация или награда не прочитаны')
            for prize in loot.values():
                if (not table(prize) or prize.get('ID')!=cfg['RewardID'] or prize.get('Type') not in (1,2)
                        or type(prize.get('Type')) is not int or not integer(prize.get('SubType'),1)
                        or not integer(prize.get('Value'),1) or prize['Type']==1 and prize['SubType'] not in range(1,7)):
                    raise NotReady('Задания: неизвестный состав награды')
                target=money if prize['Type']==1 else items;key=str(prize['SubType'])
                target[key]=target.get(key,0)+prize['Value']
        return cls(frozenset(ids),s['completed'],money,items,frozenset(remaining))

    def matches(self,state):
        s=state.values.get('side_quests')
        return (table(s) and s.get('ready') is True and s.get('completed')==self.completed-1
            and s.get('available')==len(self.remaining) and table(s.get('statuses'))
            and s['statuses']=={str(id):2 for id in self.remaining}
            and balances(state)==self.money and inventory(state)==self.items)


@dataclass(frozen=True)
class CollectSideQuests:
    def __call__(self,device,observe,cancelled,clock,allowed):
        initial=observe();s=initial.values.get('side_quests')
        if not SideAvailable().matches(initial):return initial
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Получение заданий отменено')
        def execute(steps):
            return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
                Workflow('side_quest_transition','1.1.12.20',960,540,steps,verified=True,data_timeout=10),cancelled,
                instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        if initial.values.get('quest_visible') is not True:
            if s.get('entryY') not in (155,178):raise NotReady('Задания: кнопка списка ещё не открыта обучением')
            execute((QUEUE_CLOSE,*SELECTION_CLEAR,
                Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,when=Condition(('hud_menu',),'eq',True),settle=.3),
                Tap(30,s['entryY'],CITY_HUD,Condition(('quest_visible',),'eq',True),hold_ms=100,settle=.4)))
        state=execute((Tap(77,130,Condition(('quest_visible',),'eq',True),MAIN,hold_ms=100,settle=.3),))
        for _ in range(8):
            if not SideAvailable().matches(state):break
            receipt=SideReceipt.capture(state);permit();device.tap(755,299,hold_ms=100)
            deadline=clock()+20
            while True:
                permit();state=observe()
                if receipt.matches(state) and MAIN.matches(state):break
                if clock()>=deadline:raise WorkflowError('Задания: точная выдача не подтверждена; повтор запрещён')
                if cancelled.wait(.1):raise Cancelled('Получение заданий отменено')
        return execute((Tap(818,62,MAIN,CITY_HUD,hold_ms=100,settle=.3),))


def side_workflow():
    return Workflow('quests','1.1.12.20',960,540,(Procedure(CollectSideQuests()),),verified=True,
        extra_paths=FIELDS,data_timeout=10)


@dataclass(frozen=True)
class OpenQuestList:
    def __call__(self,device,observe,cancelled,clock,allowed):
        state=observe()
        if state.values.get('quest_visible') is True:return state
        s=state.values.get('side_quests');y=s.get('entryY') if table(s) else None
        if y not in (155,178):raise NotReady('Задания: положение кнопки списка не подтверждено')
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('open_quest_list','1.1.12.20',960,540,
                (Tap(30,y,CITY_HUD,Condition(('quest_visible',),'eq',True),hold_ms=100,settle=.4),),
                verified=True),cancelled,instance_id=state.instance_id,pid=state.pid,player_id=state.player_id)


@dataclass(frozen=True)
class QuestCycle:
    def __call__(self,device,observe,cancelled,clock,allowed):
        from .workflows import DAILY_REWARD
        initial=observe()
        engine=Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed)
        for flow in (side_workflow(),replace(DAILY_REWARD,steps=tuple(
                Procedure(OpenQuestList()) if isinstance(step,Tap) and (step.x,step.y)==(30,155) else step
                for step in DAILY_REWARD.steps))):
            engine.execute(flow,cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        return observe()


def quest_workflow(settings=None):
    return Workflow('quests','1.1.12.20',960,540,(Procedure(QuestCycle()),),verified=True,
        extra_paths=FIELDS,data_timeout=10)
