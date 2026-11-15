from __future__ import annotations

import hashlib
from pathlib import Path
import shlex

from .adb import Adb
from .model import Instance, Power


FRIDA_VERSION = "17.26.2"
FRIDA_SERVER_SHA256 = "c671eee6c39d15e57782715ff22029828a68e23c51d5c571d99080a7f6564fe6"
FRIDA_SERVER_URL = "https://github.com/frida/frida/releases/download/17.26.2/frida-server-17.26.2-android-x86_64.xz"
FRIDA_ARCHIVE_SHA256 = "1f03e1bd3800618f6e6b4a978b84a7d093a2bdefd42722eb3f27e4c3bbfd2139"
REMOTE_PATH = "/data/local/tmp/mirage-frida-server"


def install(instance: Instance, file: Path) -> str:
    if instance.power != Power.ONLINE:
        raise RuntimeError("Для установки runtime нужен работающий эмулятор")
    with file.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != FRIDA_SERVER_SHA256:
        raise ValueError("SHA-256 файла отличается от закреплённого Frida Server 17.26.2 x86_64")
    adb = Adb(instance)
    adb.connect()
    root = adb.root()
    if adb.shell("getprop ro.product.cpu.abi").strip() != "x86_64":
        raise RuntimeError("Этот runtime предназначен для Android x86_64")
    temporary = REMOTE_PATH + ".upload"
    adb.command("push", str(file), temporary, timeout=60)
    adb.root_shell(root, f"chmod 755 {shlex.quote(temporary)} && mv {shlex.quote(temporary)} {shlex.quote(REMOTE_PATH)}")
    actual = adb.root_shell(root, REMOTE_PATH + " --version").strip()
    if actual != FRIDA_VERSION:
        raise RuntimeError("Установленный Android runtime не подтвердил ожидаемую версию")
    return f"Frida Server {actual} установлен: {REMOTE_PATH}"
