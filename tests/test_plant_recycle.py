from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.model import Snapshot
from mirage.tutorial import PlantRecycleReceipt, recycle_point, tutorial_workflow
from mirage.workflows import Cancelled, Engine, NotReady, WorkflowError


def state(step=3):
    plant=dict(id='53',type=57,lv=1,state=1,width=3,length=3)
    target='PLANT' if step==2 else 'PLANT_RECYCLE_FUN'
    cover='BLOCK_UI_ONLY_WITH_ARROW2' if step==2 else 'CLOVER_POPUP_FUN_2BTN'
    return Snapshot('one',10,20,100.,'1.1.12.20',{
        'server_time':100000,'resources':{str(i):10000 for i in range(1,7)},
        'supply_inventory':{'ready':True,'items':{'1':2}},
        'views':{'MapHudPanel':True,'FTECover':True,'Dialog':True},
        'buildings':{'53':dict(**plant,position={'x':-1.3,'y':1.3},logicPosition={'x':-14,'y':12}),
            'town':dict(id='town',type=1,lv=6,state=1,width=9,length=9,position={'x':0,'y':0})},
        'building_menu':{'known':True,'selected':dict(id='53',type=57,level=1,
            buttons=['btn_CityPopUpInfo','btn_CityPopUpRecycle'])},
        'tutorial':{'ready':True,'active':True,'name':'slg_2_recycle_plants','type':'TRIGGERED',
            'step':step,'enterTime':90000,'plant':plant,'selection':'53','coverVisible':True,
            'dialogVisible':True,'dialogClosing':True,'cover':dict(Target=target,CoverName=cover),
            'config':dict(StepType='SELECT_BUILDING' if step==2 else 'CLICK_UI',Target=target,
                EndCondition='EVENT_TUTORIAL_CLICK_COVER' if step==2 else 'EVENT_TUTORIAL_CLICK_UI',
                ExtFunAtEnd='SelectPlant' if step==2 else '',HighlightDelay=0)}})


def packed(s):
    s=deepcopy(s);s.values['buildings']['53'].update(position={'x':-9.8,'y':-9.8},logicPosition={'x':-99,'y':-99})
    s.values['tutorial'].update(active=False,completed=True,step=5,config=None)
    s.values['views']={'MapHudPanel':True}
    return s


@pytest.mark.parametrize('step',[2,3])
def test_recommended_elm_and_exact_live_cover_authorize_only_the_current_action(step):
    s=state(step);assert recycle_point(s)==((480,270) if step==2 else (540,370))
    s.values['tutorial']['plant']['type']=58
    with pytest.raises(NotReady):recycle_point(s)


@pytest.mark.parametrize('fault',['selection','menu','cover','modal','dialog','stored'])
def test_foreign_selection_or_blocking_window_never_authorizes_recycle(fault):
    s=state();v=s.values
    if fault=='selection':v['tutorial']['selection']='town'
    elif fault=='menu':v['building_menu']['selected']['buttons']=['btn_CityPopUpRemove']
    elif fault=='cover':v['tutorial']['cover']['Target']='other'
    elif fault=='modal':v['views']['PurchaseConfirm']=True
    elif fault=='dialog':v['tutorial']['dialogClosing']=False
    else:v['buildings']['53']['logicPosition']={'x':-99,'y':-99}
    with pytest.raises(NotReady):PlantRecycleReceipt.capture(s)


@pytest.mark.parametrize('fault',['money','item','other','missing','not_stored'])
def test_receipt_requires_one_stored_object_and_preserves_every_other_object_and_asset(fault):
    s=state();r=PlantRecycleReceipt.capture(s);after=packed(s);assert r.matches(after)
    if fault=='money':after.values['resources']['5']-=1
    elif fault=='item':after.values['supply_inventory']['items']['1']-=1
    elif fault=='other':after.values['buildings']['town']['position']['x']=1
    elif fault=='missing':del after.values['buildings']['53']
    else:after.values['buildings']['53']['logicPosition']={'x':0,'y':0}
    assert not r.matches(after)


class Route:
    def __init__(self):
        self.state=state();self.now=100.;self.inputs=[];self.stop=threading.Event();self.cancel_after=False

    def observe(self):
        self.now+=1;return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        assert (x,y)==(540,370);self.inputs.append((x,y));self.state=packed(self.state)
        if self.cancel_after:self.stop.set()

    def run(self):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            tutorial_workflow({'max_actions':2},verified=True),self.stop,instance_id='one',pid=10,player_id=20)


def test_engine_stop_and_resume_do_not_repeat_a_server_accepted_recycle():
    game=Route();game.stop.set()
    with pytest.raises(Cancelled):game.run()
    assert not game.inputs
    game.stop.clear();game.cancel_after=True
    with pytest.raises(Cancelled):game.run()
    game.stop.clear();game.cancel_after=False
    with pytest.raises(NotReady):game.run()
    assert game.state.values['tutorial']['completed'] is True
    assert game.inputs==[(540,370)]
