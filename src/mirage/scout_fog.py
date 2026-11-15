"""Dispatch the first unlocked scout to the game's fresh fog target, with an exact receipt."""
from copy import deepcopy
from dataclasses import dataclass
import math

from .navigation import navigate_city
from .supply_boxes import integer, inventory, table
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine,
    MAP_HUD, NotReady, Procedure, QUEUE_CLOSE, RETURN_TO_CITY, SELECTION_CLEAR, Tap, Workflow, WorkflowError)


MANAGEMENT='CityUIScoutsManagement'
POPUP='MapUISelectScoutsPopUp'
FORM='MapUISelectScouts'
FIELDS={'city_camera':['@city_camera'],'building_menu':['@building_menu'],
    'supply_inventory':['@item_counts'],'fog_scouts':['ScoutData','AllScouts'],
    'fog_scout_server':['ScoutData','curDataServerId'],'fog_requested':['ScoutData','reqDone'],
    'fog_server':['FogMgr','m_serverId'],'fog_initialized':['FogMgr','m_isInit'],
    'fog_viewed_server':['ViewOtherMapMgr','curViewServerId'],
    'fog_pixel':['FogMgr','MAP_PIXEL_SIZE'],'fog_size':['FogMgr','MAP_SIZE'],
    'fog_offset_x':['FogMgr','m_kingdomOffsetX'],'fog_offset_y':['FogMgr','m_kingdomOffsetY'],
    'fog_management_scouts':['UIObjectManager',MANAGEMENT,'m_scouts'],
    'fog_management_tab':['UIObjectManager',MANAGEMENT,'curTab'],
    'fog_popup_position':['UIObjectManager',POPUP,'m_objWorldPos'],
    'fog_popup_size':['UIObjectManager',POPUP,'m_blockSize'],
    'fog_popup_forbid':['UIObjectManager',POPUP,'m_popForbid'],
    **{'fog_form_'+key:['UIObjectManager',FORM,key] for key in
       ('targetPos','targetId','selectIndex','allScouts','IsMultiSelectMode','MultiSelects','lastEndPos')}}


def visible(state,name):return state.values.get('views',{}).get(name) is True


def panel(state,name):
    extra=('CommonBackground',) if name==MANAGEMENT else ()
    return visible(state,name) and set(state.values['views'])<=set(CITY_VIEWS+(name,)+extra)


def number(value):return type(value) in (int,float) and math.isfinite(value)


def context(state):
    v=state.values;server=v.get('player',{}).get('ServerID')
    if (not integer(server,1) or v.get('fog_server')!=server or v.get('fog_scout_server')!=server
            or v.get('fog_viewed_server')!=0 or v.get('fog_requested') is not True
            or v.get('fog_initialized') is not True or not table(v.get('fog_scouts'))):
        raise NotReady('Разведка: текущая домашняя карта и свежие данные не подтверждены')
    row=v['fog_scouts'].get('1')
    if (not table(row) or not integer(row.get('idx'),1) or row['idx']!=1 or not integer(row.get('charId'))
            or not integer(row.get('state'),1) or row['state']>9):
        raise NotReady('Разведка: состояние первого разведчика не прочитано')
    return row


def money(state):
    rows=state.values.get('resources')
    if not table(rows) or not rows or any(not key.isdecimal() or not integer(value) for key,value in rows.items()):
        raise NotReady('Разведка: полный баланс не прочитан')
    return dict(rows)


def destination(state,position,group):
    """Match the native fog block lattice using the current map's own dimensions."""
    v=state.values;pixel,size=v.get('fog_pixel'),v.get('fog_size')
    ox,oy=v.get('fog_offset_x'),v.get('fog_offset_y')
    if (not table(position) or any(not number(position.get(key)) for key in ('1','2'))
            or not integer(pixel,1) or not integer(size,1) or not integer(group,1)
            or group>20 or any(not number(value) for value in (ox,oy))):
        raise NotReady('Разведка: положение цели или сетка тумана не прочитаны')
    step=pixel/size;result={}
    for axis,value,offset in (('x',position['1'],ox),('y',position['2'],oy)):
        local=value-offset
        if not 0<=local<pixel:raise NotReady('Разведка: цель вне текущей домашней карты')
        projected=math.floor(local/(step*group))*step*group
        if abs(projected-round(projected))>.001:raise NotReady('Разведка: целочисленная сетка не подтверждена')
        result[axis]=round(projected)
    return result


