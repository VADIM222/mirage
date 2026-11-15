from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
import time

from .emulators import CommandError, close, launch, parse_bs_config, parse_ld_list, run
from .model import Instance, MIN_CPUS, MIN_MEMORY_MB, Power, Provider


_BS_CONFIG_LOCK = threading.Lock()


def _bluestacks_running(directory: Path) -> set[str]:
    text=run([str(directory/"BstkVMMgr.exe"),"list","runningvms"],timeout=8)
    lines=[line for line in text.splitlines() if line.strip()]
    if any(not re.fullmatch(r'"[^"\r\n]+"\s+\{[0-9a-fA-F-]+\}',line.strip()) for line in lines):
        raise CommandError("Не подтверждён список работающих BlueStacks")
    return {re.match(r'"([^\"]+)"',line.strip()).group(1) for line in lines}


def _prepare_bluestacks(instance: Instance, backup_dir: Path, cancelled: threading.Event) -> str:
    if not _BS_CONFIG_LOCK.acquire(blocking=False):
        raise CommandError("Подготовка BlueStacks уже выполняется")
    try:
        return _prepare_bluestacks_locked(instance,backup_dir,cancelled)
    finally:
        _BS_CONFIG_LOCK.release()


def _prepare_bluestacks_locked(instance: Instance, backup_dir: Path, cancelled: threading.Event) -> str:
    directory=Path(instance.install_dir)
    config_path=Path(os.environ.get("ProgramData",r"C:\ProgramData"))/"BlueStacks_nxt"/"bluestacks.conf"
    if not re.fullmatch(r"[A-Za-z0-9_]+",instance.key):raise CommandError("Некорректный ключ BlueStacks")
    if cancelled.is_set():raise CommandError("Подготовка отменена")
    running=_bluestacks_running(directory)
    if running-{instance.key}:
        raise CommandError("Закройте остальные экземпляры BlueStacks перед подготовкой общей конфигурации")
    was_online=instance.key in running
    if was_online:close(instance)
    if cancelled.is_set():raise CommandError("Подготовка отменена после закрытия эмулятора")
    if _bluestacks_running(directory):raise CommandError("BlueStacks не подтвердил выключение перед настройкой")
    original=config_path.read_bytes()
    bom=original.startswith(b"\xef\xbb\xbf")
    text=original.decode("utf-8-sig")
    config=parse_bs_config(text)
    prefix=f"bst.instance.{instance.key}."
    if config.get(prefix+"display_name")!=instance.name:
        raise CommandError("Выбранный экземпляр не совпадает с конфигурацией BlueStacks")
    try:
        cpus=max(MIN_CPUS,int(config[prefix+"cpus"]))
        memory=max(MIN_MEMORY_MB,int(config[prefix+"ram"]))
    except (ValueError,KeyError) as error:
        raise CommandError("Не подтверждены CPU и ОЗУ выбранного BlueStacks") from error
    changes={prefix+"cpus":str(cpus),prefix+"ram":str(memory),prefix+"enable_root_access":"1",
             prefix+"fb_width":"960",prefix+"fb_height":"540",prefix+"dpi":"160",
             "bst.enable_adb_access":"1","bst.feature.rooting":"1"}
    for key,value in changes.items():
        pattern=re.compile(r'^(?P<prefix>'+re.escape(key)+r'=")[^"\r\n]*(?P<suffix>"[^\S\r\n]*\r?)$',re.MULTILINE)
        text,count=pattern.subn(lambda match:match["prefix"]+value+match["suffix"],text)
        if count!=1:raise CommandError(f"Не подтверждено единственное поле BlueStacks: {key}")
    updated=parse_bs_config(text)
    if updated!={**config,**changes}:raise CommandError("Неожиданное изменение конфигурации BlueStacks")
    encoded=(b"\xef\xbb\xbf" if bom else b"")+text.encode("utf-8")
    backup_dir.mkdir(parents=True,exist_ok=True)
    backup=backup_dir/f"{instance.id.replace(':','-')}-{datetime.now():%Y%m%d-%H%M%S-%f}.conf"
    backup.write_bytes(original)
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(dir=config_path.parent,prefix=".mirage-",suffix=".conf",delete=False) as handle:
            temporary=Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        shutil.copystat(config_path,temporary)
        if cancelled.is_set():raise CommandError("Подготовка отменена до изменения конфигурации")
        if _bluestacks_running(directory) or config_path.read_bytes()!=original:
            raise CommandError("BlueStacks или его конфигурация изменились во время подготовки")
        os.replace(temporary,config_path)
        if config_path.read_bytes()!=encoded:raise CommandError(f"Настройки не подтверждены; исходная копия: {backup}")
    finally:
        if temporary is not None:temporary.unlink(missing_ok=True)
    if was_online and not cancelled.is_set():launch(instance)
    return (f"Подготовлен BlueStacks: ADB и root разрешены, CPU {cpus}, ОЗУ {memory} МБ, экран 960×540/160 DPI; "
            f"root проверяется при подключении; резервная копия {backup}")


