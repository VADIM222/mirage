from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.materials import MaterialsReceived, OrderReceived, materials_workflow
from mirage.memory import normalize_materials
from mirage.model import MATERIALS, Profile
from mirage.workflows import CITY_HUD, Cancelled, NotReady, WorkflowError
from test_rewards import Game, execute


class Materials(Game):
    def __init__(self):
        super().__init__()
        self.values.update(server_time=1000,buildings={"92":{"type":31}},material_items_known=True,
            resources={str(i):10000 for i in range(1,7)},
            material_orders={str(i):{"Index":i,"State":1,"endTime":1000} for i in range(1,6)},
            material_ui={"known":True,"visible":True,"building_id":"92","back_to_forge":False,
                "left":1,"top":1,"list_type":1,"capacity":5,"batch":15,"recipes":{
                    str(i):{"ID":item,"itemId":item,"Order":i,"ProduceTime":720,"Quality":1,"CLASS":kind}
                    for i,(item,kind) in enumerate(((412,2),(413,3),(417,7),(414,4)),1)}},
            building_menu={"known":True,"selected":None},city_camera={"x":1.,"y":2.,"distance":200})
        for item in MATERIALS:self.values[f"material_item_{item}"]={"itemId":item,"itemCount":100}
        self.after_start = lambda:None
        self.wrong_recipe = False

    def snapshot(self):
        normalize_materials(self.values)
        result = super().snapshot()
        if result.values["material_ui"]["visible"]:
            result.values["views"].update(EquipMaterial=True,CommonBackground=True)
        return result

    def tap(self,x,y,*,hold_ms=0):
        self.taps.append((x,y))
        ui = self.values["material_ui"]
        if (x,y)==(818,62):ui["visible"]=False
        elif (x,y)==(75,135):ui.update(left=1,top=1,list_type=1)
        elif y==175 and x in (572,642,711,782):
            assert ui["left"]==ui["top"]==ui["list_type"]==1
            item={572:412,642:413,711:417,782:414}[x]
            if self.wrong_recipe:item=413 if item==412 else 412
            orders=self.values["material_orders"]
            key=next(k for k,v in orders.items() if v["State"]==1)
            state=2 if any(v["State"]==3 for v in orders.values()) else 3
            orders[key]={"Index":int(key),"State":state,"Count":15,"ItemId":item,"endTime":10801000}
            if state==3:orders[key]["TotalTime"]=10800000
            self.after_start()
        elif (x,y)==(480,270):
            orders=self.values["material_orders"]
            for key,row in list(orders.items()):
                if row['State']==4:
                    self.values[f"material_item_{row['ItemId']}"]["itemCount"]+=row['Count']
                    orders[key]={"Index":int(key),"State":1,"endTime":1000}
        else:raise AssertionError(f"Unexpected material input {(x,y)}")


@pytest.mark.parametrize("item",list(MATERIALS))
def test_one_ordinary_order_is_confirmed_without_spending_currency_and_returns_to_city(item):
    game=Materials()
    result=execute(game,materials_workflow({"item_id":item}))
    assert CITY_HUD.matches(result)
    assert result.values["material_orders"]["1"]["ItemId"]==item
    assert result.values["material_orders"]["1"]["Count"]==15
    assert result.values["resources"]=={str(i):10000 for i in range(1,7)}
    assert len(game.taps)==2


def test_reached_order_limit_and_retry_after_cancel_do_not_duplicate_production():
    game=Materials()
    cancelled=threading.Event()
    game.after_start=cancelled.set
    workflow=materials_workflow({"max_orders":1})
    with pytest.raises(Cancelled):execute(game,workflow,cancelled)
    game.after_start=lambda:None
    assert CITY_HUD.matches(execute(game,workflow))
    assert game.taps.count((572,175))==1
    assert CITY_HUD.matches(execute(game,workflow))
    assert game.taps.count((572,175))==1


def test_compose_tab_is_switched_to_production_before_a_new_order():
    game=Materials()
    game.values["material_ui"].update(left=2,list_type=2)
    execute(game,materials_workflow({}))
    assert game.taps==[(75,135),(572,175),(818,62)]


@pytest.mark.parametrize("corruption",["gems","inventory","recipe"])
def test_a_wrong_recipe_or_any_item_currency_spending_never_confirms_an_order(corruption):
    game=Materials()
    if corruption=="recipe":game.wrong_recipe=True
    elif corruption=="gems":game.after_start=lambda:game.values["resources"].update({"5":9999})
    else:game.after_start=lambda:game.values["material_item_412"].update(itemCount=99)
    with pytest.raises(WorkflowError,match="не подтверждён"):
        execute(game,materials_workflow({}))
    assert game.taps==[(572,175)]


