"""Place one absent ordinary building using the live catalog and placement validity."""
from dataclasses import dataclass
import math

from .supply_boxes import balances, inventory, integer, table
from .workflows import CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, NotReady, SELECTION_CLEAR, Tap, Workflow, WorkflowError


FIELDS={'construction_plan':['@construction_plan'],'building_preview':['@building_preview']}
PIXELS_X=205
PIXELS_Y=145


def missing_candidate(state,types,reserves):
    data=state.values.get('construction_plan');owned=state.values.get('buildings')
    if not table(data) or data.get('ready') is not True or not table(owned):
        raise NotReady('Постройка: каталог или город не прочитаны')
    levels={};counts={}
    for key,row in owned.items():
        if key=='localNewBuilding' or not table(row):continue
        kind=row.get('type');counts[kind]=counts.get(kind,0)+1
        if row.get('state')==1:levels[kind]=max(levels.get(kind,0),row.get('lv',0))
    money=balances(state)
    for kind in types:
        cfg=data.get('first',{}).get(str(kind));limit=data.get('limits',{}).get(str(kind),{})
        if (counts.get(kind,0) or not table(cfg) or cfg.get('Type')!=kind or cfg.get('Level')!=1
                or cfg.get('ID')!=kind*100+1 or cfg.get('Enable')!=1
                or not integer(limit.get('Level_'+str(levels.get(1,0))),1)
                or any(cfg.get(k)!=0 for k in ('Gem','Amber','Crystal','NeedBagItem','ItemCnt1'))):continue
        if any(not integer(cfg.get(name)) or money[str(i)]-cfg[name]<reserves[i-1]
                for i,name in enumerate(('Food','Wood','Stone','Coin'),1)):continue
        if any(not integer(cfg.get('PreType'+str(n))) or not integer(cfg.get('PreLevel'+str(n)))
                or cfg['PreType'+str(n)] and levels.get(cfg['PreType'+str(n)],0)<cfg['PreLevel'+str(n)]
                for n in (1,2,3)):continue
        return cfg
    return None


def placement_buttons(state,kind,*,valid=True,offscreen=False):
    data=state.values.get('building_preview',{});p=data.get('preview',{});camera=state.values.get('city_camera',{})
    origin=data.get('cityOrigin',{});position=p.get('position',{})
    if (data.get('selection')!='localNewBuilding' or p.get('id')!='localNewBuilding' or p.get('type')!=kind
            or p.get('lv')!=0 or p.get('state')!=4 or p.get('isSelected') is not True
            or valid and p.get('newPosValid') is not True or camera.get('moving') is not False
            or not isinstance(camera.get('distance'),(int,float)) or abs(camera['distance']-150)>.1
            or set(state.values.get('views',{}))-set(CITY_VIEWS)):
        raise NotReady('Постройка: обычное размещение или неподвижная камера не подтверждены')
    values=[origin.get('1'),origin.get('2'),position.get('x'),position.get('y'),camera.get('x'),camera.get('y')]
    if any(type(n) not in (int,float) or not math.isfinite(n) for n in values):
        raise NotReady('Постройка: координаты предпросмотра не прочитаны')
    ox,oy,x,y,cx,cy=values;wx=ox+(x-y)*math.sqrt(.5);wy=oy+(x+y)*math.sqrt(.5)
    # Observed ordinary placement menu at city distance150. Recomputed from the
    # current preview, never from the position of a previously placed building.
    px=round(540+PIXELS_X*(wx-cx));py=round(151-PIXELS_Y*(wy-cy))
    if not offscreen and not (190<=px<=900 and 70<=py<=430):raise NotReady('Постройка: кнопки размещения вне доступного экрана')
    return (px,py),(px-110,py)


