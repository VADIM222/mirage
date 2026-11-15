"""Bounded, memory-led onboarding transitions for the observed slg_2_v4 tutorial."""
from dataclasses import dataclass
from copy import deepcopy
import math

from .city_resources import completed_receipt
from .building_upgrade import permanent_builder
from .model import TutorialOptions
from .plants import PlantRecycleReceipt
from .supply_boxes import balances, integer, inventory, table
from .workflows import CITY_VIEWS, Cancelled, NotReady, Procedure, Workflow, WorkflowError


FIELDS={'tutorial':['@tutorial'],'city_camera':['@city_camera'],'city_resources':['@city_resources'],
    'harvest_receipts':['CityBuildData','UserRssAniData'],'builder_queues':['CityBuildData','BuildQueue'],
    'building_menu':['@building_menu'],'supply_inventory':['@item_counts'],'onboarding_battle':['@onboarding_battle'],
    'tutorial_ap':['PveData','AP'],'onboarding_marches':['@gather_troops']}
DIALOGS={2:'LC_TUTORIAL_DIALOGUE_01_ADVISOR',3:'LC_TUTORIAL_DIALOGUE_02_ADVISOR',
    4:'LC_TUTORIAL_DIALOGUE_02_ADVISOR_01',5:'LC_TUTORIAL_DIALOGUE_03_ADVISOR',
    6:'LC_TUTORIAL_DIALOGUE_04_ADVISOR',14:'LC_DIALOG_VSBBR3_SC1_01',
    22:'LC_DIALOG_VSBBR3_SC1_02',23:'LC_DIALOG_VSBBR3_SC1_03',30:'LC_DIALOG_VSBBR3_SC1_04',
    32:'LC_DIALOG_VSBBRV2_SC1_8',36:'LC_DIALOG_VSBBR_SC1_01',37:'LC_DIALOG_VSBBR_SC1_02',
    38:'LC_DIALOG_VSBBR_SC1_05',42:'LC_DIALOG_VSBBR_SC1_03',43:'LC_DIALOG_VSBBR_SC1_04',
    50:'LC_DIALOG_VSBBRV2_SC1_1',51:'LC_DIALOG_VSBBRV2_SC1_2',59:'LC_DIALOG_VSBBRV2_SC1_3',
    60:'LC_DIALOG_VSBBRV2_SC1_4',68:'LC_DIALOG_VSBBRV2_SC1_5'}
BASE_VIEWS=set(CITY_VIEWS)|{'FTECover','TutorialSkipPage','Dialog'}
VIP_DIALOGS={1:'LC_TUTORIAL_TUTOR_VIP_DAILY_SIGNIN',4:'LC_TUTORIAL_TUTOR_VIP_PURCHASE_SILVER_BOX',
    7:'LC_TUTORIAL_TUTOR_VIP_PURCHASE_GOLD_BOX'}
SPEEDUP_DIALOGS={1:'LC_TUTORIAL_SPEEDUP_01',4:'LC_TUTORIAL_SPEEDUP_02'}
BRONZE_DIALOGS={1:'LC_TUTORIAL_TUTOR_WILL_ENTER_NEW_AGE_01',2:'LC_TUTORIAL_TUTOR_WILL_ENTER_NEW_AGE_02'}
ITEMBOX_DIALOGS={1:'LC_TUTORIAL_TUTOR_ITEMS_01',2:'LC_TUTORIAL_TUTOR_ITEMS_02'}
RADAR_DIALOGS={3:'LC_TUTORIAL_UNLOCK_RADAR_01_ADVISOR',4:'LC_TUTORIAL_UNLOCK_RADAR_02_ADVISOR',
    12:'LC_TUTORIAL_UNLOCK_RADAR_07_ADVISOR',15:'LC_TUTORIAL_UNLOCK_RADAR_06_SCOUT',
    20:'LC_TUTORIAL_UNLOCK_RADAR_03_SCOUT',24:'LC_TUTORIAL_UNLOCK_RADAR_04_FARMER'}


class TutorialGuide:
    def matches(self,state):
        try:NewSignupReceipt.capture(state);return True
        except NotReady:pass
        try:guided_point(state);return True
        except NotReady:
            try:recycle_point(state);return True
            except NotReady:pass
            try:battle_point(state);return True
            except NotReady:return False


def battle_point(state):
    b=state.values.get('onboarding_battle');views=state.values.get('views',{})
    if (table(b) and b.get('config') in (8001,8002,8003) and b.get('state')==3
            and b.get('victoryConfig')==b['config'] and b.get('rewardDone') is True
            and 'CanyonLevelVictoryPage' in views
            and not set(views)-set(CITY_VIEWS)-{'MapUIScenarioElementHud','CanyonLevelVictoryPage','QuestGuide','CommonBackground'}):
        if 'QuestGuide' in views:
            g=b.get('guide');p=g.get('position') if table(g) else None
            if (not table(g) or type(g.get('force')) is not bool or g.get('callback') is not False
                    or g.get('is3D') is not False or not table(p)
                    or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for k in ('1','2','3'))
                    or abs(480+54*p['1']-574)>3 or abs(270-54*p['2']-461)>3 or abs(p['3'])>.01):
                raise NotReady('Обучение: указание результата боя не подтверждено')
        return (574,461)
    if (not table(b) or b.get('config') not in (8001,8002,8003) or b.get('state')!=10 or b.get('mode')!=1
            or 'CanyonLevelHUD' not in views or set(views)-set(CITY_VIEWS)-{'MapUIScenarioElementHud','CanyonLevelHUD','QuestGuide'}
            or not table(b.get('selected')) or b['selected']!={'3':True}):
        raise NotReady('Обучение: боевой этап ещё не подтверждён')
    g=b.get('guide');p=g.get('position') if table(g) else None
    if (not table(g) or g.get('force') is not (b['config']==8001) or g.get('callback') is not False or g.get('is3D') is not False
            or 'QuestGuide' not in views or not table(p)
            or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for k in ('1','2','3'))):
        raise NotReady('Обучение: боевое указание не подтверждено')
    point=(round(480+54*p['1']),round(270-54*p['2']))
    if abs(point[0]-568)>3 or abs(point[1]-482)>3 or abs(p['3'])>.01:
        raise NotReady('Обучение: неподтверждённая кнопка начала боя')
    return point


def guided_point(state):
    d=data(state);cfg=d.get('config',{});step=d.get('step');guide=d.get('guide');pos=guide.get('worldPos') if table(guide) else None
    targets={49:'SLG_2_BARBARAIN_MISSION_GOTO_1',58:'SLG_2_BARBARAIN_MISSION_GOTO_2',95:'UNLOCKLV_3_RIFTSCENARIO'}
    expected={49:(730,250),58:(730,321),95:(847,504)}
    new_event=d.get('name')=='slg_2_new_event' and step==2
    if new_event:targets={2:'SLG_2_EVENT'};expected={2:(917,67)}
    required='MapHudPanel' if step==95 else 'BarbariansInvadePopUp'
    if new_event:required='MapHudPanel'
    optional={'NewFeaturesUnlockedPage'} if step==95 else set()
    if (step not in targets or cfg.get('StepType')!=('CLICK_UI' if step==95 or new_event else 'WAIT')
            or cfg.get('EndCondition')!=('EVENT_TUTORIAL_CLICK_UI' if step==95 or new_event else 'EVENT_TUTORIAL_WAIT_CONDITION')
            or cfg.get('Target')!=targets[step] or required not in state.values.get('views',{})
            or set(state.values['views'])-BASE_VIEWS-{'QuestGuide',required}-optional
            or not table(guide) or guide.get('forceClick') is not True or guide.get('needClickCb') is not False
            or guide.get('is3D') is not False or not table(pos)
            or any(type(pos.get(k)) not in (int,float) or not math.isfinite(pos[k]) for k in ('1','2','3'))
            or abs(pos['3'])>.01):raise NotReady('Обучение: цель обязательной подсказки не подтверждена')
    point=(round(480+54*pos['1']),round(270-54*pos['2']))
    if any(abs(a-b)>3 for a,b in zip(point,expected[step])):raise NotReady('Обучение: подсказка указывает в неизвестную область')
    return point


def data(state):
    d=state.values.get('tutorial')
    if not table(d) or d.get('ready') is not True:raise NotReady('Обучение: данные шага не подтверждены')
    if d.get('active') is False:return d
    supported=(d.get('name')=='slg_2_v4' and d.get('type')=='FTE' and integer(d.get('step'),1) and d['step']<=100
        or d.get('name')=='first_enter_vippage' and d.get('type')=='TRIGGERED' and integer(d.get('step'),1) and d['step']<=12
        or d.get('name')=='trigger_towncenter_2_3' and d.get('type')=='TRIGGERED' and integer(d.get('step'),1) and d['step']<=5)
    supported=supported or (d.get('name')=='slg_2_towncenter_3' and d.get('type')=='TRIGGERED'
        and integer(d.get('step'),1) and d['step']<=24)
    supported=supported or (d.get('name')=='slg_2_towncenter_enter_bronze' and d.get('type')=='TRIGGERED'
        and integer(d.get('step'),1) and d['step']<=16)
    supported=supported or (d.get('name')=='first_enter_itembox' and d.get('type')=='TRIGGERED'
        and integer(d.get('step'),1) and d['step']<=3)
    supported=supported or (d.get('name')=='slg_2_towncenter_5_1' and d.get('type')=='TRIGGERED'
        and integer(d.get('step'),1) and d['step']<=15)
    supported=supported or (d.get('name')=='slg_2_new_event' and d.get('type')=='TRIGGERED'
        and integer(d.get('step'),1) and d['step']<=5)
    supported=supported or (d.get('name')=='unlock_radar' and d.get('type')=='TRIGGERED'
        and integer(d.get('step'),1) and d['step']<=43)
    supported=supported or (d.get('name')=='first_select_campus' and d.get('type')=='TRIGGERED'
        and integer(d.get('step'),1) and d['step']<=4)
    supported=supported or (d.get('name')=='slg_2_recycle_plants' and d.get('type')=='TRIGGERED'
        and integer(d.get('step'),1) and d['step']<=4)
    if d.get('active') is not True or not supported or not table(d.get('config')):
        raise NotReady('Обучение: неподтверждённый вариант или номер шага')
    return d


