"""Normal training: memory-confirmed previews and queues, with ADB-only input."""
from dataclasses import dataclass

from .model import Snapshot, TrainingOptions
from .workflows import (All, AnyOf, CITY_HUD, CITY_SCENE, CITY_VIEWS, Condition, FocusTrainingQueue, Procedure, QUEUE_CLOSE,
                        QUEUE_HIDDEN, QUEUE_KNOWN, QUEUE_SHOWN, Tap, TRAINING_DATA_READY,
                        SELECTION_CLEAR, TRAINING_FIELDS, TRAINING_LAYOUT, TRAINING_STEPS, Workflow, WorkflowError)


FIELDS = {**TRAINING_FIELDS, "training_form":["@training_form"],
          "training_keyboard":["@training_keyboard"], "training_menu":["@building_menu"]}
FORM_VISIBLE = Condition(("training_form","visible"),"eq",True)
KEYBOARD_VISIBLE = Condition(("training_keyboard","visible"),"eq",True)
KEYBOARD_HIDDEN = Condition(("training_keyboard","visible"),"eq",False)
FORM_SCREEN = All((FORM_VISIBLE, KEYBOARD_HIDDEN,
    Condition(("views",),"subset",CITY_VIEWS+("TrainTroops","CommonBackground"))))
KEYBOARD_SCREEN = All((FORM_VISIBLE, KEYBOARD_VISIBLE,
    Condition(("training_keyboard_owned",),"eq",True),
    Condition(("views",),"subset",CITY_VIEWS+("TrainTroops","CommonBackground","NumericKeyboardPanel"))))


@dataclass(frozen=True)
class FormMatches:
    subtype: int
    options: TrainingOptions
    require_count: bool = False
    require_resources: bool = False

    def matches(self, state: Snapshot) -> bool:
        values = state.values
        form = values["training_form"]
        row = values["training_summary"].get("rows",{}).get(str(self.subtype),{})
        if (not values["training_summary"].get("ready") or not form.get("ready")
                or row.get("status") != "Free" or row.get("building_id") != form.get("building_id")
                or form.get("tier") != self.options.tier
                or form.get("config",{}).get("Type") != (1,3,2,4)[self.subtype-1]
                or self.options.count > form.get("max_count",0)):
            return False
        if self.require_count and form["count"] != self.options.count:
            return False
        if self.require_resources:
            resources = values.get("resources",{})
            if type(resources.get("5")) is not int:
                return False
            for i,reserve in enumerate(self.options.reserves,1):
                amount = resources.get(str(i))
                if type(amount) is not int or amount - form["cost"][str(i)] < reserve:
                    return False
        return True


@dataclass(frozen=True)
class TierAvailable:
    subtype: int
    options: TrainingOptions

    def matches(self, state: Snapshot) -> bool:
        form = state.values["training_form"]
        row = state.values["training_summary"].get("rows",{}).get(str(self.subtype),{})
        tier = form.get("tiers",{}).get(str(self.options.tier),{})
        return (row.get("building_id") == form.get("building_id")
                and form.get("promoting") is False and form.get("running") is False and form.get("info") is False
                and tier.get("known") is True and tier.get("locked") is False
                and type(form.get("max_count")) is int and form["max_count"] >= self.options.count)


@dataclass(frozen=True)
class Started:
    subtype: int
    unit: int
    count: int
    gems: int
    reserves: tuple[int, ...]

    def matches(self, state: Snapshot) -> bool:
        summary = state.values["training_summary"]
        row = summary.get("rows",{}).get(str(self.subtype),{})
        resources = state.values.get("resources",{})
        return (summary.get("ready") is True and row.get("status") in ("InProgress","Completed")
                and row.get("unit_id") == self.unit and row.get("count") == self.count
                and row.get("from_unit_id") == 0 and resources.get("5") == self.gems
                and all(type(resources.get(str(i))) is int and resources[str(i)] >= reserve
                        for i,reserve in enumerate(self.reserves,1)))


@dataclass(frozen=True)
class StartReceipt:
    subtype: int
    options: TrainingOptions

    def capture(self, state: Snapshot) -> Started:
        if not FormMatches(self.subtype,self.options,True,True).matches(state):
            raise WorkflowError("Не подтверждены войска, количество или резерв ресурсов")
        return Started(self.subtype,state.values["training_form"]["unit_id"],self.options.count,
                       state.values["resources"]["5"],self.options.reserves)


