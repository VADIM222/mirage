"""Native-confirmed barbarian farming with durable ownership of one field army."""
from copy import deepcopy
from dataclasses import asdict, dataclass
import math

from .gather import number, unit_ledger
from .commanders import hero_ids,selected_heroes,troop_heroes
from .model import BarbarianOptions
from .supply_boxes import all_balances, integer, inventory, table
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, MAP_HUD,
    NotReady, Procedure, RETURN_TO_CITY, Tap, Workflow, WorkflowError)


FORM_FIELDS=('DstCharId','SrcCharId','CharType','CollectResType','SelHeroIds','SelectUnits','TotalNum',
    'isAttackNpc','isAggressive','Dispatched','troopType','troopMoveTime','NpcType','NpcLevel')
FIELDS={'barbarian_target':['@barbarian_target'],'supply_inventory':['@item_counts'],
    'barbarian_hold':['@barbarian_hold'],
    'barbarian_ap':['PveData','AP'],'barbarian_cost':['UIObjectManager','MapUISelectTroops','PVEAPCost'],
    'barbarian_marches':['@barbarian_armies'],'barbarian_city':['WorldMapData','MyChars','CityId'],
    'barbarian_server':['FogMgr','m_serverId'],'barbarian_viewed_server':['ViewOtherMapMgr','curViewServerId'],
    'barbarian_hero':['@barbarian_hero'],
    'barbarian_search':['RssSearchData','RuntimeData','Barbarian'],
    'barbarian_index':['RssSearchData','CurSelectSearchIndex'],
    'barbarian_popup_x':['UIObjectManager','MapUISearchPopUp','X'],
    'barbarian_popup_y':['UIObjectManager','MapUISearchPopUp','Y'],
    **{'barbarian_form_'+key:['UIObjectManager','SendTroopsMain',key] for key in FORM_FIELDS}}


def ordinary_target(state,expected_level=None):
    v=state.values;row=v.get('barbarian_target');npc=row.get('npcInfo') if table(row) else None
    config=row.get('config') if table(row) else None
    level=npc.get('npcLevel') if table(npc) else None
    units=unit_ledger(row.get('units')) if table(row) else None
    if (v.get('barbarian_server')!=v.get('player',{}).get('ServerID') or v.get('barbarian_viewed_server')!=0
            or not table(row) or not integer(row.get('id'),1) or row['id']%100
            or row.get('charType')!=1 or row.get('playerId')!=-2 or row.get('owner')!=-2
            or row.get('allianceId')!=0 or row.get('barbarianType')!=1 or row.get('isFighting') is not False
            or row.get('isFteVillage') is not False or not table(npc) or not table(config)
            or not integer(level,1) or level>25 or expected_level is not None and level!=expected_level
            or config.get('ID')!=npc.get('npcType') or (config.get('Type'),config.get('Level'),config.get('CostAP'))!=(1,level,50)
            or config.get('OnlyRally')!=0 or config.get('KillReward')!=3000+level
            or npc.get('barbarianType')!=1 or npc.get('summonerId')!=0
            or npc.get('isFteVillage') is not False or npc.get('isS10Special') is not False
            or npc.get('isS19Special') is not False or not integer(row.get('hp'),1) or row.get('hpMax')!=row['hp']
            or not units or sum(units.values())!=row['hp']
            or level==1 and (units!={'1':750} or row['hp']!=750)):
        raise NotReady('Варвары: обычная свободная цель выбранного уровня не подтверждена')
    return row


def own_armies(state):
    rows=state.values.get('barbarian_marches')
    if not table(rows):raise NotReady('Варвары: собственные марши не прочитаны')
    for key,row in rows.items():
        if (not table(row) or not integer(row.get('troopId'),1) or str(row['troopId'])!=key
                or not table(row.get('troop')) or row['troop'].get('playerId')!=state.player_id):
            raise NotReady('Варвары: принадлежность собственного марша не подтверждена')
    return rows


def fighting_composition(rows):
    if not table(rows) or not rows:return None
    result={}
    for row in rows.values():
        if (not table(row) or not integer(row.get('unitId'),1) or not integer(row.get('unitCount'))
                or not integer(row.get('maxCount'),1) or row['unitCount']>row['maxCount']
                or str(row['unitId']) in result):return None
        result[str(row['unitId'])]=row['maxCount']
    return result


def field_composition(rows):
    if fighting_composition(rows) is None:return None
    return {str(row['unitId']):row['unitCount'] for row in rows.values()}


def pve_talent_cost(hero):
    if (not table(hero) or not integer(hero.get('Id'),1) or not integer(hero.get('CurrentPage'))
            or not table(hero.get('TalentPage'))):
        raise NotReady('Варвары: страница талантов командира не прочитана')
    page=hero['TalentPage'].get(str(hero['CurrentPage']))
    talents=page.get('TalentMap') if table(page) else None
    if not table(talents):raise NotReady('Варвары: таланты командира прочитаны не полностью')
    native=hero.get('pveTalent')
    if not talents and hero.get('actionPointTalent')==0:return 0
    if (not table(native) or not integer(native.get('cost')) or native['cost']>50 or not table(native.get('nodes'))
            or set(native['nodes'])!={'804','1007'}
            or any(not str(key).isdecimal() or not integer(level,1) or level>5 for key,level in talents.items())):
        raise NotReady('Варвары: поправка талантов к AP не подтверждена')
    for id,node in (('804',64),('1007',84)):
        value=native['nodes'][id]
        if (not table(value) or not integer(value.get('node'),1) or not integer(value.get('level'))
                or value.get('node')!=node or value.get('level')!=talents.get(id,0) or value['level']>5):
            raise NotReady('Варвары: AP-талант требует подтверждённой цены боя')
    return native['cost']


def idle_army(state,minimum=750):
    rows=own_armies(state)
    if len(rows)!=1:raise NotReady('Варвары: нужна одна подтверждённая полевая армия')
    row=next(iter(rows.values()));troop=row['troop'];units=field_composition(troop.get('units'))
    if (row.get('state')!=4 or row.get('isFightTarget') is not False or row.get('offensive') is not False
            or row.get('isRally') is not False or row.get('IsAutoPVE') is not False or row.get('IsAutoGather') is not False
            or not integer(row.get('charId'),1) or row['charId']%100 or not integer(row.get('APR'))
            or units is None or sum(units.values())<minimum or troop.get('isAggressiveRallyCaptain') is not False
            or troop_heroes(troop) is None):
        raise NotReady('Варвары: армия ещё занята или её полевой состав не подтверждён')
    return row


def next_attack_cost(state,row=None):
    discount=pve_talent_cost(state.values.get('barbarian_hero'))
    apr=row.get('APR') if row is not None else 0
    if not integer(apr) or apr>50:raise NotReady('Варвары: скидка полевой армии не прочитана')
    return max(1,50-discount-apr)