@pytest.mark.parametrize("corruption",["unknown_capture","capacity","changed_recipe"])
def test_unknown_ui_layout_or_recipe_never_authorizes_a_production_click(corruption):
    game=Materials()
    ui=game.values["material_ui"]
    if corruption=="unknown_capture":ui["known"]=False
    elif corruption=="capacity":ui["capacity"]=6
    else:ui["recipes"]["1"]["ID"]=999
    if corruption=="unknown_capture":
        with pytest.raises(NotReady):execute(game,materials_workflow({}))
    else:
        with pytest.raises(WorkflowError):execute(game,materials_workflow({}))
    assert not any(y==175 for x,y in game.taps)


def test_collection_confirms_a_finished_slot_after_the_server_already_advanced_the_queue(monkeypatch):
    game=Materials()
    game.values["material_ui"]["visible"]=False
    game.values["material_orders"]["1"]={"Index":1,"State":3,"ItemId":413,"Count":15,
        "endTime":10801000,"TotalTime":10800000}
    game.values["material_orders"]["5"]={"Index":5,"State":4,"ItemId":412,"Count":15,"endTime":900}
    def navigate(input_device,observe,cancelled,clock,kind,allowed,**kwargs):
        assert kind==31 and kwargs=={"building_id":"92","select":False}
        result=observe()
        result.values["city_navigation_target"]={"point":[480,270]}
        return result
    monkeypatch.setattr("mirage.materials.navigate_city",navigate)
    result=execute(game,materials_workflow({"max_orders":1}))
    assert CITY_HUD.matches(result)
    assert result.values["material_item_412"]["itemCount"]==115
    assert result.values["material_orders"]["1"]["State"]==3
    assert result.values["material_orders"]["5"]["State"]==1
    assert game.taps==[(480,270)]


@pytest.mark.parametrize("settings",[{"item_id":True},{"item_id":999},{"max_orders":0},{"max_orders":6}])
def test_invalid_material_options_cannot_be_saved(settings):
    with pytest.raises(ValueError):Profile("one",tasks={"materials":settings}).validate()


@pytest.mark.parametrize("corruption",["missing_slot","boolean_state","unknown_item","wrong_inventory","queued_without_active","timer"])
def test_partial_or_inconsistent_material_orders_do_not_become_ready(corruption):
    game=Materials()
    values=game.values
    if corruption=="missing_slot":del values["material_orders"]["5"]
    elif corruption=="boolean_state":values["material_orders"]["1"]["State"]=True
    elif corruption=="wrong_inventory":values["material_item_412"]["itemId"]=413
    else:
        values["material_orders"]["1"]={"Index":1,"State":2 if corruption=="queued_without_active" else 3,
            "ItemId":999 if corruption=="unknown_item" else 412,"Count":15,"endTime":float("nan"),"TotalTime":10800000}
    normalize_materials(values)
    assert not values["material_state"]["ready"]


def finished_materials():
    game=Materials()
    game.values['material_orders']={
        '1':{'Index':1,'State':3,'ItemId':413,'Count':15,'endTime':10801000,'TotalTime':10800000},
        '2':{'Index':2,'State':2,'ItemId':417,'Count':15,'endTime':900},
        '3':{'Index':3,'State':2,'ItemId':414,'Count':15,'endTime':900},
        '4':{'Index':4,'State':4,'ItemId':412,'Count':15,'endTime':900},
        '5':{'Index':5,'State':4,'ItemId':412,'Count':15,'endTime':900}}
    return game


def test_completed_orders_are_counted_as_used_and_duplicate_materials_accumulate():
    state=finished_materials().snapshot().values['material_state']
    assert state['ready'] and state['used']==5 and state['pending']=={'412':30} and not state['free']


def test_collection_receipt_uses_exact_finished_units_and_preserves_unfinished_orders():
    game=finished_materials()
    receipt=MaterialsReceived.capture(game.snapshot())
    game.tap(480,270)
    assert receipt.matches(game.snapshot())
    # UI indices can change; receipt identity is the item/count ledger, not a slot.
    orders=game.values['material_orders']
    orders['1'],orders['2']=orders['2'],orders['1']
    orders['1']['Index']=1;orders['2']['Index']=2
    assert receipt.matches(game.snapshot())


@pytest.mark.parametrize('corruption',['partial_inventory','lost_waiting_order','gems'])
def test_collection_never_confirms_lost_materials_waiting_orders_or_currency(corruption):
    game=finished_materials()
    receipt=MaterialsReceived.capture(game.snapshot())
    game.tap(480,270)
    if corruption=='partial_inventory':game.values['material_item_412']['itemCount']-=15
    elif corruption=='lost_waiting_order':game.values['material_orders']['2']={'Index':2,'State':1}
    else:game.values['resources']['5']-=1
    assert not receipt.matches(game.snapshot())


@pytest.mark.parametrize('mode',['expired_active','future_finished'])
def test_predicted_finish_without_a_valid_server_completed_state_never_authorizes_collection(mode):
    game=finished_materials()
    if mode=='expired_active':game.values['material_orders']['1']['endTime']=900
    else:game.values['material_orders']['5']['endTime']=1100
    assert not game.snapshot().values['material_state']['ready']
