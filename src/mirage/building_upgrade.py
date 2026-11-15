"""One selected ordinary building upgrade, permanent builder and exact server receipt."""
from dataclasses import dataclass, replace
from copy import deepcopy
import math

from .model import BuildingOptions
from .development import next_building_target
from .navigation import navigate_city
from .resource_packs import FIELDS as PACK_FIELDS, bag as pack_bag, replenish
from .workflows import (CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine,
    HUD_MENU, NotReady, Procedure, SELECTION_CLEAR, Tap, Workflow, WorkflowError)


FIELDS={**PACK_FIELDS,'city_camera':['@city_camera'],'building_menu':['@building_menu'],
    'building_plan':['@building_plan'],
    'upgrade_guide_position':['UIObjectManager','QuestGuide','m_worldPos'],
    'upgrade_guide_force':['UIObjectManager','QuestGuide','forceClick'],
    'upgrade_guide_callback':['UIObjectManager','QuestGuide','needClickCb'],
    'upgrade_guide_3d':['UIObjectManager','QuestGuide','is3D'],
    'city_resources':['@city_resources'],'harvest_receipts':['CityBuildData','UserRssAniData'],
    'upgrade_visible':['@active_view','UpgradeBuilding'],'builder_queues':['CityBuildData','BuildQueue'],
    **{'upgrade_'+key:['UIObjectManager','UpgradeBuilding',field] for key,field in
       (('id','buildingId'),('type','btype'),('level','curLv'),('cost','requireRss'),
        ('can','canUpgrade'),('item','itemType'),('items','itemNum'))}}
VISIBLE=Condition(('upgrade_visible',),'eq',True)
class UpgradeGuide:
    def matches(self,state):
        v=state.values;p=v.get('upgrade_guide_position')
        return (v.get('upgrade_visible') is True and v.get('upgrade_type')==1 and v.get('upgrade_level')==3
            and v.get('upgrade_can') is True and v.get('upgrade_guide_force') is False
            and v.get('upgrade_guide_callback') is False and v.get('upgrade_guide_3d') is False
            and isinstance(p,dict) and all(type(p.get(k)) in (int,float) and math.isfinite(p[k]) for k in ('1','2','3'))
            and abs(480+54*p['1']-741)<4 and abs(270-54*p['2']-415)<4 and abs(p['3'])<.01
            and set(v.get('views',{}))<=set(CITY_VIEWS+('UpgradeBuilding','CommonBackground','QuestGuide')))


class UpgradePanel:
    def matches(self,state):
        return (VISIBLE.matches(state) and (set(state.values.get('views',{}))<=set(CITY_VIEWS+('UpgradeBuilding','CommonBackground'))
            or UpgradeGuide().matches(state)))


PANEL=UpgradePanel()


def integer(value,minimum=0):return type(value) is int and value>=minimum


def table(value):return isinstance(value,dict) and not any(k.startswith('$') for k in value)


def permanent_builder(state):
    rows=state.values.get('builder_queues')
    if not table(rows) or not rows:raise NotReady('Строительство: очереди не подтверждены')
    free=[]
    for row in rows.values():
        if (not table(row) or not integer(row.get('id'),1) or type(row.get('buildingId')) is not str
                or type(row.get('endTime')) is not int):raise NotReady('Строительство: очередь неполна')
        if row.get('from')=='born' and row['buildingId']=='' and row['endTime']==-1:free.append(row['id'])
    return min(free) if free else None