@dataclass(frozen=True)
class BarbarianFieldReceipt:
    target: int
    troop_id: int
    char_id: int
    units: dict
    maximum: dict
    heroes: dict
    ap: int
    cost: int
    resources: dict
    items: dict
    city_units: dict

    @classmethod
    def capture(cls,state):
        v=state.values;target=ordinary_target(state);row=idle_army(state);sel=target.get('selection')
        selected=sel.get('row') if table(sel) else None
        if (not BattlePanel('MapUISelectTroops').matches(state)
                or not BattlePanel('TroopSelectedPopUp').matches(state) or not table(sel) or not table(selected)
                or not integer(sel.get('index'),1) or sel['index']>9 or sel.get('popupIndex')!=sel['index']
                or sel.get('target')!=target['id'] or sel.get('popupTarget')!=target['id'] or sel.get('rowType')!=1
                or selected.get('troopId')!=row['troopId'] or selected.get('charId')!=row['charId']
                or selected.get('APR')!=row['APR'] or selected.get('state')!=4
                or sel.get('multi') is not False or sel.get('popupMulti') is not False
                or sel.get('offensive') is not True or sel.get('buyAP') is not False or v.get('barbarian_hold')!=1
                or not number(sel.get('travel')) or not 0<sel['travel']<=120
                or not integer(sel.get('actualCost'),1) or sel['actualCost']>v.get('barbarian_cost',0)
                or not integer(v.get('barbarian_ap'),sel['actualCost'])):
            raise NotReady('Варвары: выбор своей полевой армии и фактическая цена AP не подтверждены')
        hero=v.get('barbarian_hero')
        if troop_heroes(row['troop'])!=selected_heroes(state):raise NotReady('Варвары: полевая пара не соответствует настройкам')
        if (v.get('barbarian_cost')!=target['config']['CostAP']
                or sel['actualCost']!=max(0,v['barbarian_cost']-row['APR']-pve_talent_cost(hero))):
            raise NotReady('Варвары: игровая скидка выбранной армии не подтверждена')
        troop=row['troop']
        return cls(target['id'],row['troopId'],row['charId'],field_composition(troop['units']),
            fighting_composition(troop['units']),{str(h['label']):h['heroId'] for h in troop['heros'].values()},
            v['barbarian_ap'],sel['actualCost'],all_balances(state),inventory(state),deepcopy(v['troops']))

    def matches(self,state):
        try:rows=own_armies(state);money=all_balances(state);items=inventory(state)
        except NotReady:return False
        if (set(rows)!={str(self.troop_id)} or money!=self.resources or items!=self.items
                or state.values.get('barbarian_ap')!=self.ap-self.cost):return False
        row=rows[str(self.troop_id)];troop=row['troop'];goal=row.get('target');heroes=troop.get('heros')
        current=field_composition(troop.get('units'));fighting=row.get('isFightTarget')
        return (row.get('charId')==self.char_id and row.get('state')==2 and row.get('offensive') is True
            and type(fighting) is bool and table(goal) and goal.get('charId')==self.target
            and goal.get('charType')==1 and goal.get('playerId')==-2 and troop.get('apTarget')==self.target//100
            and fighting_composition(troop.get('units'))==self.maximum and current is not None
            and (current==self.units if not fighting else all(current[k]<=n for k,n in self.units.items()))
            and table(heroes) and all(table(h) for h in heroes.values())
            and {str(h.get('label')):h.get('heroId') for h in heroes.values()}==self.heroes
            and (state.values.get('troops')==self.city_units if not fighting else True))


def dispatch_field(device,observe,cancelled,clock,allowed,checkpoint=None,*,keep_camera=False):
    initial=observe();receipt=BarbarianFieldReceipt.capture(initial)
    if cancelled.is_set() or not allowed():raise Cancelled('Бой с варваром отменён')
    if checkpoint is not None:checkpoint('intent',receipt,initial)
    if cancelled.is_set() or not allowed():
        if checkpoint is not None:checkpoint('aborted',receipt,initial)
        raise Cancelled('Бой с варваром отменён')
    device.tap(755,230,hold_ms=100);deadline=clock()+20
    while True:
        if cancelled.is_set() or not allowed():raise Cancelled('Бой с варваром отменён')
        state=observe()
        if receipt.matches(state):break
        if clock()>=deadline:raise WorkflowError('Варвары: полевая атака не подтверждена; повтор запрещён')
        if cancelled.wait(.1):raise Cancelled('Бой с варваром отменён')
    if checkpoint is not None:checkpoint('accepted',receipt,state)
    proof=deepcopy(state.values['barbarian_marches'])
    if not keep_camera and not CITY_HUD.matches(state):
        close_hud_menu(device,observe,cancelled,clock,allowed)
        state=Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            RETURN_TO_CITY,cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    state.values.update(barbarian_dispatched=receipt.target,barbarian_dispatch_proof=proof)
    return state


@dataclass(frozen=True)
class BarbarianMarchReceipt:
    target: int
    units: dict
    heroes: dict
    ap: int
    cost: int
    resources: dict
    items: dict

    @classmethod
    def capture(cls,state):
        v=state.values;target=ordinary_target(state);form={key:v.get('barbarian_form_'+key) for key in FORM_FIELDS}
        hero=v.get('barbarian_hero');cost=target['config']['CostAP']-pve_talent_cost(hero)
        selected=form['SelectUnits']
        if not table(selected) or not selected or any(not integer(count) for count in selected.values()):
            raise NotReady('Варвары: выбранный состав прочитан не полностью')
        units={key:count for key,count in selected.items() if count>0}
        if (own_armies(state) or set(v.get('views',{}))-set(CITY_VIEWS+('SendTroopsMain','CommonBackground'))
                or v.get('views',{}).get('SendTroopsMain') is not True or not integer(v.get('barbarian_city'),1)
                or not integer(form['SrcCharId'],1) or not integer(form['DstCharId'],1)
                or v['barbarian_city']%100 or form['SrcCharId']*100!=v['barbarian_city']
                or form['DstCharId']*100!=target['id'] or (form['CharType'],form['CollectResType'],form['troopType'])!=(1,-1,0)
                or (form['NpcType'],form['NpcLevel'])!=(target['npcInfo']['npcType'],target['npcInfo']['npcLevel']) or form['isAttackNpc'] is not True
                or form['isAggressive'] is not False or form['Dispatched'] is not False
                or type(v.get('barbarian_hold')) is not int or v['barbarian_hold']!=1
                or selected_heroes(state) is None or form['SelHeroIds']!=selected_heroes(state) or not units
                or any(key not in ('1','2','3','13','14','115') for key in units)
                or sum(units.values())!=form['TotalNum'] or not integer(form['TotalNum'],1000)
                or form['TotalNum']>300000 or not number(form['troopMoveTime']) or not 0<form['troopMoveTime']<=120
                or not integer(cost,1) or not integer(v.get('barbarian_ap'),cost) or v.get('barbarian_cost')!=target['config']['CostAP']):
            raise NotReady('Варвары: одиночный городской марш и стоимость AP не подтверждены')
        available={str(row.get('unitId')):row.get('unitCount') for row in v.get('troops',{}).values() if table(row)}
        if any(not integer(available.get(key),count) for key,count in units.items()):
            raise NotReady('Варвары: выбранные здоровые войска отсутствуют в городе')
        return cls(target['id'],units,dict(form['SelHeroIds']),v['barbarian_ap'],cost,
            all_balances(state),inventory(state))

    def matches(self,state):
        try:rows=own_armies(state);money=all_balances(state);items=inventory(state)
        except NotReady:return False
        if len(rows)!=1 or money!=self.resources or items!=self.items or state.values.get('barbarian_ap')!=self.ap-self.cost:
            return False
        row=next(iter(rows.values()));troop=row['troop'];target=row.get('target');heroes=troop.get('heros')
        fighting=row.get('isFightTarget')
        composition=(fighting_composition(troop.get('units')) if fighting is True else unit_ledger(troop.get('units')))
        return (row.get('state')==2 and row.get('offensive') is True and type(fighting) is bool
            and table(target) and target.get('charId')==self.target and target.get('charType')==1 and target.get('playerId')==-2
            and integer(troop.get('apTarget'),1) and troop['apTarget']*100==self.target
            and composition==self.units and table(heroes) and len(heroes)==len(self.heroes)
            and all(table(hero) for hero in heroes.values())
            and {str(hero.get('label')):hero.get('heroId') for hero in heroes.values()}==self.heroes)


