"""Free wall repair, only for the observed non-burning level-25 gate layout."""
from dataclasses import dataclass
import math

from .navigation import navigate_city
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, NotReady,
                        Procedure, QUEUE_CLOSE, QUEUE_KNOWN, SELECTION_CLEAR, Workflow, WorkflowError)


FIELDS = {"city_camera":["@city_camera"],"building_menu":["@building_menu"],
          "wall_ui":["@wall_ui"],"wall":["WorldMapData","MyChars","CityWallInfo"]}
READY = Condition(("wall_state","ready"),"eq",True)
VISIBLE = Condition(("wall_ui","visible"),"eq",True)
PANEL = All((VISIBLE,Condition(("wall_ui","known"),"eq",True),
             Condition(("wall_ui","editing"),"eq",False),
             Condition(("views",),"subset",CITY_VIEWS+("CityUICityWall","CommonBackground"))))


def normalize_wall(values):
    summary={"ready":False,"needed":False}
    values["wall_state"]=summary
    wall,buildings,clock=(values.get(k) for k in ("wall","buildings","server_time"))
    if (not isinstance(wall,dict) or wall.get("$truncated") or not isinstance(buildings,dict)
            or buildings.get("$truncated") or type(clock) not in (int,float) or not math.isfinite(clock)):
        return
    found=[(key,row) for key,row in buildings.items() if isinstance(row,dict) and row.get("type")==6]
    if len(found)!=1:return
    key,building=found[0]
    if (building.get("lv")!=25 or building.get("world_source")!="gate_collider"
            or any(type(building.get(k)) not in (int,float) or not math.isfinite(building[k])
                   for k in ("world_x","world_y"))):return
    if any(type(wall.get(k)) is not int for k in ("durability","durabilityMax","state","speed","repairCDEndTime")):
        return
    if (wall["durabilityMax"]!=40000 or not 0<=wall["durability"]<=wall["durabilityMax"]
            or wall["state"]!=1 or wall["speed"]!=0 or wall["repairCDEndTime"]<0):return
    resources=values.get("resources",{})
    if any(type(resources.get(str(i))) is not int or resources[str(i)]<0 for i in range(1,7)):return
    summary.update(ready=True,building_id=key,
                   needed=wall["durability"]<wall["durabilityMax"] and wall["repairCDEndTime"]<=clock)


def panel_matches(state):
    return PANEL.matches(state) and state.values["wall_ui"]["building_id"]==state.values["wall_state"]["building_id"]


@dataclass(frozen=True)
class RepairReceived:
    durability: int
    resources: dict

    @classmethod
    def capture(cls,state):
        if not READY.matches(state) or not state.values["wall_state"]["needed"] or not panel_matches(state):
            raise NotReady("Ремонт стены: бесплатный ремонт или окно не подтверждены")
        return cls(state.values["wall"]["durability"],{str(i):state.values["resources"][str(i)] for i in range(1,7)})

    def matches(self,state):
        if not READY.matches(state):return False
        wall,clock=state.values["wall"],state.values["server_time"]
        return (wall["durability"]==min(40000,self.durability+500)
                and 1785000<=wall["repairCDEndTime"]-clock<=1801000
                and all(state.values["resources"].get(k)==value for k,value in self.resources.items()))


@dataclass(frozen=True)
class RepairWall:
    def __call__(self,input_device,observe,cancelled,clock,allowed):
        def tap(x,y):
            if cancelled.is_set() or not allowed():raise Cancelled("Ремонт стены отменён")
            input_device.tap(x,y,hold_ms=100)
        def wait(predicate,message):
            deadline=clock()+15
            while True:
                state=observe()
                if predicate(state):return state
                if clock()>=deadline:raise WorkflowError(message)
                if cancelled.wait(.1):raise Cancelled("Ожидание ремонта стены отменено")
        state=observe()
        if not VISIBLE.matches(state):
            if not state.values["wall_state"]["needed"]:return state
            building=state.values["wall_state"]["building_id"]
            state=navigate_city(input_device,observe,cancelled,clock,6,allowed,building_id=building)
            menu=state.values["building_menu"]
            selected=menu.get("selected") if menu.get("known") is True else None
            if (not isinstance(selected,dict) or selected.get("id")!=building or selected.get("type")!=6
                    or set(selected.get("buttons",[]))!={"btn_CityPopUpInfo","btn_FunctionCityWall"}):
                raise NotReady("Ремонт стены: не подтверждено меню ворот")
            tap(520,300)
            state=wait(panel_matches,"Ремонт стены: окно стены не подтверждено")
        if not panel_matches(state):raise NotReady("Ремонт стены: неизвестное окно или режим редактирования")
        if state.values["wall_state"]["needed"]:
            receipt=RepairReceived.capture(state)
            tap(627,425)
            state=wait(lambda s:panel_matches(s) and receipt.matches(s),"Бесплатный ремонт стены не подтверждён")
        if not panel_matches(state):raise NotReady("Ремонт стены: окно изменилось перед закрытием")
        tap(818,62)
        return wait(CITY_HUD.matches,"Ремонт стены: возврат в город не подтверждён")


def repair_wall_workflow(settings: dict, *, verified: bool=False):
    return Workflow("repair_wall","1.1.12.20",960,540,
        (QUEUE_CLOSE,*SELECTION_CLEAR,Procedure(RepairWall()),*SELECTION_CLEAR),verified=verified,
        precondition=All((QUEUE_KNOWN,Condition(("hud_visible",),"eq",True),
            Condition(("hud_menu",),"eq",False),Condition(("in_city",),"eq",True),
            Condition(("views",),"subset",CITY_VIEWS+("VIPMainPage","CommonBackground","CityUICityWall")))),
        entry_condition=READY,data_condition=READY,
        when=AnyOf((Condition(("wall_state","needed"),"eq",True),VISIBLE)),extra_paths=FIELDS,
        wait_reason="Ремонт стены: ожидание проверенного состояния стены и таймера")
