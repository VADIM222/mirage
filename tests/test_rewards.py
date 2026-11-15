from copy import deepcopy
from dataclasses import replace
import threading

import pytest

from mirage.model import Snapshot
from mirage.workflows import Cancelled, CITY_HUD, DAILY_REWARD, Engine, EXPEDITION_REWARDS, MAIL_REWARDS, NotReady, TRAINING_COLLECT, VIP_REWARD, WorkflowError


class Game:
    def __init__(self):
        self.taps = []
        self.time = 100
        self.values = {
            "hud_visible":True, "hud_menu":False, "in_city":True, "city_enabled":True, "player":{"AllianceID":10},
            "queue_panel":{"known":True,"visible":False},
            "city_selection_known":True,"city_selection":None,
            "vip_visible":False, "vip_level":12, "vip_shown_level":12,
            "vip_box_detail":False, "vip_opening_box":False,
            "vip_notice_visible":False,
            "vip_points_available":True, "vip_box_available":True, "reward_popup_visible":False,
            "quest_visible":False, "quest_tab":1, "daily_ready_count":9, "daily_score":0,
            "daily_refresh_due":False,
            "quest_collecting":{}, "daily_chests":{str(i):{"Completed":False} for i in range(1, 6)},
        }
        self.overlay = None
        self.cancel_after_box = None
        self.effect_snapshots = 0

    def snapshot(self):
        values = deepcopy(self.values)
        views = dict.fromkeys(("MapHudPanel", "MapUIDragMoveHandler", "AlliMarkElementHUD", "CityUIContainerHud"), True)
        for field, name in (("vip_visible", "VIPMainPage"), ("quest_visible", "QuestSystemMainPage"),
                            ("vip_notice_visible", "VIPNotice"),
                            ("reward_popup_visible", "RoutineRewardsCollect")):
            if values[field]:
                views[name] = True
                views["CommonBackground"] = True
        if self.overlay:
            views[self.overlay] = True
        if self.effect_snapshots:
            views["CommonItemBagPage"] = True
            self.effect_snapshots -= 1
        values["views"] = views
        values["quest_first"] = {"Stat":2 if values["daily_ready_count"] else 1}
        values["daily_chest_count"] = sum(values["daily_score"] >= threshold and not values["daily_chests"][str(i)]["Completed"]
                                          for i, threshold in enumerate((20, 40, 60, 80, 100), 1))
        return Snapshot("one", 10, 20, self.time, "1.1.12.20", values)

    def tap(self, x, y, *, hold_ms=0):
        assert hold_ms == 100
        self.taps.append((x, y))
        if (x,y) == (248,275):
            self.values["queue_panel"]["visible"] = False
        elif (x, y) == (108, 46):
            self.values["city_selection"] = None
            self.values["vip_visible"] = True
        elif (x, y) == (765, 152):
            self.values["vip_points_available"] = False
            self.values["vip_notice_visible"] = True
        elif (x, y) == (705, 267):
            self.values["vip_box_available"] = False
            self.values["reward_popup_visible"] = True
            if self.cancel_after_box:
                self.cancel_after_box.set()
        elif (x, y) == (480, 500):
            if self.values["vip_notice_visible"]:
                self.values["vip_notice_visible"] = False
            else:
                self.values["reward_popup_visible"] = False
                self.effect_snapshots = 2
        elif (x, y) == (818, 62):
            self.values["vip_visible"] = self.values["quest_visible"] = False
        elif (x, y) == (30, 155):
            self.values["quest_visible"] = True
        elif (x, y) == (77, 239):
            self.values["quest_tab"] = 2
        elif (x, y) == (755, 255):
            self.values["daily_ready_count"] = 0
            self.values["daily_score"] = 52
        elif y == 145:
            for i, threshold in enumerate((20, 40, 60, 80, 100), 1):
                if self.values["daily_score"] >= threshold:
                    self.values["daily_chests"][str(i)]["Completed"] = True
            self.values["reward_popup_visible"] = True
        else:
            raise AssertionError("Unexpected input")


def execute(game, candidate, cancelled=None):
    def clock():
        game.time += 0.1
        return game.time
    return Engine(game, game.snapshot, clock=clock, resolution=(960, 540)).execute(
        replace(candidate, verified=True), cancelled or threading.Event(), instance_id="one", pid=10, player_id=20)