def dialog_point(state):
    d=data(state);step=d.get('step');cfg=d.get('config',{});row=d.get('dialog')
    dialogs=VIP_DIALOGS if d.get('name')=='first_enter_vippage' else DIALOGS
    if d.get('name')=='trigger_towncenter_2_3':dialogs=SPEEDUP_DIALOGS
    if d.get('name')=='slg_2_towncenter_enter_bronze':dialogs=BRONZE_DIALOGS
    if d.get('name')=='first_enter_itembox':dialogs=ITEMBOX_DIALOGS
    if d.get('name')=='unlock_radar':dialogs=RADAR_DIALOGS
    if d.get('name')=='first_select_campus':dialogs={2:'LC_TUTORIAL_TUTOR_ACADEMY_01'}
    if d.get('name')=='slg_2_recycle_plants':dialogs={1:'LC_TUTORIAL_SLGV2_CITY_SPACE_FULL_DIALOG'}
    allowed=BASE_VIEWS|({'VIPMainPage','CommonBackground'} if d.get('name')=='first_enter_vippage' else set())
    npc,side=('VILLAGE','RIGHT') if step in (36,37,38) else ('BARBARIAN','RIGHT') if step in (42,43) else ('BRAINMAN','LEFT')
    if d.get('name')=='trigger_towncenter_2_3':npc,side='BRAINMAN','RIGHT'
    if d.get('name')=='slg_2_towncenter_enter_bronze':
        npc,side='BRAINMAN','RIGHT';allowed|={'UpgradeBuilding','CommonBackground'}
    if d.get('name')=='first_enter_itembox':
        npc,side='BRAINMAN','RIGHT';allowed|={'ItemBag','CommonBackground'}
    if d.get('name')=='unlock_radar':
        npc,side=('SCOUT','RIGHT') if step in (15,20) else ('VILLAGE','RIGHT') if step==24 else ('BRAINMAN','LEFT')
        if step==15:allowed|={'RadarTaskMainPage','CommonBackground'}
    if d.get('name')=='first_select_campus':npc,side='BRAINMAN','RIGHT'
    if d.get('name')=='slg_2_recycle_plants':npc,side='BRAINMAN','RIGHT'
    if (step not in dialogs or cfg.get('StepType')!='DIALOG'
            or cfg.get('EndCondition')!='EVENT_TUTORIAL_CLICK_DIALOG'
            or cfg.get('TextKey')!=dialogs[step] or cfg.get('NPC')!=npc or cfg.get('NPCSide')!=side
            or cfg.get('Target')!='' or cfg.get('Ext')!='' or d.get('dialogVisible') is not True
            or not table(row) or row.get('TextID')!=cfg['TextKey'] or row.get('NPC')!=cfg['NPC']
            or row.get('NPCSide')!=cfg['NPCSide'] or row.get('BuildingTarget')!=''
            or set(state.values.get('views',{}))-allowed):
        raise NotReady('Обучение: этот диалог или его геометрия ещё не проверены')
    return (790,490)


def click_point(state):
    d=data(state);cfg=d['config'];step=d['step'];cover=d.get('cover')
    if d.get('name')!='slg_2_v4':raise NotReady('Обучение: действие дополнительной цепочки ещё не проверено')
    rules={7:('BUILDING','BUILDING',(44,405)),15:('BUILDING','BUILDING',(44,405)),8:('FIRST_BUILDING','FARM',(200,330)),
        9:('CLOVER_POPUP_CONFIRM','CLOVER_POPUP_CONFIRM',(450,190)),
        16:('FIRST_BUILDING','SAWMILL',(200,330)),17:('CLOVER_POPUP_CONFIRM','CLOVER_POPUP_CONFIRM',(628,210)),
        25:('CLOVER_POPUP_UPGRADE','CLOVER_POPUP_UPGRADE',(337,300)),26:('UPGRADE','UPGRADE',(740,410)),
        47:('GeneralRight','SLG_2_BARBARAIN_MISSION',(100,120)),
        53:('CLOVER_POPUP_FUN_2BTN','CLOVER_POPUP_UPGRADE',(539,355)),54:('UPGRADE','UPGRADE',(740,410)),
        56:('GeneralRight','SLG_2_BARBARAIN_MISSION',(100,120)),61:('BUILDING','BUILDING',(44,405)),
        62:('FIRST_BUILDING','QUARRY',(200,330)),63:('CLOVER_POPUP_CONFIRM','CLOVER_POPUP_CONFIRM',(375,245)),
        70:('CLOVER_POPUP_UPGRADE','CLOVER_POPUP_UPGRADE',(500,370)),71:('UPGRADE','UPGRADE',(740,410)),
        74:('GeneralRight','SLG_2_BARBARAIN_MISSION',(100,120)),
        83:('GeneralUp','SLG_2_MISSION',(78,181)),84:('FIRST_BUILDING','TAVERN',(200,330)),
        85:('CLOVER_POPUP_CONFIRM','CLOVER_POPUP_CONFIRM',(540,110)),
        87:('CLOVER_POPUP_FUN_3BTN','TAVERN_FUN',(581,325)),88:('TAVERN_GOLD','TAVERN_GOLD',(685,450)),
        90:('GeneralUp','HERO_WELCOME',(714,405)),91:('BOX_CONFIRM','BOX_CONFIRM',(377,480)),
        92:('TOP_LEFT_CLOSE','CLOSE',(30,29)),99:('GeneralUp','RIFTSCENARIO_START',(480,472))}
    if step not in rules:raise NotReady('Обучение: действие шага ещё не проверено')
    name,target,point=rules[step]
    allowed=BASE_VIEWS|({'BuildNewBuilding','CommonBackground'} if step in (8,16,62,84) else set())
    if step in (26,54,71):allowed|={'UpgradeBuilding','CommonBackground'}
    if step==88:allowed|={'TavernPage'}
    if step in (91,92):allowed|={'TavernPage'}
    if step==90:allowed|={'TavernPage','AllUIHeroCheckIn_SLG'}
    if step==99:allowed|={'CanyonLevelMainPage','CommonBackground'}
    if (cfg.get('StepType')!='CLICK_UI' or cfg.get('EndCondition')!='EVENT_TUTORIAL_CLICK_UI'
            or cfg.get('CoverName')!=name or cfg.get('Target')!=target
            or d.get('coverVisible') is not True or not table(cover)
            or cover.get('CoverName')!=name or cover.get('Target')!=target
            or set(state.values.get('views',{}))-allowed):
        raise NotReady('Обучение: активная подсказка не соответствует действию')
    if step in (8,16,62,84) and 'BuildNewBuilding' not in state.values['views']:raise NotReady('Обучение: меню строительства не открыто')
    if step in (83,90,99):
        pos=d.get('followPos')
        if not table(pos) or any(type(pos.get(k)) not in (int,float) or not math.isfinite(pos[k]) for k in ('1','2')):
            raise NotReady('Обучение: положение текущего задания не прочитано')
        actual=(round(480+54*pos['1']),round(270-54*pos['2']))
        if any(abs(a-b)>4 for a,b in zip(actual,point)):raise NotReady('Обучение: задание переместилось')
        point=actual
    if step==90:
        hero=d.get('hero')
        if d.get('heroVisible') is not True or not table(hero) or not integer(hero.get('id'),1) or hero.get('star')!=1:
            raise NotReady('Обучение: полученный командир не подтверждён')
    if step in (91,92):
        t=d.get('tavern')
        if (d.get('tavernVisible') is not True or not table(t) or t.get('multi') is not False
                or t.get('menu')!=(3 if step==91 else 1) or step==91 and t.get('mode')!=2):
            raise NotReady('Обучение: результат одиночной таверны не подтверждён')
    if step in (25,53,70,87):
        menu=state.values.get('building_menu',{}).get('selected')
        if not table(menu) or menu.get('type')!=({25:1,53:15,70:6,87:18}[step]) or menu.get('level')!=1 or 'btn_CityPopUpUpgrade' not in menu.get('buttons',[]):
            raise NotReady('Обучение: ратуша не выбрана')
    return point


