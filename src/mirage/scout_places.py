"""Visit discovered places using current-server identities and their native UI rows."""
from copy import deepcopy
from dataclasses import dataclass

from .city_resources import completed_receipt
from .scout_fog import FIELDS as SCOUT_FIELDS, MANAGEMENT, Panel, context, money, number, open_management
from .supply_boxes import integer, inventory, table
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, MAP_HUD,
    NotReady, Procedure, QUEUE_CLOSE, RETURN_TO_CITY, SELECTION_CLEAR, Tap, Workflow, WorkflowError)


VILLAGE=11
CAVE=10
POPUP='MapUnkownCityPopUp'
FIELDS={**{key:SCOUT_FIELDS[key] for key in ('city_camera','building_menu','supply_inventory','fog_scouts',
        'fog_scout_server','fog_requested','fog_server','fog_initialized','fog_viewed_server','fog_offset_x','fog_offset_y')},
    'place_rows':['UIObjectManager',MANAGEMENT,'ListDatas'],
    'place_tab':['UIObjectManager',MANAGEMENT,'curTab'],
    'place_villages':['ScoutData','PlayerScoutVillageList'],
    'place_visited_villages':['ScoutData','OpenVillageIdMap'],
    'place_target':['@place_target'],
    'place_popup_id':['UIObjectManager','MapUnkownCityPopUp','m_caviId'],
    'place_popup_target':['UIObjectManager','MapUnkownCityPopUp','targetId'],
    'place_popup_kind':['UIObjectManager','MapUnkownCityPopUp','m_showType'],
    'place_loot':['UIObjectManager','MapUnkownCityPopUp','Loot'],
    'place_packet':['UIObjectManager','MapUnkownCityPopUp','openParam'],
    'place_reward_types':['RewardHandler','Type'],
    'place_near':['UIObjectManager',POPUP,'nearVillage'],
    'place_techniques':['TechniqueData','Datas'],
    'harvest_receipts':['CityBuildData','UserRssAniData'],
    'place_view_x':['UIObjectManager','MapHudPanel','CurViewX'],
    'place_view_y':['UIObjectManager','MapHudPanel','CurViewY'],
    'place_zooming':['UIObjectManager','MapHudPanel','m_State','isInFirstEnterMapZooming']}


def pending_places(state,kind):
    context(state)
    if kind not in (VILLAGE,CAVE):raise ValueError('Unsupported discovered-place type')
    suffix='villages' if kind==VILLAGE else 'caves'
    rows=state.values.get('place_'+suffix);visited=state.values.get('place_visited_'+suffix)
    if not table(rows) or not table(visited):raise NotReady('Разведка мест: список целей или посещений не прочитан')
    result={}
    for row in rows.values():
        if (not table(row) or row.get('type')!=kind or not integer(row.get('caviId'),1)
                or not table(row.get('pos')) or any(not number(row['pos'].get(axis)) for axis in ('x','y'))
                or not number(row.get('findTm')) or row['findTm']<=0):
            raise NotReady('Разведка мест: неполная идентичность обнаруженной цели')
        key=str(row['caviId'])
        if key in result:raise NotReady('Разведка мест: повторяющаяся идентичность цели')
        if key not in visited:result[key]=deepcopy(row)
    return result


def first_place_row(state,kind):
    candidates=pending_places(state,kind);rows=state.values.get('place_rows')
    if (state.values.get('place_tab')!=(2 if kind==VILLAGE else 3) or not table(rows)):
        raise NotReady('Разведка мест: нужная вкладка управления не подтверждена')
    if not candidates:return None
    y=251
    for index in range(1,4):
        row=rows.get(str(index))
        if not table(row) or not number(row.get('height')) or not 0<row['height']<=512:
            raise NotReady('Разведка мест: размер видимых строк не прочитан')
        if y>450:break
        if str(row.get('caviId')) in candidates:
            if (row.get('type')!=kind or row.get('prefab_type')!='CityUIScoutsManagementListBar'
                    or row.get('isExplored') is not False):
                raise NotReady('Разведка мест: непосещённая строка не подтверждена')
            candidate=candidates[str(row['caviId'])]
            if any(row.get(key)!=candidate.get(key) for key in ('caviId','type','pos','findTm')):
                raise NotReady('Разведка мест: строка интерфейса не совпадает с текущим обнаружением')
            return {**candidate,'ui_index':index,'ui_y':round(y)}
        y+=row['height']*.8
    raise NotReady('Разведка мест: непосещённая цель вне проверенной видимой области')


