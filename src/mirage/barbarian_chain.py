"""Chain candidates from native skill geometry; only observed combat is a result."""
from dataclasses import dataclass,replace
import math

from .barbarians import BattlePanel,field_composition, ordinary_target, own_armies
from .gather import number
from .commanders import selected_heroes
from .supply_boxes import integer, table
from .workflows import NotReady


class ChainNotReady(NotReady):
    pass


class ChainPositioned(Exception):
    def __init__(self,state):
        self.state=state


# Measured from this supported client's native tables (skill_Client.ID30 and
# skill_Area.AreaID6). Some non-tutorial accounts keep these visual tables lazy.
# This versioned planning geometry is not combat evidence; all hits/results
# still require exact live contacts/reports. Never substitute it for an unknown
# skill, an awakened hero, or a different installed game version.
SUN_TZU_GEOMETRY_VERSION='1.1.12.20'
SUN_TZU_CLIENT={'ID':30,'AREA_ID':6,'TARGET':2}
SUN_TZU_AREA={'AreaID':6,'AreaType':2,'Target':2,'Radius':9,'Angle':120,'MaxTar':3}
# Captured on the game thread during the exact Lohar/Zhuge23+25 battle.
# TARGET1/AreaType3 is the caster-centred circular skill, not Sun's cone.
ZHUGE_CLIENT={'ID':243,'AREA_ID':15,'TARGET':1}
ZHUGE_AREA={'AreaID':15,'AreaType':3,'Target':2,'Radius':10,'Angle':0,'MaxTar':5}


def point(value):
    return table(value) and all(number(value.get(axis)) for axis in ('x','y'))


def native_baseline(state,max_level,paid_target,*,min_level=1):
    """Idle ordinary NPCs observed before payment, including unpredicted patrols."""
    hero=state.values.get('barbarian_hero');data=hero.get('chain') if table(hero) else None
    scene=data.get('scene') if table(data) else None
    if not table(scene):return {}
    result={}
    for key,row in scene.items():
        npc=row.get('npcInfo') if table(row) else None;config=row.get('config') if table(row) else None
        if (not table(row) or not integer(row.get('id'),1) or str(row['id'])!=key or row['id']==paid_target
                or row.get('playerId')!=-2 or row.get('owner')!=-2 or row.get('isFighting') is not False
                or not table(npc) or not table(config) or npc.get('barbarianType')!=1 or npc.get('summonerId')!=0
                or any(npc.get(flag) is not False for flag in ('isFteVillage','isS10Special','isS19Special'))
                or not integer(npc.get('npcLevel'),min_level) or npc['npcLevel']>max_level
                or config.get('ID')!=npc.get('npcType') or config.get('Type')!=1
                or config.get('Level')!=npc['npcLevel'] or config.get('CostAP')!=50 or config.get('OnlyRally')!=0
                or config.get('KillReward')!=3000+npc['npcLevel']
                or not integer(row.get('hp'),1) or row.get('hpMax')!=row['hp']):continue
        result[key]=row['hp']
    return result


@dataclass(frozen=True)
class ChainPlan:
    target: int
    neighbours: tuple[int,...]
    expected_hp: dict
    origin: dict
    predicted_position: dict
    radius: float
    angle: float
    geometry_source: str = 'native'
    strength_source: str = 'native-counts'
    requires_pull: bool = False


