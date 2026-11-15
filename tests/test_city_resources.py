from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.city_resources import CITY_RESOURCES
from mirage.memory import normalize_city_resources
from mirage.workflows import Cancelled, CITY_HUD, Engine, NotReady, WorkflowError
from test_rewards import Game


class ResourceCity(Game):
    def __init__(self):
        super().__init__()
        self.values.update(resources={"1":1000,"2":2000,"3":3000,"4":4000,"5":500,"6":0},
            supply_inventory={'ready':True,'items':{'1':1}},
            harvest_receipts={str(i):{"type":i,"value":i*1000,"incrValue":0,"leftTime":0} for i in range(1,5)},
            city_camera={"x":10.,"y":20.,"distance":200.,"moving":False},
            buildings={key:{"type":kind+1,"world_x":10.,"world_y":20.}
                       for key,kind in (("1",1),("2",1),("3",2))},
            city_resources={key:{"id":key,"type":kind+1,"rssType":kind,"rssValue":100,"rssProduceState":3,
                "gatherMin":10,"gatherLimit":100} for key,kind in (("1",1),("2",1),("3",2))})
        self.kind = 0
        self.delayed = None
        self.partial_balance_only = False
        self.observations_after_tap = 0
        self.server_adjustment = 0
        self.stuck_animation = False
        self.single=False;self.building=None

    def snapshot(self):
        if self.delayed is not None:
            self.observations_after_tap += 1
            if self.observations_after_tap == 3:
                kind,remaining,target=self.delayed
                if not self.partial_balance_only:
                    self.values["resources"][str(kind)] += remaining
                if not self.stuck_animation:
                    self.values["harvest_receipts"][str(kind)].update(value=target,incrValue=0,leftTime=0)
                self.delayed = None
        normalize_city_resources(self.values)
        return super().snapshot()

    def tap(self,x,y,*,hold_ms=0):
        assert (x,y) == (480,235)
        self.taps.append((x,y))
        rows = [row for key,row in self.values["city_resources"].items() if row["rssType"] == self.kind
            and (not self.single or key==self.building)]
        amount = sum(row["rssValue"] for row in rows)
        for row in rows:
            row.update(rssValue=0,rssProduceState=1)
        amount += self.server_adjustment
        previous=self.values["resources"][str(self.kind)]
        self.values["resources"][str(self.kind)] += amount//2
        self.values["harvest_receipts"][str(self.kind)].update(value=previous,incrValue=amount,leftTime=1920)
        self.delayed = (self.kind,amount-amount//2,previous+amount)
        self.observations_after_tap = 0


def run(game,monkeypatch,cancelled=None,allowed=lambda:True):
    def approach(input_device,observe,*args,building_id,**kwargs):
        game.kind = game.values["city_resources"][building_id]["rssType"]
        game.building=building_id
        state = observe()
        state.values["city_navigation_target"] = {"id":building_id,"point":[480,270],
            "camera":deepcopy(state.values["city_camera"])}
        return state
    monkeypatch.setattr("mirage.city_resources.navigate_city",approach)
    def clock():
        game.time += 1
        return game.time
    return Engine(game,game.snapshot,clock=clock,resolution=(960,540),allowed=allowed).execute(
        replace(CITY_RESOURCES,verified=True),cancelled or threading.Event(),instance_id="one",pid=10,player_id=20)


def test_harvest_waits_for_all_building_receipts_in_each_resource_group(monkeypatch):
    game = ResourceCity()
    after = run(game,monkeypatch)
    assert CITY_HUD.matches(after)
    assert after.values["resources"] == {"1":1200,"2":2100,"3":3000,"4":4000,"5":500,"6":0}
    assert len(game.taps) == 2
    assert after.values["city_resource_state"]["pending"] == 0


def test_vip_zero_single_building_harvest_collects_each_original_building_once(monkeypatch):
    game=ResourceCity();game.single=True;game.values['vip_level']=0
    after=run(game,monkeypatch)
    assert after.values['resources']=={'1':1200,'2':2100,'3':3000,'4':4000,'5':500,'6':0}
    assert after.values['city_resource_state']['pending']==0 and len(game.taps)==3


@pytest.mark.parametrize('revoke_permission',[False,True])
def test_stop_after_single_harvest_stops_observations_and_resume_never_recollects_it(monkeypatch,revoke_permission):
    game=ResourceCity();game.single=True;game.values['vip_level']=0
    cancelled=threading.Event();permission=[True];tap=game.tap;targets=[]
    def stopping_tap(*args,**kwargs):
        targets.append(game.building);tap(*args,**kwargs)
        if revoke_permission:permission[0]=False
        else:cancelled.set()
    game.tap=stopping_tap
    with pytest.raises(Cancelled):run(game,monkeypatch,cancelled,lambda:permission[0])
    assert len(game.taps)==1 and game.observations_after_tap==0
    # Resume during the animation must wait without sending another harvest.
    kind,_,total=game.delayed
    game.stuck_animation=True;game.tap=tap;cancelled.clear();permission[0]=True
    with pytest.raises(NotReady):run(game,monkeypatch,cancelled)
    assert len(game.taps)==1
    while game.delayed is not None:game.snapshot()
    game.values['harvest_receipts'][str(kind)].update(value=total,incrValue=0,leftTime=0)
    game.stuck_animation=False
    def resumed_tap(*args,**kwargs):
        targets.append(game.building);tap(*args,**kwargs)
    game.tap=resumed_tap
    after=run(game,monkeypatch,cancelled)
    assert len(targets)==len(set(targets))==3 and CITY_HUD.matches(after)
    assert after.values['resources']=={'1':1200,'2':2100,'3':3000,'4':4000,'5':500,'6':0}


@pytest.mark.parametrize('fault',['foreign_currency','inventory','unrelated_credit'])
def test_harvest_receipt_rejects_other_asset_changes_and_unrelated_extra_credit(monkeypatch,fault):
    game=ResourceCity();tap=game.tap
    def changed(*args,**kwargs):
        tap(*args,**kwargs)
        if fault=='foreign_currency':game.values['resources']['4']-=1
        elif fault=='inventory':game.values['supply_inventory']['items']['1']-=1
    if fault=='unrelated_credit':game.server_adjustment=500
    else:game.tap=changed
    with pytest.raises(WorkflowError):run(game,monkeypatch)
    assert len(game.taps)==1


def test_empty_buildings_with_only_partial_balance_do_not_count_as_a_complete_harvest(monkeypatch):
    game = ResourceCity()
    game.partial_balance_only = True
    with pytest.raises(WorkflowError,match="не подтверждено"):
        run(game,monkeypatch)
    assert len(game.taps) == 1


def test_completed_server_receipt_accepts_one_integer_unit_per_building_of_projection_rounding(monkeypatch):
    game=ResourceCity()
    game.server_adjustment=-1
    after=run(game,monkeypatch)
    assert after.values['resources']['1']==1199 and after.values['resources']['2']==2099
    assert len(game.taps)==2


@pytest.mark.parametrize('failure',['large_shortfall','unfinished_animation'])
def test_completed_receipts_cannot_hide_large_underpayment_or_an_unfinished_animation(monkeypatch,failure):
    game=ResourceCity()
    if failure=='large_shortfall':game.server_adjustment=-10
    else:game.stuck_animation=True
    with pytest.raises(WorkflowError):run(game,monkeypatch)
    assert len(game.taps)==1


@pytest.mark.parametrize('corruption',['missing','wrong_type','boolean_value','not_idle'])
def test_unknown_or_busy_server_receipt_blocks_a_new_harvest(monkeypatch,corruption):
    game=ResourceCity()
    row=game.values['harvest_receipts']['1']
    if corruption=='missing':del game.values['harvest_receipts']['1']
    elif corruption=='wrong_type':row['type']=2
    elif corruption=='boolean_value':row['value']=True
    else:row.update(incrValue=1,leftTime=100)
    with pytest.raises(NotReady):run(game,monkeypatch)
    assert not game.taps


@pytest.mark.parametrize("corruption",["wrong_kind","negative_amount","unknown_state","truncated","wrong_world"])
def test_unconfirmed_city_production_blocks_all_input(monkeypatch,corruption):
    game = ResourceCity()
    if corruption == "wrong_kind": game.values["city_resources"]["1"]["rssType"] = 4
    elif corruption == "negative_amount": game.values["city_resources"]["1"]["rssValue"] = -1
    elif corruption == "unknown_state": game.values["city_resources"]["1"]["rssProduceState"] = 7
    elif corruption == "truncated": game.values["city_resources"]["$truncated"] = True
    else: game.values["buildings"]["1"]["world_x"] = None
    with pytest.raises(NotReady):
        run(game,monkeypatch)
    assert not game.taps
