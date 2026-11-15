from copy import deepcopy
import threading

import pytest

from mirage.gather import FIELDS, GatherOptions, MarchReceipt, gather_workflow, own_troops, search_popup_matches
from mirage.model import Snapshot
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady, WorkflowError


def form():
    values={'resources':{str(i):10000 for i in range(1,7)},'gather_city_id':57610300,
        'views':{'MapHudPanel':True,'SendTroopsMain':True,'CommonBackground':True},
        'gather_count':0,'gather_troops':{},'gather_view_SendTroopsMain':True,
        'gather_target':{'id':119670600,'charType':6,'isFighting':False,
            'rss':{'playerId':0,'resType':1,'level':2,'remain':315000,'isFighting':False,'rss_troops':{}}}}
    fields={'DstCharId':1196706,'SrcCharId':576103,'CollectResType':1,'CharType':6,'troopType':0,
        'TotalNum':7648,'SelectUnits':{'4':7648},'SelHeroIds':{'1':32,'2':15},'TotalLoad':318156.8,
        'troopMoveTime':53.77,'isAggressive':False,'isAttackNpc':False,'Dispatched':False}
    values.update({'gather_form_'+key:value for key,value in fields.items()})
    return Snapshot('ld:one:1',23282,198113569,100,'1.1.12.20',values)


def dispatched(state):
    state=deepcopy(state)
    state.values.update(gather_count=1,gather_troop_ids={'10213890100':10213890100},gather_troops={
        '951243':{'troopId':951243,'state':2,'isFightTarget':False,'offensive':False,
            'charId':10213890100,'charType':1,
            'target':{'charId':119670600,'charType':6,'resType':1,'playerId':0},
            'troop':{'playerId':198113569,'units':{'1':{'unitId':4,'unitCount':7648,'maxCount':7648}},
                'heros':{'1':{'label':1,'heroId':32},'2':{'label':2,'heroId':15}}}}})
    return state


def test_dispatch_uses_local_and_server_ids_and_exact_army_ledger():
    before=form()
    receipt=MarchReceipt.capture(before,GatherOptions())
    assert receipt.matches(dispatched(before))


@pytest.mark.parametrize('fault',['occupied','fighting','level','target','source','aggressive','attack',
    'already_sent','capacity','units','commander','travel','currency','count','unknown_units','modal','incoming'])
def test_any_unconfirmed_target_form_or_army_blocks_the_sending_input(fault):
    state=form();v=state.values;rss=v['gather_target']['rss']
    if fault=='occupied':rss['playerId']=123
    elif fault=='fighting':rss['isFighting']=True
    elif fault=='level':rss['level']=9
    elif fault=='target':v['gather_form_DstCharId']+=1
    elif fault=='source':v['gather_form_SrcCharId']+=1
    elif fault=='aggressive':v['gather_form_isAggressive']=True
    elif fault=='attack':v['gather_form_isAttackNpc']=True
    elif fault=='already_sent':v['gather_form_Dispatched']=True
    elif fault=='capacity':v['gather_form_TotalLoad']=314999
    elif fault=='units':v['gather_form_SelectUnits']={'1':7648}
    elif fault=='commander':v['gather_form_SelHeroIds']={'1':32,'2':32}
    elif fault=='travel':v['gather_form_troopMoveTime']=181
    elif fault=='currency':v['resources']['5']=None
    elif fault=='count':v['gather_count']=1
    elif fault=='unknown_units':v['gather_form_SelectUnits']['$truncated']=True
    elif fault=='incoming':v['gather_target']['charAlerts']={'other':{'troopId':10}}
    else:v['views']['UnknownPurchase']=True
    with pytest.raises(NotReady):MarchReceipt.capture(state,GatherOptions())


@pytest.mark.parametrize('fault',['different_target','different_player','partial_units','hurt','different_hero',
    'extra_march','currency','truncated','fighting'])
def test_dispatch_receipt_rejects_unrelated_partial_or_changed_server_results(fault):
    before=form();receipt=MarchReceipt.capture(before,GatherOptions());after=dispatched(before)
    v=after.values;row=v['gather_troops']['951243'];troop=row['troop']
    if fault=='different_target':row['target']['charId']+=100
    elif fault=='different_player':troop['playerId']+=1
    elif fault=='partial_units':troop['units']['1']['unitCount']-=1
    elif fault=='hurt':troop['units']['1']['maxCount']+=1
    elif fault=='different_hero':troop['heros']['2']['heroId']=16
    elif fault=='extra_march':
        v['gather_troops']['951244']=deepcopy(row);v['gather_troops']['951244']['troopId']=951244;v['gather_count']=2
    elif fault=='currency':v['resources']['5']-=1
    elif fault=='truncated':troop['units']['$truncated']=True
    else:row['isFightTarget']=True
    assert not receipt.matches(after)


