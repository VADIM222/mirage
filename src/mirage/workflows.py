from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
import math
import threading
import time
from typing import Any, Callable, Protocol

from .model import Snapshot


class WorkflowError(RuntimeError):
    pass


class Cancelled(WorkflowError):
    pass


class NotReady(WorkflowError):
    pass


class Input(Protocol):
    def tap(self, x: int, y: int, *, hold_ms: int = 0) -> None: ...
    def tap_resolved(self, resolve: Callable[[], tuple[int,int]], *, hold_ms: int = 100) -> None: ...
    def drag(self, x: int, y: int, end_x: int, end_y: int, *, duration_ms: int = 300) -> None: ...
    def back(self) -> None: ...


def field(snapshot: Snapshot, path: tuple[str, ...]):
    value: Any = snapshot.values
    for key in path:
        if not isinstance(value, dict) or key not in value:
            raise WorkflowError(f"Не наблюдается обязательное поле {'.'.join(path)}")
        value = value[key]
    return value


@dataclass(frozen=True)
class Condition:
    path: tuple[str, ...]
    comparison: str
    value: Any

    def matches(self, snapshot: Snapshot) -> bool:
        actual = field(snapshot, self.path)
        if self.comparison == "eq":
            return actual == self.value
        if self.comparison == "ne":
            return actual != self.value
        if self.comparison == "gt":
            return isinstance(actual, (int, float)) and actual > self.value
        if self.comparison == "lt":
            return isinstance(actual, (int, float)) and actual < self.value
        if self.comparison == "subset":
            return isinstance(actual, (dict, list, tuple)) and set(actual).issubset(set(self.value))
        raise WorkflowError("Неизвестная операция условия")


@dataclass(frozen=True)
class All:
    conditions: tuple[Condition | All | AnyOf, ...]

    def matches(self, snapshot: Snapshot) -> bool:
        return all(condition.matches(snapshot) for condition in self.conditions)


@dataclass(frozen=True)
class AnyOf:
    conditions: tuple[Condition | All | AnyOf, ...]

    def matches(self, snapshot: Snapshot) -> bool:
        return any(condition.matches(snapshot) for condition in self.conditions)


@dataclass(frozen=True)
class CountIncrease:
    path: tuple[str, ...]
    amount_path: tuple[str, ...]
    key_path: tuple[str, ...] | None = None

    def capture(self, snapshot: Snapshot) -> Condition:
        path = self.path
        if self.key_path is not None:
            key = field(snapshot, self.key_path)
            if type(key) is not int or key <= 0:
                raise WorkflowError("Не подтверждён тип получаемых войск")
            path += (str(key),)
        before, amount = field(snapshot, path), field(snapshot, self.amount_path)
        if (type(before) is not int or before < 0 or type(amount) is not int or amount <= 0
                or not math.isfinite(before + amount)):
            raise WorkflowError("Не подтверждено количество получаемых войск")
        return Condition(path, "eq", before + amount)


@dataclass(frozen=True)
class Tap:
    x: int
    y: int
    precondition: Condition | All | AnyOf
    postcondition: Condition | All | AnyOf
    timeout: float = 8
    hold_ms: int = 0
    when: Condition | All | AnyOf | None = None
    settle: float = 0
    increase: CountIncrease | None = None


@dataclass(frozen=True)
class NavigateCity:
    building_type: int
    when: Condition | All | AnyOf | None = None
    building_id: str | None = None
    select: bool = True


@dataclass(frozen=True)
class Procedure:
    action: Callable
    when: Condition | All | AnyOf | None = None


@dataclass(frozen=True)
class Workflow:
    task_id: str
    game_version: str
    width: int
    height: int
    steps: tuple[Tap | NavigateCity | Procedure, ...]
    verified: bool = False
    precondition: Condition | All | AnyOf | None = None
    when: Condition | All | AnyOf | None = None
    wait_reason: str = "Ожидание игрового экрана для выполнения задачи"
    extra_paths: dict[str, list[str | int]] = dataclass_field(default_factory=dict)
    entry_condition: Condition | All | AnyOf | None = None
    data_condition: Condition | All | AnyOf | None = None
    data_timeout: float = 3
    requires_city: bool = True
    guide_condition: Condition | All | AnyOf | None = None


