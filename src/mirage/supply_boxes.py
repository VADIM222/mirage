"""Ordinary Supply Box 7001: one-item uses and exact, memory-backed loot receipts."""
from dataclasses import dataclass
from math import isfinite

from .model import SupplyBoxOptions
from .navigation import OpenHudFunction
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine,
    HUD_MENU, NotReady, Procedure, Tap, Workflow, WorkflowError)


BOX=7001
FIELDS={'supply_inventory':['@item_counts'],'supply_bag_visible':['@active_view','ItemBag'],
    'hud_functions':['@hud_functions'],
    'supply_tab':['UIObjectManager','ItemBag','curTab'],
    'supply_selected':['UIObjectManager','ItemBag','curBagItem'],
    'supply_use_count':['UIObjectManager','ItemBag','useCount'],
    'supply_list':['UIObjectManager','ItemBag','bagItems','Other'],
    'supply_reward_visible':['@active_view','UniversalRewardsCollect'],
    **{'supply_reward_'+key:['UIObjectManager','UniversalRewardsCollect',field] for key,field in
       (('source','srcItemId'),('rows','rewards'),('click','canClick'),('recycle','isRecycleMode'),
        ('width','m_UICullWidth'),('height','m_UICullHeigth'))}}
BAG_VISIBLE=Condition(('supply_bag_visible',),'eq',True)
REWARD_VISIBLE=Condition(('supply_reward_visible',),'eq',True)
BAG=All((BAG_VISIBLE,Condition(('supply_reward_visible',),'eq',False),
    Condition(('in_city',),'eq',True),Condition(('city_enabled',),'eq',True),
    Condition(('views',),'subset',CITY_VIEWS+('ItemBag','CommonBackground'))))


def integer(value,low=0):return type(value) is int and value>=low
def table(value):return isinstance(value,dict) and all(isinstance(key,str) and not key.startswith('$') for key in value)


def inventory(state):
    data=state.values.get('supply_inventory')
    if (not table(data) or data.get('ready') is not True or not table(data.get('items'))
            or any(not key.isdecimal() or int(key)<=0 or not integer(count,1)
                   for key,count in data['items'].items())):
        raise NotReady('Ящики: инвентарь не подтверждён')
    return dict(data['items'])


def balances(state):
    row=state.values.get('resources',{})
    if not table(row) or any(not integer(row.get(str(i))) for i in range(1,7)):
        raise NotReady('Ящики: валюты не подтверждены')
    return {str(i):row[str(i)] for i in range(1,7)}


def all_balances(state):
    balances(state);rows=state.values['resources']
    if any(not key.isdecimal() or not integer(value) for key,value in rows.items()):
        raise NotReady('Ящики: полный баланс не подтверждён')
    return dict(rows)


def rewards(state,box=BOX):
    v=state.values
    if (v.get('supply_reward_visible') is not True or v.get('supply_bag_visible') is not True
            or v.get('in_city') is not True or v.get('city_enabled') is not True
            or v.get('supply_reward_source')!=box or v.get('supply_reward_click') is not True
            or v.get('supply_reward_recycle') is not False
            or type(v.get('supply_reward_width')) not in (int,float)
            or not isfinite(v['supply_reward_width'])
            or abs(v['supply_reward_width']-586.0723)>.1
            or type(v.get('supply_reward_height')) not in (int,float)
            or not isfinite(v['supply_reward_height'])
            or abs(v['supply_reward_height']-366.3492)>.1
            or set(v.get('views',{}))-set(CITY_VIEWS+('ItemBag','CommonBackground','UniversalRewardsCollect'))):
        raise NotReady('Ящики: обычное окно награды не подтверждено')
    rows=v.get('supply_reward_rows');items={};currency={}
    if not table(rows) or not rows:raise NotReady('Ящики: состав награды не прочитан')
    for row in rows.values():
        if (not table(row) or type(row.get('Type')) is not int or row['Type'] not in (1,2)
                or not integer(row.get('SubType'),1) or not integer(row.get('Value'),1)):
            raise NotReady('Ящики: неизвестная награда')
        kind,key,value=row['Type'],str(row['SubType']),row['Value']
        if kind==1 and row['SubType'] not in range(1,7) or kind==2 and row['SubType']==box:
            raise NotReady('Ящики: неподтверждённый тип награды')
        target=currency if kind==1 else items
        target[key]=target.get(key,0)+value
    return items,currency


