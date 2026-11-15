"""Ordinary discovered caves: native identities and exact first-scout dispatch receipts."""
from copy import deepcopy
from dataclasses import dataclass

from .scout_fog import FIELDS as SCOUT_FIELDS, FORM, MANAGEMENT, Panel, context, money, open_management
from .scout_places import CAVE, POPUP, VillagePanel, first_place_row, pending_places, place_target
from .supply_boxes import integer, inventory, table
from .workflows import (AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, MAP_HUD,
    NotReady, Procedure, RETURN_TO_CITY, Tap, Workflow, WorkflowError)


FIELDS={**{key:SCOUT_FIELDS[key] for key in ('city_camera','building_menu','supply_inventory','fog_scouts',
        'fog_scout_server','fog_requested','fog_server','fog_initialized','fog_viewed_server','fog_offset_x','fog_offset_y')},
    'place_rows':['UIObjectManager',MANAGEMENT,'ListDatas'],'place_tab':['UIObjectManager',MANAGEMENT,'curTab'],
    'place_caves':['ScoutData','PlayerScoutCaveList'],'place_visited_caves':['ScoutData','OpenCaveIdMap'],
    'place_cave_ghosts':['ScoutData','OpenCaveGhostIdMap'],'place_target':['@place_target'],
    'place_popup_id':['UIObjectManager',POPUP,'m_caviId'],'place_popup_target':['UIObjectManager',POPUP,'targetId'],
    'place_view_x':['UIObjectManager','MapHudPanel','CurViewX'],'place_view_y':['UIObjectManager','MapHudPanel','CurViewY'],
    'place_zooming':['UIObjectManager','MapHudPanel','m_State','isInFirstEnterMapZooming'],
    **{'cave_form_'+key:['UIObjectManager',FORM,key] for key in
        ('targetPos','targetId','selectIndex','allScouts','IsMultiSelectMode')}}


