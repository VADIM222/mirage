"""City navigation from live camera feedback; no Unity methods or game commands."""
import math
from dataclasses import dataclass

from .workflows import Cancelled, CITY_HUD, NotReady, WorkflowError


def number(value):
    return type(value) in (int,float) and math.isfinite(value)


def hud_function_point(state,kind):
    f=state.values.get('hud_functions');slots=f.get('slots') if isinstance(f,dict) else None
    slot=slots.get(str(kind)) if isinstance(slots,dict) else None
    if (not isinstance(f,dict) or f.get('ready') is not True or not isinstance(slots,dict)
            or any(str(k).startswith('$') for k in slots) or type(slot) is not int or not 1<=slot<=5
            or sum(value==slot for value in slots.values())!=1):
        raise NotReady('Меню города: кнопка нужной функции не подтверждена')
    return (924-75*slot,505)


@dataclass(frozen=True)
class OpenHudFunction:
    kind: int
    result: object

    def __call__(self,device,observe,cancelled,clock,allowed):
        from .workflows import Engine, HUD_MENU, Tap, Workflow
        state=observe();point=hud_function_point(state,self.kind)
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('open_hud_function','1.1.12.20',960,540,
                (Tap(*point,HUD_MENU,self.result,hold_ms=100,settle=.4),),verified=True),cancelled,
            instance_id=state.instance_id,pid=state.pid,player_id=state.player_id)


