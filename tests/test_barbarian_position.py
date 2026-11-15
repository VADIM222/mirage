from copy import deepcopy

import pytest

from mirage.barbarian_position import CombatMoveReceipt,FieldPositionReceipt,PositionReceipt
from mirage.workflows import NotReady
from test_barbarians import accepted,form_state


def position_form():
    state=form_state();v=state.values
    v.update(barbarian_cost=-1,barbarian_form_DstCharId=-1,barbarian_form_CharType=None,
        barbarian_form_isAttackNpc=False)
    v['barbarian_hero']['dispatch']={'goal':{'1':10,'2':20},'formGoal':{'1':10,'2':20},
        'empty':True,'target':-1,'offensive':False}
    return state


def arrived(state):
    state=accepted(state);v=state.values;v['barbarian_ap']+=50
    row=next(iter(v['barbarian_marches'].values()))
    row.update(charId=16007320100,state=4,isFightTarget=False,offensive=False,isRally=False,
        IsAutoPVE=False,IsAutoGather=False,pos={'x':10,'y':20})
    return state


def test_position_requires_exact_free_form_and_arrival_without_ap_or_item_cost():
    state=position_form();state.values['barbarian_ap']=1490;receipt=PositionReceipt.capture(state)
    assert receipt.matches(arrived(state))
    later=arrived(state);later.values['barbarian_ap']+=1
    assert receipt.matches(later) and receipt.matches(later,recovering=True)
    assert state.values['barbarian_form_NpcType']==641  # stale NPC cache is not the free destination


@pytest.mark.parametrize('fault',['paid','not_empty','selector_target','goal','src','fighting','wrong_point','ap','heroes','items'])
def test_position_never_accepts_a_paid_attack_or_an_unrelated_army(fault):
    state=position_form();receipt=PositionReceipt.capture(state)
    if fault in ('paid','not_empty','selector_target','goal','src'):
        v=state.values;ui=v['barbarian_hero']['dispatch']
        if fault=='paid':v['barbarian_form_isAttackNpc']=True
        elif fault=='not_empty':ui['empty']=False
        elif fault=='selector_target':ui['target']=123
        elif fault=='goal':ui['formGoal']['1']+=1
        else:v['barbarian_form_SrcCharId']=None
        with pytest.raises(NotReady):PositionReceipt.capture(state)
    else:
        state=arrived(state);v=state.values;row=next(iter(v['barbarian_marches'].values()))
        if fault=='fighting':row['isFightTarget']=True
        elif fault=='wrong_point':row['pos']['x']+=1
        elif fault=='ap':v['barbarian_ap']-=1
        elif fault=='heroes':row['troop']['heros']['1']['heroId']=9
        else:v['supply_inventory']['items']['181']-=1
        assert not receipt.matches(state)


def field_form():
    state=arrived(position_form());v=state.values
    v['views']={'MapHudPanel':True,'MapUISelectTroops':True,'TroopSelectedPopUp':True}
    row=next(iter(v['barbarian_marches'].values()))
    row.update(APR=2);row['troop']['isAggressiveRallyCaptain']=False
    # The same maximum can contain fewer healthy troops after a previous battle.
    row['troop']['units']['1']['unitCount']-=10
    v['barbarian_hero']['dispatch']['selection']={'selectIndex':2,'popup_selectIndex':2,'type':1,
        'isMultiSelectMode':False,'popup_isMultiSelectMode':False,'popup_ShowPveAPBuy':False,
        'popup_troopMoveTime':5,'row':{'troopId':row['troopId'],'charId':row['charId'],'state':4}}
    return state


def test_free_field_receipt_keeps_exact_army_and_surviving_composition():
    state=field_form();state.values['barbarian_ap']=1490;receipt=FieldPositionReceipt.capture(state)
    assert receipt.units!=receipt.maximum and receipt.matches(state)
    state.values['barbarian_ap']+=1
    assert receipt.matches(state)
    other=deepcopy(state);row=next(iter(other.values['barbarian_marches'].values()))
    row['charId']+=100
    assert not receipt.matches(other)
    row['charId']=receipt.char_id;row['troop']['units']['1']['unitCount']+=1
    assert not receipt.matches(other)