@pytest.mark.parametrize("points,box", [(True, True), (True, False), (False, True), (False, False)])
def test_vip_only_claims_available_free_rewards_and_returns_to_city(points, box):
    game = Game()
    game.values.update(vip_points_available=points, vip_box_available=box)
    assert CITY_HUD.matches(execute(game, VIP_REWARD))
    expected = []
    if points or box:
        expected.append((108, 46))
        if points:
            expected.extend(((765, 152), (480, 500)))
        if box:
            expected.extend(((705, 267), (480, 500)))
        expected.append((818, 62))
    assert game.taps == expected


def test_cancelled_vip_can_resume_at_popup_without_claiming_twice():
    game = Game()
    cancelled = threading.Event()
    game.cancel_after_box = cancelled
    with pytest.raises(Cancelled):
        execute(game, VIP_REWARD, cancelled)
    assert game.taps == [(108, 46), (765, 152), (480, 500), (705, 267)]
    assert CITY_HUD.matches(execute(game, VIP_REWARD))
    assert game.taps == [(108, 46), (765, 152), (480, 500), (705, 267), (480, 500), (818, 62)]


def test_daily_chain_skips_auto_claimed_chests_and_unavailable_thresholds():
    game = Game()
    result = execute(game, DAILY_REWARD)
    assert CITY_HUD.matches(result)
    assert result.values["daily_ready_count"] == 0
    assert result.values["daily_chest_count"] == 0
    assert game.taps == [(30, 155), (77, 239), (755, 255), (270, 145), (480, 500), (818, 62)]


@pytest.mark.parametrize("candidate", [VIP_REWARD, DAILY_REWARD])
def test_unknown_overlay_prevents_reward_input(candidate):
    game = Game()
    game.overlay = "UnknownPopup"
    with pytest.raises(NotReady):
        execute(game, candidate)
    assert game.taps == []


def test_unverified_vip_level_prevents_even_opening_the_page():
    game = Game()
    game.values.update(vip_level=11, vip_shown_level=11)
    with pytest.raises(NotReady):
        execute(game, VIP_REWARD)
    assert game.taps == []


def test_daily_reset_waits_for_fresh_data_before_any_input():
    game = Game()
    game.values.update(daily_refresh_due=True, daily_ready_count=0, daily_score=52)
    with pytest.raises(NotReady, match="актуальных"):
        execute(game, DAILY_REWARD)
    assert game.taps == []


def test_unverified_higher_chest_buttons_are_not_pressed():
    game = Game()
    game.values.update(daily_ready_count=0, daily_score=100)
    game.values["daily_chests"]["1"]["Completed"] = True
    game.values["daily_chests"]["2"]["Completed"] = True
    game.values["daily_chests"]["3"]["Completed"] = True
    assert CITY_HUD.matches(execute(game, DAILY_REWARD))
    assert game.taps == []


def test_sixty_point_chest_runs_when_lower_chests_were_already_claimed():
    game=Game();game.values.update(daily_ready_count=0,daily_score=70)
    for index in ('1','2'):game.values['daily_chests'][index]['Completed']=True
    assert CITY_HUD.matches(execute(game,DAILY_REWARD))
    assert game.taps==[(30,155),(77,239),(534,145),(480,500),(818,62)]


