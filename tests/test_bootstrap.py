import json
from types import SimpleNamespace
import threading

import pytest

from mirage.bootstrap import enter_game, start_game, startup_key
from mirage.model import Power
from mirage.workflows import Cancelled


def stage(name):
    return "I setBody : "+json.dumps({"log_type":"lgroleloading","key":name})


class Adb:
    def __init__(self):
        self.log = stage("FocusGainStateTapToStart")
        self.inputs = []
        self.removed = []
        self.foreground = "mResumedActivity: com.lilithgame.roc.gp/com.harry.engine.MainActivity t4"
        self.on_validation = lambda:None
    def verify_identity(self): pass
    def pid(self): return 10
    def forward(self,port): return 12345
    def remove_forward(self,port): self.removed.append(port)
    def shell(self,command,**kwargs):
        if command.startswith("logcat"):
            return self.log
        self.on_validation()
        return self.foreground
    def tap(self,x,y,*,hold_ms,before_input):
        before_input()
        self.inputs.append((x,y,hold_ms))


def setup(monkeypatch, inspections=None):
    adb = Adb()
    boot = {"pid":10,"module":True,"luaReady":False,"apiReady":False}
    answers = iter(inspections) if inspections else None
    class Script:
        exports_sync = SimpleNamespace(inspect=lambda:next(answers) if answers else boot)
        def load(self): pass
    class Session:
        closed = False
        def create_script(self,source): return Script()
        def detach(self): self.closed = True
    session = Session()
    manager = SimpleNamespace(add_remote_device=lambda address:SimpleNamespace(attach=lambda pid:session),
                              remove_remote_device=lambda address:None)
    monkeypatch.setattr("mirage.bootstrap.frida.get_device_manager",lambda:manager)
    reader = SimpleNamespace(adb=adb,pid=10,version="1.1.12.20",instance=SimpleNamespace(width=960,height=540))
    return reader,session,boot


def test_entry_requires_native_pre_lua_proof_and_is_reserved_only_once(monkeypatch):
    reader,session,boot = setup(monkeypatch)
    attempted = set()
    result = enter_game(reader,threading.Event(),lambda:True,attempted)
    assert result.tapped and reader.adb.inputs == [(480,450,100)]
    assert attempted == {10} and session.closed and reader.adb.removed == [12345]
    assert not enter_game(reader,threading.Event(),lambda:True,attempted).tapped
    assert reader.adb.inputs == [(480,450,100)]


@pytest.mark.parametrize("field,value",[("luaReady",True),("apiReady",True),("module",False)])
def test_startup_logs_cannot_authorize_input_after_lua_or_before_the_module_loads(monkeypatch,field,value):
    boot = {"pid":10,"module":True,"luaReady":False,"apiReady":False,field:value}
    reader,session,_ = setup(monkeypatch,[boot])
    assert not enter_game(reader,threading.Event(),lambda:True,set()).tapped
    assert not reader.adb.inputs and session.closed


def test_a_later_loading_stage_invalidates_an_old_tap_to_start_event(monkeypatch):
    reader,_,_ = setup(monkeypatch)
    reader.adb.log += "\n"+stage("FocusGainStateAccountSelection")
    assert not enter_game(reader,threading.Event(),lambda:True,set()).tapped
    assert not reader.adb.inputs


def test_background_game_and_wrong_foreground_activity_block_entry(monkeypatch):
    reader,_,_ = setup(monkeypatch)
    reader.adb.foreground = "com.android.settings/.Settings"
    assert not enter_game(reader,threading.Event(),lambda:True,set()).tapped
    assert not reader.adb.inputs


def test_state_change_during_adb_validation_blocks_the_late_entry_tap(monkeypatch):
    first = {"pid":10,"module":True,"luaReady":False,"apiReady":False}
    reader,session,_ = setup(monkeypatch,[first,{**first,"luaReady":True}])
    with pytest.raises(Cancelled):
        enter_game(reader,threading.Event(),lambda:True,set())
    assert not reader.adb.inputs and session.closed


def test_stop_during_foreground_validation_blocks_input(monkeypatch):
    reader,session,_ = setup(monkeypatch)
    cancelled = threading.Event()
    reader.adb.on_validation = cancelled.set
    with pytest.raises(Cancelled):
        enter_game(reader,cancelled,lambda:True,set())
    assert not reader.adb.inputs and session.closed


def test_sdk_payloads_do_not_become_the_recorded_startup_state():
    assert startup_key("not json\nI setBody : {}") is None
    assert startup_key(stage("FocusGainStateTapToStart")+"\nI setBody : "+json.dumps({
        "key":"unrelated","log_type":"another_event","private_field":"not retained"})) == "FocusGainStateTapToStart"


class LauncherAdb:
    def __init__(self):
        self.pids = ["",""]
        self.processes = "PID NAME\n1 init\n2 kthreadd\n643 [SquashFS read w]"
        self.component = "com.lilithgame.roc.gp/com.harry.engine.MainActivity"
        self.actions = []
        self.on_ps = lambda:None
    def verify_identity(self): pass
    def process_ids(self):
        return tuple(map(int,self.shell("pidof com.lilithgame.roc.gp").split()))
    def shell(self,command):
        if command.startswith("pidof"):
            return self.pids.pop(0)
        if command.startswith("ps "):
            self.on_ps()
            return self.processes
        if command.startswith("cmd package"):
            return self.component
        self.actions.append(command)
        return "Starting: Intent"


def launcher():
    return SimpleNamespace(version="1.1.12.20",adb=LauncherAdb(),
        instance=SimpleNamespace(id="one",power=Power.ONLINE,width=960,height=540))


def test_absent_game_is_started_once_without_any_emulator_launch():
    reader = launcher()
    attempted = set()
    result = start_game(reader,threading.Event(),lambda:True,attempted)
    assert result.launched and not result.tapped and attempted == {"one"}
    assert reader.adb.actions == ["am start -n com.lilithgame.roc.gp/com.harry.engine.MainActivity"]
    assert not start_game(reader,threading.Event(),lambda:True,attempted).launched


@pytest.mark.parametrize("source",["pid","ps"])
def test_empty_or_ambiguous_pidof_cannot_override_an_existing_process(source):
    reader = launcher()
    if source == "pid":
        reader.adb.pids = ["123 124"]
    else:
        reader.adb.processes += "\n123 com.lilithgame.roc.gp"
    assert not start_game(reader,threading.Event(),lambda:True,set()).launched
    assert not reader.adb.actions


def test_a_game_that_appears_during_validation_is_not_launched_again():
    reader = launcher()
    reader.adb.pids = ["","123"]
    assert not start_game(reader,threading.Event(),lambda:True,set()).launched
    assert not reader.adb.actions


def test_unknown_package_entry_and_offline_emulator_block_game_start():
    reader = launcher()
    reader.adb.component = "com.other.game/.Activity"
    with pytest.raises(ValueError):
        start_game(reader,threading.Event(),lambda:True,set())
    assert not reader.adb.actions
    reader = launcher()
    reader.instance.power = Power.OFF
    with pytest.raises(ValueError):
        start_game(reader,threading.Event(),lambda:True,set())
    assert not reader.adb.actions


def test_manual_pause_during_process_validation_blocks_the_launch_command():
    reader = launcher()
    cancelled = threading.Event()
    reader.adb.on_ps = cancelled.set
    with pytest.raises(Cancelled):
        start_game(reader,cancelled,lambda:True,set())
    assert not reader.adb.actions
