"""Ordinary academy research: configuration and exact queue receipts."""
from dataclasses import dataclass, replace

from .model import RESEARCH_TYPES, ResearchOptions
from .supply_boxes import balances, inventory, integer, table
from .navigation import navigate_city
from .research_navigation import open_node
from .resource_packs import FIELDS as PACK_FIELDS, replenish
from .workflows import (CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, HUD_MENU,
    NotReady, Procedure, QUEUE_CLOSE, SELECTION_CLEAR, Tap, Workflow, WorkflowError)


TREE_VIEWS=('ReseachPage_Economy','ReseachPage_Military')
FIELDS={**PACK_FIELDS,'research_data':['TechniqueData'],'research_form':['@research_form'],
    'research_ui':['@research_ui'],'supply_inventory':['@item_counts'],
    'city_camera':['@city_camera'],'building_menu':['@building_menu']}


def nodes(rows):
    if not table(rows):raise NotReady('Исследования: список технологий неполон')
    out={}
    for row in rows.values():
        if (not table(row) or not integer(row.get('Type'),1) or not integer(row.get('Level'))
                or row['Type'] in out):raise NotReady('Исследования: неоднозначный тип или уровень технологии')
        out[row['Type']]=row
    return out


def idle(state):
    r=state.values.get('research_data')
    if (not table(r) or not integer(r.get('ProcessSlotCount'),1)
            or not table(r.get('ResearchProcessNode')) or not table(r.get('ResearchFinishNode'))):
        raise NotReady('Исследования: состояние очереди не подтверждено')
    return not r['ResearchProcessNode'] and not r['ResearchFinishNode']


def research_goals(state,options):
    plan=state.values.get('research_plan')
    if not table(plan) or plan.get('ready') is not True or not table(plan.get('rows')):
        raise NotReady('Исследования: каталог предпосылок не прочитан')
    levels={kind:row['Level'] for kind,row in nodes(state.values['research_data'].get('Datas')).items()}
    def visit(kind,required,stack):
        current=levels.get(kind,0)
        if current>=required:return None
        if kind in stack:raise NotReady('Исследования: цикл предпосылок технологий')
        cfg=plan['rows'].get(str(kind))
        if cfg is None:return None  # The actual native maximum may be below the user's common target.
        if not table(cfg) or cfg.get('Type')!=kind or cfg.get('Level')!=current+1:
            raise NotReady('Исследования: следующий уровень предпосылки не подтверждён')
        for n in range(1,5):
            pre,level=cfg.get('PreType'+str(n)),cfg.get('PreLevel'+str(n))
            if not integer(pre) or not integer(level):raise NotReady('Исследования: неполные предпосылки')
            if pre and levels.get(pre,0)<level:return visit(pre,level,stack+(kind,))
        return cfg
    seen=set()
    for kind in options.ordered_types():
        cfg=visit(kind,options.max_level,())
        if cfg is not None and cfg['Type'] not in seen:
            seen.add(cfg['Type']);yield cfg


def research_goal(state,options):
    return next(research_goals(state,options),None)


def candidate(state,options,*,include_shortfall=False):
    if not options.types:return None
    if not idle(state):return None
    plan=state.values.get('research_plan');r=state.values['research_data']
    if not table(plan) or plan.get('ready') is not True or not table(plan.get('rows')):
        raise NotReady('Исследования: обычные конфигурации не прочитаны')
    owned=nodes(r.get('Datas'));levels={kind:row['Level'] for kind,row in owned.items()}
    buildings=state.values.get('buildings')
    if not table(buildings):raise NotReady('Исследования: академия не прочитана')
    academy=max((row.get('lv',0) for row in buildings.values() if table(row) and row.get('type')==13 and row.get('state')==1),default=0)
    money=balances(state)
    kinds=tuple(goal['Type'] for goal in research_goals(state,options)) if options.auto_prerequisites else options.ordered_types()
    for kind in kinds:
        level=levels.get(kind,0)+1
        if level>options.max_level and not options.auto_prerequisites:continue
        cfg=plan['rows'].get(str(kind))
        if (not table(cfg) or cfg.get('Type')!=kind or cfg.get('Level')!=level or cfg.get('ID')!=kind*100+level
                or not integer(cfg.get('BuildLevel'),1) or academy<cfg['BuildLevel']):continue
        if any(not integer(cfg.get(key)) or (money[str(i)]-cfg[key]<options.reserves[i-1]
                and not (include_shortfall and i in (1,2)))
                for i,key in enumerate(('Food','Wood','Stone','Coin'),1)):continue
        prerequisites=True
        for n in range(1,5):
            pre,required=cfg.get('PreType'+str(n)),cfg.get('PreLevel'+str(n))
            if not integer(pre) or not integer(required) or pre and levels.get(pre,0)<required:prerequisites=False;break
        if prerequisites:return cfg
    return None


