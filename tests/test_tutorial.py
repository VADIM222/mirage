from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.model import Snapshot
from mirage.model import TutorialOptions, Profile
from mirage.tutorial import (DIALOGS, FIELDS, BuildReceipt, ChapterReceipt, CollectReceipt,
    StartingKeyReceipt, StoryReceipt, TutorialGuide, TutorialUpgradeReceipt, battle_point,
    VipIntroBoxReceipt, VipIntroPointReceipt, dialog_point, tutorial_workflow)
from mirage.workflows import Cancelled, Engine, NotReady, WorkflowError


def state(step=2):
    cfg={'StepType':'DIALOG','EndCondition':'EVENT_TUTORIAL_CLICK_DIALOG','TextKey':DIALOGS.get(step,''),
        'NPC':'BRAINMAN','NPCSide':'LEFT','Target':'','Ext':''}
    return Snapshot('one',10,20,100.,'1.1.12.20',{'server_time':100000,'resources':{str(i):10000 for i in range(1,7)},
        'views':{'MapHudPanel':True,'FTECover':True,'TutorialSkipPage':True,'Dialog':True},
        'tutorial':{'ready':True,'active':True,'name':'slg_2_v4','type':'FTE','step':step,'config':cfg,'enterTime':90000,
            'dialogVisible':True,'dialog':{'TextID':cfg['TextKey'],'NPC':'BRAINMAN','NPCSide':'LEFT','BuildingTarget':''}}})


@pytest.mark.parametrize('fault',['config','step','type','dialog','modal','right','choice','partial'])
def test_dialog_requires_exact_current_step_and_live_content(fault):
    s=state();d=s.values['tutorial']
    if fault=='config':d['name']='other'
    elif fault=='step':d['step']=True
    elif fault=='type':d['config']['StepType']='CLICK_UI'
    elif fault=='dialog':d['dialog']['TextID']='other'
    elif fault=='modal':s.values['views']['PurchaseConfirm']=True
    elif fault=='right':d['dialog']['NPCSide']='RIGHT'
    elif fault=='choice':d['dialog']['BuildingTarget']='buy'
    else:d['config']['$truncated']=True
    with pytest.raises(NotReady):dialog_point(s)


class Route:
    def __init__(self):
        self.state=state();self.now=100.;self.inputs=[];self.cancelled=threading.Event()
        self.no_ack=False;self.cancel_after=False

    def observe(self):
        self.now+=1;return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        assert (x,y)==(790,490);self.inputs.append((x,y))
        if not self.no_ack:self.state=state(self.state.values['tutorial']['step']+1)
        if self.cancel_after:self.cancelled.set()

    def run(self):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            tutorial_workflow({},verified=True),self.cancelled,instance_id='one',pid=10,player_id=20)


def test_intro_advances_each_dialog_once_and_stops_at_unknown_step():
    game=Route();s=game.run()
    assert len(game.inputs)==5 and s.values['tutorial']['step']==7
    with pytest.raises(NotReady):game.run()
    assert len(game.inputs)==5


def test_unacknowledged_dialog_is_not_repeated_and_stop_prevents_next_input():
    game=Route();game.no_ack=True
    with pytest.raises(WorkflowError,match='повтор'):game.run()
    assert len(game.inputs)==1
    game=Route();game.cancel_after=True
    with pytest.raises(Cancelled):game.run()
    assert len(game.inputs)==1


def test_snapshot_budget():
    from mirage.memory import PATHS
    assert len(PATHS|FIELDS)<=64


def gift_state(step):
    s=state(step);d=s.values['tutorial'];d.update(name='slg_2_towncenter_3',type='TRIGGERED')
    s.values['supply_inventory']={'ready':True,'items':{'1':2}}
    s.values['views']={'MapHudPanel':True,'FTECover':True,'RoutineRewardsCollect':True,'CommonBackground':True}
    loot={str(i):dict(ID=23330001,Type=1,SubType=k,Value=v) for i,(k,v) in enumerate(((1,10000),(2,10000),(5,50)),1)}
    d['config']={'StepType':'WAIT','Target':'GIFT_3'}
    d['gift']={'rewardId':23330001,'loot':loot,'claiming':True,'bubble':False,'arrived':True,
        'popup':{'showing':True,'flew':False,'rows':deepcopy(loot)}}
    return s


