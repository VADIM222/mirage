from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.barbarian_chain import ChainNotReady,chain_approach,chain_plan,scene_primary
from mirage.barbarian_navigation import WorldNavigator,screen_point
from mirage.model import BarbarianOptions
from test_barbarian_chain import enable_chain
from test_barbarians import BattleCity,field_state,form_state


def camera_state():
    state=enable_chain(form_state());state.values['barbarian_hero']['chain']['camera']={
        'x':8099.84228515625,'y':19074.802734375,'distance':219.4180450439453,'moving':False}
    return state


def test_projection_agrees_with_the_independent_native_ground_measurement_after_camera_pan():
    state=camera_state()
    assert screen_point(state,{'x':8113.99658203125,'y':19083.98046875})==(757,143)
    # Recentring changes only the origin, never the requested world destination.
    state.values['barbarian_hero']['chain']['camera'].update(x=8100,y=19086)
    assert screen_point(state,{'x':8100.82763671875,'y':19081.318359375})==(500,350)
    with pytest.raises(ChainNotReady):screen_point(replace(state,game_version='unknown'),{'x':8100,'y':19086})
    state.values['barbarian_hero']['chain']['camera']['moving']=True
    with pytest.raises(ChainNotReady):screen_point(state,{'x':8100,'y':19086})


@pytest.mark.parametrize('arrives',[True,False])
def test_pan_checks_the_last_allowed_settled_drag_without_adding_another_input(monkeypatch,arrives):
    state=camera_state();camera=state.values['barbarian_hero']['chain']['camera'];camera.update(x=0,y=0)
    now=[100];inputs=[]
    def clock():now[0]+=2;return now[0]
    class Device:
        def drag(self,*args,**kwargs):
            inputs.append(args);camera['x']+=13 if arrives or len(inputs)<4 else 0
    monkeypatch.setattr(WorldNavigator,'world',lambda self:state)
    nav=WorldNavigator(Device(),lambda:state,threading.Event(),clock,lambda:True)
    if arrives:assert nav.pan(lambda s:{'x':60,'y':0}) is state
    else:
        with pytest.raises(ChainNotReady):nav.pan(lambda s:{'x':60,'y':0})
    assert len(inputs)==4


def test_free_approach_changes_the_direction_without_claiming_a_hit_or_mutating_the_snapshot():
    state=enable_chain(form_state());data=state.values['barbarian_hero']['chain']
    data['scene']={key:row for key,row in data['scene'].items() if key=='10300'}
    before=deepcopy(state.values)
    with pytest.raises(ChainNotReady):chain_plan(state,BarbarianOptions())
    approach=chain_approach(state,BarbarianOptions())
    assert approach.plan.neighbours==(10300,) and state.values==before
    moved=deepcopy(state);moved.values['barbarian_hero']['chain']['cityPos']=approach.goal
    assert chain_plan(moved,BarbarianOptions()).neighbours==(10300,)
    assert 'barbarian_chain_free_defeated' not in moved.values


def test_scene_selection_prefers_the_routed_idle_npc_and_never_selects_an_occupied_one():
    state=enable_chain(field_state());army=state.values['barbarian_marches']['123'];army['pos']={'x':0,'y':0}
    army['troop']['units']['1'].update(unitCount=2000,maxCount=2000)
    assert scene_primary(state,BarbarianOptions(),10100)==10100
    state.values['barbarian_hero']['chain']['scene']['10100']['isFighting']=True
    assert scene_primary(state,BarbarianOptions(),10100)!=10100


def test_city_scene_selection_rejects_an_isolated_npc_instead_of_falling_back_to_search():
    state=enable_chain(form_state(),strong=True);scene=state.values['barbarian_hero']['chain']['scene']
    scene['10300']['pos']={'x':4,'y':100}
    assert scene_primary(state,BarbarianOptions(),10100)==10100
    scene['10100']['isFighting']=True
    assert scene_primary(state,BarbarianOptions(),10100) is None
    state.values['barbarian_hero']['chain']['cityPos']=None
    assert scene_primary(state,BarbarianOptions()) is None