class Engine:
    def __init__(self, input_device: Input, observe: Callable[[], Snapshot],
                  clock: Callable[[], float] = time.monotonic, *, resolution: tuple[int,int] | None = None,
                  allowed: Callable[[], bool] = lambda: True,
                  on_observed: Callable[[Snapshot], None] = lambda state: None):
        self.input = input_device
        self.observe = observe
        self.clock = clock
        self.resolution = resolution
        self.allowed = allowed
        self.on_observed = on_observed

    def execute(self, workflow: Workflow, cancelled: threading.Event,
                *, instance_id: str, player_id: int, pid: int) -> Snapshot:
        if not workflow.verified or not workflow.steps:
            raise WorkflowError("Игровой сценарий ещё не подтверждён живой проверкой")
        if self.resolution is not None and self.resolution != (workflow.width, workflow.height):
            raise WorkflowError("Разрешение эмулятора не соответствует профилю действий")
        if workflow.data_condition is not None and not 0 < workflow.data_timeout <= 10:
            raise WorkflowError("Некорректное время ожидания данных")

        def observe() -> Snapshot:
            deadline = self.clock()+workflow.data_timeout
            while True:
                if cancelled.is_set() or not self.allowed():
                    raise Cancelled("Выполнение отменено")
                state = self.observe()
                if state.instance_id != instance_id or state.pid != pid or state.player_id != player_id:
                    raise WorkflowError("Экземпляр, процесс или персонаж изменился во время задачи")
                if state.game_version != workflow.game_version or not state.fresh(self.clock()):
                    raise WorkflowError("Состояние игры устарело или версия несовместима")
                self.on_observed(state)
                if "PopupMissionComplete" in state.values.get("views",{}):
                    # A game-owned completion animation can briefly overlap the
                    # next task. Wait for its observed removal, never dismiss or
                    # treat it as a free HUD while active.
                    if self.clock() >= deadline:
                        raise NotReady("Ожидание завершения игрового уведомления")
                    if cancelled.wait(.1):raise Cancelled("Выполнение отменено")
                    continue
                if ("QuestGuide" in state.values.get("views",{})
                        and (state.values.get("guide_force_click") is not False
                             or state.values.get("guide_click_callback") is not False)
                        and (workflow.guide_condition is None or not workflow.guide_condition.matches(state))):
                    raise NotReady("Ожидание завершения обязательной игровой подсказки")
                if workflow.precondition is not None and not workflow.precondition.matches(state):
                    raise NotReady(workflow.wait_reason)
                if workflow.data_condition is None or workflow.data_condition.matches(state):
                    return state
                if self.clock() >= deadline:
                    raise NotReady(workflow.wait_reason)
                if cancelled.wait(.1):
                    raise Cancelled("Выполнение отменено")

        last = observe()
        if workflow.entry_condition is not None and not workflow.entry_condition.matches(last):
            raise NotReady(workflow.wait_reason)
        if workflow.when is not None and not workflow.when.matches(last):
            return last
        for step in workflow.steps:
            last = observe()
            if step.when is not None and not step.when.matches(last):
                continue
            if isinstance(step,NavigateCity):
                from .navigation import navigate_city
                last = navigate_city(self.input,observe,cancelled,self.clock,step.building_type,self.allowed,
                                     building_id=step.building_id,select=step.select)
                continue
            if isinstance(step,Procedure):
                last = step.action(self.input,observe,cancelled,self.clock,self.allowed)
                continue
            if step.postcondition.matches(last):
                continue
            if not step.precondition.matches(last):
                raise NotReady(f"{workflow.task_id}: предусловие нажатия ({step.x}, {step.y}) пока не выполнено")
            if cancelled.is_set() or not self.allowed():
                raise Cancelled("Выполнение отменено")
            if not 0 <= step.x < workflow.width or not 0 <= step.y < workflow.height:
                raise WorkflowError("Координаты сценария находятся вне экрана")
            if step.timeout <= 0 or step.timeout > 120:
                raise WorkflowError("Некорректный тайм-аут действия")
            if not 0 <= step.settle <= step.timeout:
                raise WorkflowError("Некорректное время ожидания интерфейса")
            if step.hold_ms not in (0, 100):
                raise WorkflowError("Некорректная длительность нажатия")
            increase = step.increase.capture(last) if step.increase is not None else None
            if step.hold_ms:
                self.input.tap(step.x, step.y, hold_ms=step.hold_ms)
            else:
                self.input.tap(step.x, step.y)
            tapped_at = self.clock()
            deadline = tapped_at + step.timeout
            while True:
                last = observe()
                if (step.postcondition.matches(last) and (increase is None or increase.matches(last))
                        and (not step.settle or self.clock() >= tapped_at + step.settle)):
                    break
                if self.clock() >= deadline:
                    raise WorkflowError(f"{workflow.task_id}: результат нажатия ({step.x}, {step.y}) не подтверждён")
                if cancelled.wait(0.1):
                    raise Cancelled("Выполнение отменено")
        return last


# Entries are added only after a real game action and its state transition are verified.
# Read-only adapter support is deliberately not advertised as completed farming logic.
CITY_VIEWS = ("MapHudPanel", "MapUIDragMoveHandler", "UIObject", "StrategicViewProvinceTittle",
              "AlliMarkElementHUD", "CityReflowUIContainerHud", "MapElementHud3D", "CityUIContainerHud", "MapElementHud", "QuestGuide")