def skill_geometry(state):
    primary=state.values.get('barbarian_hero');data=primary.get('chain') if table(primary) else None
    scene=data.get('scene') if table(data) else None
    if table(data) and table(scene) and table(data.get('reports')):
        for hero in (primary,primary.get('deputy')):
            if not table(hero) or hero.get('awaked') is not False:continue
            own=hero.get('chain');skill=hero.get('Skills',{}).get('1',{})
            if not table(own) or not table(skill) or not integer(skill.get('SkillId'),1) or not integer(skill.get('Level'),1):continue
            client=own.get('client');area=own.get('area');source='native'
            if state.game_version==SUN_TZU_GEOMETRY_VERSION and skill['Level']<=5 and (client is None or area is None):
                known=({3:(30,SUN_TZU_CLIENT,SUN_TZU_AREA),179:(243,ZHUGE_CLIENT,ZHUGE_AREA)}).get(hero.get('Id'))
                if known is not None and skill['SkillId']==known[0]:
                    _,known_client,known_area=known
                    # One visual table may load before the other. Fill only a
                    # missing row and only if every present planning field
                    # agrees with the independently captured native geometry.
                    if ((client is None or table(client) and all(client.get(k)==v for k,v in known_client.items()))
                            and (area is None or area==known_area)):
                        client=known_client if client is None else client
                        area=known_area if area is None else area
                        source='verified-native:'+SUN_TZU_GEOMETRY_VERSION+':'+str(known[0])+':'+str(known_area['AreaID'])
            circle=False
            # Native client rows contain additional visual/audio metadata.
            if table(client) and table(area) and hero.get('Id')==179 and skill['SkillId']==243:
                circle=all(client.get(k)==v for k,v in ZHUGE_CLIENT.items()) and area==ZHUGE_AREA
            if (not table(client) or not table(area) or client.get('ID')!=skill['SkillId']
                    or client.get('AREA_ID')!=area.get('AreaID') or not (circle or client.get('TARGET')==2 and area.get('AreaType')==2)
                    or area.get('Target')!=2
                    or not number(area.get('Radius')) or not 0<area['Radius']<=30
                    or not number(area.get('Angle')) or not (circle or 0<area['Angle']<=360) or not integer(area.get('MaxTar'),2)):continue
            return hero,skill,data,scene,area,source
    raise ChainNotReady('Цепочка: у выбранной пары площадной навык и его нативная область не подтверждены')


def combat_budget(state,options,hero,skill):
    armies=own_armies(state)
    if len(armies)>1:raise ChainNotReady('Цепочка: нужна одна подтверждённая своя армия')
    if armies:own_units=field_composition(next(iter(armies.values()))['troop'].get('units'))
    elif BattlePanel('SendTroopsMain').matches(state) and state.values.get('barbarian_form_SelHeroIds')==options.heroes:
        selected=state.values.get('barbarian_form_SelectUnits')
        own_units={key:n for key,n in selected.items() if integer(n,1) and key in ('1','2','3','13','14','115')} if table(selected) else None
    else:
        available={str(row.get('unitId')):row.get('unitCount') for row in state.values.get('troops',{}).values() if table(row)}
        ids=('13','14','115') if all(integer(available.get(key),1) for key in ('13','14','115')) else ('1','2','3')
        own_units={key:available[key] for key in ids if key in available}
    if not own_units or any(not integer(n) for n in own_units.values()):
        raise ChainNotReady('Цепочка: численности армии недостаточно для выбранного скопления')
    budget=sum(own_units.values());strength_source='native-counts'
    # The recorded83,383 balanced T4 / Sun Tzu20 Skill30-L5 battle defeated
    # 121,000 level18+17 troops with61,650 healthy survivors. The smaller1.30
    # allowance is a labelled planning heuristic, never combat evidence.
    maximum=(sum(row['maxCount'] for row in next(iter(armies.values()))['troop']['units'].values()) if armies else budget)
    if (state.game_version==SUN_TZU_GEOMETRY_VERSION and hero.get('Id')==3 and options.heroes=={'1':3}
            and hero.get('Level')==20 and skill.get('Level')==5
            and set(own_units)=={'13','14','115'} and all(budget*.2<=n<=budget*.5 for n in own_units.values())
            and budget*100>=maximum*80 and options.level<=20 and options.max_level<=20):
        budget=budget*130//100;strength_source='observed-combat:1.1.12.20:83383:121000:allowance1.30'
    primary=state.values.get('barbarian_hero') or {};deputy=primary.get('deputy') or {}
    # Observed82985 balanced T4 defeated185000 (23+25), with9413 healthy,
    # zero deaths and439 severe wounds. Use only1.50 of that measured2.23
    # ratio for this exact pair/skills, fresh formations and health threshold.
    if (state.game_version==SUN_TZU_GEOMETRY_VERSION and options.heroes=={'1':37,'2':179}
            and primary.get('Id')==37 and primary.get('Level')==60 and primary.get('awaked') is True
            and all(primary.get('Skills',{}).get('1',{}).get(k)==v for k,v in {'SkillId':56,'Level':5}.items())
            and not primary.get('Skills',{}).get('1',{}).get('SkillTrans')
            and deputy.get('Id')==179 and deputy.get('Level')==40 and deputy.get('awaked') is False
            and deputy.get('Skills',{}).get('1',{}).get('SkillId')==243
            and deputy.get('Skills',{}).get('1',{}).get('Level') in (4,5)
            and not deputy.get('Skills',{}).get('1',{}).get('SkillTrans')
            and set(own_units)=={'13','14','115'} and all(budget*.2<=n<=budget*.5 for n in own_units.values())
            and budget>=80000 and budget*100>=maximum*80 and options.min_health<=20):
        budget=budget*150//100;strength_source='observed-combat:1.1.12.20:82985:185000:37-179:allowance1.50'
    return budget,strength_source


