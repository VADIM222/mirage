"""Claim report attachments attributable to completed ordinary caves, with exact loot receipts."""
from copy import deepcopy
from dataclasses import dataclass
import math

from .scout_fog import money, number
from .navigation import OpenHudFunction
from .model import SupplyBoxOptions
from .supply_boxes import FIELDS as BOX_FIELDS, OpenSupplyBoxes, integer, inventory, table
from .workflows import (All, AnyOf, CITY_HUD, CITY_VIEWS, Condition, Engine, HUD_MENU,
    MAIL_CONFIRM, MAIL_FIELDS, MAIL_PANEL, MAIL_REWARD_VISIBLE, NotReady, Procedure,
    QUEUE_CLOSE, QUEUE_KNOWN, RETURN_TO_CITY, SELECTION_CLEAR, Tap, Workflow)


FIELDS={**MAIL_FIELDS,'supply_inventory':['@item_counts'],'cave_mails':['@cave_mails'],
    'cave_discovered':['ScoutData','PlayerScoutCaveList'],'cave_visited':['ScoutData','OpenCaveIdMap'],
    'cave_scout_server':['ScoutData','curDataServerId'],'cave_map_server':['FogMgr','m_serverId'],
    'cave_viewed_server':['ViewOtherMapMgr','curViewServerId'],'hud_functions':['@hud_functions'],
    'mail_function_type':['UIObjectManager','MapHudPanel','FuncType','Mail']}


def cave_mail_loot(state):
    v=state.values;data=v.get('cave_mails');places=v.get('cave_discovered');visited=v.get('cave_visited')
    server=v.get('player',{}).get('ServerID');summary=v.get('mail_summary')
    if (not integer(server,1) or v.get('cave_scout_server')!=server or v.get('cave_map_server')!=server
            or v.get('cave_viewed_server')!=0 or not table(data) or data.get('ready') is not True
            or not table(data.get('rows')) or not table(places) or not table(visited)
            or not table(summary) or summary.get('ready') is not True):
        raise NotReady('Награды пещер: текущая домашняя карта и полные отчёты не подтверждены')
    statuses={};items={};sources={};pending=0
    for mail_id,row in data['rows'].items():
        if not table(row) or row.get('id')!=mail_id or not table(row.get('attachments')):
            raise NotReady('Награды пещер: неполное письмо отчётов')
        statuses[mail_id]={}
        for key,attachment in row['attachments'].items():
            if not table(attachment) or type(attachment.get('status')) is not int or attachment['status'] not in (0,1):
                raise NotReady('Награды пещер: статус вложения не прочитан')
            statuses[mail_id][key]=attachment['status']
            if attachment['status']!=0:continue
            body=row.get('body');position=body.get('position') if table(body) else None
            if (row.get('box')!='Report' or row.get('type')!='System' or row.get('serverId')!=server
                    or row.get('receiver')!=f'player_{state.player_id}' or not number(row.get('time'))
                    or not table(body) or body.get('subType')!=8 or not integer(body.get('subParam'),1)
                    or not table(position) or any(not number(position.get(axis)) for axis in ('X','Y'))):
                raise NotReady('Награды пещер: в отчётах есть другое готовое вложение')
            matches=[]
            for place in places.values():
                if (not table(place) or place.get('type')!=10 or not integer(place.get('caviId'),1)
                        or not table(place.get('pos')) or any(not number(place['pos'].get(axis)) for axis in ('x','y'))
                        or not number(place.get('findTm'))):raise NotReady('Награды пещер: обнаружения прочитаны не полностью')
                if (visited.get(str(place['caviId'])) is True and row['time']/1000>place['findTm']
                        and math.dist((position['X'],position['Y']),(place['pos']['x'],place['pos']['y']))<=6):
                    matches.append(place['caviId'])
            if len(matches)!=1:raise NotReady('Награды пещер: письмо не связано с единственной исследованной пещерой')
            loot=attachment.get('loot')
            if not table(loot) or not loot or len(loot)>16:raise NotReady('Награды пещер: вложенная награда не прочитана')
            for reward in loot.values():
                if (not table(reward) or reward.get('Type')!=2 or reward.get('SubType')!=7014
                        or not integer(reward.get('Value'),1)):
                    raise NotReady('Награды пещер: этот вид сундука ещё не подтверждён')
                items['7014']=items.get('7014',0)+reward['Value']
            statuses[mail_id][key]=1;sources[mail_id]=matches[0];pending+=1
    report=summary.get('boxes',{}).get('Report',{})
    if report.get('pending')!=pending:raise NotReady('Награды пещер: число вложений не совпадает с полным почтовым счётчиком')
    return statuses,items,sources