def radar_point(state):
    d=data(state);cfg=d['config'];cover=d.get('cover')
    if (d.get('name')=='unlock_radar' and d['step']==22 and cfg.get('StepType')=='CLICK_UI'
            and cfg.get('Target')=='RESCUE' and table(cover) and cover.get('Target')=='RESCUE'
            and cover.get('CoverName')=='BARBARIAN_ATTACK_POP' and d.get('radarVillageTarget')==-9999900
            and d.get('radarVillageCave')==99999 and d.get('radar',{}).get('RadarVillageID')==-9999900
            and 'MapUnkownCityPopUp' in state.values.get('views',{})
            and set(state.values['views'])<=BASE_VIEWS|{'MapUnkownCityPopUp'}):return (681,366)
    if (d.get('name')=='unlock_radar' and d['step']==41 and cfg.get('StepType')=='CLICK_UI'
            and cfg.get('Target')=='BUILD_TROOP' and table(cover) and cover.get('Target')=='BUILD_TROOP'
            and d.get('radarSelectTarget')==d.get('radarPopupTarget') and integer(d.get('radarPopupTarget'),1)
            and 'MapUISelectTroops' in state.values.get('views',{})
            and set(state.values['views'])<=BASE_VIEWS|{'MapUISelectTroops','TroopSelectedPopUp'}):return (760,110)
    if d.get('name')=='unlock_radar' and d['step']==42:
        RadarMarchReceipt.capture(state);return (685,475)
    if d.get('name')=='unlock_radar' and d['step']==40:
        enemy=d.get('radarEnemy');npc=enemy.get('radarNpc') if table(enemy) else None
        if (cfg.get('StepType')=='CLICK_UI' and cfg.get('Target')=='ATTACK' and table(cover)
                and cover.get('Target')=='ATTACK' and cover.get('CoverName')=='BARBARIAN_ATTACK_POP'
                and integer(d.get('radarPopupTarget'),1) and d.get('radarEnemyOwner')==-2
                and table(enemy) and enemy.get('npcType')==1576 and enemy.get('npcLevel')==1
                and table(npc) and npc.get('taskid')==92502 and npc.get('playerid')==state.player_id
                and 'MapUIBarbarianPopUp' in state.values.get('views',{})
                and set(state.values['views'])<=BASE_VIEWS|{'MapUIBarbarianPopUp'}):return (685,360)
    if (d.get('name')=='unlock_radar' and d['step']==32 and cfg.get('Target')=='RADAR_TASK_CLOSE_REWARD'
            and d.get('radarRewardTask')==92501 and 'RadarTaskMainPageReward' in state.values.get('views',{})
            and set(state.values['views'])<=BASE_VIEWS|{'RadarTaskMainPage','RadarTaskMainPageReward','CommonBackground'}):return (480,500)
    if d.get('name')=='unlock_radar' and d['step']==21:
        r=d.get('radar');v=r.get('RadarVillage') if table(r) else None;c=state.values.get('city_camera')
        if (cfg.get('StepType')=='CLICK_3D' and cfg.get('Target')=='RadarVillageID'
                and cfg.get('ExtFunAtEnd')=='SelectWorldObj' and table(cover) and cover.get('Target')=='RadarVillageID'
                and cover.get('CoverName')=='BLOCK_UI_ONLY_WITH_ARROW2' and table(v) and v.get('charId')==-9999900
                and r.get('RadarVillageID')==v['charId'] and table(c) and c.get('moving') is False
                and all(type(v.get(k)) in (int,float) and math.isfinite(v[k]) and abs(c.get(k,float('inf'))-v[k])<.02 for k in ('x','y'))
                and abs(c.get('distance',float('inf'))-150)<.1 and set(state.values.get('views',{}))<=BASE_VIEWS):return (480,270)
    follows={16:('RADAR_TASK_FARM',(279,378)),17:('RADAR_TASK_FARM_GOTO',(467,475)),31:('RADAR_TASK_CLAIM',(279,378)),
        26:('RADAR_TASK_ENTRY',(32,377)),37:('RADAR_TASK_FIGHT',(272,252)),38:('RADAR_TASK_FIGHT_GOTO',(459,349))}
    if d.get('name')=='unlock_radar' and d['step'] in follows:
        pos=d.get('followPos');target,expected=follows[d['step']]
        if (cfg.get('StepType')=='CLICK_UI' and cfg.get('Target')==target
                and table(cover) and cover.get('Target')==cfg['Target'] and cover.get('CoverName')==('GeneralRight' if d['step']==26 else 'GeneralUp')
                and table(pos) and all(type(pos.get(k)) in (int,float) and math.isfinite(pos[k]) for k in ('1','2','3'))
                and abs(pos['3'])<.01 and (d['step']==26 or 'RadarTaskMainPage' in state.values.get('views',{}))
                and set(state.values['views'])<=BASE_VIEWS|{'RadarTaskMainPage','RadarTaskItemDetailPopup','CommonBackground'}):
            point=(round(480+54*pos['1']),round(270-54*pos['2']))
            if all(abs(a-b)<4 for a,b in zip(point,expected)):return point
    if d.get('name')=='unlock_radar' and d['step']==13:
        pos=d.get('followPos');selected=state.values.get('building_menu',{}).get('selected')
        if (cfg.get('StepType')=='CLICK_UI' and cfg.get('Target')=='SCOUTS_CAMP_FUN2'
                and table(cover) and cover.get('Target')=='SCOUTS_CAMP_FUN2' and cover.get('CoverName')=='GeneralUp'
                and table(pos) and all(type(pos.get(k)) in (int,float) and math.isfinite(pos[k]) for k in ('1','2','3'))
                and abs(pos['3'])<.01 and table(selected) and selected.get('type')==28 and selected.get('level')==1
                and 'btn_CityPopUpRadar' in selected.get('buttons',[]) and set(state.values.get('views',{}))<=BASE_VIEWS):
            point=(round(480+54*pos['1']),round(270-54*pos['2']))
            if abs(point[0]-618)<4 and abs(point[1]-310)<4:return point
    rules={5:('BUILDING','BUILDING',(44,405)),6:('BUILDING_BAR','BUILDING_BAR_POS_2',(40,389)),
        7:('SCOUTS_CAMP','FIRST_BUILDING',(200,330)),8:('CLOVER_POPUP_CONFIRM','CLOVER_POPUP_CONFIRM',(540,95))}
    if d.get('name')=='unlock_radar' and d['step'] in rules:
        target,name,point=rules[d['step']];allowed=BASE_VIEWS|({'BuildNewBuilding','CommonBackground'} if d['step'] in (6,7) else set())
        if (cfg.get('StepType')=='CLICK_UI' and cfg.get('Target')==target and cfg.get('CoverName')==name
                and table(cover) and cover.get('Target')==target and cover.get('CoverName')==name
                and set(state.values.get('views',{}))<=allowed):return point
    raise NotReady('Обучение радара: действие ещё не подтверждено')


@dataclass(frozen=True)
class VipIntroPointReceipt:
    money: dict
    items: dict
    experience: int

    @classmethod
    def capture(cls,state):
        d=data(state);v=d.get('vip')
        if (d.get('name')!='first_enter_vippage' or d['step']!=2 or d['config'].get('Target')!='VIP_POINT'
                or d['config'].get('StepType')!='CLICK_UI' or 'VIPMainPage' not in state.values.get('views',{})
                or set(state.values['views'])-BASE_VIEWS-{'VIPMainPage','CommonBackground'}
                or not table(v) or v.get('CanGetFreePoint') is not True or v.get('VipLevel')!=0
                or v.get('VipExp')!=0 or v.get('ContinuousLogin')!=1
                or v.get('pointConfig')!={'Day':1,'Point':40}):
            raise NotReady('Обучение VIP: ежедневные40 очков не подтверждены')
        return cls(balances(state),inventory(state),40)

    def matches(self,state):
        d=data(state);v=d.get('vip')
        return (table(v) and v.get('CanGetFreePoint') is False and v.get('VipExp')==self.experience
            and balances(state)==self.money and inventory(state)==self.items)


@dataclass(frozen=True)
class VipIntroBoxReceipt:
    items: dict
    money: dict

    @classmethod
    def capture(cls,state):
        d=data(state);v=d.get('vip');cfg=d['config']
        if (d.get('name')!='first_enter_vippage' or d['step']!=5 or cfg.get('Target')!='VIP_BOX_FREE'
                or cfg.get('StepType')!='CLICK_UI' or state.values.get('vip_visible') is not True
                or state.values.get('vip_shown_level')!=0 or state.values.get('vip_box_detail') is not False
                or state.values.get('vip_opening_box') is not False or not table(v) or v.get('VipLevel')!=0
                or v.get('CanGetFreeBox') is not True or set(state.values.get('views',{}))-BASE_VIEWS-{'VIPMainPage','CommonBackground'}
                or not table(v.get('freeLoot')) or not v['freeLoot']):
            raise NotReady('Обучение VIP: бесплатный сундук не подтверждён')
        items=inventory(state)
        for row in v['freeLoot'].values():
            if (not table(row) or row.get('ID')!=9001 or row.get('Type')!=2 or not integer(row.get('SubType'),1)
                    or not integer(row.get('Value'),1)):raise NotReady('Обучение VIP: состав бесплатного сундука не подтверждён')
            key=str(row['SubType']);items[key]=items.get(key,0)+row['Value']
        return cls(items,balances(state))

    def matches(self,state):
        d=data(state);v=d.get('vip')
        return (table(v) and v.get('CanGetFreeBox') is False and inventory(state)==self.items and balances(state)==self.money)


def vip_intro_close_point(state):
    d=data(state);step=d['step'];cfg=d['config']
    visible='vip_notice_visible' if step==3 else 'reward_popup_visible'
    modal='VIPNotice' if step==3 else 'RoutineRewardsCollect'
    target='VIP_POINT_NOTICE' if step==3 else 'VIP_BOX_FREE_REWARD'
    if (d.get('name')!='first_enter_vippage' or step not in (3,6) or cfg.get('Target')!=target
            or state.values.get(visible) is not True or state.values.get('vip_visible') is not True
            or set(state.values.get('views',{}))-BASE_VIEWS-{'VIPMainPage','CommonBackground',modal}):
        raise NotReady('Обучение VIP: подтверждение бесплатной награды не готово')
    return (480,500)


def vip_intro_special_point(state):
    d=data(state);cfg=d['config']
    if (d.get('name')!='first_enter_vippage' or d['step']!=8 or cfg.get('Target')!='VIP_BOX_GEM'
            or cfg.get('StepType')!='CLICK_UI' or state.values.get('vip_visible') is not True
            or state.values.get('vip_shown_level')!=0 or state.values.get('vip_box_detail') is not False
            or state.values.get('vip_opening_box') is not False
            or set(state.values.get('views',{}))-BASE_VIEWS-{'VIPMainPage','CommonBackground'}):
        raise NotReady('Обучение VIP: ознакомительная подсказка сундука не подтверждена')
    return (590,370)