def chain_target(state,options):
    try:target=ordinary_target(state)
    except NotReady as error:raise ChainNotReady(str(error)) from error
    if not options.level<=target['npcInfo']['npcLevel']<=options.max_level:
        raise ChainNotReady('Цепочка: полевая цель вне настроенного диапазона уровней')
    return target


def chain_plan(state,options):
    target=chain_target(state,options)
    hero,skill,data,scene,area,geometry_source=skill_geometry(state)
    armies=own_armies(state)
    origin=next(iter(armies.values())).get('pos') if len(armies)==1 else data.get('cityPos')
    pos=target.get('pos')
    if len(armies)>1 or not point(origin) or not point(pos):raise ChainNotReady('Цепочка: положение своей армии и цели не прочитано')
    dx,dy=pos['x']-origin['x'],pos['y']-origin['y'];distance=math.hypot(dx,dy)
    if distance<.1:raise ChainNotReady('Цепочка: направление подхода не определено')
    direction=(dx/distance,dy/distance)
    # A measured ordinary approach ends roughly three world units from the NPC.
    # This is a candidate estimate; it never proves a free hit or a victory.
    standoff=min(3,distance)
    predicted={axis:pos[axis]-direction[i]*standoff for i,axis in enumerate(('x','y'))}
    candidates=[];circle=area['AreaType']==3;cosine=math.cos(math.radians(area['Angle']/2))
    for key,row in scene.items():
        npc=row.get('npcInfo') if table(row) else None
        config=row.get('config') if table(row) else None
        if (not table(row) or not integer(row.get('id'),1) or str(row['id'])!=key or row['id']==target['id']
                or row.get('playerId')!=-2 or row.get('owner')!=-2 or row.get('isFighting') is not False or not table(npc)
                or npc.get('barbarianType')!=1 or npc.get('summonerId')!=0
                or not table(config) or config.get('ID')!=npc.get('npcType') or config.get('Type')!=1
                or config.get('Level')!=npc.get('npcLevel') or config.get('CostAP')!=50 or config.get('OnlyRally')!=0
                or any(npc.get(flag) is not False for flag in ('isFteVillage','isS10Special','isS19Special'))
                or not integer(npc.get('npcLevel'),options.level) or npc['npcLevel']>options.max_level
                or not integer(row.get('hp'),1) or row.get('hpMax')!=row['hp'] or not point(row.get('pos'))):continue
        nx,ny=row['pos']['x']-predicted['x'],row['pos']['y']-predicted['y'];length=math.hypot(nx,ny)
        if not .1<length<=area['Radius']-.5:continue
        if not circle and (nx*direction[0]+ny*direction[1])/length<cosine+.03:continue
        candidates.append((length,row['id'],row['hp']))
    candidates.sort()
    if not candidates:raise ChainNotReady('Цепочка: рядом нет свободных варваров в области навыка')
    budget,strength_source=combat_budget(state,options,hero,skill)
    remaining=budget-target['hp'];selected=[]
    for candidate in candidates:
        if candidate[2]<=remaining and len(selected)<area['MaxTar']-1:
            selected.append(candidate);remaining-=candidate[2]
    if not selected:raise ChainNotReady('Цепочка: численности армии недостаточно для выбранного скопления')
    candidates=selected
    expected={str(target['id']):target['hp'],**{str(id):hp for _,id,hp in candidates}}
    return ChainPlan(target['id'],tuple(id for _,id,_ in candidates),expected,dict(origin),predicted,
        area['Radius'],360 if circle else area['Angle'],geometry_source,strength_source)


