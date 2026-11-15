from dataclasses import replace

import pytest

from mirage.memory import normalize_tavern
from mirage.tavern import TAVERN
from mirage.workflows import CITY_HUD, NotReady, Tap, WorkflowError
from test_rewards import Game, execute


class TavernGame(Game):
    def __init__(self):
        super().__init__()
        self.values.update(server_time=100,resources={str(i):500 for i in range(1,7)},tavern_items_known=True,
            tavern_visible=True,tavern_menu=1,tavern_mode=None,tavern_animation=False,
            tavern_info=False,tavern_probability=False,tavern_multi=False,tavern_show_equip=True,
            tavern_normal={"NextFreeTime":90,"FreeTimes":10},tavern_rare={"NextFreeTime":90},
            tavern_equip={"NextFreeTime":90},
            tavern_key_silver={"itemId":47,"itemCount":105},tavern_key_gold={"itemId":48,"itemCount":55},
            tavern_key_equip={"itemId":190,"itemCount":9},tavern_hero_visible=False,
            tavern_hero_id=22,tavern_hero_star=1,tavern_hero_width=959.7601,tavern_hero_height=539.8651,
            tavern_slg_hero={'visible':False})
        self.spend_key = False
        self.hero_result=False
        self.slg_result=False
        self.claims = []

    def snapshot(self):
        normalize_tavern(self.values)
        state = super().snapshot()
        if self.values["tavern_visible"]:
            state.values["views"]["TavernPage"] = True
        if self.values['tavern_hero_visible']:state.values['views']['AllUIHeroCheckIn']=True
        if self.values['tavern_slg_hero']['visible']:state.values['views']['AllUIHeroCheckIn_SLG']=True
        return state

    def tap(self,x,y,*,hold_ms=0):
        self.taps.append((x,y))
        positions=(200,480,760) if self.values['tavern_show_equip'] else (310,685)
        if y == 450 and x in positions:
            index = positions.index(x)
            kind = ("normal","rare","equip")[index]
            self.claims.append(kind)
            assert self.values["tavern_menu"] == 1
            self.values["tavern_"+kind]["NextFreeTime"] = 10000
            if index == 0:
                self.values["tavern_normal"]["FreeTimes"] -= 1
            if self.spend_key:
                self.values["tavern_key_"+("silver","gold","equip")[index]]["itemCount"] -= 1
            self.values.update(tavern_menu=index+2,tavern_mode=index+1)
            if self.hero_result and index<2:self.values.update(tavern_hero_visible=True,tavern_animation=True)
            if self.slg_result and index<2:self.values.update(
                tavern_slg_hero={'visible':True,'id':38,'star':1,'width':0,'height':0},tavern_animation=True)
        elif (x,y)==(145,455):
            assert self.values['tavern_hero_visible'] is True
            self.values.update(tavern_hero_visible=False,tavern_animation=False)
        elif (x,y)==(714,405):
            assert self.values['tavern_slg_hero']['visible']
            self.values.update(tavern_slg_hero={'visible':False},tavern_animation=False)
        elif y == 480:
            assert self.values["tavern_menu"] in (2,3,4)
            assert x == (377 if self.values["tavern_mode"] == 3 or not self.values['tavern_show_equip'] else 170)
            self.values["tavern_menu"] = 1
        elif (x,y) == (29,28):
            assert self.values["tavern_menu"] == 1
            self.values["tavern_visible"] = False
        else:
            raise AssertionError(f"Unexpected tavern input {x,y}")


def test_three_free_chests_preserve_keys_and_use_the_right_result_confirmation():
    game = TavernGame()
    after = execute(game,TAVERN)
    assert CITY_HUD.matches(after)
    assert after.values["tavern_state"]["available"] == 0
    assert after.values["tavern_state"]["keys"] == {"silver":105,"gold":55,"equip":9}
    assert game.taps == [(200,450),(170,480),(480,450),(170,480),(760,450),(377,480),(29,28)]


def test_tavern_does_not_spend_keys_on_cooldown_or_when_daily_silver_attempts_are_exhausted():
    game = TavernGame()
    game.values["tavern_normal"]["FreeTimes"] = 0
    game.values["tavern_rare"]["NextFreeTime"] = game.values["tavern_equip"]["NextFreeTime"] = 10000
    execute(game,TAVERN)
    assert not game.claims
    assert game.taps == [(29,28)]


