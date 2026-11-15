from __future__ import annotations

import importlib.resources
import math
import re
import shlex
import time

import frida

from .adb import Adb
from .emulators import CommandError
from .model import Instance, MATERIALS, MIN_CPUS, MIN_MEMORY_MB, Power, Snapshot


SUPPORTED_VERSIONS = {"1.1.12.20"}
PATHS = {
    "player": ["@player"],
    "resources": ["CityBuildData", "UserRss"],
    "server_time": ["GameTimer", "frameServerTime"],
    "buildings": ["@buildings"],
    "views": ["@visible_views"],
    "hud_visible": ["@active_view", "MapHudPanel"],
    "hud_menu": ["UIObjectManager", "MapHudPanel", "IsMenuShow"],
    "queue_panel": ["@queue_panel"],
    "guide_force_click": ["UIObjectManager","QuestGuide","forceClick"],
    "guide_click_callback": ["UIObjectManager","QuestGuide","needClickCb"],
    "in_city": ["CityManager", "isInMyCity"],
    "city_enabled": ["CityManager", "isCityEnabled"],
    "alliance_help_count": ["AllianceData", "AllianceHelpNum"],
    "build_queue": ["CityBuildData", "BuildQueueMap"],
    "training": ["TrainingData", "TrainingStatusList"],
    "troops": ["TrainingData", "UnitList"],
    "scouts": ["ScoutData"],
    "alliance": ["AllianceData"],
    "tavern": ["TavernData"],
    "vip_points_available": ["VipData", "CanGetFreePoint"],
    "vip_box_available": ["VipData", "CanGetFreeBox"],
    "vip_level": ["VipData", "VipLevel"],
    "vip_visible": ["@active_view", "VIPMainPage"],
    "vip_notice_visible": ["@active_view", "VIPNotice"],
    "reward_popup_visible": ["@active_view", "RoutineRewardsCollect"],
    "vip_shown_level": ["UIObjectManager", "VIPMainPage", "m_curShowVipLevel"],
    "vip_box_detail": ["UIObjectManager", "VIPMainPage", "m_viewBoxDetail"],
    "vip_opening_box": ["UIObjectManager", "VIPMainPage", "m_isOpeningBox"],
    "daily_quests": ["QuestData", "DailyQuests"],
    "daily_chests": ["QuestData", "Chests"],
    "daily_score": ["QuestData", "QuestScores"],
    "daily_refresh_ts": ["QuestData", "NextRefreshTs"],
    "quest_visible": ["@active_view", "QuestSystemMainPage"],
    "quest_tab": ["UIObjectManager", "QuestSystemMainPage", "curSelPanelType"],
    "quest_first": ["UIObjectManager", "QuestSystemMainPage", "dailyDataSource", 1, "param"],
    "quest_collecting": ["UIObjectManager", "QuestSystemMainPage", "m_collectingDailyQuest"],
}


class MemoryError(RuntimeError):
    pass


def training_summary(values: dict) -> dict:
    queues, records, troops = (values.get(key) for key in ("training_queues", "training", "troops"))
    buildings = values.get("buildings")
    clock = values.get("server_time")
    valid = all(isinstance(data, dict) and not data.get("$truncated") for data in (queues, records, troops, buildings))
    summary = {"ready":False, "completed":0, "rows":{}, "troops":{}}
    if not valid or type(clock) not in (int,float):
        return summary
    for unit in troops.values():
        if (not isinstance(unit,dict) or type(unit.get("unitId")) is not int or unit["unitId"] <= 0
                or type(unit.get("unitCount")) is not int or unit["unitCount"] < 0
                or str(unit["unitId"]) in summary["troops"]):
            return summary
        summary["troops"][str(unit["unitId"])] = unit["unitCount"]
    by_building = {}
    for record in records.values():
        if (not isinstance(record,dict) or not isinstance(record.get("buildingId"),str)
                or record["buildingId"] in by_building):
            return summary
        by_building[record["buildingId"]] = record
    for subtype, building_type in enumerate((9,11,10,12),1):
        queue = queues.get(f"trainingQueue_{subtype}")
        if not isinstance(queue,dict) or queue.get("status") not in ("Free","Completed","InProgress","Lock"):
            return summary
        extra = queue.get("extraData")
        building_id = extra.get("buildingId") if isinstance(extra,dict) else None
        if (queue['status']=='Lock' and isinstance(extra,dict) and building_id is None
                and not any(building.get('type')==building_type for building in buildings.values()
                    if isinstance(building,dict))):
            summary['rows'][str(subtype)]={'building_id':None,'focused':False,'pending':False,
                'unit_id':None,'from_unit_id':None,'count':0,'status':'Lock'}
            continue
        building = buildings.get(building_id)
        if not isinstance(building,dict) or building.get("type") != building_type:
            return summary
        record = by_building.get(building_id)
        row = {"building_id":building_id,"focused":building.get("focused"),"pending":False,
               "unit_id":None,"from_unit_id":None,"count":0,"status":queue["status"]}
        if record is not None:
            if (type(record.get("unitId")) is not int or str(record["unitId"]) not in summary["troops"]
                    or type(record.get("unitCount")) is not int or record["unitCount"] <= 0
                    or type(record.get("endTime")) not in (int,float) or not math.isfinite(record["endTime"])):
                return summary
            if queue["status"] not in ("Completed","InProgress"):
                return summary
            row.update(unit_id=record["unitId"],count=record["unitCount"],from_unit_id=record.get("fromUnitId"))
            row["pending"] = queue["status"] == "Completed" and record["endTime"] <= clock
            if queue["status"] == "Completed" and not row["pending"]:
                return summary
        elif queue["status"] in ("Completed","InProgress"):
            return summary
        summary["rows"][str(subtype)] = row
        summary["completed"] += int(row["pending"])
    summary["ready"] = True
    return summary


