from copy import deepcopy
import threading

import pytest

from mirage.scout_caves import CAVES, CAVE_PREVIEW, CaveReceipt, FIELDS
from mirage.scout_fog import FORM
from mirage.scout_places import POPUP
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady, WorkflowError
from test_scout_places import VillageCity, discovered


class CaveCity(VillageCity):
    def __init__(self):
        super().__init__();row={**discovered(30215,2563.7,6127.6),'type':10}
        self.values.update(place_caves={'1':dict(row)},place_rows={'1':dict(row)},place_cave_ghosts={})

    def go(self,row):
        super().go(row);target=self.values['place_target'];target['charType']=10
        target['cave']={**target.pop('village'),'cavType':0}

    def tap(self,x,y,*,hold_ms=0):
        if (x,y)==(570,160):self.taps.append((x,y));self.values['place_tab']=self.values['fog_management_tab']=3
        elif (x,y)==(480,250):
            self.taps.append((x,y));self.phase=POPUP
            self.values.update(place_popup_id=self.active['caviId'],place_popup_target=self.values['place_target']['id'])
        elif (x,y)==(681,360):
            self.taps.append((x,y));self.phase=FORM;target=self.values['place_target'];row=deepcopy(self.values['fog_scouts']['1'])
            row['selected']=True
            self.values.update(cave_form_targetId=target['id'],cave_form_targetPos={'1':target['pos']['x'],'2':target['pos']['y']},
                cave_form_selectIndex=1,cave_form_allScouts={'1':row},cave_form_IsMultiSelectMode=False)
        elif (x,y)==(755,124):
            self.taps.append((x,y));self.phase='map';self.delivered=True
            self.values['fog_scouts']['1'].update(state=3,charId=16000500800,targetSubId=30215,
                targetSubType=0,targetCharType=10,targetId=self.values['place_target']['id']//100)
            if self.cancel_after_send is not None:self.cancel_after_send.set()
        else:super().tap(x,y,hold_ms=hold_ms)


def run(game,monkeypatch,flow=CAVE_PREVIEW,cancelled=None):
    def navigate(*args,**kwargs):
        s=game.snapshot();s.values['city_navigation_target']={'point':[480,270],'id':'58'};return s
    monkeypatch.setattr('mirage.scout_fog.navigate_city',navigate)
    def clock():game.time+=.5;return game.time
    return Engine(game,game.snapshot,clock=clock,resolution=(960,540)).execute(
        flow,cancelled or threading.Event(),instance_id='one',pid=10,player_id=20)


def test_cave_preview_uses_its_own_tab_and_type_without_a_village_claim(monkeypatch):
    game=CaveCity();state=run(game,monkeypatch)
    assert state.values['cave_preview_id']==30215 and state.values['place_target']['charType']==10
    assert (570,160) in game.taps and game.taps.count((480,250))==1 and (681,365) not in game.taps
    assert game.visits==0 and game.values['place_visited_caves']=={} and game.values['place_visited_villages']=={}


def test_cave_preview_waits_for_the_natural_scout_return_before_input(monkeypatch):
    game=CaveCity();game.values['fog_scouts']['1'].update(state=2,charId=15857790800)
    with pytest.raises(NotReady):run(game,monkeypatch)
    assert not game.taps


def test_cave_preview_rejects_the_separate_ghost_visit_map(monkeypatch):
    game=CaveCity();game.values['place_cave_ghosts']={'30215':True}
    with pytest.raises(NotReady):run(game,monkeypatch)
    assert (742,251) not in game.taps and (480,250) not in game.taps


def test_cave_reader_fits_a_single_atomic_native_request():
    from mirage.memory import PATHS
    assert len(PATHS|FIELDS)<=64


def test_caves_are_connected_to_the_normal_dispatcher():
    from mirage.workflows import workflow_for
    assert workflow_for('caves',{}) is CAVES


def test_cave_dispatch_is_exact_and_preserves_assets_and_other_scouts(monkeypatch):
    game=CaveCity();before=deepcopy(game.values);state=run(game,monkeypatch,CAVES)
    assert CITY_HUD.matches(state) and state.values['cave_dispatched_id']==30215
    assert game.taps.count((755,124))==1 and state.values['resources']==before['resources']
    assert state.values['supply_inventory']==before['supply_inventory']
    assert state.values['fog_scouts']['2']==before['fog_scouts']['2']


def test_cave_cancel_after_acceptance_stops_reads_and_resumes_without_repeat(monkeypatch):
    game=CaveCity();stop=threading.Event();game.cancel_after_send=stop
    with pytest.raises(Cancelled):run(game,monkeypatch,CAVES,stop)
    assert game.after_send==0
    stop.clear();game.cancel_after_send=None;state=run(game,monkeypatch,CAVES,stop)
    assert CITY_HUD.matches(state) and game.taps.count((755,124))==1


@pytest.mark.parametrize('fault',['wrong_cave','radar','ghost','multi','target','selection'])
def test_cave_form_refuses_other_target_types_or_unsafe_selections(monkeypatch,fault):
    game=CaveCity();run(game,monkeypatch);game.tap(681,360,hold_ms=100)
    if fault=='wrong_cave':game.values['place_target']['cave']['caviId']=40174
    elif fault=='radar':game.values['place_target']['cave']['isClientCave']=True
    elif fault=='ghost':game.values['place_target']['cave']['cavType']=1
    elif fault=='multi':game.values['cave_form_IsMultiSelectMode']=True
    elif fault=='target':game.values['cave_form_targetId']+=100
    else:game.values['cave_form_selectIndex']=2
    with pytest.raises(NotReady):CaveReceipt.capture(game.snapshot())
    assert (755,124) not in game.taps


def test_cave_unconfirmed_dispatch_never_repeats(monkeypatch):
    game=CaveCity();tap=game.tap
    def corrupt(*args,**kwargs):
        tap(*args,**kwargs)
        if args==(755,124):game.values['fog_scouts']['1']['targetSubId']=40174
    game.tap=corrupt
    with pytest.raises(WorkflowError,match='повтор запрещён'):run(game,monkeypatch,CAVES)
    assert game.taps.count((755,124))==1


@pytest.mark.parametrize('fault',['unsplit_world_id','zero_target','other_cave','currency','other_scout'])
def test_cave_receipt_requires_exact_split_id_and_preserved_assets(monkeypatch,fault):
    game=CaveCity();run(game,monkeypatch);game.tap(681,360,hold_ms=100)
    receipt=CaveReceipt.capture(game.snapshot());game.tap(755,124,hold_ms=100);state=game.snapshot()
    assert receipt.matches(state)
    if fault=='unsplit_world_id':state.values['fog_scouts']['1']['targetId']=receipt.target_id
    elif fault=='zero_target':state.values['fog_scouts']['1']['targetId']=0
    elif fault=='other_cave':state.values['fog_scouts']['1']['targetSubId']=40174
    elif fault=='currency':state.values['resources']['33']-=1
    else:state.values['fog_scouts']['2']['state']=3
    assert not receipt.matches(state)


def test_busy_cave_task_closes_management_without_dispatching_again(monkeypatch):
    game=CaveCity();game.phase='CityUIScoutsManagement';game.values['fog_scouts']['1'].update(state=3,charId=15877240800)
    state=run(game,monkeypatch,CAVES)
    assert CITY_HUD.matches(state) and (818,62) in game.taps and (755,124) not in game.taps


def test_completed_cave_popup_is_dismissed_without_revisiting(monkeypatch):
    game=CaveCity();run(game,monkeypatch);game.values['place_visited_caves']={'30215':True}
    state=run(game,monkeypatch,CAVES)
    assert CITY_HUD.matches(state) and game.taps.count((742,251))==1 and (755,124) not in game.taps
