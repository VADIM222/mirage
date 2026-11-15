from copy import deepcopy
import threading

import pytest

from mirage.cave_rewards import CAVE_MAIL, CaveMailReceipt
from mirage.workflows import CITY_HUD, Cancelled, NotReady
from test_rewards import MailGame, execute


class CaveMailGame(MailGame):
    def __init__(self):
        super().__init__();self.cancel_after_claim=None
        self.boxes={'SystemBox':{'pending':1,'unread':1},'AllianceBox':{'pending':0,'unread':0},'Report':{'pending':1,'unread':2}}
        self.values.update(player={'ServerID':3221},cave_scout_server=3221,cave_map_server=3221,cave_viewed_server=0,
            resources={**{str(i):1000 for i in range(1,7)},'33':10},supply_inventory={'ready':True,'items':{'47':2}},
            cave_discovered={'1':{'type':10,'caviId':30215,'pos':{'x':2563.7,'y':6127.6},'findTm':1000}},
            cave_visited={'30215':True},hud_functions={'ready':True,'slots':{'4':1}},mail_function_type=4,
            cave_mails={'ready':True,'rows':{'mail1':{'id':'mail1','box':'Report','type':'System','serverId':3221,
                'receiver':'player_20','time':2000000,'body':{'subType':8,'subParam':3,'position':{'X':2563.65,'Y':6130.03}},
                'attachments':{'1':{'id':1,'status':0,'loot':{'1':{'Type':2,'SubType':7014,'Value':1}}}}}}})

    def tap(self,x,y,*,hold_ms=0):
        if (x,y)==(849,505):x=846
        super().tap(x,y,hold_ms=hold_ms)
        if (x,y)==(90,500):
            assert self.values['mail_box']==2
            self.values['cave_mails']['rows']['mail1']['attachments']['1']['status']=1
            self.values['supply_inventory']['items']['7014']=1
            if self.cancel_after_claim is not None:self.cancel_after_claim.set()


def test_cave_mail_claims_the_proven_chest_and_preserves_other_boxes_and_assets():
    game=CaveMailGame();before=deepcopy(game.values);state=execute(game,CAVE_MAIL)
    assert CITY_HUD.matches(state) and state.values['cave_mail_claimed']==1
    assert state.values['supply_inventory']['items']=={'47':2,'7014':1} and state.values['resources']==before['resources']
    assert game.boxes['SystemBox']=={'pending':1,'unread':1} and game.taps.count((90,500))==1
    assert (188,31) in game.taps and (428,31) not in game.taps


@pytest.mark.parametrize('fault',['unvisited','other_server','other_receiver','position','other_mail','other_item','missing_rows'])
def test_cave_mail_refuses_unrelated_or_unattributable_report_attachments(fault):
    game=CaveMailGame();row=game.values['cave_mails']['rows']['mail1']
    if fault=='unvisited':game.values['cave_visited']={}
    elif fault=='other_server':row['serverId']=2759
    elif fault=='other_receiver':row['receiver']='player_21'
    elif fault=='position':row['body']['position']['X']+=100
    elif fault=='other_mail':row['body']['subType']=3
    elif fault=='other_item':row['attachments']['1']['loot']['1']['SubType']=7001
    else:game.values['cave_mails']['rows']={}
    with pytest.raises(NotReady):execute(game,CAVE_MAIL)
    assert not game.taps


def test_cave_mail_cancellation_after_claim_resumes_without_a_second_claim():
    game=CaveMailGame();stop=threading.Event();game.cancel_after_claim=stop
    with pytest.raises(Cancelled):execute(game,CAVE_MAIL,stop)
    stop.clear();game.cancel_after_claim=None
    state=execute(game,CAVE_MAIL,stop)
    assert CITY_HUD.matches(state) and game.taps.count((90,500))==1


@pytest.mark.parametrize('fault',['gems','other_item','other_box'])
def test_cave_mail_receipt_rejects_unrelated_asset_or_mail_changes(fault):
    game=CaveMailGame();game.values.update(mail_visible=True,mail_box=2)
    receipt=CaveMailReceipt.capture(game.snapshot());game.tap(90,500,hold_ms=100);state=game.snapshot()
    if fault=='gems':state.values['resources']['5']-=1
    elif fault=='other_item':state.values['supply_inventory']['items']['47']-=1
    else:state.values['mail_summary']['boxes']['SystemBox']['pending']=0
    assert not receipt.matches(state)
