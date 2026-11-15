from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.building_upgrade import (BuildingOptions, FIELDS, UpgradeReceipt, building_workflow,
    candidate, permanent_builder)
from mirage.model import Snapshot
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady, WorkflowError


def form():
    return Snapshot('one',10,20,100,'1.1.12.20',{'server_time':100000,
        'views':{'MapHudPanel':True,'UpgradeBuilding':True,'CommonBackground':True},
        'resources':{str(i):5000000 for i in range(1,7)},
        'buildings':{'75':{'id':'75','type':4,'lv':19,'state':1,'endTime':0}},
        'builder_queues':{'1':{'id':1,'from':'born','buildingId':'','endTime':-1},
                          '2':{'id':2,'from':'item','buildingId':'','endTime':-1}},
        'upgrade_visible':True,'upgrade_id':'75','upgrade_type':4,'upgrade_level':19,
        'upgrade_can':True,'upgrade_item':0,'upgrade_items':0,
        'upgrade_cost':{'1':{'type':1,'num':1200000,'finalNum':1200000},
                        '2':{'type':2,'num':1200000,'finalNum':1200000}}})


def started(state):
    state=deepcopy(state);v=state.values
    v['buildings']['75'].update(state=2,endTime=900000)
    # Queue endTime is builder expiry (-1 means permanent), not building finish.
    v['builder_queues']['1'].update(buildingId='75')
    for kind in ('1','2'):v['resources'][kind]-=1200000
    return state


def test_normal_upgrade_receipt_requires_exact_spend_and_permanent_queue_assignment():
    state=form();receipt=UpgradeReceipt.capture(state,BuildingOptions(),'75')
    assert receipt.matches(started(state))
    assert receipt.cost=={'1':1200000,'2':1200000} and receipt.builder==1


@pytest.mark.parametrize('fault',['target','type','level','busy','builder','can','modal','blueprint',
    'item','gem_cost','duplicate_cost','partial_cost','reserve','goal'])
def test_unconfirmed_requirements_prevent_start(fault):
    state=form();v=state.values;options=BuildingOptions()
    if fault=='target':v['upgrade_id']='87'
    elif fault=='type':v['upgrade_type']=14
    elif fault=='level':v['upgrade_level']=18
    elif fault=='busy':v['buildings']['75']['state']=2
    elif fault=='builder':v['builder_queues']['1']['buildingId']='87'
    elif fault=='can':v['upgrade_can']=False
    elif fault=='modal':v['views']['ResQuickBuying']=True
    elif fault=='blueprint':v['upgrade_item']=401
    elif fault=='item':v['upgrade_items']=1
    elif fault=='gem_cost':v['upgrade_cost']['1']['type']=5
    elif fault=='duplicate_cost':v['upgrade_cost']['2']['type']=1
    elif fault=='partial_cost':v['upgrade_cost']['$truncated']=True
    elif fault=='reserve':options=BuildingOptions(reserves=(4000000,0,0,0))
    else:options=BuildingOptions(max_level=19)
    with pytest.raises(NotReady):UpgradeReceipt.capture(state,options,'75')


@pytest.mark.parametrize('fault',['gems','cost','different_queue','different_building','timer','level','instant'])
def test_partial_or_unrelated_acknowledgements_never_authorize_a_duplicate_start(fault):
    before=form();receipt=UpgradeReceipt.capture(before,BuildingOptions(),'75');after=started(before);v=after.values
    if fault=='gems':v['resources']['5']-=1
    elif fault=='cost':v['resources']['2']+=1
    elif fault=='different_queue':v['builder_queues']['1']['id']=2
    elif fault=='different_building':v['builder_queues']['1']['buildingId']='87'
    elif fault=='timer':v['buildings']['75']['endTime']=v['server_time']
    elif fault=='level':v['buildings']['75']['lv']=20
    else:v['buildings']['75']['state']=1
    assert not receipt.matches(after)


def test_selection_ignores_complete_and_running_quarries_and_never_buys_a_builder():
    state=form();v=state.values
    v['buildings']['87']={'id':'87','type':4,'lv':18,'state':2,'endTime':900000}
    assert candidate(state,BuildingOptions())[0]=='75'
    v['buildings']['75']['lv']=20
    assert candidate(state,BuildingOptions()) is None
    v['builder_queues']['1']['buildingId']='87'
    assert permanent_builder(state) is None


@pytest.mark.parametrize('value',[True,0,25,'20'])
def test_invalid_target_levels_reject_the_profile(value):
    with pytest.raises(ValueError):BuildingOptions.from_settings({'max_level':value})


def test_building_extra_fields_respect_agent_snapshot_budget():
    from mirage.memory import PATHS
    assert len(PATHS|FIELDS)<=64