def select_point(state):
    d=data(state);cfg=d['config'];cover=d.get('cover')
    targets={24:('TOWNCENTER',1,(345,185)),52:('STORAGE',15,(480,240)),69:('WALL',6,(500,240))}
    target,kind,point=targets.get(d['step'],(None,None,None))
    if (target is None or cfg.get('StepType')!='SELECT_BUILDING' or cfg.get('Target')!=target
            or cfg.get('EndCondition')!='EVENT_TUTORIAL_SELECT_BUILDING' or not table(cover)
            or cover.get('Target')!=target or cover.get('CoverName')!='BLOCK_UI_ONLY_WITH_ARROW'
            or set(state.values.get('views',{}))-BASE_VIEWS):
        raise NotReady('Обучение: выбор здания ещё не проверен')
    buildings=state.values.get('buildings')
    if not table(buildings) or sum(table(r) and r.get('type')==kind and r.get('lv')==1 for r in buildings.values())!=1:
        raise NotReady('Обучение: целевое здание не подтверждено')
    return point


def recycle_point(state):
    d=data(state);cfg=d.get('config');cover=d.get('cover');plant=d.get('plant')
    step=d.get('step');target='PLANT' if step==2 else 'PLANT_RECYCLE_FUN'
    cover_name='BLOCK_UI_ONLY_WITH_ARROW2' if step==2 else 'CLOVER_POPUP_FUN_2BTN'
    if (d.get('name')!='slg_2_recycle_plants' or step not in (2,3) or not table(cfg)
            or cfg.get('StepType')!=('SELECT_BUILDING' if step==2 else 'CLICK_UI')
            or cfg.get('Target')!=target or step==2 and cfg.get('ExtFunAtEnd')!='SelectPlant'
            or cfg.get('EndCondition')!=('EVENT_TUTORIAL_CLICK_COVER' if step==2 else 'EVENT_TUTORIAL_CLICK_UI')
            or not table(cover) or cover.get('Target')!=target or cover.get('CoverName')!=cover_name
            or d.get('coverVisible') is not True or d.get('dialogVisible') is True and d.get('dialogClosing') is not True
            or set(state.values.get('views',{}))-BASE_VIEWS or not table(plant)
            or plant.get('type')!=57 or plant.get('lv')!=1 or plant.get('state')!=1
            or plant.get('width')!=3 or plant.get('length')!=3):
        raise NotReady('Обучение: рекомендованное растение не подтверждено')
    row=state.values.get('buildings',{}).get(str(plant.get('id')))
    if not table(row) or any(row.get(k)!=plant.get(k) for k in ('id','type','lv','state','width','length')):
        raise NotReady('Обучение: растение отсутствует в текущем городе')
    if row.get('logicPosition')=={'x':-99,'y':-99}:raise NotReady('Обучение: растение уже убрано')
    if step==3:
        selected=state.values.get('building_menu',{}).get('selected')
        if (not table(selected) or selected.get('id')!=plant['id'] or selected.get('type')!=57
                or set(selected.get('buttons',[]))!={'btn_CityPopUpInfo','btn_CityPopUpRecycle'}
                or d.get('selection')!=plant['id']):raise NotReady('Обучение: меню уборки растения не подтверждено')
    return (480,270) if step==2 else (540,370)


@dataclass(frozen=True)
class TutorialUpgradeReceipt:
    money: dict
    building: str
    kind: int
    level: int

    @classmethod
    def capture(cls,state):
        d=data(state);u=d.get('upgrade');kind={26:1,54:15,71:6}.get(d['step'])
        if (kind is None or d.get('upgradeVisible') is not True or not table(u) or u.get('type')!=kind
                or u.get('level')!=1 or u.get('can') is not True or u.get('item')!=0 or u.get('items')!=0
                or permanent_builder(state) is None):raise NotReady('Обучение: обычное улучшение не разрешено')
        buildings=state.values.get('buildings');row=buildings.get(u.get('id')) if table(buildings) else None
        if not table(row) or row.get('type')!=kind or row.get('lv')!=1 or row.get('state')!=1:
            raise NotReady('Обучение: исходное здание не подтверждено')
        costs=u.get('cost');money=balances(state);seen=set()
        if not table(costs) or not costs:raise NotReady('Обучение: цена улучшения не прочитана')
        for cost in costs.values():
            if (not table(cost) or type(cost.get('type')) is not int or cost['type'] not in (1,2,3,4)
                    or cost['type'] in seen or not integer(cost.get('finalNum'),1) or not integer(cost.get('num'),1)
                    or cost['finalNum']>cost['num']):raise NotReady('Обучение: неизвестная стоимость улучшения')
            key=str(cost['type']);seen.add(cost['type']);money[key]-=cost['finalNum']
            if money[key]<0:raise NotReady('Обучение: недостаточно ресурсов улучшения')
        return cls(money,u['id'],kind,u['level'])

    def matches(self,state):
        row=state.values.get('buildings',{}).get(self.building)
        return (balances(state)==self.money and table(row) and row.get('type')==self.kind
            and (row.get('lv')==self.level+1 and row.get('state')==1
                or row.get('lv')==self.level and row.get('state')==2 and row.get('endTime',0)>state.values.get('server_time',0)))


@dataclass(frozen=True)
class BuildReceipt:
    money: dict
    kind: int
    previous: frozenset

    @classmethod
    def capture(cls,state):
        d=data(state);p=d.get('preview');cost=d.get('buildCost');camera=state.values.get('city_camera');origin=d.get('cityOrigin')
        if d['step']==85:raise NotReady('Обучение: автоматическая награда при постройке таверны требует отдельной квитанции')
        kind={9:2,17:3,63:4}.get(d['step']);position={2:(-.5,.1),3:(0.,-.6),4:(-1.,.1)}.get(kind)
        offset=(.07071,-1.06066) if kind==18 else (0.,0.)
        if (kind is None or not table(p) or p.get('id')!='localNewBuilding' or p.get('type')!=kind or p.get('lv')!=0
                or p.get('newPosValid') is not True or p.get('isSelected') is not True
                or d.get('selection')!='localNewBuilding' or not table(cost) or cost.get('Type')!=kind or cost.get('Level')!=1
                or not table(camera) or camera.get('moving') is not False or camera.get('distance')!=150
                or not table(origin) or any(type(origin.get(k)) not in (int,float) or not math.isfinite(origin[k]) for k in ('1','2'))
                or not table(p.get('position')) or any(type(p['position'].get(k)) not in (int,float)
                    or not math.isfinite(p['position'][k]) or abs(p['position'][k]-v)>.01 for k,v in zip(('x','y'),position))
                or any(type(camera.get(k)) not in (int,float) or not math.isfinite(camera[k]) for k in ('x','y','distance'))
                or abs(camera.get('x',0)-origin['1']-offset[0])>.01 or abs(camera.get('y',0)-origin['2']-offset[1])>.01):
            raise NotReady('Обучение: ферма, место, камера или стоимость не подтверждены')
        money=balances(state)
        for key,name in (('1','Food'),('2','Wood'),('3','Stone'),('4','Coin')):
            if not integer(cost.get(name)) or money[key]<cost[name]:raise NotReady('Обучение: недостаточно ресурсов строительства')
            money[key]-=cost[name]
        if any(cost.get(k)!=0 for k in ('Gem','Amber','Crystal','NeedBagItem','ItemCnt1')):
            raise NotReady('Обучение: строительство требует неподтверждённые предметы или валюты')
        buildings=state.values.get('buildings')
        if not table(buildings):raise NotReady('Обучение: список построек неполон')
        return cls(money,kind,frozenset(buildings))

    def matches(self,state):
        if balances(state)!=self.money:return False
        buildings=state.values.get('buildings')
        return table(buildings) and sum(k not in self.previous and k!='localNewBuilding'
            and table(r) and r.get('type')==self.kind and r.get('lv')==1 for k,r in buildings.items())==1


@dataclass(frozen=True)
class RadarBuildReceipt:
    build: BuildReceipt
    items: dict

    @classmethod
    def capture(cls,state):
        d=data(state);p=d.get('preview');cfg=d.get('buildCost');c=state.values.get('city_camera');o=d.get('cityOrigin')
        radar_point(state)
        if (d['step']!=8 or not table(p) or p.get('id')!='localNewBuilding' or p.get('type')!=28
                or p.get('lv')!=0 or p.get('newPosValid') is not True or p.get('isSelected') is not True
                or p.get('position')!={'x':-1.05,'y':-.45} or d.get('selection')!='localNewBuilding'
                or not table(cfg) or cfg.get('ID')!=2801 or cfg.get('Food')!=300 or cfg.get('Wood')!=300
                or any(cfg.get(k)!=0 for k in ('Stone','Coin','Gem','Amber','Crystal','NeedBagItem','ItemCnt1'))
                or not table(c) or c.get('moving') is not False or not table(o)
                or any(not isinstance(c.get(k),(int,float)) or not math.isfinite(c[k]) for k in ('x','y','distance'))
                or abs(c['distance']-150)>.1 or abs(c['x']-o.get('1',float('inf'))+.42334)>.02
                or abs(c['y']-o.get('2',float('inf'))+1.41406)>.02 or permanent_builder(state) is None):
            raise NotReady('Обучение: место и обычная постройка разведчиков не подтверждены')
        buildings=state.values.get('buildings')
        if not table(buildings) or any(table(r) and r.get('type')==28 and key!='localNewBuilding' for key,r in buildings.items()):
            raise NotReady('Обучение: разведчики уже построены')
        money=balances(state)
        for k in ('1','2'):
            if money[k]<300:raise NotReady('Обучение: недостаточно ресурсов разведчиков')
            money[k]-=300
        return cls(BuildReceipt(money,28,frozenset(buildings)),inventory(state))

    def matches(self,state):return self.build.matches(state) and inventory(state)==self.items


