"""Resolve ordinary building prerequisites from the current game's next-level rows."""
from dataclasses import dataclass

from .supply_boxes import integer, table
from .workflows import NotReady


@dataclass(frozen=True)
class BuildingTarget:
    kind: int
    level: int
    building: str | None
    root: int


def next_building_target(state,types,max_level):
    buildings=state.values.get('buildings');plan=state.values.get('building_plan')
    if (not table(buildings) or not table(plan) or plan.get('ready') is not True
            or not table(plan.get('rows'))):raise NotReady('Развитие: конфигурации зданий не прочитаны')
    grouped={}
    for key,row in buildings.items():
        if (table(row) and integer(row.get('type'),1) and integer(row.get('lv'))
                and key!='localNewBuilding'):
            grouped.setdefault(row['type'],[]).append((key,row))
    def visit(kind,required,root,stack,building_id=None):
        if kind in stack:raise NotReady('Развитие: цикл предпосылок в конфигурации зданий')
        rows=[(key,row) for key,row in grouped.get(kind,[]) if building_id is None or key==building_id]
        if any(r.get('state')==1 and r['lv']>=required for _,r in rows):return None
        # An already accepted upgrade must finish naturally, even with a second builder.
        if any(r.get('state')==2 and r['lv']<required for _,r in rows):return None
        ready=[(key,r) for key,r in rows if r.get('state')==1 and r.get('endTime')==0]
        if not ready:
            if rows:return None
            cfg=state.values.get('construction_plan',{}).get('first',{}).get(str(kind))
            if table(cfg):
                if cfg.get('Type')!=kind or cfg.get('Level')!=1 or cfg.get('Enable')!=1:return None
                for n in (1,2,3):
                    pre,level=cfg.get('PreType'+str(n)),cfg.get('PreLevel'+str(n))
                    if not integer(pre) or not integer(level):raise NotReady('Развитие: неполные условия новой постройки')
                    if pre and not any(r.get('state')==1 and r['lv']>=level for _,r in grouped.get(pre,[])):
                        return visit(pre,level,root,stack+(kind,))
            return BuildingTarget(kind,1,None,root)
        key,row=max(ready,key=lambda item:(item[1]['lv'],item[0]))
        cfg=plan['rows'].get(key)
        if (not table(cfg) or cfg.get('Type')!=kind or cfg.get('Level')!=row['lv']+1
                or cfg.get('Enable')!=1):return None
        for n in (1,2,3):
            pre,level=cfg.get('PreType'+str(n)),cfg.get('PreLevel'+str(n))
            if not integer(pre) or not integer(level):raise NotReady('Развитие: неполная цепочка предпосылок')
            if pre and not any(r.get('state')==1 and r['lv']>=level for _,r in grouped.get(pre,[])):
                return visit(pre,level,root,stack+(kind,))
        return BuildingTarget(kind,row['lv']+1,key,root)
    for kind in types:
        owned=grouped.get(kind,[])
        if not owned:
            target=visit(kind,max_level,kind,())
            if target is not None:return target
        for key,row in sorted(owned,key=lambda item:(item[1]['lv'],item[0])):
            target=visit(kind,max_level,kind,(),key)
            if target is not None:return target
    return None
