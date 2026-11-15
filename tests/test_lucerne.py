from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.lucerne import ExperienceReceipt, FreeRewardReceipt, data, lucerne_workflow
from mirage.model import Snapshot
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady


def panel():
    return Snapshot('one',10,20,100.,'1.1.12.20',{'server_time':100000,'daily_score':70,
        'in_city':True,'city_enabled':True,'views':{'MapHudPanel':True,'BattlePassMain':True,'CommonBackground':True},
        'resources':{str(i):100000 for i in range(1,7)},'supply_inventory':{'ready':True,'items':{'1':10}},
        'lucerne':{'ready':True,'visible':True,'time':{'SeasonId':62,'EndTime':10000000},
            'level':{'Level':2,'Exp':10},'pay':1,'daily':1,'levelExp':100,'dailyExp':50,
            'newSeason':False,'tab':2,'missionTab':1,'week':5,'rewards':{},'season':{},
            'weeks':{'5':{'1':{'id':1024,'status':-1,'score':30,'extra':False,'group':4},
                          '2':{'id':2004,'status':-1,'score':50,'extra':False,'group':4}}}}})


def test_daily_receipt_requires_exact_free_experience_and_preserved_assets():
    before=panel();receipt=ExperienceReceipt.capture(before,daily=True);after=deepcopy(before)
    after.values['lucerne'].update(daily=2,level={'Level':2,'Exp':60})
    assert receipt.matches(after)
    after.values['resources']['5']-=1;assert not receipt.matches(after)


def test_mission_receipt_tracks_identity_across_game_owned_list_reordering_and_level_up():
    before=panel();before.values['lucerne']['level']['Exp']=90
    receipt=ExperienceReceipt.capture(before,'5');after=deepcopy(before);d=after.values['lucerne']
    d['weeks']['5']={'1':d['weeks']['5']['2'],'2':{**d['weeks']['5']['1'],'status':-2}}
    d['level']={'Level':3,'Exp':20}
    assert receipt.matches(after)
    d['weeks']['5']['2']['status']=-1;assert not receipt.matches(after)


@pytest.mark.parametrize('fault',['paid','unknown','partial','bonus','tab','week','expired','not_ready','score','inventory'])
def test_unknown_or_unconfirmed_mission_cannot_authorize_claim(fault):
    s=panel();d=s.values['lucerne']
    if fault=='paid':d['pay']=2
    elif fault=='unknown':s.values['views']['PopupInfoConfirm']=True
    elif fault=='partial':d['weeks']['$truncated']=True
    elif fault=='bonus':d['weeks']['5']['1']['extra']=True
    elif fault=='tab':d['tab']=1
    elif fault=='week':d['week']=4
    elif fault=='expired':d['time']['EndTime']=110000
    elif fault=='not_ready':d['weeks']['5']['1']['status']=0
    elif fault=='score':d['weeks']['5']['1']['score']=None
    else:s.values['supply_inventory']['ready']=False
    with pytest.raises(NotReady):ExperienceReceipt.capture(s,'5')


@pytest.mark.parametrize('fault',['wrong_exp','other_task','season','item','currency'])
def test_ambiguous_mission_receipt_rejects_unrelated_changes(fault):
    before=panel();receipt=ExperienceReceipt.capture(before,'5');after=deepcopy(before);d=after.values['lucerne']
    d['weeks']['5']['1']['status']=-2;d['level']['Exp']+=30
    if fault=='wrong_exp':d['level']['Exp']+=1
    elif fault=='other_task':d['weeks']['5']['1']['status']=-1;d['weeks']['5']['2']['status']=-2
    elif fault=='season':d['time']['SeasonId']+=1
    elif fault=='item':after.values['supply_inventory']['items']['1']+=1
    else:after.values['resources']['1']+=1
    assert not receipt.matches(after)


def test_snapshot_budget_and_claim_bound():
    from mirage.memory import PATHS
    from mirage.lucerne import FIELDS
    assert len(PATHS|FIELDS)<=64
    with pytest.raises(ValueError):lucerne_workflow({'max_claims':True})


def prize_panel():
    s=panel();s.values['lucerne'].update(tab=1,level={'Level':3,'Exp':40},rewards={
        '1':{'level':1,'free':True,'paid':False,'loot':{'Type':2,'SubType':2,'Value':10}},
        '3':{'level':3,'free':None,'paid':False,'loot':{'Type':2,'SubType':8,'Value':10}},
        '4':{'level':4,'free':None,'paid':None,'loot':{'Type':2,'SubType':75,'Value':1}}})
    return s


def test_free_prizes_require_full_inventory_and_only_earned_free_flags():
    before=prize_panel();receipt=FreeRewardReceipt.capture(before);after=deepcopy(before)
    after.values['lucerne']['rewards']['3']['free']=True
    after.values['supply_inventory']['items']['8']=10
    assert receipt.matches(after) and receipt.levels==(3,)
    after.values['lucerne']['rewards']['4']['free']=True;assert not receipt.matches(after)