def normalize_training_form(values: dict) -> None:
    form = values["training_form"]
    form["ready"] = False
    form["cost"] = None
    config = form.get("config")
    building_id = form.get("building_id")
    building = values.get("buildings",{}).get(building_id)
    if (form.get("visible") is not True or form.get("promoting") is not False or form.get("running") is not False
            or form.get("info") is not False or not isinstance(building,dict) or not isinstance(config,dict)
            or type(form.get("count")) is not int or type(form.get("max_count")) is not int
            or not 1 <= form["count"] <= form["max_count"] <= 1000000
            or type(form.get("tier")) is not int or not 1 <= form["tier"] <= 5):
        return
    tier = form.get("tiers",{}).get(str(form["tier"]))
    if (not isinstance(tier,dict) or not tier.get("known") or tier.get("locked") is not False
            or config.get("Id") != form.get("unit_id") or tier.get("unit_id") != form.get("unit_id")
            or config.get("Tier") != form["tier"] or config.get("BuildingType") != form.get("building_type")
            or building.get("type") != form["building_type"]
            or type(config.get("Time")) not in (int,float) or not math.isfinite(config["Time"]) or config["Time"] <= 0):
        return
    fields = ("Food","Wood","Stone","Coin")
    if any(type(config.get(key)) is not int or config[key] < 0 for key in fields):
        return
    form["cost"] = {str(i):config[key]*form["count"] for i,key in enumerate(fields,1)}
    form["ready"] = True


def normalize_tavern(values: dict) -> None:
    summary = {"ready":False,"rows":{},"available":0,"keys":{}}
    values["tavern_state"] = summary
    clock = values.get("server_time")
    if values.get("tavern_items_known") is not True or type(clock) not in (int,float) or not math.isfinite(clock):
        return
    for name,item_id in (("silver",47),("gold",48),("equip",190)):
        item = values.get("tavern_key_"+name)
        if item is None:
            count = 0
        elif (isinstance(item,dict) and item.get("itemId") == item_id
                and type(item.get("itemCount")) is int and item["itemCount"] >= 0):
            count = item["itemCount"]
        else:
            return
        summary["keys"][name] = count
    for name,field in (("silver","normal"),("gold","rare"),("equip","equip")):
        record = values.get("tavern_"+field)
        if not isinstance(record,dict) or record.get("$truncated"):
            return
        next_free = record.get("NextFreeTime")
        remaining = record.get("FreeTimes") if name == "silver" else 1
        if (type(next_free) not in (int,float) or not math.isfinite(next_free) or next_free <= 0
                or type(remaining) is not int or not 0 <= remaining <= 1000):
            return
        available = next_free <= clock and remaining > 0
        summary["rows"][name] = {"next":next_free,"remaining":remaining,"available":available}
        summary["available"] += int(available)
    summary["ready"] = True