class MailGame(Game):
    def __init__(self):
        super().__init__()
        self.values.update(mail_visible=False, mail_box=3, mail_edit=False,
                           mail_reward_visible=False, mail_reward_click=False, mail_reward_recycle=False)
        self.boxes = {"SystemBox":{"pending":5,"unread":4}, "AllianceBox":{"pending":0,"unread":4},
                      "Report":{"pending":0,"unread":15}}
        self.mail_ready = True
        self.receipt_delay = 0

    def snapshot(self):
        if self.receipt_delay:
            self.receipt_delay -= 1
            if self.receipt_delay == 0:
                self.values.update(mail_reward_visible=True, mail_reward_click=True)
        state = super().snapshot()
        state.values["mail_summary"] = {"ready":self.mail_ready, "boxes":deepcopy(self.boxes),
                                        "pending":sum(b["pending"] for b in self.boxes.values()),
                                        "unread":sum(b["unread"] for b in self.boxes.values())}
        for flag, view in (("mail_visible", "AllUIMailMainPage"), ("mail_reward_visible", "UniversalRewardsCollect")):
            if state.values[flag]:
                state.values["views"].update({view:True, "CommonBackground":True})
        return state

    def tap(self, x, y, *, hold_ms=0):
        assert hold_ms == 100
        self.taps.append((x, y))
        if (x, y) == (924, 505):
            self.values["hud_menu"] = not self.values["hud_menu"]
        elif (x, y) == (846, 505):
            self.values["mail_visible"] = True
        elif y == 31 and x in (428, 306, 188):
            self.values["mail_box"] = {428:4, 306:3, 188:2}[x]
        elif (x, y) == (90, 500):
            box = self.boxes[{4:"SystemBox", 3:"AllianceBox", 2:"Report"}[self.values["mail_box"]]]
            if box["pending"]:
                # Real mail metadata changes before the reward dialog appears.
                self.receipt_delay = 2
            box.update(pending=0, unread=0)
        elif (x, y) == (484, 398):
            self.values.update(mail_reward_visible=False, mail_reward_click=False)
            self.effect_snapshots = 2
        elif (x, y) == (925, 32):
            self.values["mail_visible"] = False
        else:
            raise AssertionError("Unexpected mail input")


def test_mail_waits_for_receipt_and_processes_the_three_verified_boxes():
    game = MailGame()
    result = execute(game, MAIL_REWARDS)
    assert CITY_HUD.matches(result)
    assert result.values["mail_summary"]["pending"] == result.values["mail_summary"]["unread"] == 0
    assert game.taps == [(924, 505), (846, 505), (428, 31), (90, 500), (484, 398),
                         (306, 31), (90, 500), (188, 31), (90, 500), (925, 32), (924, 505)]


def test_mail_resume_confirms_existing_receipt_without_claiming_twice():
    game = MailGame()
    for box in game.boxes.values():
        box.update(pending=0, unread=0)
    game.values.update(mail_visible=True, mail_box=4, hud_menu=True,
                       mail_reward_visible=True, mail_reward_click=True)
    assert CITY_HUD.matches(execute(game, MAIL_REWARDS))
    assert game.taps == [(484, 398), (925, 32), (924, 505)]


def test_empty_mail_does_not_open_the_menu():
    game = MailGame()
    for box in game.boxes.values():
        box.update(pending=0, unread=0)
    assert CITY_HUD.matches(execute(game, MAIL_REWARDS))
    assert game.taps == []


def test_incomplete_mail_cache_prevents_input():
    game = MailGame()
    game.mail_ready = False
    with pytest.raises(NotReady):
        execute(game, MAIL_REWARDS)
    assert game.taps == []


def test_mail_unknown_overlay_prevents_input():
    game = MailGame()
    game.overlay = "UnknownPurchasePopup"
    with pytest.raises(NotReady):
        execute(game, MAIL_REWARDS)
    assert game.taps == []


def test_mail_does_not_confirm_a_recycle_dialog():
    game = MailGame()
    game.values.update(mail_visible=True, mail_reward_visible=True, mail_reward_click=True, mail_reward_recycle=True)
    with pytest.raises(NotReady):
        execute(game, MAIL_REWARDS)
    assert game.taps == []


def test_empty_mail_resumes_menu_cleanup_without_opening_mail_again():
    game = MailGame()
    for box in game.boxes.values():
        box.update(pending=0, unread=0)
    game.values["hud_menu"] = True
    assert CITY_HUD.matches(execute(game, MAIL_REWARDS))
    assert game.taps == [(924, 505)]