@pytest.mark.parametrize('fault',['paid','partial','type','gem_spend','missing_loot'])
def test_free_prize_receipt_never_confuses_paid_unlock_or_partial_delivery(fault):
    before=prize_panel();after=deepcopy(before)
    after.values['lucerne']['rewards']['3']['free']=True
    after.values['supply_inventory']['items']['8']=10
    if fault=='partial':
        before.values['lucerne']['rewards']['3']['loot']['$truncated']=True
        with pytest.raises(NotReady):FreeRewardReceipt.capture(before)
        return
    if fault=='type':
        before.values['lucerne']['rewards']['3']['loot']['Type']=3
        with pytest.raises(NotReady):FreeRewardReceipt.capture(before)
        return
    if fault=='paid':after.values['lucerne']['rewards']['3']['paid']=True
    elif fault=='gem_spend':after.values['resources']['5']-=1
    else:after.values['supply_inventory']['items']['8']=9
    assert not FreeRewardReceipt.capture(before).matches(after)


class Route:
    def __init__(self,monkeypatch):
        self.state=panel();self.now=100.;self.inputs=[];self.cancelled=threading.Event();self.cancel_on_claim=False
        v=self.state.values;v.update(hud_visible=True,hud_menu=False,vip_visible=False,
            city_selection_known=True,city_selection=None,queue_panel={'known':True,'visible':False},
            lucerne_levelup=False,buildings={'82':{'type':19,'state':1}},building_menu={'known':True,'selected':None})
        d=v['lucerne'];d.update(daily=2,level={'Level':2,'Exp':60},rewardVisible=False)
        d['weeks']['5']={'1':d['weeks']['5']['1']}
        d['season']={'1':{'id':1003,'status':-1,'score':400,'extra':False,'group':None}}
        d['rewards']={str(i):{'level':i,'free':True if i<=2 else None,'paid':False if i<=2 else None,
            'loot':{'Type':2,'SubType':8,'Value':i}} for i in range(1,7)}
        self.city()
        def navigate(*args,**kwargs):
            v['building_menu']['selected']={'id':'82','type':19,
                'buttons':['img_BattlePassHudIcon','btn_FunctionMarket','btn_CityPopUpResBank','btn_CityPopUpInfo']}
            return self.observe()
        monkeypatch.setattr('mirage.navigation.navigate_city',navigate)

    def city(self):
        self.state.values['lucerne']['visible']=False
        self.state.values['views']={'MapHudPanel':True}

    def show(self,extra=None):
        self.state.values['lucerne']['visible']=True
        self.state.values['views']={'MapHudPanel':True,'BattlePassMain':True,'CommonBackground':True,
            **({extra:True} if extra else {})}

    def observe(self):
        self.now+=1;return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y));v=self.state.values;d=v['lucerne']
        if (x,y)==(439,354):self.show();d['tab']=1
        elif (x,y)==(560,37):d['tab']=2
        elif (x,y)==(390,37):d['tab']=1
        elif (x,y)==(150,205):d['missionTab']=1
        elif (x,y)==(150,280):d['missionTab']=2
        elif (x,y) in ((806,268),(335,421)):
            row=(d['weeks']['5'] if x==806 else d['season'])['1'];row['status']=-2
            before=d['level']['Level'];amount=(before-1)*100+d['level']['Exp']+row['score']
            d['level']={'Level':amount//100+1,'Exp':amount%100}
            if d['level']['Level']!=before:v['lucerne_levelup']=True;self.show('battlePassPopWindow_LevelUp')
            if self.cancel_on_claim:self.cancelled.set()
        elif (x,y)==(619,436):v['lucerne_levelup']=False;self.show()
        elif (x,y)==(861,508):
            loot={}
            for key,row in d['rewards'].items():
                if row['level']<=d['level']['Level'] and row['free'] is not True:
                    row.update(free=True,paid=False);loot[key]=deepcopy(row['loot'])
                    v['supply_inventory']['items']['8']=v['supply_inventory']['items'].get('8',0)+row['loot']['Value']
            d.update(rewardVisible=True,rewardRows=loot);self.show('battlePassPopWindow_Reward')
        elif (x,y)==(480,443):d['rewardVisible']=False;self.show()
        elif (x,y)==(30,29):self.city()
        else:raise AssertionError((x,y))

    def run(self):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            lucerne_workflow({},verified=True),self.cancelled,instance_id='one',pid=10,player_id=20)


def test_full_route_collects_week_season_levelups_and_free_prizes_then_is_idle(monkeypatch):
    game=Route(monkeypatch);after=game.run()
    assert CITY_HUD.matches(after) and after.values['lucerne']['level']=={'Level':6,'Exp':90}
    assert after.values['supply_inventory']['items']['8']==18
    assert game.inputs.count((806,268))==1 and game.inputs.count((335,421))==1
    assert game.inputs.count((861,508))==1 and (480,443) in game.inputs
    before=len(game.inputs);game.run();assert len(game.inputs)==before


def test_stop_after_mission_commit_resumes_without_claiming_it_twice(monkeypatch):
    game=Route(monkeypatch);game.cancel_on_claim=True
    with pytest.raises(Cancelled):game.run()
    game.cancel_on_claim=False;game.cancelled.clear();game.run()
    assert game.inputs.count((806,268))==1 and game.inputs.count((335,421))==1


def test_paid_flag_nil_to_false_is_not_a_paid_reward_unlock():
    before=prize_panel();before.values['lucerne']['rewards']['3']['paid']=None
    receipt=FreeRewardReceipt.capture(before);after=deepcopy(before)
    after.values['lucerne']['rewards']['3'].update(free=True,paid=False)
    after.values['supply_inventory']['items']['8']=10
    assert receipt.matches(after)
