"""Bounded dismissal of a specifically verified non-spending screen."""
from dataclasses import dataclass

from .workflows import (All, CITY_HUD, CITY_VIEWS, Cancelled, Condition, NotReady,
                        Procedure, Workflow, WorkflowError)


FIELDS={"battle_pass_visible":["@active_view","BattlePassMain"]}
VISIBLE=Condition(("battle_pass_visible",),"eq",True)
PANEL=All((VISIBLE,Condition(("hud_visible",),"eq",True),Condition(("hud_menu",),"eq",False),
           Condition(("in_city",),"eq",True),
           Condition(("views",),"subset",CITY_VIEWS+("BattlePassMain","CommonBackground"))))


@dataclass(frozen=True)
class DismissBattlePass:
    def __call__(self,input_device,observe,cancelled,clock,allowed):
        state=observe()
        if not PANEL.matches(state):raise NotReady("Закрытие свитков: окно не подтверждено")
        resources=state.values.get("resources",{})
        if any(type(resources.get(str(i))) is not int for i in range(1,7)):
            raise NotReady("Закрытие свитков: не подтверждены валюты")
        before={str(i):resources[str(i)] for i in range(1,7)}
        if cancelled.is_set() or not allowed():raise Cancelled("Закрытие свитков отменено")
        input_device.back()
        deadline=clock()+15
        while True:
            state=observe()
            if CITY_HUD.matches(state) and not VISIBLE.matches(state):
                if any(state.values.get("resources",{}).get(k)!=v for k,v in before.items()):
                    raise WorkflowError("Валюты изменились при закрытии окна свитков")
                return state
            if clock()>=deadline:raise WorkflowError("Возврат из окна свитков в город не подтверждён")
            if cancelled.wait(.1):raise Cancelled("Закрытие свитков отменено")


DISMISS_BATTLE_PASS=Workflow("dismiss_battle_pass","1.1.12.20",960,540,
    (Procedure(DismissBattlePass()),),verified=True,when=VISIBLE,extra_paths=FIELDS,requires_city=False)