@dataclass(frozen=True)
class ResearchReceipt:
    kind: int
    level: int
    money: dict
    items: dict
    levels: dict
    updates: int

    @classmethod
    def capture(cls,state,options):
        cfg=candidate(state,options);f=state.values.get('research_form');r=state.values['research_data']
        if (cfg is None or not table(f) or f.get('visible') is not True or f.get('type')!=cfg['Type']
                or f.get('level')!=cfg['Level'] or f.get('current')!=cfg['Level']-1
                or not integer(f.get('max'),1) or f['max']<cfg['Level']
                or not table(f.get('config')) or any(f['config'].get(k)!=cfg.get(k) for k in (
                    'ID','Type','Level','BuildLevel','Food','Wood','Stone','Coin',
                    *('PreType'+str(i) for i in range(1,5)),*('PreLevel'+str(i) for i in range(1,5))))
                or not integer(r.get('DatasUpdatedCount'))):
            raise NotReady('Исследования: обычная форма старта не подтверждена')
        expected={str(i):cfg[key] for i,key in enumerate(('Food','Wood','Stone','Coin'),1) if cfg[key]}
        if f.get('cost')!=expected:raise NotReady('Исследования: стоимость формы отличается от конфигурации')
        money=balances(state)
        for key,value in expected.items():money[key]-=value
        levels={kind:row['Level'] for kind,row in nodes(r['Datas']).items()}
        return cls(cfg['Type'],cfg['Level'],money,inventory(state),levels,r['DatasUpdatedCount'])

    def matches(self,state):
        r=state.values.get('research_data')
        if (not table(r) or not integer(r.get('DatasUpdatedCount')) or r['DatasUpdatedCount']<=self.updates
                or balances(state)!=self.money or inventory(state)!=self.items):return False
        try:owned=nodes(r.get('Datas'));process=nodes(r.get('ResearchProcessNode'));finished=nodes(r.get('ResearchFinishNode'))
        except NotReady:return False
        actual={kind:row['Level'] for kind,row in owned.items()}
        if not process and not finished:return actual=={**self.levels,self.kind:self.level}
        if set(process)!={self.kind} or finished:return False
        if actual!={**self.levels,self.kind:self.level-1}:return False
        row=process[self.kind]
        return (row.get('Level')==self.level-1 and row.get('Id')==str(self.kind)
            and integer(row.get('EndTime'),1) and row['EndTime']>state.values.get('server_time',float('inf'))
            and integer(row.get('TotalTime'),1))


@dataclass(frozen=True)
class ResearchCollectReceipt:
    kind: int
    levels: dict
    money: dict
    items: dict
    updates: int

    @classmethod
    def capture(cls,state,options):
        data=state.values.get('research_data')
        if not table(data) or not table(data.get('ResearchProcessNode')) or data['ResearchProcessNode']:
            raise NotReady('Исследования: получение при активной очереди не подтверждено')
        finished=nodes(data.get('ResearchFinishNode'));owned=nodes(data.get('Datas'))
        if len(finished)!=1:raise NotReady('Исследования: нужна одна естественно завершённая технология')
        kind,row=next(iter(finished.items()))
        if ((kind not in options.types and not (options.auto_prerequisites and kind in RESEARCH_TYPES))
                or row.get('Id')!=str(kind) or kind not in owned
                or owned[kind].get('Level')!=row.get('Level') or not integer(row.get('EndTime'),1)
                or row['EndTime']>state.values.get('server_time',0) or not integer(data.get('DatasUpdatedCount'))):
            raise NotReady('Исследования: естественное завершение выбранной технологии не подтверждено')
        levels={kind:r['Level'] for kind,r in owned.items()};levels[kind]+=1
        return cls(kind,levels,balances(state),inventory(state),data['DatasUpdatedCount'])

    def matches(self,state):
        data=state.values.get('research_data')
        if (not table(data) or data.get('ResearchProcessNode')!={} or data.get('ResearchFinishNode')!={}
                or not integer(data.get('DatasUpdatedCount')) or data['DatasUpdatedCount']<=self.updates):return False
        try:owned=nodes(data.get('Datas'))
        except NotReady:return False
        return ({kind:r['Level'] for kind,r in owned.items()}==self.levels
            and balances(state)==self.money and inventory(state)==self.items)


