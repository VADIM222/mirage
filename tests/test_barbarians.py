from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.barbarians import BARBARIANS, BARBARIAN_DISPATCH, BarbarianMarchReceipt, BarbarianFieldReceipt, FIELDS
from mirage.model import Snapshot
from mirage.workflows import Cancelled, Engine, NotReady, WorkflowError


def form_state():
    form={'DstCharId':159752101,'SrcCharId':144382003,'CharType':1,'CollectResType':-1,
        'SelHeroIds':{'1':3},'SelectUnits':{'1':1467,'2':40},'TotalNum':1507,'isAttackNpc':True,
        'isAggressive':False,'Dispatched':False,'troopType':0,'troopMoveTime':7,'NpcType':641,'NpcLevel':1}
    return Snapshot('one',10,20,100,'1.1.12.20',{'player':{'ServerID':3221},
        'views':{'MapHudPanel':True,'SendTroopsMain':True,'CommonBackground':True},
        'resources':{**{str(i):1000 for i in range(1,7)},'33':10},
        'supply_inventory':{'ready':True,'items':{'181':1}},'barbarian_ap':1500,'barbarian_cost':50,'barbarian_hold':1,
        'barbarian_server':3221,'barbarian_viewed_server':0,'barbarian_marches':{},'barbarian_city':14438200300,
        'barbarian_hero':{'Id':3,'CurrentPage':0,'actionPointTalent':0,'TalentPage':{'0':{'TalentMap':{}}}},
        'troops':{'1':{'unitId':1,'unitCount':1467},'2':{'unitId':2,'unitCount':40}},
        'barbarian_target':{'id':15975210100,'charType':1,'playerId':-2,'owner':-2,'allianceId':0,
            'selection':{'index':0},
            'config':{'ID':641,'Type':1,'Level':1,'CostAP':50,'OnlyRally':0,'KillReward':3001},
            'barbarianType':1,'isFighting':False,'isFteVillage':False,'hp':750,'hpMax':750,
            'npcInfo':{'npcType':641,'npcLevel':1,'barbarianType':1,'summonerId':0,
                'isFteVillage':False,'isS10Special':False,'isS19Special':False},
            'units':{'1':{'unitId':1,'unitCount':750,'maxCount':750}}},
        **{'barbarian_form_'+key:value for key,value in form.items()}})


def accepted(state):
    state=deepcopy(state);v=state.values;v['barbarian_ap']-=50
    v['barbarian_marches']={'123':{'troopId':123,'state':2,'offensive':True,'isFightTarget':False,
        'target':{'charId':15975210100,'charType':1,'playerId':-2},'troop':{'playerId':20,'apTarget':159752101,
            'units':{'1':{'unitId':1,'unitCount':1467,'maxCount':1467},'2':{'unitId':2,'unitCount':40,'maxCount':40}},
            'heros':{'1':{'label':1,'heroId':3}}}}}
    return state


def test_one_exact_ordinary_city_army_and_native_ap_deduction_are_required():
    state=form_state();receipt=BarbarianMarchReceipt.capture(state)
    assert receipt.matches(accepted(state)) and not receipt.matches(state)


def test_non_ap_talents_require_native_nodes_and_do_not_force_a_talent_reset():
    state=form_state();hero=state.values['barbarian_hero']
    hero['TalentPage']['0']['TalentMap']={'1101':1,'1102':3}
    with pytest.raises(NotReady):BarbarianMarchReceipt.capture(state)
    hero['pveTalent']={'cost':0,'nodes':{'804':{'node':64,'level':0},'1007':{'node':84,'level':0}}}
    assert BarbarianMarchReceipt.capture(state).cost==50
    hero['TalentPage']['0']['TalentMap']['804']=1
    with pytest.raises(NotReady):BarbarianMarchReceipt.capture(state)


def test_city_receipt_uses_primary_talents_and_preserves_both_slots():
    state=form_state();v=state.values;hero=v['barbarian_hero']
    hero.update(Id=37,selectedHeroes={'1':37,'2':3},CurrentPage=0,
        TalentPage={'0':{'TalentMap':{'804':3}}},pveTalent={'cost':10,'nodes':{
            '804':{'node':64,'level':3},'1007':{'node':84,'level':0}}})
    v['barbarian_form_SelHeroIds']={'1':37,'2':3}
    receipt=BarbarianMarchReceipt.capture(state)
    assert receipt.cost==40 and receipt.heroes=={'1':37,'2':3}
    after=accepted(state);after.values['barbarian_ap']=v['barbarian_ap']-40
    after.values['barbarian_marches']['123']['troop']['heros']={
        '1':{'label':1,'heroId':37},'2':{'label':2,'heroId':3}}
    assert receipt.matches(after)
    after.values['barbarian_marches']['123']['troop']['heros']['2']['heroId']=15
    assert not receipt.matches(after)
    v['barbarian_form_SelHeroIds']={'1':3,'2':37}
    with pytest.raises(NotReady):BarbarianMarchReceipt.capture(state)


