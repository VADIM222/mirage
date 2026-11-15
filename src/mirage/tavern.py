"""Free tavern chests, with currency invariants and memory-based city navigation."""
from dataclasses import dataclass

from .navigation import number
from .workflows import (All, AnyOf, CITY_HUD, CITY_SCENE, CITY_VIEWS, Condition, NavigateCity,
                         Cancelled, NotReady, Procedure, QUEUE_CLOSE, QUEUE_HIDDEN, QUEUE_KNOWN,
                         SELECTION_CLEAR, Tap, Workflow, WorkflowError)


FIELDS = {
    "city_camera":["@city_camera"],"building_menu":["@building_menu"],
    "tavern_visible":["@active_view","TavernPage"],
    "tavern_menu":["UIObjectManager","TavernPage","curMenu"],
    "tavern_mode":["UIObjectManager","TavernPage","mode"],
    "tavern_animation":["UIObjectManager","TavernPage","AnimationPlaying"],
    "tavern_info":["UIObjectManager","TavernPage","infoShowing"],
    "tavern_probability":["UIObjectManager","TavernPage","probShowing"],
    "tavern_multi":["UIObjectManager","TavernPage","MulitMode"],
    "tavern_show_equip":["UIObjectManager","TavernPage","showEquipBox"],
    "tavern_normal":["TavernData","Normal"],"tavern_rare":["TavernData","Rare"],"tavern_equip":["TavernData","Equip"],
    "tavern_items_known":["ItemData","MyItemListInited"],
    "tavern_key_silver":["ItemData","MyItemList",47],"tavern_key_gold":["ItemData","MyItemList",48],
    "tavern_key_equip":["ItemData","MyItemList",190],
    "tavern_hero_visible":["@active_view","AllUIHeroCheckIn"],
    "tavern_hero_id":["UIObjectManager","AllUIHeroCheckIn","ShowHeroId"],
    "tavern_hero_star":["UIObjectManager","AllUIHeroCheckIn","ShowHeroStar"],
    "tavern_hero_width":["UIObjectManager","AllUIHeroCheckIn","m_UICullWidth"],
    "tavern_hero_height":["UIObjectManager","AllUIHeroCheckIn","m_UICullHeigth"],
    'tavern_slg_hero':['@tavern_slg_hero'],
}
VISIBLE = Condition(("tavern_visible",),"eq",True)
READY = Condition(("tavern_state","ready"),"eq",True)
AVAILABLE = All((READY,AnyOf((Condition(('tavern_state','rows','silver','available'),'eq',True),
    Condition(('tavern_state','rows','gold','available'),'eq',True),
    All((Condition(('tavern_show_equip',),'eq',True),Condition(('tavern_state','rows','equip','available'),'eq',True)))))))
SCREEN = All((VISIBLE,Condition(("tavern_info",),"eq",False),Condition(("tavern_probability",),"eq",False),
    Condition(("tavern_multi",),"eq",False),Condition(("tavern_animation",),"eq",False),
    Condition(("views",),"subset",CITY_VIEWS+("TavernPage",))))
MAIN = All((SCREEN,Condition(("tavern_menu",),"eq",1)))
KINDS = (("silver",1,2,200,170),("gold",2,3,480,170),("equip",3,4,760,377))


@dataclass(frozen=True)
class HeroResultPanel:
    def matches(self,state):
        v=state.values
        slg=v.get('tavern_slg_hero',{});is_slg=isinstance(slg,dict) and slg.get('visible') is True
        hero=slg if is_slg else {key:v.get('tavern_hero_'+key) for key in ('id','star','width','height')}
        return ((v.get('tavern_hero_visible') is True or is_slg) and v.get('tavern_visible') is True
            and (v.get('tavern_mode'),v.get('tavern_menu')) in ((1,2),(2,3))
            and v.get('tavern_info') is False and v.get('tavern_probability') is False
            and v.get('tavern_multi') is False and type(hero.get('id')) is int and hero['id']>0
            and type(hero.get('star')) is int and 1<=hero['star']<=6
            and number(hero.get('width')) and abs(hero['width']-(0 if is_slg else 960))<1
            and number(hero.get('height')) and abs(hero['height']-(0 if is_slg else 540))<1
            and set(v.get('views',{}))<=set(CITY_VIEWS+('TavernPage','AllUIHeroCheckIn_SLG' if is_slg else 'AllUIHeroCheckIn')))


