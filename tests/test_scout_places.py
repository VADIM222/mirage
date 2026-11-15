from copy import deepcopy
import threading

import pytest

from mirage.scout_places import (POPUP, VILLAGE, VILLAGES, VillageReceipt, assets, first_place_row, village_packet)
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady, WorkflowError
from test_scout_fog import ScoutCity


def test_village_reader_request_fits_the_native_atomic_snapshot_limit():
    from mirage.memory import PATHS
    assert len(PATHS|VILLAGES.extra_paths)<=64


def test_villages_are_available_through_the_normal_dispatcher_registry():
    from mirage.workflows import workflow_for
    assert workflow_for('villages',{}) is VILLAGES


def discovered(place_id,x,y):
    return {'type':11,'caviId':place_id,'pos':{'x':x,'y':y},'findTm':1794442254578.114,
        'height':115,'isExplored':False,'prefab_type':'CityUIScoutsManagementListBar'}


class VillageCity(ScoutCity):
    def __init__(self,reward=(3,2,20)):
        super().__init__();self.reward=reward;self.visits=0;self.after_claim=0;self.claimed=False
        self.stop_on_claim=None;self.intro=False;self.delayed_resource=False
        places={'1':discovered(30215,2619.3,6296.6),'2':discovered(40174,2350.6,6405.1)}
        self.values.update(place_villages=deepcopy(places),place_caves={},place_visited_villages={},place_visited_caves={},
            place_rows=deepcopy(places),place_tab=1,place_target=None,place_packet=None,place_loot=None,place_near=False,
            place_techniques={'1':{'Type':101,'Level':1}},place_reward_types={'Resource':1,'Item':2,'Troop':3,'Tech':8},
            troops={'1':{'unitId':1,'unitCount':100,'hurt':0,'badHurt':0,'maxCount':100}},place_zooming=False,
            harvest_receipts={str(i):{'type':i,'value':1000,'incrValue':0,'leftTime':0} for i in range(1,5)})

    def snapshot(self):
        if self.claimed:self.after_claim+=1
        state=super().snapshot()
        if self.phase==POPUP:state.values['views'][POPUP]=True
        return state

    def go(self,row):
        self.phase='map';self.values.update(in_city=False,city_enabled=False)
        self.active=deepcopy(row);target_id=(57911 if row['caviId']==30215 else 57922)*100
        x,y=row['pos']['x']+7200,row['pos']['y']
        self.values.update(place_view_x=x,place_view_y=y,place_target={
            'id':target_id,'charType':11,'village':{'caviId':row['caviId']},'pos':{'x':x,'y':y}})

    def add_gift(self):
        kind,subtype,count=self.reward;v=self.values;key=str(subtype)
        if kind==1:v['resources'][key]+=count;v['harvest_receipts'][key]['value']=v['resources'][key]
        elif kind==2:v['supply_inventory']['items'][key]=v['supply_inventory']['items'].get(key,0)+count
        elif kind==3:
            row=next((row for row in v['troops'].values() if row['unitId']==subtype),None)
            if row is None:
                row={'unitId':subtype,'unitCount':0,'hurt':0,'badHurt':0,'maxCount':0};v['troops'][str(len(v['troops'])+1)]=row
            row['unitCount']+=count;row['maxCount']+=count
        elif kind==8:v['place_techniques'][str(len(v['place_techniques'])+1)]={'Type':subtype,'Level':count}

    def tap(self,x,y,*,hold_ms=0):
        if (x,y)==(395,160):
            self.taps.append((x,y));self.values['place_tab']=self.values['fog_management_tab']=2
        elif (x,y) in ((742,251),(742,343)):
            self.taps.append((x,y))
            if self.intro:self.intro=False;return
            self.go(self.values['place_rows']['1' if y==251 else '2'])
        elif (x,y)==(480,250):
            self.taps.append((x,y));self.visits+=1;self.claimed=True;self.phase=POPUP
            kind,subtype,count=self.reward;v=self.values
            v['place_visited_villages'][str(self.active['caviId'])]=True
            v.update(place_popup_id=self.active['caviId'],place_popup_target=v['place_target']['id'],place_popup_kind=1,
                place_packet={'CharId':v['place_target']['id']//100,'Loots':{'Loots':{'1':{'Type':kind,'SubType':subtype,'Value':count}}}},
                place_loot={'Type':kind,'SubType':subtype,'Value':count})
            if not (kind==1 and self.delayed_resource):self.add_gift()
            if self.stop_on_claim is not None:self.stop_on_claim.set()
        elif (x,y)==(681,365):
            self.taps.append((x,y))
            if self.reward[0]==1 and self.delayed_resource:self.add_gift()
            self.values.update(place_near=True,place_loot=None,place_packet={'nearVillage':self.values['place_villages']['2']})
        elif (x,y)==(900,400):self.taps.append((x,y));self.phase='map'
        else:super().tap(x,y,hold_ms=hold_ms)


def run(game,monkeypatch,stop=None):
    def navigate(*args,**kwargs):
        s=game.snapshot();s.values['city_navigation_target']={'point':[480,270],'id':'58'};return s
    monkeypatch.setattr('mirage.scout_fog.navigate_city',navigate)
    def clock():game.time+=.5;return game.time
    return Engine(game,game.snapshot,clock=clock,resolution=(960,540)).execute(
        VILLAGES,stop or threading.Event(),instance_id='one',pid=10,player_id=20)


@pytest.mark.parametrize('reward',[(1,1,100),(2,47,1),(3,2,20),(8,104,1)])
def test_village_grants_exact_resource_item_troop_or_technology_and_returns_to_city(monkeypatch,reward):
    game=VillageCity(reward);before=assets(game.snapshot());after=run(game,monkeypatch)
    assert CITY_HUD.matches(after) and after.values['villages_claimed']==1 and after.values['village_claimed_id']==30215
    assert game.visits==1 and after.values['place_visited_villages']=={'30215':True}
    assert after.values['resources']['33']==before[0]['33']


def test_resource_credit_frozen_until_welcome_does_not_cause_a_second_visit(monkeypatch):
    game=VillageCity((1,1,100));game.delayed_resource=True;game.intro=True
    after=run(game,monkeypatch)
    assert CITY_HUD.matches(after) and after.values['resources']['1']==1100 and game.visits==1
    assert game.taps.count((742,251))==2 and game.taps.count((681,365))==1


def test_cancel_after_server_grant_stops_reads_and_resume_only_acknowledges_it(monkeypatch):
    game=VillageCity();stop=threading.Event();game.stop_on_claim=stop
    with pytest.raises(Cancelled):run(game,monkeypatch,stop)
    assert game.visits==1 and game.after_claim==0 and (681,365) not in game.taps
    stop.clear();game.stop_on_claim=None
    after=run(game,monkeypatch,stop)
    assert CITY_HUD.matches(after) and after.values['villages_claimed']==0 and after.values['village_reward_resumed']
    assert game.visits==1 and game.taps.count((681,365))==1


def test_first_unvisited_row_is_found_below_an_already_claimed_one(monkeypatch):
    game=VillageCity();game.values['place_visited_villages']={'30215':True}
    game.values['place_rows']['1']['isExplored']=True
    after=run(game,monkeypatch)
    assert after.values['village_claimed_id']==40174 and (742,343) in game.taps and game.visits==1


@pytest.mark.parametrize('fault',['foreign_id','client_village','wrong_coordinates'])
def test_preflight_rejects_other_objects_and_costed_radar_villages(fault):
    game=VillageCity();game.values['place_tab']=2;candidate=first_place_row(game.snapshot(),VILLAGE)
    receipt=VillageReceipt.capture(game.snapshot(),candidate);game.go(candidate)
    if fault=='foreign_id':game.values['place_target']['village']['caviId']=40174
    elif fault=='client_village':game.values['place_target']['village']['isClientVillage']=True
    else:game.values['place_target']['pos']['x']+=1
    with pytest.raises(NotReady):receipt.can_select(game.snapshot())
    assert game.visits==0


def received_state():
    game=VillageCity();game.values['place_tab']=2;candidate=first_place_row(game.snapshot(),VILLAGE)
    receipt=VillageReceipt.capture(game.snapshot(),candidate);game.go(candidate);game.tap(480,250,hold_ms=100)
    return game,receipt


@pytest.mark.parametrize('fault',['packet','shown_loot','extra_visit','currency','inventory','troops','tech'])
def test_server_identity_and_full_asset_accounting_are_required(fault):
    game,receipt=received_state();s=game.snapshot();grant=receipt.grant(s);assert grant.matches(s)
    if fault=='packet':s.values['place_packet']['CharId']+=1
    elif fault=='shown_loot':s.values['place_loot']['Value']+=1
    elif fault=='extra_visit':s.values['place_visited_villages']['40174']=True
    elif fault=='currency':s.values['resources']['33']-=1
    elif fault=='inventory':s.values['supply_inventory']['items']['47']-=1
    elif fault=='troops':s.values['troops']['1']['unitCount']-=1
    else:s.values['place_techniques']['1']['Level']+=1
    if fault in ('packet','shown_loot','extra_visit'):
        with pytest.raises(NotReady):receipt.grant(s)
    else:assert not grant.matches(s)


def test_legacy_technology_packet_uses_the_authoritative_target_level():
    game,receipt=received_state();s=game.snapshot();s.values['troops'].pop('2')
    s.values['place_packet']={'CharId':57911,'Tech':{'Type':104,'Level':1}}
    s.values['place_loot']={'Type':8,'SubType':104,'Value':1}
    s.values['place_techniques']['2']={'Type':104,'Level':1}
    assert receipt.grant(s).matches(s)


def test_unconfirmed_asset_grant_never_repeats_the_map_claim(monkeypatch):
    game=VillageCity();tap=game.tap
    def corrupted(*args,**kwargs):
        tap(*args,**kwargs)
        if args==(480,250):game.values['troops']['2']['unitCount']-=1
    game.tap=corrupted
    with pytest.raises(WorkflowError,match='повтор запрещён'):run(game,monkeypatch)
    assert game.visits==1
