"""Memory-backed resource gathering with bounded armies and exact dispatch receipts."""
from dataclasses import dataclass
import math

from .model import GATHER_RESOURCES, GatherOptions

from .workflows import (CITY_HUD, CITY_VIEWS, Cancelled, NotReady, Procedure,
                        RETURN_TO_CITY, Workflow, WorkflowError)


FORM_FIELDS=('DstCharId','SrcCharId','CollectResType','CharType','TotalNum','TotalLoad',
    'SelectUnits','SelHeroIds','isAggressive','isAttackNpc','Dispatched','troopType','troopMoveTime')
FIELDS={
    'gather_target':['@gather_target'], 'gather_troops':['@gather_troops'],
    'gather_count':['WorldMapData','MyChars','TroopCount'],
    'gather_city_id':['WorldMapData','MyChars','CityId'],
    'gather_search_index':['RssSearchData','CurSelectSearchIndex'],
    'gather_search_runtime':['RssSearchData','RuntimeData'],
    'gather_popup_x':['UIObjectManager','MapUISearchPopUp','X'],
    'gather_popup_y':['UIObjectManager','MapUISearchPopUp','Y'],
    'gather_select_target':['UIObjectManager','MapUISelectTroops','CurTargetId'],
    'gather_select_resource':['UIObjectManager','MapUISelectTroops','CollectResType'],
    **{'gather_view_'+name:['@active_view',name] for name in
       ('MapUISearchMainPage','MapUISearchPopUp','ResDepositPopUp','MapUISelectTroops','SendTroopsMain')},
    **{'gather_form_'+name:['UIObjectManager','SendTroopsMain',name] for name in FORM_FIELDS}}

# Category centre, search/slider centre, and game-owned popup anchor.
SEARCH_LAYOUT={1:(330,335,-202),2:(475,480,-2),3:(620,624,198),4:(770,767,396)}


def integer(value,minimum=0):
    return type(value) is int and value>=minimum


def number(value):
    return type(value) in (int,float) and math.isfinite(value)


def table(value):
    return isinstance(value,dict) and not any(key.startswith('$') for key in value)


def search_level(state,resource=1):
    runtime=state.values.get('gather_search_runtime')
    row=runtime.get(str(resource)) if table(runtime) else None
    return row.get('CurLevel') if table(row) else None


def search_popup_matches(state,resource):
    values=state.values
    x,y=values.get('gather_popup_x'),values.get('gather_popup_y')
    return (values.get('gather_search_index')==resource+2 and values.get('gather_view_MapUISearchPopUp') is True
        and number(x) and abs(x-SEARCH_LAYOUT[resource][2])<.1
        and number(y) and abs(y-174)<.1)


def own_troops(state):
    values=state.values
    rows=values.get('gather_troops')
    if not table(rows) or not integer(values.get('gather_count')) or len(rows)!=values['gather_count']:
        raise NotReady('Сбор: не подтверждены занятые очереди маршей')
    result={}
    for key,row in rows.items():
        if (not table(row) or not integer(row.get('troopId'),1) or str(row['troopId'])!=key
                or not table(row.get('troop')) or row['troop'].get('playerId')!=state.player_id
                or row.get('isFightTarget') is not False or row.get('offensive') is not False):
            raise NotReady('Сбор: неизвестный или сражающийся собственный марш')
        result[key]=row
    return result


def target(state,options):
    row=state.values.get('gather_target')
    if not table(row) or not integer(row.get('id'),1) or row.get('charType')!=6 or row.get('isFighting') is not False:
        raise NotReady('Сбор: ресурсная цель не подтверждена')
    rss=row.get('rss')
    alerts=row.get('charAlerts',{})
    if (not table(rss) or rss.get('resType')!=options.resource or not integer(rss.get('level'),1)
            or not options.level<=rss['level']<=options.max_level or rss.get('playerId')!=0
            or rss.get('isFighting') is not False or not number(rss.get('remain')) or rss['remain']<=0
            or not table(rss.get('rss_troops')) or rss['rss_troops'] or not table(alerts) or alerts):
        raise NotReady('Сбор: цель занята, сражается или не соответствует фильтру')
    return row


def balances(state):
    values=state.values.get('resources',{})
    if any(not integer(values.get(str(i))) for i in range(1,7)):
        raise NotReady('Сбор: валюты не подтверждены')
    return {str(i):values[str(i)] for i in range(1,7)}


