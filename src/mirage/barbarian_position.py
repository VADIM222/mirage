"""Free positioning of the farm's own army, with a durable pre-input intent."""
from dataclasses import asdict,dataclass,field
from copy import deepcopy
import math

from .barbarians import (BattlePanel,close_hud_menu,field_composition,fighting_composition,
    idle_army,own_armies,pve_talent_cost,troop_totals)
from .gather import number
from .commanders import selected_heroes,troop_heroes
from .supply_boxes import all_balances,integer,inventory,table
from .workflows import CITY_HUD,Cancelled,Engine,NotReady,RETURN_TO_CITY,WorkflowError


def goal_point(value):
    if not table(value) or set(value)!={'1','2'} or any(not number(v) for v in value.values()):return None
    return {'x':value['1'],'y':value['2']}


@dataclass(frozen=True)
class PositionReceipt:
    goal: dict
    units: dict
    ap: int
    resources: dict
    items: dict
    heroes: dict = field(default_factory=lambda:{'1':3},kw_only=True)

    @classmethod
    def capture(cls,state):
        v=state.values;hero=v.get('barbarian_hero');ui=hero.get('dispatch') if table(hero) else None
        goal=goal_point(ui.get('goal')) if table(ui) else None
        form_goal=goal_point(ui.get('formGoal')) if table(ui) else None
        selected=v.get('barbarian_form_SelectUnits')
        if (not BattlePanel('SendTroopsMain').matches(state) or own_armies(state) or not table(ui)
                or ui.get('empty') is not True or ui.get('target')!=-1 or ui.get('offensive') is not False
                or goal is None or form_goal!=goal or v.get('barbarian_form_DstCharId')!=-1
                or not integer(v.get('barbarian_city'),1)
                or not integer(v.get('barbarian_form_SrcCharId'),1)
                or v.get('barbarian_form_SrcCharId',0)*100!=v['barbarian_city']
                or v.get('barbarian_form_CharType') is not None or v.get('barbarian_form_CollectResType')!=-1
                or v.get('barbarian_form_isAttackNpc') is not False or v.get('barbarian_form_isAggressive') is not False
                or v.get('barbarian_form_Dispatched') is not False or v.get('barbarian_form_troopType')!=0
                or selected_heroes(state) is None or v.get('barbarian_form_SelHeroIds')!=selected_heroes(state) or v.get('barbarian_cost')!=-1
                or not number(v.get('barbarian_form_troopMoveTime')) or not 0<v['barbarian_form_troopMoveTime']<=120
                or not integer(v.get('barbarian_ap')) or not table(selected)
                or any(not integer(n) for n in selected.values())
                or v.get('barbarian_server')!=v.get('player',{}).get('ServerID') or v.get('barbarian_viewed_server')!=0):
            raise NotReady('Цепочка: бесплатная форма перемещения к пустой точке не подтверждена')
        units={key:n for key,n in selected.items() if n>0}
        if (not units or any(k not in ('1','2','3','13','14','115') for k in units)
                or sum(units.values())!=v.get('barbarian_form_TotalNum') or not 1000<=sum(units.values())<=300000):
            raise NotReady('Цепочка: боевой состав для позиционирования не подтверждён')
        available={str(r.get('unitId')):r.get('unitCount') for r in v.get('troops',{}).values() if table(r)}
        if any(not integer(available.get(k),n) for k,n in units.items()):raise NotReady('Цепочка: выбранные войска отсутствуют в городе')
        return cls(goal,units,v['barbarian_ap'],all_balances(state),inventory(state),heroes=selected_heroes(state))

    def matches(self,state,*,recovering=False):
        try:rows=own_armies(state);money=all_balances(state);items=inventory(state)
        except NotReady:return False
        ap=state.values.get('barbarian_ap')
        # A free march can take up to120s; natural AP regeneration continues
        # during arrival observation as well as after a restart.
        if (len(rows)!=1 or money!=self.resources or items!=self.items or not integer(ap,self.ap)):return False
        row=next(iter(rows.values()));troop=row['troop'];pos=row.get('pos');heroes=troop.get('heros')
        return (row.get('state')==4 and row.get('isFightTarget') is False and row.get('offensive') is False
            and row.get('isRally') is False and row.get('IsAutoPVE') is False and row.get('IsAutoGather') is False
            and integer(row.get('charId'),1) and row['charId']%100==0
            and row.get('troopId')==getattr(self,'troop_id',row['troopId'])
            and row.get('charId')==getattr(self,'char_id',row.get('charId'))
            and fighting_composition(troop.get('units'))==getattr(self,'maximum',self.units)
            and field_composition(troop.get('units'))==self.units
            and table(heroes) and all(table(h) for h in heroes.values())
            and troop_heroes(troop)==self.heroes
            and table(pos) and all(number(pos.get(k)) for k in ('x','y'))
            and math.hypot(pos['x']-self.goal['x'],pos['y']-self.goal['y'])<=.35)