QUEUE_KNOWN = Condition(("queue_panel", "known"), "eq", True)
QUEUE_SHOWN = All((QUEUE_KNOWN, Condition(("queue_panel", "visible"), "eq", True)))
QUEUE_HIDDEN = All((QUEUE_KNOWN, Condition(("queue_panel", "visible"), "eq", False)))
CITY_SCENE = All((
    Condition(("hud_visible",), "eq", True),
    Condition(("hud_menu",), "eq", False),
    Condition(("in_city",), "eq", True),
    Condition(("city_enabled",), "eq", True),
    Condition(("views",), "subset", CITY_VIEWS),
))
NO_SELECTION = All((Condition(("city_selection_known",),"eq",True),Condition(("city_selection",),"eq",None)))
CITY_HUD = All((CITY_SCENE, QUEUE_HIDDEN, NO_SELECTION))


# At the outer gate a camera gesture can cross into the world-map context even
# while the city model remains rendered. Only the normal HUD permits returning.
MAP_HUD = All((QUEUE_HIDDEN,NO_SELECTION,Condition(("hud_visible",),"eq",True),
    Condition(("hud_menu",),"eq",False),
    AnyOf((Condition(("in_city",),"eq",False),Condition(("in_city",),"eq",True))),
    Condition(("views",),"subset",CITY_VIEWS)))
RETURN_TO_CITY = Workflow("return_city","1.1.12.20",960,540,(
    Tap(45,490,All((MAP_HUD,Condition(("city_enabled",),"eq",True))),
        Condition(("city_enabled",),"eq",False),hold_ms=100,timeout=20,settle=1.2,
        when=All((Condition(("in_city",),"eq",False),Condition(("city_enabled",),"eq",True)))),
    Tap(45,490,All((MAP_HUD,Condition(("city_enabled",),"eq",False))),
        CITY_HUD,hold_ms=100,timeout=20,settle=1.2,
        when=AnyOf((Condition(("in_city",),"eq",False),Condition(("city_enabled",),"eq",False))))),
    verified=True,when=AnyOf((Condition(("in_city",),"eq",False),Condition(("city_enabled",),"eq",False))),requires_city=False)
QUEUE_CLOSE = Tap(248,275, All((QUEUE_SHOWN,
    Condition(("hud_visible",), "eq", True),Condition(("in_city",), "eq", True),
    Condition(("views",), "subset", CITY_VIEWS))), QUEUE_HIDDEN,
    hold_ms=100, when=Condition(("queue_panel", "visible"), "eq", True), settle=.25)

# Reward actions are registered only after their observed transitions are confirmed.
REWARD_POPUP = Condition(("reward_popup_visible",), "eq", True)
NO_REWARD_POPUP = Condition(("reward_popup_visible",), "eq", False)
VIP_POINTS_AVAILABLE = Condition(("vip_points_available",), "eq", True)
VIP_BOX_AVAILABLE = Condition(("vip_box_available",), "eq", True)
VIP_VISIBLE = Condition(("vip_visible",), "eq", True)
VIP_NOTICE = Condition(("vip_notice_visible",), "eq", True)
VIP_PANEL = All((
    VIP_VISIBLE,
    Condition(("vip_level",), "eq", 12),
    Condition(("vip_shown_level",), "eq", 12),
    Condition(("vip_box_detail",), "eq", False),
    Condition(("vip_opening_box",), "eq", False),
    Condition(("views",), "subset", CITY_VIEWS + ("VIPMainPage", "CommonBackground")),
))
VIP_DISMISS = Tap(480, 500, All((REWARD_POPUP, VIP_VISIBLE)),
                  All((NO_REWARD_POPUP, VIP_PANEL)), hold_ms=100, when=REWARD_POPUP)
VIP_NOTICE_DISMISS = Tap(480, 500, All((VIP_NOTICE, VIP_VISIBLE)),
                          All((Condition(("vip_notice_visible",), "eq", False), VIP_PANEL)), hold_ms=100, when=VIP_NOTICE)
