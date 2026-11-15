from dataclasses import replace
import threading
import time

import pytest

from mirage.controller import Controller
from mirage.model import Instance, Power, Profile, Provider
from mirage.storage import Store
from mirage.workflows import CITY_HUD, Cancelled, NotReady, RETURN_TO_CITY
from test_rewards import Game, execute


class ReturnGame(Game):
    def __init__(self,enabled):
        super().__init__()
        self.values.update(in_city=False,city_enabled=enabled,alliance_help_count=0)
        self.after_tap=lambda:None

    def tap(self,x,y,*,hold_ms=0):
        assert (x,y,hold_ms)==(45,490,100)
        self.taps.append((x,y))
        if self.values['city_enabled']:
            self.values['city_enabled']=False
        else:self.values.update(city_enabled=True,in_city=True)
        self.after_tap()


@pytest.mark.parametrize('enabled,count',[(False,1),(True,2)])
def test_world_map_and_city_outskirts_return_via_distinct_verified_transitions(enabled,count):
    game=ReturnGame(enabled)
    assert CITY_HUD.matches(execute(game,RETURN_TO_CITY))
    assert len(game.taps)==count
    execute(game,RETURN_TO_CITY)
    assert len(game.taps)==count


@pytest.mark.parametrize('block',['modal','selection','queue','unknown_mode'])
def test_city_return_never_toggles_an_unknown_or_obstructed_hud(block):
    game=ReturnGame(False)
    if block=='modal':game.overlay='UnknownModal'
    elif block=='selection':game.values['city_selection']='17'
    elif block=='queue':game.values['queue_panel']['visible']=True
    else:game.values['city_enabled']=None
    with pytest.raises(NotReady):execute(game,RETURN_TO_CITY)
    assert not game.taps


def test_cancel_after_outskirts_zoom_prevents_the_second_click():
    game=ReturnGame(True)
    cancelled=threading.Event()
    game.after_tap=cancelled.set
    with pytest.raises(Cancelled):execute(game,RETURN_TO_CITY,cancelled)
    assert len(game.taps)==1 and not game.values['in_city']


def test_world_over_own_city_is_not_a_city_scene_even_while_is_in_my_city_is_true():
    game=ReturnGame(False)
    game.values['in_city']=True
    assert not CITY_HUD.matches(game.snapshot())
    assert CITY_HUD.matches(execute(game,RETURN_TO_CITY))
    assert len(game.taps)==1


@pytest.mark.parametrize('pause',[False,True])
@pytest.mark.parametrize('own_city_world',[False,True])
def test_controller_recovers_city_before_help_but_respects_pause_during_recovery(tmp_path,qtbot,pause,own_city_world):
    store=Store(tmp_path/'mirage.sqlite3')
    controller=Controller(store,auto_refresh=False)
    key='ld:test:1'
    controller.instances=[Instance(key,Provider.LDPLAYER,'1','Farm','C:/LD','adb','127.0.0.1:5557',
        Power.ONLINE,cpus=2,memory_mb=2048,width=960,height=540)]
    store.save_profile(Profile(key,manual_run=True,tasks={'alliance_help':{'enabled':True,'interval':86400}}))
    game=ReturnGame(True)
    if own_city_world:game.values.update(in_city=True,city_enabled=False)
    if pause:
        def stop():store.update_profile(key,lambda p:(setattr(p,'manual_pause',True),setattr(p,'manual_run',False)))
        game.after_tap=stop
    class Adb:
        def tap(self,x,y,*,before_input,**kwargs):before_input();game.tap(x,y,**kwargs)
    class Reader:
        adb=Adb()
        def snapshot(self,extra_paths=None):
            return replace(game.snapshot(),instance_id=key,captured_at=time.monotonic())
        def close(self):pass
    reader=Reader()
    controller.readers[key]=reader
    controller.snapshots[key]=reader.snapshot()
    controller._last_memory_poll=time.monotonic()
    try:
        controller.tick()
        qtbot.waitUntil(lambda:not controller.dispatcher.busy(key),timeout=10000)
        assert len(game.taps)==(1 if pause or own_city_world else 2)
        assert not controller._task_errors
        if pause:assert (key,'alliance_help') not in controller._due
        else:
            assert controller._due[(key,'alliance_help')]>time.monotonic()
            assert game.values['in_city']
    finally:controller.shutdown()
