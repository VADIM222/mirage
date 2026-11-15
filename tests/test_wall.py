import threading

import pytest

from mirage.wall import RepairReceived, normalize_wall, repair_wall_workflow
from mirage.workflows import CITY_HUD, Cancelled, NotReady, WorkflowError
from test_rewards import Game, execute


class Wall(Game):
    def __init__(self):
        super().__init__()
        self.values.update(server_time=1000000,resources={str(i):10000 for i in range(1,7)},
            buildings={"17":{"type":6,"lv":25,"world_source":"gate_collider","world_x":8000.,"world_y":19000.}},
            wall={"durability":36728,"durabilityMax":40000,"state":1,"speed":0,"repairCDEndTime":0},
            wall_ui={"known":True,"visible":True,"editing":False,"building_id":"17"},
            building_menu={"known":True,"selected":None})
        self.after_repair=lambda:None
        self.gain=500

    def snapshot(self):
        normalize_wall(self.values)
        state=super().snapshot()
        if state.values["wall_ui"]["visible"]:
            state.values["views"].update(CityUICityWall=True,CommonBackground=True)
        return state

    def tap(self,x,y,*,hold_ms=0):
        assert hold_ms==100
        self.taps.append((x,y))
        if (x,y)==(627,425):
            wall=self.values["wall"]
            wall.update(durability=min(40000,wall["durability"]+self.gain),repairCDEndTime=2800000)
            self.after_repair()
        elif (x,y)==(818,62):self.values["wall_ui"]["visible"]=False
        elif (x,y)==(520,300):self.values["wall_ui"]["visible"]=True
        else:raise AssertionError(f"Unexpected wall input {(x,y)}")


def test_free_repair_confirms_exact_durability_and_timer_then_returns_to_city():
    game=Wall()
    state=execute(game,repair_wall_workflow({}))
    assert CITY_HUD.matches(state) and state.values["wall"]["durability"]==37228
    assert game.taps==[(627,425),(818,62)]
    execute(game,repair_wall_workflow({}))
    assert game.taps==[(627,425),(818,62)]


def test_full_gate_and_cooldown_never_press_repair():
    for wall in ({"durability":40000},{"repairCDEndTime":1000001}):
        game=Wall()
        game.values["wall"].update(wall)
        execute(game,repair_wall_workflow({}))
        assert game.taps==[(818,62)]
        execute(game,repair_wall_workflow({}))
        assert game.taps==[(818,62)]


def test_cancel_after_applied_repair_resumes_without_a_second_repair():
    game=Wall()
    cancelled=threading.Event()
    game.after_repair=cancelled.set
    with pytest.raises(Cancelled):execute(game,repair_wall_workflow({}),cancelled)
    game.after_repair=lambda:None
    assert CITY_HUD.matches(execute(game,repair_wall_workflow({})))
    assert game.taps==[(627,425),(818,62)]


@pytest.mark.parametrize("corruption",["boolean","wrong_gate","invalid_coords","burning","speed","wrong_max","partial","currency_unknown"])
def test_unknown_or_burning_wall_never_allows_gameplay(corruption):
    game=Wall()
    values=game.values
    if corruption=="boolean":values["wall"]["durability"]=True
    elif corruption=="wrong_gate":values["buildings"]["17"]["world_source"]="layout"
    elif corruption=="invalid_coords":values["buildings"]["17"]["world_x"]=float("nan")
    elif corruption=="burning":values["wall"]["state"]=2
    elif corruption=="speed":values["wall"]["speed"]=-1
    elif corruption=="wrong_max":values["wall"]["durabilityMax"]=45000
    elif corruption=="partial":del values["wall"]["repairCDEndTime"]
    else:del values["resources"]["5"]
    with pytest.raises(NotReady):execute(game,repair_wall_workflow({}))
    assert game.taps==[]


@pytest.mark.parametrize("corruption",["editing","unknown","wrong_owner"])
def test_unknown_ui_and_garrison_editing_block_repair(corruption):
    game=Wall()
    if corruption=="editing":game.values["wall_ui"]["editing"]=True
    elif corruption=="unknown":game.values["wall_ui"]["known"]=False
    else:game.values["wall_ui"]["building_id"]="99"
    with pytest.raises(NotReady):execute(game,repair_wall_workflow({}))
    assert game.taps==[]


@pytest.mark.parametrize("corruption",["gems","wrong_gain","timer"])
def test_wrong_repair_receipts_never_retry_the_action(corruption):
    game=Wall()
    if corruption=="gems":game.after_repair=lambda:game.values["resources"].update({"5":9999})
    elif corruption=="wrong_gain":game.gain=1000
    else:game.after_repair=lambda:game.values["wall"].update(repairCDEndTime=2000000)
    with pytest.raises(WorkflowError):execute(game,repair_wall_workflow({}))
    assert game.taps==[(627,425)]


def test_repair_near_maximum_is_capped_at_full_durability():
    game=Wall()
    game.values["wall"]["durability"]=39999
    state=execute(game,repair_wall_workflow({}))
    assert state.values["wall"]["durability"]==40000


def test_navigation_requires_the_verified_gate_menu(monkeypatch):
    game=Wall()
    game.values["wall_ui"]["visible"]=False
    def navigate(device,observe,cancelled,clock,kind,allowed,**kwargs):
        assert kind==6 and kwargs=={"building_id":"17"}
        game.values["building_menu"]["selected"]={"id":"17","type":6,
            "buttons":["btn_CityPopUpInfo","btn_FunctionCityWall"]}
        return observe()
    monkeypatch.setattr("mirage.wall.navigate_city",navigate)
    state=execute(game,repair_wall_workflow({}))
    assert CITY_HUD.matches(state)
    assert game.taps==[(520,300),(627,425),(818,62)]