def prepare(instance: Instance, backup_dir: Path, cancelled: threading.Event) -> str:
    """Explicit setup command. Scheduling never calls this restart operation."""
    if instance.provider == Provider.BLUESTACKS:
        return _prepare_bluestacks(instance,backup_dir,cancelled)
    directory = Path(instance.install_dir)
    console = str(directory / "ldconsole.exe")
    config_path = directory / "vms" / "config" / f"leidian{instance.key}.config"
    if cancelled.is_set():
        raise CommandError("Подготовка отменена")
    was_online = instance.power != Power.OFF
    if was_online:
        close(instance)
        deadline = time.monotonic() + 30
        while any(i.key == instance.key and i.power != Power.OFF for i in parse_ld_list(run([console, "list2"]), directory)):
            if cancelled.wait(0.25):
                raise CommandError("Подготовка отменена после закрытия эмулятора")
            if time.monotonic() >= deadline:
                raise CommandError("LDPlayer не подтвердил выключение перед настройкой")
    if cancelled.is_set():
        raise CommandError("Подготовка отменена")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"{instance.id.replace(':','-')}-{datetime.now():%Y%m%d-%H%M%S-%f}.config"
    shutil.copy2(config_path, backup)
    original = json.loads(config_path.read_text(encoding="utf-8-sig"))
    cpus = max(MIN_CPUS, int(original.get("advancedSettings.cpuCount", 0)))
    memory = max(MIN_MEMORY_MB, int(original.get("advancedSettings.memorySize", 0)))
    arguments = [console, "modify", "--index", instance.key, "--root", "1"]
    if int(original.get("advancedSettings.cpuCount", 0)) < MIN_CPUS:
        arguments += ["--cpu", str(cpus)]
    if int(original.get("advancedSettings.memorySize", 0)) < MIN_MEMORY_MB:
        arguments += ["--memory", str(memory)]
    if (original.get("advancedSettings.resolution")!={"width":960,"height":540}
            or original.get("advancedSettings.resolutionDpi")!=160):
        arguments += ["--resolution","960,540,160"]
    run(arguments, timeout=15)
    updated = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if (updated.get("basicSettings.rootMode") is not True
            or int(updated.get("advancedSettings.cpuCount", 0)) < MIN_CPUS
            or int(updated.get("advancedSettings.memorySize", 0)) < MIN_MEMORY_MB
            or updated.get("advancedSettings.resolution")!={"width":960,"height":540}
            or updated.get("advancedSettings.resolutionDpi")!=160):
        raise CommandError(f"Настройки не подтверждены; исходная копия: {backup}")
    if was_online and not cancelled.is_set():
        launch(instance)
    return f"Подготовлен LDPlayer: root включён, CPU {cpus}, ОЗУ {memory} МБ, экран 960×540/160 DPI; резервная копия {backup}"