@dataclass(frozen=True)
class RadarClaimReceipt:
    money: dict
    items: dict

    @classmethod
    def capture(cls,state):
        d=data(state);radar_point(state);tasks=d.get('radarTasks');loot=d.get('radarLoot')
        if (d['step']!=31 or not table(tasks) or d.get('radarShown',{}).get('1')!=92501
                or sum(table(r) and r.get('TaskID')==92501 and r.get('RewardId')==49101
                    and r.get('TaskStatus')==-1 and r.get('AddtionExp') is False for r in tasks.values())!=1
                or not table(loot) or len(loot)!=4):raise NotReady('Обучение: награда разведки не готова')
        expected={(1,1):1000,(1,2):1000,(2,129):3,(2,10380):1};actual={}
        for row in loot.values():
            if not table(row) or row.get('ID')!=49101:raise NotReady('Обучение: неизвестная награда разведки')
            key=(row.get('Type'),row.get('SubType'))
            if key in actual:raise NotReady('Обучение: повтор награды разведки')
            actual[key]=row.get('Value')
        if actual!=expected:raise NotReady('Обучение: состав награды разведки изменился')
        money=balances(state);items=inventory(state)
        for (kind,id),value in expected.items():
            target=money if kind==1 else items;target[str(id)]=target.get(str(id),0)+value
        return cls(money,items)

    def matches(self,state):
        tasks=data(state).get('radarTasks')
        return (table(tasks) and sum(table(r) and r.get('TaskID')==92501 and r.get('TaskStatus')==-2 for r in tasks.values())==1
            and balances(state)==self.money and inventory(state)==self.items)


@dataclass(frozen=True)
class RadarMarchReceipt:
    target: int
    old: frozenset
    ap: int
    money: dict
    items: dict

    @classmethod
    def capture(cls,state):
        d=data(state);f=d.get('radarForm');enemy=d.get('radarEnemy');cfg=d['config'];cover=d.get('cover')
        target=d.get('radarPopupTarget');marches=state.values.get('onboarding_marches');ap=state.values.get('tutorial_ap')
        if (d.get('name')!='unlock_radar' or d['step']!=42 or cfg.get('Target')!='MARCH' or not table(cover)
                or cover.get('Target')!='MARCH' or cover.get('CoverName')!='MARCH' or not integer(target,1)
                or not table(enemy) or enemy.get('npcType')!=1576 or enemy.get('npcLevel')!=1
                or enemy.get('radarNpc',{}).get('taskid')!=92502 or enemy['radarNpc'].get('playerid')!=state.player_id
                or d.get('radarEnemyOwner')!=-2 or not table(f) or not integer(f.get('DstCharId'),1) or f['DstCharId']*100!=target
                or f.get('SelHeroIds')!={'1':3} or f.get('SelectUnits')!={'1':1000} or f.get('TotalNum')!=1000
                or f.get('isAttackNpc') is not True or f.get('Dispatched') is not False
                or not table(marches) or marches or not integer(ap,50)
                or 'SendTroopsMain' not in state.values.get('views',{})
                or set(state.values['views'])-BASE_VIEWS-{'SendTroopsMain','CommonBackground'}):
            raise NotReady('Обучение: первый боевой марш радара не подтверждён')
        return cls(target,frozenset(marches),ap,balances(state),inventory(state))

    def matches(self,state):
        marches=state.values.get('onboarding_marches')
        if (not table(marches) or len(set(marches)-self.old)!=1 or state.values.get('tutorial_ap')!=self.ap-50
                or balances(state)!=self.money or inventory(state)!=self.items):return False
        row=marches[next(iter(set(marches)-self.old))];troop=row.get('troop') if table(row) else None
        return (table(row) and row.get('offensive') is True and row.get('state')==2
            and row.get('target',{}).get('charId')==self.target and row['target'].get('playerId')==-2
            and table(troop) and troop.get('playerId')==state.player_id
            and {str(k):v.get('unitCount') for k,v in troop.get('units',{}).items() if table(v)}=={'1':1000}
            and {str(k):v.get('heroId') for k,v in troop.get('heros',{}).items() if table(v)}=={'1':3})


@dataclass(frozen=True)
class CollectReceipt:
    money: dict
    building: str
    amount: int
    minimum: int
    kind: int

    @classmethod
    def capture(cls,state):
        d=data(state);cfg=d['config'];cover=d.get('cover');rows=state.values.get('city_resources')
        kind={12:1,20:2,66:3}.get(d['step']);target={1:'FARM',2:'SAWMILL',3:'QUARRY'}.get(kind)
        if (kind is None or cfg.get('StepType')!='COLLECT' or cfg.get('Target')!=target
                or cfg.get('EndCondition')!='EVENT_TUTORIAL_COLLECT' or cfg.get('CoverName')!='CLOVER_POPUP_COLLECT'
                or not table(cover) or cover.get('CoverName')!='CLOVER_POPUP_COLLECT' or cover.get('Target')!=target
                or set(state.values.get('views',{}))-BASE_VIEWS or not table(rows)):
            raise NotReady('Обучение: сбор первой фермы не подтверждён')
        farms=[r for r in rows.values() if table(r) and r.get('type')==kind+1 and r.get('rssType')==kind]
        if len(farms)!=1:raise NotReady('Обучение: нужна единственная первая ферма')
        r=farms[0];value=r.get('rssValue');money=balances(state)
        if (type(value) not in (int,float) or not math.isfinite(value) or value<1
                or not integer(r.get('gatherMin')) or value<r['gatherMin']
                or completed_receipt(state,kind)!=money[str(kind)]):raise NotReady('Обучение: урожай или баланс не подтверждены')
        return cls(money,r['id'],math.floor(value),r['gatherMin'],kind)

    def matches(self,state):
        money=balances(state);rows=state.values.get('city_resources');row=rows.get(self.building) if table(rows) else None
        key=str(self.kind)
        return (table(row) and type(row.get('rssValue')) in (int,float) and row['rssValue']<self.minimum
            and money[key]>=self.money[key]+max(1,self.amount-1) and completed_receipt(state,self.kind)==money[key]
            and all(money[k]==v for k,v in self.money.items() if k!=key))


@dataclass(frozen=True)
class ChapterReceipt:
    items: dict
    money: dict

    @classmethod
    def capture(cls,state):
        d=data(state);cfg=d['config'];rows=d.get('chapterLoot');quests=d.get('chapterQuests')
        if (d['step']!=76 or cfg.get('Target')!='SLG_2_BARBARAIN_MISSION_CLAIM'
                or cfg.get('EndCondition')!='EVENT_TUTORIAL_WAIT_CONDITION' or d.get('chapter')!=1
                or 'BarbariansInvadePopUp' not in state.values.get('views',{})
                or set(state.values['views'])-BASE_VIEWS-{'BarbariansInvadePopUp'}
                or not table(quests) or not table(quests.get('4')) or quests['4'].get('Status')!=2
                or any(not table(quests.get(str(i))) or quests[str(i)].get('Status')!=3 for i in (1,2,3))
                or not table(rows) or len(rows)!=4):raise NotReady('Обучение: награда первой главы ещё не готова')
        items=inventory(state);seen=set()
        for row in rows.values():
            if (not table(row) or row.get('ID')!=23330016 or row.get('Type')!=2 or row.get('Value')!=1
                    or row.get('SubType') not in (1,7,13,26) or row['SubType'] in seen):
                raise NotReady('Обучение: неизвестный состав награды главы')
            seen.add(row['SubType']);key=str(row['SubType']);items[key]=items.get(key,0)+1
        return cls(items,balances(state))

    def matches(self,state):
        d=data(state);quests=d.get('chapterQuests',{})
        return (inventory(state)==self.items and balances(state)==self.money and
            (d.get('chapter')==2 or table(quests.get('4')) and quests['4'].get('Status')==3))


@dataclass(frozen=True)
class StartingKeyReceipt:
    items: dict
    money: dict
    now: int

    @classmethod
    def capture(cls,state):
        d=data(state);t=d.get('tavern');items=inventory(state)
        if (d['step']!=88 or d.get('tavernVisible') is not True or not table(t) or t.get('menu')!=1
                or t.get('multi') is not False or items.get('48')!=1):
            raise NotReady('Обучение: нужен единственный стартовый золотой ключ и одиночное открытие')
        del items['48']
        return cls(items,balances(state),state.values['server_time'])

    def matches(self,state):
        d=data(state)
        t=d.get('tavern');hero=d.get('hero');tokens=d.get('heroTokens');expected=dict(self.items)
        if (not table(t) or not table(t.get('items')) or not t['items'] or d.get('heroVisible') is not True
                or not table(hero) or not integer(hero.get('id'),1) or hero.get('star')!=1
                or not table(tokens) or len(tokens)!=1 or not table(hero.get('owned'))
                or hero['owned'].get('id')!=hero['id'] or hero['owned'].get('star')!=1
                or not integer(hero['owned'].get('created'),1) or hero['owned']['created']<self.now-2000):return False
        token=next(iter(tokens));count=0
        for row in t['items'].values():
            if not table(row) or not integer(row.get('Id'),1) or not integer(row.get('Cnt'),1):return False
            key=str(row['Id'])
            if key==token:
                if row['Cnt']!=1 or tokens[token]!=hero['id']:return False
                count+=1
            else:expected[key]=expected.get(key,0)+row['Cnt']
        return count==1 and inventory(state)==expected and balances(state)==self.money and d.get('step')==90


def chapter_point(state):
    d=data(state);pos=d.get('followPos')
    if not table(pos) or any(type(pos.get(k)) not in (int,float) or not math.isfinite(pos[k]) for k in ('1','2','3')):
        raise NotReady('Обучение: координаты награды не подтверждены')
    point=(round(480+54*pos['1']),round(270-54*pos['2']))
    if abs(point[0]-730)>3 or abs(point[1]-435)>3 or abs(pos['3'])>.01:
        raise NotReady('Обучение: награда находится вне проверенной области')
    return point


