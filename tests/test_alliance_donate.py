from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.alliance_donate import Receipt, donation_workflow
from mirage.memory import normalize_donation
from mirage.model import DonationOptions, Profile
from mirage.workflows import CITY_HUD, Cancelled, NotReady, Tap, WorkflowError
from test_rewards import Game, execute


class Donations(Game):
    def __init__(self):
        super().__init__()
        self.values.update(resources={"1":10000,"2":10000,"3":10000,"4":10000,"5":500,"6":1000},
            donation={"recommend":306,"chances":20,"maximum":20,"today":0,"needs_refresh":False,
                "target":{"type":306,"level":2,"max_level":5,"science_point":75200,"end_time":0,"is_alliance":True},
                "config":{"ID":30603,"Type":306,"Level":3,"Class":3,"TechniquePoint":250000,
                          "DonateType":2,"DonateValue":2000,"DonateGem":10},
                "alliance_visible":False,"research_visible":False,"detail_visible":False,
                "detail":None,"detail_id":None,"page_type":2})
        self.wrong_tile = False
        self.on_donation = lambda:None

    def snapshot(self):
        normalize_donation(self.values)
        state = super().snapshot()
        for field,name in (("alliance_visible","AllianceMainPage"),("research_visible","AllianceResearchPage"),
                           ("detail_visible","AllianceResearchRequestPage")):
            if state.values["donation"][field]:
                state.values["views"][name] = True
                state.values["views"]["CommonBackground"] = True
        return state

    def tap(self,x,y,*,hold_ms=0):
        data = self.values["donation"]
        self.taps.append((x,y))
        if (x,y) == (924,505):
            self.values["hud_menu"] = not self.values["hud_menu"]
        elif (x,y) == (695,505):
            data["alliance_visible"] = True
        elif (x,y) == (528,420):
            data.update(alliance_visible=False,research_visible=True)
        elif (x,y) == (430,445):
            data.update(detail_visible=True,detail=deepcopy(data["target"]),detail_id=30602)
            if self.wrong_tile:
                data["detail"]["type"] = 305
                data["detail_id"] = 30502
        elif (x,y) == (734,430):
            assert data["detail_visible"]
            data["target"]["science_point"] += 100
            data["detail"]["science_point"] += 100
            data["today"] += 100
            data["chances"] -= 1
            self.values["resources"]["2"] -= 2000
            self.values["resources"]["6"] += 100
            self.on_donation()
        elif (x,y) == (818,62):
            data["detail_visible"] = False
        elif (x,y) == (835,53):
            data.update(research_visible=False,alliance_visible=True)
        elif (x,y) == (837,32):
            data["alliance_visible"] = False
        else:
            raise AssertionError(f"Unexpected donation input {(x,y)}")


def test_resource_donations_stop_at_the_daily_goal_and_return_to_city():
    game = Donations()
    workflow = donation_workflow({"daily_goal":200})
    for _ in range(3):
        assert CITY_HUD.matches(execute(game,workflow))
    assert game.taps.count((734,430)) == 2
    assert game.values["resources"]["2"] == 6000
    assert game.values["resources"]["5"] == 500
    assert game.values["resources"]["6"] == 1200
    assert (548,430) not in game.taps


def test_cancellation_after_a_donation_does_not_repeat_an_already_reached_goal():
    game = Donations()
    cancelled = threading.Event()
    game.on_donation = cancelled.set
    workflow = donation_workflow({"daily_goal":100})
    with pytest.raises(Cancelled):
        execute(game,workflow,cancelled)
    game.on_donation = lambda:None
    assert CITY_HUD.matches(execute(game,workflow))
    assert game.taps.count((734,430)) == 1


def test_reserve_and_exhausted_chances_prevent_navigation_and_donation():
    game = Donations()
    execute(game,donation_workflow({"reserves":{"2":9000}}))
    assert not game.taps
    game.values["donation"]["chances"] = 0
    execute(game,donation_workflow({}))
    assert not game.taps


def test_wrong_research_tile_never_receives_a_donation():
    game = Donations()
    game.wrong_tile = True
    workflow = donation_workflow({})
    workflow = replace(workflow,steps=tuple(replace(step,timeout=1) if isinstance(step,Tap)
        and (step.x,step.y) == (430,445) else step for step in workflow.steps))
    with pytest.raises(WorkflowError):
        execute(game,workflow)
    assert (734,430) not in game.taps and game.values["resources"]["2"] == 10000


def test_receipt_rejects_gem_spending_even_if_all_donation_counters_advance():
    game = Donations()
    game.values["donation"].update(research_visible=True)
    game.tap(430,445)
    receipt = Receipt(DonationOptions()).capture(game.snapshot())
    game.tap(734,430)
    assert receipt.matches(game.snapshot())
    game.values["resources"]["5"] -= 1
    assert not receipt.matches(game.snapshot())


@pytest.mark.parametrize("corruption",["gem_cost","wrong_level","unknown_chances","refresh","wrong_type"])
def test_unknown_or_inconsistent_donation_state_blocks_all_input(corruption):
    game = Donations()
    data = game.values["donation"]
    if corruption == "gem_cost": data["config"]["DonateType"] = 5
    elif corruption == "wrong_level": data["config"]["Level"] = 2
    elif corruption == "unknown_chances": data["chances"] = None
    elif corruption == "refresh": data["needs_refresh"] = True
    else: data["recommend"] = 305
    with pytest.raises(NotReady):
        execute(game,donation_workflow({}))
    assert not game.taps


@pytest.mark.parametrize("goal",[True,0,100001,"100"])
def test_invalid_daily_contribution_goals_cannot_be_saved(goal):
    with pytest.raises(ValueError):
        Profile("one",tasks={"alliance_donate":{"daily_goal":goal}}).validate()
