"""Free Lucerne experience: native mission scores, live tab captures and exact receipts."""
from copy import deepcopy
from dataclasses import dataclass

from .model import LucerneOptions
from .supply_boxes import balances, integer, inventory, table
from .workflows import (All, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, NavigateCity,
    NotReady, Procedure, SELECTION_CLEAR, Tap, Workflow, WorkflowError)


FIELDS={'lucerne':['@lucerne'],'supply_inventory':['@item_counts'],
    'lucerne_levelup':['@active_view','battlePassPopWindow_LevelUp'],
    'city_camera':['@city_camera'],'building_menu':['@building_menu']}
PANEL=All((Condition(('lucerne','visible'),'eq',True),Condition(('in_city',),'eq',True),
    Condition(('city_enabled',),'eq',True),Condition(('views',),'subset',CITY_VIEWS+('BattlePassMain','CommonBackground'))))
LEVELUP=All((Condition(('lucerne_levelup',),'eq',True),Condition(('lucerne','visible'),'eq',True),
    Condition(('views',),'subset',CITY_VIEWS+('BattlePassMain','CommonBackground','battlePassPopWindow_LevelUp'))))
REWARD=All((Condition(('lucerne','rewardVisible'),'eq',True),Condition(('lucerne','visible'),'eq',True),
    Condition(('views',),'subset',CITY_VIEWS+('BattlePassMain','CommonBackground','battlePassPopWindow_Reward'))))


def data(state):
    d=state.values.get('lucerne');now=state.values.get('server_time')
    if (not table(d) or d.get('ready') is not True or d.get('pay')!=1 or type(d.get('pay')) is not int
            or not table(d.get('time')) or not integer(d['time'].get('SeasonId'),1)
            or not integer(d['time'].get('EndTime'),1) or type(now) not in (int,float)
            or d['time']['EndTime']<=now+30000 or d.get('levelExp')!=100 or d.get('dailyExp')!=50
            or type(d.get('daily')) is not int or d['daily'] not in (0,1,2)
            or not table(d.get('level')) or not integer(d['level'].get('Level'),1)
            or d['level']['Level']>50 or not integer(d['level'].get('Exp')) or d['level']['Exp']>=100
            or not table(d.get('weeks')) or not table(d.get('season')) or not table(d.get('rewards'))):
        raise NotReady('Свитки: не подтверждены бесплатный пропуск, сезон или опыт')
    for group in (*d['weeks'].values(),d['season']):
        if not table(group):raise NotReady('Свитки: неполные испытания')
        ids=set()
        for row in group.values():
            if (not table(row) or not integer(row.get('id'),1) or row['id'] in ids
                    or type(row.get('status')) is not int or row['status'] < -2
                    or not integer(row.get('score'),1) or row.get('extra') is not False):
                raise NotReady('Свитки: неизвестное испытание или дополнительный платный опыт')
            ids.add(row['id'])
    for row in d['rewards'].values():
        if (not table(row) or not integer(row.get('level'),1)
                or any(type(row.get(k)) not in (bool,type(None)) for k in ('free','paid'))):
            raise NotReady('Свитки: неполные флаги призов')
    return d


def total_exp(d):return (d['level']['Level']-1)*d['levelExp']+d['level']['Exp']


def free_due(d):
    return [r for r in d['rewards'].values() if table(r) and integer(r.get('level'),1)
        and r['level']<=d['level']['Level'] and r.get('free') is not True]


@dataclass(frozen=True)
class FreeRewardReceipt:
    before: dict
    items: dict
    money: dict
    levels: tuple

    @classmethod
    def capture(cls,state):
        d=data(state);items=inventory(state);money=balances(state);rows=free_due(d)
        if not PANEL.matches(state) or d.get('tab')!=1 or d.get('newSeason') is not False or not rows:
            raise NotReady('Свитки: вкладка бесплатных призов не подтверждена')
        for row in rows:
            loot=row.get('loot')
            if (row.get('free') not in (False,None) or not table(loot) or type(loot.get('Type')) is not int
                    or loot['Type'] not in (1,2) or not integer(loot.get('SubType'),1) or not integer(loot.get('Value'),1)):
                raise NotReady('Свитки: неизвестный бесплатный приз')
            key=str(loot['SubType'])
            if loot['Type']==1:
                if key not in money:raise NotReady('Свитки: неизвестная валюта приза')
                money[key]+=loot['Value']
            else:items[key]=items.get(key,0)+loot['Value']
        return cls(deepcopy(d),items,money,tuple(r['level'] for r in rows))

    def matches(self,state):
        try:d=data(state);items=inventory(state);money=balances(state)
        except NotReady:return False
        if d['time']!=self.before['time'] or total_exp(d)!=total_exp(self.before) or items!=self.items or money!=self.money:
            return False
        for key,row in self.before['rewards'].items():
            current=d['rewards'].get(key)
            if (not table(current) or (current.get('paid') is True)!=(row.get('paid') is True)
                    or current.get('free')!=(True if row['level'] in self.levels else row.get('free'))):return False
        return True