def normalize_city_resources(values: dict) -> None:
    summary = {"ready":False,"groups":{},"pending":0}
    values["city_resource_state"] = summary
    records,buildings = values.get("city_resources"),values.get("buildings")
    if (not isinstance(records,dict) or not isinstance(buildings,dict)
            or records.get("$truncated") or buildings.get("$truncated")):
        return
    for key,record in records.items():
        building = buildings.get(key)
        if not isinstance(record,dict) or not isinstance(building,dict) or record.get("id") != key:
            return
        kind = record.get("rssType")
        if (type(kind) is not int or kind not in (1,2,3,4) or record.get("type") != kind+1
                or building.get("type") != kind+1 or record.get("rssProduceState") not in (1,2,3)):
            return
        amount,minimum,limit = (record.get(field) for field in ("rssValue","gatherMin","gatherLimit"))
        if (any(type(value) not in (int,float) or not math.isfinite(value) for value in (amount,minimum,limit))
                or not 0 < minimum <= limit or not 0 <= amount <= limit+1
                or any(type(building.get(field)) not in (int,float) or not math.isfinite(building[field])
                       for field in ("world_x","world_y"))):
            return
        group = summary["groups"].setdefault(str(kind),{"pending":[],"amount":0})
        if record["rssProduceState"] in (2,3) and amount >= minimum:
            group["pending"].append(key)
            group["amount"] += math.floor(amount)
            summary["pending"] += 1
    summary["ready"] = True


def normalize_materials(values: dict) -> None:
    summary = {"ready":False,"used":0,"free":[],"pending":{},"orders":{},"inventory":{},"ui_ready":False}
    values["material_state"] = summary
    orders,buildings,clock = (values.get(k) for k in ("material_orders","buildings","server_time"))
    if (not isinstance(orders,dict) or set(orders) != {str(i) for i in range(1,6)}
            or not isinstance(buildings,dict) or buildings.get("$truncated")
            or type(clock) not in (int,float) or not math.isfinite(clock)
            or values.get("material_items_known") is not True):
        return
    found = [key for key,row in buildings.items() if isinstance(row,dict) and row.get("type")==31]
    if len(found)!=1:return
    summary["building_id"] = found[0]
    for item in MATERIALS:
        record = values.get("material_item_"+str(item))
        if record is None:count=0
        elif (isinstance(record,dict) and record.get("itemId")==item
              and type(record.get("itemCount")) is int and record["itemCount"]>=0):count=record["itemCount"]
        else:return
        summary["inventory"][str(item)] = count
    active,queued = 0,0
    for key,row in orders.items():
        if (not isinstance(row,dict) or type(row.get("Index")) is not int or row["Index"]!=int(key)
                or type(row.get("State")) is not int or row["State"] not in (1,2,3,4)):return
        if row["State"]==1:
            summary["free"].append(key)
            continue
        if (type(row.get("ItemId")) is not int or row["ItemId"] not in MATERIALS
                or type(row.get("Count")) is not int or row["Count"]!=15):return
        summary["orders"][key] = {"item":row["ItemId"],"count":row["Count"],"state":row["State"]}
        summary["used"] += 1
        if row["State"]==2:queued += 1
        elif row["State"]==4:
            end=row.get("endTime")
            if type(end) not in (int,float) or not math.isfinite(end) or not 0<end<=clock:return
            item=str(row["ItemId"])
            summary["pending"][item]=summary["pending"].get(item,0)+row["Count"]
        else:
            active += 1
            end = row.get("endTime")
            if (type(end) not in (int,float) or not math.isfinite(end) or end<=0
                    or row.get("TotalTime")!=10800000):return
            # The server moves finished orders to State4 and advances/reindexes
            # the running queue before collection. An expired local State3 timer
            # alone is not a collection receipt or permission to collect.
            if end<=clock:return
    if active>1 or queued and not active:return
    summary["ready"] = True
    ui = values.get("material_ui")
    if (not isinstance(ui,dict) or ui.get("known") is not True or ui.get("visible") is not True
            or ui.get("building_id")!=found[0] or ui.get("back_to_forge") is not False
            or any(type(ui.get(k)) is not int or ui[k]!=v for k,v in
                   (("left",1),("top",1),("list_type",1),("capacity",5),("batch",15)))):return
    recipes = ui.get("recipes")
    if not isinstance(recipes,dict) or set(recipes)!={"1","2","3","4"}:return
    for index,(item,kind) in enumerate(((412,2),(413,3),(417,7),(414,4)),1):
        row = recipes[str(index)]
        expected = {"ID":item,"itemId":item,"Order":index,"ProduceTime":720,"Quality":1,"CLASS":kind}
        if not isinstance(row,dict) or any(type(row.get(k)) is not int or row[k]!=v for k,v in expected.items()):return
    summary["ui_ready"] = True


