from copy import deepcopy
from dataclasses import replace

import pytest

from mirage.barbarian_chain import ChainEvidence,ChainNotReady,chain_plan,native_baseline,patrol_plan
from mirage.model import BarbarianOptions
from mirage.storage import Store
from test_barbarians import FarmCity,form_state,run_cycle


def enable_chain(state,strong=False):
    v=state.values;target=v['barbarian_target'];target['pos']={'x':10,'y':0}
    target['layout']={'offset_x':50,'offset_y':0,'atkBtnY':-122,'stayToggleY':-187}
    npc=deepcopy(target['npcInfo'])
    scene={str(id):{'id':id,'playerId':-2,'owner':-2,'isFighting':False,'npcInfo':deepcopy(npc),'config':deepcopy(target['config']),
        'hp':750,'hpMax':750,'pos':pos} for id,pos in
        ((10100,{'x':11,'y':1}),(10200,{'x':12,'y':-1}),(10300,{'x':4,'y':0}))}
    v['barbarian_hero'].update(awaked=False,Skills={'1':{'SkillId':30,'Level':1}},chain={
        'cityPos':{'x':0,'y':0},'client':{'ID':30,'AREA_ID':6,'TARGET':2},
        'area':{'AreaID':6,'AreaType':2,'Target':2,'Radius':9,'Angle':120,'MaxTar':3},'scene':scene,'reports':{}})
    from mirage.barbarian_navigation import _A,_B,_C
    v['barbarian_hero']['chain']['camera']={'x':10+27*_C/(1-2*_B),'y':-2*_A/(1-2*_B),
        'distance':219.4180450439453,'moving':False}
    if strong:
        v['troops']['1']['unitCount']=3000
        v['barbarian_form_SelectUnits']['1']=3000;v['barbarian_form_TotalNum']=3040
    return state


def test_candidates_follow_native_cone_and_max_targets_instead_of_a_fixed_free_count():
    state=enable_chain(form_state(),strong=True);plan=chain_plan(state,BarbarianOptions())
    assert plan.neighbours==(10100,10200) and 10300 not in plan.neighbours
    state.values['barbarian_hero']['chain']['area']['MaxTar']=2
    assert chain_plan(state,BarbarianOptions()).neighbours==(10100,)


def test_lazy_visual_geometry_is_versioned_and_never_overrides_a_conflicting_native_table():
    state=enable_chain(form_state());data=state.values['barbarian_hero']['chain']
    data.update(client=None,area=None)
    plan=chain_plan(state,BarbarianOptions())
    assert plan.geometry_source=='verified-native:1.1.12.20:30:6'
    with pytest.raises(ChainNotReady):chain_plan(replace(state,game_version='unknown'),BarbarianOptions())
    data['client']={'ID':31,'AREA_ID':6,'TARGET':2}
    with pytest.raises(ChainNotReady):chain_plan(state,BarbarianOptions())


def test_sun_tzu_in_deputy_slot_supplies_geometry_without_relabelling_primary():
    state=enable_chain(form_state(),strong=True);v=state.values;hero=v['barbarian_hero']
    deputy=deepcopy(hero);deputy['chain']={'client':None,'area':None}
    hero.update(Id=37,awaked=True,Skills={'1':{'SkillId':42,'Level':5}},
        deputy=deputy,selectedHeroes={'1':37,'2':3})
    hero['chain'].update(client=None,area=None);v['barbarian_form_SelHeroIds']={'1':37,'2':3}
    plan=chain_plan(state,BarbarianOptions(primary=37,deputy=3))
    assert hero['Id']==37 and plan.neighbours==(10100,10200)
    assert plan.geometry_source=='verified-native:1.1.12.20:30:6'
    deputy['Id']=99
    with pytest.raises(ChainNotReady):chain_plan(state,BarbarianOptions(primary=37,deputy=99))


def zhuge_state():
    state=enable_chain(form_state(),strong=True);v=state.values;hero=v['barbarian_hero']
    hero.update(Id=37,Level=60,awaked=True,Skills={'1':{'SkillId':56,'Level':5}},
        selectedHeroes={'1':37,'2':179},deputy={'Id':179,'Level':40,'awaked':False,
            'Skills':{'1':{'SkillId':243,'Level':4}},'chain':{'client':None,'area':None}})
    hero['chain'].update(client=None,area=None);v['barbarian_form_SelHeroIds']={'1':37,'2':179}
    return state


