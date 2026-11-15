from types import SimpleNamespace

import frida
import pytest

from mirage.memory import MemoryError, Reader, training_keyboard_owned, training_summary
from mirage.model import Instance, Power, Provider


def reader(monkeypatch):
    instance = Instance("ld:test:1", Provider.LDPLAYER, "1", "Farm", "C:/LD", "adb", "127.0.0.1:5557", Power.ONLINE)
    value = Reader(instance)
    value.pid = 10
    value.version = "1.1.12.20"
    raw = {"pid":10, "luaVersion":"Lua 5.1", "capturedMs":1000000,
           "values":{"player":{"PlayerID":20}, "server_time":1000}}
    value.script = SimpleNamespace(exports_sync=SimpleNamespace(snapshot=lambda *args: raw))
    monkeypatch.setattr(value.adb, "verify_identity", lambda: None)
    monkeypatch.setattr(value.adb, "pid", lambda: 10)
    monkeypatch.setattr("mirage.memory.time.time", lambda: 1000)
    return value, raw


def test_frozen_game_clock_is_not_renewed_by_fresh_rpc_timestamps(monkeypatch):
    value, raw = reader(monkeypatch)
    instant = [100.0]
    monkeypatch.setattr("mirage.memory.time.monotonic", lambda: instant[0])
    assert value.snapshot().fresh(100)
    instant[0] = 106
    with pytest.raises(MemoryError, match="не обновляются"):
        value.snapshot()
    raw["values"]["server_time"] = 2000
    assert value.snapshot().fresh(106)


def test_process_restart_blocks_reading_old_agent(monkeypatch):
    value, raw = reader(monkeypatch)
    monkeypatch.setattr(value.adb, "pid", lambda: 11)
    with pytest.raises(MemoryError, match="процесс сменился"):
        value.snapshot()


@pytest.mark.parametrize("exception",[frida.RPCException,frida.InvalidOperationError,
    frida.TransportError,frida.ServerNotRunningError])
def test_rpc_connection_loss_is_classified_as_a_failed_read_not_a_valid_snapshot(monkeypatch,exception):
    value,raw = reader(monkeypatch)
    def failed(*args):
        raise exception("read unavailable")
    value.script.exports_sync.snapshot = failed
    with pytest.raises(MemoryError,match="Не удалось прочитать игровой процесс") as failure:
        value.snapshot()
    assert isinstance(failure.value.__cause__,exception)


def keypad_values():
    return {"training_form":{"visible":True,"ready":True,"promoting":False,"running":False,
                "info":False,"max_count":2000,"count":2000},
            "training_keyboard":{"visible":True,"first":True,"initial":2000,"max":0,"min":0,"title":"",
                "dynamic_max":True,"change_callback":True,"confirm_callback":True,"y_offset":0,"right_offset":0,
                "position":{"x":770*1334/960,"y":(540-317)*1334/960}}}


def test_training_keypad_can_use_a_dynamic_capacity_without_invoking_the_callback():
    values = keypad_values()
    assert training_keyboard_owned(values)
    values["training_keyboard"]["first"] = False
    values["training_form"]["count"] = 1
    assert training_keyboard_owned(values)
    values["training_keyboard"].update(max=2000,dynamic_max=False)
    assert training_keyboard_owned(values)


@pytest.mark.parametrize("field,value",[("dynamic_max",False),("change_callback",False),("confirm_callback",False),
    ("initial",2001),("initial",1999),("max",False),("first",None),("title","other owner")])
def test_zero_limit_alone_never_authorizes_a_generic_keypad(field,value):
    values = keypad_values()
    values["training_keyboard"][field] = value
    assert not training_keyboard_owned(values)


def test_daily_progress_distinguishes_ready_tasks_and_claimed_chests(monkeypatch):
    value, raw = reader(monkeypatch)
    raw["values"].update(daily_quests={"1":{"Id":10132,"Stat":2}, "2":{"Id":10095,"Stat":1}},
                         daily_score=52, daily_chests={"1":{"Completed":True}, "2":{"Completed":False},
                                                       "3":{"Completed":False}})
    state = value.snapshot()
    assert state.values["daily_ready_count"] == 1
    assert state.values["daily_chest_count"] == 1
    raw["values"]["daily_quests"].pop("1")
    raw["values"]["daily_chests"]["2"]["Completed"] = True
    assert value.snapshot().values["daily_ready_count"] == 0
    assert value.snapshot().values["daily_chest_count"] == 0
    raw["values"]["daily_quests"]["$truncated"] = True
    raw["values"]["daily_chests"]["$truncated"] = True
    assert value.snapshot().values["daily_ready_count"] is None
    assert value.snapshot().values["daily_chest_count"] is None
    raw["values"]["daily_refresh_ts"] = 900
    assert value.snapshot().values["daily_refresh_due"] is True
    raw["values"]["daily_refresh_ts"] = 2000
    assert value.snapshot().values["daily_refresh_due"] is False