SELECTION_CLEAR = (
    Tap(108,46,All((CITY_SCENE,QUEUE_HIDDEN,Condition(("city_selection_known",),"eq",True))),
        VIP_VISIBLE,hold_ms=100,when=Condition(("city_selection",),"ne",None),settle=.2),
    Tap(818,62,All((VIP_VISIBLE,NO_SELECTION,Condition(("views",),"subset",CITY_VIEWS+("VIPMainPage","CommonBackground")))),
        CITY_HUD,hold_ms=100,when=VIP_VISIBLE,settle=.2),
)
VIP_REWARD = Workflow("vip_reward", "1.1.12.20", 960, 540, (
    QUEUE_CLOSE,
    Tap(108, 46, All((CITY_SCENE,QUEUE_HIDDEN)), VIP_VISIBLE, hold_ms=100),
    VIP_DISMISS,
    VIP_NOTICE_DISMISS,
    Tap(765, 152, VIP_PANEL, All((Condition(("vip_points_available",), "eq", False), VIP_NOTICE)), hold_ms=100, when=VIP_POINTS_AVAILABLE),
    VIP_NOTICE_DISMISS,
    Tap(705, 267, VIP_PANEL, All((Condition(("vip_box_available",), "eq", False), REWARD_POPUP)), hold_ms=100, when=VIP_BOX_AVAILABLE),
    VIP_DISMISS,
    Tap(818, 62, VIP_PANEL, CITY_HUD, hold_ms=100),
), verified=True, precondition=All((
    QUEUE_KNOWN,
    Condition(("vip_level",), "eq", 12),
    Condition(("hud_visible",), "eq", True),
    Condition(("hud_menu",), "eq", False),
    Condition(("in_city",), "eq", True),
    # CommonItemBagPage is the temporary bag icon used by the reward flight animation.
    # It is allowed while observing, but VIP_PANEL prevents input until it disappears.
    Condition(("views",), "subset", CITY_VIEWS + ("VIPMainPage", "CommonBackground", "RoutineRewardsCollect", "VIPNotice", "CommonItemBagPage")),
)), when=AnyOf((VIP_POINTS_AVAILABLE, VIP_BOX_AVAILABLE, VIP_VISIBLE, REWARD_POPUP)),
    wait_reason="Нужны VIP 12 и свободный городской/VIP-экран")

QUEST_VISIBLE = Condition(("quest_visible",), "eq", True)
DAILY_READY = Condition(("daily_ready_count",), "gt", 0)
QUEST_PANEL = All((QUEST_VISIBLE, Condition(("quest_tab",), "eq", 2), NO_REWARD_POPUP,
                   Condition(("daily_refresh_due",), "eq", False),
                   Condition(("views",), "subset", CITY_VIEWS + ("QuestSystemMainPage", "CommonBackground"))))
QUEST_DISMISS = Tap(480, 500, All((QUEST_VISIBLE, REWARD_POPUP)), All((NO_REWARD_POPUP, QUEST_PANEL)), hold_ms=100, when=REWARD_POPUP)
DAILY_CHESTS = tuple(step for index, (threshold, x) in
    enumerate(((20, 270), (40, 396), (60, 534)), 1) for step in (
    Tap(x, 145, QUEST_PANEL, All((Condition(("daily_chests", str(index), "Completed"), "eq", True), REWARD_POPUP)), hold_ms=100,
        when=All((Condition(("daily_score",), "gt", threshold - 1),
                  Condition(("daily_chests", str(index), "Completed"), "eq", False)))), QUEST_DISMISS))
DAILY_REWARD = Workflow("quests", "1.1.12.20", 960, 540, (
    QUEUE_CLOSE,
    *SELECTION_CLEAR,
    Tap(30, 155, CITY_HUD, QUEST_VISIBLE, hold_ms=100),
    QUEST_DISMISS,
    Tap(77, 239, QUEST_VISIBLE, QUEST_PANEL, hold_ms=100),
    Tap(755, 255, All((QUEST_PANEL, Condition(("quest_first", "Stat"), "eq", 2))),
        All((Condition(("daily_ready_count",), "eq", 0), Condition(("quest_collecting",), "eq", {}))),
        timeout=15, hold_ms=100, when=DAILY_READY),
    *DAILY_CHESTS,
    Tap(818, 62, QUEST_PANEL, CITY_HUD, hold_ms=100),
), verified=True, precondition=All((
    QUEUE_KNOWN,
    Condition(("daily_refresh_due",), "eq", False),
    Condition(("hud_visible",), "eq", True),
    Condition(("hud_menu",), "eq", False),
    Condition(("in_city",), "eq", True),
    Condition(("views",), "subset", CITY_VIEWS + ("QuestSystemMainPage", "VIPMainPage", "CommonBackground", "RoutineRewardsCollect", "CommonItemBagPage")),
)), when=AnyOf((DAILY_READY, QUEST_VISIBLE,
    All((Condition(("daily_score",), "gt", 19), Condition(("daily_chests", "1", "Completed"), "eq", False))),
    All((Condition(("daily_score",), "gt", 39), Condition(("daily_chests", "2", "Completed"), "eq", False))),
    All((Condition(("daily_score",), "gt", 59), Condition(("daily_chests", "3", "Completed"), "eq", False))))),
    wait_reason="Ожидание актуальных ежедневных заданий и доступного игрового экрана")


