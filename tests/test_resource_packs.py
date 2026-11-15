from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.model import Snapshot
from mirage.resource_packs import PackReceipt, bag_point, replenish
from mirage.workflows import CITY_HUD, Cancelled, NotReady, WorkflowError


def state():
    configs={str(i):dict(ID=i,OpType=1,SubType=2,Target=k,OpValue=10000,Use=1,LastTime=0,ChangeID=0)
        for i,k in ((1,1),(7,2))}
    return Snapshot('one',10,20,100.,'1.1.12.20',dict(server_time=100000,
        resources={str(i):0 for i in range(1,7)},supply_inventory={'ready':True,'items':{'1':6,'7':6}},
        views={'MapHudPanel':True,'ItemBag':True,'CommonBackground':True},in_city=True,
        hud_visible=True,hud_menu=True,city_enabled=True,vip_visible=False,
        queue_panel={'known':True,'visible':False},city_selection_known=True,city_selection=None,
        hud_functions={'ready':True,'slots':{'3':3,'4':1,'5':2,'8':4}},
        resource_pack_ui={'visible':True,'tab':'Res','count':1,'disabled':False,'progress':False,
            'configs':configs,'selected':{'itemId':1,'itemCount':6,'expireTime':0},
            'rows':{'1':{'itemId':1},'2':{'itemId':7}}}))


@pytest.mark.parametrize('fault',['amount','expire','gem','config','disabled','modal','partial'])
def test_pack_rejects_ambiguous_source_or_nonstandard_use(fault):
    s=state();p=s.values['resource_pack_ui']
    if fault=='amount':p['count']=2
    elif fault=='expire':p['selected']['expireTime']=1
    elif fault=='gem':p['selected']['itemId']=26
    elif fault=='config':p['configs']['1']['Target']=5
    elif fault=='disabled':p['disabled']=True
    elif fault=='modal':s.values['views']['ResBuying']=True
    else:s.values['supply_inventory']['items']['$truncated']=True
    with pytest.raises(NotReady):PackReceipt.capture(s,1)


def test_pack_ack_requires_exact_one_item_and_one_currency_credit():
    s=state();r=PackReceipt.capture(s,1)
    s.values['supply_inventory']['items']['1']-=1;s.values['resources']['1']+=10000
    assert r.matches(s)
    s.values['resources']['5']+=1
    assert not r.matches(s)


def test_bag_slot_uses_current_userdata_mapping_and_rejects_alias_collisions():
    s=state();assert bag_point(s)==(699,505)
    s.values['hud_functions']['slots']['8']=3
    with pytest.raises(NotReady):bag_point(s)


class Route:
    def __init__(self):
        self.state=state();self.now=100.;self.inputs=[];self.cancelled=threading.Event();self.bad=False;self.stop=False;self.stop_on_use=False

    def observe(self):
        self.now+=1;return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y));v=self.state.values;p=v['resource_pack_ui']
        if y==155:
            item={170:1,290:7}[x];p['selected']={'itemId':item,'itemCount':v['supply_inventory']['items'][str(item)],'expireTime':0}
            if self.stop:self.cancelled.set()
        elif (x,y)==(725,466):
            item=p['selected']['itemId'];v['supply_inventory']['items'][str(item)]-=1
            p['selected']['itemCount']-=1;v['resources'][str({1:1,7:2}[item])]+=9999 if self.bad else 10000
            if self.stop_on_use:self.cancelled.set()
        elif (x,y)==(835,62):p['visible']=False;v['views']={'MapHudPanel':True}
        elif (x,y)==(924,505):v['hud_menu']=False
        else:raise AssertionError((x,y))

    def run(self,minimum,max_packs=4):
        return replenish(self,self.observe,self.cancelled,lambda:self.now,lambda:True,minimum,max_packs)


def test_bounded_replenishment_uses_only_shortfall_then_returns_city():
    g=Route();after=g.run({'1':15000,'2':10000})
    assert CITY_HUD.matches(after) and after.values['building_resource_packs_used']==3
    assert g.inputs.count((725,466))==3
    assert after.values['resources']['1']==20000 and after.values['resources']['2']==10000
    g=Route();after=g.run({'1':50000,'2':50000},2)
    assert after.values['building_resource_packs_used']==2 and after.values['resources']['2']==0


def test_insufficient_total_stock_does_not_consume_any_resource_pack():
    g=Route();after=g.run({'1':70000,'2':10000})
    assert CITY_HUD.matches(after) and (725,466) not in g.inputs


def test_partial_ack_does_not_retry_and_stop_before_use_spends_nothing():
    g=Route();g.bad=True
    with pytest.raises(WorkflowError,match='повтор'):g.run({'1':10000})
    assert g.inputs.count((725,466))==1
    g=Route();g.stop=True;g.state.values['resource_pack_ui']['selected']['itemId']=7
    with pytest.raises(Cancelled):g.run({'1':10000})
    assert (725,466) not in g.inputs


def test_stop_after_commit_resumes_from_current_balance_without_a_second_pack():
    g=Route();g.stop_on_use=True
    with pytest.raises(Cancelled):g.run({'1':10000})
    assert g.inputs.count((725,466))==1
    g.cancelled.clear();g.stop_on_use=False;after=g.run({'1':10000})
    assert CITY_HUD.matches(after) and g.inputs.count((725,466))==1