def test_task_fields_are_requested_only_for_the_task_and_cannot_replace_identity(monkeypatch):
    from mirage.memory import PATHS
    from mirage.workflows import MAIL_FIELDS
    value, raw = reader(monkeypatch)
    requests = []
    def capture(paths, depth):
        requests.append(paths)
        return raw
    value.script.exports_sync.snapshot = capture
    value.snapshot()
    value.snapshot(MAIL_FIELDS)
    value.snapshot()
    assert "mail_summary" not in requests[0] and "mail_summary" not in requests[2]
    assert requests[1]["mail_summary"] == ["@mail_summary"]
    assert requests[1]["player"] == PATHS["player"]
    with pytest.raises(MemoryError, match="идентичность"):
        value.snapshot({"player":["SomeoneElse"]})
    assert len(requests) == 3


def test_expedition_counts_only_unclaimed_three_star_daily_rewards(monkeypatch):
    value, raw = reader(monkeypatch)
    infos = {"1":{"star":3,"getRewardStar":0}, "2":{"star":1,"getRewardStar":0},
             "3":{"star":2,"getRewardStar":0}, "4":{"star":3,"getRewardStar":3}}
    raw["values"]["expedition_infos"] = infos
    assert value.snapshot().values["expedition_pending"] == 1
    infos["1"]["getRewardStar"] = 3
    assert value.snapshot().values["expedition_pending"] == 0
    assert value.snapshot().values["expedition_data_ready"]
    infos["1"]["getRewardStar"] = 1
    assert value.snapshot().values["expedition_pending"] is None
    assert not value.snapshot().values["expedition_data_ready"]
    infos["1"]["getRewardStar"] = 3
    infos["$truncated"] = True
    assert not value.snapshot().values["expedition_data_ready"]


def training_values():
    return {"server_time":1000,"buildings":{str(i):{"type":t,"focused":i==4}
                                            for i,t in enumerate((9,11,10,12),1)},
            "training_queues":{f"trainingQueue_{i}":{"status":"Completed" if i==4 else "Free",
                                                      "extraData":{"buildingId":str(i)}} for i in range(1,5)},
            "training":{"1":{"buildingId":"4","unitId":4,"unitCount":2000,"endTime":900}},
            "troops":{str(i):{"unitId":i,"unitCount":100*i} for i in range(1,5)}}


def test_training_summary_links_ui_queues_to_buildings_and_real_unit_counts():
    values = training_values()
    summary = training_summary(values)
    assert summary["ready"] and summary["completed"] == 1
    assert summary["rows"]["4"] == {"building_id":"4","focused":True,"pending":True,
                                    "unit_id":4,"from_unit_id":None,"count":2000,"status":"Completed"}
    values["training"].clear()
    values["training_queues"]["trainingQueue_4"]["status"] = "Free"
    values["troops"]["4"]["unitCount"] += 2000
    after = training_summary(values)
    assert after["ready"] and after["completed"] == 0
    assert after["troops"]["4"] == 2400


def test_locked_unbuilt_siege_workshop_does_not_block_existing_training_queues():
    values=training_values();values['buildings'].pop('4');values['training']={}
    values['training_queues']['trainingQueue_4']={'status':'Lock','extraData':{'buildingId':None}}
    summary=training_summary(values)
    assert summary['ready'] and summary['rows']['1']['status']=='Free' and summary['rows']['4']['status']=='Lock'
    values['training_queues']['trainingQueue_4']['status']='Free'
    assert not training_summary(values)['ready']


@pytest.mark.parametrize("corruption", ["missing_record","wrong_building","duplicate_unit","future_end","truncated"])
def test_training_summary_rejects_unconfirmed_or_mixed_state(corruption):
    values = training_values()
    if corruption == "missing_record":
        values["training"].clear()
    elif corruption == "wrong_building":
        values["buildings"]["4"]["type"] = 18
    elif corruption == "duplicate_unit":
        values["troops"]["5"] = dict(values["troops"]["4"])
    elif corruption == "future_end":
        values["training"]["1"]["endTime"] = 2000
    else:
        values["training_queues"]["$truncated"] = True
    assert not training_summary(values)["ready"]
