from dataclasses import replace
import threading
import time

import pytest

from mirage.controller import Controller
from mirage.model import Instance, Power, Profile, Provider
from mirage.recovery import DISMISS_BATTLE_PASS
from mirage.storage import Store
from mirage.workflows import CITY_HUD, Cancelled, NotReady, Procedure, VERIFIED_WORKFLOWS, Workflow, WorkflowError
from test_rewards import Game, execute


class BattlePass(Game):
    def __init__(self):
        super().__init__()
        self.overlay='BattlePassMain'
        self.values.update(battle_pass_visible=True,resources={str(i):10000 for i in range(1,7)},alliance_help_count=0)
        self.backs=0
        self.after_back=lambda:None

    def back(self):
        self.backs+=1
        self.overlay=None
        self.values['battle_pass_visible']=False
        self.values['queue_panel']['known']=True
        self.after_back()


def test_verified_lucerne_screen_is_closed_once_even_if_hud_activity_was_hidden():
    game=BattlePass()
    game.values['queue_panel'].update(known=False,visible=None)
    def close():game.values['queue_panel']['visible']=False
    game.after_back=close
    assert CITY_HUD.matches(execute(game,DISMISS_BATTLE_PASS))
    assert game.backs==1 and game.taps==[]
    execute(game,DISMISS_BATTLE_PASS)
    assert game.backs==1


def test_other_modal_windows_are_never_dismissed_by_the_lucerne_recovery():
    game=BattlePass()
    original=game.snapshot
    def snapshot():
        state=original();state.values['views']['UnknownPurchasePage']=True;return state
    game.snapshot=snapshot
    with pytest.raises(NotReady):execute(game,DISMISS_BATTLE_PASS)
    assert game.backs==0


def test_cancellation_after_back_never_repeats_it():
    game=BattlePass()
    cancelled=threading.Event()
    game.after_back=cancelled.set
    with pytest.raises(Cancelled):execute(game,DISMISS_BATTLE_PASS,cancelled)
    assert game.backs==1


def test_currency_changes_cannot_confirm_a_screen_dismissal():
    game=BattlePass()
    game.after_back=lambda:game.values['resources'].update({'5':9999})
    with pytest.raises(WorkflowError):execute(game,DISMISS_BATTLE_PASS)
    assert game.backs==1


@pytest.mark.parametrize('mode',['normal','pause','world_task'])
def test_controller_recovers_a_known_screen_only_for_city_tasks(tmp_path,qtbot,monkeypatch,mode):
    store=Store(tmp_path/'mirage.sqlite3')
    controller=Controller(store,auto_refresh=False)
    key='ld:test:1'
    controller.instances=[Instance(key,Provider.LDPLAYER,'1','Farm','C:/LD','adb','127.0.0.1:5557',
        Power.ONLINE,cpus=2,memory_mb=2048,width=960,height=540)]
    store.save_profile(Profile(key,manual_run=True,tasks={'alliance_help':{'enabled':True,'interval':86400}}))
    game=BattlePass()
    if mode=='pause':
        def pause():store.update_profile(key,lambda p:(setattr(p,'manual_pause',True),setattr(p,'manual_run',False)))
        game.after_back=pause
    if mode=='world_task':
        def noop(device,observe,cancelled,clock,allowed):return observe()
        monkeypatch.setitem(VERIFIED_WORKFLOWS,'alliance_help',
            Workflow('alliance_help','1.1.12.20',960,540,(Procedure(noop),),verified=True,requires_city=False))
    class Adb:
        def back(self,*,before_input):before_input();game.back()
    class Reader:
        adb=Adb()
        def snapshot(self,extra_paths=None):return replace(game.snapshot(),instance_id=key,captured_at=time.monotonic())
        def close(self):pass
    reader=Reader()
    controller.readers[key]=reader;controller.snapshots[key]=reader.snapshot()
    controller._last_memory_poll=time.monotonic()
    try:
        controller.tick()
        qtbot.waitUntil(lambda:not controller.dispatcher.busy(key),timeout=5000)
        assert game.backs==(0 if mode=='world_task' else 1)
        assert not controller._task_errors
        if mode=='pause':assert (key,'alliance_help') not in controller._due
        else:assert controller._due[(key,'alliance_help')]>time.monotonic()
    finally:controller.shutdown()