def test_arrival_keeps_the_queue_occupied_even_when_map_troop_ids_disappear():
    before=form();receipt=MarchReceipt.capture(before,GatherOptions());after=dispatched(before)
    v=after.values;v['gather_troop_ids']={};row=v['gather_troops']['951243']
    row.update(state=6,charId=119670600,charType=6,collectSpeed=.119735)
    del row['target']
    v['gather_target']['rss']['playerId']=after.player_id
    assert len(own_troops(after))==1
    assert receipt.matches(after)
    with pytest.raises(NotReady):MarchReceipt.capture(after,GatherOptions())


def test_existing_march_cannot_be_mistaken_for_a_new_dispatch():
    state=dispatched(form())
    state.values['gather_view_SendTroopsMain']=True
    receipt=MarchReceipt.capture(state,GatherOptions(max_marches=2))
    assert not receipt.matches(state)


def test_selected_commander_filter_does_not_silently_accept_a_different_pair():
    state=form()
    assert MarchReceipt.capture(state,GatherOptions(primary=32,deputy=15))
    with pytest.raises(NotReady):MarchReceipt.capture(state,GatherOptions(primary=15,deputy=32))


@pytest.mark.parametrize('settings',[{'level':True},{'max_marches':0},{'level':5,'max_level':4},
    {'resource':5},{'max_travel':601},{'primary':32,'deputy':32}])
def test_bad_gathering_settings_are_rejected(settings):
    with pytest.raises(ValueError):GatherOptions.from_settings(settings)


@pytest.mark.parametrize('resource',[1,2,3,4])
@pytest.mark.parametrize('limit',[1,2,3,4,5])
def test_verified_resources_accept_the_total_occupied_army_limit(resource,limit):
    from mirage.workflows import workflow_for
    workflow=workflow_for('gather_resources',{'resource':resource,'max_marches':limit})
    assert workflow.verified and not workflow.requires_city
    assert workflow.steps[0].action.options.resource==resource
    assert workflow.steps[0].action.options.max_marches==limit


@pytest.mark.parametrize('resource',[0,5])
def test_non_resource_and_gem_routes_remain_blocked(resource):
    from mirage.workflows import workflow_for
    with pytest.raises(ValueError):workflow_for('gather_resources',{'resource':resource})


@pytest.mark.parametrize('resource,anchor',[(1,-202),(2,-2),(3,198),(4,396)])
def test_search_buttons_require_the_resource_specific_observed_popup_anchor(resource,anchor):
    state=form();v=state.values
    v.update(gather_search_index=resource+2,gather_view_MapUISearchPopUp=True,
             gather_popup_x=anchor,gather_popup_y=174.000015)
    assert search_popup_matches(state,resource)
    v['gather_popup_x']+=20
    assert not search_popup_matches(state,resource)
    v['gather_popup_x']=anchor;v['gather_search_index']=1
    assert not search_popup_matches(state,resource)


def test_gather_snapshot_stays_inside_the_agents_bounded_request_budget():
    from mirage.memory import PATHS
    assert not PATHS.keys()&FIELDS.keys()
    assert len(PATHS)+len(FIELDS)<=64