def unlock_point(state):
    d=data(state);u=d.get('unlock');cfg=d['config']
    if (d.get('name')=='unlock_radar' and d['step']==2 and cfg.get('Target')=='UNLOCKLV_SLG2_SCOUT_CAMP'
            and d.get('unlockVisible') is True and table(u) and u.get('canClick') is True and u.get('clicked') is False
            and u.get('items')=={'1':{'funcName':'LC_BUILD_BUILDING_NAME_28','funcId':31,'funcBType':28,'funcIconType':2}}
            and set(state.values.get('views',{}))<=BASE_VIEWS|{'NewFeaturesUnlockedPage'}):return (480,500)
    if (d.get('name')=='slg_2_new_event' and d['step']==1 and cfg.get('Target')=='UNLOCKLV_SLG2_EVENT'
            and d.get('unlockVisible') is True and table(u) and u.get('canClick') is True and u.get('clicked') is False
            and table(u.get('items')) and {key:row.get('funcId') for key,row in u['items'].items() if table(row)}=={'1':27,'2':32}
            and set(state.values.get('views',{}))<=BASE_VIEWS|{'NewFeaturesUnlockedPage'}):return (480,500)
    if (d['step']!=81 or cfg.get('Target')!='UNLOCKLV_SLG2_TASK' or d.get('unlockVisible') is not True
            or not table(u) or u.get('canClick') is not True or u.get('clicked') is not False
            or not table(u.get('items')) or len(u['items'])!=1 or not table(u['items'].get('1'))
            or u['items']['1'].get('funcId')!=27 or u['items']['1'].get('funcName')!='LC_COMMON_QUESTS'
            or set(state.values.get('views',{}))-BASE_VIEWS-{'NewFeaturesUnlockedPage'}):
        raise NotReady('Обучение: экран открытия заданий не подтверждён')
    return (480,500)


STORIES={78:'VSBBRV2_SC1_04',80:'VSBBRV2_SC2_01',93:'VSBBRV2_SC2_02_',98:'VSBBRV2_SC2_03_'}
TOWN_STORIES={2:'VSBBR_BT1_01',5:'VSBBR_BT1_07',6:'VSBBR_BT1_02',14:'VSBBR_BT1_08',
    18:'VSBBR_BT1_03',21:'VSBBR_BT1_04',23:'VSBBR_BT1_05'}
SINGLE_CHOICES={('VSBBRV2_SC1_04',3):'LC_DIALOG_VSBBRV2_SC1_11',
    ('VSBBR_BT1_02',2):'LC_DIALOG_VSBBR_BT1_05',('VSBBR_BT1_03',2):'LC_DIALOG_VSBBR_BT1_09'}


def current_story(d):
    if d.get('name')=='slg_2_v4':return STORIES.get(d.get('step'))
    if d.get('name')=='slg_2_towncenter_3':return TOWN_STORIES.get(d.get('step'))
    if d.get('name')=='slg_2_towncenter_5_1':return {3:'VSBBR_BT2_01',6:'VSBBR_BT3_01',14:'VSBBRV3_SC5_03'}.get(d.get('step'))
    return None


def fred_point(state):
    d=data(state);cfg=d['config'];cover=d.get('cover');pos=d.get('followPos')
    rules={5:('SLG_2_BARBARAIN_MISSION','GeneralRight'),7:('AidFredPopup.AidFredPopup_BtnGreen1','GeneralRight'),
        8:('AidFredPopup.AidFredPopup_btnDialog','GeneralUp'),9:('AidFredPopup.AidFredPopup_btnDialog','GeneralUp'),
        10:('AidFredPopup.AidFredPopup_itemArea','GeneralUp'),12:('AidFredPopup.AidFredPopup_BtnBlue1','GeneralUp')}
    target,name=rules.get(d.get('step'),(None,None));allowed=BASE_VIEWS|({'AidFredPopup','CommonBackground'} if d.get('step')!=5 else set())
    if (d.get('name')!='slg_2_towncenter_5_1' or target is None or cfg.get('StepType')!='CLICK_UI'
            or cfg.get('Target')!=target or not table(cover)
            or cover.get('CoverName')!=name or cover.get('Target')!=target
            or not table(pos) or any(type(pos.get(k)) not in (int,float) or not math.isfinite(pos[k]) for k in ('1','2','3'))
            or abs(pos['3'])>.01 or set(state.values.get('views',{}))-allowed):
        raise NotReady('Обучение: вход в помощь Фреду не подтверждён')
    point=(round(480+54*pos['1']),round(270-54*pos['2']))
    if not 80<=point[0]<=880 or not 80<=point[1]<=510:raise NotReady('Обучение: указание помощи Фреду вне экрана')
    return point


@dataclass(frozen=True)
class NewSignupReceipt:
    event: str
    tasks: dict
    money: dict
    items: dict

    @classmethod
    def capture(cls,state):
        d=data(state);g=d.get('guide');s=d.get('signup');cfg=d.get('config',{})
        task=s.get('task') if table(s) else None;p=g.get('worldPos') if table(g) else None
        if (d.get('name')!='slg_2_new_event' or d.get('step')!=4 or cfg.get('Target')!='SLG_2_EVENT_REWARD'
                or not table(s) or s.get('current')!=s.get('id') or not isinstance(s.get('id'),str) or not s['id'].isdecimal()
                or s.get('server')!=state.values.get('player',{}).get('ServerID')
                or not integer(s.get('end'),1) or s['end']*1000<=state.values.get('server_time',float('inf'))
                or s.get('ui')!={'UIType':'NewSignup','LastEventId':s['id']} or not table(task)
                or task.get('TaskID')!=1 or task.get('Value')!=1 or task.get('ScoreRuleKey')!='login_daily'
                or task.get('Loots')!={'1':{'Value':1,'Type':2,'SubType':47}}
                or task.get('AddtionLoots')!={} or task.get('Addtion2Loots')!={}
                or not table(g) or g.get('forceClick') is not True or g.get('needClickCb') is not False
                or g.get('is3D') is not False or not table(p)
                or any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for k in ('1','2','3'))
                or abs(480+54*p['1']-248)>4 or abs(270-54*p['2']-408)>4 or abs(p['3'])>.01
                or 'AllUIEventMainPage_SLG' not in state.values.get('views',{})
                or set(state.values['views'])-BASE_VIEWS-{'AllUIEventMainPage_SLG','CommonBackground','QuestGuide'}):
            raise NotReady('Обучение: бесплатный первый день NewSignup не подтверждён')
        tasks=s.get('playerTasks')
        if (not table(tasks) or any(not table(r) or not integer(r.get('TaskId'),1) or type(r.get('TaskStatus')) is not int for r in tasks.values())
                or sum(r.get('TaskId')==1 and r.get('TaskStatus')==-1 for r in tasks.values())!=1):
            raise NotReady('Обучение: первый день события недоступен')
        expected=deepcopy(tasks)
        for row in expected.values():
            if row.get('TaskId')==1:row['TaskStatus']=-2
        items=inventory(state);items['47']=items.get('47',0)+1
        return cls(s['id'],expected,balances(state),items)

    def matches(self,state):
        s=data(state).get('signup')
        return (table(s) and s.get('id')==self.event and s.get('playerTasks')==self.tasks
            and balances(state)==self.money and inventory(state)==self.items)


@dataclass(frozen=True)
class FredTransitionReceipt:
    step: int
    money: dict
    items: dict

    @classmethod
    def capture(cls,state):
        d=data(state);fred_point(state);f=d.get('fred');quest=d.get('chapterQuests',{}).get('10')
        if (not table(f) or f.get('chapter')!=2 or not table(f.get('firstQuest'))
                or f['firstQuest'].get('ID')!=10 or f['firstQuest'].get('RewardID')!=23330011
                or f.get('loot')!={'1':{'ID':23330011,'Type':2,'Value':1,'SubType':10990,'DefaultSortIndex':1}}
                or not table(quest) or quest.get('Status')!=(2 if d['step']==7 else 3)):
            raise NotReady('Обучение: награда за щит не подтверждена')
        items=inventory(state)
        if d['step']==7:items['10990']=items.get('10990',0)+1
        elif not integer(items.get('10990'),1):raise NotReady('Обучение: фрагмент награды за щит не подтверждён')
        return cls(d['step'],balances(state),items)

    def matches(self,state):
        d=data(state)
        return (d.get('name')=='slg_2_towncenter_5_1' and d.get('step')==self.step+1
            and d.get('chapterQuests',{}).get('10',{}).get('Status')==3
            and balances(state)==self.money and inventory(state)==self.items)


