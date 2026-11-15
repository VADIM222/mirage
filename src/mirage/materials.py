"""Ordinary material production and collection; no merging, dismantling or acceleration."""
from dataclasses import dataclass
from collections import Counter

from .model import MATERIALS, MaterialOptions
from .navigation import navigate_city
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, NotReady, Procedure,
                        QUEUE_CLOSE, QUEUE_KNOWN, SELECTION_CLEAR, Workflow, WorkflowError)


FIELDS = {"city_camera":["@city_camera"],"building_menu":["@building_menu"],
    "material_ui":["@material_ui"],"material_orders":["EquipData","m_aMaterialOrders"],
    "material_items_known":["ItemData","MyItemListInited"],
    **{"material_item_"+str(i):["ItemData","MyItemList",i] for i in MATERIALS}}
READY = Condition(("material_state","ready"),"eq",True)
VISIBLE = Condition(("material_ui","visible"),"eq",True)
UI_READY = Condition(("material_state","ui_ready"),"eq",True)


@dataclass(frozen=True)
class Needed:
    options: MaterialOptions

    def matches(self,state):
        data = state.values["material_state"]
        return data["ready"] and (bool(data["pending"]) or data["used"]<self.options.max_orders)


def balances(state):
    resources = state.values.get("resources",{})
    if any(type(resources.get(str(i))) is not int for i in range(1,7)):
        raise NotReady("Материалы: не подтверждены ресурсные балансы")
    return {str(i):resources[str(i)] for i in range(1,7)}


def menu_matches(state,building):
    menu = state.values.get("building_menu",{})
    selected = menu.get("selected") if menu.get("known") is True else None
    return (isinstance(selected,dict) and selected.get("id")==building and selected.get("type")==31
        and set(selected.get("buttons",[]))=={"btn_CityPopUpInfo","btn_EquipMaterial","btn_BlackSmithsShop"})


@dataclass(frozen=True)
class OrderReceived:
    item: int
    previous: dict
    inventory: dict
    resources: dict

    @classmethod
    def capture(cls,state,item):
        if not UI_READY.matches(state) or not state.values["material_state"]["free"]:
            raise NotReady("Материалы: не подтверждены вкладка производства и свободная очередь")
        data = state.values["material_state"]
        return cls(item,dict(data["orders"]),dict(data["inventory"]),balances(state))

    def matches(self,state):
        if not READY.matches(state):return False
        data = state.values["material_state"]
        new = set(data["orders"])-set(self.previous)
        return (len(new)==1 and len(data["orders"])==len(self.previous)+1
            and data["orders"][next(iter(new))]["item"]==self.item
            and data["orders"][next(iter(new))]["count"]==15
            and all(key in data["orders"] and all(data["orders"][key][f]==row[f] for f in ("item","count"))
                    for key,row in self.previous.items())
            and data["inventory"]==self.inventory and balances(state)==self.resources)


@dataclass(frozen=True)
class MaterialsReceived:
    pending: dict
    inventory: dict
    totals: dict
    used: int
    resources: dict

    @staticmethod
    def order_totals(data):
        totals=Counter()
        for row in data["orders"].values():totals[str(row["item"])]+=row["count"]
        return {str(item):totals[str(item)] for item in MATERIALS}

    @classmethod
    def capture(cls,state):
        data=state.values["material_state"]
        if not READY.matches(state) or not data["pending"]:
            raise NotReady("Материалы: нет подтверждённых завершённых заказов")
        return cls(dict(data["pending"]),dict(data["inventory"]),cls.order_totals(data),data["used"],balances(state))

    def matches(self,state):
        if not READY.matches(state):return False
        data=state.values["material_state"]
        received={str(item):self.pending.get(str(item),0)-data["pending"].get(str(item),0) for item in MATERIALS}
        if any(value<0 or value%15 for value in received.values()) or sum(received.values())<=0:return False
        return (data["used"]==self.used-sum(received.values())//15
            and data["inventory"]=={key:value+received[key] for key,value in self.inventory.items()}
            and self.order_totals(data)=={key:value-received[key] for key,value in self.totals.items()}
            and balances(state)==self.resources)