def test_gift_claim_requires_exact_loot_and_one_credit_without_inventory_spend():
    from mirage.tutorial import GiftClaimReceipt
    s=gift_state(20);r=GiftClaimReceipt.capture(s)
    s.values['tutorial']['step']=21;s.values['views'].pop('RoutineRewardsCollect')
    for k,v in (('1',10000),('2',10000),('5',50)):s.values['resources'][k]+=v
    assert r.matches(s)
    s.values['resources']['5']+=50
    assert not r.matches(s)
    s=gift_state(20);s.values['tutorial']['gift']['popup']['rows']['1']['Value']=9999
    with pytest.raises(NotReady):GiftClaimReceipt.capture(s)


def test_gift_reveal_never_credits_reward_before_confirmation():
    from mirage.tutorial import GiftRevealReceipt
    s=gift_state(19);d=s.values['tutorial'];s.values['views'].pop('RoutineRewardsCollect');s.values['views'].pop('CommonBackground')
    d['config']={'StepType':'COLLECT','Target':'SLG_2_Aethelflad_GiftIcon','ExtFunAtBegin':'GiftPerformanceShowBubble'}
    d['cover']={'Target':'SLG_2_Aethelflad_GiftIcon'};d['gift'].update(claiming=None,bubble=True)
    r=GiftRevealReceipt.capture(s);after=gift_state(20)
    assert r.matches(after)
    after.values['resources']['1']+=10000
    assert not r.matches(after)


def test_fred_submit_waits_for_actual_fragment_and_claimed_quest_not_just_next_dialog():
    from mirage.tutorial import FredTransitionReceipt
    s=state(7);d=s.values['tutorial'];d.update(name='slg_2_towncenter_5_1',type='TRIGGERED',
        followPos={'1':-4.415,'2':.042,'3':0},chapterQuests={'10':{'Id':10,'Status':2}})
    target='AidFredPopup.AidFredPopup_BtnGreen1'
    d['config']={'StepType':'CLICK_UI','Target':target}
    d['cover']={'CoverName':'GeneralRight','Target':target}
    d['fred']={'chapter':2,'firstQuest':{'ID':10,'RewardID':23330011},
        'loot':{'1':{'ID':23330011,'Type':2,'Value':1,'SubType':10990,'DefaultSortIndex':1}}}
    s.values['views']={'MapHudPanel':True,'AidFredPopup':True,'CommonBackground':True}
    s.values['supply_inventory']={'ready':True,'items':{}}
    r=FredTransitionReceipt.capture(s);d['step']=8;d['chapterQuests']['10']['Status']=3
    assert not r.matches(s)
    s.values['supply_inventory']['items']['10990']=1
    assert r.matches(s)
    s.values['supply_inventory']['items']['10990']=2
    assert not r.matches(s)


def test_new_signup_claim_requires_its_event_task_and_exact_free_key():
    from mirage.tutorial import NewSignupReceipt
    s=state(4);d=s.values['tutorial'];d.update(name='slg_2_new_event',type='TRIGGERED')
    d['config']={'StepType':'CLICK_UI','Target':'SLG_2_EVENT_REWARD'}
    d['guide']={'forceClick':True,'needClickCb':False,'is3D':False,'worldPos':{'1':-4.29072,'2':-2.55872,'3':0}}
    d['signup']={'current':'5124','id':'5124','server':3221,'end':200,
        'ui':{'UIType':'NewSignup','LastEventId':'5124'},
        'task':{'TaskID':1,'Value':1,'ScoreRuleKey':'login_daily','Loots':{'1':{'Value':1,'Type':2,'SubType':47}},
            'AddtionLoots':{},'Addtion2Loots':{}},'playerTasks':{'1':{'TaskId':1,'TaskStatus':-1}}}
    s.values.update(player={'ServerID':3221},supply_inventory={'ready':True,'items':{'47':1}},
        views={'MapHudPanel':True,'QuestGuide':True,'AllUIEventMainPage_SLG':True,'CommonBackground':True})
    assert TutorialGuide().matches(s)
    r=NewSignupReceipt.capture(s)
    d.update(active=False,completed=True,step=6)
    d['signup']['playerTasks']['1']['TaskStatus']=-2;s.values['supply_inventory']['items']['47']=2
    assert r.matches(s)
    s.values['resources']['5']-=1
    assert not r.matches(s)


