from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from .model import Instance, Power, Profile, RunState, Slot


@dataclass(frozen=True)
class Decision:
    state: RunState
    tasks: tuple[str, ...] = ()
    reason: str = ""
    slot_id: str | None = None


def active_slot(profile: Profile, now: datetime) -> Slot | None:
    value = now.hour * 60 + now.minute
    return next((slot for slot in profile.slots if slot.contains(value)), None)


def decide(instance: Instance, profile: Profile, now: datetime, adapter_ready: bool) -> Decision:
    """Pure policy. It can request task work, never launch an emulator."""
    if profile.manual_pause:
        return Decision(RunState.PAUSED, reason="Ручная пауза")
    if instance.power != Power.ONLINE:
        wanted = profile.schedule_enabled or profile.manual_run
        return Decision(RunState.WAIT_EMULATOR if wanted else RunState.STOPPED,
                        reason="Ожидание работающего эмулятора" if wanted else "Остановлено")
    slot = active_slot(profile, now) if profile.schedule_enabled else None
    if profile.schedule_enabled and slot is None:
        return Decision(RunState.WAIT_SLOT, reason="Вне интервала расписания")
    if not profile.schedule_enabled and not profile.manual_run:
        return Decision(RunState.STOPPED, reason="Остановлено")
    if not adapter_ready:
        return Decision(RunState.WAIT_ADAPTER, reason="Ожидание адаптера состояния игры")
    tasks = slot.tasks if slot else tuple(key for key, value in profile.tasks.items() if value.get("enabled"))
    if not tasks:
        return Decision(RunState.STOPPED, reason="Задачи не выбраны", slot_id=slot.id if slot else None)
    return Decision(RunState.RUNNING, tasks=tasks, reason="Работа по расписанию" if slot else "Ручной запуск",
                    slot_id=slot.id if slot else None)


@dataclass(frozen=True)
class RotationPlan:
    launch: tuple[str, ...]
    close: tuple[str, ...]
    current: tuple[str, ...]


class Rotation:
    """Explicitly enabled rotation, separate from task schedule evaluation."""

    def __init__(self, members: list[str], *, parallel: int = 1, duration: float = 3600):
        if not members or len(set(members)) != len(members):
            raise ValueError("Ротация требует уникального непустого списка эмуляторов")
        if isinstance(parallel, bool) or not isinstance(parallel, int) or not 1 <= parallel <= 50 or not math.isfinite(duration) or duration < 1:
            raise ValueError("Некорректный лимит или длительность ротации")
        self.members = list(members)
        self.parallel = parallel
        self.duration = duration
        self.enabled = False
        self.suspended: set[str] = set()
        self.current: dict[str, float] = {}
        self.cursor = 0
        self.closing: set[str] = set()
        self.seen_online: set[str] = set()

    def pause(self, instance_id: str) -> None:
        self.suspended.add(instance_id)
        self.current.pop(instance_id, None)
        self.seen_online.discard(instance_id)

    def resume(self, instance_id: str) -> None:
        self.suspended.discard(instance_id)

    def tick(self, now: float, online: set[str], device_limit: int) -> RotationPlan:
        if not self.enabled:
            return RotationPlan((), (), tuple(self.current))
        limit = min(self.parallel, device_limit)
        if limit < 1:
            raise ValueError("Лимит устройства должен быть положительным")
        close = []
        self.closing.intersection_update(online)
        for key, started in list(self.current.items()):
            if key in online:
                self.seen_online.add(key)
            elif key in self.seen_online:
                # The user closed it before its allotted run ended.
                self.pause(key)
                continue
            if key in self.suspended or now - started >= self.duration:
                if key in online and key not in self.suspended:
                    close.append(key)
                    self.closing.add(key)
                del self.current[key]
                self.seen_online.discard(key)
        occupied = (online - set(close)) | set(self.current)
        free = max(0, limit - len(occupied) - len(close))
        launch = []
        visited = 0
        while free and visited < len(self.members):
            key = self.members[self.cursor % len(self.members)]
            self.cursor = (self.cursor + 1) % len(self.members)
            visited += 1
            if key in self.suspended or key in occupied or key in self.closing or key in close:
                continue
            self.current[key] = now
            occupied.add(key)
            launch.append(key)
            free -= 1
        return RotationPlan(tuple(launch), tuple(close), tuple(self.current))
