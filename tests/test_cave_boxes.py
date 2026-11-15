from copy import deepcopy

import pytest

from mirage.cave_rewards import cave_box_workflow, cave_rewards_workflow
from mirage.supply_boxes import SupplyReceipt
from mirage.workflows import CITY_HUD, Cancelled, Engine
from test_supply_boxes import Route


class CaveBox(Route):
    def __init__(self):
        super().__init__(1);v=self.state.values
        v['supply_inventory']['items']['7014']=v['supply_inventory']['items']['7001'];v['supply_inventory']['items']['7001']=2
        v['supply_selected']['itemId']=7014;v['supply_list']['5']['itemId']=7014;v['resources']['33']=10

    def tap(self,x,y,**kwargs):
        v=self.state.values
        if (x,y)==(170,270):
            self.inputs.append((x,y));v['supply_selected']['itemId']=7014
        elif (x,y)==(725,466):
            self.inputs.append((x,y));v['supply_inventory']['items'].pop('7014');v['supply_selected']['itemCount']=0
            v['supply_inventory']['items']['141']+=5
            v.update(supply_reward_visible=True,supply_reward_source=7014,supply_reward_click=True,
                supply_reward_recycle=False,supply_reward_width=586.0723266601562,supply_reward_height=366.3492431640625,
                supply_reward_rows={'1':{'Type':2,'SubType':141,'Value':5}})
            v['views']['UniversalRewardsCollect']=True
            if self.cancel_on_use:self.cancelled.set()
        else:super().tap(x,y,**kwargs)

    def run(self,combined=False):
        return Engine(self,self.observe,clock=lambda:self.now,resolution=(960,540)).execute(
            (cave_rewards_workflow if combined else cave_box_workflow)({},verified=True),self.cancelled,
            instance_id='one',pid=10,player_id=20)


def test_cave_box_uses_one7014_and_leaves_ordinary7001_and_all_currencies_unchanged():
    game=CaveBox();before=deepcopy(game.state.values);state=game.run()
    assert CITY_HUD.matches(state) and game.inputs.count((725,466))==1
    assert state.values['supply_inventory']['items']['7001']==2 and '7014' not in state.values['supply_inventory']['items']
    assert state.values['resources']==before['resources']


def test_cave_box_cancel_after_use_only_confirms_the_existing_reward_on_resume():
    game=CaveBox();game.cancel_on_use=True
    with pytest.raises(Cancelled):game.run()
    game.cancel_on_use=False;game.cancelled.clear();state=game.run()
    assert CITY_HUD.matches(state) and game.inputs.count((725,466))==1 and state.values['supply_reward_resumed']


def test_cave_box_receipt_rejects_changes_to_currencies_outside_the_original_six():
    game=CaveBox();game.show('bag');receipt=SupplyReceipt.capture(game.state,7014)
    game.tap(725,466);assert receipt.matches(game.state)
    game.state.values['resources']['33']-=1
    assert not receipt.matches(game.state)


def test_combined_cave_mail_and_box_reader_stays_within_atomic64_field_limit():
    from mirage.memory import PATHS
    assert len(PATHS|cave_rewards_workflow({},verified=True).extra_paths)<=64


def test_already_owned_cave_box_does_not_depend_on_mail_cache_or_collect_other_mail():
    game=CaveBox();state=game.run(combined=True)
    assert CITY_HUD.matches(state) and game.inputs.count((725,466))==1
    assert (90,500) not in game.inputs


def test_cave_rewards_are_connected_to_the_normal_dispatcher():
    from mirage.workflows import workflow_for
    flow=workflow_for('cave_rewards',{'max_boxes':3})
    assert flow.verified and flow.task_id=='cave_rewards'
