"""Resource-only alliance donations toward the game's observed daily contribution goal."""
from dataclasses import dataclass

from .model import DonationOptions
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Condition, HUD_MENU, QUEUE_CLOSE,
                        Cancelled, NotReady, Procedure, QUEUE_KNOWN, SELECTION_CLEAR, Tap, Workflow, WorkflowError)


FIELDS = {"donation":["@alliance_donation"]}
READY = Condition(("donation","ready"),"eq",True)
ALLIANCE_VISIBLE = Condition(("donation","alliance_visible"),"eq",True)
RESEARCH_VISIBLE = Condition(("donation","research_visible"),"eq",True)
DETAIL_VISIBLE = Condition(("donation","detail_visible"),"eq",True)
ALLIANCE_PANEL = All((ALLIANCE_VISIBLE,
    Condition(("views",),"subset",CITY_VIEWS+("AllianceMainPage","CommonBackground"))))
RESEARCH_PANEL = All((RESEARCH_VISIBLE,
    Condition(("views",),"subset",CITY_VIEWS+("AllianceResearchPage","CommonBackground"))))
DETAIL_PANEL = All((DETAIL_VISIBLE,RESEARCH_VISIBLE,
    Condition(("views",),"subset",CITY_VIEWS+("AllianceResearchPage","AllianceResearchRequestPage","CommonBackground"))))


@dataclass(frozen=True)
class Needed:
    options: DonationOptions

    def matches(self,state):
        data = state.values["donation"]
        if not data["ready"] or not data["available"] or data["today"] >= self.options.daily_goal:
            return False
        resources = state.values.get("resources",{})
        if type(resources.get("5")) is not int or type(resources.get("6")) is not int:
            return False
        config = data["config"]
        return all(type(resources.get(str(i))) is int and resources[str(i)]-
                   (config["DonateValue"] if config["DonateType"] == i else 0) >= reserve
                   for i,reserve in enumerate(self.options.reserves,1))


@dataclass(frozen=True)
class SelectedTarget:
    def matches(self,state):
        if not READY.matches(state) or not DETAIL_PANEL.matches(state):
            return False
        data = state.values["donation"]
        detail,target = data.get("detail"),data["target"]
        return (isinstance(detail,dict) and detail.get("is_alliance") is True
                and type(data.get("detail_id")) is int and data["detail_id"] == target["type"]*100+target["level"]
                and all(type(detail.get(key)) is int and detail[key] == target[key]
                        for key in ("type","level","max_level","science_point","end_time")))


SELECTED = SelectedTarget()


@dataclass(frozen=True)
class Receipt:
    options: DonationOptions

    def capture(self,state):
        if not Needed(self.options).matches(state) or not SELECTED.matches(state):
            raise WorkflowError("Не подтверждены технология, ресурсная стоимость или резерв пожертвования")
        data = state.values["donation"]
        return Received(data["today"],data["chances"],data["target"]["type"],data["target"]["level"],
            data["target"]["science_point"],data["config"]["DonateType"],data["config"]["DonateValue"],
            {str(i):state.values["resources"][str(i)] for i in range(1,7)})


@dataclass(frozen=True)
class Received:
    today: int
    chances: int
    kind: int
    level: int
    science: int
    resource: int
    cost: int
    resources: dict

    def matches(self,state):
        if not READY.matches(state):
            return False
        data,resources = state.values["donation"],state.values.get("resources",{})
        target = data["target"]
        return (data["today"] > self.today and data["chances"] == self.chances-1
                and target["type"] == self.kind and target["level"] == self.level
                and target["science_point"] > self.science
                and all(resources.get(str(i)) == self.resources[str(i)]-(self.cost if i == self.resource else 0)
                        for i in range(1,5))
                and resources.get("5") == self.resources["5"]
                and type(resources.get("6")) is int and resources["6"] > self.resources["6"])


@dataclass(frozen=True)
class DonateOnce:
    options: DonationOptions

    def __call__(self,input_device,observe,cancelled,clock,allowed):
        state = observe()
        if not SELECTED.matches(state) or not Needed(self.options).matches(state):
            raise NotReady("Пожертвование: стоимость, цель или резерв изменились")
        receipt = Receipt(self.options).capture(state)
        if cancelled.is_set() or not allowed():
            raise Cancelled("Пожертвование отменено перед вводом")
        input_device.tap(734,430,hold_ms=100)
        deadline = clock()+15
        while True:
            state = observe()
            if SELECTED.matches(state) and receipt.matches(state):
                return state
            if clock() >= deadline:
                raise WorkflowError("Ресурсное пожертвование не подтверждено")
            if cancelled.wait(.1):
                raise Cancelled("Пожертвование отменено")


CLOSE_PAGES = (
    Tap(818,62,DETAIL_PANEL,RESEARCH_PANEL,hold_ms=100,when=DETAIL_VISIBLE,settle=.2),
    Tap(835,53,RESEARCH_PANEL,AnyOf((ALLIANCE_PANEL,HUD_MENU,CITY_HUD)),hold_ms=100,when=RESEARCH_VISIBLE,settle=.2),
    Tap(837,32,ALLIANCE_PANEL,AnyOf((HUD_MENU,CITY_HUD)),hold_ms=100,when=ALLIANCE_VISIBLE,settle=.2),
)
CLOSE_MENU = Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,
                 when=Condition(("hud_menu",),"eq",True),settle=.3)


def donation_workflow(settings: dict, *, verified: bool = False) -> Workflow:
    options = DonationOptions.from_settings(settings)
    needed = Needed(options)
    return Workflow("alliance_donate","1.1.12.20",960,540,(
        *CLOSE_PAGES,QUEUE_CLOSE,CLOSE_MENU,*SELECTION_CLEAR,
        Tap(924,505,CITY_HUD,HUD_MENU,hold_ms=100,when=needed,settle=.3),
        Tap(695,505,HUD_MENU,ALLIANCE_PANEL,hold_ms=100,when=needed,settle=.3),
        Tap(528,420,ALLIANCE_PANEL,RESEARCH_PANEL,hold_ms=100,when=needed,settle=.4),
        Tap(430,445,All((RESEARCH_PANEL,Condition(("donation","page_type"),"eq",2))),
            SELECTED,hold_ms=100,when=needed,settle=.3),
        Procedure(DonateOnce(options),when=needed),
        *CLOSE_PAGES,CLOSE_MENU,
    ),verified=verified,precondition=All((QUEUE_KNOWN,Condition(("hud_visible",),"eq",True),
        Condition(("in_city",),"eq",True),Condition(("player","AllianceID"),"gt",0),
        Condition(("views",),"subset",CITY_VIEWS+("VIPMainPage","CommonBackground","AllianceMainPage",
                                                 "AllianceResearchPage","AllianceResearchRequestPage")))),
        entry_condition=All((READY,Condition(("donation","recommend"),"eq",306))),
        when=AnyOf((needed,ALLIANCE_VISIBLE,RESEARCH_VISIBLE,DETAIL_VISIBLE)),extra_paths=FIELDS,
        wait_reason="Пожертвования: ожидание данных и проверенной рекомендации Building Durability I (306)")