def test_native_strong_form_keeps_zero_rows_out_of_its_dispatch_receipt():
    state=form_state();v=state.values
    v['barbarian_form_SelectUnits']={'1':0,'4':0,'13':22485,'14':27442}
    v['barbarian_form_TotalNum']=49927
    v['troops'].update({'3':{'unitId':13,'unitCount':22592},'4':{'unitId':14,'unitCount':27572}})
    receipt=BarbarianMarchReceipt.capture(state)
    assert receipt.units=={'13':22485,'14':27442}
    after=accepted(state);army=next(iter(after.values['barbarian_marches'].values()))
    army['troop']['units']={str(i):{'unitId':int(id),'unitCount':count,'maxCount':count}
        for i,(id,count) in enumerate(receipt.units.items(),1)}
    assert receipt.matches(after)
    army['troop']['units']['1']['unitId']=16
    assert not receipt.matches(after)


def test_native_level_fourteen_target_matches_its_two_unit_groups_and_requested_level():
    from mirage.barbarians import ordinary_target
    state=form_state();v=state.values;target=v['barbarian_target']
    target['npcInfo'].update(npcType=914,npcLevel=14)
    target['config'].update(ID=914,Level=14,KillReward=3014)
    target.update(hp=32000,hpMax=32000,units={
        '1':{'unitId':5,'unitCount':20000,'maxCount':20000},
        '2':{'unitId':7,'unitCount':12000,'maxCount':12000}})
    v.update(barbarian_form_NpcType=914,barbarian_form_NpcLevel=14)
    assert ordinary_target(state,expected_level=14) is target
    with pytest.raises(NotReady):ordinary_target(state,expected_level=1)
    assert BarbarianMarchReceipt.capture(state).target==target['id']
    target['config']['Type']=2
    with pytest.raises(NotReady):BarbarianMarchReceipt.capture(state)


class CommanderForm:
    def __init__(self):
        self.state=form_state();self.now=100;self.inputs=[];self.missing=False
        v=self.state.values;v['barbarian_form_SelHeroIds']={'1':99,'2':9}
        v['barbarian_form_SelectUnits']={'4':1507};v['barbarian_hero']['Level']=20
        v['barbarian_hero']['dispatch']={'picker':None,'units':[
            {'index':i,'type':i,'unitId':id,'unitCount':30000,'bound':True}
            for i,id in enumerate((13,14,115),1)]}

    def observe(self):
        self.now+=.5;return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y));v=self.state.values;d=v['barbarian_hero']['dispatch'];p=d['picker']
        if (x,y)==(240,200):
            v['views']['HeroSelectPop']=True;d['picker']={'scale':1,'offsetY':0,'isCityWall':False,'slot':1,
                'IsOpenFilterPage':False,'FilterRarity':0,'FilterSpecialized':0,'FilterSpecialties':0,'heroes':[99,3]}
        elif (x,y)==(135,60):p['IsOpenFilterPage']=not p['IsOpenFilterPage']
        elif (x,y)==(692,138):
            for key in ('FilterRarity','FilterSpecialized','FilterSpecialties'):p[key]=0
        elif (x,y)==(470,201):p['FilterRarity']=16;p['heroes']=[37,3,181]
        elif (x,y)==(322,323):p['FilterSpecialties']=2;p['heroes']=[181] if self.missing else [3,181]
        elif (x,y)==(60,145):
            v['barbarian_form_SelHeroIds']['1']=3;v['views'].pop('HeroSelectPop');d['picker']=None
        elif (x,y)==(354,350):v['barbarian_form_SelHeroIds'].pop('2')
        elif (x,y)==(510,475):v.update(barbarian_form_SelectUnits={'4':0},barbarian_form_TotalNum=0)
        elif x==722 and y in (124,185,250):
            id={124:'13',185:'14',250:'115'}[y];v['barbarian_form_SelectUnits'][id]=10000
            v['barbarian_form_TotalNum']=sum(v['barbarian_form_SelectUnits'].values())
        else:raise AssertionError('Unexpected input, including dispatch')


def test_form_preparation_uses_native_filtered_hero_order_and_excludes_siege_without_dispatch():
    from mirage.barbarians import prepare_army
    game=CommanderForm();before=deepcopy(game.state.values['resources'])
    state=prepare_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert state.values['barbarian_form_SelHeroIds']=={'1':3}
    assert state.values['barbarian_form_SelectUnits']=={'4':0,'13':10000,'14':10000,'115':10000}
    assert state.values['resources']==before and (695,475) not in game.inputs