def check_reward_window(state):
    d=data(state);rows=d.get('rewardRows');items=inventory(state);money=balances(state)
    if not REWARD.matches(state) or not table(rows) or not rows:raise NotReady('Свитки: окно призов не подтверждено')
    available=[]
    for row in d['rewards'].values():
        loot=row.get('loot')
        if row.get('free') is True and table(loot):available.append((loot.get('Type'),loot.get('SubType'),loot.get('Value')))
    received={}
    for row in rows.values():
        if not table(row) or any(not integer(row.get(k),1) for k in ('Type','SubType','Value')):
            raise NotReady('Свитки: неизвестная строка приза')
        token=(row['Type'],row['SubType'],row['Value'])
        if token not in available:raise NotReady('Свитки: приз не относится к полученной бесплатной дорожке')
        available.remove(token)
        key=(row['Type'],str(row['SubType']));received[key]=received.get(key,0)+row['Value']
    if any(kind not in (1,2) or (money if kind==1 else items).get(key,0)<count for (kind,key),count in received.items()):
        raise NotReady('Свитки: полученные активы не подтверждены')


@dataclass(frozen=True)
class ExperienceReceipt:
    before: dict
    items: dict
    money: dict
    week: str | None
    task: int | None
    score: int

    @classmethod
    def capture(cls,state,week=None,*,daily=False):
        d=data(state)
        if (not PANEL.matches(state) or d.get('newSeason') is not False or d.get('tab')!=2):
            raise NotReady('Свитки: вкладка испытаний не подтверждена')
        if daily:
            if d['daily']!=1 or state.values.get('daily_score',0)<50:raise NotReady('Свитки: ежедневный опыт недоступен')
            return cls(deepcopy(d),inventory(state),balances(state),None,None,d['dailyExp'])
        kind=1 if week is not None else 2
        if d.get('missionTab')!=kind or week is not None and d.get('week')!=int(week):
            raise NotReady('Свитки: вкладка испытаний или неделя изменились')
        rows=d['season'] if week is None else d['weeks'].get(week,{})
        row=rows.get('1')
        if not table(row) or row.get('status')!=-1:raise NotReady('Свитки: первое испытание не готово')
        return cls(deepcopy(d),inventory(state),balances(state),week,row['id'],row['score'])

    def matches(self,state):
        try:d=data(state);items=inventory(state);money=balances(state)
        except NotReady:return False
        if (d['time']!=self.before['time'] or total_exp(d)!=total_exp(self.before)+self.score
                or items!=self.items or money!=self.money):return False
        if self.task is None:return d['daily']==2
        rows=d['season'] if self.week is None else d['weeks'].get(self.week,{})
        found=[r for r in rows.values() if r.get('id')==self.task]
        return len(found)==1 and found[0]['status']==-2


