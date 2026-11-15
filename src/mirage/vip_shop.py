"""One resource-priced VIP-shop purchase, checked against stock, inventory and balances."""
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite

from .model import VipShopOptions
from .supply_boxes import inventory, balances, integer, table
from .workflows import (All, CITY_HUD, CITY_VIEWS, Cancelled, Condition, Engine, NavigateCity,
    NotReady, Procedure, SELECTION_CLEAR, Tap, Workflow, WorkflowError)


FIELDS={'supply_inventory':['@item_counts'],'vip_shop_visible':['@active_view','VIPShop'],
    'vip_shop_stock':['VipData','ShopData'],'vip_shop_quick':['UIObjectManager','VIPShop','showQuickBuy'],
    'vip_shop_width':['UIObjectManager','VIPShop','m_UICullWidth'],
    'vip_shop_height':['UIObjectManager','VIPShop','m_UICullHeigth'],
    'building_menu':['@building_menu'],'city_camera':['@city_camera']}
VISIBLE=Condition(('vip_shop_visible',),'eq',True)
PANEL=All((VISIBLE,Condition(('in_city',),'eq',True),Condition(('city_enabled',),'eq',True),
    Condition(('views',),'subset',CITY_VIEWS+('VIPShop','CommonBackground'))))
SLOTS={124:(1,1,(294,197)),58:(2,2,(541,197)),8011:(5,5,(294,416)),9998:(6,6,(541,416))}


def stock(state):
    value=state.values.get('vip_shop_stock');clock=state.values.get('server_time')
    if (not table(value) or not table(value.get('Items')) or not value['Items']
            or not table(value.get('Refresh')) or value['Refresh'].get('Method')!='week'
            or not integer(value['Refresh'].get('Next'),1) or not isinstance(clock,(int,float))
            or not isfinite(clock) or value['Refresh']['Next']*1000<=clock+30000):
        raise NotReady('VIP-магазин: неполные данные или близкая смена ассортимента')
    ids=set()
    for row in value['Items'].values():
        if (not table(row) or any(not integer(row.get(k),1) for k in ('SlotId','Weight','SubType','VipLvl','Price','Type','PriceType'))
                or not integer(row.get('Amount')) or row['SlotId'] in ids):
            raise NotReady('VIP-магазин: ассортимент не подтверждён')
        ids.add(row['SlotId'])
    return deepcopy(value)


def offer(state,options):
    data=stock(state);slot,weight,point=SLOTS[options.item_id]
    rows=[r for r in data['Items'].values() if r['SlotId']==slot]
    if len(rows)!=1:raise NotReady('VIP-магазин: выбранный слот отсутствует')
    row=rows[0]
    if (row['SubType']!=options.item_id or row['Type']!=2 or row['PriceType']!=1 or row['Weight']!=weight
            or type(state.values.get('vip_level')) is not int or row['VipLvl']>state.values['vip_level']):
        raise NotReady('VIP-магазин: товар, порядок, VIP или оплата едой не подтверждены')
    return row,point


@dataclass(frozen=True)
class PurchaseReceipt:
    shop: dict
    items: dict
    currency: dict
    slot: int
    item: int
    price: int

    @classmethod
    def capture(cls,state,options):
        v=state.values;row,_=offer(state,options);money=balances(state)
        if (not PANEL.matches(state) or v.get('vip_shop_quick') is not False
                or any(type(v.get('vip_shop_'+k)) not in (int,float) or not isfinite(v['vip_shop_'+k])
                    or abs(v['vip_shop_'+k]-expected)>.1 for k,expected in (('width',720.8992),('height',444.8423)))
                or row['Amount']<1 or row['Price']>options.max_price or money['1']-row['Price']<options.reserve):
            raise NotReady('VIP-магазин: форма, остаток, цена или резерв не разрешают покупку')
        return cls(stock(state),inventory(state),money,row['SlotId'],row['SubType'],row['Price'])

    def matches(self,state):
        try:current=stock(state);items=inventory(state);money=balances(state)
        except NotReady:return False
        expected=deepcopy(self.shop)
        for row in expected['Items'].values():
            if row['SlotId']==self.slot:row['Amount']-=1
        expected_items=dict(self.items);expected_items[str(self.item)]=expected_items.get(str(self.item),0)+1
        expected_money={key:value-(self.price if key=='1' else 0) for key,value in self.currency.items()}
        return current==expected and items==expected_items and money==expected_money


@dataclass(frozen=True)
class BuyVipItem:
    options: VipShopOptions

    def __call__(self,device,observe,cancelled,clock,allowed):
        initial=observe()
        def permit():
            if cancelled.is_set() or not allowed():raise Cancelled('Покупка VIP-магазина отменена')
        def execute(steps):
            return Engine(device,observe,clock=clock,resolution=(960,540),allowed=allowed).execute(
                Workflow('vip_shop_transition','1.1.12.20',960,540,steps,verified=True),cancelled,
                instance_id=initial.instance_id,pid=initial.pid,player_id=initial.player_id)
        def clean():
            return execute((Tap(819,62,PANEL,Condition(('vip_shop_visible',),'eq',False),when=VISIBLE,hold_ms=100,settle=.3),*SELECTION_CLEAR))
        state=clean()
        if not CITY_HUD.matches(state):raise NotReady('VIP-магазин: нужен свободный город')
        # Stock may be nil before the first visit. A known sold-out or capped
        # offer can return without navigating; unknown data is loaded via UI.
        if state.values.get('vip_shop_stock') is not None:
            row,_=offer(state,self.options)
            if not row['Amount'] or row['Price']>self.options.max_price or balances(state)['1']-row['Price']<self.options.reserve:
                return state
        buildings=[k for k,r in state.values['buildings'].items() if table(r) and r.get('type')==20 and r.get('state')==1]
        if len(buildings)!=1:raise NotReady('VIP-магазин: не подтверждено единственное здание магазина')
        building=buildings[0]
        state=execute((NavigateCity(20,building_id=building),))
        class Selected:
            def matches(self,s):
                row=s.values.get('building_menu',{}).get('selected')
                return (table(row) and row.get('id')==building and row.get('type')==20
                    and set(row.get('buttons',[]))=={'btn_CityPopUpInfo','btn_FunctionShop','btn_CityPopUpVIPShop'}
                    and set(s.values['views'])<=set(CITY_VIEWS))
        state=execute((Tap(480,350,Selected(),PANEL,hold_ms=100,settle=1.5),))
        try:receipt=PurchaseReceipt.capture(observe(),self.options)
        except NotReady:return clean()
        _,point=offer(state,self.options)
        permit();device.tap(*point,hold_ms=100)
        deadline=clock()+20
        while True:
            permit();state=observe()
            if receipt.matches(state):break
            if clock()>=deadline:raise WorkflowError('VIP-магазин: точная покупка не подтверждена; повтор запрещён')
            if cancelled.wait(.1):raise Cancelled('Покупка VIP-магазина отменена')
        state=clean();state.values['vip_shop_bought']=self.options.item_id
        return state


def vip_shop_workflow(settings,*,verified=False):
    return Workflow('vip_shop','1.1.12.20',960,540,(Procedure(BuyVipItem(VipShopOptions.from_settings(settings))),),
        verified=verified,extra_paths=FIELDS,data_timeout=10,wait_reason='Ожидание VIP-магазина и выбранного товара за еду')