@dataclass(frozen=True)
class MaterialCycle:
    options: MaterialOptions

    def __call__(self,input_device,observe,cancelled,clock,allowed):
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled("Материалы: выполнение отменено")
        def wait(predicate,message,timeout=15):
            deadline = clock()+timeout
            while True:
                state = observe()
                if predicate(state):return state
                if clock()>=deadline:raise WorkflowError(message)
                if cancelled.wait(.1):raise Cancelled("Материалы: ожидание отменено")
        def tap(x,y):
            permit()
            input_device.tap(x,y,hold_ms=100)
        def close(state):
            ui = state.values["material_ui"]
            if (ui.get("known") is not True or ui.get("back_to_forge") is not False
                    or ui.get("building_id")!=state.values["material_state"]["building_id"]):
                raise NotReady("Материалы: не подтверждён самостоятельный экран производства")
            tap(818,62)
            return wait(CITY_HUD.matches,"Материалы: возврат в город не подтверждён")
        state = observe()
        if VISIBLE.matches(state) and state.values["material_state"]["pending"]:
            state = close(state)
        if not VISIBLE.matches(state) and Needed(self.options).matches(state):
            building = state.values["material_state"]["building_id"]
            state = navigate_city(input_device,observe,cancelled,clock,31,allowed,building_id=building,select=False)
            point = state.values["city_navigation_target"]["point"]
            camera = dict(state.values["city_camera"])
            # A first tap collects completed materials instead of opening the building menu.
            pending = dict(state.values["material_state"]["pending"])
            if pending:
                receipt=MaterialsReceived.capture(state)
                tap(*point)
                state = wait(receipt.matches,"Материалы: получение готового заказа не подтверждено")
            if not Needed(self.options).matches(state):return state
            if not menu_matches(state,building):
                if (not CITY_HUD.matches(state) or any(abs(state.values["city_camera"][k]-camera[k])>.001
                                                      for k in ("x","y","distance"))):
                    raise NotReady("Материалы: камера изменилась перед выбором кузницы")
                tap(*point)
                state = wait(lambda s:menu_matches(s,building),"Материалы: выбор кузницы не подтверждён")
            tap(560,340)
            state = wait(lambda s:VISIBLE.matches(s) and s.values["material_ui"].get("known") is True,
                         "Материалы: экран производства не подтверждён")
        if VISIBLE.matches(state):
            ui = state.values["material_ui"]
            if (ui.get("known") is not True or ui.get("building_id")!=state.values["material_state"]["building_id"]
                    or ui.get("back_to_forge") is not False):raise NotReady("Материалы: неизвестное окно кузницы")
            if state.values["material_state"]["used"]<self.options.max_orders:
                if not UI_READY.matches(state):
                    if ui.get("left") not in (1,2,3):raise NotReady("Материалы: неизвестная вкладка")
                    tap(75,135)
                    state = wait(UI_READY.matches,"Материалы: вкладка производства не подтверждена")
                state = observe()
                if state.values["material_state"]["used"]<self.options.max_orders:
                    receipt = OrderReceived.capture(state,self.options.item_id)
                    x = {412:572,413:642,417:711,414:782}[self.options.item_id]
                    tap(x,175)
                    state = wait(receipt.matches,"Материалы: новый обычный заказ не подтверждён")
            return close(state)
        return state


def materials_workflow(settings: dict, *, verified: bool = False) -> Workflow:
    options = MaterialOptions.from_settings(settings)
    return Workflow("materials","1.1.12.20",960,540,(QUEUE_CLOSE,*SELECTION_CLEAR,Procedure(MaterialCycle(options)),*SELECTION_CLEAR),
        verified=verified,precondition=All((QUEUE_KNOWN,Condition(("hud_visible",),"eq",True),
            Condition(("hud_menu",),"eq",False),Condition(("in_city",),"eq",True),
            Condition(("views",),"subset",CITY_VIEWS+("VIPMainPage","CommonBackground","EquipMaterial")))),
        entry_condition=READY,data_condition=READY,when=AnyOf((Needed(options),VISIBLE)),extra_paths=FIELDS,
        wait_reason="Материалы: ожидание свободной очереди, готового заказа и подтверждённых данных")
