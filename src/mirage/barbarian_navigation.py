"""Memory-led world-map selection and verified free approaches for chaining."""
from dataclasses import dataclass
import math

from .barbarians import BattlePanel,close_hud_menu,idle_army,ordinary_target,own_armies,prepare_army
from .barbarian_chain import ChainNotReady,point,scene_primary,skill_geometry
from .barbarian_position import goal_point,move_combat_army,position_city_army,position_field_army
from .gather import number
from .supply_boxes import integer,table
from .workflows import (All,Condition,CITY_HUD,CITY_VIEWS,MAP_HUD,NO_SELECTION,QUEUE_HIDDEN,
    Cancelled,NotReady,WorkflowError)


PROJECTION_VERSION='1.1.12.20'
# Independent native MapEmptySpacePopUp.pos measurements at screen500/350 and
# 800/300. A third measurement8114/19084 agreed within0.02 world units. Every
# free move rechecks the requested ground point; a projection is never evidence
# of a destination, a hit or a victory.
_Y1=-4.681640625;_Y2=-1.83984375
_B=(_Y2/30-_Y1/80)/(_Y1-_Y2)
_A=-_Y1/80-_Y1*_B
_C=.82763671875*(1+80*_B)/20
RESOURCE_HEIGHT=4500
SURVEY_RADIUS=450
RESOURCE_VIEWS=('TactitalToStrategic_L1L2_ElementHUD','TactitalToStrategic_L1_ElementHUD',
    'AllUIMinimapHUD','StrategicViewHUD')
RESOURCE_HUD=All((QUEUE_HIDDEN,NO_SELECTION,Condition(('hud_visible',),'eq',True),
    Condition(('hud_menu',),'eq',False),Condition(('city_enabled',),'eq',False),
    Condition(('views',),'subset',CITY_VIEWS+RESOURCE_VIEWS)))


def frustum(camera):
    corners=camera.get('corners') if table(camera) else None
    if not table(corners) or set(corners)!={'1','2','3','4'}:
        raise ChainNotReady('Цепочка: границы видимой области карты не прочитаны')
    rows=[corners[str(i)] for i in range(1,5)]
    if any(not table(row) or any(not number(row.get(k)) for k in ('1','2','3')) for row in rows):
        raise ChainNotReady('Цепочка: неполные углы видимой области карты')
    a,b,c,d=rows;near=(b['1']-a['1'])/2;far=(c['1']-d['1'])/2
    center=(a['1']+b['1']+c['1']+d['1'])/4;bottom=(a['3']+b['3'])/2;top=(c['3']+d['3'])/2
    if (not 1<near<=far<2000 or not 1<top-bottom<2000
            or abs(a['3']-b['3'])>.1 or abs(c['3']-d['3'])>.1
            or abs((a['1']+b['1'])/2-(c['1']+d['1'])/2)>.1):
        raise ChainNotReady('Цепочка: проекция границ карты не подтверждена')
    return center,bottom,top,near,far


def screen_point(state,position,*,camera=None):
    hero=state.values.get('barbarian_hero');data=hero.get('chain') if table(hero) else None
    if camera is None:camera=data.get('camera') if table(data) else None
    if table(camera) and camera.get('corners') is not None:
        if (state.game_version!=PROJECTION_VERSION or not point(position) or camera.get('moving') is not False
                or not number(camera.get('worldHeight')) or not 0<camera['worldHeight']<=RESOURCE_HEIGHT+2):
            raise ChainNotReady('Цепочка: масштаб карты не подтверждён')
        center,bottom,top,near,far=frustum(camera)
        t=(position['y']-bottom)/(top-bottom);half=near+(far-near)*t
        if half<=.1:raise ChainNotReady('Цепочка: точка за пределами проекции карты')
        return round(480+(position['x']-center)*480/half),round(540*near*(1-t)/half)
    if (state.game_version!=PROJECTION_VERSION or not point(position) or not table(camera)
            or not point(camera) or camera.get('moving') is not False
            or not number(camera.get('distance')) or not 150<=camera['distance']<=280):
        raise ChainNotReady('Цепочка: проекция карты и неподвижная камера не подтверждены')
    dx,dy=position['x']-camera['x'],position['y']-camera['y'];denominator=_A+dy*_B
    if denominator<=.005:raise ChainNotReady('Цепочка: точка за пределами проекции карты')
    d=-dy/denominator
    return round(480+dx*(1+_B*d)/_C),round(270+d)