def test_tavern_resumes_a_gold_result_without_opening_another_chest():
    game = TavernGame()
    for kind in ("normal","rare","equip"):
        game.values["tavern_"+kind]["NextFreeTime"] = 10000
    game.values.update(tavern_menu=3,tavern_mode=2)
    execute(game,TAVERN)
    assert game.taps == [(170,480),(29,28)]


def test_changed_key_balance_is_not_a_confirmed_free_chest():
    game = TavernGame()
    game.spend_key = True
    workflow = replace(TAVERN,steps=tuple(replace(step,timeout=1) if isinstance(step,Tap) and step.increase else step
                                         for step in TAVERN.steps))
    with pytest.raises(WorkflowError,match="не подтверждён"):
        execute(game,workflow)
    assert game.claims == ["normal"]


@pytest.mark.parametrize("corruption",["inventory_unknown","negative_key","missing_time","wrong_key_id","negative_attempts"])
def test_tavern_rejects_unconfirmed_free_attempt_or_currency_state(corruption):
    game = TavernGame()
    if corruption == "inventory_unknown": game.values["tavern_items_known"] = False
    elif corruption == "negative_key": game.values["tavern_key_gold"]["itemCount"] = -1
    elif corruption == "missing_time": game.values["tavern_rare"].clear()
    elif corruption == "wrong_key_id": game.values["tavern_key_gold"]["itemId"] = 47
    else: game.values["tavern_normal"]["FreeTimes"] = -1
    with pytest.raises(NotReady):
        execute(game,TAVERN)
    assert not game.taps


def test_unknown_commander_overlay_defers_input():
    game = TavernGame()
    game.overlay = "UnknownCommanderReward"
    with pytest.raises(NotReady):
        execute(game,TAVERN)
    assert not game.taps


def test_single_chest_commander_result_is_confirmed_without_repeating_free_claim():
    game=TavernGame();game.hero_result=True
    after=execute(game,TAVERN)
    assert CITY_HUD.matches(after)
    assert game.claims==['normal','rare','equip']
    assert game.taps.count((145,455))==2
    assert game.taps==[(200,450),(145,455),(170,480),(480,450),(145,455),(170,480),
                       (760,450),(377,480),(29,28)]


def test_resume_at_known_commander_result_finishes_without_opening_another_chest():
    game=TavernGame()
    for kind in ('normal','rare','equip'):game.values['tavern_'+kind]['NextFreeTime']=10000
    game.values.update(tavern_menu=2,tavern_mode=1,tavern_hero_visible=True,tavern_animation=True)
    after=execute(game,TAVERN)
    assert CITY_HUD.matches(after) and game.taps==[(145,455),(170,480),(29,28)]
    assert not game.claims


@pytest.mark.parametrize('fault',['size','hero','star','multi','info','mode','foreign_modal','keys'])
def test_unconfirmed_commander_panel_does_not_receive_confirmation(fault):
    game=TavernGame();game.values.update(tavern_menu=2,tavern_mode=1,tavern_hero_visible=True,tavern_animation=True)
    if fault=='size':game.values['tavern_hero_width']=1200
    elif fault=='hero':game.values['tavern_hero_id']=None
    elif fault=='star':game.values['tavern_hero_star']=True
    elif fault=='multi':game.values['tavern_multi']=True
    elif fault=='info':game.values['tavern_info']=True
    elif fault=='mode':game.values['tavern_mode']=3
    elif fault=='foreign_modal':game.overlay='UnknownPurchase'
    else:game.values['tavern_items_known']=False
    with pytest.raises(NotReady):execute(game,TAVERN)
    assert not game.taps


def test_tavern_fields_remain_within_snapshot_budget():
    from mirage.memory import PATHS
    from mirage.tavern import FIELDS
    assert len(PATHS|FIELDS)<=64


def test_two_chest_early_city_layout_confirms_slg_commander_without_keys_or_locked_equipment():
    game=TavernGame();game.values['tavern_show_equip']=False;game.slg_result=True
    after=execute(game,TAVERN)
    assert CITY_HUD.matches(after) and game.claims==['normal','rare']
    assert game.taps==[(310,450),(714,405),(377,480),(685,450),(714,405),(377,480),(29,28)]
    assert after.values['tavern_state']['keys']=={'silver':105,'gold':55,'equip':9}
