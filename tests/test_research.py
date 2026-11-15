from copy import deepcopy
from dataclasses import replace

import pytest
import threading

from mirage.model import Profile, ResearchOptions, Snapshot
from mirage.research import ResearchCollectReceipt, ResearchReceipt, candidate, research_goal, research_workflow
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady, WorkflowError


def state():
    cfg=dict(ID=10301,Type=103,Level=1,BuildLevel=1,Food=100,Wood=100,Stone=0,Coin=0)
    for i in range(1,5):cfg.update({'PreType'+str(i):0,'PreLevel'+str(i):0})
    return Snapshot('one',10,20,100.,'1.1.12.20',{
        'server_time':100000,'resources':{str(i):500 for i in range(1,7)},
        'supply_inventory':{'ready':True,'items':{'1':2}},
        'buildings':{'13':{'type':13,'lv':1,'state':1}},
        'research_data':{'ProcessSlotCount':1,'ResearchProcessNode':{},'ResearchFinishNode':{},'Datas':{},'DatasUpdatedCount':0},
        'research_plan':{'ready':True,'rows':{'103':cfg}},
        'research_form':{'visible':True,'type':103,'level':1,'current':0,'max':5,'config':deepcopy(cfg),'cost':{'1':100,'2':100}}})


def started(s):
    s=deepcopy(s);v=s.values;r=v['research_data']
    row={'Id':'103','Type':103,'Level':0,'StartTime':100000,'EndTime':200000,'TotalTime':100000}
    r.update(DatasUpdatedCount=1,Datas={'1':deepcopy(row)},ResearchProcessNode={'1':row})
    v['resources']['1']-=100;v['resources']['2']-=100
    return s


def test_busy_or_uncollected_slot_never_allows_another_research_order():
    s=state();options=ResearchOptions(types=(103,))
    assert candidate(s,options)['Type']==103
    for field in ('ResearchProcessNode','ResearchFinishNode'):
        busy=deepcopy(s);busy.values['research_data'][field]={'1':{'Type':236,'Level':6}}
        assert candidate(busy,options) is None


def test_research_plan_checks_academy_technology_dependencies_and_reserves():
    s=state();options=ResearchOptions(types=(103,))
    s.values['research_plan']['rows']['103'].update(PreType1=101,PreLevel1=2)
    assert candidate(s,options) is None
    s.values['research_data']['Datas']={'1':{'Type':101,'Level':2}}
    assert candidate(s,options)['Type']==103
    assert candidate(s,replace(options,reserves=(450,0,0,0))) is None
    s.values['buildings']['13']['lv']=0
    assert candidate(s,options) is None


@pytest.mark.parametrize('fault',['gem','foreign','level','counter','inventory','expired'])
def test_research_ack_requires_exact_cost_inventory_node_and_queue(fault):
    s=state();receipt=ResearchReceipt.capture(s,ResearchOptions(types=(103,)));after=started(s);v=after.values
    assert receipt.matches(after)
    if fault=='gem':v['resources']['5']-=1
    elif fault=='foreign':v['research_data']['ResearchProcessNode']['1']['Type']=104
    elif fault=='level':v['research_data']['Datas']['1']['Level']=2
    elif fault=='counter':v['research_data']['DatasUpdatedCount']=0
    elif fault=='inventory':v['supply_inventory']['items']['1']-=1
    else:v['research_data']['ResearchProcessNode']['1']['EndTime']=100000
    assert not receipt.matches(after)


def test_short_completed_research_has_a_durable_level_update_without_an_active_queue():
    s=state();receipt=ResearchReceipt.capture(s,ResearchOptions(types=(103,)));after=started(s)
    after.values['research_data'].update(ResearchProcessNode={},Datas={'1':{'Id':'103','Type':103,'Level':1}})
    assert receipt.matches(after)


@pytest.mark.parametrize('settings',[{'types':[True]},{'types':[103,103]},{'max_level':0},{'reserves':{'5':100}}])
def test_invalid_research_settings_are_rejected_atomically(settings):
    with pytest.raises(ValueError):Profile('one',tasks={'research':settings}).validate()


def test_mismatched_native_form_does_not_authorize_spending():
    s=state();s.values['research_form']['config']['Type']=104
    with pytest.raises(NotReady):ResearchReceipt.capture(s,ResearchOptions(types=(103,)))
    s=state();s.values['research_form']['cost']['5']=1
    with pytest.raises(NotReady):ResearchReceipt.capture(s,ResearchOptions(types=(103,)))