def placement_candidates(state,kind):
    cfg=state.values.get('construction_plan',{}).get('first',{}).get(str(kind),{})
    width,length=cfg.get('Width'),cfg.get('Length')
    if not integer(width,1) or not integer(length,1) or max(width,length)>15:
        raise NotReady('Постройка: размер обычного здания не подтверждён')
    occupied=[]
    for key,row in state.values.get('buildings',{}).items():
        if key=='localNewBuilding' or not table(row):continue
        if row.get('logicPosition')=={'x':-99,'y':-99}:continue
        pos=row.get('position',{});w,h=row.get('width'),row.get('length')
        if not integer(w) or not integer(h):raise NotReady('Постройка: размеры занятых клеток не прочитаны')
        if not w or not h:continue
        if any(type(pos.get(k)) not in (int,float) or not math.isfinite(pos[k]) for k in ('x','y')):
            raise NotReady('Постройка: положение существующего объекта не прочитано')
        occupied.append((pos['x'],pos['y'],w*.1,h*.1))
    origin=state.values.get('building_preview',{}).get('preview',{}).get('position',{})
    result=[]
    for gx in range(-19,20-width):
        for gy in range(-19,20-length):
            x,y=(gx+(width-1)/2)*.1,(gy+(length-1)/2)*.1
            if any(abs(x-ox)<(width*.1+w)/2-.001 and abs(y-oy)<(length*.1+h)/2-.001
                    for ox,oy,w,h in occupied):continue
            distance=(x-origin.get('x',0))**2+(y-origin.get('y',0))**2
            result.append((distance,x,y))
    return [(x,y) for _,x,y in sorted(result)]


@dataclass(frozen=True)
class ConstructionReceipt:
    kind: int
    builder: int
    position: dict
    previous: frozenset
    money: dict
    items: dict
    seconds: int

    @classmethod
    def capture(cls,state,types,reserves):
        from .building_upgrade import permanent_builder
        cfg=missing_candidate(state,types,reserves);data=state.values.get('building_preview',{})
        if cfg is None or data.get('buildCost')!=cfg:raise NotReady('Постройка: стоимость предпросмотра отличается от каталога')
        placement_buttons(state,cfg['Type']);builder=permanent_builder(state)
        if builder is None:raise NotReady('Постройка: постоянный строитель занят')
        money=balances(state)
        for i,name in enumerate(('Food','Wood','Stone','Coin'),1):money[str(i)]-=cfg[name]
        if not integer(cfg.get('BuildingTime'),1):raise NotReady('Постройка: естественный таймер не прочитан')
        return cls(cfg['Type'],builder,dict(data['preview']['position']),frozenset(state.values['buildings']),money,inventory(state),cfg['BuildingTime'])

    def matches(self,state):
        if balances(state)!=self.money or inventory(state)!=self.items:return False
        buildings=state.values.get('buildings');queues=state.values.get('builder_queues')
        if not table(buildings) or not table(queues) or not self.previous-{'localNewBuilding'}<=set(buildings):return False
        added=[(key,row) for key,row in buildings.items() if key not in self.previous and key!='localNewBuilding']
        if len(added)!=1:return False
        key,row=added[0]
        if not table(row) or row.get('type')!=self.kind or not table(row.get('position')):return False
        if any(abs(row['position'].get(k,float('inf'))-v)>.011 for k,v in self.position.items()):return False
        finished=row.get('lv')==1 and row.get('state')==1 and row.get('endTime')==0
        running=(row.get('lv') in (0,1) and row.get('state')==2 and integer(row.get('endTime'),1)
            and row['endTime']>state.values.get('server_time',float('inf')))
        unveiling=(row.get('lv')==0 and row.get('state')==3 and integer(row.get('endTime'),1)
            and row['endTime']>state.values.get('server_time',float('inf'))
            and integer(row.get('totalTime'),1) and row['totalTime']<=self.seconds*1000)
        if not finished and not running and not unveiling:return False
        return sum(table(q) and q.get('id')==self.builder and q.get('from')=='born'
            and q.get('endTime')==-1 and q.get('buildingId')==('' if finished or unveiling else key) for q in queues.values())==1