def candidate(state,options,*,include_shortfall=False):
    rows=state.values.get('buildings')
    if not table(rows):raise NotReady('Строительство: список зданий неполон')
    items=[(key,row) for key,row in rows.items() if table(row) and row.get('type') in options.types
        and row.get('state')==1 and row.get('endTime')==0 and integer(row.get('lv'),1)
        and row['lv']<options.max_level and str(row.get('id'))==key]
    if 'building_plan' in state.values:
        plan=state.values['building_plan']
        if not table(plan) or plan.get('ready') is not True or not table(plan.get('rows')):
            raise NotReady('Строительство: конфигурации следующих уровней не прочитаны')
        levels={}
        for row in rows.values():
            if table(row) and integer(row.get('type'),1) and integer(row.get('lv'),1):
                levels[row['type']]=max(levels.get(row['type'],0),row['lv'])
        def eligible(item):
            key,row=item;cfg=plan['rows'].get(key);resources=state.values.get('resources',{})
            if (not table(cfg) or cfg.get('Type')!=row['type'] or cfg.get('Level')!=row['lv']+1
                    or cfg.get('Enable')!=1 or any(cfg.get(k)!=0 for k in ('Gem','Amber','Crystal','NeedBagItem','ItemCnt1'))):return False
            for kind,cost,reserve in zip(range(1,5),('Food','Wood','Stone','Coin'),options.reserves):
                if not integer(cfg.get(cost)) or not integer(resources.get(str(kind))):return False
                if resources[str(kind)]-cfg[cost]<reserve and not (include_shortfall and kind in (1,2)):return False
            for n in (1,2,3):
                kind,level=cfg.get('PreType'+str(n)),cfg.get('PreLevel'+str(n))
                if not integer(kind) or not integer(level) or kind and levels.get(kind,0)<level:return False
            return True
        items=[item for item in items if eligible(item)]
    return min(items,key=lambda item:(options.types.index(item[1]['type']),item[1]['lv'],item[0])) if items else None


def selected(state,building,kind=4):
    menu=state.values.get('building_menu')
    row=menu.get('selected') if table(menu) else None
    buttons=row.get('buttons') if table(row) else None
    return (table(row) and row.get('id')==building and row.get('type')==kind
        and isinstance(buttons,list) and len(buttons) in (2,3,4)
        and {'btn_CityPopUpUpgrade','btn_CityPopUpInfo'}<=set(buttons)
        and all(button in ('btn_CityPopUpUpgrade','btn_CityPopUpInfo') or button.startswith('btn_Function')
            or kind==1 and button=='btn_CityPopUpVIPSkin' for button in buttons)
        and (len(buttons)<4 or kind==1 and set(buttons)=={'btn_CityPopUpUpgrade','btn_CityPopUpInfo','btn_FunctionTownCenter','btn_CityPopUpVIPSkin'})
        and set(state.values.get('views',{}))<=set(CITY_VIEWS))


