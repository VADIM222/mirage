from copy import deepcopy
from types import SimpleNamespace
import math
import threading

import pytest

from mirage.construction import ConstructionReceipt, PIXELS_X, PIXELS_Y, cleanup_target, find_placement, missing_candidate, placement_buttons, placement_candidates
from mirage.model import BuildingOptions, RESEARCH_TYPES, ResearchOptions
from mirage.workflows import Cancelled, NotReady, WorkflowError


def state():
    cfg=dict(ID=1601,Type=16,Level=1,Enable=1,BuildingTime=2,Food=500,Wood=500,Stone=0,Coin=0,
        Gem=0,Amber=0,Crystal=0,NeedBagItem=0,ItemCnt1=0,
        PreType1=1,PreLevel1=6,PreType2=0,PreLevel2=0,PreType3=0,PreLevel3=0)
    return SimpleNamespace(values={
        'resources':{str(i):10000 for i in range(1,7)},'supply_inventory':{'ready':True,'items':{'1':1}},
        'server_time':1000,'views':{'MapHudPanel':True},
        'buildings':{'town':dict(type=1,lv=6,state=1,endTime=0),'localNewBuilding':dict(type=16,lv=0)},
        'builder_queues':{'1':{'id':1,'from':'born','endTime':-1,'buildingId':''}},
        'construction_plan':{'ready':True,'first':{'16':cfg},'limits':{'16':{'Level_6':1}}},
        'building_preview':{'selection':'localNewBuilding','preview':{'id':'localNewBuilding','type':16,
            'lv':0,'state':4,'isSelected':True,'newPosValid':True,'position':{'x':0.,'y':0.}},
            'cityOrigin':{'1':10.,'2':20.},'buildCost':deepcopy(cfg)},
        'city_camera':{'x':10.,'y':19.65,'distance':150,'moving':False}})


def committed(s):
    s=deepcopy(s);v=s.values;del v['buildings']['localNewBuilding']
    v['buildings']['new']=dict(type=16,lv=1,state=1,endTime=0,position={'x':0.,'y':0.})
    v['resources']['1']-=500;v['resources']['2']-=500
    return s


def test_new_building_requires_live_unlock_limit_dependencies_and_reserves():
    s=state();assert missing_candidate(s,(16,),(0,0,0,0))['Type']==16
    assert missing_candidate(s,(16,),(9800,0,0,0)) is None
    s.values['construction_plan']['limits']['16']['Level_6']=0
    assert missing_candidate(s,(16,),(0,0,0,0)) is None
    s=state();s.values['buildings']['town']['lv']=5
    assert missing_candidate(s,(16,),(0,0,0,0)) is None


@pytest.mark.parametrize('fault',['gem','item','wrong_type','position','builder','duplicate'])
def test_construction_receipt_rejects_wrong_cost_items_location_builder_and_extra_buildings(fault):
    s=state();receipt=ConstructionReceipt.capture(s,(16,),(0,0,0,0));after=committed(s)
    assert receipt.matches(after)
    v=after.values
    if fault=='gem':v['resources']['5']-=1
    elif fault=='item':del v['supply_inventory']['items']['1']
    elif fault=='wrong_type':v['buildings']['new']['type']=13
    elif fault=='position':v['buildings']['new']['position']['x']=.2
    elif fault=='builder':v['builder_queues']['1']['from']='temporary'
    else:v['buildings']['another']=deepcopy(v['buildings']['new'])
    assert not receipt.matches(after)


def test_invalid_placement_or_foreign_preview_never_authorizes_confirmation():
    s=state();assert placement_buttons(s,16)==((540,100),(430,100))
    s.values['building_preview']['preview']['newPosValid']=False
    with pytest.raises(NotReady):ConstructionReceipt.capture(s,(16,),(0,0,0,0))
    s=state();s.values['building_preview']['preview']['type']=13
    with pytest.raises(NotReady):ConstructionReceipt.capture(s,(16,),(0,0,0,0))