def unit_ledger(rows):
    if not table(rows) or not rows:return None
    result={}
    for row in rows.values():
        if (not table(row) or not integer(row.get('unitId'),1) or not integer(row.get('unitCount'),1)
                or row.get('maxCount')!=row['unitCount'] or str(row['unitId']) in result):return None
        result[str(row['unitId'])]=row['unitCount']
    return result


@dataclass(frozen=True)
class MarchReceipt:
    target_id: int
    resource: int
    previous_ids: frozenset
    units: dict
    heroes: dict
    resources: dict

    @classmethod
    def capture(cls,state,options):
        v=state.values
        row=target(state,options)
        previous=own_troops(state)
        if len(previous)>=options.max_marches:raise NotReady('Сбор: достигнут лимит маршей')
        form={key:v.get('gather_form_'+key) for key in FORM_FIELDS}
        city=v.get('gather_city_id')
        units,heroes=form['SelectUnits'],form['SelHeroIds']
        if (v.get('gather_view_SendTroopsMain') is not True or not table(v.get('views'))
                or set(v['views'])-set(CITY_VIEWS+('SendTroopsMain','CommonBackground'))
                or not integer(city,1) or city%100
                or row['id']%100 or form['DstCharId']!=row['id']//100 or form['SrcCharId']!=city//100
                or (form['CollectResType'],form['CharType'],form['troopType'])!=(options.resource,6,0)
                or form['isAggressive'] is not False or form['isAttackNpc'] is not False
                or form['Dispatched'] is not False):raise NotReady('Сбор: форма не соответствует мирной ресурсной цели')
        if (not table(units) or not units or any(key not in ('4','8','12','16','20') or not integer(count,1)
                for key,count in units.items()) or sum(units.values())!=form['TotalNum']
                or not number(form['TotalLoad']) or form['TotalLoad']<row['rss']['remain']
                or not number(form['troopMoveTime']) or not 0<form['troopMoveTime']<=options.max_travel):
            raise NotReady('Сбор: состав, вместимость или время перехода не подтверждены')
        if (not table(heroes) or set(heroes) not in ({'1'},{'1','2'})
                or any(not integer(hero,1) for hero in heroes.values()) or len(set(heroes.values()))!=len(heroes)
                or options.primary and heroes.get('1')!=options.primary
                or options.deputy and heroes.get('2')!=options.deputy):raise NotReady('Сбор: командиры не подтверждены')
        return cls(row['id'],options.resource,frozenset(previous),dict(units),dict(heroes),balances(state))

    def matches(self,state):
        try:
            rows=own_troops(state)
            resources=balances(state)
        except NotReady:return False
        new=set(rows)-self.previous_ids
        if len(new)!=1 or not self.previous_ids<=set(rows) or resources!=self.resources:return False
        row=rows[new.pop()]
        if row.get('state')==2 and table(row.get('target')):
            goal=row['target']
            destination=(goal.get('charId')==self.target_id and goal.get('charType')==6
                and goal.get('resType')==self.resource and goal.get('playerId')==0)
        elif row.get('state')==6:
            resource=state.values.get('gather_target')
            rss=resource.get('rss') if table(resource) else None
            destination=(row.get('charId')==self.target_id and row.get('charType')==6
                and table(rss) and resource.get('id')==self.target_id and rss.get('resType')==self.resource
                and rss.get('playerId')==state.player_id and number(row.get('collectSpeed')) and row['collectSpeed']>0)
        else:return False
        troop=row['troop']
        heroes=troop.get('heros')
        if not table(heroes) or len(heroes)!=len(self.heroes) or any(not table(h) for h in heroes.values()):return False
        return (destination and unit_ledger(troop.get('units'))==self.units
            and {str(h.get('label')):h.get('heroId') for h in heroes.values()}==self.heroes)