def test_lohar_form_with_missing_redundant_type_uses_exact_visible_unit_ids():
    from mirage.barbarians import prepare_army
    game=CommanderForm();game.state.values['barbarian_form_SelHeroIds']={'1':3}
    for row in game.state.values['barbarian_hero']['dispatch']['units']:row['type']=None
    state=prepare_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert state.values['barbarian_form_SelectUnits']=={'4':0,'13':10000,'14':10000,'115':10000}
    assert (695,475) not in game.inputs
    game=CommanderForm();game.state.values['barbarian_form_SelHeroIds']={'1':3}
    game.state.values['barbarian_hero']['dispatch']['units'][0]['unitId']=16
    with pytest.raises(NotReady):prepare_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert not game.inputs
    game=CommanderForm();game.state.values['barbarian_form_SelHeroIds']={'1':3}
    game.state.values['barbarian_hero']['dispatch']['units'][0]['type']=4
    with pytest.raises(NotReady):prepare_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert not game.inputs


def test_raised_primary_capacity_handles_max_then_clear_before_selecting_combat_units():
    from mirage.barbarians import prepare_army
    class RaisedCapacity(CommanderForm):
        def tap(self,x,y,**kwargs):
            if (x,y)==(510,475) and self.state.values['barbarian_form_TotalNum']==1507:
                self.inputs.append((x,y));self.state.values.update(barbarian_form_SelectUnits={'4':2000},barbarian_form_TotalNum=2000)
            else:super().tap(x,y,**kwargs)
    game=RaisedCapacity();game.state.values['barbarian_form_SelHeroIds']={'1':3}
    state=prepare_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert game.inputs.count((510,475))==2
    assert state.values['barbarian_form_SelectUnits']=={'4':0,'13':10000,'14':10000,'115':10000}
    assert (695,475) not in game.inputs


def test_named_pair_swap_assigns_both_native_slots_without_a_dispatch():
    from mirage.barbarians import prepare_army
    from mirage.model import BarbarianOptions
    class PairForm(CommanderForm):
        def __init__(self):
            super().__init__();v=self.state.values
            v['barbarian_form_SelHeroIds']={'1':3,'2':37};v['barbarian_form_SelectUnits']={'1':1467,'2':40}
            v['barbarian_hero'].update(Id=37,Star=6,selectedHeroes={'1':37,'2':3},deputy={'Id':3})
            v['player']['_commanders']={'heroes':{'37':{'rarity':4,'tags':'4,8,14'},'3':{'rarity':4,'tags':'1,7,11'}}}
        def tap(self,x,y,**kwargs):
            v=self.state.values;d=v['barbarian_hero']['dispatch'];p=d['picker']
            if (x,y) in ((240,200),(354,245)):
                self.inputs.append((x,y));self.slot='1' if x==240 else '2';v['views']['HeroSelectPop']=True
                d['picker']={'scale':1,'offsetY':0,'isCityWall':False,'slot':int(self.slot),'IsOpenFilterPage':False,
                    'FilterRarity':0,'FilterSpecialized':0,'FilterSpecialties':0,'heroes':[99,37 if self.slot=='1' else 3]}
            elif (x,y) in ((470,284),(322,323)):
                self.inputs.append((x,y));p['FilterSpecialties']=16 if y==284 else 2
            elif (x,y)==(470,201):self.inputs.append((x,y));p['FilterRarity']=16
            elif (x,y)==(155,145):
                self.inputs.append((x,y));v['barbarian_form_SelHeroIds'][self.slot]=37 if self.slot=='1' else 3
                v['views'].pop('HeroSelectPop');d['picker']=None
            else:super().tap(x,y,**kwargs)
    game=PairForm();state=prepare_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True,
        BarbarianOptions(primary=37,deputy=3))
    assert state.values['barbarian_form_SelHeroIds']=={'1':37,'2':3}
    assert game.inputs[0]==(354,350) and (354,245) in game.inputs
    assert not any(p in game.inputs for p in ((695,475),(755,230)))


def test_missing_filtered_commander_or_unbound_unit_rows_block_form_preparation():
    from mirage.barbarians import prepare_army
    game=CommanderForm();game.missing=True
    with pytest.raises(NotReady):prepare_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert (60,145) not in game.inputs and (510,475) not in game.inputs
    game=CommanderForm();game.state.values['barbarian_form_SelHeroIds']={'1':3}
    game.state.values['barbarian_hero']['dispatch']['units'][0]['bound']=False
    with pytest.raises(NotReady):prepare_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert not game.inputs