def test_new_building_unveiling_has_level_zero_and_does_not_occupy_upgrade_queue():
    s=state();receipt=ConstructionReceipt.capture(s,(16,),(0,0,0,0));after=committed(s)
    after.values['buildings']['new'].update(lv=0,state=3,endTime=2900,totalTime=1900)
    assert receipt.matches(after)
    after.values['buildings']['new']['totalTime']=999999
    assert not receipt.matches(after)


def test_all_research_nodes_fit_settings_and_new_building_options_are_explicit():
    assert len(ResearchOptions.from_settings({'types':list(RESEARCH_TYPES)}).types)==71
    assert not BuildingOptions().create_missing and not BuildingOptions().auto_prerequisites
    with pytest.raises(ValueError):BuildingOptions.from_settings({'create_missing':1})


def test_stored_plant_does_not_occupy_city_cells():
    s=state();s.values['construction_plan']['first']['16'].update(Width=6,Length=6)
    s.values['buildings']={}
    expected=placement_candidates(s,16)
    s.values['buildings']['stored']=dict(type=57,lv=1,state=1,width=3,length=3,
        logicPosition={'x':-99,'y':-99},position=None)
    assert placement_candidates(s,16)==expected


def test_space_cleanup_never_selects_special_decoration_or_more_than_three_blockers():
    s=state();s.values['construction_plan']['first']['16'].update(Width=6,Length=6)
    s.values['construction_plan']['groups']={'3':{'1':dict(Type=57,CanRemove=1,Width=3,Length=3)}}
    s.values['buildings']={'plant':dict(id='plant',type=57,lv=1,state=1,width=3,length=3,
        position={'x':0,'y':0},logicPosition={'x':-1,'y':-1})}
    assert cleanup_target(s,16)=='plant'
    s.values['buildings']['plant']['type']=288
    assert cleanup_target(s,16) is None
    s.values['buildings']['plant']['type']=57
    s.values['construction_plan']['groups']['3']['1']['CanRemove']=0
    assert cleanup_target(s,16) is None
    assert not BuildingOptions().clear_plants
    with pytest.raises(ValueError):BuildingOptions.from_settings({'clear_plants':1})


def test_placement_relocates_with_native_feedback_despite_damped_input_and_supports_stop(monkeypatch):
    import mirage.construction as module
    monkeypatch.setattr(module,'placement_candidates',lambda *_:[(-.8,-.8)])
    class Stop(threading.Event):
        def wait(self,timeout=None):return self.is_set()
    class Game:
        def __init__(self):
            self.state=state();self.stop=Stop();self.inputs=[];self.stop_after=False;self.spend=False
            self.state.values['building_preview']['preview']['newPosValid']=False
        def observe(self):return deepcopy(self.state)
        def permit(self):
            if self.stop.is_set():raise Cancelled('stop')
        def drag(self,x,y,ex,ey):
            self.inputs.append((x,y,ex,ey));p=self.state.values['building_preview']['preview']
            a=(ex-x)/PIXELS_X;b=-(ey-y)/PIXELS_Y
            p['position']['x']+=.6*(a+b)*math.sqrt(.5)-.05
            p['position']['y']+=.6*(b-a)*math.sqrt(.5)-.05
            p['newPosValid']=math.hypot(p['position']['x']+.8,p['position']['y']+.8)<.15
            if self.spend:self.state.values['resources']['5']-=1
            if self.stop_after:self.stop.set()
        def run(self):return find_placement(self.observe(),16,self,self.observe,self.stop,self.permit)
    game=Game();after=game.run()
    assert after.values['building_preview']['preview']['newPosValid'] is True
    assert len(game.inputs)==2 and after.values['resources']==state().values['resources']
    game=Game();game.stop_after=True
    with pytest.raises(Cancelled):game.run()
    assert len(game.inputs)==1
    game=Game();game.spend=True
    with pytest.raises(WorkflowError):game.run()
    assert len(game.inputs)==1