@dataclass(frozen=True)
class FieldPositionReceipt(PositionReceipt):
    troop_id: int
    char_id: int
    maximum: dict

    @classmethod
    def capture(cls,state):
        v=state.values;army=idle_army(state);hero=v.get('barbarian_hero')
        ui=hero.get('dispatch') if table(hero) else None;sel=ui.get('selection') if table(ui) else None
        row=sel.get('row') if table(sel) else None;goal=goal_point(ui.get('goal')) if table(ui) else None
        if (not BattlePanel('MapUISelectTroops').matches(state) or not BattlePanel('TroopSelectedPopUp').matches(state)
                or not table(ui) or not table(sel) or not table(row) or goal is None
                or ui.get('empty') is not True or ui.get('target')!=-1 or ui.get('offensive') is not False
                or not integer(sel.get('selectIndex'),1) or sel['selectIndex']>9
                or sel.get('popup_selectIndex')!=sel['selectIndex'] or sel.get('type')!=1
                or sel.get('isMultiSelectMode') is not False or sel.get('popup_isMultiSelectMode') is not False
                or sel.get('popup_ShowPveAPBuy') is not False or v.get('barbarian_cost')!=-1
                or row.get('troopId')!=army['troopId'] or row.get('charId')!=army['charId'] or row.get('state')!=4
                or not number(sel.get('popup_troopMoveTime')) or not 0<sel['popup_troopMoveTime']<=120
                or not integer(v.get('barbarian_ap'))
                or v.get('barbarian_server')!=v.get('player',{}).get('ServerID') or v.get('barbarian_viewed_server')!=0):
            raise NotReady('Цепочка: бесплатное перемещение выбранной своей армии не подтверждено')
        return cls(goal,field_composition(army['troop']['units']),v['barbarian_ap'],all_balances(state),inventory(state),
            army['troopId'],army['charId'],fighting_composition(army['troop']['units']),heroes=troop_heroes(army['troop']))