def screen(state,*extra):
    views=state.values.get('views',{})
    return (state.values.get('in_city') is True and set(views)<=set(CITY_VIEWS+TREE_VIEWS+('CommonBackground',)+extra))


class ResearchPanel:
    def matches(self,state):
        return state.values.get('research_form',{}).get('visible') is True and screen(state,'ResearchRequestPage2','QuestGuide')


class ResearchTree:
    def matches(self,state):
        return state.values.get('research_ui',{}).get('tree') in TREE_VIEWS and screen(state,'QuestGuide')


@dataclass(frozen=True)
class ResearchCycle:
    options: ResearchOptions

    def __call__(self,device,observe,cancelled,clock,allowed):
        options=self.options;initial=observe();observed_kind=None
        if options.priority_mode=='balanced':
            data=initial.values.get('research_data',{})
            for field in ('ResearchProcessNode','ResearchFinishNode'):
                rows=data.get(field)
                if table(rows) and len(rows)==1:
                    row=next(iter(rows.values()))
                    if table(row) and row.get('Type') in RESEARCH_TYPES:observed_kind=row['Type']
            if observed_kind is not None:
                options=replace(options,next_branch='military' if observed_kind<200 else 'economy')
        state=replace(self,options=options)._run(device,observe,cancelled,clock,allowed)
        kind=state.values.get('research_started',observed_kind)
        if options.priority_mode=='balanced' and kind in RESEARCH_TYPES:
            state.values['research_next_branch']='military' if kind<200 else 'economy'
        return state

    def _run(self,device,observe,cancelled,clock,allowed):
        initial=observe()
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Исследования отменены')
        def execute(steps):
            return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
                Workflow('research_transition','1.1.12.20',960,540,steps,verified=True,data_timeout=10),cancelled,
                instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        def clean():
            execute((Tap(818,62,ResearchPanel(),Condition(('research_form','visible'),'eq',False),
                hold_ms=100,settle=.4,when=Condition(('research_form','visible'),'eq',True)),
                Tap(836,53,ResearchTree(),Condition(('research_ui','tree'),'eq',None),
                    hold_ms=100,settle=.4,when=ResearchTree())))
            return execute((*SELECTION_CLEAR,Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,
                when=Condition(('hud_menu',),'eq',True),settle=.3)))
        def enter_tree():
            state=execute((QUEUE_CLOSE,*SELECTION_CLEAR,Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,
                when=Condition(('hud_menu',),'eq',True),settle=.3)))
            state=navigate_city(device,observe,cancelled,clock,13,allowed,select=False)
            proof=state.values.get('city_navigation_target')
            if not table(proof):raise NotReady('Исследования: положение академии не подтверждено')
            state=execute((Tap(*proof['point'],CITY_HUD,Condition(('city_selection',),'eq',proof['id']),hold_ms=100,settle=.4),))
            selected=state.values.get('building_menu',{}).get('selected')
            if (not table(selected) or selected.get('id')!=proof['id'] or selected.get('type')!=13
                    or set(selected.get('buttons',[]))!={'btn_CityPopUpUpgrade','btn_CityPopUpInfo','btn_FunctionCampus'}):
                raise NotReady('Исследования: меню академии не подтверждено')
            x,y=proof['point']
            return execute((Tap(x+100,y+90,Condition(('city_selection',),'eq',proof['id']),ResearchTree(),hold_ms=100,settle=.4),))
        def develop_academy(level):
            from .building_upgrade import UpgradeCycle
            from .model import BuildingOptions
            if not integer(level,1) or level>24:raise NotReady('Исследования: академия25 требует отдельной проверки предметных условий')
            before=clean()
            previous={k:(r.get('lv'),r.get('state')) for k,r in before.values.get('buildings',{}).items()}
            options=BuildingOptions(max_level=level,reserves=self.options.reserves,types=(13,),
                use_resource_packs=self.options.use_resource_packs,auto_prerequisites=True,create_missing=True)
            state=UpgradeCycle(options)(device,observe,cancelled,clock,allowed)
            current={k:(r.get('lv'),r.get('state')) for k,r in state.values.get('buildings',{}).items()}
            if current!=previous or any(table(r) and r.get('state') in (2,3)
                    for r in state.values.get('buildings',{}).values()):
                state.values['research_prerequisite_pending']=True
            return state
        state=initial
        if self.options.types and any(table(r) and r.get('type')==13 and r.get('state') in (2,3)
                for r in state.values.get('buildings',{}).values()):
            if self.options.auto_prerequisites:state.values['research_prerequisite_pending']=True
            return state
        finished=state.values.get('research_data',{}).get('ResearchFinishNode')
        if self.options.types and table(finished) and finished:
            receipt=ResearchCollectReceipt.capture(state,self.options)
            state=execute((QUEUE_CLOSE,*SELECTION_CLEAR,Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,
                when=Condition(('hud_menu',),'eq',True),settle=.3)))
            state=navigate_city(device,observe,cancelled,clock,13,allowed,select=False)
            proof=state.values.get('city_navigation_target')
            if not table(proof):raise NotReady('Исследования: положение академии не подтверждено')
            receipt=ResearchCollectReceipt.capture(state,self.options)
            permit();device.tap(*proof['point'],hold_ms=100);deadline=clock()+20
            while True:
                permit();state=observe()
                if receipt.matches(state):break
                if clock()>=deadline:raise WorkflowError('Исследования: получение уровня не подтверждено; повтор запрещён')
                if cancelled.wait(.1):raise Cancelled('Исследования отменены')
            state=clean()
        if self.options.types and idle(state):
            academy=max((r.get('lv',0) for r in state.values.get('buildings',{}).values()
                if table(r) and r.get('type')==13 and r.get('state')==1),default=0)
            if not academy and self.options.auto_prerequisites:return develop_academy(1)
            if state.values.get('research_plan',{}).get('ready') is not True and academy:
                if not ResearchTree().matches(state):state=enter_tree()
                deadline=clock()+10
                while state.values.get('research_plan',{}).get('ready') is not True:
                    permit()
                    if clock()>=deadline:raise NotReady('Исследования: каталог ещё загружается')
                    if cancelled.wait(.1):raise Cancelled('Исследования отменены')
                    state=observe()
            if self.options.auto_prerequisites:
                goal=research_goal(state,self.options)
                if goal is not None and integer(goal.get('BuildLevel'),1) and academy<goal['BuildLevel']:
                    return develop_academy(goal['BuildLevel'])
        cfg=candidate(state,self.options)
        if cfg is None and self.options.use_resource_packs:
            pending=candidate(state,self.options,include_shortfall=True)
            if pending is not None:
                state=clean()
                minimum={str(i):pending[name]+self.options.reserves[i-1] for i,name in ((1,'Food'),(2,'Wood'))}
                state=replenish(device,observe,cancelled,clock,allowed,minimum)
                cfg=candidate(state,self.options)
        if cfg is None:return clean() if ResearchPanel().matches(state) or ResearchTree().matches(state) else state
        if ResearchPanel().matches(state) and state.values['research_form'].get('type')!=cfg['Type']:
            state=execute((Tap(818,62,ResearchPanel(),ResearchTree(),hold_ms=100,settle=.3),))
        if not ResearchPanel().matches(state):
            if not ResearchTree().matches(state):state=enter_tree()
            state=open_node(cfg['Type'],device,observe,execute,permit,ResearchTree(),ResearchPanel(),cancelled)
        receipt=ResearchReceipt.capture(state,self.options)
        permit();device.tap(737,400,hold_ms=100)
        deadline=clock()+20
        while True:
            permit();state=observe()
            if receipt.matches(state):break
            if clock()>=deadline:raise WorkflowError('Исследования: точный запуск не подтверждён; повтор запрещён')
            if cancelled.wait(.1):raise Cancelled('Исследования отменены')
        state=clean();state.values['research_started']=receipt.kind
        return state


def research_workflow(settings,*,verified=False):
    options=ResearchOptions.from_settings(settings)
    paths=FIELDS;types=options.types
    if options.auto_prerequisites:
        from .building_upgrade import FIELDS as BUILDING_FIELDS
        from .construction import FIELDS as CONSTRUCTION_FIELDS
        paths={**BUILDING_FIELDS,**CONSTRUCTION_FIELDS,**FIELDS};types=RESEARCH_TYPES
    return Workflow('research','1.1.12.20',960,540,(Procedure(ResearchCycle(options)),),verified=verified,
        extra_paths={**paths,'research_plan':['@research_plan',','.join(map(str,types))]},data_timeout=10,
        wait_reason='Ожидание свободной академии, предпосылок и ресурсов обычного исследования')
