from copy import deepcopy
import threading

import pytest

from mirage.vip_daily import BoxReceipt, PointReceipt, VIP_DAILY
from mirage.workflows import CITY_HUD, Cancelled, NotReady, WorkflowError
from test_rewards import Game, execute


def test_vip_daily_dispatcher_includes_the_new_level_zero_route():
    from mirage.workflows import workflow_for
    assert workflow_for('vip_reward',{}) is VIP_DAILY


class VipZero(Game):
    def __init__(self):
        super().__init__();self.values.update(vip_level=0,vip_shown_level=0,vip_experience=40,vip_login_days=1,
            vip_daily_points={'Day':2,'Point':60},vip_daily_config={'ready':True,'level':0,'rows':{'0':{'FreeGiftReward':9001}}},
            vip_daily_loot={'1':{'ID':9001,'Type':2,'SubType':129,'Value':1},
                '2':{'ID':9001,'Type':2,'SubType':1,'Value':1},'3':{'ID':9001,'Type':2,'SubType':7,'Value':1}},
            supply_inventory={'ready':True,'items':{'1':1,'7':1,'129':11,'49':1}},
            resources={'1':1000,'2':1000,'3':1000,'4':1000,'5':400,'6':0,'33':10})

    def tap(self,x,y,*,hold_ms=0):
        super().tap(x,y,hold_ms=hold_ms)
        if (x,y)==(765,152):self.values['vip_experience']+=60;self.values['vip_login_days']+=1
        elif (x,y)==(705,267):
            for row in self.values['vip_daily_loot'].values():
                key=str(row['SubType']);items=self.values['supply_inventory']['items'];items[key]=items.get(key,0)+row['Value']


@pytest.mark.parametrize('points,box',[(True,True),(True,False),(False,True),(False,False)])
def test_vip0_collects_only_available_free_rewards_with_full_asset_receipts(points,box):
    game=VipZero();game.values.update(vip_points_available=points,vip_box_available=box)
    before=deepcopy(game.values);after=execute(game,VIP_DAILY)
    assert CITY_HUD.matches(after) and after.values['resources']==before['resources']
    assert after.values['vip_experience']==40+60*points
    assert after.values['vip_login_days']==1+int(points)
    assert after.values['supply_inventory']['items']==({'1':2,'7':2,'129':12,'49':1} if box else before['supply_inventory']['items'])
    assert game.taps.count((765,152))==int(points) and game.taps.count((705,267))==int(box)


def test_vip0_cancellation_after_box_resumes_without_repeating_either_claim():
    game=VipZero();stop=threading.Event();game.cancel_after_box=stop
    with pytest.raises(Cancelled):execute(game,VIP_DAILY,stop)
    stop.clear();game.cancel_after_box=None
    assert CITY_HUD.matches(execute(game,VIP_DAILY,stop))
    assert game.taps.count((765,152))==game.taps.count((705,267))==1


def test_vip12_keeps_the_existing_verified_route():
    game=Game();assert CITY_HUD.matches(execute(game,VIP_DAILY))
    assert game.taps==[(108,46),(765,152),(480,500),(705,267),(480,500),(818,62)]


@pytest.mark.parametrize('fault',['day','points','reward_id','paid_box','currency','unrelated_item'])
def test_native_configuration_and_all_assets_are_required(fault):
    game=VipZero();game.values['vip_visible']=True;s=game.snapshot()
    if fault=='day':s.values['vip_daily_points']['Day']=1
    elif fault=='points':s.values['vip_daily_points']['Point']=0
    elif fault=='reward_id':s.values['vip_daily_loot']['1']['ID']=9002
    elif fault=='paid_box':s.values['vip_daily_config']['rows']['0']['FreeGiftReward']=9000000
    if fault in ('day','points'):
        with pytest.raises(NotReady):PointReceipt.capture(s)
    elif fault in ('reward_id','paid_box'):
        with pytest.raises(NotReady):BoxReceipt.capture(s)
    else:
        receipt=PointReceipt.capture(s);game.tap(765,152,hold_ms=100);after=game.snapshot()
        if fault=='currency':after.values['resources']['33']-=1
        else:after.values['supply_inventory']['items'].pop('49')
        assert not receipt.matches(after)


def test_wrong_point_grant_stops_before_box_and_never_repeats():
    game=VipZero();tap=game.tap
    def corrupt(*args,**kwargs):
        tap(*args,**kwargs)
        if args==(765,152):game.values['vip_experience']-=1
    game.tap=corrupt
    with pytest.raises(WorkflowError,match='повтор запрещён'):execute(game,VIP_DAILY)
    assert game.taps.count((765,152))==1 and (705,267) not in game.taps