@dataclass(frozen=True)
class CombatMoveReceipt:
    goal: dict
    troop_id: int
    char_id: int
    maximum: dict
    ap_target: int
    ap: int
    resources: dict
    items: dict
    heroes: dict = field(default_factory=lambda:{'1':3},kw_only=True)

    @classmethod
    def capture(cls,state):
        v=state.values;rows=own_armies(state)
        if len(rows)!=1:raise NotReady('Цепочка: нужна одна своя боевая армия')
        army=next(iter(rows.values()));troop=army['troop'];hero=v.get('barbarian_hero')
        ui=hero.get('dispatch') if table(hero) else None;sel=ui.get('selection') if table(ui) else None
        selected=sel.get('row') if table(sel) else None;goal=goal_point(ui.get('goal')) if table(ui) else None
        maximum=fighting_composition(troop.get('units'))
        if (not BattlePanel('MapUISelectTroops').matches(state) or not BattlePanel('TroopSelectedPopUp').matches(state)
                or army.get('state')!=2 or army.get('offensive') is not True or army.get('isFightTarget') is not True
                or army.get('isRally') is not False or army.get('IsAutoPVE') is not False or army.get('IsAutoGather') is not False
                or troop.get('isAggressiveRallyCaptain') is not False or maximum is None
                or not integer(troop.get('apTarget'),1) or not integer(army.get('charId'),1) or army['charId']%100
                or troop_heroes(troop) is None
                or goal is None or not table(ui) or not table(sel) or not table(selected)
                or ui.get('empty') is not True or ui.get('target')!=-1 or ui.get('offensive') is not False
                or v.get('barbarian_cost')!=-1 or not integer(sel.get('selectIndex'),1)
                or sel['selectIndex']>9 or sel.get('popup_selectIndex')!=sel['selectIndex'] or sel.get('type')!=1
                or sel.get('isMultiSelectMode') is not False or sel.get('popup_isMultiSelectMode') is not False
                or sel.get('popup_ShowPveAPBuy') is not False
                or selected.get('troopId')!=army['troopId'] or selected.get('charId')!=army['charId']
                or selected.get('state')!=2 or not number(sel.get('popup_troopMoveTime'))
                or not 0<sel['popup_troopMoveTime']<=120 or not integer(v.get('barbarian_ap'))
                or v.get('barbarian_server')!=v.get('player',{}).get('ServerID') or v.get('barbarian_viewed_server')!=0):
            raise NotReady('Цепочка: бесплатный отвод своей уже сражающейся армии не подтверждён')
        return cls(goal,army['troopId'],army['charId'],maximum,troop['apTarget'],v['barbarian_ap'],all_balances(state),inventory(state),heroes=troop_heroes(troop))

    def matches(self,state):
        try:rows=own_armies(state);money=all_balances(state);items=inventory(state)
        except NotReady:return False
        row=rows.get(str(self.troop_id));troop=row.get('troop') if table(row) else None
        if (len(rows)!=1 or not table(row) or not table(troop) or row.get('charId')!=self.char_id
                or row.get('offensive') is not False or row.get('isFightTarget') is not False
                or troop.get('apTarget')!=self.ap_target or fighting_composition(troop.get('units'))!=self.maximum
                or troop_heroes(troop)!=self.heroes
                or not integer(state.values.get('barbarian_ap'),self.ap)
                or money!=self.resources or items!=self.items):return False
        if row.get('state')==2:return True  # command acknowledgment, not arrival or combat evidence
        pos=row.get('pos')
        return row.get('state')==4 and table(pos) and all(number(pos.get(k)) for k in ('x','y')) and math.dist(
            [pos[k] for k in ('x','y')],[self.goal[k] for k in ('x','y')])<=.35