@dataclass(frozen=True)
class GatherCycle:
    options: GatherOptions

    def __call__(self,input_device,observe,cancelled,clock,allowed):
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Сбор отменён')
        def wait(predicate,message):
            deadline=clock()+20
            while True:
                permit()
                state=observe()
                if predicate(state):return state
                if clock()>=deadline:raise WorkflowError(message)
                if cancelled.wait(.1):raise Cancelled('Сбор отменён')
        def tap(x,y):
            permit();input_device.tap(x,y,hold_ms=100)
        def panel(state,*names):
            return set(state.values.get('views',{}))<=set(CITY_VIEWS+('CommonBackground',)+names)
        def visible(state,name):return state.values.get('gather_view_'+name) is True
        def return_city():
            from .workflows import Engine
            return Engine(input_device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
                RETURN_TO_CITY,cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        initial=state=observe()
        own_troops(state)
        known=('MapUISearchMainPage','MapUISearchPopUp','ResDepositPopUp','MapUISelectTroops','TroopSelectedPopUp','SendTroopsMain')
        # On resumption discard only our known navigation/forms, never an unknown modal.
        # Recheck server armies first: a delivered march remains occupied after a pause.
        for _ in range(4):
            active=set(state.values.get('views',{}))&set(known)
            if not active:break
            if not panel(state,*known):raise NotReady('Сбор: форма перекрыта неизвестным окном')
            permit();input_device.back()
            state=wait(lambda s:set(s.values.get('views',{}))&set(known)!=active,
                       'Сбор: закрытие старой формы не подтверждено')
        else:raise NotReady('Сбор: старая форма не закрылась за четыре перехода')
        state=return_city()
        if not CITY_HUD.matches(state):raise NotReady('Сбор: нужен свободный город')
        if len(own_troops(state))>=self.options.max_marches:return state
        category,search_x,_=SEARCH_LAYOUT[self.options.resource]
        tap(45,490)
        state=wait(lambda s:s.values.get('city_enabled') is False and panel(s),'Сбор: выход на карту не подтверждён')
        tap(45,400)
        state=wait(lambda s:visible(s,'MapUISearchMainPage') and panel(s,'MapUISearchMainPage','MapUISearchPopUp'),
                   'Сбор: поиск не открыт')
        tap(category,470)
        state=wait(lambda s:search_popup_matches(s,self.options.resource),
                   'Сбор: вкладка ресурса и положение поиска не подтверждены')
        for _ in range(8):
            current=search_level(state,self.options.resource)
            if not integer(current,1) or current>8:raise NotReady('Сбор: неизвестный уровень поиска')
            if current==self.options.level:break
            if (not panel(state,'MapUISearchMainPage','MapUISearchPopUp')
                    or not search_popup_matches(state,self.options.resource)):raise NotReady('Сбор: поиск перекрыт или перемещён')
            tap(search_x+(-105 if current>self.options.level else 105),315)
            expected=current+(-1 if current>self.options.level else 1)
            state=wait(lambda s:search_level(s,self.options.resource)==expected,
                       'Сбор: изменение уровня не подтверждено')
        else:raise NotReady('Сбор: уровень поиска не достигнут')
        if not search_popup_matches(state,self.options.resource):raise NotReady('Сбор: окно поиска изменилось')
        tap(search_x,365)
        state=wait(lambda s:visible(s,'ResDepositPopUp') and panel(s,'ResDepositPopUp'),'Сбор: цель не найдена')
        target_id=target(state,self.options)['id']
        tap(690,365)
        state=wait(lambda s:visible(s,'MapUISelectTroops') and panel(s,'MapUISelectTroops','TroopSelectedPopUp'),
                   'Сбор: выбор марша не открыт')
        if (state.values.get('gather_select_target')!=target_id
                or state.values.get('gather_select_resource')!=self.options.resource):raise NotReady('Сбор: цель выбора марша изменилась')
        tap(755,110)
        state=wait(lambda s:visible(s,'SendTroopsMain') and panel(s,'SendTroopsMain'),'Сбор: форма марша не открыта')
        # Reobserve immediately before the only sending input, including target occupancy.
        state=observe()
        receipt=MarchReceipt.capture(state,self.options)
        if receipt.target_id!=target_id:raise NotReady('Сбор: ресурсная цель изменилась')
        tap(695,475)
        wait(receipt.matches,'Сбор: квитанция отправки не получена; повтор запрещён')
        return return_city()


def gather_workflow(settings,*,verified=False):
    options=GatherOptions.from_settings(settings)
    if options.resource not in GATHER_RESOURCES:
        raise ValueError('Выберите еду, дерево, камень или золото')
    return Workflow('gather_resources','1.1.12.20',960,540,
        (Procedure(GatherCycle(options)),),verified=verified,
        extra_paths=FIELDS,requires_city=False)