@dataclass(frozen=True)
class ScoutFogReceipt:
    server: int
    group: int
    target: dict
    previous: dict
    resources: dict
    items: dict

    @classmethod
    def capture(cls,state):
        row=context(state);v=state.values;available=v.get('fog_form_allScouts')
        if (not panel(state,FORM) or v.get('fog_form_targetId') is not None and
                    (not integer(v['fog_form_targetId']) or v['fog_form_targetId']!=0)
                or v.get('fog_form_IsMultiSelectMode') is not False or type(v.get('fog_form_selectIndex')) is not int
                or v['fog_form_selectIndex']!=1 or not table(available) or set(available)!={'1'}
                or not table(available['1']) or available['1'].get('idx')!=1
                or available['1'].get('selected') is not True or available['1'].get('state')!=1
                or available['1'].get('charId')!=0 or available['1'].get('groupSize')!=row.get('groupSize')
                or row.get('state')!=1 or row.get('charId')!=0 or row.get('targetId')!=0
                or v.get('fog_form_targetPos')!=v.get('fog_form_lastEndPos')):
            raise NotReady('Разведка: свободный одиночный разведчик и форма тумана не подтверждены')
        group=row.get('groupSize');target=destination(state,v.get('fog_form_targetPos'),group)
        return cls(v['fog_server'],group,target,deepcopy(v['fog_scouts']),money(state),inventory(state))

    def matches(self,state):
        context(state);v=state.values;row=v['fog_scouts']['1']
        if (v['fog_server']!=self.server or money(state)!=self.resources or inventory(state)!=self.items
                or row.get('state')!=2 or not integer(row.get('charId'),1) or row.get('targetId')!=0
                or row.get('groupSize')!=self.group or row.get('fogDstGrid')!=self.target
                or any(row.get(key)!=0 for key in ('targetSubId','targetSubType','targetCharType'))
                or set(v['fog_scouts'])!=set(self.previous)):return False
        for key,previous in self.previous.items():
            if key=='1':continue
            if {k:value for k,value in previous.items() if k!='selected'}!={
                    k:value for k,value in v['fog_scouts'][key].items() if k!='selected'}:return False
        return True


def open_management(state,device,observe,cancelled,clock,allowed,execute):
    """Open the live scout camp menu; shared by fog and discovered-place workflows."""
    if panel(state,MANAGEMENT):return state
    if not CITY_HUD.matches(state):state=execute(RETURN_TO_CITY.steps)
    state=execute((QUEUE_CLOSE,*SELECTION_CLEAR))
    owned=[key for key,b in state.values['buildings'].items() if table(b) and b.get('type')==28 and b.get('state')==1]
    if len(owned)!=1:raise NotReady('Разведка: готовый разведлагерь не подтверждён')
    building=owned[0]
    state=navigate_city(device,observe,cancelled,clock,28,allowed,building_id=building,select=False)
    point=state.values['city_navigation_target']['point']
    state=execute((Tap(*point,CITY_HUD,Condition(('city_selection',),'eq',building),hold_ms=100,settle=.4),))
    selected=state.values.get('building_menu',{}).get('selected',{})
    if (selected.get('id')!=building or selected.get('type')!=28 or set(selected.get('buttons',[]))!={
            'btn_CityPopUpInfo','btn_CityPopUpUpgrade','btn_FunctionScoutCamp','btn_CityPopUpRadar'}):
        raise NotReady('Разведка: обычное меню разведлагеря не подтверждено')
    return execute((Tap(point[0]+50,point[1]+105,Condition(('city_selection',),'eq',building),
        Panel(MANAGEMENT),hold_ms=100,settle=.4),))


