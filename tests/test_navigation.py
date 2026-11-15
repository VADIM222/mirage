from copy import deepcopy
import threading

import pytest

from mirage.model import Snapshot
from mirage.navigation import navigate_city
from mirage.workflows import Cancelled, NotReady


class City:
    def __init__(self):
        self.now = 100
        self.values = {"hud_visible":True,"hud_menu":False,"in_city":True,"city_enabled":True,"views":{"MapHudPanel":True},
            "queue_panel":{"known":True,"visible":False},"city_selection_known":True,"city_selection":None,
            "city_camera":{"x":10.,"y":20.,"distance":200.,"moving":False},
            "buildings":{"60":{"type":18,"world_x":8.5,"world_y":20.5}},
            "building_menu":{"known":True,"selected":None}}
        self.inputs = []
        self.wrong_selection = False
        self.freeze_camera = False
        self.block_downward_drag = False
        self.block_primary_origin = False
        self.blocked_origins = set()

    def clock(self):
        return self.now

    def observe(self):
        self.now += .2
        return Snapshot("one",10,20,self.now,"1.1.12.20",deepcopy(self.values))

    def drag(self,x,y,end_x,end_y,**kwargs):
        self.inputs.append(("drag",x,y,end_x,end_y))
        if (not self.freeze_camera and (x,y) not in self.blocked_origins
                and not (self.block_primary_origin and (x,y)==(600,400))
                and not (self.block_downward_drag and (x,y)==(600,400) and end_y>400)):
            self.values["city_camera"]["x"] -= (end_x-x)*.0085
            self.values["city_camera"]["y"] += (end_y-y)*.011

    def tap(self,x,y,**kwargs):
        self.inputs.append(("tap",x,y))
        self.values["city_selection"] = "42" if self.wrong_selection else "60"
        self.values["building_menu"]["selected"] = {"id":self.values["city_selection"],"type":18}


@pytest.mark.parametrize('distance',[150.,200.])
def test_camera_feedback_selects_only_the_requested_owned_building(distance):
    city = City()
    city.values['city_camera']['distance']=distance
    after = navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert after.values["building_menu"]["selected"]["id"] == "60"
    assert city.inputs[-1][0] == "tap"
    assert len([item for item in city.inputs if item[0] == "drag"]) >= 2
    assert abs(city.values["city_camera"]["x"]-8.5) < .15


def test_wrong_building_selection_never_continues_to_a_menu_action():
    city = City()
    city.wrong_selection = True
    with pytest.raises(NotReady,match="другое здание"):
        navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert sum(item[0] == "tap" for item in city.inputs) == 1


def test_missing_camera_response_stops_after_calibration():
    city = City()
    city.freeze_camera = True
    with pytest.raises(NotReady,match="отклик камеры"):
        navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert not any(item[0] == "tap" for item in city.inputs)


def test_permission_change_during_observation_blocks_city_input():
    city = City()
    permitted = [True]
    def observe():
        permitted[0] = False
        return city.observe()
    with pytest.raises(Cancelled):
        navigate_city(city,observe,threading.Event(),city.clock,18,lambda:permitted[0])
    assert not city.inputs


def test_explicit_building_can_be_approached_without_selecting_or_harvesting():
    city = City()
    city.values["buildings"]["61"] = {"type":18,"world_x":9.,"world_y":20.5}
    after = navigate_city(city,city.observe,threading.Event(),city.clock,18,building_id="60",select=False)
    assert after.values["city_navigation_target"]["id"] == "60"
    assert after.values["city_selection"] is None
    assert not any(action[0] == "tap" for action in city.inputs)


def test_a_captured_city_gesture_retries_from_a_bounded_alternate_origin():
    city = City()
    city.block_downward_drag = True
    after = navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert after.values["building_menu"]["selected"]["id"] == "60"
    assert any(item[0] == "drag" and item[1:3] != (600,400) for item in city.inputs)
    assert all(item[4] <= 440 for item in city.inputs if item[0] == "drag")


def test_calibration_retries_a_city_area_that_does_not_capture_the_gesture():
    city = City()
    city.block_primary_origin = True
    after = navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert after.values["building_menu"]["selected"]["id"] == "60"
    assert any(item[:3] == ("drag",300,200) for item in city.inputs)


def test_fine_navigation_does_not_turn_a_short_drag_into_an_accidental_building_tap():
    import math
    city = City()
    navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert all(math.hypot(item[3]-item[1],item[4]-item[2]) >= 24
               for item in city.inputs if item[0] == "drag")


def test_fine_vertical_approach_does_not_oscillate_against_the_bottom_viewport_limit():
    city=City()
    # After calibration the goal is 30px below the camera. At y400 both
    # the detour and the clipped correction used to be exactly 40px forever.
    city.values['buildings']['60'].update(world_x=10.68,world_y=19.45)
    after=navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert after.values['building_menu']['selected']['id']=='60'
    assert all(160<=item[2]<=440 and 160<=item[4]<=440 for item in city.inputs if item[0]=='drag')


def test_damped_short_gestures_can_select_a_confirmed_target_without_repeated_detours():
    city=City()
    city.values['buildings']['60'].update(world_x=10.68,world_y=19.45)
    original=city.drag
    def drag(x,y,end_x,end_y,**kwargs):
        # Live camera response to short gestures is weaker than the80px calibration.
        if len(city.inputs)>=2:
            end_x=x+(end_x-x)*.65;end_y=y+(end_y-y)*.65
        original(x,y,end_x,end_y,**kwargs)
    city.drag=drag
    after=navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert after.values['building_menu']['selected']['id']=='60'


def test_a_blocked_fine_adjustment_changes_origin_instead_of_repeating_forever():
    city = City()
    city.block_primary_origin = True
    city.blocked_origins.add((300,200))
    after = navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert after.values["building_menu"]["selected"]["id"] == "60"
    assert any(item[:3] == ("drag",300,300) for item in city.inputs)


def test_recalibration_and_fine_moves_avoid_the_interactive_top_hud():
    city=City()
    city.block_primary_origin=True
    original=city.drag
    def drag(x,y,end_x,end_y,**kwargs):
        if min(y,end_y)<160:city.values['views']['BattlePassMain']=True
        original(x,y,end_x,end_y,**kwargs)
    city.drag=drag
    state=navigate_city(city,city.observe,threading.Event(),city.clock,18)
    assert state.values['building_menu']['selected']['id']=='60'
    assert 'BattlePassMain' not in state.values['views']
