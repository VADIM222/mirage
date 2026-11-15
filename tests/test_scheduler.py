from dataclasses import replace
from datetime import datetime

import pytest

from mirage.model import Instance, Power, Profile, Provider, RunState, Slot, validate_slots
from mirage.scheduler import Rotation, decide


@pytest.fixture
def instance():
    return Instance("test:1", Provider.BLUESTACKS, "Pie64", "Ферма", "C:/BS", "adb", "127.0.0.1:5555", Power.ONLINE)


def now(hour, minute=0):
    return datetime(2026, 11, 8, hour, minute)


def test_off_instance_never_produces_work(instance):
    profile = Profile(instance.id, schedule_enabled=True,
                      slots=[Slot("day", "00:00", "24:00", ("alliance_help",))])
    result = decide(replace(instance, power=Power.OFF), profile, now(12), True)
    assert result.state == RunState.WAIT_EMULATOR
    assert result.tasks == ()
    # A schedule decision deliberately has no emulator-launch field.
    assert not hasattr(result, "launch")


def test_night_slot_and_end_boundary(instance):
    profile = Profile(instance.id, schedule_enabled=True,
                      slots=[Slot("night", "22:00", "06:00", ("gather_resources",))])
    assert decide(instance, profile, now(22), True).tasks == ("gather_resources",)
    assert decide(instance, profile, now(2), True).state == RunState.RUNNING
    assert decide(instance, profile, now(6), True).state == RunState.WAIT_SLOT
    assert decide(instance, profile, now(21, 59), True).tasks == ()


def test_manual_stop_survives_next_slot(instance):
    profile = Profile(instance.id, schedule_enabled=True, manual_pause=True,
                      slots=[Slot("a", "00:00", "12:00", ("tavern",)),
                             Slot("b", "12:00", "24:00", ("alliance_help",))])
    assert decide(instance, profile, now(11, 59), True).state == RunState.PAUSED
    assert decide(instance, profile, now(12), True).state == RunState.PAUSED


def test_manually_opened_instance_inside_slot_can_run(instance):
    profile = Profile(instance.id, schedule_enabled=True,
                      slots=[Slot("a", "08:00", "20:00", ("tavern",))])
    assert decide(replace(instance, power=Power.OFF), profile, now(10), False).tasks == ()
    assert decide(instance, profile, now(10), False).state == RunState.WAIT_ADAPTER
    assert decide(instance, profile, now(10), True).state == RunState.RUNNING


def test_disabling_schedule_stops_schedule_owned_work(instance):
    profile = Profile(instance.id, schedule_enabled=False,
                      slots=[Slot("a", "00:00", "24:00", ("tavern",))])
    assert decide(instance, profile, now(10), True).state == RunState.STOPPED


def test_manual_mode_uses_only_enabled_tasks(instance):
    profile = Profile(instance.id, manual_run=True,
                      tasks={"tavern": {"enabled": True}, "barbarians": {"enabled": False}})
    assert decide(instance, profile, now(10), True).tasks == ("tavern",)


@pytest.mark.parametrize("start,end", [("24:00", "24:00"), ("8:00", "09:00"),
                                       ("23:60", "24:00"), ("12:00", "12:00")])
def test_invalid_slots_are_rejected(start, end):
    with pytest.raises(ValueError):
        Slot("bad", start, end)


def test_overlapping_night_slots_are_rejected():
    with pytest.raises(ValueError, match="пересекаются"):
        validate_slots([Slot("a", "22:00", "06:00"), Slot("b", "05:00", "08:00")])
    validate_slots([Slot("a", "22:00", "06:00"), Slot("b", "06:00", "22:00")])


def test_rotation_requires_explicit_enabling():
    rotation = Rotation(["a", "b"])
    assert rotation.tick(0, set(), 3).launch == ()
    rotation.enabled = True
    assert rotation.tick(0, set(), 3).launch == ("a",)


def test_rotation_does_not_exceed_device_limit_while_closing():
    rotation = Rotation(["a", "b", "c", "d"], parallel=3, duration=10)
    rotation.enabled = True
    assert rotation.tick(0, set(), 3).launch == ("a", "b", "c")
    expiry = rotation.tick(10, {"a", "b", "c"}, 3)
    assert set(expiry.close) == {"a", "b", "c"}
    assert not expiry.launch
    assert rotation.tick(11, set(), 3).launch == ("d", "a", "b")


def test_rotation_does_not_relaunch_manually_paused_instance():
    rotation = Rotation(["a", "b"], parallel=1, duration=10)
    rotation.enabled = True
    rotation.tick(0, set(), 1)
    rotation.pause("a")
    assert rotation.tick(1, set(), 1).launch == ("b",)
    assert "a" not in rotation.tick(20, set(), 1).launch


def test_50_logical_sessions_are_all_visited_with_local_limit_three():
    members = [f"farm{i}" for i in range(50)]
    rotation = Rotation(members, parallel=50, duration=1)
    rotation.enabled = True
    visited = set()
    online = set()
    for instant in range(100):
        plan = rotation.tick(instant, online, 3)
        assert not (set(plan.launch) & set(plan.close))
        assert len(online | set(plan.launch)) <= 3
        online.difference_update(plan.close)
        online.update(plan.launch)
        visited.update(plan.launch)
    assert visited == set(members)


def test_manually_closed_rotation_member_stays_suspended():
    rotation = Rotation(["a", "b"], parallel=1, duration=100)
    rotation.enabled = True
    rotation.tick(0, set(), 1)
    rotation.tick(1, {"a"}, 1)
    plan = rotation.tick(2, set(), 1)
    assert "a" in rotation.suspended
    assert plan.launch == ("b",)


def test_slow_closing_rotation_member_keeps_capacity_reserved():
    rotation = Rotation(["a", "b"], parallel=1, duration=10)
    rotation.enabled = True
    rotation.tick(0, set(), 1)
    assert rotation.tick(10, {"a"}, 1).close == ("a",)
    assert not rotation.tick(11, {"a"}, 1).launch
    assert not rotation.tick(12, {"a"}, 1).launch
    assert rotation.tick(13, set(), 1).launch == ("b",)