def test_registered_factory_and_profile_validate_the_same_building_options():
    from mirage.model import Profile
    from mirage.workflows import workflow_for
    settings={'max_level':23,'reserves':{'2':2000000}}
    profile=Profile('one',tasks={'buildings':settings});profile.validate()
    workflow=workflow_for('buildings',settings)
    assert workflow.verified and workflow.steps[0].action.options==BuildingOptions(23,(0,2000000,0,0))
    profile.tasks['buildings']['max_level']=25
    with pytest.raises(ValueError):profile.validate()


class Route:
    def __init__(self,monkeypatch):
        self.state=form();self.now=100.;self.inputs=[];self.cancelled=threading.Event();self.cancel_at_form=False
        v=self.state.values;v.update(hud_visible=True,hud_menu=False,in_city=True,city_enabled=True,vip_visible=False,
            queue_panel={'known':True,'visible':False},city_selection_known=True,city_selection=None,
            building_menu={'known':True,'selected':None},city_camera={'x':1.,'y':2.,'distance':200.},
            city_resource_state={'groups':{}})
        self.show()
        def approach(*args,**kwargs):
            self.state.values['city_navigation_target']={'point':[480,270],
                'camera':{'x':1.,'y':2.,'distance':200.}}
            return self.observe()
        monkeypatch.setattr('mirage.building_upgrade.navigate_city',approach)

    def show(self,upgrade=False):
        self.state.values.update(upgrade_visible=upgrade,views={'MapHudPanel':True,
            **({'UpgradeBuilding':True,'CommonBackground':True} if upgrade else {})})

    def observe(self):
        self.now+=1
        return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y));v=self.state.values
        if (x,y)==(480,270):
            v['building_menu']['selected']={'id':'75','type':4,'level':19,
                'buttons':['btn_CityPopUpUpgrade','btn_FunctionQuarry','btn_CityPopUpInfo']}
            v['city_selection']='75'
        elif (x,y)==(475,365):
            v['building_menu']['selected']=None;v['city_selection']=None;self.show(True)
            if self.cancel_at_form:self.cancelled.set()
        elif (x,y)==(740,410):self.state=started(self.state);self.show()
        elif (x,y)==(818,62):self.show()
        else:raise AssertionError((x,y))

    def run(self):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            building_workflow({},verified=True),self.cancelled,instance_id='one',pid=10,player_id=20)


def test_route_starts_once_and_waits_for_busy_permanent_builder_without_another_input(monkeypatch):
    game=Route(monkeypatch);after=game.run()
    assert CITY_HUD.matches(after) and game.inputs.count((740,410))==1
    count=len(game.inputs);game.run()
    assert len(game.inputs)==count


def test_cancellation_after_opening_costs_prevents_upgrade_input(monkeypatch):
    game=Route(monkeypatch);game.cancel_at_form=True
    with pytest.raises(Cancelled):game.run()
    assert (740,410) not in game.inputs


def test_completed_short_upgrade_requires_builder_release_and_exact_cost():
    s=form();receipt=UpgradeReceipt.capture(s,BuildingOptions(),'75');after=started(s)
    after.values['buildings']['75'].update(lv=20,state=1,endTime=0)
    assert not receipt.matches(after)
    after.values['builder_queues']['1']['buildingId']=''
    assert receipt.matches(after)
    after.values['resources']['5']-=1
    assert not receipt.matches(after)


def test_plan_skips_blocked_priority_and_respects_resource_reserves():
    s=form();v=s.values
    v['buildings']['29']={'id':'29','type':1,'lv':3,'state':1,'endTime':0}
    def config(kind,level,pre=0):
        return dict(Type=kind,Level=level,Enable=1,Gem=0,Amber=0,Crystal=0,NeedBagItem=0,ItemCnt1=0,
            Food=100,Wood=100,Stone=0,Coin=0,PreType1=pre,PreLevel1=3 if pre else 0,
            PreType2=0,PreLevel2=0,PreType3=0,PreLevel3=0)
    v['building_plan']={'ready':True,'rows':{'29':config(1,4,6),'75':config(4,20)}}
    options=BuildingOptions(max_level=24,types=(1,4))
    assert candidate(s,options)[0]=='75'
    v['buildings']['4']={'id':'4','type':6,'lv':3,'state':1,'endTime':0}
    assert candidate(s,options)[0]=='29'
    assert candidate(s,replace(options,reserves=(5000000,0,0,0))) is None
    v['building_plan']['ready']=False
    with pytest.raises(NotReady):candidate(s,options)


@pytest.mark.parametrize('types',[[True],[999],[1,1],['1'],None])
def test_invalid_selected_types_reject_profile(types):
    with pytest.raises(ValueError):BuildingOptions.from_settings({'types':types})


def test_empty_selected_types_are_an_explicit_noop():
    assert candidate(form(),BuildingOptions.from_settings({'types':[]})) is None


@pytest.mark.parametrize('value',[1,'true',None,[]])
def test_resource_pack_replenishment_requires_an_explicit_boolean(value):
    with pytest.raises(ValueError):BuildingOptions.from_settings({'use_resource_packs':value})