MAIL_FIELDS = {
    "mail_summary":["@mail_summary"],
    "mail_visible":["@active_view", "AllUIMailMainPage"],
    "mail_box":["UIObjectManager", "AllUIMailMainPage", "CurSelectBoxIndex"],
    "mail_edit":["UIObjectManager", "AllUIMailMainPage", "IsEditMode"],
    "mail_reward_visible":["@active_view", "UniversalRewardsCollect"],
    "mail_reward_click":["UIObjectManager", "UniversalRewardsCollect", "canClick"],
    "mail_reward_recycle":["UIObjectManager", "UniversalRewardsCollect", "isRecycleMode"],
}
HUD_MENU = All((
    QUEUE_HIDDEN,
    Condition(("hud_visible",), "eq", True), Condition(("in_city",), "eq", True),
    Condition(("hud_menu",), "eq", True), Condition(("views",), "subset", CITY_VIEWS),
))
MAIL_VISIBLE = Condition(("mail_visible",), "eq", True)
MAIL_REWARD_VISIBLE = Condition(("mail_reward_visible",), "eq", True)
MAIL_PANEL = All((
    MAIL_VISIBLE, Condition(("mail_edit",), "eq", False),
    Condition(("mail_reward_visible",), "eq", False),
    Condition(("views",), "subset", CITY_VIEWS + ("AllUIMailMainPage", "CommonBackground")),
))
MAIL_CONFIRM = Tap(484, 398, All((
    MAIL_VISIBLE, MAIL_REWARD_VISIBLE, Condition(("mail_reward_click",), "eq", True),
    Condition(("mail_reward_recycle",), "eq", False),
)), MAIL_PANEL, hold_ms=100, when=MAIL_REWARD_VISIBLE)
MAIL_NEEDED = AnyOf((MAIL_VISIBLE, Condition(("mail_summary", "pending"), "gt", 0),
                     Condition(("mail_summary", "unread"), "gt", 0)))
MAIL_BOX_STEPS = tuple(step for box, index, x in (("SystemBox", 4, 428), ("AllianceBox", 3, 306), ("Report", 2, 188))
    for step in (
        Tap(x, 31, MAIL_PANEL, Condition(("mail_box",), "eq", index), hold_ms=100,
            when=AnyOf((Condition(("mail_summary", "boxes", box, "pending"), "gt", 0),
                        Condition(("mail_summary", "boxes", box, "unread"), "gt", 0)))),
        Tap(90, 500, All((MAIL_PANEL, Condition(("mail_box",), "eq", index))),
            All((Condition(("mail_summary", "boxes", box, "pending"), "eq", 0),
                 Condition(("mail_summary", "boxes", box, "unread"), "eq", 0), MAIL_REWARD_VISIBLE)),
            timeout=20, hold_ms=100, when=Condition(("mail_summary", "boxes", box, "pending"), "gt", 0)),
        MAIL_CONFIRM,
        Tap(90, 500, All((MAIL_PANEL, Condition(("mail_box",), "eq", index))),
            All((Condition(("mail_summary", "boxes", box, "pending"), "eq", 0),
                 Condition(("mail_summary", "boxes", box, "unread"), "eq", 0))),
            timeout=20, hold_ms=100,
            when=All((Condition(("mail_summary", "boxes", box, "pending"), "eq", 0),
                      Condition(("mail_summary", "boxes", box, "unread"), "gt", 0)))),
    ))
MAIL_REWARDS = Workflow("mail", "1.1.12.20", 960, 540, (
    QUEUE_CLOSE,
    *SELECTION_CLEAR,
    Tap(924, 505, CITY_HUD, AnyOf((Condition(("hud_menu",), "eq", True), MAIL_VISIBLE)), hold_ms=100, when=MAIL_NEEDED, settle=0.35),
    Tap(846, 505, HUD_MENU, MAIL_VISIBLE, hold_ms=100, when=MAIL_NEEDED),
    MAIL_CONFIRM,
    *MAIL_BOX_STEPS,
    Tap(925, 32, MAIL_PANEL,
        All((Condition(("mail_visible",), "eq", False), AnyOf((CITY_HUD, HUD_MENU)))), hold_ms=100),
    Tap(924, 505, HUD_MENU, CITY_HUD, hold_ms=100, when=Condition(("hud_menu",), "eq", True), settle=0.35),
), verified=True, precondition=All((
    QUEUE_KNOWN,
    Condition(("mail_summary", "ready"), "eq", True),
    Condition(("hud_visible",), "eq", True), Condition(("in_city",), "eq", True),
    Condition(("views",), "subset", CITY_VIEWS + ("AllUIMailMainPage", "VIPMainPage", "CommonBackground", "UniversalRewardsCollect", "CommonItemBagPage")),
)), when=AnyOf((MAIL_NEEDED, Condition(("hud_menu",), "eq", True))),
    wait_reason="Ожидание загруженной почты и доступного городского/почтового экрана", extra_paths=MAIL_FIELDS)