def prepare_cave(device,observe,cancelled,clock,allowed):
    initial=observe();state=initial;scout=context(state)
    if scout['state']!=1 or scout['charId']!=0:raise NotReady('Пещеры: ожидание свободного первого разведчика')
    def permit():
        if cancelled.is_set() or not allowed():raise Cancelled('Разведка пещеры отменена')
    def execute(steps):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('cave_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    def wait(predicate,message):
        deadline=clock()+25
        while True:
            permit();s=observe()
            try:
                if predicate(s):return s
            except NotReady:pass
            if clock()>=deadline:raise WorkflowError(message)
            if cancelled.wait(.1):raise Cancelled('Разведка пещеры отменена')
    candidates=pending_places(state,CAVE);ghosts=state.values.get('place_cave_ghosts')
    if not table(ghosts):raise NotReady('Пещеры: особые посещения не прочитаны')
    if not candidates:raise NotReady('Пещеры: нет непосещённых обнаруженных целей')
    state=open_management(state,device,observe,cancelled,clock,allowed,execute)
    state=execute((Tap(570,160,Panel(MANAGEMENT),Condition(('place_tab',),'eq',3),hold_ms=100,settle=.4),))
    candidate=first_place_row(state,CAVE)
    if candidate is None or str(candidate['caviId']) in ghosts:raise NotReady('Пещеры: обычная непосещённая строка не подтверждена')
    for _ in range(2):
        current=first_place_row(state,CAVE)
        if current!=candidate or not Panel(MANAGEMENT).matches(state):raise NotReady('Пещеры: строка изменилась перед переходом')
        permit();device.tap(742,candidate['ui_y'],hold_ms=100)
        if cancelled.wait(1):raise Cancelled('Разведка пещеры отменена')
        state=wait(AnyOf((Panel(MANAGEMENT),MAP_HUD,VillagePanel())).matches,'Пещеры: переход к карте не подтверждён')
        if not Panel(MANAGEMENT).matches(state):break
    if Panel(MANAGEMENT).matches(state):raise NotReady('Пещеры: подсказка перекрывает переход')
    def centered(s):
        target=place_target(s,candidate);v=s.values
        if target['cave'].get('isClientCave') is True or target['cave'].get('cavType')!=0:
            raise NotReady('Пещеры: цель не является обычной пещерой')
        return (v.get('place_zooming') is False and all(abs(v.get('place_view_'+axis,0)-target['pos'][axis])<.05 for axis in ('x','y')))
    state=wait(centered,'Пещеры: точный загруженный объект не подтверждён')
    target=place_target(state,candidate)
    state=execute((Tap(480,250,MAP_HUD,VillagePanel(),hold_ms=100,settle=.5),))
    if (state.values.get('place_popup_id')!=candidate['caviId'] or state.values.get('place_popup_target')!=target['id']):
        raise NotReady('Пещеры: popup относится к другой цели')
    state.values['cave_preview_id']=candidate['caviId'];state.values['cave_preview_target']=target['id']
    return state


CAVE_PREVIEW=Workflow('cave_preview','1.1.12.20',960,540,(Procedure(prepare_cave),),verified=True,
    extra_paths=FIELDS,requires_city=False,
    precondition=Condition(('views',),'subset',CITY_VIEWS+(MANAGEMENT,POPUP,'CommonBackground')))


@dataclass(frozen=True)
class CaveReceipt:
    candidate: dict
    target_id: int
    scouts: dict
    visited: dict
    ghosts: dict
    resources: dict
    items: dict

    @classmethod
    def capture(cls,state):
        row=context(state);v=state.values;target=v.get('place_target');available=v.get('cave_form_allScouts')
        candidate=pending_places(state,CAVE).get(str(target['cave'].get('caviId'))) if table(target) and table(target.get('cave')) else None
        if candidate is None:raise NotReady('Пещеры: цель формы уже посещена или не обнаружена')
        target=place_target(state,candidate);ghosts=v.get('place_cave_ghosts')
        if (not table(ghosts) or str(candidate['caviId']) in ghosts or target['cave'].get('cavType')!=0
                or target['cave'].get('isClientCave') is True or target['id']%100!=0 or not Panel(FORM).matches(state)
                or v.get('cave_form_targetId')!=target['id'] or v.get('cave_form_selectIndex')!=1
                or type(v.get('cave_form_selectIndex')) is not int or v.get('cave_form_IsMultiSelectMode') is not False
                or v.get('cave_form_targetPos')!={'1':target['pos']['x'],'2':target['pos']['y']}
                or not table(available) or set(available)!={'1'} or not table(available['1'])
                or available['1'].get('idx')!=1 or available['1'].get('selected') is not True
                or any(available['1'].get(key)!=value or row.get(key)!=value for key,value in
                    (('state',1),('charId',0),('targetId',0)))):
            raise NotReady('Пещеры: обычная цель и свободный одиночный разведчик в форме не подтверждены')
        return cls(deepcopy(candidate),target['id'],deepcopy(v['fog_scouts']),deepcopy(v['place_visited_caves']),
            deepcopy(ghosts),money(state),inventory(state))

    def matches(self,state):
        row=context(state);v=state.values
        if (row.get('state')!=3 or not integer(row.get('charId'),1)
                or any(type(row.get(key)) is not int for key in ('targetSubId','targetSubType','targetCharType','targetId','groupSize'))
                or row.get('targetSubId')!=self.candidate['caviId']
                or row.get('targetSubType')!=0 or row.get('targetCharType')!=10 or row.get('targetId',0)*100!=self.target_id
                or row.get('groupSize')!=self.scouts['1'].get('groupSize') or money(state)!=self.resources
                or inventory(state)!=self.items or v.get('place_visited_caves')!=self.visited
                or v.get('place_cave_ghosts')!=self.ghosts or set(v['fog_scouts'])!=set(self.scouts)):return False
        return all(key=='1' or {k:value for k,value in previous.items() if k!='selected'}=={
            k:value for k,value in v['fog_scouts'][key].items() if k!='selected'} for key,previous in self.scouts.items())


def explore_cave(device,observe,cancelled,clock,allowed):
    initial=observe();state=initial;row=context(state)
    def execute(steps):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('cave_dispatch_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    def wait(predicate,message):
        deadline=clock()+25
        while True:
            if cancelled.is_set() or not allowed():raise Cancelled('Разведка пещеры отменена')
            s=observe()
            if predicate(s):return s
            if clock()>=deadline:raise WorkflowError(message)
            if cancelled.wait(.1):raise Cancelled('Разведка пещеры отменена')
    def return_city(s):
        if Panel(MANAGEMENT).matches(s):
            s=execute((Tap(818,62,Panel(MANAGEMENT),AnyOf((CITY_HUD,MAP_HUD)),hold_ms=100,settle=.3),))
        if VillagePanel().matches(s):
            target=s.values.get('place_target')
            if not table(target) or target.get('charType')!=10 or not table(target.get('cave')) or target['cave'].get('cavType')!=0:
                raise NotReady('Пещеры: ожидание закрытия другого объекта карты')
            s=execute((Tap(900,400,VillagePanel(),MAP_HUD,hold_ms=100,settle=.3),))
        return s if CITY_HUD.matches(s) else execute(RETURN_TO_CITY.steps)
    if row['state']!=1 or row['charId']!=0:
        if Panel(FORM).matches(state):state=wait(lambda s:not Panel(FORM).matches(s),'Пещеры: форма принятой отправки ещё открыта')
        return return_city(state)
    if not pending_places(state,CAVE):return return_city(state)
    if not Panel(FORM).matches(state):
        if not VillagePanel().matches(state):state=prepare_cave(device,observe,cancelled,clock,allowed)
        target=state.values.get('place_target')
        candidate=pending_places(state,CAVE).get(str(target['cave'].get('caviId'))) if table(target) and table(target.get('cave')) else None
        if candidate is None:raise NotReady('Пещеры: выбранная обычная цель не подтверждена')
        target=place_target(state,candidate)
        if target['cave'].get('cavType')!=0 or target['cave'].get('isClientCave') is True:
            raise NotReady('Пещеры: особая или радарная цель не обслуживается')
        state=execute((Tap(681,360,VillagePanel(),Panel(FORM),hold_ms=100,settle=.5),))
    receipt=CaveReceipt.capture(state)
    if cancelled.is_set() or not allowed():raise Cancelled('Разведка пещеры отменена')
    device.tap(755,124,hold_ms=100)
    state=wait(receipt.matches,'Пещеры: точная отправка не подтверждена; повтор запрещён')
    if Panel(FORM).matches(state):state=wait(lambda s:not Panel(FORM).matches(s),'Пещеры: ожидание закрытия формы')
    state=return_city(state)
    state.values['cave_dispatched']=1;state.values['cave_dispatched_id']=receipt.candidate['caviId']
    state.values['cave_dispatched_target']=receipt.target_id
    return state


CAVES=Workflow('caves','1.1.12.20',960,540,(Procedure(explore_cave),),verified=True,
    extra_paths=FIELDS,requires_city=False,
    precondition=Condition(('views',),'subset',CITY_VIEWS+(MANAGEMENT,POPUP,FORM,'CommonBackground')))