class Catalog:
    def matches(self,state):
        return (state.values.get('construction_plan',{}).get('ui',{}).get('visible') is True
            and set(state.values.get('views',{}))<=set(CITY_VIEWS+('BuildNewBuilding','CommonBackground')))


def open_building_preview(state,kind,device,observe,cancelled,execute,permit):
    """Locate a card through harmless previews; returned type is verified before spending."""
    if not CITY_HUD.matches(state) and set(state.values.get('views',{}))<=set(CITY_VIEWS):
        state=execute(SELECTION_CLEAR)
    if not CITY_HUD.matches(state) and not Catalog().matches(state):
        raise NotReady('Постройка: нужен город или обычный каталог')
    state=execute((Tap(43,408,CITY_HUD,Catalog(),hold_ms=100,settle=.4),))
    group=next((int(g) for g,rows in state.values['construction_plan']['groups'].items()
        if any(r.get('Type')==kind for r in rows.values())),None)
    if group not in (1,2):raise NotReady('Постройка: обычная вкладка здания не найдена')
    requested=None;card_x=422;money,items=balances(state),inventory(state)
    for attempt in range(8):
        state=execute((Tap(43,408,CITY_HUD,Catalog(),hold_ms=100,settle=.4),))
        current=state.values['construction_plan']['ui']['group']
        for wanted in ((3-group,group) if current==group else (group,)):
            state=execute((Tap(40,293 if wanted==2 else 385,Catalog(),
                Condition(('construction_plan','ui','group'),'eq',wanted),hold_ms=100,settle=.4),))
        ui=state.values['construction_plan']['ui'];rows=ui['rows']
        indices=[int(i) for i,r in rows.items() if r.get('type')==kind]
        if len(indices)!=1 or ui.get('itemHeight')!=308:
            raise NotReady('Постройка: карточка или размер каталога не подтверждены')
        index=indices[0]
        if requested is None:
            requested=0 if index<=4 else (index-2)*222/1.2
            card_x=200+222*(index-1) if index<=4 else 422
        if requested:
            steps=max(1,math.ceil(requested/500));distance=max(80,round(requested/steps))
            if steps>10:raise NotReady('Постройка: слишком большой сдвиг каталога')
            for _ in range(steps):
                permit()
                if not Catalog().matches(observe()):raise NotReady('Постройка: каталог изменился при прокрутке')
                device.drag(840,350,840-distance,350)
                if cancelled.wait(.5):raise Cancelled('Постройка отменена')
        permit()
        if not Catalog().matches(observe()):raise NotReady('Постройка: перед выбором карточки нужен каталог')
        device.tap(round(card_x),350,hold_ms=100)
        if cancelled.wait(.6):raise Cancelled('Постройка отменена')
        state=observe()
        if balances(state)!=money or inventory(state)!=items:
            raise WorkflowError('Постройка: активы изменились до подтверждения размещения')
        p=state.values.get('building_preview',{}).get('preview',{})
        if p.get('type')==kind:return state
        actual=p.get('type')
        if actual is None:
            if not Catalog().matches(state):raise NotReady('Постройка: неизвестный экран карточки')
            requested=max(0,requested+(-222 if attempt%2 else 333));card_x=422
            continue
        positions=[int(i) for i,r in rows.items() if r.get('type')==actual]
        _,cancel=placement_buttons(state,actual,valid=False)
        state=execute((Tap(*cancel,Condition(('building_preview','preview','type'),'eq',actual),
            CITY_HUD,hold_ms=100,settle=.4),))
        if len(positions)!=1:raise NotReady('Постройка: неизвестная карточка после прокрутки')
        delta=(index-positions[0])*222
        if 130<=card_x+delta<=880:card_x+=delta
        else:requested=max(0,requested+delta/1.2);card_x=422
    raise NotReady('Постройка: ограниченный поиск нужной карточки завершён')


