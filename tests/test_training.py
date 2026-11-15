from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.memory import normalize_training_form
from mirage.model import Profile, TrainingOptions
from mirage.training import FormMatches, StartReceipt, TierAvailable, training_workflow
from mirage.workflows import Cancelled, CITY_HUD, Engine, NotReady, Tap, WorkflowError
from test_rewards import Game, execute


class Trainer(Game):
    def __init__(self):
        super().__init__()
        self.values.update(resources={"1":50000,"2":50000,"3":50000,"4":50000,"5":1000},
            buildings={str(i):{"type":t} for i,t in enumerate((9,11,10,12),1)},
            training_layout_ready=True, training_keyboard_owned=True,training_menu_type=None,
            training_keyboard={"visible":False,"first":True,"text":"2000"},
            training_form={"visible":False},
            training_summary={"ready":True,"completed":0,"troops":{"1":10,"2":20,"3":30,"4":40},
                "rows":{str(i):{"building_id":str(i),"focused":False,"pending":False,"status":"Free",
                    "unit_id":None,"from_unit_id":None,"count":0} for i in range(1,5)}})
        self.focus = 0
        self.changed_gems = False
        self.on_start = lambda: None

    def snapshot(self):
        state = super().snapshot()
        for key,name in (("training_form","TrainTroops"),("training_keyboard","NumericKeyboardPanel")):
            if state.values[key]["visible"]:
                state.values["views"][name] = True
                state.values["views"]["CommonBackground"] = True
        return state

    def tap(self,x,y,*,hold_ms=0):
        if (x,y) in ((108,46),(818,62),(248,275)):
            return super().tap(x,y,hold_ms=hold_ms)
        self.taps.append((x,y))
        form = self.values["training_form"]
        keyboard = self.values["training_keyboard"]
        rows = self.values["training_summary"]["rows"]
        if (x,y) == (24,102):
            self.values["queue_panel"]["visible"] = True
        elif x == 110 and y in (150,200,250,300):
            self.focus = (y-150)//50+1
            for i,row in rows.items():
                row["focused"] = int(i) == self.focus
        elif (x,y) == (480,270):
            self.values["city_selection"] = str(self.focus)
            self.values["training_menu_type"] = self.focus
        elif (x,y) == (525,344):
            form.update(visible=True,ready=True,building_id=str(self.focus),building_type=(9,11,10,12)[self.focus-1],
                unit_id=(1,3,2,4)[self.focus-1],tier=1,count=2000,max_count=2000,promoting=False,running=False,info=False,
                config={"Id":(1,3,2,4)[self.focus-1],"Type":(1,3,2,4)[self.focus-1],"Tier":1,
                    "BuildingType":(9,11,10,12)[self.focus-1],"Time":15,"Food":50,"Wood":50,"Stone":0,"Coin":0},
                tiers={str(i):{"known":True,"locked":i==5,"unit_id":(1,3,2,4)[self.focus-1]+4*(i-1)} for i in range(1,6)})
            normalize_training_form(self.values)
            self.values["city_selection"] = None
        elif (x,y) == (770,317):
            keyboard.update(visible=True,first=True,text=str(form["count"]))
        elif (x,y) == (825,247):
            form["count"] = int(keyboard["text"])
            normalize_training_form(self.values)
            keyboard["visible"] = False
        elif keyboard["visible"]:
            positions = {(711,247):"0"}
            positions.update({((683,739,795)[(i-1)%3],(100,149,198)[(i-1)//3]):str(i) for i in range(1,10)})
            digit = positions[(x,y)]
            keyboard["text"] = digit if keyboard["first"] else keyboard["text"]+digit
            keyboard["first"] = False
        elif (x,y) == (823,62):
            form["visible"] = False
        elif (x,y) == (738,443):
            rows[str(self.focus)].update(status="InProgress",unit_id=form["unit_id"],from_unit_id=0,count=form["count"])
            for resource,amount in form["cost"].items():
                self.values["resources"][resource] -= amount
            if self.changed_gems:
                self.values["resources"]["5"] -= 1
            form["visible"] = False
            self.on_start()
        else:
            raise AssertionError(f"Unexpected training input {x,y}")


def test_all_types_confirm_exact_quantity_and_start_once_without_instant_input():
    game = Trainer()
    game.values["player"]["AllianceID"] = 0
    state = execute(game,training_workflow({"units":[1,2,3,4],"count":12}))
    assert CITY_HUD.matches(state)
    assert [row["count"] for row in state.values["training_summary"]["rows"].values()] == [12]*4
    assert game.taps.count((738,443)) == 4
    assert (512,443) not in game.taps
    execute(game,training_workflow({"units":[1,2,3,4],"count":12}))
    assert game.taps.count((738,443)) == 4  # Busy queues are not restarted on retry.


def test_insufficient_reserve_stops_before_train():
    game = Trainer()
    assert CITY_HUD.matches(execute(game,training_workflow({"units":[4],"count":12,"reserves":{"1":49999}})))
    assert (738,443) not in game.taps
    assert game.values["resources"]["5"] == 1000


def test_locked_tier_does_not_open_unlock_dialog():
    game = Trainer()
    assert CITY_HUD.matches(execute(game,training_workflow({"units":[4],"tier":5,"count":1})))
    assert (775,133) not in game.taps and (738,443) not in game.taps


def test_changed_gems_do_not_count_as_confirmed_normal_training():
    game = Trainer()
    game.changed_gems = True
    workflow = training_workflow({"units":[4],"count":12})
    workflow = replace(workflow,steps=tuple(replace(step,timeout=1) if isinstance(step,Tap) and (step.x,step.y)==(738,443) else step for step in workflow.steps))
    with pytest.raises(WorkflowError,match="не подтверждён"):
        execute(game,workflow)
    assert game.taps.count((738,443)) == 1


def test_interruption_after_start_does_not_start_duplicate_on_resume():
    game = Trainer()
    cancelled = threading.Event()
    game.on_start = cancelled.set
    workflow = training_workflow({"units":[4],"count":12})
    with pytest.raises(Cancelled):
        execute(game,workflow,cancelled)
    game.on_start = lambda: None
    execute(game,workflow)
    assert game.taps.count((738,443)) == 1


def test_recovery_clears_selected_building_without_collecting_vip_rewards():
    game = Trainer()
    game.values["city_selection"] = "2"
    execute(game,training_workflow({"units":[4],"count":12}))
    assert game.taps[:2] == [(108,46),(818,62)]
    assert game.values["vip_points_available"] and game.values["vip_box_available"]


@pytest.mark.parametrize("settings",[{"units":[True]},{"units":[1,1]},{"tier":0},{"count":True},
    {"count":1000001},{"reserves":{"5":1}},{"reserves":{"1":-1}}])
def test_profile_rejects_invalid_training_settings(settings):
    with pytest.raises(ValueError):
        Profile("one",tasks={"training":settings}).validate()


def test_training_requires_explicit_type_selection():
    with pytest.raises(ValueError,match="хотя бы один"):
        training_workflow({})


def test_form_rejects_mismatched_configuration_and_missing_resource_prices():
    game = Trainer()
    game.focus = 4
    game.tap(525,344)
    good = deepcopy(game.values["training_form"])
    for change in ({"Id":3},{"Tier":2},{"BuildingType":9},{"Food":None}):
        game.values["training_form"] = deepcopy(good)
        game.values["training_form"]["config"].update(change)
        normalize_training_form(game.values)
        assert not game.values["training_form"]["ready"]