@dataclass(frozen=True)
class ChainApproach:
    goal: dict
    plan: ChainPlan


def chain_approach(state,options):
    """Find a free stand position; payment still needs a fresh normal plan."""
    target=chain_target(state,options);armies=own_armies(state)
    hero=state.values.get('barbarian_hero');data=hero.get('chain') if table(hero) else None
    origin=next(iter(armies.values())).get('pos') if len(armies)==1 else data.get('cityPos') if table(data) else None
    if len(armies)>1 or not point(origin) or not point(target.get('pos')):
        raise ChainNotReady('Цепочка: положение своей армии для подхода не прочитано')
    candidates=[]
    for degrees in range(0,360,15):
        angle=math.radians(degrees);goal={'x':target['pos']['x']+6*math.cos(angle),'y':target['pos']['y']+6*math.sin(angle)}
        distance=math.dist([origin[k] for k in ('x','y')],[goal[k] for k in ('x','y')])
        if not .75<distance<=90:continue
        values=dict(state.values)
        if armies:
            key,row=next(iter(armies.items()));values['barbarian_marches']={key:{**row,'pos':goal}}
        else:values['barbarian_hero']={**hero,'chain':{**data,'cityPos':goal}}
        try:plan=chain_plan(replace(state,values=values),options)
        except ChainNotReady:continue
        candidates.append((distance,ChainApproach(goal,plan)))
    if not candidates:raise ChainNotReady('Цепочка: рядом нет скопления с подтверждённым бесплатным подходом')
    return min(candidates,key=lambda item:item[0])[1]


def pull_destination(state,target_id,neighbour_id):
    _,_,_,scene,area,_=skill_geometry(state)
    target=scene.get(str(target_id));neighbour=scene.get(str(neighbour_id))
    if not table(target) or not table(neighbour) or not point(target.get('pos')) or not point(neighbour.get('pos')):
        raise ChainNotReady('Цепочка: обе цели отвода больше не видны')
    t=target['pos'];n=neighbour['pos'];distance=math.dist([t[k] for k in ('x','y')],[n[k] for k in ('x','y')])
    if not 4<distance<=25:raise ChainNotReady('Цепочка: сосед покинул ограниченную область отвода')
    radius=min(7.5,area['Radius']-1.5);candidates=[]
    if radius<=.5:raise ChainNotReady('Цепочка: область навыка слишком мала для отвода')
    for degrees in range(0,360,10):
        angle=math.radians(degrees);goal={'x':n['x']+radius*math.cos(angle),'y':n['y']+radius*math.sin(angle)}
        tx,ty=t['x']-goal['x'],t['y']-goal['y'];nx,ny=n['x']-goal['x'],n['y']-goal['y'];length=math.hypot(tx,ty)
        # A recorded longer pull let the paid NPC break contact and fully heal.
        # Keep the destination inside a conservative10-unit pursuit radius;
        # an unavailable short pull leaves the current paid fight untouched.
        if (0<length<=10 and (area['AreaType']==3
                or (tx*nx+ty*ny)/(length*radius)>=math.cos(math.radians(max(1,area['Angle']/2-5))))):
            candidates.append((length,goal))
    if not candidates:raise ChainNotReady('Цепочка: точка отвода внутри сектора не найдена')
    return min(candidates,key=lambda item:item[0])[1]