@pytest.mark.parametrize('field,value',[('popup_selectIndex',1),('isMultiSelectMode',True),
    ('popup_ShowPveAPBuy',True),('popup_troopMoveTime',None),('type',0)])
def test_free_field_receipt_rejects_wrong_or_incomplete_selection(field,value):
    state=field_form();state.values['barbarian_hero']['dispatch']['selection'][field]=value
    with pytest.raises(NotReady):FieldPositionReceipt.capture(state)


def test_field_move_persists_intent_before_input_and_never_repeats_uncertain_send(tmp_path):
    import threading
    from mirage.barbarian_position import position_field_army
    from mirage.storage import Store
    from mirage.workflows import WorkflowError
    state=field_form();receipt=FieldPositionReceipt.capture(state);store=Store(tmp_path/'farm.sqlite3')
    key='barbarian-session:'+state.instance_id
    session={'task':'barbarian_chain','player':state.player_id,'server':state.values['barbarian_server'],
        'phase':'field','count':2,'troop_id':receipt.troop_id,'char_id':receipt.char_id,'maximum':receipt.maximum}
    store.set_preference(key,session);inputs=[];now=[0]
    class Device:
        def tap(self,x,y,**kwargs):
            assert store.preference(key)['phase']=='free_move_intent';inputs.append((x,y))
    def clock():now[0]+=100;return now[0]
    moving=deepcopy(state);next(iter(moving.values['barbarian_marches'].values()))['state']=2
    observed=iter([state,moving])
    with pytest.raises(WorkflowError):position_field_army(Device(),lambda:next(observed),threading.Event(),clock,lambda:True,store=store)
    assert store.preference(key)['count']==2 and inputs==[(755,230)]
    with pytest.raises(NotReady):position_field_army(Device(),lambda:state,threading.Event(),clock,lambda:True,store=store)
    assert inputs==[(755,230)]


@pytest.mark.parametrize('phase',['moving','arrived','unknown'])
def test_restart_recovers_field_move_without_another_march(tmp_path,monkeypatch,phase):
    import threading
    from dataclasses import asdict
    from mirage.barbarians import BarbarianCycle
    from mirage.model import BarbarianOptions
    from mirage.storage import Store
    state=field_form();receipt=FieldPositionReceipt.capture(state);store=Store(tmp_path/'farm.sqlite3')
    key='barbarian-session:'+state.instance_id
    session={'task':'barbarian_chain','player':state.player_id,'server':state.values['barbarian_server'],
        'phase':'free_move_intent','count':2,'troop_id':receipt.troop_id,'char_id':receipt.char_id,
        'maximum':receipt.maximum,'move_intent':asdict(receipt)}
    store.set_preference(key,session);row=next(iter(state.values['barbarian_marches'].values()))
    if phase=='moving':row['state']=2
    elif phase=='unknown':row['pos']['x']+=10
    state.values['barbarian_ap']+=1
    monkeypatch.setattr('mirage.barbarians.attack_level_one',lambda *args,**kwargs:state)
    cycle=BarbarianCycle(BarbarianOptions(),store,'barbarian_chain')
    if phase=='unknown':
        with pytest.raises(NotReady):cycle(object(),lambda:state,threading.Event(),lambda:0,lambda:True)
    else:cycle(object(),lambda:state,threading.Event(),lambda:0,lambda:True)
    saved=store.preference(key)
    assert saved['count']==2
    assert saved['phase']==('field' if phase=='arrived' else 'free_move_intent')
    assert ('move_intent' in saved)==(phase!='arrived')


def test_unknown_interrupted_transition_cannot_be_treated_as_an_idle_owned_army(tmp_path):
    import threading
    from mirage.barbarians import BarbarianCycle
    from mirage.model import BarbarianOptions
    from mirage.storage import Store
    state=field_form();receipt=FieldPositionReceipt.capture(state);store=Store(tmp_path/'farm.sqlite3')
    store.set_preference('barbarian-session:'+state.instance_id,{'task':'barbarian_chain','player':state.player_id,
        'server':state.values['barbarian_server'],'phase':'unconfirmed_transition','troop_id':receipt.troop_id,
        'char_id':receipt.char_id,'maximum':receipt.maximum,'count':0})
    with pytest.raises(NotReady,match='переход'):
        BarbarianCycle(BarbarianOptions(),store,'barbarian_chain')(object(),lambda:state,threading.Event(),lambda:0,lambda:True)


