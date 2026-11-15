from copy import deepcopy
import threading

import pytest

from mirage.scout_fog import FORM, MANAGEMENT, POPUP, SCOUT_FOG, ScoutFogReceipt
from mirage.workflows import CITY_HUD, CITY_VIEWS, Cancelled, Engine, NotReady, WorkflowError, workflow_for
from test_rewards import Game


class ScoutCity(Game):
    def __init__(self):
        super().__init__();self.phase='city';self.cancel_after_send=None;self.after_send=0;self.delivered=False
        scouts={str(i):{'idx':i,'state':1,'charId':0,'targetId':0,'targetSubId':0,
            'targetSubType':0,'targetCharType':0,'groupSize':5,'exploreRate':0} for i in range(1,4)}
        self.values.update(player={'ServerID':3221},resources={'1':1000,'2':1000,'3':1000,'4':1000,'5':400,'6':0,'33':10},
            supply_inventory={'ready':True,'items':{'47':2}},fog_scouts=scouts,
            buildings={'58':{'type':28,'lv':1,'state':1}},fog_server=3221,fog_scout_server=3221,
            fog_viewed_server=0,fog_initialized=True,fog_requested=True,
            fog_pixel=7200,fog_size=400,fog_offset_x=7200,fog_offset_y=0,
            fog_popup_position={'1':9612,'2':0,'3':6354},fog_popup_size=5,fog_popup_forbid=None,
            city_camera={'x':9612,'y':6354,'moving':False,'distance':150},
            fog_form_targetPos={'1':9612,'2':6354},fog_form_lastEndPos={'1':9612,'2':6354},
            fog_form_targetId=None,fog_form_selectIndex=1,fog_form_IsMultiSelectMode=False,
            fog_management_tab=1,
            building_menu={'known':True,'selected':None})
        self.prepare_form()

    def prepare_form(self):
        row=deepcopy(self.values['fog_scouts']['1']);row['selected']=True
        self.values['fog_form_allScouts']={'1':row}
        self.values['fog_management_scouts']={'1':deepcopy(self.values['fog_scouts']['1'])}

    def snapshot(self):
        if self.delivered:self.after_send+=1
        state=super().snapshot();state.values['views']=dict.fromkeys((name for name in CITY_VIEWS if name!='QuestGuide'),True)
        if self.phase in (MANAGEMENT,FORM,POPUP):state.values['views'][self.phase]=True
        if self.phase==MANAGEMENT:state.values['views']['CommonBackground']=True
        return state

    def tap(self,x,y,*,hold_ms=0):
        assert hold_ms==100;self.taps.append((x,y))
        if (x,y)==(480,270):
            self.values['city_selection']='58';self.values['building_menu']['selected']={
                'id':'58','type':28,'buttons':['btn_CityPopUpInfo','btn_CityPopUpUpgrade','btn_FunctionScoutCamp','btn_CityPopUpRadar']}
        elif (x,y)==(530,375):
            self.phase=MANAGEMENT;self.values['city_selection']=None
        elif (x,y)==(742,267):
            self.phase=POPUP;self.values.update(in_city=False,city_enabled=False)
        elif (x,y)==(225,160):self.values['fog_management_tab']=1
        elif (x,y)==(603,357):self.phase=FORM
        elif (x,y)==(755,124):
            self.phase='map';self.delivered=True
            self.values['fog_scouts']['1'].update(state=2,charId=15477950800,fogDstGrid={'x':2340,'y':6300})
            if self.cancel_after_send is not None:self.cancel_after_send.set()
        elif (x,y)==(45,490):self.phase='city';self.values.update(in_city=True,city_enabled=True)
        elif (x,y)==(818,62):self.phase='city'
        else:raise AssertionError((x,y))


def run(game,monkeypatch,cancelled=None):
    def navigate(*args,**kwargs):
        s=game.snapshot();s.values['city_navigation_target']={'point':[480,270],'id':'58'};return s
    monkeypatch.setattr('mirage.scout_fog.navigate_city',navigate)
    def clock():game.time+=.5;return game.time
    return Engine(game,game.snapshot,clock=clock,resolution=(960,540)).execute(
        SCOUT_FOG,cancelled or threading.Event(),instance_id='one',pid=10,player_id=20)


def form_state():
    game=ScoutCity();game.phase=FORM;game.values.update(in_city=False,city_enabled=False)
    return game.snapshot()


