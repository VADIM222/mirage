from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.model import Profile, Snapshot, VipShopOptions
from mirage.vip_shop import FIELDS, PurchaseReceipt, offer, vip_shop_workflow
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady, WorkflowError


def form():
    return Snapshot('one',10,20,100.,'1.1.12.20',{'server_time':100000,
        'hud_visible':True,'hud_menu':False,'in_city':True,'city_enabled':True,
        'queue_panel':{'known':True,'visible':False},'city_selection_known':True,'city_selection':None,
        'vip_visible':False,'vip_level':12,'views':{'MapHudPanel':True,'VIPShop':True,'CommonBackground':True},
        'vip_shop_visible':True,'vip_shop_quick':False,'vip_shop_width':720.89923,'vip_shop_height':444.84235,
        'resources':{str(i):1000000 for i in range(1,7)},
        'supply_inventory':{'ready':True,'items':{'124':156,'58':601,'99':1}},
        'vip_shop_stock':{'Refresh':{'Value':1,'Method':'week','Next':10000},'Items':{
            '1':{'Type':2,'VipLvl':2,'DisCount':50,'Price':12000,'SubType':124,'PriceType':1,'Amount':29,'SlotId':1,'Weight':1},
            '2':{'Type':2,'VipLvl':3,'DisCount':70,'Price':7000,'SubType':58,'PriceType':1,'Amount':50,'SlotId':2,'Weight':2},
            '4':{'Type':2,'VipLvl':3,'DisCount':43,'Price':6,'SubType':58,'PriceType':5,'Amount':500,'SlotId':4,'Weight':4}}},
        'buildings':{'74':{'id':'74','type':20,'state':1}},'building_menu':{'known':True,'selected':None}})


def bought(state):
    state=deepcopy(state);v=state.values
    v['vip_shop_stock']['Items']['1']['Amount']-=1
    v['supply_inventory']['items']['124']+=1;v['resources']['1']-=12000
    return state


def test_purchase_receipt_requires_exact_food_inventory_and_slot_delta():
    before=form();receipt=PurchaseReceipt.capture(before,VipShopOptions())
    assert receipt.matches(bought(before))
    assert offer(before,VipShopOptions(item_id=58))[0]['SlotId']==2  # same item for gems is a different slot


@pytest.mark.parametrize('fault',['gems','double','loot','other_item','other_stock','refresh','partial','free_count'])
def test_unrelated_or_incomplete_ack_cannot_authorize_duplicate_purchase(fault):
    before=form();after=bought(before);v=after.values
    if fault=='gems':v['resources']['5']-=1
    elif fault=='double':v['resources']['1']-=12000
    elif fault=='loot':v['supply_inventory']['items']['124']-=1
    elif fault=='other_item':v['supply_inventory']['items']['99']+=1
    elif fault=='other_stock':v['vip_shop_stock']['Items']['2']['Amount']-=1
    elif fault=='refresh':v['vip_shop_stock']['Refresh']['Next']+=604800
    elif fault=='partial':v['supply_inventory']['ready']=False
    else:v['vip_shop_stock']['Items']['1']['Amount']+=1
    assert not PurchaseReceipt.capture(before,VipShopOptions()).matches(after)


@pytest.mark.parametrize('fault',['currency','soldout','price','reserve','locked','item','order','modal','quick','nan','reset','partial'])
def test_purchase_preflight_blocks_unconfirmed_or_unaffordable_offers(fault):
    state=form();v=state.values;row=v['vip_shop_stock']['Items']['1'];options=VipShopOptions()
    if fault=='currency':row['PriceType']=5
    elif fault=='soldout':row['Amount']=0
    elif fault=='price':row['Price']=12001
    elif fault=='reserve':options=VipShopOptions(reserve=1000000)
    elif fault=='locked':row['VipLvl']=13
    elif fault=='item':row['SubType']=125
    elif fault=='order':row['Weight']=3
    elif fault=='modal':v['views']['PopupInfoConfirm']=True
    elif fault=='quick':v['vip_shop_quick']=True
    elif fault=='nan':v['vip_shop_width']=float('nan')
    elif fault=='reset':v['vip_shop_stock']['Refresh']['Next']=120
    else:v['vip_shop_stock']['Items']['$truncated']=True
    with pytest.raises(NotReady):PurchaseReceipt.capture(state,options)


class Route:
    def __init__(self,monkeypatch):
        self.state=form();self.now=100.;self.inputs=[];self.cancelled=threading.Event()
        self.cancel_at_panel=False;self.bad_receipt=False;self.show(False)
        def navigate(*args,**kwargs):
            self.state.values['building_menu']['selected']={'id':'74','type':20,
                'buttons':['btn_CityPopUpInfo','btn_FunctionShop','btn_CityPopUpVIPShop']}
            return self.observe()
        monkeypatch.setattr('mirage.navigation.navigate_city',navigate)

    def show(self,visible):
        self.state.values.update(vip_shop_visible=visible,
            views={'MapHudPanel':True,**({'VIPShop':True,'CommonBackground':True} if visible else {})})

    def observe(self):
        self.now+=1;return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y))
        if (x,y)==(480,350):
            self.show(True)
            if self.cancel_at_panel:self.cancelled.set()
        elif (x,y)==(294,197):
            self.state=bought(self.state)
            if self.bad_receipt:self.state.values['supply_inventory']['items']['124']-=1
        elif (x,y)==(819,62):self.show(False)
        else:raise AssertionError((x,y))

    def run(self,settings=None):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            vip_shop_workflow(settings or {},verified=True),self.cancelled,instance_id='one',pid=10,player_id=20)


def test_route_buys_one_then_returns_city_and_sold_out_does_not_navigate(monkeypatch):
    game=Route(monkeypatch);after=game.run()
    assert CITY_HUD.matches(after) and game.inputs==[(480,350),(294,197),(819,62)]
    game.state.values['vip_shop_stock']['Items']['1']['Amount']=0
    game.inputs.clear();assert CITY_HUD.matches(game.run());assert not game.inputs


def test_cancellation_after_shop_open_prevents_spend(monkeypatch):
    game=Route(monkeypatch);game.cancel_at_panel=True
    with pytest.raises(Cancelled):game.run()
    assert (294,197) not in game.inputs


def test_ambiguous_purchase_is_not_retried(monkeypatch):
    game=Route(monkeypatch);game.bad_receipt=True
    with pytest.raises(WorkflowError,match='повтор запрещён'):game.run()
    assert game.inputs.count((294,197))==1


@pytest.mark.parametrize('settings',[{'item_id':True},{'item_id':148},{'max_price':0},{'reserve':-1}])
def test_profile_rejects_invalid_purchase_settings(settings):
    with pytest.raises(ValueError):Profile('one',tasks={'vip_shop':settings}).validate()


def test_snapshot_budget():
    from mirage.memory import PATHS
    assert len(PATHS|FIELDS)<=64