def test_highlight_delay_is_observed_before_a_known_click():
    game=Route();game.state=state(47);d=game.state.values['tutorial'];d['enterTime']=100000
    d['config']={'StepType':'CLICK_UI','Target':'SLG_2_BARBARAIN_MISSION',
        'EndCondition':'EVENT_TUTORIAL_CLICK_UI','CoverName':'GeneralRight','HighlightDelay':3000}
    d.update(coverVisible=True,cover={'Target':'SLG_2_BARBARAIN_MISSION','CoverName':'GeneralRight'})
    def observe():
        game.now+=1;game.state.values['server_time']+=500
        return replace(deepcopy(game.state),captured_at=game.now)
    def tap(x,y,**kwargs):
        assert game.state.values['server_time']>=103100
        game.inputs.append((x,y));game.state.values['tutorial'].update(active=False,completed=True)
    game.observe=observe;game.tap=tap
    game.run()
    assert game.inputs==[(100,120)]


def radar_march_state():
    s=state(42);d=s.values['tutorial'];d.update(name='unlock_radar',type='TRIGGERED')
    d['config']={'StepType':'CLICK_UI','Target':'MARCH'};d['cover']={'Target':'MARCH','CoverName':'MARCH'}
    d.update(radarPopupTarget=1234500,radarEnemyOwner=-2,
        radarEnemy={'npcType':1576,'npcLevel':1,'radarNpc':{'taskid':92502,'playerid':20}},
        radarForm={'DstCharId':12345,'SelHeroIds':{'1':3},'SelectUnits':{'1':1000},'TotalNum':1000,
            'isAttackNpc':True,'Dispatched':False})
    s.values.update(tutorial_ap=1500,onboarding_marches={},supply_inventory={'ready':True,'items':{}},
        views={'MapHudPanel':True,'SendTroopsMain':True,'FTECover':True,'CommonBackground':True})
    return s


def test_radar_march_requires_owned_task_npc_and_exact_real_dispatch_receipt():
    from mirage.tutorial import RadarMarchReceipt
    s=radar_march_state();r=RadarMarchReceipt.capture(s)
    s.values['tutorial_ap']-=50
    row={'offensive':True,'state':2,'target':{'charId':1234500,'playerId':-2},
        'troop':{'playerId':20,'units':{'1':{'unitId':1,'unitCount':1000}},'heros':{'1':{'heroId':3}}}}
    s.values['onboarding_marches']={'900':row}
    assert r.matches(s)
    row['target']['charId']=1234600
    assert not r.matches(s)
    s=radar_march_state();s.values['tutorial']['radarEnemy']['radarNpc']['playerid']=21
    with pytest.raises(NotReady):RadarMarchReceipt.capture(s)
    s=radar_march_state();s.values['tutorial']['radarForm']['DstCharId']=None
    with pytest.raises(NotReady):RadarMarchReceipt.capture(s)


def test_radar_reward_requires_task_claim_status_and_exact_items():
    from mirage.tutorial import RadarClaimReceipt
    s=state(31);d=s.values['tutorial'];d.update(name='unlock_radar',type='TRIGGERED',
        radarShown={'1':92501},radarTasks={'1':{'TaskID':92501,'RewardId':49101,'TaskStatus':-1,'AddtionExp':False}},
        followPos={'1':-3.71814,'2':-1.999,'3':0})
    d['config']={'StepType':'CLICK_UI','Target':'RADAR_TASK_CLAIM'}
    d['cover']={'Target':'RADAR_TASK_CLAIM','CoverName':'GeneralUp'}
    d['radarLoot']={str(i):{'ID':49101,'Type':kind,'SubType':id,'Value':value} for i,(kind,id,value) in
        enumerate(((1,1,1000),(1,2,1000),(2,129,3),(2,10380,1)),1)}
    s.values.update(supply_inventory={'ready':True,'items':{}},views={'MapHudPanel':True,'RadarTaskMainPage':True})
    r=RadarClaimReceipt.capture(s);s.values['resources']['1']+=1000;s.values['resources']['2']+=1000
    s.values['supply_inventory']['items']={'129':3,'10380':1}
    assert not r.matches(s)
    d['radarTasks']['1']['TaskStatus']=-2
    assert r.matches(s)


