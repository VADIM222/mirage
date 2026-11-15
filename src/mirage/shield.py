"""Eight-hour inventory shield; never replace protection or retry an uncertain use."""
from dataclasses import dataclass
from math import isfinite

from .supply_boxes import inventory, balances, integer, table
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine,
    HUD_MENU, NotReady, Procedure, Tap, Workflow, WorkflowError)


ITEM=49
FIELDS={'supply_inventory':['@item_counts'],'shield':['BuffData','Shield'],
    'shield_pk_id':['BuffData','PK_Buff'],'shield_fever':['BuffData','BuffMap',17202],
    'shield_bag':['@active_view','ItemBag'],'shield_tab':['UIObjectManager','ItemBag','curTab'],
    'shield_selected':['UIObjectManager','ItemBag','curBagItem'],
    'shield_count':['UIObjectManager','ItemBag','useCount'],
    'shield_disabled':['UIObjectManager','ItemBag','disableUseBtn'],
    'shield_list':['UIObjectManager','ItemBag','bagItems','Battle']}
VISIBLE=Condition(('shield_bag',),'eq',True)
BAG=All((VISIBLE,Condition(('in_city',),'eq',True),Condition(('city_enabled',),'eq',True),
    Condition(('views',),'subset',CITY_VIEWS+('ItemBag','CommonBackground'))))
TIMES=('shieldSystemEndTime','shieldItemEndTime','shieldEndTime','shieldSystemStartTime','shieldItemStartTime')


def protection(state):
    v=state.values;row=v.get('shield');now=v.get('server_time')
    if (not table(row) or any(not integer(row.get(k)) for k in TIMES)
            or type(now) not in (int,float) or not isfinite(now) or now<=0
            or v.get('shield_pk_id')!=17202 or type(v.get('shield_pk_id')) is not int
            or 'shield_fever' not in v):
        raise NotReady('Щит: состояние защиты и военной лихорадки не подтверждено')
    return dict(row),now


def unprotected(state):
    row,now=protection(state)
    return all(row[k]<=now for k in TIMES if k.endswith('EndTime'))


def no_fever(state):
    protection(state);rows=state.values['shield_fever']
    if rows is None:return True
    if not table(rows):raise NotReady('Щит: неполные данные военной лихорадки')
    for row in rows.values():
        if (not table(row) or row.get('BuffId')!=17202 or not integer(row.get('Expire'))):
            raise NotReady('Щит: неизвестная запись военной лихорадки')
    # Any present record blocks use, including an expired cache awaiting refresh.
    return not rows


@dataclass(frozen=True)
class ShieldReceipt:
    shield: dict
    items: dict
    money: dict
    now: int | float

    @classmethod
    def capture(cls,state):
        v=state.values;shield,now=protection(state);items=inventory(state);selected=v.get('shield_selected')
        if (not BAG.matches(state) or not unprotected(state) or not no_fever(state)
                or v.get('shield_tab')!='Battle' or v.get('shield_disabled') is not False
                or type(v.get('shield_count')) is not int or v['shield_count']!=1
                or not table(selected) or selected.get('itemId')!=ITEM or selected.get('expireTime')!=0
                or selected.get('itemCount')!=items.get(str(ITEM)) or items.get(str(ITEM),0)<1):
            raise NotReady('Щит: применение одного предмета49 не разрешено')
        return cls(shield,items,balances(state),now)

    def matches(self,state):
        try:row,now=protection(state);items=inventory(state);money=balances(state)
        except NotReady:return False
        expected=dict(self.items);expected[str(ITEM)]-=1
        if not expected[str(ITEM)]:del expected[str(ITEM)]
        start,end=row['shieldItemStartTime'],row['shieldItemEndTime']
        return (items==expected and money==self.money and self.now-2000<=start<=now+2000
            and end-start==28800000 and end>now and row['shieldEndTime']==end
            and all(row[k]==self.shield[k] for k in ('shieldSystemStartTime','shieldSystemEndTime')))


@dataclass(frozen=True)
class ApplyShield:
    def __call__(self,device,observe,cancelled,clock,allowed):
        initial=observe()
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Применение щита отменено')
        def execute(steps):
            return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
                Workflow('shield_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
                instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        def clean():
            return execute((Tap(835,62,BAG,AnyOf((HUD_MENU,CITY_HUD)),hold_ms=100,when=VISIBLE,settle=.3),
                Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,when=Condition(('hud_menu',),'eq',True),settle=.3)))
        state=clean()
        if not CITY_HUD.matches(state):raise NotReady('Щит: нужен свободный город')
        if not unprotected(state) or not no_fever(state) or not inventory(state).get(str(ITEM)):return state
        state=execute((Tap(924,505,CITY_HUD,HUD_MENU,hold_ms=100,settle=.35),
            Tap(625,505,HUD_MENU,BAG,hold_ms=100,settle=.4),
            Tap(410,62,BAG,Condition(('shield_tab',),'eq','Battle'),hold_ms=100,settle=.3)))
        rows=state.values.get('shield_list')
        if not table(rows):raise NotReady('Щит: список сумки неполон')
        indexes=[int(k) for k,r in rows.items() if k.isdecimal() and table(r) and r.get('itemId')==ITEM]
        if len(indexes)!=1 or not 1<=indexes[0]<=12:raise NotReady('Щит: предмет вне проверенной области сумки')
        index=indexes[0]-1
        class Selected:
            def matches(self,s):
                row=s.values.get('shield_selected')
                return table(row) and row.get('itemId')==ITEM
        state=execute((Tap((170,290,410,530)[index%4],(155,270,385)[index//4],BAG,
            Selected(),hold_ms=100,settle=.3),))
        receipt=ShieldReceipt.capture(observe());permit();device.tap(725,466,hold_ms=100)
        deadline=clock()+20
        while True:
            permit();state=observe()
            if receipt.matches(state):break
            if clock()>=deadline:raise WorkflowError('Щит: расход1 и защита8ч не подтверждены; повтор запрещён')
            if cancelled.wait(.1):raise Cancelled('Применение щита отменено')
        state=clean();state.values['shield_applied']=True
        return state


def shield_workflow(settings,*,verified=False):
    return Workflow('shield','1.1.12.20',960,540,(Procedure(ApplyShield()),),verified=verified,
        extra_paths=FIELDS,data_timeout=10,wait_reason='Ожидание предмета49 и отсутствия щита/военной лихорадки')