class Route:
    def __init__(self):
        self.state=state();self.now=100.;self.inputs=[];self.cancelled=threading.Event();self.bad=False;self.stop=False
        v=self.state.values;v.update(hud_visible=True,hud_menu=False,in_city=True,city_enabled=True,
            city_selection_known=True,city_selection=None,queue_panel={'known':True,'visible':False},vip_visible=False,
            views={'MapHudPanel':True,'ReseachPage_Economy':True,'ResearchRequestPage2':True,'CommonBackground':True},
            research_ui={'tree':'ReseachPage_Economy','offset':0},building_menu={'known':True,'selected':None})

    def observe(self):
        self.now+=1;return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y));v=self.state.values
        if (x,y)==(737,400):
            self.state=started(self.state);v=self.state.values
            v['research_form']['visible']=False;v['views'].pop('ResearchRequestPage2',None)
            if self.bad:v['resources']['5']-=1
            if self.stop:self.cancelled.set()
        elif (x,y)==(818,62):v['research_form']['visible']=False;v['views'].pop('ResearchRequestPage2',None)
        elif (x,y)==(836,53):v['research_ui']['tree']=None;v['views']={'MapHudPanel':True}
        elif (x,y)==(480,270):
            data=v['research_data'];data.update(ResearchFinishNode={},Datas={'1':{'Id':'103','Type':103,'Level':1}},
                DatasUpdatedCount=data['DatasUpdatedCount']+1)
            if self.stop:self.cancelled.set()
        else:raise AssertionError((x,y))

    def run(self):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            research_workflow({'types':[103],'max_level':1},verified=True),self.cancelled,instance_id='one',pid=10,player_id=20)


def test_start_uses_normal_button_then_busy_slot_prevents_a_second_order():
    game=Route();after=game.run()
    assert CITY_HUD.matches(after) and after.values['research_started']==103
    assert game.inputs==[(737,400),(836,53)]
    game.run();assert game.inputs.count((737,400))==1


def test_research_stop_after_server_commit_resumes_without_spending_again():
    game=Route();game.stop=True
    with pytest.raises(Cancelled):game.run()
    game.cancelled.clear();game.stop=False;after=game.run()
    assert CITY_HUD.matches(after) and game.inputs.count((737,400))==1


def test_nonmatching_credit_never_retries_research_start():
    game=Route();game.bad=True
    with pytest.raises(WorkflowError,match='повтор'):game.run()
    assert game.inputs==[(737,400)]


def completed_queue(game):
    game.state=started(game.state);v=game.state.values;data=v['research_data']
    data['ResearchFinishNode']=data.pop('ResearchProcessNode');data['ResearchProcessNode']={}
    data['ResearchFinishNode']['1']['EndTime']=90000
    v.update(views={'MapHudPanel':True},research_ui={'tree':None},research_form={'visible':False})


def test_research_collection_requires_level_update_free_queue_and_unchanged_assets():
    game=Route();completed_queue(game);receipt=ResearchCollectReceipt.capture(game.state,ResearchOptions(types=(103,)))
    game.tap(480,270);assert receipt.matches(game.state)
    game.state.values['research_data']['Datas']['1']['Level']=2
    assert not receipt.matches(game.state)


def test_completed_research_is_collected_once_and_stop_can_resume(monkeypatch):
    import mirage.research as module
    game=Route();completed_queue(game)
    def navigate(*args,**kwargs):
        state=game.observe();state.values['city_navigation_target']={'id':'13','point':[480,270]};return state
    monkeypatch.setattr(module,'navigate_city',navigate)
    game.stop=True
    with pytest.raises(Cancelled):game.run()
    game.stop=False;game.cancelled.clear();after=game.run()
    assert CITY_HUD.matches(after) and game.inputs==[(480,270)]


def test_research_goal_resolves_unselected_prerequisite_above_common_target_level():
    s=state();cfg=s.values['research_plan']['rows']['103'];cfg.update(ID=10302,Level=2)
    root=deepcopy(cfg);root.update(ID=10401,Type=104,Level=1,PreType1=103,PreLevel1=2)
    s.values['research_plan']['rows']['104']=root
    s.values['research_data']['Datas']={'1':{'Type':103,'Level':1}}
    options=ResearchOptions(types=(104,),max_level=1,auto_prerequisites=True)
    assert research_goal(s,options)['Type']==103 and candidate(s,options)['Level']==2
    assert candidate(s,replace(options,auto_prerequisites=False)) is None


def test_research_prerequisite_collection_and_native_catalog_cover_the_entire_tree():
    game=Route();completed_queue(game)
    options=ResearchOptions(types=(243,),max_level=1,auto_prerequisites=True)
    receipt=ResearchCollectReceipt.capture(game.state,options)
    game.tap(480,270);assert receipt.matches(game.state)
    paths=research_workflow({'types':[243],'auto_prerequisites':True}).extra_paths
    assert len(paths['research_plan'][1].split(','))==71
    assert 'construction_plan' in paths and 'builder_queues' in paths


def test_research_academy_prerequisite_is_one_bounded_building_action_without_research_spending(monkeypatch):
    import mirage.building_upgrade as module
    game=Route();cfg=game.state.values['research_plan']['rows']['103'];cfg['BuildLevel']=2
    def upgrade(*args):
        game.state.values['buildings']['13'].update(state=2,endTime=200000)
        return game.observe()
    def factory(options):
        assert options.types==(13,) and options.max_level==2 and options.create_missing and options.auto_prerequisites
        return upgrade
    monkeypatch.setattr(module,'UpgradeCycle',factory)
    result=Engine(game,game.observe,clock=lambda:game.now,resolution=(960,540)).execute(
        research_workflow({'types':[103],'auto_prerequisites':True},verified=True),game.cancelled,
        instance_id='one',pid=10,player_id=20)
    assert result.values['research_prerequisite_pending'] is True and (737,400) not in game.inputs