def test_verified_zhuge_circle_in_second_slot_includes_targets_behind_without_using_a_sun_cone():
    state=zhuge_state();options=BarbarianOptions(primary=37,deputy=179)
    plan=chain_plan(state,options)
    assert set(plan.neighbours)=={10100,10200,10300}
    assert plan.radius==10 and plan.angle==360 and plan.geometry_source.endswith(':243:15')
    state.values['barbarian_hero']['deputy']['chain']['client']={'ID':243,'AREA_ID':15,'TARGET':2}
    with pytest.raises(ChainNotReady):chain_plan(state,options)
    state=zhuge_state()
    with pytest.raises(ChainNotReady):chain_plan(replace(state,game_version='unknown'),options)


def test_observed_pair_budget_is_labelled_and_does_not_apply_to_another_threshold_or_skill():
    from mirage.barbarian_chain import combat_budget
    state=zhuge_state();v=state.values;hero=v['barbarian_hero'];deputy=hero['deputy'];skill=deputy['Skills']['1']
    v['barbarian_form_SelectUnits']={'13':22323,'14':27287,'115':33375}
    options=BarbarianOptions(primary=37,deputy=179,level=17,max_level=20,min_health=20)
    budget,source=combat_budget(state,options,deputy,skill)
    assert budget==82985*150//100 and source.endswith(':37-179:allowance1.50')
    assert combat_budget(state,replace(options,min_health=50),deputy,skill)==(82985,'native-counts')
    skill['Level']=5
    assert combat_budget(state,options,deputy,skill)==(budget,source)
    skill['Level']=3
    assert combat_budget(state,options,deputy,skill)==(82985,'native-counts')


@pytest.mark.parametrize('missing',['client','area'])
def test_partial_visual_table_load_fills_only_missing_verified_geometry_and_rejects_conflicts(missing):
    from mirage.barbarian_chain import ZHUGE_CLIENT,ZHUGE_AREA
    state=zhuge_state();geometry=state.values['barbarian_hero']['deputy']['chain']
    geometry.update(client={**ZHUGE_CLIENT,'HeroVideo':3},area=dict(ZHUGE_AREA));geometry[missing]=None
    options=BarbarianOptions(primary=37,deputy=179)
    assert chain_plan(state,options).geometry_source.endswith(':243:15')
    if missing=='area':geometry['client']['TARGET']=2
    else:geometry['area']['Radius']=8
    with pytest.raises(ChainNotReady):chain_plan(state,options)


def test_chain_minimum_level_applies_to_neighbours_and_primary_can_be_above_minimum():
    state=enable_chain(form_state(),strong=True);v=state.values;target=v['barbarian_target']
    target['npcInfo'].update(npcLevel=2,npcType=642);target['config'].update(ID=642,Level=2,KillReward=3002)
    plan=chain_plan(state,BarbarianOptions(level=1,max_level=2))
    assert plan.target==target['id']
    with pytest.raises(ChainNotReady):chain_plan(state,BarbarianOptions(level=2,max_level=2))


def test_a_smaller_army_selects_one_affordable_neighbour_and_rejects_an_insufficient_army():
    state=enable_chain(form_state())
    assert chain_plan(state,BarbarianOptions()).neighbours==(10100,)
    state.values['troops']['1']['unitCount']=1000
    state.values['barbarian_form_SelectUnits']['1']=1000;state.values['barbarian_form_TotalNum']=1040
    with pytest.raises(ChainNotReady,match='недостаточно'):chain_plan(state,BarbarianOptions())


def test_idle_city_siege_and_unselected_stock_cannot_inflate_the_chain_combat_budget():
    state=enable_chain(form_state());v=state.values
    v['troops']['1']['unitCount']=1000000
    v['barbarian_form_SelectUnits']['1']=1000;v['barbarian_form_TotalNum']=1040
    with pytest.raises(ChainNotReady,match='недостаточно'):chain_plan(state,BarbarianOptions())
    v['views']={'MapHudPanel':True};v['troops']['1']['unitCount']=1000
    v['troops']['siege']={'unitId':4,'unitCount':1000000}
    with pytest.raises(ChainNotReady,match='недостаточно'):chain_plan(state,BarbarianOptions())


