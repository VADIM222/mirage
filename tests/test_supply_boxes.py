from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.model import Profile, Snapshot, SupplyBoxOptions
from mirage.supply_boxes import FIELDS, SupplyReceipt, inventory, supply_box_workflow
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady, WorkflowError


def bag(count=3):
    return Snapshot('one',10,20,100.,'1.1.12.20',{
        'hud_visible':True,'hud_menu':True,'in_city':True,'city_enabled':True,
        'queue_panel':{'known':True,'visible':False},'city_selection_known':True,'city_selection':None,
        'views':{'MapHudPanel':True,'ItemBag':True,'CommonBackground':True},
        'resources':{str(i):100000 for i in range(1,7)},
        'supply_inventory':{'ready':True,'items':{'7001':count,'141':10,'142':20,'999':1}},
        'supply_bag_visible':True,'supply_reward_visible':False,'supply_tab':'Other',
        'supply_selected':{'itemId':7001,'itemCount':count,'expireTime':0},'supply_use_count':1,
        'supply_list':{'1':{'itemId':8297},'5':{'itemId':7001}}})


def awarded(state):
    state=deepcopy(state);v=state.values;items=v['supply_inventory']['items']
    items['7001']-=1
    if not items['7001']:del items['7001']
    items['141']+=5;items['142']+=5
    v['supply_selected']['itemCount']-=1
    v.update(supply_reward_visible=True,supply_reward_source=7001,supply_reward_click=True,
        supply_reward_recycle=False,supply_reward_width=586.0723266601562,
        supply_reward_height=366.3492431640625,
        supply_reward_rows={'1':{'Type':2,'SubType':141,'Value':5},'2':{'Type':2,'SubType':142,'Value':5}})
    v['views']['UniversalRewardsCollect']=True
    return state


def test_exact_receipt_accepts_last_box_and_item_loot_without_changing_balances():
    before=bag(1);receipt=SupplyReceipt.capture(before)
    assert receipt.matches(awarded(before))
    assert '7001' in receipt.items  # capture is independent of later inventory edits


def test_receipt_aggregates_repeated_items_and_direct_currency_rewards():
    before=bag();after=awarded(before);v=after.values
    v['supply_reward_rows']['1']['Value']=2
    v['supply_reward_rows']['3']={'Type':2,'SubType':141,'Value':3}
    v['supply_reward_rows']['4']={'Type':1,'SubType':1,'Value':1000}
    v['resources']['1']+=1000
    assert SupplyReceipt.capture(before).matches(after)


@pytest.mark.parametrize('fault',['selected','quantity','bool_quantity','expiry','selected_count','partial',
    'unready','modal','map','disabled_city','missing_currency'])
def test_unconfirmed_selection_never_authorizes_use(fault):
    state=bag();v=state.values
    if fault=='selected':v['supply_selected']['itemId']=7002
    elif fault=='quantity':v['supply_use_count']=2
    elif fault=='bool_quantity':v['supply_use_count']=True
    elif fault=='expiry':v['supply_selected']['expireTime']=123
    elif fault=='selected_count':v['supply_selected']['itemCount']=2
    elif fault=='partial':v['supply_inventory']['items']['$truncated']=True
    elif fault=='unready':v['supply_inventory']['ready']=False
    elif fault=='modal':v['views']['ItemUseConfirmPage']=True
    elif fault=='map':v['in_city']=False
    elif fault=='disabled_city':v['city_enabled']=False
    else:del v['resources']['5']
    with pytest.raises(NotReady):SupplyReceipt.capture(state)


@pytest.mark.parametrize('fault',['source','recycle','click','geometry','nan','reward_type','reward_value',
    'self_reward','partial_reward','missing_loot','extra_item','double_spend','gems','partial_inventory','foreign_window'])
def test_incomplete_or_unrelated_receipt_is_rejected(fault):
    before=bag();after=awarded(before);v=after.values
    if fault=='source':v['supply_reward_source']=7002
    elif fault=='recycle':v['supply_reward_recycle']=True
    elif fault=='click':v['supply_reward_click']=False
    elif fault=='geometry':v['supply_reward_width']=600
    elif fault=='nan':v['supply_reward_height']=float('nan')
    elif fault=='reward_type':v['supply_reward_rows']['1']['Type']=3
    elif fault=='reward_value':v['supply_reward_rows']['1']['Value']=True
    elif fault=='self_reward':v['supply_reward_rows']['1']['SubType']=7001
    elif fault=='partial_reward':v['supply_reward_rows']['$truncated']=True
    elif fault=='missing_loot':v['supply_inventory']['items']['141']-=1
    elif fault=='extra_item':v['supply_inventory']['items']['999']+=1
    elif fault=='double_spend':v['supply_inventory']['items']['7001']-=1
    elif fault=='gems':v['resources']['5']-=1
    elif fault=='partial_inventory':v['supply_inventory']['ready']=False
    else:v['views']['RoutineRewardsCollect']=True
    assert not SupplyReceipt.capture(before).matches(after)