def move_combat_army(device,observe,cancelled,clock,allowed,*,store):
    initial=observe();receipt=CombatMoveReceipt.capture(initial);key='barbarian-session:'+initial.instance_id
    session=store.preference(key)
    if (not table(session) or session.get('task')!='barbarian_chain' or session.get('phase')!='field'
            or session.get('player')!=initial.player_id or session.get('server')!=initial.values['barbarian_server']
            or session.get('troop_id')!=receipt.troop_id or session.get('char_id')!=receipt.char_id
            or session.get('maximum')!=receipt.maximum or session.get('intent',{}).get('target',0)//100!=receipt.ap_target):
        raise NotReady('Цепочка: боевой отвод не принадлежит этой сессии')
    if receipt.heroes!=session.get('heroes',session.get('intent',{}).get('heroes',{'1':3})):
        raise NotReady('Цепочка: пара боевой армии изменилась')
    previous=deepcopy(session)
    if cancelled.is_set() or not allowed():raise Cancelled('Боевой отвод отменён')
    session.update(phase='combat_move_intent',combat_move_intent=asdict(receipt),pull_attempted=True);store.set_preference(key,session)
    if cancelled.is_set() or not allowed():
        store.set_preference(key,previous);raise Cancelled('Боевой отвод отменён')
    device.tap(755,230,hold_ms=100);deadline=clock()+20
    while True:
        if cancelled.is_set() or not allowed():raise Cancelled('Боевой отвод отменён')
        state=observe()
        if receipt.matches(state):break
        if clock()>=deadline:raise WorkflowError('Цепочка: отвод не подтверждён; повтор команды запрещён')
        if cancelled.wait(.1):raise Cancelled('Боевой отвод отменён')
    session.update(phase='field',pull_goal=receipt.goal);session.pop('combat_move_intent',None);store.set_preference(key,session)
    state.values['barbarian_pull_started']=True;return state


def position_field_army(device,observe,cancelled,clock,allowed,*,store,target_id=None):
    initial=observe();receipt=FieldPositionReceipt.capture(initial);key='barbarian-session:'+initial.instance_id
    session=store.preference(key)
    if (not table(session) or session.get('task')!='barbarian_chain' or session.get('player')!=initial.player_id
            or session.get('server')!=initial.values.get('barbarian_server') or session.get('phase')!='field'
            or session.get('troop_id')!=receipt.troop_id or session.get('char_id')!=receipt.char_id
            or session.get('maximum')!=receipt.maximum):
        raise NotReady('Цепочка: армия для перемещения не закреплена за этим режимом')
    if receipt.heroes!=session.get('heroes',session.get('intent',{}).get('heroes',{'1':3})):
        raise NotReady('Цепочка: пара полевой армии изменилась')
    previous=deepcopy(session)
    if cancelled.is_set() or not allowed():raise Cancelled('Перемещение армии отменено')
    session.update(phase='free_move_intent',move_intent=asdict(receipt))
    if target_id is not None:
        session.update(position_target=target_id,position_attempts=(previous.get('position_attempts',0)+1
            if previous.get('position_target')==target_id else 1))
    store.set_preference(key,session)
    if cancelled.is_set() or not allowed():
        store.set_preference(key,previous);raise Cancelled('Перемещение армии отменено')
    device.tap(755,230,hold_ms=100)
    deadline=clock()+initial.values['barbarian_hero']['dispatch']['selection']['popup_troopMoveTime']+20
    while True:
        if cancelled.is_set() or not allowed():raise Cancelled('Перемещение армии отменено')
        state=observe()
        if receipt.matches(state):break
        if clock()>=deadline:raise WorkflowError('Цепочка: бесплатное прибытие армии не подтверждено; повтор запрещён')
        if cancelled.wait(.1):raise Cancelled('Перемещение армии отменено')
    session.update(phase='field',position_goal=receipt.goal);session.pop('move_intent',None)
    store.set_preference(key,session);state.values['barbarian_positioned']=deepcopy(receipt.goal)
    return state


def position_city_army(device,observe,cancelled,clock,allowed,*,store,task='barbarian_chain',target_id=None,return_camera=True):
    initial=observe();receipt=PositionReceipt.capture(initial);key='barbarian-session:'+initial.instance_id
    if store.preference(key):raise NotReady('Цепочка: другая сессия уже владеет армией')
    if cancelled.is_set() or not allowed():raise Cancelled('Позиционирование отменено')
    session={'task':task,'player':initial.player_id,'server':initial.values['barbarian_server'],
        'phase':'position_intent','count':0,'city_totals':troop_totals(initial),'position_intent':asdict(receipt),'heroes':receipt.heroes}
    if target_id is not None:session.update(position_target=target_id,position_attempts=1)
    store.set_preference(key,session)
    if cancelled.is_set() or not allowed():
        store.set_preference(key,None);raise Cancelled('Позиционирование отменено')
    device.tap(695,475,hold_ms=100)
    deadline=clock()+initial.values['barbarian_form_troopMoveTime']+20
    while True:
        if cancelled.is_set() or not allowed():raise Cancelled('Позиционирование отменено')
        state=observe()
        if receipt.matches(state):break
        if clock()>=deadline:raise WorkflowError('Цепочка: точное бесплатное прибытие не подтверждено; повтор запрещён')
        if cancelled.wait(.1):raise Cancelled('Позиционирование отменено')
    row=next(iter(own_armies(state).values()))
    session.update(phase='field',troop_id=row['troopId'],char_id=row['charId'],maximum=dict(receipt.units),position_goal=receipt.goal)
    store.set_preference(key,session)
    state.values['barbarian_positioned']=deepcopy(receipt.goal)
    if return_camera and not CITY_HUD.matches(state):
        close_hud_menu(device,observe,cancelled,clock,allowed)
        state=Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            RETURN_TO_CITY,cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        state.values['barbarian_positioned']=deepcopy(receipt.goal)
    return state


@dataclass
class PositionCity:
    store: object = None

    def __call__(self,*args):
        if self.store is None:raise NotReady('Цепочка: хранилище сессии не подключено')
        return position_city_army(*args,store=self.store)


@dataclass
class PositionField:
    store: object = None

    def __call__(self,*args):
        if self.store is None:raise NotReady('Цепочка: хранилище сессии не подключено')
        return position_field_army(*args,store=self.store)