def story_state(step=98):
    s=state(step);s.values['player']={'Civilization':6}
    d=s.values['tutorial'];d.update(storyVisible=True)
    d['config']={'StepType':'WAIT','Target':'STORY_CONVERSATION_END','ExtFunAtBegin':'PopStoryConversation'}
    node={'Id':1,'DialogType':1,'NextDialogId':'101'}
    d['story']={'id':'VSBBRV2_SC2_03_06','return':'Tutorial','canClick':True,'typing':False,'end':False,
        'choiceShown':False,'node':node,'graph':{'1':deepcopy(node),'101':{'Id':101,'DialogType':1},'EndId':'101'}}
    s.values['views'].update(StoryConversation=True,CanyonLevelMainPage=True,CommonBackground=True)
    return s


def test_story_accepts_observed_background_only_for_vengeance_and_rejects_wrong_branch():
    s=story_state();r=StoryReceipt.capture(s)
    s.values['tutorial']['story']['node']={'Id':101,'DialogType':1}
    assert r.matches(s)
    end=StoryReceipt.capture(s);assert end.next_nodes==()
    s.values['tutorial']['step']=99
    assert end.matches(s)
    s=story_state();s.values['tutorial']['story']['id']='VSBBRV2_SC2_03_01'
    with pytest.raises(NotReady):StoryReceipt.capture(s)
    s=story_state();s.values['views']['BuyPopup']=True
    with pytest.raises(NotReady):StoryReceipt.capture(s)
    s=story_state(93);s.values['tutorial']['story']['id']='VSBBRV2_SC2_02_06'
    with pytest.raises(NotReady):StoryReceipt.capture(s)


def test_story_merge_and_only_known_single_choice():
    s=story_state(78);d=s.values['tutorial'];s.values['views'].pop('CanyonLevelMainPage');s.values['views'].pop('CommonBackground')
    story=d['story'];story['id']='VSBBRV2_SC1_04';story['node']['NextDialogId']='2'
    choice={'Id':3,'DialogType':2,'ChoiceContent':'LC_DIALOG_VSBBRV2_SC1_11'}
    story['graph']={'1':deepcopy(story['node']),'2':{'Id':2,'DialogType':1,'NextDialogId':'3'},'3':choice,'EndId':'3'}
    r=StoryReceipt.capture(s);story['node']=deepcopy(choice)
    assert r.matches(s)
    show=StoryReceipt.capture(s);story.update(canClick=False,choiceShown=True)
    assert show.matches(s)
    assert StoryReceipt.capture(s).choice
    story['node']['ChoiceContent']='choose_unknown_purchase'
    with pytest.raises(NotReady):StoryReceipt.capture(s)


def test_guide_permission_is_bound_to_exact_step_target_modal_and_position():
    s=state(58);d=s.values['tutorial'];d['config']={'StepType':'WAIT','EndCondition':'EVENT_TUTORIAL_WAIT_CONDITION',
        'Target':'SLG_2_BARBARAIN_MISSION_GOTO_2'}
    s.values['views'].update(QuestGuide=True,BarbariansInvadePopUp=True)
    d['guide']={'forceClick':True,'needClickCb':False,'is3D':False,'worldPos':{'1':(730-480)/54,'2':(270-321)/54,'3':0}}
    assert TutorialGuide().matches(s)
    for mutate in (lambda:d.update(step=57),lambda:d['config'].update(Target='buy'),
            lambda:s.values['views'].update(PurchaseConfirm=True),lambda:d['guide']['worldPos'].update({'1':0})):
        before=deepcopy(s.values);mutate();assert not TutorialGuide().matches(s);s.values.clear();s.values.update(before);d=s.values['tutorial']