def patrol_plan(state,options):
    """A bounded pull opportunity, not a prediction of a free hit."""
    target=chain_target(state,options)
    hero,skill,data,scene,area,source=skill_geometry(state);budget,strength=combat_budget(state,options,hero,skill)
    armies=own_armies(state);origin=next(iter(armies.values())).get('pos') if armies else data.get('cityPos')
    if not point(origin):raise ChainNotReady('Цепочка: положение своей армии не подтверждено')
    if not point(target.get('pos')) or math.dist([origin[k] for k in ('x','y')],[target['pos'][k] for k in ('x','y')])>90:
        raise ChainNotReady('Цепочка: платная цель вне ограниченной области подхода')
    candidates=[]
    for key,hp in native_baseline(state,options.max_level,target['id'],min_level=options.level).items():
        if target['hp']+hp>budget:continue
        try:goal=pull_destination(state,target['id'],int(key))
        except ChainNotReady:continue
        candidates.append((math.dist([scene[key]['pos'][k] for k in ('x','y')],[target['pos'][k] for k in ('x','y')]),int(key),hp,goal))
    if not candidates:raise ChainNotReady('Цепочка: нет подходящего соседа для ограниченного бесплатного отвода')
    _,id,hp,goal=min(candidates,key=lambda item:item[0])
    return ChainPlan(target['id'],(id,),{str(target['id']):target['hp'],str(id):hp},dict(origin),goal,
        area['Radius'],360 if area['AreaType']==3 else area['Angle'],source,strength,True)


def scene_primary(state,options,preferred=None,*,rejected=(),max_distance=90):
    armies=own_armies(state)
    if len(armies)>1:return None
    try:
        hero,skill,data,scene,area,_=skill_geometry(state)
        budget,_=combat_budget(state,options,hero,skill)
    except ChainNotReady:return None
    origin=next(iter(armies.values())).get('pos') if armies else data.get('cityPos')
    if not point(origin):return None
    baseline=native_baseline(state,options.max_level,-1,min_level=options.level);candidates=[]
    for key,hp in baseline.items():
        row=scene[key]
        if int(key) in rejected or not point(row.get('pos')):continue
        distance=math.dist([origin[k] for k in ('x','y')],[row['pos'][k] for k in ('x','y')])
        if distance>max_distance:continue
        neighbours=sorted((other_hp for other,other_hp in baseline.items() if other!=key
            and point(scene[other].get('pos')) and math.dist([row['pos'][k] for k in ('x','y')],
                [scene[other]['pos'][k] for k in ('x','y')])<=25))
        remaining=budget-hp;count=0
        for other_hp in neighbours:
            if other_hp<=remaining and count<area['MaxTar']-1:remaining-=other_hp;count+=1
        if count:candidates.append((-count,int(key)!=preferred,distance,int(key)))
    return min(candidates)[-1] if candidates else None