def dispatch_from_form(device,observe,cancelled,clock,allowed,checkpoint=None,*,keep_camera=False):
    initial=observe();receipt=BarbarianMarchReceipt.capture(initial)
    if cancelled.is_set() or not allowed():raise Cancelled('Бой с варваром отменён')
    if checkpoint is not None:checkpoint('intent',receipt,initial)
    if cancelled.is_set() or not allowed():
        if checkpoint is not None:checkpoint('aborted',receipt,initial)
        raise Cancelled('Бой с варваром отменён')
    device.tap(695,475,hold_ms=100);deadline=clock()+20
    while True:
        if cancelled.is_set() or not allowed():raise Cancelled('Бой с варваром отменён')
        state=observe()
        if receipt.matches(state):break
        if clock()>=deadline:raise WorkflowError('Варвары: точная отправка не подтверждена; повтор запрещён')
        if cancelled.wait(.1):raise Cancelled('Бой с варваром отменён')
    if checkpoint is not None:checkpoint('accepted',receipt,state)
    proof=deepcopy(state.values['barbarian_marches'])
    if not keep_camera and not CITY_HUD.matches(state):
        close_hud_menu(device,observe,cancelled,clock,allowed)
        state=Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            RETURN_TO_CITY,cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    state.values['barbarian_dispatched']=receipt.target;state.values['barbarian_dispatch_proof']=proof
    return state


BARBARIAN_DISPATCH=Workflow('barbarian_dispatch','1.1.12.20',960,540,(Procedure(dispatch_from_form),),
    verified=True,extra_paths=FIELDS,requires_city=False)


PANELS=('MapUISearchMainPage','MapUISearchPopUp','MapUIBarbarianPopUp','MapUISelectTroops','HeroSelectPop','MapEmptySpacePopUp',
    'TroopSelectedPopUp','SendTroopsMain','CommonBackground','AttackPopup')


@dataclass(frozen=True)
class BattlePanel:
    name: str

    def matches(self,state):
        views=state.values.get('views',{})
        return views.get(self.name) is True and set(views)<=set(CITY_VIEWS+PANELS)


