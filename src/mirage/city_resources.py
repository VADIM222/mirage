"""Collect single or grouped city production from exact observed resets and receipts."""
import math
from dataclasses import dataclass
from .navigation import navigate_city
from .supply_boxes import balances, inventory, table
from .workflows import (All, CITY_HUD, CITY_VIEWS, Cancelled, Condition, NotReady, Procedure,
                        QUEUE_CLOSE, QUEUE_KNOWN, SELECTION_CLEAR, Workflow, WorkflowError)


FIELDS = {"city_camera":["@city_camera"],"building_menu":["@building_menu"],
          "city_resources":["@city_resources"],"harvest_receipts":["CityBuildData","UserRssAniData"],
          "supply_inventory":["@item_counts"]}
READY = Condition(("city_resource_state","ready"),"eq",True)


def completed_receipt(state,kind):
    records=state.values.get("harvest_receipts")
    row=records.get(str(kind)) if isinstance(records,dict) and not records.get("$truncated") else None
    if (not isinstance(row,dict) or row.get("$truncated") or type(row.get("type")) is not int
            or row["type"]!=kind or type(row.get("value")) is not int or row["value"]<0
            or type(row.get("incrValue")) is not int or row["incrValue"]!=0
            or type(row.get("leftTime")) not in (int,float) or not math.isfinite(row["leftTime"])
            or row["leftTime"]!=0):return None
    return row["value"]


@dataclass(frozen=True)
class HarvestReceipt:
    kind: int
    target: str
    stocks: dict
    rates: dict
    money: dict
    items: dict

    @classmethod
    def capture(cls,state,kind,target):
        group=state.values.get('city_resource_state',{}).get('groups',{}).get(str(kind),{})
        records=state.values.get('city_resources',{})
        if not READY.matches(state) or target not in group.get('pending',[]):
            raise NotReady('Сбор ресурсов: готовое производство выбранного здания не подтверждено')
        money=balances(state)
        if completed_receipt(state,kind)!=money[str(kind)]:
            raise NotReady('Ожидание завершения предыдущего изменения городского баланса')
        stocks={};rates={}
        for key in group['pending']:
            row=records[key];rate=row.get('speedSec',0)
            if type(rate) not in (int,float) or not math.isfinite(rate) or rate<0:
                raise NotReady('Сбор ресурсов: скорость производства не прочитана')
            stocks[key]=math.floor(row['rssValue']);rates[key]=rate
        return cls(kind,target,stocks,rates,money,inventory(state))

    def collected(self,state,input_seconds):
        if not READY.matches(state) or not CITY_HUD.matches(state):return ()
        records=state.values.get('city_resources',{})
        ids=tuple(key for key in self.stocks if key in records
            and records[key]['rssValue']<records[key]['gatherMin'])
        if self.target not in ids:return ()
        money=balances(state)
        if (any(money[key]!=value for key,value in self.money.items() if key!=str(self.kind))
                or inventory(state)!=self.items or completed_receipt(state,self.kind)!=money[str(self.kind)]):return ()
        expected=sum(self.stocks[key] for key in ids)
        # Account for integer interpolation and only the production accrued while
        # the ordinary input was in flight, not arbitrary unrelated credits.
        tolerance=len(ids)+math.ceil(sum(self.rates[key] for key in ids)*input_seconds)
        amount=money[str(self.kind)]-self.money[str(self.kind)]
        return ids if max(1,expected-len(ids))<=amount<=expected+tolerance else ()


def harvest_city(input_device,observe,cancelled,clock,allowed):
    state = observe()
    if not READY.matches(state):raise NotReady('Ожидание актуального производства городских ресурсов')
    pending={kind:set(state.values['city_resource_state']['groups'].get(str(kind),{}).get('pending',[])) for kind in range(1,5)}
    for kind in range(1,5):
        for _ in range(16):
            state=observe()
            if not READY.matches(state):raise NotReady('Ожидание актуального производства городских ресурсов')
            pending[kind].intersection_update(state.values['city_resource_state']['groups'].get(str(kind),{}).get('pending',[]))
            if not pending[kind]:break
            target=max(pending[kind],key=lambda key:state.values['city_resources'][key]['rssValue'])
            approached=navigate_city(input_device,observe,cancelled,clock,kind+1,allowed,building_id=target,select=False)
            proof=approached.values['city_navigation_target'];state=observe()
            if not CITY_HUD.matches(state) or not READY.matches(state):raise NotReady('Сбор ресурсов: ожидание свободного города')
            camera=state.values['city_camera']
            if (abs(camera['x']-proof['camera']['x'])>.005 or abs(camera['y']-proof['camera']['y'])>.005
                    or abs(camera['distance']-proof['camera']['distance'])>.1 or camera['moving'] is not False):
                raise NotReady('Камера сместилась перед сбором ресурсов')
            if target not in state.values['city_resource_state']['groups'].get(str(kind),{}).get('pending',[]):
                pending[kind].discard(target);continue
            receipt=HarvestReceipt.capture(state,kind,target)
            x,y=proof['point'][0],proof['point'][1]-35
            if not 440<=x<=520 or not 190<=y<=280:raise NotReady('Ресурсный значок находится вне подтверждённой области')
            if cancelled.is_set() or not allowed():raise Cancelled('Сбор ресурсов отменён перед вводом')
            sent=clock();input_device.tap(x,y,hold_ms=100);input_seconds=max(0,clock()-sent)
            deadline=clock()+20
            while True:
                if cancelled.is_set() or not allowed():raise Cancelled('Сбор ресурсов отменён')
                state=observe();collected=receipt.collected(state,input_seconds)
                if collected:
                    pending[kind].difference_update(collected);break
                if clock()>=deadline:
                    raise WorkflowError(f'Полное получение городских ресурсов не подтверждено: тип {kind}, здание {target}; повтор запрещён')
                if cancelled.wait(.1):raise Cancelled('Сбор ресурсов отменён')
    return state


CITY_RESOURCES = Workflow("city_resources","1.1.12.20",960,540,
    (QUEUE_CLOSE,*SELECTION_CLEAR,Procedure(harvest_city)),
    verified=True,
    precondition=All((QUEUE_KNOWN,Condition(("hud_visible",),"eq",True),Condition(("hud_menu",),"eq",False),
        Condition(("in_city",),"eq",True),
        Condition(("views",),"subset",CITY_VIEWS+("VIPMainPage","CommonBackground","PopupMissionComplete",
                                                  "CourierStationNotify","CommonItemBagPage")))),
    entry_condition=READY,when=Condition(("city_resource_state","pending"),"gt",0),extra_paths=FIELDS,
    wait_reason="Ожидание готового городского производства и доступного игрового экрана")