def test_build_receipt_requires_cost_and_one_new_building_and_preserves_gems():
    s=state(9);d=s.values['tutorial'];s.values['buildings']={'1':{'type':1,'lv':1}}
    s.values['city_camera']={'moving':False,'distance':150,'x':10.,'y':20.}
    d.update(selection='localNewBuilding',cityOrigin={'1':10.,'2':20.},
        preview={'id':'localNewBuilding','type':2,'lv':0,'newPosValid':True,'isSelected':True,'position':{'x':-.5,'y':.1}},
        buildCost={'Type':2,'Level':1,'Food':0,'Wood':100,'Stone':0,'Coin':0,'Gem':0,'Amber':0,'Crystal':0,'NeedBagItem':0,'ItemCnt1':0})
    r=BuildReceipt.capture(s);s.values['resources']['2']-=100
    assert not r.matches(s)
    s.values['buildings']['55']={'type':2,'lv':1};assert r.matches(s)
    s.values['resources']['5']-=1;assert not r.matches(s)
    s.values['resources']['5']+=1;s.values['buildings']['56']={'type':2,'lv':1};assert not r.matches(s)
    d['buildCost']['Gem']=1
    with pytest.raises(NotReady):BuildReceipt.capture(s)


def test_starting_key_receipt_accounts_for_hero_token_and_all_loot_without_reopening():
    s=state(88);d=s.values['tutorial'];s.values.update(server_time=10000,supply_inventory={'ready':True,'items':{'48':1,'128':2}})
    d.update(tavernVisible=True,tavern={'menu':1,'multi':False})
    r=StartingKeyReceipt.capture(s)
    d.update(step=90,heroVisible=True,hero={'id':3,'star':1,'owned':{'id':3,'star':1,'created':10001}},heroTokens={'10031':3})
    d['tavern']['items']={'1':{'Id':128,'Cnt':2},'2':{'Id':1,'Cnt':1},'3':{'Id':10031,'Cnt':1},'4':{'Id':128,'Cnt':5}}
    s.values['supply_inventory']['items']={'128':9,'1':1}
    assert r.matches(s)
    d['hero']['owned']['created']=1;assert not r.matches(s)
    d['hero']['owned']['created']=10001;s.values['supply_inventory']['items']['48']=1
    assert not r.matches(s)
    with pytest.raises(NotReady):StartingKeyReceipt.capture(s)


@pytest.mark.parametrize('value',[True,0,33,1.5,'8'])
def test_tutorial_settings_validate_before_profile_is_saved(value):
    with pytest.raises(ValueError):Profile('one',tasks={'tutorial':{'max_actions':value}}).validate()


def test_limit_is_bounded_and_resume_uses_current_step():
    game=Route()
    flow=tutorial_workflow({'max_actions':1},verified=True)
    engine=Engine(game,game.observe,clock=lambda:game.now,resolution=(960,540))
    result=engine.execute(flow,game.cancelled,instance_id='one',pid=10,player_id=20)
    assert result.values['tutorial']['step']==3 and len(game.inputs)==1
    result=engine.execute(flow,game.cancelled,instance_id='one',pid=10,player_id=20)
    assert result.values['tutorial']['step']==4 and len(game.inputs)==2


def test_chapter_claim_needs_all_objectives_and_exact_four_item_receipt():
    s=state(76);d=s.values['tutorial'];s.values['views']['BarbariansInvadePopUp']=True
    s.values['supply_inventory']={'ready':True,'items':{'48':1}}
    d.update(chapter=1,chapterQuests={str(i):{'Status':3 if i<4 else 2} for i in range(1,5)},
        chapterLoot={str(i):{'ID':23330016,'Type':2,'SubType':item,'Value':1} for i,item in enumerate((1,7,13,26),1)})
    d['config']={'Target':'SLG_2_BARBARAIN_MISSION_CLAIM','EndCondition':'EVENT_TUTORIAL_WAIT_CONDITION'}
    r=ChapterReceipt.capture(s);s.values['supply_inventory']['items'].update({'1':1,'7':1,'13':1,'26':1})
    assert not r.matches(s)
    d['chapter']=2;assert r.matches(s)
    s.values['supply_inventory']['items']['26']=2;assert not r.matches(s)
    d['chapter']=1;d['chapterQuests']['3']['Status']=1
    with pytest.raises(NotReady):ChapterReceipt.capture(s)