@dataclass(frozen=True)
class CaveMailReceipt:
    statuses: dict
    items: dict
    resources: dict
    other_boxes: dict
    sources: dict

    @classmethod
    def capture(cls,state):
        statuses,rewards,sources=cave_mail_loot(state)
        if not sources:raise NotReady('Награды пещер: нет готового сундука в отчётах')
        items=inventory(state)
        for key,count in rewards.items():items[key]=items.get(key,0)+count
        boxes=state.values['mail_summary']['boxes']
        return cls(statuses,items,money(state),deepcopy({key:value for key,value in boxes.items() if key!='Report'}),sources)

    def matches(self,state):
        v=state.values;rows=v.get('cave_mails',{});summary=v.get('mail_summary',{})
        if (rows.get('ready') is not True or summary.get('ready') is not True or not table(rows.get('rows'))
                or set(rows['rows'])-set(self.statuses) or set(self.statuses)-set(rows['rows'])-set(self.sources)
                or money(state)!=self.resources or inventory(state)!=self.items
                or summary.get('boxes',{}).get('Report',{}).get('pending')!=0
                or {key:value for key,value in summary.get('boxes',{}).items() if key!='Report'}!=self.other_boxes):return False
        for mail_id,expected in self.statuses.items():
            if mail_id not in rows['rows']:continue
            attachments=rows['rows'][mail_id].get('attachments')
            if not table(attachments) or set(attachments)!=set(expected):return False
            if any(attachments[key].get('status')!=status for key,status in expected.items()):return False
        return True


def collect_cave_mail(device,observe,cancelled,clock,allowed):
    initial=observe();state=initial
    def execute(steps):
        return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
            Workflow('cave_mail_transition','1.1.12.20',960,540,steps,verified=True,data_timeout=10),cancelled,
            instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
    def clean(s):
        return execute((MAIL_CONFIRM,Tap(925,32,MAIL_PANEL,
                All((Condition(('mail_visible',),'eq',False),AnyOf((CITY_HUD,HUD_MENU)))),hold_ms=100,
                when=Condition(('mail_visible',),'eq',True)),
            Tap(924,505,HUD_MENU,CITY_HUD,hold_ms=100,when=Condition(('hud_menu',),'eq',True),settle=.35)))
    if state.values.get('mail_reward_visible') is True:
        state=clean(state);state.values['cave_mail_claimed']=0;state.values['cave_mail_resumed']=True;return state
    _,rewards,_=cave_mail_loot(state)
    if not rewards:
        if not CITY_HUD.matches(state):
            state=clean(state) if state.values.get('mail_visible') is True else execute(RETURN_TO_CITY.steps)
        return state
    if state.values.get('mail_visible') is not True:
        if not CITY_HUD.matches(state):state=execute(RETURN_TO_CITY.steps)
        state=execute((QUEUE_CLOSE,*SELECTION_CLEAR,Tap(924,505,CITY_HUD,HUD_MENU,hold_ms=100,settle=.35)))
        kind=state.values.get('mail_function_type')
        if not integer(kind,1) or kind>8:raise NotReady('Награды пещер: native-тип кнопки почты не прочитан')
        state=OpenHudFunction(kind,MAIL_PANEL)(device,observe,cancelled,clock,allowed)
    state=execute((Tap(188,31,MAIL_PANEL,Condition(('mail_box',),'eq',2),hold_ms=100,settle=.3),))
    receipt=CaveMailReceipt.capture(state)
    state=execute((Tap(90,500,All((MAIL_PANEL,Condition(('mail_box',),'eq',2))),
        All((MAIL_REWARD_VISIBLE,receipt)),hold_ms=100,timeout=25,settle=.3),))
    state=clean(state);state.values['cave_mail_claimed']=len(receipt.sources);state.values['cave_mail_sources']=receipt.sources
    return state


CAVE_MAIL=Workflow('cave_rewards','1.1.12.20',960,540,(Procedure(collect_cave_mail),),verified=True,
    extra_paths=FIELDS,requires_city=False,data_timeout=10,
    precondition=All((QUEUE_KNOWN,Condition(('hud_visible',),'eq',True),Condition(('views',),'subset',CITY_VIEWS+('AllUIMailMainPage','VIPMainPage',
        'CommonBackground','UniversalRewardsCollect','CommonItemBagPage')))))


def cave_box_workflow(settings,*,verified=False):
    return Workflow('cave_rewards','1.1.12.20',960,540,
        (Procedure(OpenSupplyBoxes(SupplyBoxOptions.from_settings(settings),7014)),),verified=verified,
        extra_paths=BOX_FIELDS,data_timeout=10,wait_reason='Ожидание полученного сундука пещеры7014 и свободной сумки')


def cave_rewards_workflow(settings,*,verified=False):
    options=SupplyBoxOptions.from_settings(settings)
    def collect_and_open(device,observe,cancelled,clock,allowed):
        def observed():
            state=observe()
            # The mail and bag receipts read the same native recycle flag. Keep
            # one wire path so their combined atomic request stays within64.
            state.values['mail_reward_recycle']=state.values.get('supply_reward_recycle')
            return state
        initial=observed()
        if initial.values.get('supply_bag_visible') is not True and not inventory(initial).get('7014'):
            state=collect_cave_mail(device,observed,cancelled,clock,allowed)
            if state.values.get('cave_mail_resumed'):return state
        return OpenSupplyBoxes(options,7014)(device,observed,cancelled,clock,allowed)
    fields={**FIELDS,**BOX_FIELDS};fields.pop('mail_reward_recycle')
    return Workflow('cave_rewards','1.1.12.20',960,540,(Procedure(collect_and_open),),verified=verified,
        extra_paths=fields,requires_city=False,data_timeout=10,
        precondition=All((QUEUE_KNOWN,Condition(('hud_visible',),'eq',True),Condition(('views',),'subset',
            CITY_VIEWS+('AllUIMailMainPage','VIPMainPage','CommonBackground','UniversalRewardsCollect','CommonItemBagPage','ItemBag')))))