def explore_fog(device,observe,cancelled,clock,allowed):
    initial=observe();state=initial
    def permit():
        if cancelled.is_set() or not allowed():raise Cancelled('Разведка отменена')
    def execute(steps):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('scout_fog_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    def wait_for(predicate,reason):
        deadline=clock()+20
        while True:
            permit();s=observe()
            if predicate(s):return s
            if clock()>=deadline:raise WorkflowError(reason)
            if cancelled.wait(.1):raise Cancelled('Разведка отменена')
    def return_city(s):
        if not CITY_HUD.matches(s):s=execute(RETURN_TO_CITY.steps)
        return s
    row=context(state)
    if row['state']!=1 or row['charId']!=0:
        if panel(state,MANAGEMENT):state=execute((Tap(818,62,Panel(MANAGEMENT),CITY_HUD,hold_ms=100),))
        if visible(state,FORM):state=wait_for(lambda s:not visible(s,FORM),'Разведка: ожидание закрытия принятой отправки')
        if visible(state,POPUP):raise NotReady('Разведка: выбранный разведчик уже занят')
        return return_city(state)
    if not any(visible(state,name) for name in (MANAGEMENT,POPUP,FORM)):
        state=open_management(state,device,observe,cancelled,clock,allowed,execute)
    if panel(state,MANAGEMENT):
        state=execute((Tap(225,160,Panel(MANAGEMENT),Condition(('fog_management_tab',),'eq',1),
            hold_ms=100,settle=.4,when=Condition(('fog_management_tab',),'ne',1)),))
        rows=state.values.get('fog_management_scouts')
        if (not table(rows) or set(rows)!={'1'} or rows['1'].get('idx')!=1 or rows['1'].get('state')!=1):
            raise NotReady('Разведка: проверенная единственная строка свободного разведчика не найдена')
        state=execute((Tap(742,267,Panel(MANAGEMENT),Panel(POPUP),hold_ms=100,settle=1),))
    if panel(state,POPUP):
        v=state.values;p=v.get('fog_popup_position');row=context(state);camera=v.get('city_camera')
        if (not table(p) or v.get('fog_popup_forbid') not in (None,False) or v.get('fog_popup_size')!=row.get('groupSize')
                or any(not number(p.get(key)) for key in ('1','2','3')) or abs(p['2'])>.001):
            raise NotReady('Разведка: свежий обычный предпросмотр участка не подтверждён')
        if (not table(camera) or camera.get('moving') is not False
                or any(not number(camera.get(axis)) or abs(camera[axis]-p[key])>.05 for axis,key in (('x','1'),('y','3')))):
            raise NotReady('Разведка: предпросмотр участка вне проверенного центра карты')
        target={'1':p['1'],'2':p['3']};destination(state,target,row['groupSize'])
        state=execute((Tap(603,357,Panel(POPUP),Panel(FORM),hold_ms=100,settle=.5),))
        if state.values.get('fog_form_targetPos')!=target:raise NotReady('Разведка: цель изменилась при выборе разведчика')
    receipt=ScoutFogReceipt.capture(state);permit();device.tap(755,124,hold_ms=100)
    state=wait_for(receipt.matches,'Разведка: точная отправка в туман не подтверждена; повтор запрещён')
    if visible(state,FORM):state=wait_for(lambda s:not visible(s,FORM),'Разведка: ожидание закрытия формы отправки')
    state=return_city(state);state.values['scout_fog_dispatched']=1;state.values['scout_fog_target']=receipt.target
    return state


class Panel:
    def __init__(self,name):self.name=name
    def matches(self,state):return panel(state,self.name)


SCOUT_FOG=Workflow('scout_fog','1.1.12.20',960,540,(Procedure(explore_fog),),verified=True,
    precondition=All((Condition(('hud_visible',),'eq',True),Condition(('hud_menu',),'eq',False),
        Condition(('views',),'subset',CITY_VIEWS+(MANAGEMENT,POPUP,FORM,'CommonBackground')))),
    when=AnyOf((Condition(('fog_scouts','1','state'),'eq',1),Panel(MANAGEMENT),Panel(POPUP),Panel(FORM),
        Condition(('in_city',),'eq',False),Condition(('city_enabled',),'eq',False))),
    extra_paths=FIELDS,requires_city=False,wait_reason='Ожидание свободного первого разведчика и подтверждённой домашней карты')
