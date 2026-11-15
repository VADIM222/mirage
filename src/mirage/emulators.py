from __future__ import annotations

from dataclasses import replace
import hashlib
import importlib.resources
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time

from .model import Instance, Power, Provider


class CommandError(RuntimeError):
    def __init__(self, message: str = "", *, returncode: int | None = None, empty_output: bool = False):
        super().__init__(message)
        self.returncode = returncode
        self.empty_output = empty_output


def run(arguments: list[str], *, timeout: float = 15, binary: bool = False):
    try:
        process = subprocess.Popen(arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if os.name == "nt":
            # Vendor launchers can leave a child holding stdout open. Killing just
            # the launcher would make a second, unbounded communicate() hang.
            try:
                subprocess.run(["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2,
                               creationflags=subprocess.CREATE_NO_WINDOW)
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            process.kill()
        try:
            process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        raise CommandError(f"Команда превысила {timeout:g} с: {Path(arguments[0]).name}") from error
    except OSError as error:
        raise CommandError(str(error)) from error
    if process.returncode:
        message = (stderr or stdout).decode("utf-8", "replace").strip()
        raise CommandError(message[:2000] or f"Код завершения: {process.returncode}",
                           returncode=process.returncode,empty_output=not message)
    if binary:
        return stdout
    try:
        return stdout.decode("utf-8").strip()
    except UnicodeDecodeError:
        return stdout.decode("cp1251", "replace").strip()


def installation_id(directory: Path) -> str:
    return hashlib.sha256(str(directory.resolve()).casefold().encode()).hexdigest()[:10]


def parse_bs_config(text: str) -> dict[str, str]:
    return dict(re.findall(r'^([^=\r\n]+)="([^"\r\n]*)"\s*$', text, re.MULTILINE))


def bs_instances(config: dict[str, str], install: Path, running: set[str]) -> list[Instance]:
    keys = sorted({match.group(1) for key in config
                   if (match := re.match(r"bst\.instance\.([^.]+)\.display_name$", key))})
    instances = []
    for key in keys:
        prefix = f"bst.instance.{key}."

        def number(field: str, default: int = 0):
            try:
                return int(config.get(prefix + field, str(default)))
            except ValueError:
                return default

        port = number("status.adb_port", number("adb_port", 5555))
        if not 1 <= port <= 65535:
            port = 5555
        instances.append(Instance(
            id=f"bs:{installation_id(install)}:{key}", provider=Provider.BLUESTACKS, key=key,
            name=config[prefix + "display_name"], install_dir=str(install),
            adb_path=str(install / "HD-Adb.exe"), serial=f"127.0.0.1:{port}",
            power=Power.ONLINE if key in running else Power.OFF,
            cpus=number("cpus"), memory_mb=number("ram"), width=number("fb_width"),
            height=number("fb_height"), dpi=number("dpi")))
    return instances


def parse_ld_list(text: str, install: Path, configs: dict[str, dict] | None = None) -> list[Instance]:
    instances = []
    for line in text.splitlines():
        pieces = line.strip().split(",")
        if len(pieces) < 7:
            continue
        try:
            index = int(pieces[0])
            try:
                if len(pieces) < 10:
                    raise ValueError
                tail = list(map(int, pieces[-8:]))
                name = ",".join(pieces[1:-8])
            except ValueError:
                tail = list(map(int, pieces[-5:])) + [0, 0, 0]
                name = ",".join(pieces[1:-5])
            _, _, started, pid, _, width, height, dpi = tail
        except ValueError:
            continue
        if index < 0 or not name:
            continue
        config = (configs or {}).get(str(index), {})
        power = Power.ONLINE if started == 1 else Power.BOOTING if pid > 0 else Power.OFF
        instances.append(Instance(
            id=f"ld:{installation_id(install)}:{index}", provider=Provider.LDPLAYER,
            key=str(index), name=name, install_dir=str(install), adb_path=str(install / "adb.exe"),
            serial=f"127.0.0.1:{5555 + index * 2}", power=power,
            cpus=int(config.get("advancedSettings.cpuCount", 0)),
            memory_mb=int(config.get("advancedSettings.memorySize", 0)),
            width=width, height=height, dpi=dpi))
    return instances


class Discovery:
    def __init__(self, extra_dirs: list[str] | None = None):
        self.extra_dirs = [Path(value) for value in (extra_dirs or [])]
        self.errors: list[str] = []

    def directories(self) -> tuple[list[Path], list[Path]]:
        blues = [Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "BlueStacks_nxt"]
        ld = [Path(r"C:\LDPlayer\LDPlayer9"), Path(r"C:\LDPlayer\LDPlayer14")]
        if os.name == "nt":
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for suffix in (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                               r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"):
                    try:
                        with winreg.OpenKey(root, suffix) as keys:
                            for index in range(winreg.QueryInfoKey(keys)[0]):
                                try:
                                    with winreg.OpenKey(keys, winreg.EnumKey(keys, index)) as entry:
                                        name = winreg.QueryValueEx(entry, "DisplayName")[0]
                                        if "LDPlayer" in name:
                                            icon = winreg.QueryValueEx(entry, "DisplayIcon")[0].strip('"').split(",")[0]
                                            ld.append(Path(icon).parent)
                                except OSError:
                                    continue
                    except OSError:
                        continue
        for directory in self.extra_dirs:
            if (directory / "HD-Player.exe").exists():
                blues.append(directory)
            if (directory / "ldconsole.exe").exists():
                ld.append(directory)
        return list(dict.fromkeys(blues)), list(dict.fromkeys(ld))

    def discover(self) -> list[Instance]:
        self.errors = []
        blues, ld = self.directories()
        instances = []
        for directory in blues:
            if not (directory / "HD-Player.exe").exists():
                continue
            config_path = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "BlueStacks_nxt" / "bluestacks.conf"
            try:
                config = parse_bs_config(config_path.read_text(encoding="utf-8-sig"))
                vm_text = run([str(directory / "BstkVMMgr.exe"), "list", "runningvms"], timeout=8)
                running = set(re.findall(r'^"([^"]+)"', vm_text, re.MULTILINE))
                instances.extend(bs_instances(config, directory, running))
            except (OSError, CommandError) as error:
                self.errors.append(f"BlueStacks: {error}")
        for directory in ld:
            console = directory / "ldconsole.exe"
            if not console.exists():
                continue
            try:
                configs = {}
                config_dir = directory / "vms" / "config"
                for path in config_dir.glob("leidian[0-9]*.config"):
                    try:
                        index = re.fullmatch(r"leidian(\d+)\.config", path.name).group(1)
                        configs[index] = json.loads(path.read_text(encoding="utf-8-sig"))
                    except (OSError, ValueError, AttributeError):
                        continue
                instances.extend(parse_ld_list(run([str(console), "list2"], timeout=8), directory, configs))
            except (OSError, CommandError, ValueError) as error:
                self.errors.append(f"LDPlayer ({directory.name}): {error}")
        return instances


def launch(instance: Instance) -> None:
    directory = Path(instance.install_dir)
    if instance.provider == Provider.BLUESTACKS:
        subprocess.Popen([str(directory / "HD-Player.exe"), "--instance", instance.key],
                         creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        run([str(directory / "ldconsole.exe"), "launch", "--index", instance.key])


def close(instance: Instance) -> None:
    directory = Path(instance.install_dir)
    if instance.provider == Provider.LDPLAYER:
        run([str(directory / "ldconsole.exe"), "quit", "--index", instance.key])
        deadline = time.monotonic() + 20
        while any(i.key == instance.key and i.power != Power.OFF
                  for i in parse_ld_list(run([str(directory / "ldconsole.exe"), "list2"], timeout=5), directory)):
            if time.monotonic() >= deadline:
                raise CommandError("LDPlayer не подтвердил выключение экземпляра")
            time.sleep(0.25)
    else:
        match = re.fullmatch(r"127\.0\.0\.1:(\d+)", instance.serial)
        if not match:
            raise CommandError("Не подтверждён локальный ADB-порт BlueStacks")
        info = run([str(directory / "BstkVMMgr.exe"), "showvminfo", instance.key, "--machinereadable"], timeout=8)
        forwards = re.findall(r'^Forwarding\(\d+\)="[^,]+,tcp,127\.0\.0\.1,(\d+),[^,]*,5555"', info, re.MULTILINE)
        if match.group(1) not in forwards or 'VMState="running"' not in info:
            raise CommandError("Порт не подтверждён настройками выбранной виртуальной машины")
        resource = importlib.resources.files("mirage").joinpath("assets/close_bluestacks.ps1")
        with importlib.resources.as_file(resource) as script:
            run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(script), "-Port", match.group(1)], timeout=30)
        deadline = time.monotonic() + 20
        while True:
            running = run([str(directory / "BstkVMMgr.exe"), "list", "runningvms"], timeout=5)
            if instance.key not in re.findall(r'^"([^"]+)"', running, re.MULTILINE):
                return
            if time.monotonic() >= deadline:
                raise CommandError("BlueStacks не подтвердил выключение экземпляра")
            time.sleep(0.25)
