from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.model import Snapshot
from mirage.shield import FIELDS, ShieldReceipt, shield_workflow
from mirage.workflows import CITY_HUD, Cancelled, Engine, NotReady, WorkflowError


def form():
    return Snapshot('one',10,20,100.,'1.1.12.20',{'server_time':100000,
        'hud_visible':True,'hud_menu':False,'in_city':True,'city_enabled':True,
        'queue_panel':{'known':True,'visible':False},'city_selection_known':True,'city_selection':None,
        'views':{'MapHudPanel':True,'ItemBag':True,'CommonBackground':True},
        'resources':{str(i):100000 for i in range(1,7)},'supply_inventory':{'ready':True,'items':{'49':13,'50':1}},
        'shield':dict.fromkeys(('shieldSystemEndTime','shieldItemEndTime','shieldEndTime',
            'shieldSystemStartTime','shieldItemStartTime'),0),'shield_pk_id':17202,'shield_fever':None,
        'shield_bag':True,'shield_tab':'Battle','shield_count':1,'shield_disabled':False,
        'shield_selected':{'itemId':49,'itemCount':13,'expireTime':0},
        'shield_list':{'4':{'itemId':49,'itemCount':13,'expireTime':0}}})


def applied(s):
    s=deepcopy(s);v=s.values;v['supply_inventory']['items']['49']-=1
    v['shield'].update(shieldItemStartTime=100000,shieldItemEndTime=28900000,shieldEndTime=28900000)
    return s


def test_receipt_requires_one_inventory_item_and_exact_eight_hours():
    s=form();assert ShieldReceipt.capture(s).matches(applied(s))


@pytest.mark.parametrize('fault',['active','fever','partial','missing_fever','count','wrong_item','disabled','modal','clock'])
def test_preflight_blocks_unconfirmed_use(fault):
    s=form();v=s.values
    if fault=='active':v['shield']['shieldSystemEndTime']=200000
    elif fault=='fever':v['shield_fever']={'1':{'BuffId':17202,'Expire':200}}
    elif fault=='partial':v['shield']['$truncated']=True
    elif fault=='missing_fever':del v['shield_fever']
    elif fault=='count':v['shield_count']=True
    elif fault=='wrong_item':v['shield_selected']['itemId']=50
    elif fault=='disabled':v['shield_disabled']=True
    elif fault=='modal':v['views']['CommonMsgBox']=True
    else:v['server_time']=float('nan')
    with pytest.raises(NotReady):ShieldReceipt.capture(s)


@pytest.mark.parametrize('fault',['double','gems','duration','start','system','inventory','missing'])
def test_ambiguous_ack_cannot_authorize_second_use(fault):
    s=form();after=applied(s);v=after.values
    if fault=='double':v['supply_inventory']['items']['49']-=1
    elif fault=='gems':v['resources']['5']-=1
    elif fault=='duration':v['shield']['shieldItemEndTime']+=1000
    elif fault=='start':v['shield']['shieldItemStartTime']=1
    elif fault=='system':v['shield']['shieldSystemEndTime']=28900000
    elif fault=='inventory':v['supply_inventory']['items']['50']+=1
    else:v['supply_inventory']['ready']=False
    assert not ShieldReceipt.capture(s).matches(after)


class Route:
    def __init__(self):
        self.state=form();self.now=100.;self.inputs=[];self.cancelled=threading.Event()
        self.cancel_on_selection=False;self.bad_ack=False;self.show(False)
        self.state.values['shield_selected']=None

    def show(self,visible):
        v=self.state.values;v['shield_bag']=visible
        v['views']={'MapHudPanel':True,**({'ItemBag':True,'CommonBackground':True} if visible else {})}

    def observe(self):
        self.now+=1;return replace(deepcopy(self.state),captured_at=self.now)

    def tap(self,x,y,**kwargs):
        self.inputs.append((x,y));v=self.state.values
        if (x,y)==(924,505):v['hud_menu']=not v['hud_menu']
        elif (x,y)==(625,505):self.show(True)
        elif (x,y)==(410,62):v['shield_tab']='Battle'
        elif (x,y)==(530,155):
            v['shield_selected']={'itemId':49,'itemCount':13,'expireTime':0}
            if self.cancel_on_selection:self.cancelled.set()
        elif (x,y)==(725,466):
            self.state=applied(self.state)
            if self.bad_ack:self.state.values['resources']['5']-=1
        elif (x,y)==(835,62):self.show(False)
        else:raise AssertionError((x,y))

    def run(self):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            shield_workflow({},verified=True),self.cancelled,instance_id='one',pid=10,player_id=20)


def test_full_route_does_not_renew_an_active_shield():
    game=Route();assert CITY_HUD.matches(game.run())
    assert game.inputs.count((725,466))==1
    before=len(game.inputs);assert CITY_HUD.matches(game.run());assert len(game.inputs)==before


def test_stop_before_use_and_uncertain_ack_never_repeat_spend():
    game=Route();game.cancel_on_selection=True
    with pytest.raises(Cancelled):game.run()
    assert (725,466) not in game.inputs
    game=Route();game.bad_ack=True
    with pytest.raises(WorkflowError,match='повтор запрещён'):game.run()
    assert game.inputs.count((725,466))==1


def test_snapshot_budget():
    from mirage.memory import PATHS
    assert len(PATHS|FIELDS)<=64