EXPEDITION_FIELDS = {
    "expedition_infos":["ScenarioData", "ScenarioInfos"],
    "expedition_state":["ScenarioData", "ScenarioState"],
    "expedition_visible":["@active_view", "ScenarioMapMainPage"],
    "campaign_visible":["@active_view", "GVGEntranceNew"],
    "expedition_reward_visible":["@active_view", "UniversalRewardsCollect"],
    "expedition_reward_click":["UIObjectManager", "UniversalRewardsCollect", "canClick"],
    "expedition_reward_recycle":["UIObjectManager", "UniversalRewardsCollect", "isRecycleMode"],
    "expedition_reward_height":["UIObjectManager", "UniversalRewardsCollect", "m_UICullHeigth"],
    "expedition_reward_width":["UIObjectManager", "UniversalRewardsCollect", "m_UICullWidth"],
    "expedition_currency":["UIObjectManager", "ScenarioMapMainPage", "curEmblemNum"],
}
EXPEDITION_VISIBLE = Condition(("expedition_visible",), "eq", True)
CAMPAIGN_VISIBLE = Condition(("campaign_visible",), "eq", True)
EXPEDITION_REWARD_VISIBLE = Condition(("expedition_reward_visible",), "eq", True)
CAMPAIGN_PANEL = All((CAMPAIGN_VISIBLE, Condition(("expedition_visible",), "eq", False),
                      Condition(("views",), "subset", CITY_VIEWS + ("GVGEntranceNew", "CommonBackground"))))
EXPEDITION_ENTRY = All((
    EXPEDITION_VISIBLE, Condition(("expedition_data_ready",), "eq", True),
    Condition(("expedition_state",), "eq", 3),
    Condition(("views",), "subset", CITY_VIEWS + ("ScenarioMapMainPage", "CommonBackground", "UniversalRewardsCollect", "CommonItemBagPage")),
))
EXPEDITION_PANEL = All((EXPEDITION_ENTRY, Condition(("expedition_reward_visible",), "eq", False),
                        Condition(("views",), "subset", CITY_VIEWS + ("ScenarioMapMainPage", "CommonBackground"))))
EXPEDITION_CONFIRM = Tap(484, 398, All((
    EXPEDITION_VISIBLE, EXPEDITION_REWARD_VISIBLE,
    Condition(("expedition_reward_click",), "eq", True), Condition(("expedition_reward_recycle",), "eq", False),
    Condition(("expedition_reward_height",), "gt", 365), Condition(("expedition_reward_height",), "lt", 368),
    Condition(("expedition_reward_width",), "gt", 585), Condition(("expedition_reward_width",), "lt", 588),
)), EXPEDITION_PANEL, hold_ms=100, when=EXPEDITION_REWARD_VISIBLE)
EXPEDITION_NEEDED = AnyOf((EXPEDITION_VISIBLE, CAMPAIGN_VISIBLE, Condition(("expedition_pending",), "gt", 0),
                           Condition(("expedition_data_ready",), "eq", False)))
EXPEDITION_REWARDS = Workflow("expedition", "1.1.12.20", 960, 540, (
    QUEUE_CLOSE,
    *SELECTION_CLEAR,
    Tap(924, 505, CITY_HUD, AnyOf((Condition(("hud_menu",), "eq", True), CAMPAIGN_VISIBLE, EXPEDITION_VISIBLE)),
        hold_ms=100, when=EXPEDITION_NEEDED, settle=0.35),
    Tap(545, 503, HUD_MENU, AnyOf((CAMPAIGN_VISIBLE, EXPEDITION_VISIBLE)),
        hold_ms=100, when=EXPEDITION_NEEDED, settle=0.25),
    Tap(141, 180, CAMPAIGN_PANEL, EXPEDITION_ENTRY, hold_ms=100, when=EXPEDITION_NEEDED, settle=0.2),
    EXPEDITION_CONFIRM,
    Tap(95, 170, EXPEDITION_PANEL,
        All((Condition(("expedition_pending",), "eq", 0), EXPEDITION_REWARD_VISIBLE)),
        timeout=15, hold_ms=100, when=Condition(("expedition_pending",), "gt", 0)),
    EXPEDITION_CONFIRM,
    Tap(31, 27, EXPEDITION_PANEL, CAMPAIGN_PANEL, hold_ms=100, when=EXPEDITION_VISIBLE, settle=0.2),
    Tap(34, 27, CAMPAIGN_PANEL, AnyOf((CITY_HUD, HUD_MENU)), hold_ms=100, when=CAMPAIGN_VISIBLE, settle=0.15),
    Tap(924, 505, HUD_MENU, CITY_HUD, hold_ms=100, when=Condition(("hud_menu",), "eq", True), settle=0.35),
), verified=True, precondition=All((
    QUEUE_KNOWN,
    Condition(("hud_visible",), "eq", True), Condition(("in_city",), "eq", True),
    Condition(("views",), "subset", CITY_VIEWS + ("GVGEntranceNew", "ScenarioMapMainPage", "VIPMainPage", "CommonBackground", "UniversalRewardsCollect", "CommonItemBagPage")),
)), when=AnyOf((EXPEDITION_NEEDED, Condition(("hud_menu",), "eq", True))),
    wait_reason="Ожидание доступной экспедиции и подтверждённых данных наград", extra_paths=EXPEDITION_FIELDS)