@pytest.mark.parametrize('wrong_selection',[False,True])
def test_npc_selection_avoids_the_observed_overlapping_patrol_upper_body(wrong_selection):
    game=BattleCity();game.show('map');state=enable_chain(game.state);target=state.values['barbarian_target']
    state.values['barbarian_hero']['chain']['camera'].update(x=8038.7333984375,y=19101.21484375,distance=216.9910888671875)
    target['pos']={'x':8032.251159667969,'y':19098.197265625}
    state.values['barbarian_hero']['chain']['scene']={str(target['id']):deepcopy(target),'10100':{
        'id':10100,'pos':{'x':8033.037292480469,'y':19099.5830078125}}}
    calls=[]
    class Device:
        def tap_resolved(self,resolve,**kwargs):
            calls.append(resolve());state.values['views']['MapUIBarbarianPopUp']=True
            if wrong_selection:state.values['barbarian_target']['id']=10100
    nav=WorldNavigator(Device(),lambda:state,threading.Event(),lambda:100,lambda:True)
    target_id=target['id']
    if wrong_selection:
        with pytest.raises(ChainNotReady,match='другой'):nav.select(target_id)
    else:nav.select(target_id)
    assert calls==[(308,315)]


def test_native_empty_point_mismatch_prevents_opening_a_march_selector():
    game=BattleCity();game.show('map');game.state.values['barbarian_hero']['chain']={
        'camera':{'x':8100,'y':19086,'distance':219.418045,'moving':False},'emptyPos':None}
    class Device:
        def tap_resolved(self,resolve,**kwargs):
            x,y=resolve();game.inputs.append((x,y));game.state.values['views']['MapEmptySpacePopUp']=True
            game.state.values['barbarian_hero']['chain']['emptyPos']={'x':8000,'y':19000}
        def tap(self,*args,**kwargs):raise AssertionError('No March can follow a wrong ground point')
    navigator=WorldNavigator(Device(),game.observe,threading.Event(),lambda:game.now,lambda:True)
    with pytest.raises(ChainNotReady,match='координаты'):navigator.empty_selector({'x':8100.827637,'y':19081.318359})
    assert len(game.inputs)==1


def test_unknown_modal_blocks_all_world_navigation_input():
    game=BattleCity();game.state.values['views']['UnknownModal']=True
    navigator=WorldNavigator(object(),game.observe,threading.Event(),lambda:game.now,lambda:True)
    with pytest.raises(ChainNotReady):navigator.world()


@pytest.mark.parametrize('x,side,d,expected',[(453,50,52,(660,414)),(520,50,52,(727,414)),
    (530,-50,52,(323,414)),(750,-50,52,(543,414)),(600,-50,137,(393,499))])
def test_npc_attack_card_uses_the_native_layout_even_when_search_and_direct_selection_differ(x,side,d,expected):
    state=camera_state();state.values['views']={'MapHudPanel':True,'MapUIBarbarianPopUp':True}
    from mirage.barbarian_navigation import _A,_B,_C
    camera=state.values['barbarian_hero']['chain']['camera']
    state.values['barbarian_target']['layout']['offset_x']=side
    state.values['barbarian_target']['pos']={'x':camera['x']+(x-480)*_C/(1+_B*d),
        'y':camera['y']-d*_A/(1+_B*d)}
    calls=[]
    class Device:
        def tap_resolved(self,resolve,**kwargs):
            calls.append(resolve());state.values['views']={'MapHudPanel':True,'MapUISelectTroops':True}
    nav=WorldNavigator(Device(),lambda:state,threading.Event(),lambda:100,lambda:True)
    nav.attack_selector(state.values['barbarian_target']['id'])
    assert calls==[expected]