def test_observed_balanced_t4_allowance_is_labelled_and_limited_to_the_verified_hero_route():
    state=enable_chain(form_state());v=state.values;t=v['barbarian_target'];t['npcInfo'].update(npcLevel=14,npcType=914)
    t['config'].update(ID=914,Level=14,KillReward=3014);t.update(hp=32000,hpMax=32000,units={
        '1':{'unitId':5,'unitCount':20000,'maxCount':20000},'2':{'unitId':7,'unitCount':12000,'maxCount':12000}})
    v['barbarian_hero'].update(Level=20,Skills={'1':{'SkillId':30,'Level':5}})
    v['barbarian_form_SelectUnits']={'13':22461,'14':27423,'115':33499}
    neighbour=deepcopy(v['barbarian_hero']['chain']['scene']['10100']);neighbour.update(hp=72000,hpMax=72000)
    neighbour['npcInfo'].update(npcLevel=20,npcType=820);neighbour['config'].update(ID=820,Level=20,KillReward=3020)
    v['barbarian_hero']['chain']['scene']={'10100':neighbour}
    options=BarbarianOptions.from_settings({'level':14,'max_level':20})
    plan=chain_plan(state,options)
    assert plan.strength_source.startswith('observed-combat:') and plan.neighbours==(10100,)
    v['barbarian_hero']['Level']=19
    with pytest.raises(ChainNotReady,match='недостаточно'):chain_plan(state,options)
    v['barbarian_hero']['Level']=20
    with pytest.raises(ChainNotReady,match='недостаточно'):
        chain_plan(state,BarbarianOptions.from_settings({'level':14,'max_level':21}))


def test_distant_patrol_is_only_a_bounded_pull_plan_and_never_a_free_victory():
    state=enable_chain(form_state(),strong=True);data=state.values['barbarian_hero']['chain']
    data['scene']={key:row for key,row in data['scene'].items() if key=='10300'}
    data['scene']['10300']['pos']={'x':18,'y':0}
    target=state.values['barbarian_target']
    data['scene'][str(target['id'])]=deepcopy(target)
    with pytest.raises(ChainNotReady):chain_plan(state,BarbarianOptions())
    plan=patrol_plan(state,BarbarianOptions())
    assert plan.requires_pull is True and plan.neighbours==(10300,)
    assert not ChainEvidence.start(plan,123).free_defeated
    data['cityPos']={'x':200,'y':0}
    with pytest.raises(ChainNotReady,match='области подхода'):patrol_plan(state,BarbarianOptions())
    data['cityPos']={'x':0,'y':0}
    data['scene']['10300']['pos']['x']=19
    with pytest.raises(ChainNotReady):patrol_plan(state,BarbarianOptions())
    data['scene']['10300']['pos']['x']=50
    with pytest.raises(ChainNotReady):patrol_plan(state,BarbarianOptions())


def test_resumed_combat_restarts_the_quiet_period_before_recall(tmp_path):
    store=Store(tmp_path/'farm.sqlite3');game=FarmCity();enable_chain(game.state)
    game.show('npc')
    run_cycle(game,store,task='barbarian_chain');game.finish_battle()
    key='barbarian-session:one';lease=store.preference(key);lease.update(pull_goal={'x':15,'y':0},
        pull_attempted=True,pull_idle_since=game.now-20);store.set_preference(key,lease)
    scene=game.state.values['barbarian_hero']['chain']['scene']
    scene[str(lease['char_id'])]={'isFighting':True}
    result=run_cycle(game,store,{'max_battles':1},task='barbarian_chain')
    assert result.values['barbarian_pending'] and store.preference(key)['pull_idle_since'] is None
    scene[str(lease['char_id'])]['isFighting']=False
    run_cycle(game,store,{'max_battles':1},task='barbarian_chain')
    assert store.preference(key)['phase']=='field' and (920,145) not in game.inputs
    game.now+=6
    run_cycle(game,store,{'max_battles':1},task='barbarian_chain')
    assert store.preference(key)['phase']=='returning'