def units(state):
    rows=state.values.get('troops');result={}
    if not table(rows):raise NotReady('Деревни: войска не прочитаны')
    for row in rows.values():
        if (not table(row) or not integer(row.get('unitId'),1)
                or any(not integer(row.get(key)) for key in ('unitCount','hurt','badHurt'))):
            raise NotReady('Деревни: состав войск не подтверждён')
        key=str(row['unitId'])
        if key in result:raise NotReady('Деревни: повторяющийся тип войск')
        counts={name:row[name] for name in ('unitCount','hurt','badHurt')}
        if any(counts.values()):result[key]=counts
    return result


def techniques(state):
    rows=state.values.get('place_techniques');result={}
    if not table(rows):raise NotReady('Деревни: технологии не прочитаны')
    for row in rows.values():
        if not table(row) or not integer(row.get('Type'),1) or not integer(row.get('Level')):
            raise NotReady('Деревни: уровни технологий не подтверждены')
        key=str(row['Type'])
        if key in result:raise NotReady('Деревни: повторяющаяся технология')
        if row['Level']>0:result[key]=row['Level']
    return result


def assets(state):return money(state),inventory(state),units(state),techniques(state)


def place_target(state,candidate):
    context(state);target=state.values.get('place_target');kind=candidate.get('type')
    detail='village' if kind==VILLAGE else 'cave'
    if (not table(target) or not integer(target.get('id'),1) or target.get('charType')!=kind
            or not table(target.get(detail)) or target[detail].get('caviId')!=candidate.get('caviId')
            or target[detail].get('isClientVillage') is True or not table(target.get('pos'))):
        raise NotReady('Разведка мест: загруженный объект выбранной цели не подтверждён')
    for axis in ('x','y'):
        expected=candidate['pos'][axis]+state.values['fog_offset_'+axis]
        if not number(target['pos'].get(axis)) or abs(target['pos'][axis]-expected)>.05:
            raise NotReady('Разведка мест: координаты объекта не совпадают с обнаружением')
    return target


def village_packet(state,candidate=None):
    """Read the server gift cached by the selected village's own popup."""
    context(state);v=state.values;target=v.get('place_target');packet=v.get('place_packet');loot=v.get('place_loot')
    if (not table(target) or target.get('charType')!=VILLAGE or not integer(target.get('id'),1)
            or not table(target.get('village')) or target['village'].get('isClientVillage') is True
            or not integer(target['village'].get('caviId'),1) or v.get('place_popup_kind')!=1
            or v.get('place_popup_id')!=target['village']['caviId'] or v.get('place_popup_target')!=target['id']
            or not table(packet) or not integer(packet.get('CharId'),1) or packet['CharId']*100!=target['id']
            or not table(loot) or not integer(loot.get('Type'),1) or not integer(loot.get('SubType'),1)
            or not integer(loot.get('Value'),1)):
        raise NotReady('Деревни: полученная награда не связана с выбранной обычной деревней')
    if candidate is not None:place_target(state,candidate)
    rows=[];tech=packet.get('Tech')
    if tech is not None:
        if not table(tech) or not integer(tech.get('Type'),1) or not integer(tech.get('Level'),1):
            raise NotReady('Деревни: уровень подаренной технологии не прочитан')
    if packet.get('Loots') is not None:
        container=packet['Loots'];values=container.get('Loots') if table(container) else None
        if not table(values) or not 1<=len(values)<=16 or set(values)!={str(i) for i in range(1,len(values)+1)}:
            raise NotReady('Деревни: состав серверного подарка не прочитан')
        rows.extend(values.values())
    if packet.get('Troop') is not None:rows.append(packet['Troop'])
    if not rows and tech is None:raise NotReady('Деревни: пустая серверная награда')
    for row in rows:
        if (not table(row) or type(row.get('Type')) is not int or row['Type'] not in (1,2,3,8)
                or not integer(row.get('SubType'),1) or not integer(row.get('Value'),1)):
            raise NotReady('Деревни: неподдержанный вид подарка')
    shown=any(all(loot[key]==row[key] for key in ('Type','SubType','Value')) for row in rows)
    if tech is not None:
        codes=v.get('place_reward_types')
        shown=shown or (table(codes) and loot['Type']==codes.get('Tech')
            and loot['SubType']==tech['Type'] and loot['Value']==tech['Level'])
    if not shown:raise NotReady('Деревни: показанная награда отличается от серверной')
    return target['village']['caviId'],deepcopy(rows),deepcopy(tech)


@dataclass(frozen=True)
class VillageGrant:
    visited: dict
    resources: dict
    items: dict
    troops: dict
    tech: dict
    currencies: tuple

    def matches(self,state):
        return (state.values.get('place_visited_villages')==self.visited
            and assets(state)==(self.resources,self.items,self.troops,self.tech)
            and all(completed_receipt(state,kind)==self.resources[str(kind)] for kind in self.currencies))