def rescue_point(state):
    d=data(state);cfg=d['config'];r=d.get('rescue');cover=d.get('cover')
    form=r.get('form') if table(r) else None
    if (d.get('name')=='slg_2_towncenter_3' and d['step']==11 and cfg.get('StepType')=='CLICK_UI'
            and cfg.get('Target')=='SELECT_HERO' and table(cover) and cover.get('CoverName')=='SELECT_HERO_IN_LIST'
            and table(r) and r.get('heroes')=={'1':{'id':3,'level':1,'state':1}}
            and table(form) and form.get('SelHeroIds')=={} and 'HeroSelectPop' in state.values.get('views',{})
            and not set(state.values['views'])-BASE_VIEWS-{'SendTroopsMain','HeroSelectPop','CommonBackground'}):return (60,145)
    if (d.get('name')=='slg_2_towncenter_3' and d['step']==10 and cfg.get('StepType')=='CLICK_UI'
            and cfg.get('Target')=='SELECT_HERO' and table(cover) and cover.get('CoverName')=='SELECT_HERO'
            and table(r) and integer(r.get('id'),1) and r['id']%100==0 and table(form)
            and form.get('DstCharId')==r['id']//100 and form.get('SelHeroIds')=={}
            and form.get('SelectUnits')=={'1':1000} and form.get('isAttackNpc') is True
            and form.get('Dispatched') is False and 'SendTroopsMain' in state.values.get('views',{})
            and not set(state.values['views'])-BASE_VIEWS-{'SendTroopsMain','CommonBackground'}):return (285,270)
    if (d.get('name')=='slg_2_towncenter_3' and d['step']==9 and cfg.get('StepType')=='CLICK_UI'
            and cfg.get('Target')=='BUILD_TROOP' and table(cover) and cover.get('Target')=='BUILD_TROOP'
            and table(r) and r.get('selectTarget')==r.get('id') and integer(r.get('id'),1)
            and r.get('player')==-2 and 'MapUISelectTroops' in state.values.get('views',{})
            and not set(state.values['views'])-BASE_VIEWS-{'MapUISelectTroops','TroopSelectedPopUp'}):return (760,110)
    if (d.get('name')=='slg_2_towncenter_3' and d['step']==8 and cfg.get('StepType')=='CLICK_UI'
            and cfg.get('Target')=='ATTACK' and table(cover) and cover.get('Target')=='ATTACK'
            and table(r) and r.get('popupTarget')==r.get('id') and integer(r.get('id'),1)
            and r.get('player')==-2 and r.get('fight')==7 and r.get('tick')==3
            and 'MapUIBarbarianPopUp' in state.values.get('views',{})
            and not set(state.values['views'])-BASE_VIEWS-{'MapUIBarbarianPopUp'}):return (685,360)
    if (d.get('name')!='slg_2_towncenter_3' or d['step']!=7 or cfg.get('StepType')!='CLICK_3D'
            or cfg.get('Target')!='Fight2_BarbarianCharID' or cfg.get('LockCamera')!=1
            or cfg.get('EndCondition')!='EVENT_TUTORIAL_CLICK_COVER' or not table(cover)
            or cover.get('Target')!='Fight2_BarbarianCharID' or cover.get('CoverName')!='BLOCK_UI_ONLY_WITH_ARROW2'
            or not table(r) or not integer(r.get('id'),1) or r.get('player')!=-2 or r.get('kind')!=1
            or r.get('fight')!=7 or r.get('tick')!=3 or not table(r.get('npc')) or r['npc'].get('npcLevel')!=1
            or r['npc'].get('npcType')!=229 or set(state.values.get('views',{}))-BASE_VIEWS):
        raise NotReady('Обучение: учебная цель спасения не подтверждена')
    return (480,260)


@dataclass(frozen=True)
class GiftRevealReceipt:
    money: dict
    items: dict

    @classmethod
    def capture(cls,state):
        d=data(state);cfg=d['config'];g=d.get('gift');cover=d.get('cover')
        if (d.get('name')!='slg_2_towncenter_3' or d['step']!=19 or cfg.get('StepType')!='COLLECT'
                or cfg.get('Target')!='SLG_2_Aethelflad_GiftIcon' or cfg.get('ExtFunAtBegin')!='GiftPerformanceShowBubble'
                or not table(cover) or cover.get('Target')!=cfg['Target'] or not table(g)
                or g.get('rewardId')!=23330001 or g.get('arrived') is not True or g.get('bubble') is not True
                or g.get('claiming') not in (None,False) or set(state.values.get('views',{}))-BASE_VIEWS):
            raise NotReady('Обучение: подарок Этельфледы не подтверждён')
        gift_money(state)
        return cls(balances(state),inventory(state))

    def matches(self,state):
        d=data(state)
        return (d.get('name')=='slg_2_towncenter_3' and d.get('step')==20
            and 'RoutineRewardsCollect' in state.values.get('views',{})
            and balances(state)==self.money and inventory(state)==self.items)


def gift_money(state):
    g=data(state).get('gift');loot=g.get('loot') if table(g) else None
    expected={1:10000,2:10000,5:50};seen={}
    if not table(loot) or len(loot)!=3:raise NotReady('Обучение: состав подарка не прочитан')
    for row in loot.values():
        if (not table(row) or row.get('ID')!=23330001 or row.get('Type')!=1
                or type(row.get('SubType')) is not int or row['SubType'] in seen):
            raise NotReady('Обучение: неизвестный состав подарка')
        seen[row['SubType']]=row.get('Value')
    if seen!=expected:raise NotReady('Обучение: состав подарка изменился')
    return {str(k):v for k,v in expected.items()}


@dataclass(frozen=True)
class GiftClaimReceipt:
    money: dict
    items: dict

    @classmethod
    def capture(cls,state):
        d=data(state);g=d.get('gift');p=g.get('popup') if table(g) else None
        if (d.get('name')!='slg_2_towncenter_3' or d['step']!=20 or d['config'].get('Target')!='GIFT_3'
                or not table(g) or g.get('claiming') is not True or g.get('bubble') is not False
                or not table(p) or p.get('showing') is not True or p.get('flew') is not False
                or p.get('rows')!=g.get('loot') or 'RoutineRewardsCollect' not in state.values.get('views',{})
                or set(state.values['views'])-BASE_VIEWS-{'RoutineRewardsCollect','CommonBackground'}):
            raise NotReady('Обучение: подтверждение подарка не готово')
        money=balances(state)
        for key,value in gift_money(state).items():money[key]+=value
        return cls(money,inventory(state))

    def matches(self,state):
        d=data(state)
        return (d.get('name')=='slg_2_towncenter_3' and d.get('step')==21
            and 'RoutineRewardsCollect' not in state.values.get('views',{})
            and balances(state)==self.money and inventory(state)==self.items)


@dataclass(frozen=True)
class RescueMarchReceipt:
    money: dict
    items: dict
    troops: dict

    @classmethod
    def capture(cls,state):
        d=data(state);r=d.get('rescue');cfg=d['config'];form=r.get('form') if table(r) else None
        if (d.get('name')!='slg_2_towncenter_3' or d['step']!=12 or cfg.get('Target')!='MARCH'
                or cfg.get('StepType')!='CLICK_UI' or not table(r) or r.get('fight')!=7 or r.get('tick')!=3
                or not table(form) or form.get('DstCharId')!=r.get('id',0)//100 or form.get('SelHeroIds')!={'1':3}
                or form.get('SelectUnits')!={'1':1000} or form.get('TotalNum')!=1000 or form.get('CharType')!=1
                or form.get('isAttackNpc') is not True or form.get('isAggressive') is not False
                or form.get('Dispatched') is not False or 'SendTroopsMain' not in state.values.get('views',{})
                or set(state.values['views'])-BASE_VIEWS-{'SendTroopsMain','CommonBackground'}):
            raise NotReady('Обучение: учебный марш с Сунь-цзы и1000 воинов не подтверждён')
        troops=state.values.get('troops')
        if not table(troops):raise NotReady('Обучение: войска не прочитаны')
        return cls(balances(state),inventory(state),deepcopy(troops))

    def matches(self,state):
        d=data(state);r=d.get('rescue')
        return (d.get('step') in (13,14) and table(r) and r.get('fight')==7 and integer(r.get('tick'),4)
            and balances(state)==self.money and inventory(state)==self.items and state.values.get('troops')==self.troops
            and 'SendTroopsMain' not in state.values.get('views',{}))


@dataclass(frozen=True)
class StoryReceipt:
    step: int
    story: str
    node: int
    next_nodes: tuple
    money: dict
    choice: bool
    max_step: int
    config_name: str

    @classmethod
    def capture(cls,state):
        d=data(state);cfg=d['config'];story=d.get('story');node=story.get('node') if table(story) else None
        allowed=BASE_VIEWS|{'StoryConversation'}
        if d.get('name')=='slg_2_towncenter_5_1' and d['step'] in (6,14):allowed|={'AidFredPopup','CommonBackground'}
        if d.get('name')=='slg_2_towncenter_5_1' and d['step']==14:allowed|={'CanyonLevelMainPage'}
        if d['step']==98:allowed|={'CanyonLevelMainPage','CommonBackground'}
        expected=current_story(d)
        if expected and expected.endswith('_'):
            civ=state.values.get('player',{}).get('Civilization')
            if not integer(civ,1):raise NotReady('Обучение: цивилизация сюжетного диалога неизвестна')
            expected+=str(civ).zfill(2)
        static_narration=(d.get('name')=='slg_2_towncenter_3' and table(node) and node.get('Style')==2
            and story.get('typing') is None and type(node.get('autoPlayEndTime')) in (int,float)
            and node['autoPlayEndTime']<=state.values.get('server_time',0))
        if (expected is None or cfg.get('Target')!='STORY_CONVERSATION_END'
                or cfg.get('ExtFunAtBegin')!='PopStoryConversation' or d.get('storyVisible') is not True
                or not table(story) or story.get('id')!=expected or story.get('return')!='Tutorial'
                or (story.get('canClick') is not True and story.get('choiceShown') is not True)
                or (story.get('typing') is not False and not static_narration) or story.get('end') is not False
                or not table(node) or not integer(node.get('Id'),1) or node.get('DialogType') not in (1,2)
                or set(state.values.get('views',{}))-allowed):
            raise NotReady('Обучение: простой сюжетный диалог ещё не готов')
        if node['DialogType']==2 and ((story['id'],node['Id']) not in SINGLE_CHOICES
                or node.get('ChoiceContent')!=SINGLE_CHOICES[(story['id'],node['Id'])]):
            raise NotReady('Обучение: этот выбор сюжетного диалога ещё не проверен')
        graph=story.get('graph');nexts=[];key=node.get('NextDialogId')
        if not table(graph):raise NotReady('Обучение: последовательность реплик не подтверждена')
        if key in (None,'') and str(node['Id'])!=graph.get('EndId'):
            raise NotReady('Обучение: конечная реплика не подтверждена')
        for _ in range(8):
            if key in (None,''):break
            if type(key) is not str or not key.isdecimal() or key in nexts:raise NotReady('Обучение: неизвестная ветка реплик')
            row=graph.get(key)
            if not table(row) or row.get('DialogType') not in (1,2):raise NotReady('Обучение: неизвестный следующий узел')
            nexts.append(key)
            if row['DialogType']==2:break
            key=row.get('NextDialogId')
        maximum=({'slg_2_v4':{78:80,80:81,93:95,98:99},
            'slg_2_towncenter_3':{2:5,5:6,6:7,14:18,18:19,21:23,23:24},
            'slg_2_towncenter_5_1':{3:5,6:7,14:16}}[d['name']][d['step']])
        return cls(d['step'],story['id'],node['Id'],tuple(nexts),balances(state),story.get('choiceShown') is True,maximum,d['name'])

    def matches(self,state):
        d=data(state);story=d.get('story')
        if balances(state)!=self.money:return False
        if d.get('name')!=self.config_name:return False
        if d.get('active') is False:return d.get('completed') is True and (self.config_name,self.step) in (
            ('slg_2_towncenter_3',23),('slg_2_towncenter_5_1',14))
        if d.get('step')!=self.step:return self.step<d.get('step',0)<=self.max_step
        return (table(story) and story.get('id')==self.story and table(story.get('node'))
            and (str(story['node'].get('Id')) in self.next_nodes and story['node']['Id']!=self.node
                or not self.choice and story.get('choiceShown') is True and story['node'].get('Id')==self.node))