@dataclass(frozen=True)
class UpgradeReceipt:
    building: str
    level: int
    builder: int
    cost: dict
    resources: dict
    kind: int = 4

    @classmethod
    def capture(cls,state,options,building):
        v=state.values;row=v.get('buildings',{}).get(building);builder=permanent_builder(state)
        if (not PANEL.matches(state) or v.get('upgrade_id')!=building or not table(row)
                or row.get('type') not in options.types or v.get('upgrade_type')!=row.get('type')
                or row.get('state')!=1 or row.get('endTime')!=0
                or not integer(row.get('lv'),1) or not row['lv']<options.max_level
                or v.get('upgrade_level')!=row['lv'] or v.get('upgrade_can') is not True
                or v.get('upgrade_item')!=0 or v.get('upgrade_items')!=0 or builder is None):
            raise NotReady('Строительство: цель, условия или постоянный строитель не подтверждены')
        resources=v.get('resources')
        if not table(resources) or any(not integer(resources.get(str(i))) for i in range(1,7)):
            raise NotReady('Строительство: баланс не подтверждён')
        costs=v.get('upgrade_cost');cost={}
        if not table(costs) or not costs:raise NotReady('Строительство: стоимость не подтверждена')
        for item in costs.values():
            if (not table(item) or type(item.get('type')) is not int or item['type'] not in (1,2,3,4)
                    or not integer(item.get('num'),1) or not integer(item.get('finalNum'),1)
                    or item['finalNum']>item['num'] or str(item['type']) in cost):
                raise NotReady('Строительство: неизвестная стоимость или предметы')
            cost[str(item['type'])]=item['finalNum']
        if any(resources[str(i)]-cost.get(str(i),0)<reserve for i,reserve in enumerate(options.reserves,1)):
            raise NotReady('Строительство: недостаточно ресурсов с учётом резерва')
        return cls(building,row['lv'],builder,cost,{str(i):resources[str(i)] for i in range(1,7)},row['type'])

    def matches(self,state):
        v=state.values;row=v.get('buildings',{}).get(self.building);queues=v.get('builder_queues')
        if not table(row) or row.get('type')!=self.kind or not table(queues):return False
        finished=row.get('lv')==self.level+1 and row.get('state')==1 and row.get('endTime')==0
        running=(row.get('lv')==self.level and row.get('state')==2 and integer(row.get('endTime'),1)
            and row['endTime']>v.get('server_time',float('inf')))
        if not finished and not running:return False
        assigned=[q for q in queues.values() if table(q) and q.get('id')==self.builder
            and q.get('from')=='born' and q.get('buildingId')==('' if finished else self.building) and q.get('endTime')==-1]
        return len(assigned)==1 and all(v.get('resources',{}).get(str(i))==self.resources[str(i)]-self.cost.get(str(i),0)
                                      for i in range(1,7))