def training_workflow(settings: dict, *, verified: bool = False) -> Workflow:
    options = TrainingOptions.from_settings(settings)
    if not options.units:
        raise ValueError("Обучение войск: выберите хотя бы один тип войск в параметрах задачи")
    # Resume from interrupted previews by closing them before rebuilding the configured form.
    steps = [
        Tap(825,247,KEYBOARD_SCREEN,KEYBOARD_HIDDEN,hold_ms=100,when=KEYBOARD_VISIBLE,settle=.2),
        Tap(823,62,FORM_SCREEN,CITY_HUD,hold_ms=100,when=FORM_VISIBLE,settle=.3),
        QUEUE_CLOSE,
        *SELECTION_CLEAR,
        *TRAINING_STEPS,
    ]
    for subtype in options.units:
        row = ("training_summary","rows",str(subtype))
        free = All((TRAINING_DATA_READY,Condition(row+("status",),"eq","Free")))
        eligible = All((free,TierAvailable(subtype,options)))
        focus = All((TRAINING_DATA_READY,Condition(row+("focused",),"eq",True)))
        menu = Condition(("training_menu_type",),"eq",subtype)
        form = FormMatches(subtype,options)
        configured = FormMatches(subtype,options,True)
        steps.extend((
            # The object becomes active before the queue's opening animation finishes.
            Tap(24,102,CITY_HUD,QUEUE_SHOWN,hold_ms=100,when=free,settle=1.2),
            Procedure(FocusTrainingQueue(subtype),when=free),
            QUEUE_CLOSE,
            Tap(480,270,All((CITY_HUD,focus,free)),menu,hold_ms=100,when=free,settle=.4),
            Tap(525,344,All((CITY_SCENE,QUEUE_HIDDEN,menu,free)),FORM_SCREEN,hold_ms=100,when=free,settle=.4),
            Tap((475,550,625,700,775)[options.tier-1],133,All((FORM_SCREEN,free,TierAvailable(subtype,options))),
                All((FORM_SCREEN,form)),hold_ms=100,when=eligible,settle=.2),
            Tap(770,317,All((FORM_SCREEN,form)),
                All((KEYBOARD_SCREEN,Condition(("training_keyboard","first"),"eq",True))),
                hold_ms=100,when=All((eligible,Condition(("training_form","count"),"ne",options.count))),settle=.15),
        ))
        prefix = ""
        for digit in str(options.count):
            previous = prefix
            prefix += digit
            number = int(digit)
            x,y = (711,247) if number == 0 else ((683,739,795)[(number-1)%3],(100,149,198)[(number-1)//3])
            expected_previous = Condition(("training_keyboard","first"),"eq",True) if not previous else All((
                Condition(("training_keyboard","first"),"eq",False),Condition(("training_keyboard","text"),"eq",previous)))
            steps.append(Tap(x,y,All((KEYBOARD_SCREEN,form,expected_previous)),All((KEYBOARD_SCREEN,
                Condition(("training_keyboard","first"),"eq",False),Condition(("training_keyboard","text"),"eq",prefix))),
                hold_ms=100,when=KEYBOARD_VISIBLE,settle=.1))
        steps.extend((
            Tap(825,247,All((KEYBOARD_SCREEN,form,Condition(("training_keyboard","text"),"eq",str(options.count)))),
                All((FORM_SCREEN,configured)),hold_ms=100,when=KEYBOARD_VISIBLE,settle=.2),
            Tap(738,443,All((FORM_SCREEN,FormMatches(subtype,options,True,True))),
                All((CITY_HUD,TRAINING_DATA_READY,Condition(row+("status",),"ne","Free"))),
                hold_ms=100,when=All((free,FormMatches(subtype,options,True,True))),
                timeout=15,increase=StartReceipt(subtype,options)),
            Tap(823,62,FORM_SCREEN,CITY_HUD,hold_ms=100,when=FORM_VISIBLE,settle=.2),
        ))
    return Workflow("training","1.1.12.20",960,540,tuple(steps),verified=verified,
        precondition=All((QUEUE_KNOWN,Condition(("hud_visible",),"eq",True),
            Condition(("hud_menu",),"eq",False),Condition(("in_city",),"eq",True),
            Condition(("views",),"subset",CITY_VIEWS+("TrainTroops","NumericKeyboardPanel","VIPMainPage","CommonBackground",
                "PopupMissionComplete","CourierStationNotify","CommonItemBagPage")))),
        entry_condition=TRAINING_DATA_READY,data_condition=TRAINING_DATA_READY,extra_paths=FIELDS,
        wait_reason="Обучение: ожидание очередей, доступного тира, ресурсов или свободного экрана")
