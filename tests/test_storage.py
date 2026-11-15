from concurrent.futures import ThreadPoolExecutor

import pytest

from mirage.model import Profile, Slot
from mirage.storage import Store


def test_roundtrip_and_copy_preserve_target_identity(tmp_path):
    store = Store(tmp_path / "mirage.db")
    source = Profile("one", account_name="Source", manual_run=True, schedule_enabled=True,
                     tasks={"tavern": {"enabled": True, "interval": 60}},
                     slots=[Slot("a", "22:00", "06:00", ("tavern",))])
    store.save_profile(source)
    store.save_profile(Profile("two", account_name="Target", manual_pause=True))
    store.copy_profile("one", ["two"])
    restored = store.profile("two")
    assert restored.account_name == "Target"
    assert restored.slots == source.slots
    assert restored.manual_pause
    assert not restored.manual_run
    assert restored.tasks == source.tasks


def test_invalid_import_is_atomic(tmp_path):
    store = Store(tmp_path / "mirage.db")
    good = Profile("one", account_name="Unchanged")
    store.save_profile(good)
    document = {"format": "mirage-profiles", "version": 1,
                "profiles": [Profile("one", account_name="Overwritten").to_dict(),
                             {"instance_id": "two", "schedule_enabled": "false"}]}
    with pytest.raises(ValueError):
        store.import_profiles(document)
    assert store.profile("one").account_name == "Unchanged"


def test_export_does_not_export_global_secrets_or_running_intent(tmp_path):
    store = Store(tmp_path / "mirage.db")
    store.set_preference("telegram_token", "private")
    store.save_profile(Profile("one", manual_run=True))
    exported = store.export_profiles()
    assert "private" not in str(exported)
    assert not exported["profiles"][0]["manual_run"]


def test_concurrent_events_and_profiles_use_independent_connections(tmp_path):
    store = Store(tmp_path / "mirage.db")

    def write(index):
        store.save_profile(Profile(f"farm{index}"))
        store.event(f"farm{index}", "info", f"event {index}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write, range(50)))
    assert len(store.events()) == 50
    assert len(store.export_profiles()["profiles"]) == 50


@pytest.mark.parametrize("interval", [True, 0, -1, float("nan"), float("inf"), "60"])
def test_task_interval_rejects_unsafe_values(interval):
    with pytest.raises(ValueError):
        Profile("one", tasks={"tavern": {"interval": interval}}).validate()


def test_preset_applies_only_settings_and_pauses_target(tmp_path):
    store = Store(tmp_path / "mirage.db")
    source = Profile("one", account_name="Source", manual_run=True,
                     tasks={"alliance_help":{"enabled":True,"interval":90}},
                     slots=[Slot("day","08:00","20:00",("alliance_help",))], schedule_enabled=True)
    store.save_preset("Farm", source)
    store.save_profile(Profile("two", account_name="Target", manual_run=True))
    store.apply_preset("Farm", ["two"])
    target = store.profile("two")
    assert target.instance_id == "two" and target.account_name == "Target"
    assert target.tasks == source.tasks and target.slots == source.slots
    assert target.manual_pause and not target.manual_run
    assert store.presets() == ["Farm"]
    store.delete_preset("Farm")
    assert store.presets() == []


def test_export_import_includes_presets_without_source_account_identity(tmp_path):
    source = Store(tmp_path / "source.db")
    source.save_preset("Help", Profile("source", account_name="Private account", manual_run=True,
                                      tasks={"alliance_help":{"enabled":True}}))
    document = source.export_profiles()
    assert "Private account" not in str(document)
    target = Store(tmp_path / "target.db")
    target.import_profiles(document)
    target.apply_preset("Help", ["target"])
    assert target.profile("target").tasks["alliance_help"]["enabled"]