def combat_form():
    state=field_form();row=next(iter(state.values['barbarian_marches'].values()))
    row.update(state=2,isFightTarget=True,offensive=True);row['troop']['apTarget']=1234
    state.values['barbarian_hero']['dispatch']['selection']['row']['state']=2
    return state


def combat_move_ack(state):
    state=deepcopy(state);row=next(iter(state.values['barbarian_marches'].values()))
    row.update(offensive=False,isFightTarget=False)
    row['troop']['units']['1']['unitCount']-=5
    return state


def test_combat_move_allows_natural_losses_and_regeneration_but_never_another_paid_target():
    state=combat_form();receipt=CombatMoveReceipt.capture(state);after=combat_move_ack(state)
    after.values['barbarian_ap']+=1
    assert receipt.matches(after) and 'barbarian_chain_free_defeated' not in after.values
    row=next(iter(after.values['barbarian_marches'].values()));row['troop']['apTarget']+=1
    assert not receipt.matches(after)
    row['troop']['apTarget']=receipt.ap_target;after.values['barbarian_ap']=receipt.ap-1
    assert not receipt.matches(after)


def test_combat_move_uses_the_owned_lease_and_persists_one_free_intent_before_input(tmp_path):
    import threading
    from mirage.barbarian_position import move_combat_army
    from mirage.storage import Store
    state=combat_form();receipt=CombatMoveReceipt.capture(state);store=Store(tmp_path/'farm.sqlite3')
    key='barbarian-session:'+state.instance_id
    store.set_preference(key,{'task':'barbarian_chain','player':state.player_id,'server':state.values['barbarian_server'],
        'phase':'field','count':1,'troop_id':receipt.troop_id,'char_id':receipt.char_id,'maximum':receipt.maximum,
        'intent':{'target':receipt.ap_target*100}})
    calls=[]
    class Device:
        def tap(self,x,y,**kwargs):
            assert store.preference(key)['phase']=='combat_move_intent';calls.append((x,y))
    observed=iter([state,combat_move_ack(state)])
    after=move_combat_army(Device(),lambda:next(observed),threading.Event(),lambda:0,lambda:True,store=store)
    lease=store.preference(key)
    assert calls==[(755,230)] and after.values['barbarian_pull_started'] is True
    assert lease['count']==1 and lease['pull_attempted'] is True and lease['phase']=='field'
    assert 'combat_move_intent' not in lease


def test_cancelled_combat_move_recovers_its_acknowledgment_without_another_input(tmp_path):
    import threading
    from mirage.barbarian_position import move_combat_army
    from mirage.barbarians import BarbarianCycle
    from mirage.model import BarbarianOptions
    from mirage.storage import Store
    from mirage.workflows import Cancelled
    state=combat_form();receipt=CombatMoveReceipt.capture(state);store=Store(tmp_path/'farm.sqlite3');stop=threading.Event()
    key='barbarian-session:'+state.instance_id
    store.set_preference(key,{'task':'barbarian_chain','player':state.player_id,'server':state.values['barbarian_server'],
        'phase':'field','count':1,'troop_id':receipt.troop_id,'char_id':receipt.char_id,'maximum':receipt.maximum,
        'intent':{'target':receipt.ap_target*100}})
    calls=[]
    class Device:
        def tap(self,x,y,**kwargs):calls.append((x,y));stop.set()
    with pytest.raises(Cancelled):move_combat_army(Device(),lambda:state,stop,lambda:0,lambda:True,store=store)
    assert store.preference(key)['phase']=='combat_move_intent'
    stop.clear();after=combat_move_ack(state)
    result=BarbarianCycle(BarbarianOptions(),store,'barbarian_chain')(Device(),lambda:after,stop,lambda:0,lambda:True)
    assert result.values['barbarian_pending'] is True and calls==[(755,230)]
    assert store.preference(key)['phase']=='field' and store.preference(key)['count']==1