def test_native_confirmed_cavalry_variant_keeps_exact_form_identity():
    state=form_state();state.values['barbarian_target']['npcInfo']['npcType']=901
    with pytest.raises(NotReady):BarbarianMarchReceipt.capture(state)
    state.values['barbarian_target']['config']['ID']=901
    state.values['barbarian_form_NpcType']=901
    assert BarbarianMarchReceipt.capture(state).matches(accepted(state))


def test_a_nearby_army_already_fighting_is_proven_by_original_counts_and_exact_ap_target():
    state=form_state();receipt=BarbarianMarchReceipt.capture(state);after=accepted(state)
    row=after.values['barbarian_marches']['123'];row['isFightTarget']=True
    row['troop']['units']['1']['unitCount']-=24
    assert receipt.matches(after)
    row['troop']['units']['1']['maxCount']-=1
    assert not receipt.matches(after)


def test_combat_cannot_confirm_an_unrelated_ap_destination():
    state=form_state();receipt=BarbarianMarchReceipt.capture(state);after=accepted(state)
    row=after.values['barbarian_marches']['123'];row['isFightTarget']=True;row['troop']['apTarget']+=1
    assert not receipt.matches(after)


@pytest.mark.parametrize('fault',['player','radar','fighting','level','summoned','wrong_destination','null_source',
    'rally','aggressive','already_dispatched','talent','other_hero','siege','insufficient_units','ap','foreign_server'])
def test_other_target_and_form_states_cannot_authorize_attack(fault):
    s=form_state();v=s.values;t=v['barbarian_target']
    if fault=='player':t['owner']=21;t['playerId']=21
    elif fault=='radar':t['npcInfo']['npcType']=1576
    elif fault=='fighting':t['isFighting']=True
    elif fault=='level':t['npcInfo']['npcLevel']=2
    elif fault=='summoned':t['npcInfo']['summonerId']=20
    elif fault=='wrong_destination':v['barbarian_form_DstCharId']+=1
    elif fault=='null_source':v['barbarian_form_SrcCharId']=None
    elif fault=='rally':v['barbarian_form_troopType']=1
    elif fault=='aggressive':v['barbarian_form_isAggressive']=True
    elif fault=='already_dispatched':v['barbarian_form_Dispatched']=True
    elif fault=='talent':v['barbarian_hero']['TalentPage']['0']['TalentMap']={'123':1}
    elif fault=='other_hero':v['barbarian_form_SelHeroIds']={'1':36}
    elif fault=='siege':v['barbarian_form_SelectUnits']={'4':1507}
    elif fault=='insufficient_units':v['troops']['1']['unitCount']=1000
    elif fault=='ap':v['barbarian_ap']=49
    else:v['barbarian_server']=2759
    with pytest.raises(NotReady):BarbarianMarchReceipt.capture(s)


@pytest.mark.parametrize('fault',['target','ap','currency','inventory','units','hero','owner','additional_army'])
def test_unrelated_changes_do_not_count_as_success(fault):
    before=form_state();receipt=BarbarianMarchReceipt.capture(before);s=accepted(before);v=s.values
    row=v['barbarian_marches']['123']
    if fault=='target':row['target']['charId']+=100
    elif fault=='ap':v['barbarian_ap']-=1
    elif fault=='currency':v['resources']['33']-=1
    elif fault=='inventory':v['supply_inventory']['items']={}
    elif fault=='units':row['troop']['units']['1']['unitCount']-=1
    elif fault=='hero':row['troop']['heros']['1']['heroId']=36
    elif fault=='owner':row['troop']['playerId']=21
    else:v['barbarian_marches']['124']={**row,'troopId':124}
    assert not receipt.matches(s)


def test_cancellation_after_input_stops_before_the_first_post_dispatch_read():
    stop=threading.Event();s=form_state();sent=[]
    class Device:
        def tap(self,*args,**kwargs):sent.append(args);stop.set()
    def observe():
        assert not stop.is_set();return deepcopy(s)
    with pytest.raises(Cancelled):Engine(Device(),observe,clock=lambda:100,resolution=(960,540)).execute(
        BARBARIAN_DISPATCH,stop,instance_id='one',pid=10,player_id=20)
    assert sent==[(695,475)]


def test_atomic_reader_budget_is_preserved():
    from mirage.memory import PATHS
    assert len(PATHS|FIELDS)<=64