@dataclass
class ChainEvidence:
    """Count extra enemies only with a proven own-army contact and result."""
    paid_target: int
    troop_id: int
    ap_target: int
    candidates: frozenset[int]
    engaged: set[int]
    defeated: set[int]
    expected_hp: dict
    unexpected_paid: bool = False

    @classmethod
    def start(cls,plan,troop_id,*,baseline=None):
        # Patrols can enter the cone after the initial prediction. Their own
        # complete report can prove a free victory, provided their untouched
        # identity/HP were captured before this paid attack.
        baseline=baseline or {}
        expected={**baseline,**plan.expected_hp}
        candidates=frozenset(plan.neighbours)|frozenset(int(key) for key in baseline if int(key)!=plan.target)
        return cls(plan.target,troop_id,plan.target//100,candidates,set(),set(),expected)

    def to_dict(self):
        return {'paid_target':self.paid_target,'troop_id':self.troop_id,'ap_target':self.ap_target,
            'candidates':sorted(self.candidates),'engaged':sorted(self.engaged),'defeated':sorted(self.defeated),
            'expected_hp':dict(self.expected_hp),'unexpected_paid':self.unexpected_paid}

    @classmethod
    def from_dict(cls,value):
        return cls(value['paid_target'],value['troop_id'],value['ap_target'],frozenset(value['candidates']),
            set(value['engaged']),set(value['defeated']),dict(value['expected_hp']),value['unexpected_paid'])

    def observe_state(self,state,char_id,baseline_reports):
        armies=own_armies(state);army=armies.get(str(self.troop_id))
        if not table(army) or army.get('charId')!=char_id:return
        hero=state.values.get('barbarian_hero');data=hero.get('chain') if table(hero) else None
        if not table(data):return
        contacts=[];results=[];scene=data.get('scene')
        if table(scene):
            own=scene.get(str(char_id))
            for id in self.candidates:
                row=scene.get(str(id))
                if not table(row) or row.get('owner')!=-2 or row.get('isFighting') is not True:continue
                attackers=row.get('attackers')
                if (row.get('attackTarget')==char_id or table(attackers) and any(table(a) and a.get('id')==char_id for a in attackers.values())
                        or table(own) and own.get('isFighting') is True and own.get('attackTarget')==id):
                    contacts.append((id,self.troop_id))
        reports=data.get('reports')
        if table(reports):
            for key,report in reports.items():
                if (key in baseline_reports or not table(report) or report.get('player')!=state.player_id
                        or report.get('server')!=state.values.get('barbarian_server') or report.get('charId')!=char_id//100
                        or report.get('troopId')!=self.troop_id or report.get('omitted') is not False
                        or not integer(report.get('start'),1) or not integer(report.get('end'),report['start'])
                        or not integer(report.get('battle'),1) or not table(report.get('attacks'))):continue
                for attack in report['attacks'].values():
                    if (not table(attack) or not integer(attack.get('id'),1) or attack['id']*100 not in self.candidates
                            or (attack.get('player'),attack.get('type'),attack.get('barbarianType'))!=(-2,1,1)
                            or not table(attack.get('Kill')) or not table(attack.get('Damage'))):continue
                    id=attack['id']*100;kill=attack['Kill'];damage=attack['Damage']
                    if (kill.get('Cnt')==0 and integer(kill.get('Max'),1) and kill.get('Max')==self.expected_hp.get(str(id))
                            and kill.get('Death')==kill['Max'] and integer(damage.get('Cnt'),1) and damage.get('Death')==0):
                        contacts.append((id,self.troop_id));results.append((id,self.troop_id,True))
        self.observe(troop_id=self.troop_id,ap_target=army['troop'].get('apTarget'),contacts=contacts,results=results)

    def observe(self,*,troop_id,ap_target,contacts,results):
        if troop_id!=self.troop_id:return
        if ap_target!=self.ap_target:self.unexpected_paid=True
        # contacts/results are normalized, attributable records, never just an
        # enemy disappearing from the loaded map or somebody else's hp delta.
        for enemy,own_troop in contacts:
            if own_troop==self.troop_id and enemy in self.candidates:self.engaged.add(enemy)
        for enemy,own_troop,victory in results:
            if victory is True and own_troop==self.troop_id and enemy in self.engaged:self.defeated.add(enemy)

    @property
    def free_defeated(self):return frozenset() if self.unexpected_paid else frozenset(self.defeated)