class ExpeditionGame(Game):
    def __init__(self):
        super().__init__()
        self.values.update(expedition_visible=False, campaign_visible=False, expedition_state=3,
                           expedition_data_ready=True, expedition_pending=66, expedition_currency=165510,
                           expedition_reward_visible=False, expedition_reward_click=False,
                           expedition_reward_recycle=False, expedition_reward_height=366.349, expedition_reward_width=586.072)
        self.receipt_delay = 0

    def snapshot(self):
        if self.receipt_delay:
            self.receipt_delay -= 1
            if self.receipt_delay == 0:
                self.values.update(expedition_reward_visible=True, expedition_reward_click=True)
        state = super().snapshot()
        for flag, view in (("campaign_visible", "GVGEntranceNew"), ("expedition_visible", "ScenarioMapMainPage"),
                           ("expedition_reward_visible", "UniversalRewardsCollect")):
            if state.values[flag]:
                state.values["views"].update({view:True, "CommonBackground":True})
        return state

    def tap(self, x, y, *, hold_ms=0):
        assert hold_ms == 100
        self.taps.append((x, y))
        if (x, y) == (924, 505):
            self.values["hud_menu"] = not self.values["hud_menu"]
        elif (x, y) == (545, 503):
            self.values["campaign_visible"] = True
        elif (x, y) == (141, 180):
            self.values.update(campaign_visible=False, expedition_visible=True, expedition_data_ready=True)
            if self.values["expedition_pending"] is None:
                self.values["expedition_pending"] = 0
        elif (x, y) == (95, 170):
            self.values["expedition_pending"] = 0
            self.values["expedition_currency"] += 4280
            self.receipt_delay = 2
        elif (x, y) == (484, 398):
            self.values.update(expedition_reward_visible=False, expedition_reward_click=False)
            self.effect_snapshots = 2
        elif (x, y) == (31, 27):
            self.values.update(expedition_visible=False, campaign_visible=True)
        elif (x, y) == (34, 27):
            self.values["campaign_visible"] = False
        else:
            raise AssertionError("Unexpected expedition action")


def test_expedition_claims_free_rewards_and_returns_to_city():
    game = ExpeditionGame()
    result = execute(game, EXPEDITION_REWARDS)
    assert CITY_HUD.matches(result)
    assert result.values["expedition_currency"] == 169790
    assert game.taps == [(924, 505), (545, 503), (141, 180), (95, 170), (484, 398),
                         (31, 27), (34, 27), (924, 505)]


@pytest.mark.parametrize("field,value", [("expedition_reward_recycle", True),
                                       ("expedition_reward_height", 300), ("expedition_reward_width", 800)])
def test_expedition_does_not_confirm_an_unknown_reward_dialog(field, value):
    game = ExpeditionGame()
    game.values.update(expedition_visible=True, expedition_pending=0, expedition_reward_visible=True, expedition_reward_click=True)
    game.values[field] = value
    with pytest.raises(NotReady):
        execute(game, EXPEDITION_REWARDS)
    assert game.taps == []


def test_expedition_never_enters_a_running_battle():
    game = ExpeditionGame()
    game.values.update(expedition_visible=True, expedition_state=13)
    with pytest.raises(NotReady):
        execute(game, EXPEDITION_REWARDS)
    assert game.taps == []


def test_expedition_without_rewards_is_noop_or_finishes_only_menu_cleanup():
    game = ExpeditionGame()
    game.values["expedition_pending"] = 0
    assert CITY_HUD.matches(execute(game, EXPEDITION_REWARDS))
    assert game.taps == []
    game.values["hud_menu"] = True
    assert CITY_HUD.matches(execute(game, EXPEDITION_REWARDS))
    assert game.taps == [(924, 505)]


def test_expedition_unknown_data_is_loaded_before_deciding_about_claims():
    game = ExpeditionGame()
    game.values.update(expedition_data_ready=False, expedition_pending=None)
    assert CITY_HUD.matches(execute(game, EXPEDITION_REWARDS))
    assert (95, 170) not in game.taps


def test_daily_closes_queue_overlay_before_using_the_quest_button():
    game = Game()
    game.values["queue_panel"]["visible"] = True
    assert not CITY_HUD.matches(game.snapshot())
    assert CITY_HUD.matches(execute(game, DAILY_REWARD))
    assert game.taps[0:2] == [(248,275),(30,155)]


@pytest.mark.parametrize("passive",[True,False])
def test_only_nonblocking_quest_arrow_is_allowed_during_automation(passive):
    game = Game()
    game.overlay = "QuestGuide"
    game.values.update(guide_force_click=not passive,guide_click_callback=False)
    if passive:
        execute(game,VIP_REWARD)
    else:
        with pytest.raises(NotReady):
            execute(game,VIP_REWARD)
        assert game.taps == []


