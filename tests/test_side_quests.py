from copy import deepcopy
import threading

import pytest

from mirage.side_quests import SideReceipt, side_workflow
from mirage.workflows import CITY_HUD, Cancelled, NotReady, WorkflowError, workflow_for
from test_rewards import Game, execute


class QuestGame(Game):
    def __init__(self,count=3):
        super().__init__();self.time=100.;self.bad=False;self.stop=None
        self.values.update(resources={str(i):1000 for i in range(1,7)},
            supply_inventory={'ready':True,'items':{}},
            side_quests={'ready':True,'entryY':178},daily_ready_count=0)
        self.ready=list(range(100,100+count))

    def snapshot(self):
        state=super().snapshot();s=state.values['side_quests']
        s.update(available=len(self.ready),completed=len(self.ready),statuses={str(i):2 for i in self.ready},
            rows={str(i):{'config':{'ID':i,'RewardID':i+1000},
                'loot':{'1':{'ID':i+1000,'Type':1,'SubType':1,'Value':500},
                    '2':{'ID':i+1000,'Type':2,'SubType':10004,'Value':1}}} for i in self.ready},
            display={'1':{'type':2,'param':{'text':'LC_COMMON_MAIN_MISSION'}},
                '2':{'type':1,'param':{'questType':1,'Id':41103,'Stat':1}},
                '3':{'type':2,'param':{'text':'LC_COMMON_NORMAL_MISSION'}},
                **{str(j+4):{'type':1,'param':{'questType':2,'Id':i,'Stat':2}} for j,i in enumerate(self.ready)}})
        return state

    def tap(self,x,y,**kwargs):
        if (x,y) in ((30,178),(77,130),(755,299)):
            self.taps.append((x,y))
            if (x,y)==(30,178):self.values.update(quest_visible=True,quest_tab=1)
            elif (x,y)==(77,130):self.values['quest_tab']=1
            else:
                self.ready.pop(0);self.values['resources']['1']+=499 if self.bad else 500
                items=self.values['supply_inventory']['items'];items['10004']=items.get('10004',0)+1
                if self.stop:self.stop.set()
        else:super().tap(x,y,**kwargs)


def test_each_claim_confirms_one_reward_and_ready_counter_decrements():
    game=QuestGame();game.values.update(quest_visible=True,quest_tab=1)
    before=game.snapshot();receipt=SideReceipt.capture(before)
    game.tap(755,299);after=game.snapshot()
    assert receipt.matches(after) and after.values['side_quests']['completed']==2
    after.values['resources']['5']-=1
    assert not receipt.matches(after)
    after=game.snapshot();after.values['side_quests']['completed']=4
    assert not receipt.matches(after)


def test_side_cycle_is_bounded_and_preserves_unclaimed_remainder():
    game=QuestGame(9);after=execute(game,side_workflow())
    assert CITY_HUD.matches(after) and len(game.ready)==1
    assert game.taps.count((755,299))==8
    assert after.values['resources']['1']==5000


def test_uncertain_reward_never_triggers_a_second_claim():
    game=QuestGame();game.bad=True
    with pytest.raises(WorkflowError,match='повтор'):execute(game,side_workflow())
    assert game.taps.count((755,299))==1


def test_stop_after_claim_resumes_with_remaining_quests_only():
    game=QuestGame();cancelled=threading.Event();game.stop=cancelled
    with pytest.raises(Cancelled):execute(game,side_workflow(),cancelled)
    assert len(game.ready)==2
    game.stop=None
    after=execute(game,side_workflow())
    assert CITY_HUD.matches(after) and game.taps.count((755,299))==3
    assert after.values['supply_inventory']['items']=={'10004':3}


def test_registry_runs_side_then_existing_daily_rewards_with_shifted_hud_entry():
    game=QuestGame(2);game.values['daily_ready_count']=3
    after=execute(game,workflow_for('quests',{}))
    assert CITY_HUD.matches(after) and not game.ready and after.values['daily_ready_count']==0
    assert game.taps.count((30,178))==2 and (30,155) not in game.taps
    assert (755,255) in game.taps and (270,145) in game.taps


@pytest.mark.parametrize('fault',['main','unknown_loot','display','counter','inventory'])
def test_ambiguous_claim_is_rejected_before_input(fault):
    game=QuestGame();game.values.update(quest_visible=True,quest_tab=1);s=game.snapshot();side=s.values['side_quests']
    if fault=='main':side['display']['2']['param']['Stat']=2
    elif fault=='unknown_loot':side['rows']['100']['loot']['1']['Type']=3
    elif fault=='display':del side['display']['5']
    elif fault=='counter':side['completed']=50
    else:s.values['supply_inventory']['items']['$truncated']=True
    with pytest.raises(NotReady):SideReceipt.capture(s)
