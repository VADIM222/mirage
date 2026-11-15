"""Pre-Lua entry: native lifecycle proof plus the process's own startup transition."""
from dataclasses import dataclass
import json
import re

import frida

from .emulators import CommandError
from .memory import SUPPORTED_VERSIONS
from .model import Power
from .workflows import Cancelled


BOOT_SOURCE = """
rpc.exports.inspect=function(){
 const module=Process.findModuleByName('libEz.so');
 if(module===null)return {pid:Process.id,module:false,luaReady:false,apiReady:false};
 return {pid:Process.id,module:true,
  luaReady:!module.getExportByName('_ZN2ez3lua1LE').readPointer().isNull(),
  apiReady:!module.getExportByName('_ZN2ez3lua6gettopE').readPointer().isNull()};
};
"""


def startup_key(log: str) -> str | None:
    """Extract only stage keys, never retain account/SDK payloads."""
    key = None
    for line in log.splitlines():
        if "setBody : " not in line:
            continue
        try:
            payload = json.loads(line.split("setBody : ",1)[1])
        except (ValueError,TypeError):
            continue
        if isinstance(payload,dict) and payload.get("log_type") == "lgroleloading":
            value = payload.get("key")
            if isinstance(value,str):
                key = value
    return key


def loading_error(error: Exception) -> bool:
    text = str(error)
    return any(marker in text for marker in ("Lua API is not initialized:",
        "unable to find module 'libEz.so'", "Lua-состояние ещё не создано",
        "Состояние персонажа ещё не доступно", "Не подтверждён ID персонажа",
        "Не получены актуальные игровые часы"))


@dataclass(frozen=True)
class EntryResult:
    pid: int
    tapped: bool
    reason: str
    launched: bool = False


def missing_process(error: Exception) -> bool:
    return isinstance(error,CommandError) and "Игровой процесс не запущен или неоднозначен (pidof: пустой ответ)" in str(error)


def process_absent(adb) -> bool:
    if adb.process_ids():
        return False
    rows = adb.shell("ps -A -o PID,NAME").splitlines()
    if not rows or rows[0].split() != ["PID","NAME"]:
        raise ValueError("Не подтверждён список процессов Android")
    for row in rows[1:]:
        pieces = row.split(maxsplit=1)
        if len(pieces) != 2 or not re.fullmatch(r"[1-9][0-9]*",pieces[0]):
            raise ValueError("Неоднозначный список процессов Android")
        if pieces[1] == "com.lilithgame.roc.gp" or pieces[1].startswith("com.lilithgame.roc.gp:"):
            return False
    return True


def start_game(reader,cancelled,allowed,attempted: set[str]) -> EntryResult:
    """Start the installed game once; absent PID must also agree with Android ps."""
    if (reader.instance.power != Power.ONLINE or reader.version not in SUPPORTED_VERSIONS
            or (reader.instance.width,reader.instance.height) != (960,540)):
        raise ValueError("Запуск игры несовместим с проверенным профилем")
    key = reader.instance.id
    if cancelled.is_set() or not allowed():
        raise Cancelled("Запуск игры отменён")
    if key in attempted:
        return EntryResult(0,False,"Ожидание запущенной игры")
    adb = reader.adb
    adb.verify_identity()
    if not process_absent(adb):
        return EntryResult(0,False,"Ожидание подключения к процессу игры")
    rows = adb.shell("cmd package resolve-activity --brief com.lilithgame.roc.gp").splitlines()
    component = rows[-1].strip() if rows else ""
    if not re.fullmatch(r"com\.lilithgame\.roc\.gp/com\.harry\.engine\.MainActivity",component):
        raise ValueError("Не подтверждена точка запуска установленной игры")
    adb.verify_identity()
    if not process_absent(adb):
        return EntryResult(0,False,"Игра уже запускается; ожидание памяти")
    if cancelled.is_set() or not allowed():
        raise Cancelled("Запуск игры отменён перед командой")
    attempted.add(key)
    adb.shell("am start -n "+component)
    return EntryResult(0,False,"Игра запущена; ожидание стартового экрана",launched=True)


def entry_permitted(boot: dict, pid: int, stage: str | None, foreground: str) -> bool:
    return (type(pid) is int and pid > 0 and boot.get("pid") == pid and boot.get("module") is True
        and boot.get("luaReady") is False and boot.get("apiReady") is False
        and stage == "FocusGainStateTapToStart"
        and re.search(r"\bcom\.lilithgame\.roc\.gp/com\.harry\.engine\.MainActivity\b",foreground) is not None)


def enter_game(reader, cancelled, allowed, attempted: set[int]) -> EntryResult:
    """Only enter an already running, supported game. Never launch an emulator."""
    adb = reader.adb
    if reader.version not in SUPPORTED_VERSIONS or (reader.instance.width,reader.instance.height) != (960,540):
        raise ValueError("Стартовый экран несовместим с проверенным профилем")
    def permit():
        if cancelled.is_set() or not allowed():
            raise Cancelled("Вход в игру отменён")
    permit()
    adb.verify_identity()
    pid = adb.pid()
    if pid != reader.pid:
        raise ValueError("Стартовый процесс изменился")
    if pid in attempted:
        return EntryResult(pid,False,"Ожидание игрового мира после входа")
    address = None
    port = None
    session = None
    try:
        port = adb.forward(27183)
        address = f"127.0.0.1:{port}"
        device = frida.get_device_manager().add_remote_device(address)
        session = device.attach(pid)
        script = session.create_script(BOOT_SOURCE)
        script.load()
        boot = script.exports_sync.inspect()
        if boot.get("pid") != pid:
            raise ValueError("Стартовое состояние принадлежит другому процессу")
        if boot.get("module") is not True or boot.get("luaReady") is not False or boot.get("apiReady") is not False:
            return EntryResult(pid,False,"Ожидание загрузки игрового мира")
        # logcat is PID-filtered. A later loading stage invalidates the start proof.
        stage = startup_key(adb.shell(f"logcat -d --pid={pid} -t 1800",timeout=15))
        foreground = adb.shell("dumpsys activity activities | grep mResumedActivity")
        if not entry_permitted(boot,pid,stage,foreground):
            return EntryResult(pid,False,"Ожидание подтверждённого стартового экрана")
        def before_input():
            permit()
            latest = startup_key(adb.shell(f"logcat -d --pid={pid} -t 1800",timeout=15))
            if adb.pid() != pid or not entry_permitted(script.exports_sync.inspect(),pid,latest,
                    adb.shell("dumpsys activity activities | grep mResumedActivity")):
                raise Cancelled("Стартовое состояние изменилось перед входом")
            permit()
            # Reserve before the ADB command: an uncertain command result must not cause a second tap.
            attempted.add(pid)
        adb.tap(480,450,hold_ms=100,before_input=before_input)
        return EntryResult(pid,True,"Вход подтверждён; ожидание игрового мира")
    finally:
        if session is not None:
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass
        if address is not None:
            try:
                frida.get_device_manager().remove_remote_device(address)
            except frida.InvalidArgumentError:
                pass
        if port is not None:
            try:
                adb.remove_forward(port)
            except CommandError:
                pass