@dataclass(frozen=True)
class AdvanceTutorial:
    max_actions: int = 8

    def __call__(self,device,observe,cancelled,clock,allowed):
        initial=observe();state=initial;count=0;budget=clock()+90
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Обучение отменено')
        while count<self.max_actions and clock()<budget:
            permit();state=observe();d=data(state)
            if not d.get('active'):
                try:point=battle_point(state)
                except NotReady:
                    if count:break
                    raise NotReady('Вступление завершено; ожидание поддержанного этапа боевого обучения')
                before_money=balances(state);before_items=inventory(state)
                config=state.values['onboarding_battle']['config'];victory=state.values['onboarding_battle']['state']==3
                permit();device.tap(*point,hold_ms=100)
                deadline=min(budget,clock()+15)
                while True:
                    permit();state=observe();b=state.values.get('onboarding_battle')
                    if balances(state)!=before_money or inventory(state)!=before_items:
                        raise WorkflowError('Обучение: активы изменились при начале учебного боя')
                    if table(b) and ((not victory and b.get('config')==config and b.get('state')==13)
                            or victory and b.get('config')==config+1 and b.get('state')==10):break
                    if clock()>=deadline:raise WorkflowError('Обучение: начало боя не подтверждено; повтор не выполнялся')
                    if cancelled.wait(.1):raise Cancelled('Обучение отменено')
                count+=1
                continue
            if current_story(d) and d.get('storyVisible') is True and table(d.get('story')):
                if d['story'].get('typing') is True or d['story'].get('canClick') is False and d['story'].get('choiceShown') is not True:
                    if cancelled.wait(.2):raise Cancelled('Обучение отменено')
                    continue
            if (d['config'].get('StepType') in ('WAIT','MOVE_CAMERA','PLAY_FIGHT')
                    and not (d.get('name')=='unlock_radar' and d['step']==32)
                    and not (d.get('name')=='unlock_radar' and d['step']==2)
                    and not (d.get('name')=='slg_2_new_event' and d['step']==1)
                    and not (d.get('name')=='slg_2_towncenter_3' and d['step']==20)
                    and not current_story(d) and (d.get('name')!='slg_2_v4' or d['step'] not in (49,58,76,81))):
                deadline=min(budget,clock()+10);step=d['step']
                while data(state).get('step')==step and clock()<deadline:
                    permit()
                    if cancelled.wait(.1):raise Cancelled('Обучение отменено')
                    state=observe()
                if data(state).get('step')==step:break
                continue
            delay=2000 if d['config'].get('StepType')=='DIALOG' else d['config'].get('HighlightDelay',0)
            if type(delay) not in (int,float) or not math.isfinite(delay) or not 0<=delay<=10000:
                raise NotReady('Обучение: задержка подсказки не подтверждена')
            if delay>0:
                entered=d.get('enterTime');now=state.values.get('server_time')
                if (type(entered) not in (int,float) or type(now) not in (int,float)
                        or not math.isfinite(entered) or not math.isfinite(now) or entered<=0 or now<entered):
                    raise NotReady('Обучение: время входа в диалог не подтверждено')
                if now-entered<delay+100:
                    if cancelled.wait(.2):raise Cancelled('Обучение отменено')
                    continue
            try:
                receipt=None
                if d.get('name')=='unlock_radar' and d['step']==2:point=unlock_point(state)
                elif d.get('name')=='slg_2_recycle_plants' and d['step']==2:point=recycle_point(state)
                elif d.get('name')=='slg_2_recycle_plants' and d['step']==3:
                    point=recycle_point(state);receipt=PlantRecycleReceipt.capture(state)
                elif d.get('name')=='unlock_radar' and d['config'].get('StepType')!='DIALOG':
                    point=radar_point(state)
                    if d['step']==8:receipt=RadarBuildReceipt.capture(state)
                    if d['step']==31:receipt=RadarClaimReceipt.capture(state)
                    if d['step']==32:receipt=RadarClaimReceipt(balances(state),inventory(state))
                    if d['step']==42:receipt=RadarMarchReceipt.capture(state)
                elif d.get('name')=='slg_2_new_event' and d['step']==1:point=unlock_point(state)
                elif d.get('name')=='slg_2_new_event' and d['step']==2:point=guided_point(state)
                elif d.get('name')=='slg_2_new_event' and d['step']==4:
                    receipt=NewSignupReceipt.capture(state);point=(248,408)
                elif d.get('name')=='slg_2_towncenter_5_1' and d['step'] in (5,7,8,9,10,12):
                    point=fred_point(state)
                    if d['step'] in (7,8,9):receipt=FredTransitionReceipt.capture(state)
                elif d.get('name')=='slg_2_towncenter_3' and d['step']==20:
                    receipt=GiftClaimReceipt.capture(state);point=(480,500)
                elif d.get('name')=='slg_2_towncenter_3' and d['step']==19:
                    receipt=GiftRevealReceipt.capture(state);point=(485,205)
                elif d.get('name')=='slg_2_towncenter_3' and d['step']==12:
                    receipt=RescueMarchReceipt.capture(state);point=(695,475)
                elif d.get('name')=='slg_2_towncenter_3' and d['step'] in (7,8,9,10,11):point=rescue_point(state)
                elif d.get('name')=='first_enter_vippage' and d['step']==2:
                    receipt=VipIntroPointReceipt.capture(state);point=(765,152)
                elif d.get('name')=='first_enter_vippage' and d['step']==5:
                    receipt=VipIntroBoxReceipt.capture(state);point=(705,267)
                elif d.get('name')=='first_enter_vippage' and d['step'] in (3,6):
                    point=vip_intro_close_point(state)
                elif d.get('name')=='first_enter_vippage' and d['step']==8:
                    point=vip_intro_special_point(state)
                elif d['step']==81:point=unlock_point(state)
                elif current_story(d):
                    receipt=StoryReceipt.capture(state);point=(480,470) if receipt.choice else (790,500)
                elif d['step']==76:receipt=ChapterReceipt.capture(state);point=chapter_point(state)
                elif d['step'] in (49,58,95):point=guided_point(state)
                elif d['config'].get('StepType')=='COLLECT':
                    receipt=CollectReceipt.capture(state);point={12:(390,270),20:(565,290),66:(315,320)}[d['step']]
                elif d['config'].get('StepType')=='SELECT_BUILDING':point=select_point(state)
                else:point=dialog_point(state) if d['config'].get('StepType')=='DIALOG' else click_point(state)
            except NotReady:
                if count:break
                raise
            before_money=balances(state);step=d['step']
            if d.get('name')=='slg_2_v4':
                if step in (9,17,63,85):receipt=BuildReceipt.capture(state)
                if step in (26,54,71):receipt=TutorialUpgradeReceipt.capture(state)
                if step==88:receipt=StartingKeyReceipt.capture(state)
            permit();device.tap(*point,hold_ms=100)
            deadline=min(budget,clock()+15)
            while True:
                permit();state=observe();current=data(state)
                if receipt is None and balances(state)!=before_money:raise WorkflowError('Обучение: валюты изменились при переходе')
                if isinstance(receipt,StoryReceipt) and receipt.matches(state):break
                if not current.get('active') or current['step']!=step:
                    maximum=({8:12,13:15,17:20,24:26,26:31,31:32,32:37,38:40}.get(step,step+1) if d.get('name')=='unlock_radar' else
                        {9:12,12:14,17:20,20:22,26:30,54:56,63:66,66:68,71:74,76:78,81:83,85:87,88:90}.get(step,step+1))
                    if current.get('active') and not step<current['step']<=maximum:
                        raise WorkflowError('Обучение: неожиданный переход шага')
                    if receipt is None or receipt.matches(state):break
                if clock()>=deadline:raise WorkflowError('Обучение: переход не подтверждён; повтор не выполнялся')
                if cancelled.wait(.1):raise Cancelled('Обучение отменено')
            count+=1
            if cancelled.wait(.7):raise Cancelled('Обучение отменено')
        state.values['tutorial_actions']=count
        return state


def tutorial_workflow(settings,*,verified=False):
    limit=TutorialOptions.from_settings(settings).max_actions
    return Workflow('tutorial','1.1.12.20',960,540,(Procedure(AdvanceTutorial(limit)),),verified=verified,
        extra_paths=FIELDS,data_timeout=10,guide_condition=TutorialGuide(),requires_city=False,
        wait_reason='Ожидание проверенного шага обучения нового персонажа')