def training_keyboard_owned(values: dict) -> bool:
    keyboard,form = values.get("training_keyboard"),values.get("training_form")
    if (not isinstance(keyboard,dict) or not isinstance(form,dict) or keyboard.get("visible") is not True
            or form.get("visible") is not True or form.get("ready") is not True
            or form.get("promoting") is not False or form.get("running") is not False or form.get("info") is not False):
        return False
    maximum,initial = form.get("max_count"),keyboard.get("initial")
    fixed = type(keyboard.get("max")) is int and keyboard["max"] == maximum
    # New game sessions can supply a maximum callback, leaving the scalar maximum at zero.
    # Observe that callback's presence; never invoke it. Training's own verified capacity
    # still bounds every configured quantity and the confirmed form after keypad input.
    dynamic = (type(keyboard.get("max")) is int and keyboard["max"] == 0 and keyboard.get("dynamic_max") is True
        and keyboard.get("change_callback") is True and keyboard.get("confirm_callback") is True
        and type(initial) is int and type(maximum) is int and 0 <= initial <= maximum
        and type(keyboard.get("first")) is bool
        and (keyboard["first"] is False or initial == form.get("count")))
    pos = keyboard.get("position")
    return bool((fixed or dynamic) and type(keyboard.get("min")) is int and keyboard["min"] == 0 and keyboard.get("title") == ""
        and keyboard.get("y_offset") == 0 and keyboard.get("right_offset") == 0
        and isinstance(pos,dict) and type(pos.get("x")) in (int,float) and type(pos.get("y")) in (int,float)
        and abs(pos["x"]*960/1334-770)<3 and abs(540-pos["y"]*960/1334-317)<3)


def normalize_donation(values: dict) -> None:
    data = values.get("donation")
    if not isinstance(data,dict):
        values["donation"] = {"ready":False,"available":False}
        return
    data.update(ready=False,available=False)
    if (data.get("needs_refresh") is not False or type(data.get("recommend")) is not int
            or type(data.get("maximum")) is not int or not 1 <= data["maximum"] <= 100
            or type(data.get("chances")) is not int or not 0 <= data["chances"] <= data["maximum"]
            or type(data.get("today")) is not int or not 0 <= data["today"] <= 2000000000):
        return
    target,config = data.get("target"),data.get("config")
    if not isinstance(target,dict) or not isinstance(config,dict):
        return
    if (any(type(target.get(key)) is not int for key in ("type","level","max_level","science_point","end_time"))
            or target.get("is_alliance") is not True or target["type"] != data["recommend"]
            or not 0 <= target["level"] < target["max_level"] <= 100 or target["end_time"] < 0
            or any(type(config.get(key)) is not int for key in
                ("ID","Type","Level","Class","TechniquePoint","DonateType","DonateValue","DonateGem"))
            or config["ID"] != target["type"]*100+target["level"]+1
            or config["Type"] != target["type"] or config["Level"] != target["level"]+1
            or config["Class"] != target["type"]//100 or config["Class"] not in (1,2,3)
            or config["DonateType"] not in (1,2,3,4) or not 0 < config["DonateValue"] <= 1000000
            or config["DonateGem"] < 0 or not 0 <= target["science_point"] <= config["TechniquePoint"]
            or config["TechniquePoint"] <= 0):
        return
    data["ready"] = True
    data["available"] = (data["chances"] > 0 and target["end_time"] == 0
                         and target["science_point"] < config["TechniquePoint"])