@dataclass(frozen=True)
class VillageReceipt:
    candidate: dict
    visited: dict
    resources: dict
    items: dict
    troops: dict
    tech: dict

    @classmethod
    def capture(cls,state,candidate):
        candidates=pending_places(state,VILLAGE);key=str(candidate.get('caviId'))
        if key not in candidates or any(candidate.get(name)!=candidates[key].get(name) for name in ('type','pos','findTm')):
            raise NotReady('Деревни: цель уже получена или изменилась')
        v=state.values
        return cls(deepcopy(candidate),deepcopy(v['place_visited_villages']),*assets(state))

    def can_select(self,state):
        if not MAP_HUD.matches(state):return False
        place_target(state,self.candidate);v=state.values
        if (v.get('place_zooming') is not False or any(not number(v.get('place_view_'+axis)) or
                abs(v['place_view_'+axis]-self.candidate['pos'][axis]-v['fog_offset_'+axis])>.05 for axis in ('x','y'))):
            return False
        if v.get('place_visited_villages')!=self.visited or assets(state)!=(self.resources,self.items,self.troops,self.tech):
            raise WorkflowError('Деревни: активы или посещения изменились до выбора карты')
        return True

    def grant(self,state):
        place_id,rows,tech=village_packet(state,self.candidate)
        if place_id!=self.candidate['caviId']:raise NotReady('Деревни: получена другая цель')
        visited={**self.visited,str(place_id):True}
        if state.values.get('place_visited_villages')!=visited:
            raise NotReady('Деревни: точное новое посещение не подтверждено')
        resources,items,troops,levels=deepcopy((self.resources,self.items,self.troops,self.tech))
        currencies=set()
        for row in rows:
            kind,key,count=row['Type'],str(row['SubType']),row['Value']
            if kind==1:
                if key not in resources:raise NotReady('Деревни: неизвестная валюта подарка')
                resources[key]+=count
                if row['SubType'] in (1,2,3,4):currencies.add(row['SubType'])
            elif kind==2:items[key]=items.get(key,0)+count
            elif kind==3:
                troops.setdefault(key,{'unitCount':0,'hurt':0,'badHurt':0})['unitCount']+=count
            else:
                if count<=self.tech.get(key,0):raise NotReady('Деревни: подаренная технология не улучшена')
                levels[key]=count
        if tech is not None:
            key=str(tech['Type'])
            if tech['Level']<=levels.get(key,0):raise NotReady('Деревни: технология не получила новый уровень')
            levels[key]=tech['Level']
        return VillageGrant(visited,resources,items,troops,levels,tuple(sorted(currencies)))


class VillagePanel:
    def matches(self,state):
        return (state.values.get('views',{}).get(POPUP) is True
            and set(state.values['views'])<=set(CITY_VIEWS+(POPUP,'TroopPowerUpHUD','CommonBackground')))


class NearVillagePanel:
    def matches(self,state):
        v=state.values;packet=v.get('place_packet')
        return (VillagePanel().matches(state) and v.get('place_near') is True and v.get('place_loot') is None
            and table(packet) and table(packet.get('nearVillage')) and packet['nearVillage'].get('type')==VILLAGE)


@dataclass(frozen=True)
class GiftPanel:
    receipt: VillageReceipt
    expected: VillageGrant

    def matches(self,state):
        if not VillagePanel().matches(state):return False
        try:return self.receipt.grant(state)==self.expected
        except NotReady:return False


@dataclass(frozen=True)
class ReceivedVillagePanel:
    place_id: int

    def matches(self,state):
        if not VillagePanel().matches(state):return False
        try:return (village_packet(state)[0]==self.place_id
            and state.values.get('place_visited_villages',{}).get(str(self.place_id)) is True)
        except NotReady:return False


