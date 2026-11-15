"""Bounded optional building supplies: existing 10k food/wood packs, one at a time."""
from dataclasses import dataclass

from .navigation import hud_function_point

from .supply_boxes import balances, inventory, integer, table
from .workflows import (AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, HUD_MENU,
    NotReady, Tap, Workflow, WorkflowError)


FIELDS={'supply_inventory':['@item_counts'],'resource_pack_ui':['@resource_pack_ui'],
    'hud_functions':['@hud_functions']}


def bag(state):
    p=state.values.get('resource_pack_ui')
    return (table(p) and p.get('visible') is True and state.values.get('in_city') is True
        and set(state.values.get('views',{}))<=set(CITY_VIEWS+('ItemBag','CommonBackground')))


class Bag:
    def matches(self,state):return bag(state)


BAG=Bag()


def bag_point(state):
    return hud_function_point(state,3)


@dataclass(frozen=True)
class PackReceipt:
    money: dict
    items: dict

    @classmethod
    def capture(cls,state,item):
        p=state.values.get('resource_pack_ui');kind={1:1,7:2}.get(item)
        row=p.get('selected') if table(p) else None;cfg=p.get('configs',{}).get(str(item)) if table(p) else None
        items=inventory(state)
        if (type(item) is not int or kind is None or not bag(state) or p.get('tab')!='Res' or p.get('count')!=1
                or type(p.get('count')) is not int or p.get('disabled') is not False or p.get('progress') is not False
                or not table(row) or row.get('itemId')!=item or row.get('expireTime')!=0
                or row.get('itemCount')!=items.get(str(item)) or not integer(items.get(str(item)),1)
                or not table(cfg) or cfg.get('ID')!=item or cfg.get('OpType')!=1 or cfg.get('SubType')!=2
                or cfg.get('Target')!=kind or cfg.get('OpValue')!=10000 or cfg.get('Use')!=1
                or cfg.get('LastTime')!=0 or cfg.get('ChangeID')!=0):
            raise NotReady('Ресурсные пакеты: обычный пакет10000 и количество1 не подтверждены')
        items[str(item)]-=1
        if not items[str(item)]:del items[str(item)]
        money=balances(state);money[str(kind)]+=10000
        return cls(money,items)

    def matches(self,state):
        p=state.values.get('resource_pack_ui')
        return (bag(state) and p.get('progress') is False
            and balances(state)==self.money and inventory(state)==self.items)


def replenish(device,observe,cancelled,clock,allowed,minimum,max_packs=4):
    initial=observe();used=0
    def permit():
        if cancelled.is_set() or not allowed():raise Cancelled('Пополнение ресурсов отменено')
    def execute(steps):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('building_resource_packs','1.1.12.20',960,540,steps,verified=True),cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    def close():
        return execute((Tap(835,62,BAG,AnyOf((HUD_MENU,CITY_HUD)),hold_ms=100,when=BAG,settle=.3),
            Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,when=Condition(('hud_menu',),'eq',True),settle=.3)))
    state=initial
    if not bag(state) and not CITY_HUD.matches(state):raise NotReady('Ресурсные пакеты: нужен свободный город или сумка')
    deadline=clock()+15
    while bag(state) and state.values['resource_pack_ui'].get('progress') is True:
        permit()
        if clock()>=deadline:raise NotReady('Ресурсные пакеты: ожидание ранее начатого использования')
        if cancelled.wait(.1):raise Cancelled('Пополнение ресурсов отменено')
        state=observe()
    money=balances(state);items=inventory(state)
    if any((max(0,minimum.get(kind,0)-money[kind])+9999)//10000>items.get(str(item),0)
            for item,kind in ((1,'1'),(7,'2'))):
        state=close();state.values['building_resource_packs_used']=0
        return state
    for item,kind in ((1,'1'),(7,'2')):
        while used<max_packs and balances(state)[kind]<minimum.get(kind,0) and inventory(state).get(str(item),0)>0:
            permit()
            if not bag(state):
                point=bag_point(state)
                state=execute((Tap(924,505,CITY_HUD,HUD_MENU,hold_ms=100,settle=.3),
                    Tap(*point,HUD_MENU,BAG,hold_ms=100,settle=.4)))
            p=state.values['resource_pack_ui']
            if p.get('tab')!='Res':
                state=execute((Tap(190,62,BAG,Condition(('resource_pack_ui','tab'),'eq','Res'),hold_ms=100,settle=.3),))
                p=state.values['resource_pack_ui']
            rows=p.get('rows')
            if not table(rows):raise NotReady('Ресурсные пакеты: список сумки неполон')
            indexes=[int(key) for key,row in rows.items() if key.isdecimal() and table(row) and row.get('itemId')==item]
            if len(indexes)!=1 or not 1<=indexes[0]<=12:raise NotReady('Ресурсные пакеты: пакет вне проверенной области')
            i=indexes[0]-1;point=((170,290,410,530)[i%4],(155,270,385)[i//4])
            class Selected:
                def matches(self,s):return bag(s) and s.values['resource_pack_ui'].get('selected',{}).get('itemId')==item
            state=execute((Tap(*point,BAG,Selected(),hold_ms=100,settle=.3),))
            receipt=PackReceipt.capture(state,item);permit();device.tap(725,466,hold_ms=100)
            deadline=clock()+15
            while True:
                permit();state=observe()
                if receipt.matches(state):break
                if clock()>=deadline:raise WorkflowError('Ресурсные пакеты: точный расход1 и выдача10000 не подтверждены; повтор запрещён')
                if cancelled.wait(.1):raise Cancelled('Пополнение ресурсов отменено')
            used+=1
    state=close();state.values['building_resource_packs_used']=used
    return state