class TrainingGame(Game):
    def __init__(self):
        super().__init__()
        self.values.update(training_layout_ready=True,training_summary={
            "ready":True,"completed":1,"troops":{"1":100,"2":200,"3":300,"4":400},
            "rows":{str(i):{"building_id":str(i),"focused":False,"pending":i==4,
                            "unit_id":i,"count":2000 if i==4 else 0} for i in range(1,5)}})
        self.receipt_samples = 0
        self.missing_troops = False

    def snapshot(self):
        if self.receipt_samples:
            self.receipt_samples -= 1
            self.values["training_summary"]["ready"] = self.receipt_samples != 2
            if self.receipt_samples == 0 and not self.missing_troops:
                self.values["training_summary"]["troops"]["4"] += 2000
        return super().snapshot()

    def tap(self,x,y,*,hold_ms=0):
        assert hold_ms == 100
        self.taps.append((x,y))
        if (x,y) == (24,102):
            self.values["queue_panel"]["visible"] = True
        elif (x,y) == (248,275):
            self.values["queue_panel"]["visible"] = False
        elif x == 110 and y in (150,200,250,300):
            subtype = (y-150)//50+1
            for i,row in self.values["training_summary"]["rows"].items():
                row["focused"] = int(i) == subtype
        elif (x,y) == (480,270):
            summary = self.values["training_summary"]
            assert summary["rows"]["4"]["focused"] and not self.values["queue_panel"]["visible"]
            summary["completed"] = 0
            summary["rows"]["4"].update(pending=False,count=0,unit_id=None)
            self.receipt_samples = 3
        else:
            raise AssertionError("Unexpected training input")


def test_training_collection_confirms_focus_queue_removal_and_actual_troop_increase():
    game = TrainingGame()
    result = execute(game,TRAINING_COLLECT)
    assert CITY_HUD.matches(result)
    assert result.values["training_summary"]["troops"]["4"] == 2400
    assert game.taps == [(24,102),(110,300),(248,275),(480,270)]


def test_training_does_not_treat_queue_removal_alone_as_a_successful_claim():
    game = TrainingGame()
    game.missing_troops = True
    workflow = replace(TRAINING_COLLECT,steps=tuple(replace(s,timeout=1) if getattr(s,"increase",None) else s for s in TRAINING_COLLECT.steps))
    with pytest.raises(WorkflowError,match="не подтверждён"):
        execute(game,workflow)
    assert game.values["training_summary"]["troops"]["4"] == 400
    assert game.taps.count((480,270)) == 1


def test_training_does_not_navigate_unknown_queue_layout():
    game = TrainingGame()
    game.values["training_layout_ready"] = False
    with pytest.raises(NotReady):
        execute(game,TRAINING_COLLECT)
    assert game.taps == [(24,102)]


def test_missed_queue_focus_is_retried_but_collection_is_performed_only_once():
    game=TrainingGame()
    original=game.tap
    ignored=[]
    def tap(x,y,**kwargs):
        if (x,y)==(110,300) and not ignored:
            game.taps.append((x,y));ignored.append(True)
        else:original(x,y,**kwargs)
    game.tap=tap
    result=execute(game,TRAINING_COLLECT)
    assert CITY_HUD.matches(result) and result.values["training_summary"]["troops"]["4"]==2400
    assert game.taps.count((110,300))==2 and game.taps.count((480,270))==1


@pytest.mark.parametrize("change",["cancel","layout","persistent_miss"])
def test_focus_retry_cannot_cross_cancellation_or_an_unknown_queue_layout(change):
    game=TrainingGame()
    original=game.tap
    cancelled=threading.Event()
    def tap(x,y,**kwargs):
        if (x,y)==(110,300):
            game.taps.append((x,y))
            if change=="cancel":cancelled.set()
            if change=="layout":game.values["training_layout_ready"]=False
        else:original(x,y,**kwargs)
    game.tap=tap
    error=Cancelled if change=="cancel" else NotReady if change=="layout" else WorkflowError
    with pytest.raises(error):execute(game,TRAINING_COLLECT,cancelled)
    assert game.taps.count((110,300))==(2 if change=="persistent_miss" else 1)
    assert (480,270) not in game.taps and game.values["training_summary"]["troops"]["4"]==400


def test_training_waits_for_observed_queue_visibility_before_input():
    game = TrainingGame()
    game.values["queue_panel"].update(known=False,visible=None)
    with pytest.raises(NotReady):
        execute(game,TRAINING_COLLECT)
    assert game.taps == []