@dataclass(frozen=True)
class UpgradeCycle:
    options: BuildingOptions

    def __call__(self,device,observe,cancelled,clock,allowed):
        if self.options.create_missing:
            from .construction import build_missing
            created=build_missing(self.options,device,observe,cancelled,clock,allowed)
            if created is not None:return created
        initial=observe()
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Строительство отменено')
        def execute(steps):
            return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
                Workflow('building_upgrade_transition','1.1.12.20',960,540,steps,verified=True,guide_condition=UpgradeGuide()),cancelled,
                instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        def clean():
            if pack_bag(observe()):
                replenish(device,observe,cancelled,clock,allowed,{})
            deadline=clock()+10;stable=clock()
            while True:
                permit()
                if 'TroopPowerUpHUD' in observe().values.get('views',{}):stable=clock()
                elif clock()-stable>=.8:break
                if clock()>=deadline:raise NotReady('Строительство: ожидание завершения анимации силы')
                if cancelled.wait(.1):raise Cancelled('Строительство отменено')
            return execute((Tap(818,62,PANEL,Condition(('upgrade_visible',),'eq',False),hold_ms=100,
                when=VISIBLE,settle=.3),*SELECTION_CLEAR,
                Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,when=Condition(('hud_menu',),'eq',True),settle=.3)))
        state=clean()
        if not CITY_HUD.matches(state):raise NotReady('Строительство: нужен свободный город')
        options=self.options
        if options.auto_prerequisites:
            goal=next_building_target(state,options.types,options.max_level)
            if goal is None:return state
            if goal.building is None:
                raise NotReady('Строительство: требуется размещение отсутствующего здания типа '+str(goal.kind))
            options=replace(options,types=(goal.kind,),max_level=goal.level)
        target=candidate(state,options)
        if target is None and options.use_resource_packs and permanent_builder(state) is not None:
            pending=candidate(state,options,include_shortfall=True)
            if pending is not None:
                config=state.values['building_plan']['rows'][pending[0]]
                minimum={str(i):config[name]+options.reserves[i-1] for i,name in ((1,'Food'),(2,'Wood'))}
                state=replenish(device,observe,cancelled,clock,allowed,minimum)
                target=candidate(state,options)
        if target is None or permanent_builder(state) is None:return state
        building,row=target;kind=row['type'];resource=kind-1 if kind in (2,3,4,5) else None
        approached=navigate_city(device,observe,cancelled,clock,kind,allowed,building_id=building,select=False)
        proof=deepcopy(approached.values['city_navigation_target'])
        state=observe()
        # A resource-building tap can harvest first. Permit a second selection
        # only after the observed city's harvest reset and exact credit settle.
        from .city_resources import completed_receipt
        group=state.values.get('city_resource_state',{}).get('groups',{}).get(str(resource),{})
        pending=tuple(group.get('pending',()))
        before=state.values['resources'].get(str(resource));gems=state.values['resources']['5']
        for attempt in range(2):
            state=observe();camera=state.values.get('city_camera',{})
            if (not CITY_HUD.matches(state) or any(abs(camera.get(key,float('inf'))-proof['camera'][key])>.005
                    for key in ('x','y','distance'))):raise NotReady('Строительство: камера или экран изменились')
            permit();device.tap(*proof['point'],hold_ms=100)
            deadline=clock()+15
            while True:
                state=observe()
                if selected(state,building,kind):break
                menu=state.values.get('building_menu',{})
                if menu.get('selected') is not None:raise NotReady('Строительство: выбрано другое здание')
                harvested=(attempt==0 and pending and CITY_HUD.matches(state)
                    and state.values.get('city_resource_state',{}).get('ready') is True
                    and all(state.values['city_resources'].get(key,{}).get('rssValue',float('inf'))
                        <state.values['city_resources'].get(key,{}).get('gatherMin',0) for key in pending)
                    and state.values['resources'].get(str(resource),0)>before and state.values['resources']['5']==gems
                    and completed_receipt(state,resource)==state.values['resources'][str(resource)])
                if harvested:break
                if clock()>=deadline:raise NotReady('Строительство: выбор здания не подтверждён')
                if cancelled.wait(.1):raise Cancelled('Строительство отменено')
            if selected(state,building,kind):break
        if not selected(state,building,kind):raise NotReady('Строительство: целевое здание не выбрано')
        class Selection:
            def matches(self,state):return selected(state,building,kind)
        buttons=state.values['building_menu']['selected']['buttons']
        point=(proof['point'][0]+{2:50,3:0,4:-45}[len(buttons)],proof['point'][1]+105)
        # Existing quarry geometry is retained; other ordinary menus are anchored
        # to the selected building's just-calibrated screen ground point.
        if kind==4:point=(475,365)
        state=execute((Tap(*point,Selection(),PANEL,hold_ms=100,settle=.4),))
        try:receipt=UpgradeReceipt.capture(observe(),options,building)
        except NotReady:
            return clean()
        permit();device.tap(740,410,hold_ms=100)
        deadline=clock()+20
        while True:
            state=observe()
            if receipt.matches(state):break
            if clock()>=deadline:raise WorkflowError('Строительство: результат не подтверждён; повтор запрещён')
            if cancelled.wait(.1):raise Cancelled('Строительство отменено')
        # The server can start an onboarding overlay after accepting the order.
        # The upgrade is complete as a task; let the tutorial task own that UI.
        state=observe()
        if set(state.values.get('views',{}))-set(CITY_VIEWS+('UpgradeBuilding','CommonBackground','TroopPowerUpHUD')):
            state.values['building_upgrade_started']=building
            return state
        return clean()


def building_workflow(settings,*,verified=False):
    options=BuildingOptions.from_settings(settings);paths=FIELDS
    if options.create_missing:
        from .construction import FIELDS as CONSTRUCTION_FIELDS
        paths={**paths,**CONSTRUCTION_FIELDS}
        if options.clear_plants:paths={**paths,'tutorial':['@tutorial']}
    return Workflow('buildings','1.1.12.20',960,540,(Procedure(UpgradeCycle(options)),),
        verified=verified,extra_paths=paths,data_timeout=10,guide_condition=UpgradeGuide(),
        wait_reason='Ожидание выбранного здания, ресурсов и постоянного строителя')