class Reader:
    """One independently attached game process and one read-only agent per instance."""

    def __init__(self, instance: Instance, server_path: str = "/data/local/tmp/mirage-frida-server"):
        self.instance = instance
        self.adb = Adb(instance)
        self.server_path = server_path
        self.session = None
        self.device = None
        self.script = None
        self.forward_port = None
        self.address = None
        self.version = ""
        self.pid = 0
        self.last_error = ""
        self._last_clock: float | None = None
        self._clock_changed_at = 0.0

    def connect(self) -> None:
        if self.instance.power != Power.ONLINE:
            raise MemoryError("Для подключения нужен уже работающий эмулятор")
        if self.instance.cpus < MIN_CPUS or self.instance.memory_mb < MIN_MEMORY_MB:
            raise MemoryError("Для игры нужны минимум 2 CPU-ядра и 2 ГБ ОЗУ")
        if not re.fullmatch(r"/data/local/tmp/[A-Za-z0-9_.-]+", self.server_path):
            raise MemoryError("Некорректный путь Android runtime")
        self.close()
        try:
            self.adb.connect()
            root = self.adb.root()
            self.version = self.adb.version()
            if self.version not in SUPPORTED_VERSIONS:
                raise MemoryError(f"Версия игры {self.version} ещё не проверена адаптером")
            self.pid = self.adb.pid()
            version = self.adb.root_shell(root, f"{shlex.quote(self.server_path)} --version", timeout=5).strip()
            if version != frida.__version__:
                raise MemoryError(f"Версия Android runtime ({version}) отличается от клиента ({frida.__version__})")
            self.forward_port = self.adb.forward(27183)
            self.address = f"127.0.0.1:{self.forward_port}"
            self.device = frida.get_device_manager().add_remote_device(self.address)
            try:
                self.device.enumerate_processes()
            except (frida.TransportError, frida.ServerNotRunningError):
                self.adb.root_shell(root, f"{shlex.quote(self.server_path)} -l 127.0.0.1:27183 -D", timeout=5)
                self.device.enumerate_processes()
            self.session = self.device.attach(self.pid)
            self.session.on("detached", self._detached)
            self.last_error = ""
            self._last_clock = None
            self._clock_changed_at = time.monotonic()
            source = importlib.resources.files("mirage").joinpath("agents/state_reader.js").read_text(encoding="utf-8")
            self.script = self.session.create_script(source)
            self.script.on("message", self._message)
            self.script.load()
            if self.last_error:
                raise MemoryError(self.last_error)
            status = self.script.exports_sync.status()
            if not status["stateReady"]:
                raise MemoryError("Lua-состояние ещё не создано: войдите в игровой мир")
            self.last_error = ""
        except Exception:
            self.close()
            raise

    def _detached(self, reason, crash=None):
        self.last_error = f"Игровое подключение разорвано: {reason}"

    def _message(self, message, data):
        if message.get("type") == "error":
            self.last_error = str(message.get("description", "Ошибка Android-адаптера"))

    def snapshot(self, extra_paths: dict | None = None) -> Snapshot:
        if self.script is None or self.last_error:
            raise MemoryError(self.last_error or "Адаптер не подключён")
        self.adb.verify_identity()
        if self.adb.pid() != self.pid:
            raise MemoryError("Игровой процесс сменился; требуется новое подключение")
        if extra_paths and PATHS.keys() & extra_paths.keys():
            raise MemoryError("Дополнительные поля не могут заменять базовую идентичность и состояние")
        try:
            raw = self.script.exports_sync.snapshot({**PATHS, **(extra_paths or {})}, 3)
        except (frida.RPCException, frida.InvalidOperationError, frida.TransportError,
                frida.ServerNotRunningError) as error:
            raise MemoryError("Не удалось прочитать игровой процесс: " + str(error)) from error
        if raw.get("pid") != self.pid or raw.get("luaVersion") != "Lua 5.1":
            raise MemoryError("Неверная идентичность процесса или Lua ABI")
        player = raw["values"].get("player")
        if (not isinstance(player, dict) or type(player.get("PlayerID")) not in (int, float)
                or not math.isfinite(player["PlayerID"]) or int(player["PlayerID"]) != player["PlayerID"]):
            raise MemoryError("Состояние персонажа ещё не доступно")
        player_id = int(player["PlayerID"])
        if player_id <= 0:
            raise MemoryError("Не подтверждён ID персонажа")
        game_time = raw["values"].get("server_time")
        if type(game_time) not in (int, float) or not math.isfinite(game_time) or game_time <= 0:
            raise MemoryError("Не получены актуальные игровые часы")
        now = time.monotonic()
        if game_time != self._last_clock:
            self._clock_changed_at = now
            self._last_clock = game_time
        elif now - self._clock_changed_at > 5:
            raise MemoryError("Игровые часы не обновляются больше пяти секунд")
        captured = raw["capturedMs"] / 1000
        if abs(time.time() - captured) > 10:
            raise MemoryError("Время наблюдения недостоверно")
        daily = raw["values"].get("daily_quests")
        chests = raw["values"].get("daily_chests")
        score = raw["values"].get("daily_score")
        raw["values"]["daily_ready_count"] = (
            sum(1 for quest in daily.values() if isinstance(quest, dict) and quest.get("Stat") == 2)
            if isinstance(daily, dict) and not daily.get("$truncated") else None)
        raw["values"]["daily_chest_count"] = (
            sum(1 for index, threshold in enumerate((20, 40, 60, 80, 100), 1)
                if isinstance(chests.get(str(index)), dict)
                and chests[str(index)].get("Completed") is False and score >= threshold)
            if isinstance(chests, dict) and not chests.get("$truncated") and type(score) in (int, float) else None)
        refresh = raw["values"].get("daily_refresh_ts")
        raw["values"]["daily_refresh_due"] = game_time >= refresh if type(refresh) in (int, float) and refresh > 0 else None
        buildings = raw["values"].get("buildings")
        known = isinstance(buildings,dict) and not buildings.get("$truncated")
        selection = [key for key,item in buildings.items() if isinstance(item,dict) and item.get("selected") is True] if known else []
        raw["values"]["city_selection_known"] = known and len(selection) <= 1
        raw["values"]["city_selection"] = selection[0] if len(selection) == 1 else None
        if "expedition_infos" in raw["values"]:
            infos = raw["values"]["expedition_infos"]
            ready = isinstance(infos, dict) and not infos.get("$truncated")
            if ready:
                ready = all(isinstance(info, dict)
                            and type(info.get("star")) in (int, float) and info["star"] in (0, 1, 2, 3)
                            and type(info.get("getRewardStar")) in (int, float)
                            and info["getRewardStar"] in (0, 1, 2, 3) and info["getRewardStar"] <= info["star"]
                            and (info["star"] != 3 or info["getRewardStar"] in (0, 3))
                            for info in infos.values())
            raw["values"]["expedition_data_ready"] = bool(ready)
            raw["values"]["expedition_pending"] = (
                sum(info["star"] == 3 and info["getRewardStar"] == 0 for info in infos.values()) if ready else None)
        if "training_queues" in raw["values"]:
            raw["values"]["training_summary"] = training_summary(raw["values"])
            rows, filters = raw["values"].get("queue_rows"), raw["values"].get("queue_filters")
            head = rows.get("1") if isinstance(rows,dict) else None
            raw["values"]["training_layout_ready"] = bool(
                isinstance(rows,dict) and not rows.get("$truncated") and isinstance(filters,dict)
                and filters.get("1") is True and isinstance(head,dict) and head.get("type") == "trainingTab"
                and head.get("visible") is True and head.get("filtered") is True
                and all(isinstance(rows.get(str(i+1)),dict) and rows[str(i+1)].get("type") == "trainingQueue"
                        and rows[str(i+1)].get("subType") == i for i in range(1,5)))
        if "training_form" in raw["values"]:
            normalize_training_form(raw["values"])
            menu = raw["values"].get("training_menu")
            selected = menu.get("selected") if isinstance(menu,dict) and menu.get("known") is True else None
            raw["values"]["training_menu_type"] = None
            if isinstance(selected,dict):
                summary = raw["values"].get("training_summary",{})
                buttons = {9:"btn_FunctionBarracks",11:"btn_FunctionArcheryRange",10:"btn_FunctionStable",12:"btn_FunctionSiegeWorkshop"}
                for subtype, row in summary.get("rows",{}).items():
                    if (selected.get("id") == row["building_id"] and row["focused"] is True
                            and selected.get("type") in buttons
                            and set(selected.get("buttons",[])) == {"btn_CityPopUpInfo",buttons[selected["type"]]}):
                        raw["values"]["training_menu_type"] = int(subtype)
            raw["values"]["training_keyboard_owned"] = training_keyboard_owned(raw["values"])
        if "tavern_normal" in raw["values"]:
            normalize_tavern(raw["values"])
        if "city_resources" in raw["values"]:
            normalize_city_resources(raw["values"])
        if "donation" in raw["values"]:
            normalize_donation(raw["values"])
        if "material_orders" in raw["values"]:
            normalize_materials(raw["values"])
        if "wall" in raw["values"]:
            from .wall import normalize_wall
            normalize_wall(raw["values"])
        return Snapshot(self.instance.id, self.pid, player_id, now, self.version, raw["values"])

    def close(self) -> None:
        session, self.session = self.session, None
        self.script = None
        if session is not None:
            try:
                session.detach()
            except frida.InvalidOperationError:
                pass
        if self.address:
            try:
                frida.get_device_manager().remove_remote_device(self.address)
            except frida.InvalidArgumentError:
                pass
            self.address = None
        if self.forward_port is not None:
            try:
                self.adb.remove_forward(self.forward_port)
            except CommandError:
                pass
            self.forward_port = None
        self.device = None