def find_placement(state,kind,device,observe,cancelled,permit):
    """Move only the uncommitted preview; every move is checked against native validity."""
    if state.values.get('building_preview',{}).get('preview',{}).get('newPosValid') is not False:return state
    money,items=balances(state),inventory(state)
    for x,y in placement_candidates(state,kind)[:12]:
        correction_x=correction_y=0
        for _ in range(3):
            permit();state=observe();point,_=placement_buttons(state,kind,valid=False,offscreen=True)
            p=state.values['building_preview']['preview']['position'];dx,dy=x-p['x'],y-p['y']
            sx,sy=point[0]-60,point[1]+95
            ex=round(sx+PIXELS_X*(dx-dy)*math.sqrt(.5)+correction_x)
            ey=round(sy-PIXELS_Y*(dx+dy)*math.sqrt(.5)+correction_y)
            if not (180<=sx<=850 and 120<=sy<=430 and 180<=ex<=850 and 120<=ey<=430):break
            if math.hypot(ex-sx,ey-sy)<30:break
            permit();device.drag(sx,sy,ex,ey)
            if cancelled.wait(.5):raise Cancelled('Постройка отменена')
            state=observe()
            if balances(state)!=money or inventory(state)!=items:
                raise WorkflowError('Постройка: активы изменились во время выбора места')
            if state.values.get('building_preview',{}).get('preview',{}).get('newPosValid') is True:return state
            actual=state.values.get('building_preview',{}).get('preview',{}).get('position',{})
            if not table(actual):raise NotReady('Постройка: предпросмотр исчез при перемещении')
            error_x,error_y=x-actual['x'],y-actual['y']
            correction_x+=PIXELS_X*(error_x-error_y)*math.sqrt(.5)
            correction_y-=PIXELS_Y*(error_x+error_y)*math.sqrt(.5)
    raise NotReady('Постройка: свободное место не подтверждено после ограниченного поиска')


def cleanup_target(state,kind):
    """Pick one plant from the smallest obstructing set (at most three) for a footprint."""
    from .plants import PLANT_TYPES
    cfg=state.values.get('construction_plan',{}).get('first',{}).get(str(kind),{})
    width,length=cfg.get('Width'),cfg.get('Length')
    if not integer(width,1) or not integer(length,1):raise NotReady('Уборка: размер цели не подтверждён')
    catalog=state.values.get('construction_plan',{}).get('groups',{}).get('3',{})
    removable={r['Type'] for r in catalog.values() if table(r) and r.get('Type') in PLANT_TYPES
        and r.get('CanRemove')==1 and r.get('Width')==3 and r.get('Length')==3}
    objects=[]
    for key,row in state.values.get('buildings',{}).items():
        if key=='localNewBuilding' or not table(row) or row.get('logicPosition')=={'x':-99,'y':-99}:continue
        p=row.get('position');w,h=row.get('width'),row.get('length')
        if not table(p) or not integer(w) or not integer(h):raise NotReady('Уборка: карта города неполна')
        if not w or not h:continue
        if any(type(p.get(k)) not in (int,float) or not math.isfinite(p[k]) for k in ('x','y')):
            raise NotReady('Уборка: положение объекта неизвестно')
        can=(row.get('type') in removable and row.get('state')==1 and row.get('lv')==1 and w==h==3)
        objects.append((key,p['x'],p['y'],w*.1,h*.1,can))
    choices=[]
    # Stay inside the observed ordinary city; native placement still decides validity.
    for gx in range(-19,20-width):
        for gy in range(-19,20-length):
            x,y=(gx+(width-1)/2)*.1,(gy+(length-1)/2)*.1;blockers=[]
            for key,ox,oy,w,h,can in objects:
                if abs(x-ox)<(width*.1+w)/2-.001 and abs(y-oy)<(length*.1+h)/2-.001:
                    if not can:break
                    blockers.append(key)
            else:
                if 1<=len(blockers)<=3:choices.append((len(blockers),x*x+y*y,tuple(sorted(blockers))))
    return min(choices)[2][0] if choices else None