@dataclass
class WorldNavigator:
    device: object
    observe: object
    cancelled: object
    clock: object
    allowed: object

    def check(self):
        if self.cancelled.is_set() or not self.allowed():raise Cancelled('Навигация цепочки остановлена')

    def read(self):
        self.check();return self.observe()

    def wait(self,predicate,timeout=10):
        deadline=self.clock()+timeout
        while True:
            state=self.read()
            if predicate(state):return state
            if self.clock()>=deadline:raise WorkflowError('Цепочка: переход карты не подтверждён; повтор ввода запрещён')
            if self.cancelled.wait(.1):raise Cancelled('Навигация цепочки остановлена')

    def tap(self,x,y,hold=100):
        self.check();self.device.tap(x,y,hold_ms=hold)

    def dynamic(self,resolve,hold=100):
        self.check()
        if not hasattr(self.device,'tap_resolved'):raise NotReady('Цепочка: позднее разрешение движущейся цели не подключено')
        self.device.tap_resolved(resolve,hold_ms=hold)

    def close(self):
        state=self.read()
        for _ in range(2):
            active=set(state.values.get('views',{}))&{'MapUISearchMainPage','MapUISearchPopUp'}
            if not active:break
            if not any(BattlePanel(name).matches(state) for name in active):
                raise ChainNotReady('Цепочка: поиск перекрыт неизвестным окном')
            self.check();self.device.back()
            state=self.wait(lambda s:not active<=set(s.values.get('views',{})))
        for _ in range(2):
            if not BattlePanel('MapUISelectTroops').matches(state) and not BattlePanel('SendTroopsMain').matches(state):break
            before=set(state.values['views'])&{'SendTroopsMain','MapUISelectTroops','TroopSelectedPopUp'}
            self.check();self.device.back()
            state=self.wait(lambda s:not before<=set(s.values.get('views',{})))
        if any(BattlePanel(name).matches(state) for name in ('MapEmptySpacePopUp','MapUIBarbarianPopUp','AttackPopup')):
            self.tap(900,440);state=self.wait(lambda s:MAP_HUD.matches(s) or CITY_HUD.matches(s))
        return close_hud_menu(self.device,self.observe,self.cancelled,self.clock,self.allowed)

    def world(self):
        state=self.close()
        if CITY_HUD.matches(state):
            self.tap(45,490)
            state=self.wait(lambda s:MAP_HUD.matches(s) and s.values.get('city_enabled') is False)
        if not (MAP_HUD.matches(state) or RESOURCE_HUD.matches(state)):
            raise ChainNotReady('Цепочка: свободная карта перекрыта другим окном')
        return state

    def resources(self):
        state=self.world();camera=state.values['barbarian_hero']['chain']['camera']
        if number(camera.get('worldHeight')) and abs(camera['worldHeight']-RESOURCE_HEIGHT)<2 and camera.get('wheel') is False:
            frustum(camera);return state
        if camera.get('wheelPrefix')!='' or type(camera.get('wheel')) is not bool:
            raise ChainNotReady('Цепочка: меню масштаба домашней карты не подтверждено')
        if not camera['wheel']:
            self.tap(45,490,800)
            state=self.wait(lambda s:s.values['barbarian_hero']['chain']['camera'].get('wheel') is True,5)
        self.tap(190,420)
        state=self.wait(lambda s:RESOURCE_HUD.matches(s)
            and abs((s.values['barbarian_hero']['chain']['camera'].get('worldHeight') or 0)-RESOURCE_HEIGHT)<2
            and s.values['barbarian_hero']['chain']['camera'].get('wheel') is False,8)
        frustum(state.values['barbarian_hero']['chain']['camera']);return state

    def tactical(self,position):
        state=self.world();camera=state.values['barbarian_hero']['chain']['camera']
        if camera.get('wheel') is True:
            state=self.resources();camera=state.values['barbarian_hero']['chain']['camera']
        if camera.get('worldHeight') is None:return state
        if camera['worldHeight']<=1400:
            return state if MAP_HUD.matches(state) else self.wait(lambda s:MAP_HUD.matches(s),6)
        state,_=self.survey_pan(position)
        self.pan(lambda s:position)
        def resolve():
            current=self.read()
            if not RESOURCE_HUD.matches(current):raise ChainNotReady('Цепочка: обзор карты перекрыт перед приближением')
            x,y=screen_point(current,position)
            if not 200<=x<=850 or not 140<=y<=420:raise ChainNotReady('Цепочка: точка приближения не видна')
            return x,y
        # At Resources height the game-owned long press zooms into its ground
        # point. It does not issue a march. Recheck the actual HUD before input.
        self.dynamic(resolve,800)
        self.wait(lambda s:(MAP_HUD.matches(s) or BattlePanel('MapUIBarbarianPopUp').matches(s))
            and (s.values['barbarian_hero']['chain']['camera'].get('worldHeight') or RESOURCE_HEIGHT)<=1400,10)
        return self.close()

    def survey_pan(self,goal):
        state=self.world()
        for _ in range(3):
            camera=state.values['barbarian_hero']['chain']['camera'];_,bottom,top,near,far=frustum(camera)
            if abs(camera['x']-goal['x'])<=(near+far)*.10 and abs(camera['y']-goal['y'])<=(top-bottom)*.10:
                return state,True
            try:x,y=screen_point(state,goal)
            except ChainNotReady:
                x=480+(goal['x']-camera['x'])*960/(near+far)
                y=270-(goal['y']-camera['y'])*540/(top-bottom)
            dx=max(-600,min(600,480-x));dy=max(-280,min(280,270-y))
            self.check();self.device.drag(round(480-dx/2),round(275-dy/2),
                round(480+dx/2),round(275+dy/2),duration_ms=300)
            previous=None;stable_since=self.clock();minimum=stable_since+.25
            def settled(s):
                nonlocal previous,stable_since
                c=s.values['barbarian_hero']['chain']['camera'];now=self.clock()
                pos=(c.get('x'),c.get('y'),c.get('worldHeight'))
                if previous is None or any(not number(a) or not number(b) or abs(a-b)>.1 for a,b in zip(pos,previous)):
                    previous=pos;stable_since=now;return False
                return c.get('moving') is False and now>=minimum and now-stable_since>=.2
            state=self.wait(settled,5)
        camera=state.values['barbarian_hero']['chain']['camera'];_,bottom,top,near,far=frustum(camera)
        arrived=abs(camera['x']-goal['x'])<=(near+far)*.10 and abs(camera['y']-goal['y'])<=(top-bottom)*.10
        return state,arrived

    def pan(self,destination,*,npc=False):
        state=self.world()
        for _ in range(4):
            goal=destination(state);x,y=screen_point(state,goal)
            if 200<=x<=850 and 140<=y<=(330 if npc else 420):return state
            ex=500+max(-260,min(260,480-x));ey=300+max(-160,min(160,270-y))
            self.check();self.device.drag(500,300,ex,ey,duration_ms=300)
            settled=self.clock()+1.5
            state=self.wait(lambda s:self.clock()>=settled and
                s.values.get('barbarian_hero',{}).get('chain',{}).get('camera',{}).get('moving') is False,6)
        goal=destination(state);x,y=screen_point(state,goal)
        if 200<=x<=850 and 140<=y<=(330 if npc else 420):return state
        raise ChainNotReady('Цепочка: точка остаётся вне проверенной области карты')

    def survey(self,options,cursor=None,*,preferred=None):
        """Inspect up to three broad Resources-map regions per bounded tick."""
        state=self.world();hero=state.values.get('barbarian_hero') or {};data=hero.get('chain') or {}
        armies=own_armies(state)
        origin=next(iter(armies.values())).get('pos') if len(armies)==1 else data.get('cityPos')
        if len(armies)>1 or not point(origin):raise ChainNotReady('Цепочка: центр осмотра карты не прочитан')
        rejected=cursor.get('rejected',()) if table(cursor) else ()
        target=scene_primary(state,options,preferred,rejected=rejected,max_distance=SURVEY_RADIUS)
        # A freshly visible group need not pay another zoom round-trip.
        if target is None:state=self.resources()
        camera=state.values['barbarian_hero']['chain']['camera']
        if camera.get('corners') is not None:
            _,bottom,top,near,far=frustum(camera)
            step_x=max(80,round((near+far)*.7/5)*5);step_y=max(60,round((top-bottom)*.7/5)*5)
        else:step_x,step_y=110,85
        identity={'version':2,'player':state.player_id,'server':state.values.get('barbarian_server'),
            'heroes':options.heroes,'levels':[options.level,options.max_level],
            'troop':next(iter(armies.values()))['troopId'] if armies else None}
        offsets=[(0,0)]
        # Save the stride with the cursor: tactical focus changes the footprint,
        # but must not silently change the remaining survey grid on resumption.
        if table(cursor) and cursor.get('identity')==identity and cursor.get('stride'):
            stride=cursor['stride']
            if isinstance(stride,list) and len(stride)==2 and all(integer(v,60) and v<=200 for v in stride):
                step_x,step_y=stride
        for radius in range(1,7):
            ring=[(x*step_x,-radius*step_y) for x in range(-radius,radius+1)]
            ring.extend((radius*step_x,y*step_y) for y in range(-radius+1,radius+1))
            ring.extend((x*step_x,radius*step_y) for x in range(radius-1,-radius-1,-1))
            ring.extend((-radius*step_x,y*step_y) for y in range(radius-1,-radius,-1))
            offsets.extend(pos for pos in ring if math.hypot(*pos)<=SURVEY_RADIUS)
        if (not table(cursor) or cursor.get('identity')!=identity or not point(cursor.get('origin'))
                or math.dist([cursor['origin'][k] for k in ('x','y')],[origin[k] for k in ('x','y')])>30
                or not integer(cursor.get('index')) or cursor['index']>=len(offsets)
                or not isinstance(cursor.get('rejected'),list)
                or any(not integer(id,1) for id in cursor['rejected']) or len(cursor['rejected'])>128):
            cursor={'identity':identity,'origin':dict(origin),'index':0,'rejected':[],'passes':0,
                'stride':[step_x,step_y],'radius':SURVEY_RADIUS,'regions':0}
        else:cursor={**cursor,'rejected':list(cursor['rejected'])}
        target=scene_primary(state,options,preferred,rejected=cursor['rejected'],max_distance=SURVEY_RADIUS)
        if target is not None:return state,target,cursor
        deadline=self.clock()+18
        for _ in range(3):
            dx,dy=offsets[cursor['index']];goal={k:cursor['origin'][k]+d for k,d in (('x',dx),('y',dy))}
            state,arrived=self.survey_pan(goal)
            target=scene_primary(state,options,preferred,rejected=cursor['rejected'],max_distance=SURVEY_RADIUS)
            if target is not None:return state,target,cursor
            if arrived:
                cursor['regions']=cursor.get('regions',0)+1
                cursor['index']=(cursor['index']+1)%len(offsets)
                if cursor['index']==0:
                    cursor['passes']=cursor.get('passes',0)+1;cursor['rejected']=[]
            if not arrived or self.clock()>=deadline:break
        try:skill_geometry(state)
        except ChainNotReady as error:reason=str(error)
        else:reason=f'Цепочка: обзор «Ресурсы», радиус{SURVEY_RADIUS}; осмотр продолжается, участков{cursor["regions"]}'
        cursor['reason']=reason
        return state,None,cursor

    def select(self,target_id):
        def position(state):
            row=state.values.get('barbarian_hero',{}).get('chain',{}).get('scene',{}).get(str(target_id))
            if not table(row) or row.get('owner')!=-2 or row.get('isFighting') is not False or not point(row.get('pos')):
                raise ChainNotReady('Цепочка: выбранный свободный варвар больше не виден')
            return row['pos']
        self.tactical(position(self.read()));self.pan(position,npc=True)
        def resolve():
            state=self.read()
            if not MAP_HUD.matches(state):raise ChainNotReady('Цепочка: карта перекрыта перед выбором варвара')
            x,y=screen_point(state,position(state))
            if not 200<=x<=850 or not 140<=y<=475:raise ChainNotReady('Цепочка: движущаяся цель покинула область выбора')
            scene=state.values['barbarian_hero']['chain']['scene'];near=[]
            for key,row in scene.items():
                if key==str(target_id) or not table(row) or not point(row.get('pos')):continue
                try:other=screen_point(state,row['pos'])
                except ChainNotReady:continue
                if math.hypot(other[0]-x,other[1]-y)<80:near.append(other)
            if near:
                # Close patrols can overlap the usual upper-body hit region.
                # Choose a point inside this formation's measured body area
                # with maximum separation from other native unit centres.
                dx,dy=max(((0,-15),(-20,-5),(20,-5),(0,12)),key=lambda offset:min(
                    math.hypot(x+offset[0]-ox,y+offset[1]-oy) for ox,oy in near))
                return x+dx,y+dy
            return x,y-15
        self.dynamic(resolve)
        state=self.wait(lambda s:BattlePanel('MapUIBarbarianPopUp').matches(s),5)
        if (state.values.get('barbarian_target') or {}).get('id')!=target_id:
            raise ChainNotReady('Цепочка: выбран другой перекрывающий NPC; платная команда не отправляется')
        try:ordinary_target(state)
        except NotReady as error:raise ChainNotReady(str(error)) from error
        return state

    def attack_selector(self,target_id):
        state=self.read();ordinary_target(state)
        if state.values['barbarian_target']['id']!=target_id:raise ChainNotReady('Цепочка: цель окна атаки изменилась')
        def button(offset=False):
            current=self.read();target=ordinary_target(current)
            if not BattlePanel('MapUIBarbarianPopUp').matches(current) or target['id']!=target_id:
                raise ChainNotReady('Цепочка: окно атаки перекрыто или цель изменилась')
            layout=target.get('layout')
            # Search and direct selection can put the same NPC card on
            # opposite sides. Read the native layout sign instead of guessing
            # from the NPC's current (possibly patrolling) screen position.
            if (not table(layout) or layout.get('offset_x') not in (-50,50) or layout.get('offset_y')!=0
                    or layout.get('atkBtnY')!=-122 or layout.get('stayToggleY')!=-187):
                raise ChainNotReady('Цепочка: native-раскладка окна атаки не подтверждена')
            x,y=screen_point(current,target['pos']);x+=207 if layout['offset_x']==50 else -207;y=max(249,y+92)
            if not 100<=x<=860 or not 200<=y<=510:
                raise ChainNotReady('Цепочка: кнопка атаки вышла из видимой области окна')
            return (x-72,y+46) if offset else (x,y)
        hold=state.values.get('barbarian_hold')
        if type(hold) is not int or hold not in (0,1):raise ChainNotReady('Цепочка: удержание своей армии не прочитано')
        if hold==0:self.dynamic(lambda:button(True))
        self.dynamic(button)
        return self.wait(lambda s:BattlePanel('MapUISelectTroops').matches(s)
            and (s.values.get('barbarian_target') or {}).get('id')==target_id
            and s.values.get('barbarian_hold')==1,8)

    def empty_selector(self,goal):
        state=self.world();camera=state.values['barbarian_hero']['chain'].get('camera') or {}
        if point(camera) and math.dist([camera[k] for k in ('x','y')],[goal[k] for k in ('x','y')])>30:
            self.resources()
        self.tactical(goal)
        self.pan(lambda s:goal);touched=[]
        def resolve():
            state=self.read()
            if not MAP_HUD.matches(state):raise ChainNotReady('Цепочка: пустая точка перекрыта другим окном')
            x,y=screen_point(state,goal)
            if not 200<=x<=850 or not 140<=y<=420:raise ChainNotReady('Цепочка: пустая точка покинула область выбора')
            touched[:]=[x,y];return x,y
        self.dynamic(resolve,800)
        state=self.wait(lambda s:BattlePanel('MapEmptySpacePopUp').matches(s),5)
        actual=state.values['barbarian_hero']['chain'].get('emptyPos')
        if not point(actual) or math.dist([actual[k] for k in ('x','y')],[goal[k] for k in ('x','y')])>.35:
            raise ChainNotReady('Цепочка: native-координаты пустой точки расходятся с назначением')
        x,y=touched;self.tap(x-157 if x>=480 else x+315,min(380,max(233,y+55)))
        state=self.wait(lambda s:BattlePanel('MapUISelectTroops').matches(s),5)
        ui=state.values['barbarian_hero'].get('dispatch');confirmed=goal_point(ui.get('goal')) if table(ui) else None
        if (not table(ui) or ui.get('empty') is not True or ui.get('target')!=-1 or ui.get('offensive') is not False
                or confirmed is None or math.dist([confirmed[k] for k in ('x','y')],[goal[k] for k in ('x','y')])>.35):
            raise ChainNotReady('Цепочка: бесплатное назначение селектора не подтверждено')
        return state

    def position(self,goal,store,target_id,*,options=None):
        state=self.empty_selector(goal)
        if own_armies(state):
            army=idle_army(state);self.tap(910,170)
            self.wait(lambda s:((s.values['barbarian_hero'].get('dispatch') or {}).get('selection',{}).get('row') or {}).get('troopId')==army['troopId'],5)
            return position_field_army(self.device,self.observe,self.cancelled,self.clock,self.allowed,
                store=store,target_id=target_id)
        self.tap(755,110);self.wait(lambda s:BattlePanel('SendTroopsMain').matches(s),8)
        prepare_army(self.device,self.observe,self.cancelled,self.clock,self.allowed,options)
        return position_city_army(self.device,self.observe,self.cancelled,self.clock,self.allowed,
            store=store,target_id=target_id,return_camera=False)

    def focus_army(self):
        state=self.world();army=idle_army(state)
        self.tactical(army['pos'])
        self.tap(920,145)
        self.wait(lambda s:any(table(row.get('ui')) and row['ui'].get('target')==army['charId']
            and table(row['ui'].get('camera')) and row['ui']['camera'].get('moving') is False
            for row in own_armies(s).values()),15)
        return self.close()

    def pull(self,goal,store):
        state=self.empty_selector(goal);armies=own_armies(state)
        if len(armies)!=1:raise ChainNotReady('Цепочка: боевая армия отвода не прочитана')
        army=next(iter(armies.values()));self.tap(910,170)
        self.wait(lambda s:((s.values['barbarian_hero'].get('dispatch') or {}).get('selection',{}).get('row') or {}).get('troopId')==army['troopId'],5)
        return move_combat_army(self.device,self.observe,self.cancelled,self.clock,self.allowed,store=store)