@dataclass(frozen=True)
class CollectLucerne:
    max_claims: int = 32

    def __call__(self,device,observe,cancelled,clock,allowed):
        initial=observe();d=data(initial)
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Получение наград свитков отменено')
        def execute(steps):
            return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
                Workflow('lucerne_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
                instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        def claim(receipt,point):
            permit();device.tap(*point,hold_ms=100);deadline=clock()+20
            while True:
                permit();s=observe()
                if receipt.matches(s):return settle()
                if clock()>=deadline:raise WorkflowError('Свитки: точный опыт и получение не подтверждены; повтор запрещён')
                if cancelled.wait(.1):raise Cancelled('Получение свитков отменено')
        def settle():
            started=clock();deadline=started+10
            while True:
                permit();s=observe()
                if LEVELUP.matches(s):
                    before_items=inventory(s);before_money=balances(s);before_exp=total_exp(data(s))
                    s=execute((Tap(619,436,LEVELUP,PANEL,hold_ms=100,settle=.5),))
                    if inventory(s)!=before_items or balances(s)!=before_money or total_exp(data(s))!=before_exp:
                        raise WorkflowError('Свитки: активы изменились при закрытии повышения уровня')
                elif REWARD.matches(s):
                    check_reward_window(s)
                    before_items=inventory(s);before_money=balances(s);before_exp=total_exp(data(s))
                    s=execute((Tap(480,443,REWARD,PANEL,hold_ms=100,settle=.5),))
                    if inventory(s)!=before_items or balances(s)!=before_money or total_exp(data(s))!=before_exp:
                        raise WorkflowError('Свитки: активы изменились при закрытии призов')
                if PANEL.matches(s) and clock()>=started+2:return s
                if clock()>=deadline:raise NotReady('Свитки: неизвестное окно после получения опыта')
                if cancelled.wait(.1):raise Cancelled('Получение свитков отменено')
        pending=(d['daily']==1 and initial.values.get('daily_score',0)>=50) or free_due(d) or any(r['status']==-1 for g in (*d['weeks'].values(),d['season']) for r in g.values())
        state=settle() if d.get('visible') else initial
        if not pending and not d.get('visible'):return state
        if not d.get('visible'):
            state=execute(SELECTION_CLEAR)
            if not CITY_HUD.matches(state):raise NotReady('Свитки: нужен свободный город')
            buildings=[k for k,r in state.values['buildings'].items() if table(r) and r.get('type')==19 and r.get('state')==1]
            if len(buildings)!=1:raise NotReady('Свитки: торговый пост не подтверждён')
            building=buildings[0]
            state=execute((NavigateCity(19,building_id=building),))
            class Selected:
                def matches(self,s):
                    row=s.values.get('building_menu',{}).get('selected')
                    return (table(row) and row.get('id')==building and row.get('type')==19
                        and set(row.get('buttons',[]))=={'img_BattlePassHudIcon','btn_FunctionMarket','btn_CityPopUpResBank','btn_CityPopUpInfo'}
                        and set(s.values['views'])<=set(CITY_VIEWS))
            state=execute((Tap(439,354,Selected(),PANEL,hold_ms=100,settle=1.5),))
        state=execute((Tap(560,37,PANEL,All((PANEL,Condition(('lucerne','tab'),'eq',2))),hold_ms=100,settle=.5),))
        count=0
        if data(state)['daily']==1 and state.values.get('daily_score',0)>=50:
            state=claim(ExperienceReceipt.capture(state,daily=True),(895,128));count+=1
        while count<self.max_claims:
            state=observe();d=data(state)
            if not PANEL.matches(state):raise NotReady('Свитки: ожидание известного экрана после опыта')
            ready=[week for week,rows in d['weeks'].items() if any(r['status']==-1 for r in rows.values())]
            season=any(r['status']==-1 for r in d['season'].values())
            if not ready and not season:break
            if ready:
                week=str(d['week']) if str(d.get('week')) in ready else min(ready,key=int)
                if not 1<=int(week)<=5:raise NotReady('Свитки: геометрия этой недели ещё не проверена')
                state=execute((Tap(150,205,PANEL,Condition(('lucerne','missionTab'),'eq',1),hold_ms=100,settle=.4),
                    Tap((309,439,569,699,829)[int(week)-1],178,PANEL,
                        Condition(('lucerne','week'),'eq',int(week)),hold_ms=100,settle=.4)))
                receipt=ExperienceReceipt.capture(state,week);point=(806,268)
            else:
                state=execute((Tap(150,280,PANEL,Condition(('lucerne','missionTab'),'eq',2),hold_ms=100,settle=.4),))
                receipt=ExperienceReceipt.capture(state);point=(335,421)
            state=claim(receipt,point);count+=1
        prizes=0
        if count<self.max_claims and free_due(data(state)):
            state=execute((Tap(390,37,PANEL,All((PANEL,Condition(('lucerne','tab'),'eq',1))),hold_ms=100,settle=.5),))
            receipt=FreeRewardReceipt.capture(state);prizes=len(receipt.levels)
            state=claim(receipt,(861,508))
        if not PANEL.matches(state):raise NotReady('Свитки: неизвестное окно результата')
        state=execute((Tap(30,29,PANEL,Condition(('lucerne','visible'),'eq',False),hold_ms=100,settle=.5),*SELECTION_CLEAR))
        state.values['lucerne_claimed']=count
        state.values['lucerne_free_rewards']=prizes
        return state


def lucerne_workflow(settings,*,verified=False):
    limit=LucerneOptions.from_settings(settings).max_claims
    return Workflow('lucerne','1.1.12.20',960,540,(Procedure(CollectLucerne(limit)),),verified=verified,
        extra_paths=FIELDS,data_timeout=10,wait_reason='Ожидание бесплатных наград Люцернских свитков')
