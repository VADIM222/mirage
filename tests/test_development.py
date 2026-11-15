from copy import deepcopy
from types import SimpleNamespace

import pytest

from mirage.development import next_building_target
from mirage.workflows import NotReady


def state():
    def config(kind,level,pre,required):
        return dict(Type=kind,Level=level,Enable=1,PreType1=pre,PreLevel1=required,
            PreType2=0,PreLevel2=0,PreType3=0,PreLevel3=0)
    return SimpleNamespace(values={'buildings':{
        'town':dict(type=1,lv=6,state=1,endTime=0),
        'wall':dict(type=6,lv=5,state=1,endTime=0),
        'tavern':dict(type=18,lv=5,state=1,endTime=0),
        'quarry':dict(type=4,lv=2,state=1,endTime=0)},
        'building_plan':{'ready':True,'rows':{
            'town':config(1,7,6,6),'wall':config(6,6,18,6),
            'tavern':config(18,6,4,6),'quarry':config(4,3,1,3)}}})


def test_recursive_current_game_prerequisites_choose_next_quarry_upgrade_for_townhall():
    s=state();target=next_building_target(s,(1,),7)
    assert (target.kind,target.level,target.building,target.root)==(4,3,'quarry',1)


def test_accepted_prerequisite_is_not_duplicated_and_missing_building_becomes_placement_goal():
    s=state();s.values['buildings']['quarry']['state']=2
    assert next_building_target(s,(1,),7) is None
    del s.values['buildings']['quarry']
    target=next_building_target(s,(1,),7)
    assert target.kind==4 and target.building is None and target.level==1


def test_root_goal_keeps_improving_each_existing_resource_building():
    s=state();s.values['buildings']['other_quarry']=dict(type=4,lv=6,state=1,endTime=0)
    target=next_building_target(s,(4,),6)
    assert target.building=='quarry' and target.level==3


def test_cyclic_or_incomplete_native_requirements_never_issue_an_order():
    s=state();s.values['building_plan']['rows']['quarry']['PreType1']=18
    s.values['building_plan']['rows']['quarry']['PreLevel1']=6
    with pytest.raises(NotReady,match='цикл'):next_building_target(s,(1,),7)
    s=state();del s.values['building_plan']['rows']['quarry']['PreLevel1']
    with pytest.raises(NotReady):next_building_target(s,(1,),7)