TRAINING_FIELDS = {
    "training_queues":["@training_queues"],
    "queue_rows":["UIObjectManager","MapHudPanel","viewDataQueueManage"],
    "queue_filters":["UIObjectManager","MapHudPanel","filterSettings"],
}
TRAINING_DATA_READY = Condition(("training_summary","ready"),"eq",True)
TRAINING_LAYOUT = Condition(("training_layout_ready",),"eq",True)


@dataclass(frozen=True)
class FocusTrainingQueue:
    subtype: int

    def __call__(self,input_device,observe,cancelled,clock,allowed):
        focus = All((TRAINING_DATA_READY,
            Condition(("training_summary","rows",str(self.subtype),"focused"),"eq",True)))
        proof = All((CITY_SCENE,QUEUE_SHOWN,TRAINING_LAYOUT,TRAINING_DATA_READY))
        # Only a non-spending focus transition can be repeated. A fresh, complete
        # queue layout and the same game identity are required before each tap.
        for attempt in range(2):
            state = observe()
            if focus.matches(state):return state
            if not proof.matches(state):raise NotReady("Обучение: не подтверждена панель очередей")
            if cancelled.is_set() or not allowed():raise Cancelled("Выбор здания отменён")
            # Row centers overlap progress controls on completed queues. The title
            # remains a focus target in both idle and completed row presentations.
            input_device.tap(110,(150,200,250,300)[self.subtype-1],hold_ms=100)
            deadline = clock()+(3 if attempt==0 else 10)
            focused_at = None
            while True:
                state = observe()
                if not proof.matches(state):raise NotReady("Обучение: панель изменилась во время выбора здания")
                if focus.matches(state):
                    if focused_at is None:focused_at=clock()
                    if clock()-focused_at>=.5:return state
                else:focused_at=None
                if clock()>=deadline:break
                if cancelled.wait(.1):raise Cancelled("Выбор здания отменён")
        raise WorkflowError("Обучение: фокус целевого здания не подтверждён после двух попыток")


TRAINING_STEPS = tuple(step for subtype,y in enumerate((164,214,264,314),1) for step in (
    Tap(24,102,CITY_HUD,QUEUE_SHOWN,hold_ms=100,settle=1.2,
        when=All((TRAINING_DATA_READY,Condition(("training_summary","rows",str(subtype),"pending"),"eq",True)))),
    Procedure(FocusTrainingQueue(subtype),
        when=All((TRAINING_DATA_READY,Condition(("training_summary","rows",str(subtype),"pending"),"eq",True)))),
    QUEUE_CLOSE,
    Tap(480,270,All((CITY_HUD,TRAINING_DATA_READY,
                    Condition(("training_summary","rows",str(subtype),"focused"),"eq",True))),
        All((TRAINING_DATA_READY,Condition(("training_summary","rows",str(subtype),"pending"),"eq",False),CITY_HUD)),
        timeout=20,hold_ms=100,
        when=All((TRAINING_DATA_READY,Condition(("training_summary","rows",str(subtype),"pending"),"eq",True))),
        increase=CountIncrease(("training_summary","troops"),
            ("training_summary","rows",str(subtype),"count"),
            key_path=("training_summary","rows",str(subtype),"unit_id"))),
))
TRAINING_COLLECT = Workflow("training_collect","1.1.12.20",960,540,(QUEUE_CLOSE,*SELECTION_CLEAR,*TRAINING_STEPS),
    verified=True,
    precondition=All((QUEUE_KNOWN,Condition(("hud_visible",),"eq",True),Condition(("hud_menu",),"eq",False),
                     Condition(("in_city",),"eq",True),
                     Condition(("views",),"subset",CITY_VIEWS+("VIPMainPage","CommonBackground","PopupMissionComplete","CourierStationNotify","CommonItemBagPage")))),
    entry_condition=TRAINING_DATA_READY,data_condition=TRAINING_DATA_READY,
    when=AnyOf((Condition(("training_summary","completed"),"gt",0),QUEUE_SHOWN)),
    wait_reason="Ожидание актуальных очередей обучения и свободного городского экрана",
    extra_paths=TRAINING_FIELDS)


def configured_training(settings: dict) -> Workflow:
    from .training import training_workflow
    return training_workflow(settings,verified=True)


def configured_tavern(settings: dict) -> Workflow:
    from .tavern import TAVERN
    return TAVERN