HERO_RESULT=HeroResultPanel()
HERO_VISIBLE=AnyOf((Condition(('tavern_hero_visible',),'eq',True),Condition(('tavern_slg_hero','visible'),'eq',True)))


@dataclass(frozen=True)
class DismissHeroResult:
    def __call__(self,device,observe,cancelled,clock,allowed):
        state=observe()
        if not HERO_RESULT.matches(state):raise NotReady('Таверна: окно командира не подтверждено')
        resources=state.values.get('resources',{})
        summary=state.values.get('tavern_state',{})
        if (any(type(resources.get(str(i))) is not int for i in range(1,7))
                or summary.get('ready') is not True or not isinstance(summary.get('keys'),dict)):
            raise NotReady('Таверна: валюты и ключи перед подтверждением не прочитаны')
        before={str(i):resources[str(i)] for i in range(1,7)};keys=dict(summary['keys'])
        if cancelled.is_set() or not allowed():raise Cancelled('Таверна: подтверждение командира отменено')
        slg=state.values.get('tavern_slg_hero',{}).get('visible') is True
        device.tap(*(714,405) if slg else (145,455),hold_ms=100)
        deadline=clock()+30
        while True:
            state=observe()
            if (state.values.get('resources',{}).get('5')!=before['5']
                    or state.values.get('tavern_state',{}).get('keys')!=keys):
                raise WorkflowError('Таверна: гемы или ключи изменились при подтверждении командира')
            if not HERO_VISIBLE.matches(state) and SCREEN.matches(state):
                if any(state.values.get('resources',{}).get(k)!=v for k,v in before.items()):
                    raise WorkflowError('Таверна: валюты изменились при подтверждении командира')
                return state
            if clock()>=deadline:raise WorkflowError('Таверна: закрытие окна командира не подтверждено; повтор запрещён')
            if cancelled.wait(.1):raise Cancelled('Таверна: подтверждение командира отменено')


HERO_CONFIRM=Procedure(DismissHeroResult(),when=HERO_VISIBLE)


def result_screen(mode,menu):
    return All((SCREEN,Condition(("tavern_menu",),"eq",menu),Condition(("tavern_mode",),"eq",mode)))


LAYOUTS=((True,KINDS),(False,(("silver",1,2,310,377),("gold",2,3,685,377))))


def confirm_step(mode,menu,x,show_equip):
    return Tap(x,480,result_screen(mode,menu),MAIN,hold_ms=100,settle=.3,
        when=All((VISIBLE,Condition(('tavern_show_equip',),'eq',show_equip),
            Condition(("tavern_menu",),"eq",menu),Condition(("tavern_mode",),"eq",mode))))


CONFIRMS = tuple(confirm_step(mode,menu,confirm_x,show_equip) for show_equip,entries in LAYOUTS
    for name,mode,menu,x,confirm_x in entries)


@dataclass(frozen=True)
class FreeReceipt:
    name: str

    def capture(self,state):
        values = state.values
        if not MAIN.matches(state) or not READY.matches(state) or not values["tavern_state"]["rows"][self.name]["available"]:
            raise WorkflowError("Не подтверждена бесплатная попытка таверны")
        if type(values.get("resources",{}).get("5")) is not int:
            raise WorkflowError("Не подтверждён баланс гемов")
        row = values["tavern_state"]["rows"][self.name]
        return FreeReceived(self.name,row["next"],row["remaining"],dict(values["tavern_state"]["keys"]),values["resources"]["5"])


