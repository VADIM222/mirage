from dataclasses import replace

import pytest

from mirage.adb import Adb
from mirage.emulators import CommandError
from mirage.model import Instance, Power, Provider


def device():
    return Instance("ld:one:1", Provider.LDPLAYER, "1", "Farm", "C:/LD", "adb", "127.0.0.1:5557",
                    Power.ONLINE, cpus=2, width=960, height=540)


def test_offline_instance_cannot_connect_to_other_provider_on_same_port(monkeypatch):
    calls = []
    monkeypatch.setattr("mirage.adb.run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(CommandError, match="не подтверждён"):
        Adb(replace(device(), power=Power.OFF, serial="127.0.0.1:5555")).connect()
    assert calls == []


def test_wrong_android_identity_blocks_connect_and_input(monkeypatch):
    adb = Adb(device())
    monkeypatch.setattr(adb, "_expected_identity", lambda: "0123456789abcdef")
    monkeypatch.setattr("mirage.adb.run", lambda *args, **kwargs: "connected")
    commands = []

    def shell(command, **kwargs):
        commands.append(command)
        return "uid=2000(shell)" if command == "id" else "fedcba9876543210"

    monkeypatch.setattr(adb, "shell", shell)
    with pytest.raises(CommandError, match="другому"):
        adb.connect()
    with pytest.raises(CommandError, match="другому"):
        adb.tap(860, 505)
    assert not any(command.startswith("input") for command in commands)


def test_port_reassigned_after_connect_blocks_tap(monkeypatch):
    adb = Adb(device())
    adb._android_id = "0123456789abcdef"
    commands = []
    def shell(command, **kwargs):
        commands.append(command)
        return "fedcba9876543210"
    monkeypatch.setattr(adb, "shell", shell)
    with pytest.raises(CommandError, match="другому"):
        adb.tap(10, 10)
    assert commands == ["settings get secure android_id"]


@pytest.mark.parametrize('block',['none','identity','permission'])
def test_back_key_checks_device_and_permission_before_any_input(monkeypatch,block):
    from mirage.workflows import Cancelled
    adb=Adb(device())
    adb._android_id='0123456789abcdef'
    commands=[]
    def shell(command,**kwargs):
        commands.append(command)
        return 'fedcba9876543210' if block=='identity' else '0123456789abcdef'
    def permit():
        if block=='permission':raise Cancelled('Paused')
    monkeypatch.setattr(adb,'shell',shell)
    if block=='none':
        adb.back(before_input=permit)
        assert commands==['settings get secure android_id','input keyevent 4']
    else:
        with pytest.raises(CommandError if block=='identity' else Cancelled):adb.back(before_input=permit)
        assert commands==['settings get secure android_id']


def test_held_tap_checks_identity_and_resolution_before_input(monkeypatch):
    adb = Adb(device())
    adb._android_id = "0123456789abcdef"
    commands = []
    def shell(command, **kwargs):
        commands.append(command)
        return "0123456789abcdef" if command.startswith("settings") else "Physical size: 960x540"
    monkeypatch.setattr(adb, "shell", shell)
    adb.tap(705, 267, hold_ms=100)
    assert commands == ["settings get secure android_id", "wm size", "input touchscreen swipe 705 267 705 267 100"]
    commands.clear()
    monkeypatch.setattr(adb, "shell", lambda command, **kwargs: "0123456789abcdef" if command.startswith("settings") else "Physical size: 540x960")
    with pytest.raises(CommandError, match="разрешение"):
        adb.tap(705, 267, hold_ms=100)


@pytest.mark.parametrize("action",["tap","drag"])
def test_stop_during_resolution_check_blocks_the_late_input(monkeypatch,action):
    from mirage.workflows import Cancelled
    adb = Adb(device())
    adb._android_id = "0123456789abcdef"
    commands = []
    stopped = [False]
    def shell(command, **kwargs):
        commands.append(command)
        if command == "wm size":
            stopped[0] = True
            return "Physical size: 960x540"
        return "0123456789abcdef"
    monkeypatch.setattr(adb,"shell",shell)
    def guard():
        if stopped[0]:
            raise Cancelled("stopped")
    with pytest.raises(Cancelled):
        if action == "tap":
            adb.tap(738,443,hold_ms=100,before_input=guard)
        else:
            adb.drag(600,400,520,400,before_input=guard)
    assert not any(command.startswith("input") for command in commands)


def test_city_drag_checks_identity_display_and_bounded_coordinates(monkeypatch):
    adb = Adb(device())
    adb._android_id = "0123456789abcdef"
    commands = []
    def shell(command,**kwargs):
        commands.append(command)
        return "0123456789abcdef" if command.startswith("settings") else "Physical size: 960x540"
    monkeypatch.setattr(adb,"shell",shell)
    adb.drag(600,400,520,400)
    assert commands == ["settings get secure android_id","wm size","input touchscreen swipe 600 400 520 400 300"]
    commands.clear()
    with pytest.raises(ValueError):
        adb.drag(600,400,1500,400)
    assert not commands


@pytest.mark.parametrize('stop_at',[None,'display','native'])
def test_moving_target_is_resolved_after_device_checks_and_stop_still_blocks_input(monkeypatch,stop_at):
    from mirage.workflows import Cancelled
    adb=Adb(device());adb._android_id='0123456789abcdef';commands=[];stopped=[False]
    def shell(command,**kwargs):
        commands.append(command)
        if command=='wm size':
            if stop_at=='display':stopped[0]=True
            return 'Physical size: 960x540'
        return '0123456789abcdef'
    monkeypatch.setattr(adb,'shell',shell)
    def resolve():
        assert commands==['settings get secure android_id','wm size']
        if stop_at=='native':stopped[0]=True
        return 735,233
    def permit():
        if stopped[0]:raise Cancelled('stopped')
    if stop_at:
        with pytest.raises(Cancelled):adb.tap_resolved(resolve,before_input=permit)
        assert not any(command.startswith('input') for command in commands)
    else:
        adb.tap_resolved(resolve,before_input=permit)
        assert commands[-1]=='input touchscreen swipe 735 233 735 233 100'


@pytest.mark.parametrize("replies,expected",[(["", "14465"],14465),(["14465"],14465),
    (["14465 14466"],None),(["", ""],None),(["0"],None),(["error"],None)])
def test_pid_lookup_retries_only_an_empty_read_and_never_accepts_ambiguity(monkeypatch,replies,expected):
    adb = Adb(device())
    answers = iter(replies)
    commands = []
    def shell(command,**kwargs):
        commands.append(command)
        return next(answers)
    monkeypatch.setattr(adb,"shell",shell)
    monkeypatch.setattr("mirage.adb.time.sleep",lambda duration:None)
    if expected is None:
        with pytest.raises(CommandError,match="pidof"):
            adb.pid()
    else:
        assert adb.pid() == expected
    assert commands == ["pidof com.lilithgame.roc.gp"]*len(replies)


@pytest.mark.parametrize("empty_output,returncode,absent",[(True,1,True),(False,1,False),(True,2,False),(True,None,False)])
def test_only_pidofs_documented_empty_exit_one_means_absence(monkeypatch,empty_output,returncode,absent):
    adb = Adb(device())
    def shell(*args,**kwargs):
        raise CommandError("failure",returncode=returncode,empty_output=empty_output)
    monkeypatch.setattr(adb,"shell",shell)
    if absent:
        assert adb.process_ids() == ()
    else:
        with pytest.raises(CommandError):
            adb.process_ids()