@dataclass(frozen=True)
class SupplyReceipt:
    items: dict
    currency: dict
    box: int=BOX

    @classmethod
    def capture(cls,state,box=BOX):
        v=state.values;items=inventory(state);selected=v.get('supply_selected')
        if (not BAG.matches(state) or v.get('supply_tab')!='Other' or v.get('supply_use_count')!=1
                or type(v.get('supply_use_count')) is not int or not table(selected)
                or box not in (BOX,7014) or selected.get('itemId')!=box or selected.get('expireTime')!=0
                or selected.get('itemCount')!=items.get(str(box)) or items.get(str(box),0)<1):
            raise NotReady('Ящики: не подтверждены выбранный обычный ящик и количество1')
        return cls(items,all_balances(state),box)

    def matches(self,state):
        try:
            item_loot,currency_loot=rewards(state,self.box);current=inventory(state);currency=all_balances(state)
        except NotReady:return False
        expected=dict(self.items);expected[str(self.box)]-=1
        if not expected[str(self.box)]:del expected[str(self.box)]
        for key,value in item_loot.items():expected[key]=expected.get(key,0)+value
        return current==expected and currency=={key:value+currency_loot.get(key,0) for key,value in self.currency.items()}


@dataclass(frozen=True)
class OpenSupplyBoxes:
    options: SupplyBoxOptions
    box: int=BOX

    def __post_init__(self):
        if type(self.box) is not int or self.box not in (BOX,7014):raise ValueError('Unsupported ordinary box')

    def __call__(self,device,observe,cancelled,clock,allowed):
        initial=observe();opened=0
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Открытие ящиков отменено')
        def execute(steps):
            return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
                Workflow('supply_box_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
                instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        def wait(predicate,message,seconds=20):
            deadline=clock()+seconds
            while True:
                permit();state=observe()
                if predicate(state):return state
                if clock()>=deadline:raise WorkflowError(message)
                if cancelled.wait(.1):raise Cancelled('Открытие ящиков отменено')
        def confirm(receipt=None):
            state=observe();rewards(state,self.box);before=inventory(state);money=all_balances(state)
            if receipt is not None and not receipt.matches(state):
                raise WorkflowError('Ящики: награда изменилась перед подтверждением')
            permit();device.tap(484,398,hold_ms=100)
            state=wait(lambda s:BAG.matches(s),'Ящики: закрытие награды не подтверждено')
            if inventory(state)!=before or all_balances(state)!=money:
                raise WorkflowError('Ящики: активы изменились при подтверждении награды')
            return state
        def clean():
            return execute((Tap(835,62,BAG,AnyOf((HUD_MENU,CITY_HUD)),hold_ms=100,when=BAG_VISIBLE,settle=.3),
                Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,when=Condition(('hud_menu',),'eq',True),settle=.3)))
        if initial.values.get('supply_reward_visible') is True:
            # The prior use may have been committed before a stop: finish its
            # known receipt only, without opening another box in this check.
            confirm();state=clean();state.values['supply_boxes_opened']=0
            state.values['supply_reward_resumed']=True
            return state
        state=clean()
        if not CITY_HUD.matches(state):raise NotReady('Ящики: нужен свободный город')
        if not inventory(state).get(str(self.box)):return state
        state=execute((Tap(924,505,CITY_HUD,HUD_MENU,hold_ms=100,settle=.35),
            Procedure(OpenHudFunction(3,BAG)),
            Tap(757,62,BAG,Condition(('supply_tab',),'eq','Other'),hold_ms=100,settle=.3)))
        rows=state.values.get('supply_list')
        if not table(rows):raise NotReady('Ящики: список сумки неполон')
        indexes=[int(key) for key,row in rows.items() if key.isdecimal() and table(row) and row.get('itemId')==self.box]
        if len(indexes)!=1 or not 1<=indexes[0]<=12:raise NotReady('Ящики: целевой ящик не в проверенной области списка')
        index=indexes[0]-1;x=(170,290,410,530)[index%4];y=(155,270,385)[index//4]
        state=execute((Tap(x,y,BAG,Condition(('supply_selected','itemId'),'eq',self.box),hold_ms=100,settle=.3),))
        for _ in range(self.options.max_boxes):
            state=observe()
            if not inventory(state).get(str(self.box)):break
            receipt=SupplyReceipt.capture(state,self.box)
            permit();device.tap(725,466,hold_ms=100)
            state=wait(receipt.matches,'Ящики: расход1 и точная награда не подтверждены; повтор запрещён')
            opened+=1
            confirm(receipt)
        state=clean();state.values['supply_boxes_opened']=opened
        return state


def supply_box_workflow(settings,*,verified=False):
    return Workflow('supply_boxes','1.1.12.20',960,540,
        (Procedure(OpenSupplyBoxes(SupplyBoxOptions.from_settings(settings))),),verified=verified,
        extra_paths=FIELDS,data_timeout=10,
        wait_reason='Ожидание обычных ящиков снабжения и свободной сумки')