def test_lost_cluster_keeps_owned_army_in_field_and_continues_map_survey(tmp_path,monkeypatch):
    store=Store(tmp_path/'farm.sqlite3');game=FarmCity()
    run_cycle(game,store);game.finish_battle();enable_chain(game.state);game.show('npc')
    previous_inputs=len(game.inputs)
    key='barbarian-session:one';lease=store.preference(key);lease['task']='barbarian_chain';store.set_preference(key,lease)
    def missing(*args,**kwargs):raise ChainNotReady('Сосед ушёл после подхода')
    monkeypatch.setattr('mirage.barbarians.attack_level_one',missing)
    def world(self):game.show('map');return game.observe()
    monkeypatch.setattr('mirage.barbarian_navigation.WorldNavigator.world',world)
    result=run_cycle(game,store,task='barbarian_chain')
    assert result.values['barbarian_pending'] and result.values['barbarian_no_cluster']
    assert store.preference(key)['phase']=='field'
    assert (518,346) not in game.inputs and game.inputs.count((695,475))==1
    assert not game.inputs[previous_inputs:]


@pytest.mark.parametrize('fault',['player','owner','fighting','special','radar','summoned','level','hp','outside','wrong_skill','wrong_area','partial'])
def test_unverified_or_occupied_neighbours_never_authorize_chain_input(fault):
    state=enable_chain(form_state());data=state.values['barbarian_hero']['chain'];data['scene'].pop('10200')
    row=data['scene']['10100']
    if fault=='player':row['playerId']=21
    elif fault=='owner':row['owner']=21
    elif fault=='fighting':row['isFighting']=True
    elif fault=='special':row['npcInfo']['barbarianType']=4
    elif fault=='radar':row['config']['Type']=20
    elif fault=='summoned':row['npcInfo']['summonerId']=20
    elif fault=='level':row['npcInfo']['npcLevel']=2
    elif fault=='hp':row['hp']=700
    elif fault=='outside':row['pos']['x']=40
    elif fault=='wrong_skill':state.values['barbarian_hero']['Skills']['1']['SkillId']=10
    elif fault=='wrong_area':data['client']['ID']=31
    else:data['scene']['$truncated']=True
    with pytest.raises(ChainNotReady):chain_plan(state,BarbarianOptions())


def test_disappearing_enemies_and_foreign_battles_are_not_free_victories():
    state=enable_chain(form_state());plan=chain_plan(state,BarbarianOptions());proof=ChainEvidence.start(plan,123)
    proof.observe(troop_id=124,ap_target=proof.ap_target,contacts=[(10100,124)],results=[(10100,124,True)])
    proof.observe(troop_id=123,ap_target=proof.ap_target,contacts=[],results=[(10100,123,True)])
    assert not proof.free_defeated
    proof.observe(troop_id=123,ap_target=proof.ap_target,contacts=[(10100,123)],results=[(10100,123,True)])
    assert proof.free_defeated=={10100}
    restored=ChainEvidence.from_dict(proof.to_dict());assert restored.free_defeated=={10100}
    restored.observe(troop_id=123,ap_target=999,contacts=[],results=[])
    assert not restored.free_defeated


def test_chain_is_a_distinct_owned_workflow_and_counts_a_new_attributable_native_report(tmp_path):
    store=Store(tmp_path/'state.sqlite');game=FarmCity();enable_chain(game.state)
    game.show('npc')
    run_cycle(game,store,task='barbarian_chain');lease=store.preference('barbarian-session:one')
    assert lease['task']=='barbarian_chain' and lease['count']==1
    assert lease['chain_plan']['neighbours']==[10100] and lease['evidence']['candidates']==[10100,10200,10300]
    data=game.state.values['barbarian_hero']['chain']
    data['reports']['new']={'player':20,'server':3221,'charId':160073201,'troopId':123,'omitted':False,
        'start':1000,'end':1010,'battle':1,'attacks':{'101':{'id':101,'player':-2,'type':1,'barbarianType':1,
            'Kill':{'Cnt':0,'Max':750,'Death':750},'Damage':{'Cnt':1000,'Death':0}}}}
    after=run_cycle(game,store,task='barbarian_chain')
    assert after.values['barbarian_chain_free_defeated']==1
    assert game.inputs.count((695,475))==1 and (755,230) not in game.inputs


