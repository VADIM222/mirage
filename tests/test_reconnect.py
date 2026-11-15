"""Recovery exercises the real controller/engine while replacing only the device."""
import time

import pytest

from mirage.controller import Controller
from mirage.emulators import CommandError
from mirage.model import Instance, Power, Profile, Provider, RunState, Snapshot
from mirage.memory import MemoryError
from mirage.storage import Store


@pytest.fixture
def session(tmp_path, monkeypatch):
    store = Store(tmp_path / "mirage.sqlite3")
    controller = Controller(store, auto_refresh=False)
    key = "ld:test:1"
    controller.instances = [Instance(key,Provider.LDPLAYER,"1","Farm","C:/LD","adb","127.0.0.1:5557",
        Power.ONLINE,cpus=2,memory_mb=2048,width=960,height=540)]
    store.save_profile(Profile(key,manual_run=True,tasks={"alliance_help":{"enabled":True,"interval":86400}}))
    values = {"player":{"PlayerID":20,"AllianceID":10},"hud_visible":True,"hud_menu":False,
        "queue_panel":{"known":True,"visible":False},"city_selection_known":True,"city_selection":None,
        "vip_visible":False,"in_city":True,"city_enabled":True,"views":{"MapHudPanel":True},"alliance_help_count":0}
    class Reader:
        adb = object()  # No input is allowed during reconnection or a completed help check.
        def __init__(self, player=20, failure=False):
            self.player = player
            self.failure = failure
            self.script = object()
            self.instance = controller.instances[0]
            self.closed = False
        def snapshot(self):
            if self.failure:
                raise CommandError("pidof: empty response")
            return Snapshot(key,10,self.player,time.monotonic(),"1.1.12.20",values)
        def connect(self):
            self.script = object()
        def close(self):
            self.closed = True
            self.script = None
    failed = Reader(failure=True)
    controller.readers[key] = failed
    controller.snapshots[key] = Reader().snapshot()
    controller._last_memory_poll = controller._last_discovery = time.monotonic()
    controller._auto_refresh = True
    monkeypatch.setattr("mirage.controller.Reader", lambda *args:Reader())
    yield controller,store,key,Reader,failed
    controller.shutdown()


def lose_connection(controller,key,qtbot):
    controller.tick()
    qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
    assert key not in controller.snapshots
    assert key not in controller.readers


def test_transient_read_loss_reconnects_to_same_player_without_spending_task_interval(session,qtbot):
    controller,store,key,Reader,failed = session
    lose_connection(controller,key,qtbot)
    assert failed.closed
    assert controller._reconnect_player[key] == 20
    assert key not in controller._task_errors
    assert (key,"alliance_help") not in controller._due
    controller.tick()
    assert not controller.dispatcher.busy(key)  # Backoff applies before the next connection.
    controller._retry_at[key] = 0
    controller.tick()
    qtbot.waitUntil(lambda:key in controller.snapshots)
    assert controller.snapshots[key].player_id == 20
    controller.tick()
    qtbot.waitUntil(lambda:controller._due.get((key,"alliance_help"),0)>time.monotonic())
    assert key not in controller._reconnect_attempts
    assert key not in controller._reconnect_player
    assert not any(row[3] == "error" for row in store.events())


def test_different_player_never_receives_input_and_reconnects_are_bounded(session,qtbot,monkeypatch):
    controller,store,key,Reader,failed = session
    lose_connection(controller,key,qtbot)
    readers = []
    def other_player(*args):
        reader = Reader(player=99)
        readers.append(reader)
        return reader
    monkeypatch.setattr("mirage.controller.Reader",other_player)
    for _ in range(3):
        controller._retry_at[key] = 0
        controller.tick()
        qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
        assert key not in controller.snapshots
    assert len(readers) == 3 and all(reader.closed for reader in readers)
    assert "другой персонаж" in controller._task_errors[key]
    controller.tick()
    assert controller.decisions[key].state == RunState.ERROR
    assert not controller.dispatcher.busy(key)
    assert (key,"alliance_help") not in controller._due


def test_manual_pause_during_backoff_prevents_automatic_reconnect(session,qtbot):
    controller,store,key,Reader,failed = session
    lose_connection(controller,key,qtbot)
    controller.stop(key)
    controller._retry_at[key] = 0
    controller.tick()
    assert controller.decisions[key].state == RunState.PAUSED
    assert not controller.dispatcher.busy(key)
    assert key not in controller.snapshots


def test_idle_memory_poll_keeps_the_player_identity_when_its_connection_is_lost(session,qtbot):
    controller,store,key,Reader,failed = session
    controller.probe(key)
    qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
    assert failed.closed
    assert controller._reconnect_player[key] == 20
    assert key not in controller.snapshots
    assert not any(row[3] == "error" for row in store.events())


def test_connecting_without_completing_a_task_does_not_reset_the_recovery_budget(session,qtbot,monkeypatch):
    controller,store,key,Reader,failed = session
    lose_connection(controller,key,qtbot)
    class FlakyReader(Reader):
        def __init__(self):
            super().__init__()
            self.calls = 0
        def snapshot(self):
            self.calls += 1
            if self.calls > 1:
                raise CommandError("connection lost again")
            return super().snapshot()
    monkeypatch.setattr("mirage.controller.Reader",lambda *args:FlakyReader())
    for _ in range(3):
        controller._retry_at[key] = 0
        controller.tick()
        qtbot.waitUntil(lambda:key in controller.snapshots)
        controller.tick()
        qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
        assert key not in controller.snapshots
    assert key in controller._task_errors
    assert (key,"alliance_help") not in controller._due


def test_loading_entry_preserves_expected_character_and_has_a_bounded_deadline(session,qtbot,monkeypatch):
    from mirage.bootstrap import EntryResult
    controller,store,key,Reader,failed = session
    class BootReader(Reader):
        def snapshot(self):
            raise MemoryError("Lua API is not initialized: gettop")
    controller.readers[key] = BootReader()
    entries = []
    def enter(reader,cancelled,allowed,attempted):
        assert allowed()
        entries.append(True)
        return EntryResult(10,True,"Ожидание игрового мира")
    monkeypatch.setattr("mirage.bootstrap.enter_game",enter)
    controller.probe(key)
    qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
    assert entries == [True] and controller._reconnect_player[key] == 20
    assert key not in controller.snapshots and key not in controller._task_errors
    controller._entry_started[key] = time.monotonic()-181
    monkeypatch.setattr("mirage.controller.Reader",lambda *args:BootReader())
    controller._retry_at[key] = 0
    controller.tick()
    qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
    assert "180 секунд" in controller._task_errors[key]
    assert entries == [True]


def test_missing_game_launch_keeps_the_previous_character_pin(session,qtbot,monkeypatch):
    from mirage.bootstrap import EntryResult
    controller,store,key,Reader,failed = session
    class MissingReader(Reader):
        def snapshot(self):
            raise CommandError("Игровой процесс не запущен или неоднозначен (pidof: пустой ответ)")
    controller.readers[key] = MissingReader()
    launches = []
    def launch(reader,cancelled,allowed,attempted):
        assert allowed()
        attempted.add(key)
        launches.append(True)
        return EntryResult(0,False,"Игра запущена",launched=True)
    monkeypatch.setattr("mirage.bootstrap.start_game",launch)
    controller.probe(key)
    qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
    assert launches == [True]
    assert controller._reconnect_player[key] == 20 and key in controller._game_launch_attempted
    assert key not in controller.snapshots and (key,"alliance_help") not in controller._due