class Route:
    def __init__(self,count=3):
        self.state=bag(count);self.now=100.;self.inputs=[];self.cancelled=threading.Event()
        self.state.values['hud_functions']={'ready':True,'slots':{'3':4}}
        self.cancel_on_select=False;self.cancel_on_use=False;self.bad_receipt=False
        self.popup_on_use=0;self.popup_remaining=0
        self.show('city')
        if not count:del self.state.values['supply_inventory']['items']['7001']

    def show(self,screen):
        v=self.state.values;v.update(supply_bag_visible=screen=='bag',supply_reward_visible=False,
            hud_menu=screen!='city',views={'MapHudPanel':True})
        if screen=='bag':v['views'].update(ItemBag=True,CommonBackground=True)

    def observe(self):
        self.now+=1
        if self.popup_remaining:
            self.state.values['views']['PopupMissionComplete']=True
            self.popup_remaining-=1
        else:self.state.values['views'].pop('PopupMissionComplete',None)
        return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y));v=self.state.values
        if (x,y)==(924,505):self.show('city' if v['hud_menu'] else 'menu')
        elif (x,y)==(624,505):self.show('bag');v['supply_tab']='Res'
        elif (x,y)==(757,62):v['supply_tab']='Other'
        elif (x,y)==(170,270):
            v['supply_selected']['itemId']=7001
            if self.cancel_on_select:self.cancelled.set()
        elif (x,y)==(725,466):
            self.state=awarded(self.state)
            self.popup_remaining=self.popup_on_use
            if self.bad_receipt:self.state.values['supply_inventory']['items']['141']-=1
            if self.cancel_on_use:self.cancelled.set()
        elif (x,y)==(484,398):self.show('bag')
        elif (x,y)==(835,62):self.show('menu')
        else:raise AssertionError((x,y))

    def run(self,limit=1):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            supply_box_workflow({'max_boxes':limit},verified=True),self.cancelled,
            instance_id='one',pid=10,player_id=20)


@pytest.mark.parametrize('count,limit,opened',[(3,1,1),(3,2,2),(1,10,1),(0,10,0)])
def test_full_route_respects_limit_and_inventory_then_returns_city(count,limit,opened):
    game=Route(count);after=game.run(limit)
    assert CITY_HUD.matches(after)
    assert game.inputs.count((725,466))==opened
    assert inventory(after).get('7001',0)==count-opened
    if not count:assert not game.inputs


def test_stop_after_commit_resumes_only_existing_reward_without_reopening():
    game=Route();game.cancel_on_use=True
    with pytest.raises(Cancelled):game.run()
    assert game.inputs.count((725,466))==1 and (484,398) not in game.inputs
    game.cancelled.clear();before=len(game.inputs);after=game.run(10)
    assert after.values['supply_reward_resumed'] and after.values['supply_boxes_opened']==0
    assert game.inputs[before:]==[(484,398),(835,62),(924,505)]
    assert CITY_HUD.matches(after)


def test_cancellation_before_use_prevents_spend():
    game=Route();game.cancel_on_select=True
    # Force a real selection tap rather than an already selected item.
    game.state.values['supply_selected']['itemId']=8297
    with pytest.raises(Cancelled):game.run()
    assert (725,466) not in game.inputs


def test_ambiguous_receipt_times_out_without_retrying_or_confirming():
    game=Route();game.bad_receipt=True
    with pytest.raises(WorkflowError,match='повтор запрещён'):game.run(10)
    assert game.inputs.count((725,466))==1 and (484,398) not in game.inputs


def test_foreign_reward_window_is_not_confirmed_on_resume():
    game=Route();game.show('bag');game.state=awarded(game.state)
    game.state.values['supply_reward_source']=7002
    with pytest.raises(NotReady):game.run()
    assert not game.inputs


def test_completion_popup_can_expire_naturally_after_use_without_a_duplicate():
    game=Route();game.popup_on_use=5
    after=game.run()
    assert CITY_HUD.matches(after) and game.inputs.count((725,466))==1


@pytest.mark.parametrize('value',[True,0,11,'2',1.5])
def test_profile_rejects_invalid_limits(value):
    with pytest.raises(ValueError):Profile('one',tasks={'supply_boxes':{'max_boxes':value}}).validate()


def test_supply_snapshot_stays_within_agent_budget():
    from mirage.memory import PATHS
    assert len(PATHS|FIELDS)<=64
    assert SupplyBoxOptions.from_settings({}).max_boxes==1


def test_registered_supply_factory_uses_validated_profile_limit():
    from mirage.workflows import workflow_for
    profile=Profile('one',tasks={'supply_boxes':{'max_boxes':4}});profile.validate()
    flow=workflow_for('supply_boxes',profile.tasks['supply_boxes'])
    assert flow.verified and flow.steps[0].action.options==SupplyBoxOptions(4)