@dataclass(frozen=True)
class FreeReceived:
    name: str
    previous: int | float
    remaining: int
    keys: dict
    gems: int

    def matches(self,state):
        summary = state.values.get("tavern_state",{})
        row = summary.get("rows",{}).get(self.name,{})
        return (summary.get("ready") is True and row.get("available") is False
                and row.get("next",0) > self.previous
                and (self.name != "silver" or row.get("remaining") == self.remaining-1)
                and summary.get("keys") == self.keys and state.values.get("resources",{}).get("5") == self.gems)


@dataclass(frozen=True)
class TavernMenu:
    ordinary: bool = False

    def matches(self,state):
        values = state.values
        menu = values.get("building_menu")
        selected = menu.get("selected") if isinstance(menu,dict) and menu.get("known") is True else None
        camera = values.get("city_camera")
        if not isinstance(selected,dict) or selected.get("type") != 18 or not isinstance(camera,dict):
            return False
        building = values.get("buildings",{}).get(selected.get("id"),{})
        coordinates = (camera.get("x"),camera.get("y"),building.get("world_x"),building.get("world_y"))
        return (building.get("type") == 18 and all(number(value) for value in coordinates)
                and abs(camera["x"]-building["world_x"]) < .16 and abs(camera["y"]-building["world_y"]) < .16
                and set(selected.get("buttons",[])) == {"btn_CityPopUpInfo","btn_FunctionTavern",
                    "btn_CityPopUpUpgrade" if self.ordinary else "btn_LegendTavern"})


CLAIMS = tuple(step for show_equip,entries in LAYOUTS
    for (name,mode,menu,x,confirm_x) in entries for step in (
    Tap(x,450,All((MAIN,READY)),AnyOf((result_screen(mode,menu),All((HERO_RESULT,
        Condition(('tavern_menu',),'eq',menu),Condition(('tavern_mode',),'eq',mode))))),hold_ms=100,timeout=30,
        when=All((READY,Condition(('tavern_show_equip',),'eq',show_equip),
            Condition(("tavern_state","rows",name,"available"),"eq",True))),increase=FreeReceipt(name)),
    HERO_CONFIRM,
    confirm_step(mode,menu,confirm_x,show_equip),
))
TAVERN = Workflow("tavern","1.1.12.20",960,540,(
    HERO_CONFIRM,*CONFIRMS,QUEUE_CLOSE,*SELECTION_CLEAR,
    NavigateCity(18,when=All((Condition(("tavern_visible",),"eq",False),AVAILABLE))),
    Tap(575,365,All((CITY_SCENE,QUEUE_HIDDEN,TavernMenu(True))),MAIN,hold_ms=100,settle=.3,
        when=All((Condition(("tavern_visible",),"eq",False),AVAILABLE,TavernMenu(True)))),
    Tap(485,365,All((CITY_SCENE,QUEUE_HIDDEN,TavernMenu())),MAIN,hold_ms=100,settle=.3,
        when=All((Condition(("tavern_visible",),"eq",False),AVAILABLE))),
    *CLAIMS,
    Tap(29,28,MAIN,CITY_HUD,hold_ms=100,when=VISIBLE,settle=.3),
),verified=True,precondition=All((QUEUE_KNOWN,Condition(("hud_visible",),"eq",True),Condition(("hud_menu",),"eq",False),
    Condition(("in_city",),"eq",True),
     Condition(("views",),"subset",CITY_VIEWS+("TavernPage","AllUIHeroCheckIn","AllUIHeroCheckIn_SLG","VIPMainPage","CommonBackground","TroopPowerUpHUD")))),
    entry_condition=READY,when=AnyOf((AVAILABLE,VISIBLE)),extra_paths=FIELDS,
    wait_reason="Таверна: ожидание бесплатных попыток, загруженных данных и доступного экрана")
