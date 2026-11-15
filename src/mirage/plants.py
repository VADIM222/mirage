"""Store one ordinary plant; keep its object identity and all other city assets."""
from copy import deepcopy
from dataclasses import dataclass

from .supply_boxes import balances, inventory, table
from .workflows import NotReady


PLANT_TYPES=tuple(range(51,61))


@dataclass(frozen=True)
class PlantRecycleReceipt:
    building: str
    previous: dict
    money: dict
    items: dict

    @staticmethod
    def rows(state):
        buildings=state.values.get('buildings')
        if not table(buildings) or any(not table(row) for row in buildings.values()):
            raise NotReady('Уборка: город не прочитан')
        return {key:{k:deepcopy(row.get(k)) for k in ('id','type','lv','state','endTime','totalTime',
            'position','logicPosition','width','length')} for key,row in buildings.items()}

    @classmethod
    def capture_selected(cls,state,building):
        selected=state.values.get('building_menu',{}).get('selected')
        row=state.values.get('buildings',{}).get(building)
        if (not table(row) or row.get('id')!=building or row.get('type') not in PLANT_TYPES or row.get('lv')!=1 or row.get('state')!=1
                or row.get('width')!=3 or row.get('length')!=3
                or row.get('logicPosition')=={'x':-99,'y':-99}
                or not table(selected) or selected.get('id')!=building or selected.get('type')!=row['type']
                or set(selected.get('buttons',[]))!={'btn_CityPopUpInfo','btn_CityPopUpRecycle'}):
            raise NotReady('Уборка: меню обычного растения не подтверждено')
        return cls(building,cls.rows(state),balances(state),inventory(state))

    @classmethod
    def capture(cls,state):
        from .tutorial import data, recycle_point
        recycle_point(state);d=data(state)
        if d['step']!=3:raise NotReady('Уборка: подтверждение доступно только в меню растения')
        return cls.capture_selected(state,d['plant']['id'])

    def matches(self,state):
        if balances(state)!=self.money or inventory(state)!=self.items:return False
        expected=deepcopy(self.previous);row=expected[self.building]
        row['logicPosition']={'x':-99,'y':-99}
        row['position']={'x':(-99+(row['width']-1)/2)*.1,'y':(-99+(row['length']-1)/2)*.1}
        return self.rows(state)==expected