class Route:
    """Observed UI transitions, with injected target races and delivery ambiguity."""
    def __init__(self,resource=1,max_marches=1):
        self.resource=resource;self.settings={'resource':resource,'max_marches':max_marches}
        self.state=form()
        self.state.values['gather_target']['rss']['resType']=resource
        self.state.values['gather_form_CollectResType']=resource
        self.state.values.update(hud_visible=True,hud_menu=False,in_city=True,city_enabled=True,
            views={'MapHudPanel':True},queue_panel={'known':True,'visible':False},
            city_selection_known=True,city_selection=None,gather_view_SendTroopsMain=False,
            gather_search_runtime={str(resource):{'CurLevel':8}},
            gather_popup_x={1:-202,2:-2,3:198,4:396}[resource],gather_popup_y=174.)
        self.now=100
        self.inputs=[]
        self.claim_target=False
        self.wrong_receipt=False
        self.after_input=lambda point:None

    def clock(self):return self.now

    def observe(self):
        self.now+=1
        return Snapshot(self.state.instance_id,self.state.pid,self.state.player_id,self.now,
                        self.state.game_version,deepcopy(self.state.values))

    def show(self,*names):
        v=self.state.values
        v['views']={'MapHudPanel':True,**{name:True for name in names}}
        for name in ('MapUISearchMainPage','MapUISearchPopUp','ResDepositPopUp','MapUISelectTroops','SendTroopsMain'):
            v['gather_view_'+name]=name in names

    def tap(self,x,y,*,hold_ms):
        assert hold_ms==100
        point=(x,y);v=self.state.values;self.inputs.append(point)
        category,center={1:(330,335),2:(475,480),3:(620,624),4:(770,767)}[self.resource]
        if point==(45,490):
            v['city_enabled']=not v['city_enabled'];self.show()
        elif point==(45,400):self.show('MapUISearchMainPage','MapUISearchPopUp')
        elif point==(category,470):v['gather_search_index']=self.resource+2
        elif point==(center-105,315):v['gather_search_runtime'][str(self.resource)]['CurLevel']-=1
        elif point==(center,365):self.show('ResDepositPopUp')
        elif point==(690,365):
            self.show('MapUISelectTroops','TroopSelectedPopUp')
            v.update(gather_select_target=119670600,gather_select_resource=self.resource)
        elif point==(755,110):
            self.show('SendTroopsMain','CommonBackground')
            if self.claim_target:v['gather_target']['rss']['playerId']=999
        elif point==(695,475):
            previous=deepcopy(v['gather_troops'])
            self.state=dispatched(self.state)
            self.state.values['gather_troops']['951243']['target']['resType']=self.resource
            self.state.values['gather_troops'].update(previous)
            self.state.values['gather_count']=len(self.state.values['gather_troops']);self.show()
            if self.wrong_receipt:self.state.values['gather_troops']['951243']['target']['charId']+=100
        else:raise AssertionError(point)
        self.after_input(point)

    def back(self):
        self.inputs.append(('back',))
        self.show()

    def execute(self,cancelled=None):
        return Engine(self,self.observe,clock=self.clock,resolution=(960,540)).execute(
            gather_workflow(self.settings,verified=True),cancelled or threading.Event(),
            instance_id=self.state.instance_id,pid=self.state.pid,player_id=self.state.player_id)


@pytest.mark.parametrize('resource',[1,2,3,4])
def test_full_route_sends_once_returns_from_world_over_own_city_and_respects_occupied_queue(resource):
    game=Route(resource=resource);after=game.execute()
    assert CITY_HUD.matches(after)
    assert game.inputs.count((695,475))==1
    count=len(game.inputs)
    game.execute()
    assert len(game.inputs)==count


def test_wood_route_preserves_user_marches_sends_once_and_counts_them_against_limit():
    game=Route(resource=2,max_marches=2)
    existing=dispatched(form()).values['gather_troops']['951243']
    existing['troopId']=951240
    game.state.values.update(gather_count=1,gather_troops={'951240':existing})
    after=game.execute()
    assert CITY_HUD.matches(after) and set(own_troops(after))=={'951240','951243'}
    assert after.values['gather_troops']['951240']==existing
    assert (475,470) in game.inputs and (480,365) in game.inputs
    assert game.inputs.count((695,475))==1
    count=len(game.inputs);game.execute()
    assert len(game.inputs)==count


def test_target_claimed_during_form_opening_prevents_dispatch():
    game=Route();game.claim_target=True
    with pytest.raises(NotReady):game.execute()
    assert (695,475) not in game.inputs


def test_ambiguous_delivery_never_retries_march_or_sends_again_on_the_next_check():
    game=Route();game.wrong_receipt=True
    with pytest.raises(WorkflowError,match='повтор'):game.execute()
    assert game.inputs.count((695,475))==1
    count=len(game.inputs)
    game.execute()
    assert game.inputs[count:]==[(45,490)]
    assert game.inputs.count((695,475))==1


def test_pause_at_form_opening_prevents_the_sending_input():
    game=Route();cancelled=threading.Event()
    game.after_input=lambda point:cancelled.set() if point==(755,110) else None
    with pytest.raises(Cancelled):game.execute(cancelled)
    assert (695,475) not in game.inputs
    # Resuming closes the old form before starting a fresh, validated route.
    game.after_input=lambda point:None
    assert CITY_HUD.matches(game.execute())
    assert game.inputs.count(('back',))==1 and game.inputs.count((695,475))==1


def test_resume_after_a_delivered_march_closes_the_form_without_sending_again():
    game=Route();game.state=dispatched(game.state)
    game.state.values['city_enabled']=False
    game.show('SendTroopsMain','CommonBackground')
    assert CITY_HUD.matches(game.execute())
    assert game.inputs==[('back',),(45,490)]


def test_unknown_modal_is_never_closed_on_resume():
    game=Route();game.show('SendTroopsMain','UnknownPurchase')
    with pytest.raises(NotReady):game.execute()
    assert not game.inputs


def test_an_unknown_modal_still_blocks_an_occupied_queue_noop():
    game=Route();game.state=dispatched(game.state);game.show('UnknownPurchase')
    with pytest.raises(NotReady):game.execute()
    assert not game.inputs