def test_chain_cycle_stops_before_payment_when_a_verified_free_approach_is_needed(tmp_path,monkeypatch):
    from mirage.storage import Store
    from test_barbarians import FarmCity,run_cycle
    game=FarmCity();enable_chain(game.state);data=game.state.values['barbarian_hero']['chain']
    game.show('npc')
    data['scene']={key:row for key,row in data['scene'].items() if key=='10300'}
    store=Store(tmp_path/'farm.sqlite3');positions=[]
    class Navigator:
        def __init__(self,*args):pass
        def position(self,goal,store,target_id,*,options=None):
            assert options.heroes=={'1':3}
            positions.append((goal,target_id));state=deepcopy(game.state)
            store.set_preference('barbarian-session:one',{'task':'barbarian_chain','player':20,'server':3221,
                'phase':'field','count':0,'position_target':target_id,'position_attempts':1})
            return state
    monkeypatch.setattr('mirage.barbarian_navigation.WorldNavigator',Navigator)
    result=run_cycle(game,store,task='barbarian_chain')
    assert len(positions)==1 and result.values['barbarian_pending'] is True
    assert result.values['barbarian_paid_attacks']==0 and store.preference('barbarian-session:one')['phase']=='field'
    assert (695,475) not in game.inputs and (755,230) not in game.inputs


def test_map_only_attack_never_enters_city_or_opens_builtin_search_when_target_is_missing():
    from mirage.barbarians import attack_level_one
    game=BattleCity();game.show('map')
    with pytest.raises(ChainNotReady,match='осмотр карты'):
        attack_level_one(game,game.observe,threading.Event(),lambda:game.now,lambda:True,map_only=True)
    assert not game.inputs