def prepare_army(device,observe,cancelled,clock,allowed,options=None):
    initial=state=observe()
    requested=selected_heroes(state)
    options=options or BarbarianOptions(primary=(requested or {}).get('1',3),deputy=(requested or {}).get('2',0))
    if not BattlePanel('SendTroopsMain').matches(state):raise NotReady('Варвары: форма своей армии не открыта')
    def execute(x,y,before,after):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('barbarian_prepare','1.1.12.20',960,540,
                (Tap(x,y,before,after,hold_ms=100,settle=.3,timeout=10),),verified=True,requires_city=False),
            cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    def picker(state):
        hero=state.values.get('barbarian_hero');dispatch=hero.get('dispatch') if table(hero) else None
        value=dispatch.get('picker') if table(dispatch) else None
        if (not table(value) or value.get('scale')!=1 or value.get('offsetY')!=0
                or value.get('isCityWall') is not False or not isinstance(value.get('heroes'),list)):
            raise NotReady('Варвары: геометрия списка командиров не подтверждена')
        return value
    if requested!=options.heroes:raise NotReady('Варвары: данные выбранной пары ещё не прочитаны')
    catalog=state.values.get('player',{}).get('_commanders',{})
    primary=state.values.get('barbarian_hero',{})
    if options.deputy and (not integer(primary.get('Star'),3) or primary.get('deputy',{}).get('Id')!=options.deputy):
        raise NotReady('Варвары: второй командир не открыт или данные пары отсутствуют')
    heroes=state.values.get('barbarian_form_SelHeroIds')
    if table(heroes) and heroes.get('2')==options.primary and heroes.get('1')!=options.primary:
        state=execute(354,350,BattlePanel('SendTroopsMain'),Condition(('barbarian_form_SelHeroIds',),'eq',{'1':heroes['1']}))
    for slot,id,x,y in (('1',options.primary,240,200),('2',options.deputy,354,245)):
        if not id or state.values.get('barbarian_form_SelHeroIds',{}).get(slot)==id:continue
        metadata=catalog.get('heroes',{}).get(str(id)) if table(catalog) else None
        if id==3 and not table(metadata):metadata={'rarity':4,'tags':'1,7,11'}
        rarity=metadata.get('rarity') if table(metadata) else None
        tags=metadata.get('tags') if table(metadata) else None
        tag=int(tags.split(',')[0]) if isinstance(tags,str) and tags.split(',')[0].isdigit() else None
        rarity_buttons={5:(322,201),4:(470,201),3:(618,201),2:(322,235)}
        unit_buttons={5:(322,284),4:(470,284),3:(618,284),1:(322,323),2:(470,323),16:(618,323)}
        if rarity not in rarity_buttons or tag not in unit_buttons:raise NotReady('Варвары: native-фильтры выбранного командира не подтверждены')
        state=execute(x,y,BattlePanel('SendTroopsMain'),BattlePanel('HeroSelectPop'))
        p=picker(state)
        if p.get('slot')!=int(slot):raise NotReady('Варвары: открыт другой слот командира')
        if p.get('IsOpenFilterPage') is False:
            state=execute(135,60,BattlePanel('HeroSelectPop'),
                Condition(('barbarian_hero','dispatch','picker','IsOpenFilterPage'),'eq',True))
        elif p.get('IsOpenFilterPage') is not True:raise NotReady('Варвары: фильтр командиров не прочитан')
        # A reset affects this picker only. Both filters are confirmed from Lua
        # before the row is chosen, so no inertial scrolling or image matching is needed.
        state=execute(692,138,BattlePanel('HeroSelectPop'),_Predicate(lambda s:
            all(picker(s).get(key)==0 for key in ('FilterRarity','FilterSpecialized','FilterSpecialties'))))
        state=execute(*rarity_buttons[rarity],BattlePanel('HeroSelectPop'),
            Condition(('barbarian_hero','dispatch','picker','FilterRarity'),'eq',1<<rarity))
        state=execute(*unit_buttons[tag],BattlePanel('HeroSelectPop'),
            Condition(('barbarian_hero','dispatch','picker','FilterSpecialties'),'eq',1<<tag))
        state=execute(135,60,BattlePanel('HeroSelectPop'),
            Condition(('barbarian_hero','dispatch','picker','IsOpenFilterPage'),'eq',False))
        p=picker(state);ids=p['heroes']
        if p.get('FilterRarity')!=1<<rarity or p.get('FilterSpecialized')!=0 or p.get('FilterSpecialties')!=1<<tag or ids.count(id)!=1:
            raise NotReady('Варвары: выбранный командир отсутствует в подтверждённом фильтре')
        index=ids.index(id)
        if index>=8:raise NotReady('Варвары: командир вне первых четырёх строк списка')
        state=execute(60+95*(index%2),145+100*(index//2),BattlePanel('HeroSelectPop'),
            All((BattlePanel('SendTroopsMain'),_Predicate(lambda s,slot=slot,id=id:
                s.values.get('barbarian_form_SelHeroIds',{}).get(slot)==id),
                _Predicate(lambda s:s.values.get('views',{}).get('HeroSelectPop') is not True))))
    heroes=state.values.get('barbarian_form_SelHeroIds')
    if not options.deputy and table(heroes) and set(heroes)=={'1','2'} and heroes.get('1')==options.primary:
        state=execute(354,350,BattlePanel('SendTroopsMain'),Condition(('barbarian_form_SelHeroIds',),'eq',options.heroes))
    if state.values.get('barbarian_form_SelHeroIds')!=options.heroes:raise NotReady('Варвары: выбранная пара не назначена')
    selected=state.values.get('barbarian_form_SelectUnits')
    if not table(selected) or any(not integer(n) for n in selected.values()):raise NotReady('Варвары: состав формы не прочитан')
    if any(n and key not in ('1','2','3','13','14','115') for key,n in selected.items()):
        hero=state.values['barbarian_hero'];dispatch=hero.get('dispatch')
        rows=dispatch.get('units') if table(dispatch) else None
        if (not integer(hero.get('Level'),1) or not isinstance(rows,list) or len(rows)<3
                or any(not table(row) or row.get('index')!=i+1 or row.get('type') not in (None,i+1)
                    or row.get('unitId')!=id or not integer(row.get('unitCount'),1) or row.get('bound') is not True
                    for i,(row,id) in enumerate(zip(rows[:3],(13,14,115))))):
            raise NotReady('Варвары: первые строки боевых T4 не подтверждены')
        total=state.values.get('barbarian_form_TotalNum')
        if not integer(total,1):raise NotReady('Варвары: текущая численность формы не подтверждена')
        # Changing the primary can raise capacity. The shared MAX/CLEAR button
        # then fills the new maximum first; accept that observed transition and
        # clear once more, rather than assuming the first click always clears.
        state=execute(510,475,BattlePanel('SendTroopsMain'),_Predicate(lambda s:
            integer(s.values.get('barbarian_form_TotalNum')) and s.values['barbarian_form_TotalNum']!=total))
        if state.values['barbarian_form_TotalNum']:
            state=execute(510,475,BattlePanel('SendTroopsMain'),Condition(('barbarian_form_TotalNum',),'eq',0))
        for id,y in ((13,124),(14,185),(115,250)):
            state=execute(722,y,BattlePanel('SendTroopsMain'),
                _Predicate(lambda s,id=id:integer(s.values.get('barbarian_form_SelectUnits',{}).get(str(id)),1)))
    return state


def attack_level_one(device,observe,cancelled,clock,allowed,checkpoint=None,target_guard=None,level=1,keep_camera=False,options=None,map_only=False):
    initial=observe();state=initial
    if state.values.get('hud_menu') is True:state=close_hud_menu(device,observe,cancelled,clock,allowed)
    def execute(steps):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('barbarian_transition','1.1.12.20',960,540,steps,verified=True,data_timeout=10),cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    def return_city():
        close_hud_menu(device,observe,cancelled,clock,allowed)
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            RETURN_TO_CITY,cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    armies=own_armies(state)
    # Busy armies retain their slot; only a proven idle field army can continue.
    if armies:
        try:idle_army(state)
        except NotReady:return state if map_only or CITY_HUD.matches(state) else return_city()
    if BattlePanel('SendTroopsMain').matches(state):
        state=prepare_army(device,observe,cancelled,clock,allowed,options)
        if target_guard is not None:target_guard(state)
        return dispatch_from_form(device,observe,cancelled,clock,allowed,checkpoint,keep_camera=keep_camera)
    if not BattlePanel('MapUISelectTroops').matches(state):
        if not BattlePanel('MapUIBarbarianPopUp').matches(state):
            if map_only:
                from .barbarian_chain import ChainNotReady
                raise ChainNotReady('Цепочка: полевая цель не выбрана; продолжается осмотр карты')
            if not BattlePanel('MapUISearchMainPage').matches(state):
                if not CITY_HUD.matches(state):
                    if not MAP_HUD.matches(state):raise NotReady('Варвары: нужен свободный город или карта')
                    state=return_city()
                state=execute((Tap(45,490,CITY_HUD,All((MAP_HUD,Condition(('city_enabled',),'eq',False))),hold_ms=100,settle=.5),
                    Tap(31,425,MAP_HUD,BattlePanel('MapUISearchMainPage'),hold_ms=100,settle=.4)))
            if not BattlePanel('MapUISearchPopUp').matches(state) or state.values.get('barbarian_index')!=1:
                state=execute((Tap(185,470,BattlePanel('MapUISearchMainPage'),All((BattlePanel('MapUISearchPopUp'),
                    Condition(('barbarian_index',),'eq',1))),hold_ms=100,settle=.3),))
            if (abs(state.values.get('barbarian_popup_x',0)+387)>.1
                    or abs(state.values.get('barbarian_popup_y',0)-174)>.1):
                raise NotReady('Варвары: поиск находится вне проверенной первой вкладки')
            current=state.values.get('barbarian_search',{}).get('CurLevel')
            if not integer(current,1) or current>50 or not integer(level,1) or level>25:
                raise NotReady('Варвары: текущий уровень поиска не подтверждён')
            for _ in range(abs(level-current)):
                delta=1 if current<level else -1
                state=execute((Tap(334 if delta==1 else 70,291,BattlePanel('MapUISearchPopUp'),
                    All((BattlePanel('MapUISearchPopUp'),Condition(('barbarian_search','CurLevel'),'eq',current+delta))),
                    hold_ms=100,timeout=5,settle=.15),))
                current+=delta
            state=execute((Tap(202,365,BattlePanel('MapUISearchPopUp'),BattlePanel('MapUIBarbarianPopUp'),
                hold_ms=100,timeout=20,settle=.5),))
        target=ordinary_target(state)['id']
        if target_guard is not None:target_guard(state)
        if keep_camera or table(state.values['barbarian_target'].get('layout')):
            from .barbarian_navigation import WorldNavigator
            state=WorldNavigator(device,observe,cancelled,clock,allowed).attack_selector(target)
        else:
            hold=state.values.get('barbarian_hold')
            if type(hold) is not int or hold not in (0,1):raise NotReady('Варвары: сохранённое удержание армии не прочитано')
            if hold==0:
                if cancelled.is_set() or not allowed():raise Cancelled('Бой с варваром отменён')
                device.tap(590,406,hold_ms=100)
            state=execute((Tap(660,360,BattlePanel('MapUIBarbarianPopUp'),All((BattlePanel('MapUISelectTroops'),
                    Condition(('barbarian_hold',),'eq',1))),
                hold_ms=100,timeout=15,settle=.3),))
        if ordinary_target(state)['id']!=target:raise NotReady('Варвары: цель выбора марша изменилась')
    target=ordinary_target(state)['id']
    if armies:
        state=execute((Tap(910,170,BattlePanel('MapUISelectTroops'),All((BattlePanel('TroopSelectedPopUp'),
            Condition(('barbarian_target','selection','index'),'eq',1))),hold_ms=100,settle=.3),))
        if ordinary_target(state)['id']!=target:raise NotReady('Варвары: цель полевой армии изменилась')
        return dispatch_field(device,observe,cancelled,clock,allowed,checkpoint,keep_camera=keep_camera)
    state=execute((Tap(755,110,BattlePanel('MapUISelectTroops'),BattlePanel('SendTroopsMain'),hold_ms=100,settle=.3),))
    if ordinary_target(state)['id']!=target:raise NotReady('Варвары: цель новой армии изменилась')
    state=prepare_army(device,observe,cancelled,clock,allowed,options)
    if target_guard is not None:target_guard(state)
    return dispatch_from_form(device,observe,cancelled,clock,allowed,checkpoint,keep_camera=keep_camera)


def close_hud_menu(device,observe,cancelled,clock,allowed):
    state=observe()
    if state.values.get('hud_menu') is not True:return state
    if (state.values.get('hud_visible') is not True or set(state.values.get('views',{}))-set(CITY_VIEWS)
            or state.values.get('city_selection_known') is not True or state.values.get('city_selection') is not None):
        raise NotReady('Варвары: меню HUD перекрыто другим окном')
    if cancelled.is_set() or not allowed():raise Cancelled('Меню HUD: остановлено')
    device.tap(920,500,hold_ms=100);deadline=clock()+12
    while True:
        if cancelled.is_set() or not allowed():raise Cancelled('Меню HUD: остановлено')
        state=observe()
        if state.values.get('hud_menu') is False:return state
        if clock()>=deadline:raise WorkflowError('Варвары: закрытие меню HUD не подтверждено')
        if cancelled.wait(.1):raise Cancelled('Меню HUD: остановлено')


BARBARIANS=Workflow('barbarians','1.1.12.20',960,540,(Procedure(attack_level_one),),verified=True,
    extra_paths=FIELDS,requires_city=False,data_timeout=10,
    precondition=Condition(('views',),'subset',CITY_VIEWS+PANELS+('Arraw','PopupMissionComplete')),
    data_condition=Condition(('views',),'subset',CITY_VIEWS+PANELS),
    wait_reason='Ожидание свободного одиночного марша и обычного варвара выбранного уровня')


def recall_army(device,observe,cancelled,clock,allowed):
    initial=observe()
    if any(BattlePanel(name).matches(initial) for name in ('MapUISelectTroops','SendTroopsMain','MapEmptySpacePopUp')):
        from .barbarian_navigation import WorldNavigator
        initial=WorldNavigator(device,observe,cancelled,clock,allowed).close()
    else:initial=close_hud_menu(device,observe,cancelled,clock,allowed)
    row=idle_army(initial,1);troop_id=row['troopId'];char_id=row['charId']
    heroes=troop_heroes(row['troop'])
    money=all_balances(initial);items=inventory(initial);units=field_composition(row['troop']['units'])
    def focused(state):
        try:current=idle_army(state,1)
        except NotReady:return False
        ui=current.get('ui');camera=ui.get('camera') if table(ui) else None;pos=current.get('pos')
        return (current['troopId']==troop_id and current['charId']==char_id and troop_heroes(current['troop'])==heroes and table(ui)
            and ui.get('target')==char_id and ui.get('buttons')==2 and ui.get('recall') is True
            and ui.get('icon')=='btn_backb' and table(camera) and table(pos) and camera.get('moving') is False
            and number(camera.get('distance')) and 150<=camera['distance']<=280
            and all(number(camera.get(k)) and number(pos.get(k)) for k in ('x','y'))
            and -1.25<=camera['x']-pos['x']<=2 and abs(camera['y']-pos['y'])<=2)
    flow=Workflow('barbarian_recall_focus','1.1.12.20',960,540,
        (Tap(920,145,AnyOf((CITY_HUD,MAP_HUD)),All((BattlePanel('AttackPopup'),_Predicate(focused))),
            hold_ms=100,timeout=15,settle=.5),),verified=True,requires_city=False)
    if not focused(initial):
        state=Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(flow,cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    else:state=initial
    if not focused(state) or inventory(state)!=items or all_balances(state)!=money:
        raise NotReady('Варвары: точная кнопка возврата своей армии не подтверждена')
    if cancelled.is_set() or not allowed():raise Cancelled('Возврат армии отменён')
    current=idle_army(state,1)
    # The83k mixed T4 formation focuses1.56 world units to its right; the
    # observed two-button recall hit region then shifts from518 to486px.
    # Use its measured overlapping interior rather than clicking its edge.
    x=500 if current['ui']['camera']['x']-current['pos']['x']>1.25 else 518
    y=346
    if abs(current['ui']['camera']['y']-current['pos']['y'])>1.25:
        from .barbarian_navigation import screen_point
        px,py=screen_point(state,current['pos'],camera=current['ui']['camera']);x,y=px+38,py+76
    device.tap(x,y,hold_ms=100);deadline=clock()+20
    while True:
        if cancelled.is_set() or not allowed():raise Cancelled('Возврат армии отменён')
        state=observe();rows=own_armies(state);current=rows.get(str(troop_id));goal=current.get('target') if table(current) else None
        if (current and len(rows)==1 and current.get('charId')==char_id and current.get('state')==2
                and current.get('offensive') is False and current.get('isFightTarget') is False and table(goal)
                and goal.get('charId')==state.values.get('barbarian_city') and goal.get('charType')==3
                and field_composition(current['troop'].get('units'))==units
                and troop_heroes(current['troop'])==heroes
                and inventory(state)==items and all_balances(state)==money):break
        if clock()>=deadline:raise WorkflowError('Варвары: возврат не подтверждён; повтор запрещён')
        if cancelled.wait(.1):raise Cancelled('Возврат армии отменён')
    return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(RETURN_TO_CITY,cancelled,
        instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)


@dataclass(frozen=True)
class _Predicate:
    action: object

    def matches(self,state):return self.action(state)


def troop_totals(state):
    rows=state.values.get('troops')
    if not table(rows):raise NotReady('Варвары: городской учёт войск не прочитан')
    result={}
    for row in rows.values():
        if (not table(row) or not integer(row.get('unitId'),1) or str(row['unitId']) in result
                or any(not integer(row.get(key)) for key in ('unitCount','badHurt','hurt'))):
            raise NotReady('Варвары: здоровые и раненые войска не учтены')
        result[str(row['unitId'])]=sum(row[key] for key in ('unitCount','badHurt','hurt'))
    return result


def close_battle_forms(device,observe,cancelled,clock,allowed):
    initial=state=observe()
    for _ in range(3):
        active=set(state.values.get('views',{}))&{'SendTroopsMain','MapUISelectTroops','TroopSelectedPopUp'}
        if not active:break
        if not any(BattlePanel(name).matches(state) for name in active):raise NotReady('Варвары: форма перекрыта неизвестным окном')
        if cancelled.is_set() or not allowed():raise Cancelled('Закрытие формы отменено')
        device.back();deadline=clock()+12
        while True:
            if cancelled.is_set() or not allowed():raise Cancelled('Закрытие формы отменено')
            state=observe()
            if set(state.values.get('views',{}))&active!=active:break
            if clock()>=deadline:raise WorkflowError('Варвары: закрытие формы не подтверждено')
            if cancelled.wait(.1):raise Cancelled('Закрытие формы отменено')
    if BattlePanel('MapEmptySpacePopUp').matches(state) or BattlePanel('AttackPopup').matches(state):
        if cancelled.is_set() or not allowed():raise Cancelled('Закрытие карты отменено')
        device.tap(900,440,hold_ms=100);deadline=clock()+8
        while True:
            if cancelled.is_set() or not allowed():raise Cancelled('Закрытие карты отменено')
            state=observe()
            if MAP_HUD.matches(state):break
            if clock()>=deadline:raise WorkflowError('Цепочка: закрытие окна карты не подтверждено')
            if cancelled.wait(.1):raise Cancelled('Закрытие карты отменено')
    if BattlePanel('MapUIBarbarianPopUp').matches(state):
        flow=Workflow('close_barbarian','1.1.12.20',960,540,
            (Tap(45,490,BattlePanel('MapUIBarbarianPopUp'),CITY_HUD,hold_ms=100,settle=.3),),verified=True,requires_city=False)
    else:
        close_hud_menu(device,observe,cancelled,clock,allowed)
        flow=RETURN_TO_CITY
    return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(flow,cancelled,
        instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)


@dataclass
class BarbarianCycle:
    options: BarbarianOptions
    store: object = None
    task: str = 'barbarians'
    session: dict | None = None
    survey: dict | None = None

    def __call__(self,device,observe,cancelled,clock,allowed):
        initial=observe();key='barbarian-session:'+initial.instance_id
        session=self.store.preference(key) if self.store is not None else self.session
        def save(value):
            nonlocal session
            session=deepcopy(value);self.session=session
            if self.store is not None:self.store.set_preference(key,session)
        def pending(state):
            state.values['barbarian_pending']=True
            if session:
                state.values.update(barbarian_paid_attacks=session.get('count',0),barbarian_phase=session.get('phase'))
            if session and session.get('evidence'):
                from .barbarian_chain import ChainEvidence
                evidence=ChainEvidence.from_dict(session['evidence'])
                state.values['barbarian_chain_engaged']=len(evidence.engaged)
                state.values['barbarian_chain_free_defeated']=session.get('free_total',0)+len(evidence.free_defeated)
            return state
        rows=own_armies(initial)
        if session:
            if (session.get('task')!=self.task or session.get('player')!=initial.player_id
                    or session.get('server')!=initial.values.get('barbarian_server')):
                raise NotReady('Варвары: полевая армия закреплена за другой задачей или персонажем')
            if session.get('phase') not in ('position_intent','free_move_intent','combat_move_intent','intent','field','recall_intent','returning'):
                raise NotReady('Варвары: незавершённый переход армии требует подтверждения')
            if session.get('phase')=='position_intent':
                from .barbarian_position import PositionReceipt
                receipt=PositionReceipt(**session['position_intent'])
                if not receipt.matches(initial,recovering=True):
                    if len(rows)==1:
                        candidate=next(iter(rows.values()))
                        if (candidate.get('state')==2 and candidate.get('offensive') is False
                                and troop_heroes(candidate['troop'])==receipt.heroes
                                and fighting_composition(candidate['troop'].get('units'))==receipt.units):
                            return pending(initial)
                    raise NotReady('Цепочка: незавершённое бесплатное позиционирование требует подтверждения')
                candidate=next(iter(rows.values()))
                session.update(phase='field',troop_id=candidate['troopId'],char_id=candidate['charId'],
                    maximum=receipt.units,position_goal=receipt.goal);save(session)
            if session.get('phase')=='free_move_intent':
                from .barbarian_position import FieldPositionReceipt
                receipt=FieldPositionReceipt(**session['move_intent'])
                if receipt.matches(initial,recovering=True):
                    session.update(phase='field',position_goal=receipt.goal);session.pop('move_intent',None);save(session)
                else:
                    candidate=rows.get(str(receipt.troop_id))
                    if (table(candidate) and candidate.get('charId')==receipt.char_id and candidate.get('state')==2
                            and troop_heroes(candidate['troop'])==receipt.heroes
                            and candidate.get('offensive') is False
                            and fighting_composition(candidate['troop'].get('units'))==receipt.maximum):return pending(initial)
                    raise NotReady('Цепочка: неподтверждённое перемещение своей армии; повтор запрещён')
            if session.get('phase')=='combat_move_intent':
                from .barbarian_position import CombatMoveReceipt
                receipt=CombatMoveReceipt(**session['combat_move_intent'])
                if not receipt.matches(initial):
                    raise NotReady('Цепочка: незавершённый боевой отвод; повтор команды запрещён')
                session.update(phase='field',pull_goal=receipt.goal);session.pop('combat_move_intent',None);save(session)
            if session.get('phase')=='intent':
                intent=session['intent'];candidate=next(iter(rows.values())) if len(rows)==1 else None
                troop=candidate.get('troop') if table(candidate) else None
                maximum=intent.get('maximum',intent['units'])
                if (not table(candidate) or not table(troop) or troop.get('apTarget')!=intent['target']//100
                        or fighting_composition(troop.get('units'))!=maximum
                        or {str(h.get('label')):h.get('heroId') for h in troop.get('heros',{}).values()}!=intent['heroes']
                        or intent.get('troop_id',candidate['troopId'])!=candidate['troopId']
                        or intent.get('char_id',candidate.get('charId'))!=candidate.get('charId')):
                    raise NotReady('Варвары: незавершённая отправка требует подтверждения; повтор запрещён')
                session.update(phase='field',troop_id=candidate['troopId'],char_id=candidate['charId'],
                    maximum=maximum,count=session['count']+1)
                if session.get('chain_plan'):
                    from .barbarian_chain import ChainEvidence,ChainPlan
                    session['evidence']=ChainEvidence.start(ChainPlan(**session['chain_plan']),candidate['troopId'],
                        baseline=session.get('chain_baseline')).to_dict()
                save(session)
            if not rows:
                if session.get('phase') not in ('returning','recall_intent'):raise NotReady('Варвары: закреплённая армия исчезла до подтверждения возврата')
                totals=troop_totals(initial)
                if any(totals.get(unit,0)<count for unit,count in session['city_totals'].items()):
                    raise NotReady('Варвары: вернувшиеся здоровые и раненые войска не сходятся')
                if session.get('evidence'):
                    from .barbarian_chain import ChainEvidence
                    initial.values['barbarian_chain_free_defeated']=session.get('free_total',0)+len(ChainEvidence.from_dict(session['evidence']).free_defeated)
                initial.values['barbarian_paid_attacks']=session.get('count',0)
                save(None);initial.values['barbarian_session_completed']=True;return initial
            row=rows.get(str(session.get('troop_id')))
            if (len(rows)!=1 or not table(row) or row.get('charId')!=session.get('char_id')
                    or fighting_composition(row['troop'].get('units'))!=session.get('maximum')
                    or troop_heroes(row['troop'])!=session.get('heroes',session.get('intent',{}).get('heroes',{'1':3}))):
                raise NotReady('Варвары: идентичность закреплённой армии изменилась')
            if session.get('evidence'):
                from .barbarian_chain import ChainEvidence
                evidence=ChainEvidence.from_dict(session['evidence'])
                evidence.observe_state(initial,session['char_id'],session.get('baseline_reports',[]))
                session['evidence']=evidence.to_dict();save(session)
            if session.get('phase')=='recall_intent' and row.get('state')==2:
                goal=row.get('target')
                if table(goal) and goal.get('charId')==initial.values.get('barbarian_city') and goal.get('charType')==3:
                    session['phase']='returning';save(session)
            data=(initial.values.get('barbarian_hero') or {}).get('chain') or {}
            scene=data.get('scene') or {};own=scene.get(str(session['char_id'])) or {}
            in_combat=own.get('isFighting') is True
            if in_combat and session.get('pull_idle_since') is not None:
                session['pull_idle_since']=None;save(session)
            if session.get('phase')=='returning' or row.get('state')!=4 or row.get('isFightTarget') is not False or in_combat:
                plan=session.get('chain_plan') or {}
                if (self.task=='barbarian_chain' and troop_heroes(row['troop'])==self.options.heroes
                        and self.store is not None and plan.get('requires_pull') is True
                        and not session.get('pull_attempted') and in_combat and session.get('phase')=='field'):
                    from .barbarian_chain import ChainNotReady,pull_destination
                    from .barbarian_navigation import WorldNavigator
                    try:
                        neighbour=next((id for id in plan['neighbours'] if (scene.get(str(id)) or {}).get('isFighting') is False),None)
                        if neighbour is None:raise ChainNotReady('Цепочка: сосед уже вступил в бой или покинул сцену')
                        goal=pull_destination(initial,plan['target'],neighbour)
                        moved=WorldNavigator(device,observe,cancelled,clock,allowed).pull(goal,self.store)
                        save(self.store.preference(key));return pending(moved)
                    except ChainNotReady as error:
                        session.update(pull_attempted=True,pull_reason=str(error));save(session)
                return pending(initial)
            if session.get('pull_goal') and not in_combat:
                now=clock();since=session.get('pull_idle_since')
                if not number(since) or since>now:
                    session['pull_idle_since']=now;save(session);return pending(initial)
                if now-since<5:return pending(initial)
            units=field_composition(row['troop']['units'])
            if (session.get('phase')=='recall_intent' or troop_heroes(row['troop'])!=self.options.heroes
                    or session['count']>=self.options.max_battles or sum(units.values())*100<sum(session['maximum'].values())*self.options.min_health
                    or sum(units.values())<750 or initial.values.get('barbarian_ap',0)<self.options.reserve_ap+next_attack_cost(initial,row)):
                session['phase']='recall_intent';save(session)
                state=recall_army(device,observe,cancelled,clock,allowed)
                session['phase']='returning';save(session)
                return pending(state)
        elif rows:
            raise NotReady('Варвары: существующая армия не закреплена за этим фармом')
        elif initial.values.get('barbarian_ap',0)<self.options.reserve_ap+next_attack_cost(initial):
            return initial
        previous_session=deepcopy(session)
        def checkpoint(event,receipt,state):
            nonlocal session
            if event=='aborted':save(previous_session)
            elif event=='intent':
                if receipt.ap<self.options.reserve_ap+receipt.cost:raise NotReady('Варвары: цена выбранной пары затрагивает резерв AP')
                plan=guard(state) if self.task=='barbarian_chain' else None
                if session is None:
                    session={'task':self.task,'player':state.player_id,'server':state.values['barbarian_server'],
                        'count':0,'city_totals':troop_totals(state)}
                session.update(phase='intent',intent=asdict(receipt),heroes=receipt.heroes)
                if plan is not None:
                    from .barbarian_chain import ChainEvidence,native_baseline
                    if session.get('evidence'):
                        previous=ChainEvidence.from_dict(session['evidence'])
                        session['free_total']=session.get('free_total',0)+len(previous.free_defeated)
                    session.update(chain_plan=asdict(plan),evidence=None,
                        pull_attempted=False,pull_goal=None,pull_idle_since=None,
                        chain_baseline=native_baseline(state,self.options.max_level,plan.target),
                        baseline_reports=list(state.values['barbarian_hero']['chain'].get('reports') or {}))
                save(session)
            else:
                row=next(iter(own_armies(state).values()))
                session.update(phase='field',troop_id=row['troopId'],char_id=row['charId'],
                    maximum=fighting_composition(row['troop']['units']),count=session['count']+1)
                if session.get('chain_plan'):
                    from .barbarian_chain import ChainEvidence,ChainPlan
                    plan=ChainPlan(**session['chain_plan']);evidence=ChainEvidence.start(plan,row['troopId'],
                        baseline=session.get('chain_baseline'))
                    session['evidence']=evidence.to_dict()
                save(session)
        def guard(state):
            nonlocal session
            if self.task=='barbarians':return ordinary_target(state,expected_level=self.options.level)
            from .barbarian_chain import ChainNotReady,ChainPositioned,chain_approach,chain_plan,chain_target,patrol_plan,point
            from .barbarian_navigation import SURVEY_RADIUS,WorldNavigator
            target=chain_target(state,self.options);armies=own_armies(state)
            origin=next(iter(armies.values())).get('pos') if armies else state.values['barbarian_hero']['chain'].get('cityPos')
            if point(origin) and point(target.get('pos')):
                distance=math.dist([origin[k] for k in ('x','y')],[target['pos'][k] for k in ('x','y')])
                if distance>75:
                    if distance>SURVEY_RADIUS or self.store is None:
                        raise ChainNotReady('Цепочка: группа вне ограниченного маршрута подхода')
                    if session and session.get('position_target')==target['id'] and session.get('position_attempts',0)>=8:
                        raise ChainNotReady('Цепочка: предел бесплатных переходов к группе достигнут')
                    route_steps=session.get('route_steps',0) if session and session.get('position_target')==target['id'] else 0
                    goal={k:origin[k]+(target['pos'][k]-origin[k])*60/distance for k in ('x','y')}
                    moved=WorldNavigator(device,observe,cancelled,clock,allowed).position(goal,self.store,target['id'],options=self.options)
                    saved=self.store.preference(key);saved['route_steps']=route_steps+1;save(saved)
                    raise ChainPositioned(moved)
            try:return chain_plan(state,self.options)
            except ChainNotReady:
                try:approach=chain_approach(state,self.options)
                except ChainNotReady:return patrol_plan(state,self.options)
                if self.store is None:raise ChainNotReady('Цепочка: хранилище бесплатного подхода не подключено')
                if (session and session.get('position_target')==approach.plan.target
                        and session.get('position_attempts',0)>=2+session.get('route_steps',0)):
                    raise ChainNotReady('Цепочка: скопление переместилось; предел бесплатных подходов достигнут')
                moved=WorldNavigator(device,observe,cancelled,clock,allowed).position(approach.goal,self.store,approach.plan.target,
                    options=self.options)
                save(self.store.preference(key));raise ChainPositioned(moved)
        from .barbarian_chain import ChainPositioned,ChainNotReady
        from .barbarian_navigation import RESOURCE_HUD
        try:
            if (self.task=='barbarian_chain'
                    and not BattlePanel('MapUISelectTroops').matches(initial)
                    and not BattlePanel('SendTroopsMain').matches(initial) and (
                    CITY_HUD.matches(initial) or MAP_HUD.matches(initial) or RESOURCE_HUD.matches(initial)
                    or BattlePanel('AttackPopup').matches(initial))):
                from .barbarian_chain import point
                from .barbarian_navigation import WorldNavigator
                navigator=WorldNavigator(device,observe,cancelled,clock,allowed)
                current=observe();hero=current.values.get('barbarian_hero');camera=hero.get('chain',{}).get('camera') if table(hero) else None
                armies=own_armies(current)
                if armies:
                    army=next(iter(armies.values()))
                    if (CITY_HUD.matches(current) or not point(camera) or not point(army.get('pos'))
                            or sum((camera[k]-army['pos'][k])**2 for k in ('x','y'))>400):current=navigator.focus_army()
                else:current=navigator.world()
                survey_key='barbarian-survey:'+initial.instance_id
                survey=self.store.preference(survey_key) if self.store is not None else self.survey
                current,target,survey=navigator.survey(self.options,survey,
                    preferred=session.get('position_target') if session else None)
                self.survey=survey
                if self.store is not None:self.store.set_preference(survey_key,survey)
                if target is None:
                    current.values.update(barbarian_no_cluster=True,barbarian_chain_reason=survey['reason'],
                        barbarian_survey_region=survey['index'],barbarian_survey_pending=True)
                    return pending(current)
                navigator.select(target)
                guard(observe())
                navigator.attack_selector(target)
            return pending(attack_level_one(device,observe,cancelled,clock,allowed,checkpoint,
                guard,level=self.options.level,keep_camera=self.task=='barbarian_chain',options=self.options,
                map_only=self.task=='barbarian_chain'))
        except ChainPositioned as result:return pending(result.state)
        except ChainNotReady as error:
            if self.task!='barbarian_chain':raise
            from .barbarian_navigation import WorldNavigator
            state=observe();target=(state.values.get('barbarian_target') or {}).get('id')
            survey_key='barbarian-survey:'+initial.instance_id
            survey=self.store.preference(survey_key) if self.store is not None else self.survey
            if survey is not None and integer(target,1):
                survey['rejected']=list(dict.fromkeys([*survey.get('rejected',[]),target]))[-128:]
                self.survey=survey
                if self.store is not None:self.store.set_preference(survey_key,survey)
            state=WorldNavigator(device,observe,cancelled,clock,allowed).world()
            state.values.update(barbarian_no_cluster=True,barbarian_chain_reason=str(error))
            state.values['barbarian_survey_pending']=True
            return pending(state)


def barbarian_workflow(settings,*,verified=False,store=None,task='barbarians'):
    if task not in ('barbarians','barbarian_chain'):raise ValueError('Неизвестный режим фарма варваров')
    cycle=BarbarianCycle(BarbarianOptions.from_settings(settings),store,task)
    precondition=BARBARIANS.precondition;data_condition=BARBARIANS.data_condition
    if task=='barbarian_chain':
        from .barbarian_navigation import RESOURCE_VIEWS
        precondition=Condition(('views',),'subset',CITY_VIEWS+PANELS+RESOURCE_VIEWS+('Arraw','PopupMissionComplete'))
        data_condition=Condition(('views',),'subset',CITY_VIEWS+PANELS+RESOURCE_VIEWS)
    return Workflow(task,'1.1.12.20',960,540,(Procedure(cycle),),verified=verified,
        extra_paths={**FIELDS,'barbarian_hero':['@barbarian_hero',cycle.options.primary,cycle.options.deputy]},requires_city=False,data_timeout=10,
        precondition=precondition,data_condition=data_condition,wait_reason=BARBARIANS.wait_reason)