def visit_village(device,observe,cancelled,clock,allowed):
    initial=observe();state=initial;context(state)
    def permit():
        if cancelled.is_set() or not allowed():raise Cancelled('Посещение деревень отменено')
    def execute(steps):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('village_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    def wait(predicate,message):
        deadline=clock()+25
        while True:
            permit();s=observe()
            try:
                if predicate(s):return s
            except NotReady:pass
            if clock()>=deadline:raise WorkflowError(message)
            if cancelled.wait(.1):raise Cancelled('Посещение деревень отменено')
    def clean(s):
        if NearVillagePanel().matches(s):
            s=execute((Tap(900,400,NearVillagePanel(),MAP_HUD,hold_ms=100,settle=.4),))
        if Panel(MANAGEMENT).matches(s):
            s=execute((Tap(818,62,Panel(MANAGEMENT),AnyOf((CITY_HUD,MAP_HUD)),hold_ms=100,settle=.4),))
        if (s.values.get('in_city') is True and s.values.get('city_enabled') is True
                and set(s.values.get('views',{}))<=set(CITY_VIEWS)):
            s=execute((QUEUE_CLOSE,*SELECTION_CLEAR))
        if not CITY_HUD.matches(s):s=execute(RETURN_TO_CITY.steps)
        if not CITY_HUD.matches(s):raise NotReady('Деревни: ожидание свободного города после получения')
        return s
    if VillagePanel().matches(state) and not NearVillagePanel().matches(state):
        place_id,rows,_=village_packet(state)
        if state.values.get('place_visited_villages',{}).get(str(place_id)) is not True:
            raise NotReady('Деревни: ожидание квитанции уже открытого подарка')
        before=assets(state);visited=deepcopy(state.values['place_visited_villages'])
        permits={}
        for row in rows:
            if row['Type']==1:permits[str(row['SubType'])]=permits.get(str(row['SubType']),0)+row['Value']
        state=execute((Tap(681,365,ReceivedVillagePanel(place_id),AnyOf((NearVillagePanel(),MAP_HUD)),hold_ms=100,settle=.4),))
        def resumed(s):
            current=assets(s)
            return (s.values.get('place_visited_villages')==visited and current[1:]==before[1:]
                and set(current[0])==set(before[0]) and all(value<=current[0][key]<=value+permits.get(key,0)
                    for key,value in before[0].items())
                and all(completed_receipt(s,int(key))==current[0][key] for key in permits if key in ('1','2','3','4')))
        state=wait(resumed,'Деревни: завершение уже полученной награды не подтверждено')
        state=clean(state);state.values['villages_claimed']=0;state.values['village_reward_resumed']=True
        return state
    state=clean(state)
    if not pending_places(state,VILLAGE):return state
    state=open_management(state,device,observe,cancelled,clock,allowed,execute)
    state=execute((Tap(395,160,Panel(MANAGEMENT),Condition(('place_tab',),'eq',2),hold_ms=100,settle=.4),))
    candidate=first_place_row(state,VILLAGE)
    if candidate is None:return clean(state)
    receipt=VillageReceipt.capture(state,candidate)
    for _ in range(2):
        row=first_place_row(state,VILLAGE)
        if row is None or row['caviId']!=candidate['caviId'] or assets(state)!=(receipt.resources,receipt.items,receipt.troops,receipt.tech):
            raise NotReady('Деревни: строка или активы изменились перед переходом к цели')
        if not Panel(MANAGEMENT).matches(state):raise NotReady('Деревни: управление закрыто перед переходом')
        permit();device.tap(742,row['ui_y'],hold_ms=100)
        if cancelled.wait(1):raise Cancelled('Посещение деревень отменено')
        state=wait(AnyOf((Panel(MANAGEMENT),MAP_HUD,VillagePanel())).matches,
            'Деревни: переход из управления не подтверждён')
        if not Panel(MANAGEMENT).matches(state):break
    if Panel(MANAGEMENT).matches(state):raise NotReady('Деревни: подсказка ещё перекрывает переход к цели')
    ready=[]
    def selected_or_received(s):
        if VillagePanel().matches(s):
            ready.append(receipt.grant(s));return True
        return receipt.can_select(s)
    state=wait(selected_or_received,'Деревни: выбранная цель не загрузилась в центре карты')
    if not ready:
        permit();device.tap(480,250,hold_ms=100)
        def received(s):
            if not VillagePanel().matches(s):return False
            ready.append(receipt.grant(s));return True
        state=wait(received,'Деревни: точное получение выбранной награды не подтверждено; повтор запрещён')
    grant=ready[0];_,rows,tech=village_packet(state,candidate)
    state=execute((Tap(681,365,GiftPanel(receipt,grant),AnyOf((NearVillagePanel(),MAP_HUD)),hold_ms=100,settle=.4),))
    state=wait(grant.matches,'Деревни: полный состав выдачи не подтверждён; повтор запрещён')
    state=clean(state);state.values['villages_claimed']=1;state.values['village_claimed_id']=candidate['caviId']
    state.values['village_reward']={'rows':rows,'tech':tech}
    return state


VILLAGES=Workflow('villages','1.1.12.20',960,540,(Procedure(visit_village),),verified=True,
    precondition=All((Condition(('hud_visible',),'eq',True),Condition(('hud_menu',),'eq',False),
        Condition(('views',),'subset',CITY_VIEWS+(MANAGEMENT,POPUP,'CommonBackground','TroopPowerUpHUD')))),
    extra_paths=FIELDS,requires_city=False,wait_reason='Ожидание непосещённых деревень на текущей домашней карте')