def test_survey_resumes_adjacent_regions_after_empty_views_and_rebinds_on_account_change(monkeypatch):
    game=BattleCity();enable_chain(game.state);game.show('map');data=game.state.values['barbarian_hero']['chain']
    data['scene']={};data['camera'].update(x=0,y=0);destinations=[]
    def pan(self,goal):
        destinations.append(dict(goal));data['camera'].update(goal)
        return game.observe(),True
    monkeypatch.setattr(WorldNavigator,'resources',lambda self:game.observe())
    monkeypatch.setattr(WorldNavigator,'survey_pan',pan)
    nav=WorldNavigator(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    first,target,cursor=nav.survey(BarbarianOptions())
    assert target is None and cursor['index']==3 and cursor['radius']==450
    _,target,next_cursor=nav.survey(BarbarianOptions(),cursor)
    assert target is None and next_cursor['index']==6 and cursor['index']==3
    assert destinations[:2]==[{'x':0,'y':0},{'x':-110,'y':-85}]
    assert not game.inputs and first.values['city_enabled'] is False
    changed={**next_cursor,'identity':{**next_cursor['identity'],'player':999},'rejected':[10100]}
    _,_,reset=nav.survey(BarbarianOptions(),changed)
    assert reset['index']==3 and reset['rejected']==[]


def native_wide_camera():
    return {'x':8007.7236328125,'y':19100.92578125,'moving':False,'distance':214.5641632080078,
        'worldHeight':4500,'wheel':False,'wheelPrefix':'','corners':{
            '1':{'1':7951.3681640625,'2':0,'3':19056.0859375},
            '2':{'1':8064.0732421875,'2':0,'3':19056.0859375},
            '3':{'1':8105.32373046875,'2':0,'3':19178.548828125},
            '4':{'1':7910.11279296875,'2':0,'3':19178.548828125}}}


def test_native_frustum_projection_matches_independent_wide_ground_zoom_measurement():
    state=camera_state();camera=native_wide_camera()
    # The game's strategic ground hold at500/350 itself zoomed its camera to
    # this exact native point; it is independent of the projection code.
    assert screen_point(state,{'x':8010.48193359375,'y':19085.322265625},camera=camera)==(500,350)
    camera['corners']['3']['3']+=1
    with pytest.raises(ChainNotReady):screen_point(state,{'x':8010,'y':19085},camera=camera)


def test_resources_preset_uses_city_hold_and_tree_without_changing_the_viewed_position():
    game=BattleCity();enable_chain(game.state);game.show('map');c=native_wide_camera();c['worldHeight']=1350
    game.state.values['barbarian_hero']['chain']['camera']=c;calls=[]
    class Device:
        def tap(self,x,y,hold_ms=100):
            calls.append((x,y,hold_ms))
            if (x,y)==(45,490):c['wheel']=True
            elif (x,y)==(190,420):c.update(worldHeight=4500,wheel=False)
            else:raise AssertionError('Only the zoom wheel is allowed')
    nav=WorldNavigator(Device(),game.observe,threading.Event(),lambda:game.now,lambda:True)
    nav.resources();nav.resources()
    assert calls==[(45,490,800),(190,420,100)]
    assert (c['x'],c['y'])==(8007.7236328125,19100.92578125) and game.state.values['city_enabled'] is False


def test_strategic_views_are_admitted_only_by_chain_workflow_not_ordinary_farm():
    from mirage.barbarians import barbarian_workflow
    from mirage.barbarian_navigation import RESOURCE_VIEWS
    game=BattleCity();enable_chain(game.state);game.show('map')
    game.state.values['views'].update({name:True for name in RESOURCE_VIEWS})
    assert barbarian_workflow({},task='barbarian_chain').data_condition.matches(game.state)
    assert not barbarian_workflow({},task='barbarians').data_condition.matches(game.state)


def test_wide_survey_can_rank_a_remote_cluster_but_legacy_default_range_cannot():
    state=enable_chain(form_state(),strong=True)
    for row in state.values['barbarian_hero']['chain']['scene'].values():row['pos']['x']+=200
    assert scene_primary(state,BarbarianOptions()) is None
    assert scene_primary(state,BarbarianOptions(),10100,max_distance=450)==10100


def test_distant_survey_group_stages_one_free_waypoint_before_any_paid_attack(tmp_path,monkeypatch):
    from mirage.storage import Store
    from test_barbarians import FarmCity,run_cycle
    game=FarmCity();enable_chain(game.state);game.show('npc');v=game.state.values
    v['barbarian_target']['pos']['x']+=200
    for row in v['barbarian_hero']['chain']['scene'].values():row['pos']['x']+=200
    store=Store(tmp_path/'route.sqlite3');moves=[]
    class Navigator:
        def __init__(self,*args):pass
        def position(self,goal,store,target_id,*,options=None):
            moves.append(dict(goal));store.set_preference('barbarian-session:one',{
                'task':'barbarian_chain','player':20,'server':3221,'phase':'field','count':0,
                'position_target':target_id,'position_attempts':1})
            return game.observe()
    monkeypatch.setattr('mirage.barbarian_navigation.WorldNavigator',Navigator)
    result=run_cycle(game,store,task='barbarian_chain')
    assert moves==[{'x':60,'y':0}] and result.values['barbarian_pending']
    assert store.preference('barbarian-session:one')['route_steps']==1 and not game.inputs


def test_survey_returns_a_loaded_cluster_without_camera_or_search_input():
    game=BattleCity();enable_chain(game.state,strong=True);game.show('map')
    nav=WorldNavigator(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    _,target,cursor=nav.survey(BarbarianOptions(),preferred=10100)
    assert target==10100 and cursor['index']==0 and not game.inputs


def test_survey_stop_prevents_even_the_first_map_input():
    game=BattleCity();enable_chain(game.state);stop=threading.Event();stop.set()
    from mirage.workflows import Cancelled
    with pytest.raises(Cancelled):
        WorldNavigator(game,game.observe,stop,lambda:game.now,lambda:True).survey(BarbarianOptions())
    assert not game.inputs
