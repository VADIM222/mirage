"""Free daily VIP0 rewards with native point/loot receipts; retain the verified VIP12 path."""
from dataclasses import dataclass

from .scout_fog import money
from .supply_boxes import integer, inventory, table
from .workflows import (All, AnyOf, CITY_HUD, CITY_SCENE, CITY_VIEWS, Condition, Engine,
    NotReady, Procedure, QUEUE_CLOSE, QUEUE_HIDDEN, QUEUE_KNOWN, Tap, VIP_REWARD, Workflow, WorkflowError)


FIELDS={'supply_inventory':['@item_counts'],'vip_experience':['VipData','VipExp'],
    'vip_login_days':['VipData','ContinuousLogin'],'vip_daily_points':['@vip_daily_points'],
    'vip_daily_config':['@vip_config'],'vip_daily_loot':['@reward_rows',9001]}
PANEL=All((Condition(('vip_visible',),'eq',True),Condition(('vip_level',),'eq',0),
    Condition(('vip_shown_level',),'eq',0),Condition(('vip_box_detail',),'eq',False),
    Condition(('vip_opening_box',),'eq',False),
    Condition(('views',),'subset',CITY_VIEWS+('VIPMainPage','CommonBackground'))))
NOTICE=All((Condition(('vip_visible',),'eq',True),Condition(('vip_notice_visible',),'eq',True),
    Condition(('views',),'subset',CITY_VIEWS+('VIPMainPage','CommonBackground','VIPNotice'))))
REWARD=All((Condition(('vip_visible',),'eq',True),Condition(('reward_popup_visible',),'eq',True),
    Condition(('views',),'subset',CITY_VIEWS+('VIPMainPage','CommonBackground','RoutineRewardsCollect'))))


@dataclass(frozen=True)
class PointReceipt:
    resources: dict
    items: dict
    experience: int
    days: int
    box_available: bool

    @classmethod
    def capture(cls,state):
        v=state.values;row=v.get('vip_daily_points');days=v.get('vip_login_days');experience=v.get('vip_experience')
        if (not PANEL.matches(state) or v.get('vip_points_available') is not True or not integer(experience)
                or not integer(days,1) or not table(row) or row.get('Day')!=days+1
                or not integer(row.get('Point'),1) or type(v.get('vip_box_available')) is not bool):
            raise NotReady('VIP: ежедневные очки по native-конфигурации не подтверждены')
        return cls(money(state),inventory(state),experience+row['Point'],days+1,v['vip_box_available'])

    def matches(self,state):
        v=state.values
        return (v.get('vip_points_available') is False and v.get('vip_experience')==self.experience
            and v.get('vip_login_days')==self.days and v.get('vip_box_available') is self.box_available
            and v.get('vip_level')==0 and money(state)==self.resources and inventory(state)==self.items)


@dataclass(frozen=True)
class BoxReceipt:
    resources: dict
    items: dict
    experience: int
    points_available: bool

    @classmethod
    def capture(cls,state):
        v=state.values;config=v.get('vip_daily_config');rows=v.get('vip_daily_loot')
        if (not PANEL.matches(state) or v.get('vip_box_available') is not True or not table(config)
                or config.get('ready') is not True or config.get('level')!=0 or not table(config.get('rows'))
                or config['rows'].get('0',{}).get('FreeGiftReward')!=9001
                or not integer(v.get('vip_experience')) or type(v.get('vip_points_available')) is not bool
                or not table(rows) or not rows or len(rows)>16):
            raise NotReady('VIP: бесплатный сундук9001 не подтверждён')
        items=inventory(state)
        for row in rows.values():
            if (not table(row) or row.get('ID')!=9001 or row.get('Type')!=2
                    or not integer(row.get('SubType'),1) or not integer(row.get('Value'),1)):
                raise NotReady('VIP: состав бесплатного сундука не прочитан')
            key=str(row['SubType']);items[key]=items.get(key,0)+row['Value']
        return cls(money(state),items,v['vip_experience'],v['vip_points_available'])

    def matches(self,state):
        v=state.values
        return (v.get('vip_box_available') is False and v.get('vip_experience')==self.experience
            and v.get('vip_points_available') is self.points_available and v.get('vip_level')==0
            and money(state)==self.resources and inventory(state)==self.items)


def claim_daily(device,observe,cancelled,clock,allowed):
    initial=observe()
    def execute(steps):
        flow=Workflow('vip0_daily_transition','1.1.12.20',960,540,steps,verified=True)
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            flow,cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    if initial.values.get('vip_level')==12:
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            VIP_REWARD,cancelled,instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    if initial.values.get('vip_level')!=0:raise NotReady('VIP: этот уровень пока не проверен')
    dismiss_notice=Tap(480,500,NOTICE,PANEL,hold_ms=100,when=Condition(('vip_notice_visible',),'eq',True))
    dismiss_reward=Tap(480,500,REWARD,PANEL,hold_ms=100,when=Condition(('reward_popup_visible',),'eq',True),settle=.5)
    state=execute((QUEUE_CLOSE,Tap(108,46,All((CITY_SCENE,QUEUE_HIDDEN)),Condition(('vip_visible',),'eq',True),hold_ms=100),
        dismiss_notice,dismiss_reward))
    for flag,receipt_class,point,result in (('vip_points_available',PointReceipt,(765,152),NOTICE),
            ('vip_box_available',BoxReceipt,(705,267),REWARD)):
        if state.values.get(flag) is not True:continue
        receipt=receipt_class.capture(state)
        state=execute((Tap(*point,PANEL,All((Condition((flag,),'eq',False),result)),hold_ms=100),))
        deadline=clock()+20
        while True:
            state=observe()
            if receipt.matches(state):break
            if clock()>=deadline:raise WorkflowError('VIP: точная бесплатная выдача не подтверждена; повтор запрещён')
            if cancelled.wait(.1):
                from .workflows import Cancelled
                raise Cancelled('Получение VIP отменено')
        state=execute((dismiss_notice,dismiss_reward))
    return execute((Tap(818,62,PANEL,CITY_HUD,hold_ms=100),))


VIP_DAILY=Workflow('vip_reward','1.1.12.20',960,540,(Procedure(claim_daily),),verified=True,
    extra_paths=FIELDS,precondition=All((QUEUE_KNOWN,
        AnyOf((Condition(('vip_level',),'eq',0),Condition(('vip_level',),'eq',12))),
        Condition(('hud_visible',),'eq',True),Condition(('hud_menu',),'eq',False),Condition(('in_city',),'eq',True),
        Condition(('views',),'subset',CITY_VIEWS+('VIPMainPage','CommonBackground','RoutineRewardsCollect','VIPNotice','CommonItemBagPage')))),
    when=AnyOf((Condition(('vip_points_available',),'eq',True),Condition(('vip_box_available',),'eq',True),
        Condition(('vip_visible',),'eq',True))),wait_reason='Ожидание свободного VIP0/VIP12 экрана и бесплатных наград')