def navigate_city(input_device, observe, cancelled, clock, building_type, allowed=lambda:True,
                  *, building_id=None, select=True):
    deadline = clock()+120
    initial = observe()
    if not CITY_HUD.matches(initial):
        raise NotReady("Для навигации нужен свободный городской экран")
    buildings = initial.values["buildings"]
    candidates = [(key,item) for key,item in buildings.items()
                  if isinstance(item,dict) and item.get("type") == building_type
                  and (building_id is None or key == building_id)]
    if len(candidates) != 1 or buildings.get("$truncated"):
        raise NotReady("Не подтверждено единственное целевое здание")
    building_id,building = candidates[0]
    target = (building.get("world_x"),building.get("world_y"))
    camera = initial.values.get("city_camera")
    if (not all(number(value) for value in target) or not isinstance(camera,dict)
            or not number(camera.get("distance"))
            or not (abs(camera['distance']-150)<=.1 or 190 <= camera["distance"] <= 210)):
        raise NotReady("Не подтверждены координаты здания и масштаб города")
    distance = camera["distance"]

    def permit_input():
        if cancelled.is_set() or not allowed():
            raise Cancelled("Навигация отменена перед вводом")

    def check(state):
        camera = state.values.get("city_camera")
        item = state.values.get("buildings",{}).get(building_id,{})
        if (not isinstance(camera,dict) or not number(camera.get("distance"))
                or abs(camera["distance"]-distance) > .1 or item.get("type") != building_type
                or (item.get("world_x"),item.get("world_y")) != target):
            raise NotReady("Здание или масштаб города изменился во время навигации")
        point = (camera.get("x"),camera.get("y"))
        if not all(number(value) for value in point) or math.dist(point,target) > 6:
            raise NotReady("Цель находится вне подтверждённой области города")
        return camera,point

    def wait():
        if clock() >= deadline:
            raise WorkflowError("Навигация к зданию не завершилась за 120 секунд")
        if cancelled.wait(.1):
            raise Cancelled("Навигация отменена")

    def stable():
        until = min(deadline,clock()+12)
        previous,samples = None,0
        while True:
            state = observe()
            camera,point = check(state)
            if (CITY_HUD.matches(state) and camera.get("moving") is False and previous is not None
                    and max(abs(a-b) for a,b in zip(point,previous)) < .001):
                samples += 1
                if samples >= 3:
                    return state,point
            else:
                samples = 0
            if clock() >= until:
                raise NotReady("Ожидание неподвижной камеры на свободном городском экране")
            previous = point
            wait()

    # Two reversible drags measure the actual current camera scale and orientation.
    calibrated = False
    for calibration_origin,delta in (((600,400),-80),((300,200),80),((300,300),-80)):
        columns = []
        for dx,dy in ((delta,0),(0,delta)):
            state,before = stable()
            permit_input()
            input_device.drag(*calibration_origin,calibration_origin[0]+dx,calibration_origin[1]+dy,duration_ms=300)
            state,after = stable()
            columns.append(tuple((b-a)/delta for a,b in zip(before,after)))
        (a,c),(b,d) = columns
        determinant = a*d-b*c
        if .000001 < abs(determinant) < .01:
            calibrated = True
            break
    if not calibrated:
        raise NotReady("Не подтверждён отклик камеры на перемещение")
    origin = calibration_origin
    origins = ((600,400),(300,200),(300,300),(700,250),(700,350),(250,350))
    fine_origins = ((300,300),(600,300),(700,300))
    fine = False
    response_gain = 1.0
    stalled = 0
    for _ in range(14):
        state,point = stable()
        wx,wy = target[0]-point[0],target[1]-point[1]
        dx,dy = (d*wx-b*wy)/determinant,(-c*wx+a*wy)/determinant
        remaining = math.hypot(dx,dy)
        if remaining < (12 if select else 26):
            break
        # A very short gesture is interpreted as a building tap. Move away first,
        # so that the following correction is a full drag rather than a click.
        detour = remaining < 40
        if detour and not fine:
            # Near an edge, a 40px detour followed by a correction clipped to
            # the same 40px returns to the same point. Central origins give
            # the next full gesture room in both directions.
            fine = True
            origin = fine_origins[0]
        if detour:
            dx,dy = -dx*50/remaining,-dy*50/remaining
        # After a deliberate detour, use the measured gain for the whole
        # correction. Repeated80% corrections can settle just outside the
        # selection tolerance and trigger another detour indefinitely.
        scale = min((1.0 if fine and not detour else .8)/response_gain,100/max(abs(dx),abs(dy)))
        # Keep the complete gesture inside the city viewport, above bottom controls.
        for delta,start,low,high in ((dx,origin[0],200,850),(dy,origin[1],160,440)):
            if delta > 0: scale = min(scale,(high-start)/delta)
            elif delta < 0: scale = min(scale,(low-start)/delta)
        permit_input()
        sx,sy = round(dx*scale),round(dy*scale)
        input_device.drag(*origin,origin[0]+sx,origin[1]+sy,duration_ms=300)
        state,after = stable()
        # Gesture damping differs from the80px calibration. Adapt only input
        # gain; retain the original geometric projection for the final tap.
        px,py = a*sx+b*sy,c*sx+d*sy
        predicted = px*px+py*py
        gain = ((after[0]-point[0])*px+(after[1]-point[1])*py)/predicted if predicted else 0
        if .35 <= gain <= 1.5:
            response_gain = gain
        if math.dist(after,point) < .002 or (not detour and math.dist(after,target) >= math.dist(point,target)):
            stalled += 1
            candidates = fine_origins if fine else origins
            origin = candidates[(candidates.index(origin)+1)%len(candidates)]
            if stalled >= len(candidates):
                raise NotReady("Камера не приближается к целевому зданию")
        else:
            stalled = 0
    else:
        raise NotReady("Не удалось приблизиться к зданию за четырнадцать перемещений")
    x,y = round(480-dx),round(270-dy)
    if not 440 <= x <= 520 or not 230 <= y <= 310:
        raise NotReady("Здание не находится рядом с центром экрана")
    if not select:
        state.values["city_navigation_target"] = {"id":building_id,"point":[x,y],
            "camera":{"x":point[0],"y":point[1],"distance":distance},"world":list(target)}
        return state
    permit_input()
    input_device.tap(x,y,hold_ms=100)
    until = min(deadline,clock()+10)
    selected_at = None
    while True:
        state = observe()
        check(state)
        menu = state.values.get("building_menu")
        selected = menu.get("selected") if isinstance(menu,dict) and menu.get("known") is True else None
        if selected is not None:
            if selected.get("id") != building_id or selected.get("type") != building_type:
                raise NotReady("Выбрано другое здание; ввод в меню остановлен")
            if selected_at is None:
                selected_at = clock()
            elif clock()-selected_at >= .4:
                return state
        if clock() >= until:
            raise WorkflowError("Выбор городского здания не подтверждён")
        wait()