def store_plant(state,building,device,observe,cancelled,clock,allowed,execute,permit):
    from .navigation import navigate_city
    from .plants import PlantRecycleReceipt
    row=state.values['buildings'][building]
    catalog=state.values.get('construction_plan',{}).get('groups',{}).get('3',{})
    if not any(table(r) and r.get('Type')==row.get('type') and r.get('CanRemove')==1
            and r.get('Width')==3 and r.get('Length')==3 for r in catalog.values()):
        raise NotReady('Уборка: native-разрешение упаковки обычного растения не прочитано')
    state=navigate_city(device,observe,cancelled,clock,row['type'],allowed,building_id=building,select=False)
    proof=state.values.get('city_navigation_target')
    if not table(proof) or proof.get('id')!=building:raise NotReady('Уборка: положение растения не подтверждено')
    state=execute((Tap(*proof['point'],CITY_HUD,Condition(('city_selection',),'eq',building),hold_ms=100,settle=.4),))
    receipt=PlantRecycleReceipt.capture_selected(state,building)
    x,y=proof['point'];permit();device.tap(x+60,y+100,hold_ms=100);deadline=clock()+15
    while True:
        permit();state=observe()
        if receipt.matches(state):
            state=execute(SELECTION_CLEAR);state.values['building_space_pending']=True
            state.values['plant_stored']=building;return state
        if clock()>=deadline:raise WorkflowError('Уборка: точная упаковка растения не подтверждена; повтор запрещён')
        if cancelled.wait(.1):raise Cancelled('Уборка отменена')


def build_missing(options,device,observe,cancelled,clock,allowed):
    from .building_upgrade import permanent_builder
    from .development import next_building_target
    if not options.create_missing:return None
    initial=observe();state=initial;types=options.types
    def permit():
        if cancelled.is_set() or not allowed():raise Cancelled('Постройка отменена')
    def execute(steps):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('construction_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    if options.auto_prerequisites:
        target=next_building_target(state,types,options.max_level)
        if target is None or target.building is not None:return None
        types=(target.kind,)
    cfg=missing_candidate(state,types,options.reserves)
    if cfg is None or permanent_builder(state) is None:return None
    kind=cfg['Type'];preview=state.values.get('building_preview',{}).get('preview')
    if not table(preview):
        state=open_building_preview(state,kind,device,observe,cancelled,execute,permit)
    state=observe()
    tutorial=state.values.get('tutorial',{})
    if options.clear_plants and tutorial.get('name')=='slg_2_recycle_plants' and tutorial.get('active') is True:
        from .tutorial import AdvanceTutorial
        state=AdvanceTutorial(3)(device,observe,cancelled,clock,allowed)
        state.values['building_space_pending']=True;return state
    try:state=find_placement(state,kind,device,observe,cancelled,permit)
    except NotReady:
        if not options.clear_plants:raise
        state=observe();building=cleanup_target(state,kind)
        if building is None:raise
        _,cancel=placement_buttons(state,kind,valid=False)
        state=execute((Tap(*cancel,Condition(('building_preview','preview','type'),'eq',kind),CITY_HUD,hold_ms=100,settle=.4),))
        return store_plant(state,building,device,observe,cancelled,clock,allowed,execute,permit)
    deadline=clock()+10
    while True:
        permit();state=observe()
        try:
            point,_=placement_buttons(state,kind);receipt=ConstructionReceipt.capture(state,types,options.reserves)
            break
        except NotReady:
            if clock()>=deadline:raise
            if cancelled.wait(.1):raise Cancelled('Постройка отменена')
    permit();device.tap(*point,hold_ms=100);deadline=clock()+20
    while True:
        permit();state=observe()
        if receipt.matches(state):
            if set(state.values.get('views',{}))<=set(CITY_VIEWS):state=execute(SELECTION_CLEAR)
            else:state.values['building_upgrade_started']=kind
            state.values['building_created']=kind
            return state
        if clock()>=deadline:raise WorkflowError('Постройка: точный серверный результат не подтверждён; повтор запрещён')
        if cancelled.wait(.1):raise Cancelled('Постройка отменена')