class BattleCity:
    def __init__(self):
        self.state=form_state();self.now=100;self.inputs=[];self.cancel_on_send=None;self.corrupt=False
        self.search_arrow=False;self.arrow_remaining=0
        self.state.values.update(hud_visible=True,hud_menu=False,in_city=True,city_enabled=True,
            queue_panel={'known':True,'visible':False},city_selection_known=True,city_selection=None,
            guide_force_click=False,guide_click_callback=False,
            barbarian_search={'CurLevel':1},barbarian_index=1,barbarian_popup_x=-387,barbarian_popup_y=174)
        self.show('city')

    def show(self,screen):
        v=self.state.values;v['in_city']=v['city_enabled']=screen=='city';v['views']={'MapHudPanel':True}
        for name in {'search':('MapUISearchMainPage','MapUISearchPopUp'),
                'npc':('MapUIBarbarianPopUp',),'select':('MapUISelectTroops','TroopSelectedPopUp'),
                'form':('SendTroopsMain','CommonBackground')}.get(screen,()):v['views'][name]=True

    def observe(self):
        self.now+=.5;s=replace(deepcopy(self.state),captured_at=self.now)
        if self.arrow_remaining:
            self.arrow_remaining-=1;s.values['views']={'MapHudPanel':True,'Arraw':True}
        return s

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y))
        if (x,y)==(45,490):self.show('map' if self.state.values['city_enabled'] else 'city')
        elif (x,y)==(31,425):self.show('search')
        elif (x,y)==(185,470):pass
        elif (x,y)==(202,365):
            self.show('npc')
            if self.search_arrow:self.arrow_remaining=3
        elif (x,y)==(660,360):self.show('select')
        elif (x,y)==(590,406):self.state.values['barbarian_hold']=1
        elif (x,y)==(755,110):self.show('form')
        elif (x,y)==(695,475):
            self.state=accepted(self.state);self.show('map')
            if self.corrupt:self.state.values['barbarian_marches']['123']['target']['charId']+=100
            if self.cancel_on_send is not None:self.cancel_on_send.set()
        else:raise AssertionError((x,y))

    def run(self,stop=None):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            BARBARIANS,stop or threading.Event(),instance_id='one',pid=10,player_id=20)


def test_full_city_search_selection_and_exact_dispatch_returns_the_screen_to_city():
    from mirage.workflows import CITY_HUD
    game=BattleCity();after=game.run()
    assert CITY_HUD.matches(after) and after.values['barbarian_dispatched']==15975210100
    assert game.inputs==[(45,490),(31,425),(202,365),(660,360),(755,110),(695,475),(45,490)]


def test_busy_army_prevents_another_search_or_attack_on_later_scheduler_checks():
    game=BattleCity();game.state=accepted(game.state);game.show('city');game.run()
    assert not game.inputs


def test_cancelled_accepted_army_is_not_repeated_when_resuming():
    game=BattleCity();stop=threading.Event();game.cancel_on_send=stop
    with pytest.raises(Cancelled):game.run(stop)
    stop.clear();game.cancel_on_send=None;game.run(stop)
    assert game.inputs.count((695,475))==1 and game.inputs.count((202,365))==1


def test_unconfirmed_army_dispatch_is_never_retried():
    game=BattleCity();game.corrupt=True
    with pytest.raises(WorkflowError,match='повтор запрещён'):game.run()
    assert game.inputs.count((695,475))==1


def test_search_arrow_is_observed_until_removed_before_the_next_action():
    game=BattleCity();game.search_arrow=True;game.run()
    assert game.arrow_remaining==0 and game.inputs.count((202,365))==game.inputs.count((695,475))==1


def test_unknown_modal_still_blocks_all_battle_input():
    game=BattleCity();game.state.values['views']['ConfirmWindow']=True
    with pytest.raises(NotReady):game.run()
    assert not game.inputs


def test_search_restores_the_configured_level_with_confirmed_single_step_controls():
    class SearchGame(BattleCity):
        def tap(self,x,y,**kwargs):
            if (x,y) in ((70,291),(334,291)):
                self.inputs.append((x,y));self.state.values['barbarian_search']['CurLevel']+=1 if x==334 else -1
            else:super().tap(x,y,**kwargs)
    game=SearchGame();game.state.values['barbarian_search']['CurLevel']=3
    game.run()
    assert game.inputs.count((70,291))==2 and (334,291) not in game.inputs
    assert game.inputs.index((70,291))<game.inputs.index((202,365))


@pytest.mark.parametrize('screen',['search','npc'])
def test_resuming_confirmed_search_or_target_does_not_reopen_city_or_search(screen):
    game=BattleCity();game.show(screen);game.run()
    assert (45,490) not in game.inputs[:game.inputs.index((695,475))]
    assert (31,425) not in game.inputs
    assert game.inputs.count((202,365))==(screen=='search')


