from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
import socket
import os
import time
from typing import Callable
from pathlib import Path

from .emulators import CommandError, parse_bs_config, parse_ld_list, run
from .model import Instance, Power, Provider


@dataclass(frozen=True)
class RootAccess:
    command: str
    output: str


class Adb:
    def __init__(self, instance: Instance):
        self.instance = instance
        # Vendor clients use dedicated ports, never replace a user's global server.
        self.server_port = 15041 if instance.provider == Provider.BLUESTACKS else 15042
        self._android_id: str | None = None

    def command(self, *arguments: str, timeout: float = 15, binary: bool = False):
        return run([self.instance.adb_path, "-P", str(self.server_port), "-s", self.instance.serial,
                    *arguments], timeout=timeout, binary=binary)

    def connect(self) -> None:
        self._android_id = None
        if self.instance.power != Power.ONLINE:
            raise CommandError("Эмулятор не подтверждён как работающий")
        expected = self._expected_identity()
        result = run([self.instance.adb_path, "-P", str(self.server_port), "connect", self.instance.serial], timeout=10)
        if "unable" in result.lower() or "failed" in result.lower() or "cannot" in result.lower():
            raise CommandError(result)
        if "uid=" not in self.shell("id"):
            raise CommandError("ADB не подтвердил подключение к Android")
        self._android_id = expected
        self.verify_identity()

    def _expected_identity(self) -> str:
        if self.instance.provider == Provider.BLUESTACKS:
            config_path = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "BlueStacks_nxt" / "bluestacks.conf"
            config = parse_bs_config(config_path.read_text(encoding="utf-8-sig"))
            expected = config.get(f"bst.instance.{self.instance.key}.android_id", "")
        else:
            console = str(Path(self.instance.install_dir) / "ldconsole.exe")
            instances = parse_ld_list(run([console, "list2"], timeout=8), Path(self.instance.install_dir))
            if not any(i.key == self.instance.key and i.power == Power.ONLINE for i in instances):
                raise CommandError("Выбранный экземпляр LDPlayer уже выключен")
            # The console resolves the exact instance, independent of a guessed TCP port.
            expected = run([console, "adb", "--index", self.instance.key, "--command",
                            "shell settings get secure android_id"], timeout=10).strip()
        if not re.fullmatch(r"[0-9a-fA-F]{16}", expected):
            raise CommandError("Не удалось подтвердить Android ID выбранного экземпляра")
        return expected.lower()

    def verify_identity(self) -> None:
        if self._android_id is None:
            raise CommandError("Сначала подтвердите ADB-подключение к выбранному экземпляру")
        actual = self.shell("settings get secure android_id", timeout=5).strip().lower()
        if actual != self._android_id:
            raise CommandError("ADB-порт принадлежит другому Android-устройству; обновите список эмуляторов")

    def shell(self, command: str, *, timeout: float = 15) -> str:
        return self.command("shell", command, timeout=timeout)

    def root(self) -> RootAccess:
        self.verify_identity()
        direct = self.shell("id")
        if re.search(r"\buid=0\(", direct):
            return RootAccess("", direct)
        for binary in ("su", "/system/xbin/bstk/su", "/system/xbin/su", "/system/bin/su"):
            try:
                output = self.shell(f"{shlex.quote(binary)} -c id", timeout=5)
                if re.search(r"\buid=0\(", output):
                    return RootAccess(binary, output)
            except CommandError:
                continue
        raise CommandError("Root-доступ не подтверждён ни одним доступным su")

    def root_shell(self, root: RootAccess, command: str, *, timeout: float = 15) -> str:
        self.verify_identity()
        return self.shell(f"{shlex.quote(root.command)} -c {shlex.quote(command)}" if root.command else command,
                          timeout=timeout)

    def screenshot(self) -> bytes:
        self.verify_identity()
        result = self.command("exec-out", "screencap", "-p", timeout=10, binary=True)
        if not result.startswith(b"\x89PNG\r\n\x1a\n"):
            raise CommandError("Android вернул некорректный снимок экрана")
        return result

    def tap(self, x: int, y: int, *, hold_ms: int = 0, before_input: Callable[[], None] | None = None) -> None:
        if hold_ms not in (0, 100, 800):
            raise ValueError("Неподдерживаемая длительность нажатия")
        self.verify_identity()
        if not 0 <= x < self.instance.width or not 0 <= y < self.instance.height:
            raise ValueError("Координаты нажатия находятся вне экрана")
        output = self.shell("wm size", timeout=5)
        dimensions = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", output)
        if not dimensions or tuple(map(int, dimensions[-1])) != (self.instance.width, self.instance.height):
            raise CommandError("Текущее разрешение Android отличается от профиля действий")
        command = (f"input touchscreen swipe {int(x)} {int(y)} {int(x)} {int(y)} {hold_ms}"
                   if hold_ms else f"input tap {int(x)} {int(y)}")
        if before_input is not None:
            before_input()
        self.shell(command, timeout=5)

    def drag(self, x: int, y: int, end_x: int, end_y: int, *, duration_ms: int = 300,
             before_input: Callable[[], None] | None = None) -> None:
        if duration_ms != 300 or any(type(value) is not int for value in (x,y,end_x,end_y)):
            raise ValueError("Неподдерживаемый жест перемещения города")
        if any(not 0 <= px < self.instance.width or not 0 <= py < self.instance.height
               for px,py in ((x,y),(end_x,end_y))):
            raise ValueError("Координаты жеста находятся вне экрана")
        self.verify_identity()
        dimensions = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)",self.shell("wm size",timeout=5))
        if not dimensions or tuple(map(int,dimensions[-1])) != (self.instance.width,self.instance.height):
            raise CommandError("Текущее разрешение Android отличается от профиля действий")
        if before_input is not None:
            before_input()
        self.shell(f"input touchscreen swipe {x} {y} {end_x} {end_y} {duration_ms}",timeout=5)

    def tap_resolved(self, resolve: Callable[[], tuple[int, int]], *, hold_ms: int = 100,
                     before_input: Callable[[], None] | None = None) -> None:
        """Resolve a moving native target after the slower device checks."""
        if hold_ms not in (100,800):raise ValueError("Неподдерживаемая длительность нажатия")
        self.verify_identity()
        dimensions=re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)",self.shell("wm size",timeout=5))
        if not dimensions or tuple(map(int,dimensions[-1]))!=(self.instance.width,self.instance.height):
            raise CommandError("Текущее разрешение Android отличается от профиля действий")
        if before_input is not None:before_input()
        x,y=resolve()
        if type(x) is not int or type(y) is not int or not 0<=x<self.instance.width or not 0<=y<self.instance.height:
            raise ValueError("Координаты нажатия находятся вне экрана")
        if before_input is not None:before_input()
        self.shell(f"input touchscreen swipe {x} {y} {x} {y} {hold_ms}",timeout=5)

    def back(self, *, before_input: Callable[[], None] | None = None) -> None:
        self.verify_identity()
        if before_input is not None:
            before_input()
        self.shell("input keyevent 4",timeout=5)

    def process_ids(self, package: str = "com.lilithgame.roc.gp") -> tuple[int, ...]:
        if not re.fullmatch(r"[\w.]+", package):
            raise ValueError("Некорректное имя пакета")
        try:
            text = self.shell(f"pidof {package}").strip()
        except CommandError as error:
            if error.returncode == 1 and error.empty_output:
                return ()
            raise
        if not text:
            return ()
        if not re.fullmatch(r"[1-9][0-9]*(?:\s+[1-9][0-9]*)*",text):
            raise CommandError("Игровой процесс не запущен или неоднозначен (pidof: " + repr(text[:160]) + ")")
        return tuple(map(int,text.split()))

    def pid(self, package: str = "com.lilithgame.roc.gp") -> int:
        pids = self.process_ids(package)
        if not pids:
            # Vendor ADB occasionally returns an empty successful shell response.
            # Retry only the read; ambiguous replies never authorize any input.
            time.sleep(.05)
            pids = self.process_ids(package)
        if len(pids) != 1:
            text = " ".join(map(str,pids))
            raise CommandError("Игровой процесс не запущен или неоднозначен (pidof: "
                               + (repr(text[:160]) if text else "пустой ответ") + ")")
        return pids[0]

    def version(self) -> str:
        package = self.shell("dumpsys package com.lilithgame.roc.gp | grep versionName")
        match = re.search(r"versionName=([\d.]+)", package)
        if not match:
            raise CommandError("Не удалось определить установленную версию игры")
        return match.group(1)

    def forward(self, remote_port: int) -> int:
        if not 1 <= remote_port <= 65535:
            raise ValueError("Некорректный удалённый порт")
        # BlueStacks' ADB 1.0.36 accepts tcp:0 but leaves an unusable tcp:0 entry.
        # Reserve a candidate locally, then ask ADB to bind without replacing a mapping.
        error = None
        for _ in range(3):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
                candidate.bind(("127.0.0.1", 0))
                port = candidate.getsockname()[1]
            try:
                self.command("forward", "--no-rebind", f"tcp:{port}", f"tcp:{remote_port}")
                return port
            except CommandError as exception:
                error = exception
        raise CommandError(f"Не удалось создать перенаправление ADB: {error}")

    def remove_forward(self, local_port: int) -> None:
        self.command("forward", "--remove", f"tcp:{int(local_port)}")