def test_fog_dispatch_navigates_first_scout_and_returns_to_city_with_exact_block(monkeypatch):
    game=ScoutCity();after=run(game,monkeypatch)
    assert CITY_HUD.matches(after) and after.values['scout_fog_target']=={'x':2340,'y':6300}
    assert game.taps==[(480,270),(530,375),(742,267),(603,357),(755,124),(45,490)]
    assert after.values['resources']['33']==10 and after.values['supply_inventory']['items']=={'47':2}


def test_registered_scout_task_uses_the_verified_memory_backed_workflow():
    assert workflow_for('scout_fog',{}) is SCOUT_FOG and SCOUT_FOG.verified
    assert SCOUT_FOG.extra_paths['fog_scouts']==['ScoutData','AllScouts']


def test_fog_switches_back_from_the_village_tab_before_exploring(monkeypatch):
    game=ScoutCity();game.phase='CityUIScoutsManagement';game.values['fog_management_tab']=2
    after=run(game,monkeypatch)
    assert CITY_HUD.matches(after) and game.taps[0]==(225,160)
    assert game.taps.count((755,124))==1


def test_manually_offset_fog_popup_cannot_use_the_centered_button_coordinates(monkeypatch):
    game=ScoutCity();game.phase=POPUP;game.values['city_camera']['x']+=20
    with pytest.raises(NotReady,match='центра карты'):run(game,monkeypatch)
    assert not game.taps


def test_stop_after_acceptance_never_observes_or_redispatches_until_resumed(monkeypatch):
    game=ScoutCity();stop=threading.Event();game.cancel_after_send=stop
    with pytest.raises(Cancelled):run(game,monkeypatch,stop)
    assert game.after_send==0 and game.taps.count((755,124))==1
    stop.clear();game.cancel_after_send=None
    assert CITY_HUD.matches(run(game,monkeypatch,stop))
    assert game.taps.count((755,124))==1 and game.taps[-1]==(45,490)


@pytest.mark.parametrize('fault',['map','other_map','unready','multi','hostile','wrong_scout','busy','malformed','foreign_target','outside','boolean'])
def test_unconfirmed_form_cannot_authorize_dispatch(fault):
    state=form_state();v=state.values
    if fault=='map':v['fog_server']=2759
    elif fault=='other_map':v['fog_viewed_server']=3759
    elif fault=='unready':v['fog_initialized']=False
    elif fault=='multi':v['fog_form_IsMultiSelectMode']=True
    elif fault=='hostile':v['fog_form_targetId']=123456
    elif fault=='wrong_scout':v['fog_form_allScouts']['2']=deepcopy(v['fog_form_allScouts']['1'])
    elif fault=='busy':v['fog_form_allScouts']['1']['state']=2
    elif fault=='malformed':v['fog_form_allScouts']['1']=False
    elif fault=='foreign_target':v['fog_form_targetPos']={'1':9612,'2':6355}
    elif fault=='outside':
        v['fog_form_targetPos']=v['fog_form_lastEndPos']={'1':-1,'2':6354}
    else:v['fog_form_selectIndex']=True
    with pytest.raises(NotReady):ScoutFogReceipt.capture(state)


@pytest.mark.parametrize('fault',['target','currency','item','other_scout','character','kind'])
def test_receipt_requires_exact_fog_block_and_preservation_of_other_assets(fault):
    before=form_state();receipt=ScoutFogReceipt.capture(before);after=deepcopy(before)
    row=after.values['fog_scouts']['1'];row.update(state=2,charId=15477950800,fogDstGrid={'x':2340,'y':6300})
    assert receipt.matches(after)
    if fault=='target':row['fogDstGrid']['x']+=90
    elif fault=='currency':after.values['resources']['33']-=1
    elif fault=='item':after.values['supply_inventory']['items']['47']-=1
    elif fault=='other_scout':after.values['fog_scouts']['2']['state']=2
    elif fault=='character':row['charId']=0
    else:row['targetCharType']=8
    assert not receipt.matches(after)


def test_failed_dispatch_receipt_never_retries_input(monkeypatch):
    game=ScoutCity();tap=game.tap
    def changed(*args,**kwargs):
        tap(*args,**kwargs)
        if args==(755,124):game.values['resources']['5']-=1
    game.tap=changed
    with pytest.raises(WorkflowError,match='повтор запрещён'):run(game,monkeypatch)
    assert game.taps.count((755,124))==1