def test_open_legacy_hud_menu_is_closed_once_without_clicking_through_a_modal():
    from mirage.barbarians import close_hud_menu
    game=BattleCity();game.state.values['hud_menu']=True
    class Device:
        def tap(self,x,y,**kwargs):
            assert (x,y)==(920,500);game.inputs.append((x,y));game.state.values['hud_menu']=False
    close_hud_menu(Device(),game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert game.inputs==[(920,500)]
    game.state.values['hud_menu']=True;game.state.values['views']['UnknownModal']=True;game.inputs=[]
    with pytest.raises(NotReady):close_hud_menu(Device(),game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert not game.inputs


def test_ordinary_farming_enables_hold_before_attack_and_does_not_toggle_it_back():
    game=BattleCity();game.state.values['barbarian_hold']=0;game.run()
    assert game.inputs.index((590,406))<game.inputs.index((660,360))
    game=BattleCity();game.run();assert (590,406) not in game.inputs


def test_a_city_army_without_verified_hold_cannot_be_dispatched():
    state=form_state();state.values['barbarian_hold']=0
    with pytest.raises(NotReady):BarbarianMarchReceipt.capture(state)


def field_state():
    s=accepted(form_state());v=s.values;row=v['barbarian_marches']['123']
    row.update(state=4,charId=16007320100,offensive=False,isRally=False,IsAutoPVE=False,IsAutoGather=False,APR=2)
    row.pop('target');row['troop']['isAggressiveRallyCaptain']=False
    row['troop']['units']['1']['unitCount']=1047;row['troop']['units']['2']['unitCount']=0
    v['views']={'MapHudPanel':True,'MapUISelectTroops':True,'TroopSelectedPopUp':True}
    v['barbarian_target']['selection']={'index':1,'popupIndex':1,'target':15975210100,'popupTarget':15975210100,
        'rowType':1,'row':deepcopy(row),'multi':False,'popupMulti':False,'offensive':True,'buyAP':False,
        'travel':22,'actualCost':48}
    return s


def field_accepted(s):
    s=deepcopy(s);v=s.values;v['barbarian_ap']-=v['barbarian_target']['selection']['actualCost']
    row=v['barbarian_marches']['123'];row.update(state=2,offensive=True,
        target={'charId':15975210100,'charType':1,'playerId':-2})
    return s


def test_field_receipt_preserves_original_army_and_uses_actual_game_discount_with_zero_cavalry():
    s=field_state();receipt=BarbarianFieldReceipt.capture(s)
    assert receipt.cost==48 and receipt.matches(field_accepted(s))
    s.values['barbarian_marches']['123']['APR']=7
    s.values['barbarian_target']['selection']['row']['APR']=7
    s.values['barbarian_target']['selection']['actualCost']=43
    assert BarbarianFieldReceipt.capture(s).cost==43


@pytest.mark.parametrize('fault',['index','selected_army','actual','ap','busy','owner','multiselect','buy_ap','hp'])
def test_field_dispatch_requires_the_exact_idle_owned_selection_and_game_cost(fault):
    s=field_state();v=s.values;sel=v['barbarian_target']['selection'];row=v['barbarian_marches']['123']
    if fault=='index':sel['popupIndex']=2
    elif fault=='selected_army':sel['row']['troopId']=124
    elif fault=='actual':sel['actualCost']=50
    elif fault=='ap':v['barbarian_ap']=47
    elif fault=='busy':row['isFightTarget']=True
    elif fault=='owner':row['troop']['playerId']=21
    elif fault=='multiselect':sel['multi']=True
    elif fault=='buy_ap':sel['buyAP']=True
    else:row['troop']['units']['1']['unitCount']=500
    with pytest.raises(NotReady):BarbarianFieldReceipt.capture(s)


@pytest.mark.parametrize('fault',['new_army','char','target','ap','units','items'])
def test_field_receipt_cannot_accept_replacement_armies_or_unrelated_deltas(fault):
    s=field_state();receipt=BarbarianFieldReceipt.capture(s);s=field_accepted(s);v=s.values;row=v['barbarian_marches']['123']
    if fault=='new_army':v['barbarian_marches']={'124':{**row,'troopId':124}}
    elif fault=='char':row['charId']+=100
    elif fault=='target':row['troop']['apTarget']+=1
    elif fault=='ap':v['barbarian_ap']-=1
    elif fault=='units':row['troop']['units']['1']['unitCount']-=1
    else:v['supply_inventory']['items']['181']=0
    assert not receipt.matches(s)


class FarmCity(BattleCity):
    def __init__(self):
        super().__init__()
        for unit in self.state.values['troops'].values():unit.update(badHurt=0,hurt=0)

    def tap_resolved(self,resolve,**kwargs):self.tap(*resolve(),**kwargs)

    def tap(self,x,y,**kwargs):
        v=self.state.values
        if (x,y)==(910,170):
            self.inputs.append((x,y));row=deepcopy(next(iter(v['barbarian_marches'].values())))
            v['barbarian_target']['selection']={'index':1,'popupIndex':1,'target':15975210100,'popupTarget':15975210100,
                'rowType':1,'row':row,'multi':False,'popupMulti':False,'offensive':True,'buyAP':False,
                'travel':22,'actualCost':50-row['APR']}
        elif (x,y)==(755,230):
            self.inputs.append((x,y));self.state=field_accepted(self.state);self.show('map')
        elif (x,y)==(920,145):
            self.inputs.append((x,y));self.show('map');v['views']['AttackPopup']=True
            row=next(iter(v['barbarian_marches'].values()));row['pos']={'x':10,'y':20}
            row['ui']={'target':row['charId'],'buttons':2,'recall':True,'icon':'btn_backb',
                'camera':{'x':10,'y':20,'distance':150,'moving':False}}
        elif (x,y)==(518,346):
            self.inputs.append((x,y));self.show('map');row=next(iter(v['barbarian_marches'].values()))
            row.update(state=2,target={'charId':v['barbarian_city'],'charType':3,'playerId':0})
        else:
            super().tap(x,y,**kwargs)
            if (x,y)==(695,475):
                row=next(iter(self.state.values['barbarian_marches'].values()))
                row.update(charId=16007320100,isRally=False,IsAutoPVE=False,IsAutoGather=False,APR=0)
                row['troop']['isAggressiveRallyCaptain']=False
                for unit in self.state.values['troops'].values():unit['unitCount']=0

    def finish_battle(self):
        row=next(iter(self.state.values['barbarian_marches'].values()))
        row.update(state=4,isFightTarget=False,offensive=False,APR=row['APR']+2)
        row.pop('target',None)


def run_cycle(game,store=None,settings=None,task='barbarians',stop=None):
    from mirage.barbarians import BarbarianCycle,barbarian_workflow
    flow=barbarian_workflow(settings or {},verified=True,store=store,task=task)
    return Engine(game,game.observe,clock=lambda:game.now,resolution=(960,540)).execute(
        flow,stop or threading.Event(),instance_id='one',pid=10,player_id=20)


def test_persistent_farm_reuses_its_army_then_recalls_at_limit_and_accounts_for_return(tmp_path):
    from mirage.storage import Store
    store=Store(tmp_path/'state.sqlite');game=FarmCity()
    run_cycle(game,store,{'max_battles':2});first=store.preference('barbarian-session:one')
    assert first['troop_id']==123 and first['count']==1
    run_cycle(game,store,{'max_battles':2});assert game.inputs.count((695,475))==1
    game.finish_battle();run_cycle(game,store,{'max_battles':2})
    assert store.preference('barbarian-session:one')['count']==2
    assert game.inputs.count((755,230))==1 and game.inputs.count((755,110))==1
    game.finish_battle();run_cycle(game,store,{'max_battles':2})
    assert store.preference('barbarian-session:one')['phase']=='returning' and game.inputs.count((518,346))==1
    game.state.values['barbarian_marches']={}
    game.state.values['troops']['1'].update(unitCount=1450,badHurt=17)
    game.state.values['troops']['2'].update(unitCount=30,badHurt=10)
    after=run_cycle(game,store,{'max_battles':2})
    assert after.values['barbarian_session_completed'] and store.preference('barbarian-session:one') is None


def test_another_mode_cannot_take_the_persistent_army_lease(tmp_path):
    from mirage.storage import Store
    store=Store(tmp_path/'state.sqlite');game=FarmCity();run_cycle(game,store);game.finish_battle();game.inputs=[]
    with pytest.raises(NotReady,match='другой задачей'):run_cycle(game,store,task='barbarian_chain')
    assert not game.inputs


def test_an_untracked_manual_army_is_not_adopted_as_a_farm():
    game=FarmCity();game.state.values.update(field_state().values);game.show('city')
    with pytest.raises(NotReady,match='не закреплена'):run_cycle(game)
    assert not game.inputs


def test_changing_pair_recalls_previous_owned_army_before_a_new_march(tmp_path):
    from mirage.storage import Store
    store=Store(tmp_path/'state.sqlite');game=FarmCity();run_cycle(game,store)
    game.finish_battle();game.inputs=[]
    run_cycle(game,store,{'primary':37,'deputy':3})
    assert store.preference('barbarian-session:one')['phase']=='returning'
    assert (518,346) in game.inputs and (695,475) not in game.inputs and (755,230) not in game.inputs


def test_cancelled_send_recovers_the_saved_intent_without_repeating_input(tmp_path):
    from mirage.storage import Store
    store=Store(tmp_path/'state.sqlite');game=FarmCity();stop=threading.Event();game.cancel_on_send=stop
    with pytest.raises(Cancelled):run_cycle(game,store,stop=stop)
    assert store.preference('barbarian-session:one')['phase']=='intent'
    stop.clear();game.cancel_on_send=None;run_cycle(game,store)
    assert store.preference('barbarian-session:one')['count']==1
    assert game.inputs.count((695,475))==1


def test_missing_returned_units_keep_the_session_owned_and_prevent_a_new_attack(tmp_path):
    from mirage.storage import Store
    store=Store(tmp_path/'state.sqlite');game=FarmCity();run_cycle(game,store,{'max_battles':1})
    game.finish_battle();run_cycle(game,store,{'max_battles':1});game.state.values['barbarian_marches']={};game.inputs=[]
    with pytest.raises(NotReady,match='не сходятся'):run_cycle(game,store,{'max_battles':1})
    assert not game.inputs and store.preference('barbarian-session:one')['phase']=='returning'


def test_return_accepts_a_centered_native_popup_at_the_observed_automatic_zoom(tmp_path):
    from mirage.barbarians import recall_army
    game=FarmCity();game.state.values.update(field_state().values);game.show('city')
    row=game.state.values['barbarian_marches']['123'];row['pos']={'x':10,'y':20}
    game.show('map');game.state.values['views']['AttackPopup']=True
    row['ui']={'target':row['charId'],'buttons':2,'recall':True,'icon':'btn_backb',
        'camera':{'x':10.2,'y':20.2,'distance':270.82757568359375,'moving':False}}
    after=recall_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert (518,346) in game.inputs and (920,145) not in game.inputs


def test_return_accepts_the_observed_large_army_model_focus_offset():
    from mirage.barbarians import recall_army
    game=FarmCity();game.state.values.update(field_state().values);game.show('map')
    game.state.values['views']['AttackPopup']=True
    row=game.state.values['barbarian_marches']['123'];row['pos']={'x':8000.586364746094,'y':19111.1142578125}
    row['ui']={'target':row['charId'],'buttons':2,'recall':True,'icon':'btn_backb','camera':{
        'x':7999.51123046875,'y':19112.212890625,'distance':210.9237518310547,'moving':False}}
    recall_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert (518,346) in game.inputs and (920,145) not in game.inputs


def test_large_mixed_formation_uses_the_observed_interior_recall_hit_region():
    from mirage.barbarians import recall_army
    class LargeFormation(FarmCity):
        def tap(self,x,y,**kwargs):
            if (x,y)==(500,346):
                super().tap(518,346,**kwargs);self.inputs[-1]=(500,346)
            else:super().tap(x,y,**kwargs)
    game=LargeFormation();game.state.values.update(field_state().values);game.show('map')
    game.state.values['views']['AttackPopup']=True;row=game.state.values['barbarian_marches']['123']
    row['pos']={'x':8098.086853027344,'y':19084.92529296875}
    row['ui']={'target':row['charId'],'buttons':2,'recall':True,'icon':'btn_backb','camera':{
        'x':8099.64599609375,'y':19084.896484375,'distance':219.4180450439453,'moving':False}}
    recall_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert (500,346) in game.inputs and (518,346) not in game.inputs and (920,145) not in game.inputs


def test_recall_closes_the_legacy_hud_menu_before_focusing_the_owned_army():
    from mirage.barbarians import recall_army
    class LegacyHud(FarmCity):
        def tap(self,x,y,**kwargs):
            if (x,y)==(920,500):self.inputs.append((x,y));self.state.values['hud_menu']=False
            else:super().tap(x,y,**kwargs)
    game=LegacyHud();game.state.values.update(field_state().values);game.show('map');game.state.values['hud_menu']=True
    recall_army(game,game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert game.inputs.index((920,500))<game.inputs.index((920,145))


def test_recall_uses_native_projection_for_the_observed_vertical_formation_offset():
    from mirage.barbarians import recall_army
    from mirage.barbarian_navigation import screen_point
    game=FarmCity();game.state.values.update(field_state().values);game.show('map')
    game.state.values['views']['AttackPopup']=True;row=game.state.values['barbarian_marches']['123']
    row['pos']={'x':7924.085632324219,'y':19084.0048828125}
    row['ui']={'target':row['charId'],'buttons':2,'recall':True,'icon':'btn_backb','camera':{
        'x':7923.9326171875,'y':19085.5546875,'distance':209.71026611328125,'moving':False}}
    px,py=screen_point(game.state,row['pos'],camera=row['ui']['camera']);button=(px+38,py+76)
    class Device:
        def tap(self,x,y,**kwargs):
            if (x,y)==(45,490):game.tap(x,y,**kwargs)
            else:
                assert (x,y)==button;game.tap(518,346,**kwargs);game.inputs[-1]=(x,y)
    recall_army(Device(),game.observe,threading.Event(),lambda:game.now,lambda:True)
    assert 515<=button[0]<=530 and 365<=button[1]<=380 and game.inputs==[button,(45,490)]