def test_tutorial_upgrade_confirms_resource_cost_and_real_building_state():
    s=state(26);d=s.values['tutorial'];s.values.update(buildings={'29':{'type':1,'lv':1,'state':1}},
        builder_queues={'1':{'id':1,'from':'born','buildingId':'','endTime':-1}})
    d.update(upgradeVisible=True,upgrade={'id':'29','type':1,'level':1,'can':True,'item':0,'items':0,
        'cost':{'1':{'type':1,'num':300,'finalNum':300}}})
    r=TutorialUpgradeReceipt.capture(s);s.values['resources']['1']-=300
    assert not r.matches(s)
    s.values['buildings']['29'].update(lv=2);assert r.matches(s)
    s.values['resources']['5']-=1;assert not r.matches(s)


def test_harvest_waits_for_balance_animation_and_untouched_other_currencies():
    s=state(12);d=s.values['tutorial'];d['config']={'StepType':'COLLECT','Target':'FARM',
        'EndCondition':'EVENT_TUTORIAL_COLLECT','CoverName':'CLOVER_POPUP_COLLECT'}
    d['cover']={'CoverName':'CLOVER_POPUP_COLLECT','Target':'FARM'}
    s.values.update(city_resources={'55':{'id':'55','type':2,'rssType':1,'rssValue':4013.,'gatherMin':100}},
        harvest_receipts={'1':{'type':1,'value':10000,'incrValue':0,'leftTime':0}})
    r=CollectReceipt.capture(s);s.values['resources']['1']+=4013;s.values['city_resources']['55']['rssValue']=0
    assert not r.matches(s)
    s.values['harvest_receipts']['1']['value']=14013;assert r.matches(s)
    s.values['resources']['2']+=1;assert not r.matches(s)


def test_vip_intro_claims_free_points_and_box_with_exact_inventory_receipts():
    s=state(2);d=s.values['tutorial'];s.values['views']={'VIPMainPage':True,'CommonBackground':True}
    s.values.update(supply_inventory={'ready':True,'items':{'48':1}},vip_visible=True,vip_shown_level=0,
        vip_box_detail=False,vip_opening_box=False)
    d.update(name='first_enter_vippage',type='TRIGGERED',vip={'VipLevel':0,'VipExp':0,'ContinuousLogin':1,
        'CanGetFreePoint':True,'CanGetFreeBox':True,'pointConfig':{'Day':1,'Point':40},
        'freeLoot':{'1':{'ID':9001,'Type':2,'SubType':129,'Value':1}}})
    d['config']={'StepType':'CLICK_UI','Target':'VIP_POINT'}
    r=VipIntroPointReceipt.capture(s);d['vip'].update(VipExp=40,CanGetFreePoint=False)
    assert r.matches(s)
    d['step']=5;d['config']['Target']='VIP_BOX_FREE';box=VipIntroBoxReceipt.capture(s)
    d['vip']['CanGetFreeBox']=False;assert not box.matches(s)
    s.values['supply_inventory']['items']['129']=1;assert box.matches(s)
    s.values['resources']['5']-=1;assert not box.matches(s)


def test_completed_intro_does_not_allow_an_unrelated_force_guide():
    s=state();s.values['tutorial']={'ready':True,'active':False,'completed':True}
    s.values['views'].update(QuestGuide=True);s.values['guide_force_click']=True
    assert not TutorialGuide().matches(s)
    game=Route();game.state=s
    with pytest.raises(NotReady,match='подсказки'):game.run()
    assert not game.inputs