def configured_city_resources(settings: dict) -> Workflow:
    from .city_resources import CITY_RESOURCES
    return CITY_RESOURCES


def configured_scout_fog(settings: dict) -> Workflow:
    from .scout_fog import SCOUT_FOG
    return SCOUT_FOG


def configured_villages(settings: dict) -> Workflow:
    from .scout_places import VILLAGES
    return VILLAGES


def configured_vip_reward(settings: dict) -> Workflow:
    from .vip_daily import VIP_DAILY
    return VIP_DAILY


def configured_caves(settings: dict) -> Workflow:
    from .scout_caves import CAVES
    return CAVES


def configured_cave_rewards(settings: dict) -> Workflow:
    from .cave_rewards import cave_rewards_workflow
    return cave_rewards_workflow(settings,verified=True)


def configured_alliance_donation(settings: dict) -> Workflow:
    from .alliance_donate import donation_workflow
    return donation_workflow(settings,verified=True)


def configured_materials(settings: dict) -> Workflow:
    from .materials import materials_workflow
    return materials_workflow(settings,verified=True)


def configured_wall_repair(settings: dict) -> Workflow:
    from .wall import repair_wall_workflow
    return repair_wall_workflow(settings,verified=True)


def configured_gathering(settings: dict) -> Workflow:
    from .gather import gather_workflow
    return gather_workflow(settings,verified=True)


def configured_barbarians(settings: dict) -> Workflow:
    from .barbarians import barbarian_workflow
    return barbarian_workflow(settings,verified=True)


def configured_barbarian_chain(settings: dict) -> Workflow:
    from .barbarians import barbarian_workflow
    return barbarian_workflow(settings,verified=True,task='barbarian_chain')


def configured_building_upgrade(settings: dict) -> Workflow:
    from .building_upgrade import building_workflow
    return building_workflow(settings,verified=True)


def configured_supply_boxes(settings: dict) -> Workflow:
    from .supply_boxes import supply_box_workflow
    return supply_box_workflow(settings,verified=True)


def configured_vip_shop(settings: dict) -> Workflow:
    from .vip_shop import vip_shop_workflow
    return vip_shop_workflow(settings,verified=True)


def configured_lucerne(settings: dict) -> Workflow:
    from .lucerne import lucerne_workflow
    return lucerne_workflow(settings,verified=True)


def configured_shield(settings: dict) -> Workflow:
    from .shield import shield_workflow
    return shield_workflow(settings,verified=True)


def configured_tutorial(settings: dict) -> Workflow:
    from .tutorial import tutorial_workflow
    return tutorial_workflow(settings,verified=True)


def configured_quests(settings: dict) -> Workflow:
    from .side_quests import quest_workflow
    return quest_workflow(settings)


def configured_research(settings: dict) -> Workflow:
    from .research import research_workflow
    return research_workflow(settings,verified=True)


VERIFIED_WORKFLOWS: dict[str, Workflow | Callable[[dict], Workflow]] = {
    'research': configured_research,
    "training": configured_training,
    "tavern": configured_tavern,
    "city_resources": configured_city_resources,
    "scout_fog": configured_scout_fog,
    "villages": configured_villages,
    "caves": configured_caves,
    "cave_rewards": configured_cave_rewards,
    "alliance_donate": configured_alliance_donation,
    "materials": configured_materials,
    "repair_wall": configured_wall_repair,
    "gather_resources": configured_gathering,
    'barbarians': configured_barbarians,
    'barbarian_chain': configured_barbarian_chain,
    "buildings": configured_building_upgrade,
    "supply_boxes": configured_supply_boxes,
    "vip_shop": configured_vip_shop,
    "lucerne": configured_lucerne,
    "shield": configured_shield,
    'tutorial': configured_tutorial,
    "training_collect": TRAINING_COLLECT,
    "expedition": EXPEDITION_REWARDS,
    "mail": MAIL_REWARDS,
    "vip_reward": configured_vip_reward,
    "quests": configured_quests,
    "alliance_help": Workflow(
        "alliance_help", "1.1.12.20", 960, 540,
        (QUEUE_CLOSE, *SELECTION_CLEAR, Tap(860, 505, Condition(("alliance_help_count",), "gt", 0),
             Condition(("alliance_help_count",), "eq", 0), timeout=10),),
        verified=True, precondition=All((QUEUE_KNOWN,Condition(("hud_visible",),"eq",True),
            Condition(("hud_menu",),"eq",False),Condition(("in_city",),"eq",True),
            Condition(("player","AllianceID"),"gt",0),
            Condition(("views",),"subset",CITY_VIEWS+("VIPMainPage","CommonBackground")))),
    ),
}


def workflow_for(task_id: str, settings: dict) -> Workflow:
    candidate = VERIFIED_WORKFLOWS[task_id]
    return candidate(settings) if callable(candidate) else candidate