def test_no_cluster_stays_on_map_without_search_payment_or_lease(tmp_path,monkeypatch):
    from mirage.workflows import MAP_HUD
    store=Store(tmp_path/'state.sqlite');game=FarmCity();enable_chain(game.state)
    game.state.values['barbarian_hero']['chain']['scene']={}
    from mirage.barbarian_navigation import WorldNavigator
    monkeypatch.setattr(WorldNavigator,'resources',lambda self:game.observe())
    monkeypatch.setattr(WorldNavigator,'survey_pan',lambda self,goal:(game.observe(),True))
    after=run_cycle(game,store,task='barbarian_chain')
    assert MAP_HUD.matches(after) and after.values['barbarian_no_cluster'] and after.values['barbarian_pending']
    assert store.preference('barbarian-session:one') is None
    assert game.inputs==[(45,490)]
    assert store.preference('barbarian-survey:one')['index']==3
    assert after.values['barbarian_survey_pending']


@pytest.mark.parametrize('fault',['baseline','owner','server','char','troop','partial','not_defeated','not_same_hp'])
def test_only_new_complete_results_of_the_exact_own_army_can_count_as_free(fault):
    from test_barbarians import field_state
    state=enable_chain(field_state());state.values['barbarian_marches']['123']['pos']={'x':0,'y':0}
    state.values['barbarian_marches']['123']['troop']['units']['1'].update(unitCount=2000,maxCount=2000)
    plan=chain_plan(state,BarbarianOptions());proof=ChainEvidence.start(plan,123)
    report={'player':20,'server':3221,'charId':160073201,'troopId':123,'omitted':False,
        'start':1000,'end':1010,'battle':1,'attacks':{'101':{'id':101,'player':-2,'type':1,'barbarianType':1,
            'Kill':{'Cnt':0,'Max':750,'Death':750},'Damage':{'Cnt':1000,'Death':0}}}}
    if fault=='owner':report['player']=21
    elif fault=='server':report['server']=3222
    elif fault=='char':report['charId']+=1
    elif fault=='troop':report['troopId']=124
    elif fault=='partial':report['omitted']=True
    elif fault=='not_defeated':report['attacks']['101']['Kill']['Cnt']=1
    elif fault=='not_same_hp':report['attacks']['101']['Kill']['Max']=749
    state.values['barbarian_hero']['chain']['reports']={'new':report}
    proof.observe_state(state,16007320100,['new'] if fault=='baseline' else [])
    assert not proof.free_defeated


@pytest.mark.parametrize('occupied',[False,True])
def test_a_patrol_entering_later_needs_a_pre_payment_idle_baseline_and_its_own_report(occupied):
    from test_barbarians import field_state
    state=enable_chain(field_state());army=state.values['barbarian_marches']['123']
    army['pos']={'x':0,'y':0};army['troop']['units']['1'].update(unitCount=2000,maxCount=2000)
    plan=chain_plan(state,BarbarianOptions());assert 10300 not in plan.neighbours
    scene=state.values['barbarian_hero']['chain']['scene'];scene['10300']['isFighting']=occupied
    baseline=native_baseline(state,1,plan.target);proof=ChainEvidence.start(plan,123,baseline=baseline)
    assert not proof.free_defeated  # a captured patrol is not an engagement or a result
    state.values['barbarian_hero']['chain']['reports']={'new':{'player':20,'server':3221,'charId':160073201,
        'troopId':123,'omitted':False,'start':1000,'end':1010,'battle':1,'attacks':{'103':{
            'id':103,'player':-2,'type':1,'barbarianType':1,'Kill':{'Cnt':0,'Max':750,'Death':750},
            'Damage':{'Cnt':1000,'Death':0}}}}}
    proof.observe_state(state,16007320100,[])
    assert proof.free_defeated==(frozenset() if occupied else {10300})
