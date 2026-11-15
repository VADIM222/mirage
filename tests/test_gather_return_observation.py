"""Research evidence must not credit user marches or partial return packets."""
from copy import deepcopy
from dataclasses import replace

import pytest

from mirage.model import Snapshot
from research.check_multi_resource_return import ReturnObservation


def baseline():
    def army(key,resource,count):
        return {'troopId':int(key),'state':6,'isFightTarget':False,'offensive':False,'collected':0,
            'carrier':{'resType':resource},'troop':{'playerId':20,'units':{
                '1':{'unitId':4,'unitCount':count,'maxCount':count}}}}
    return Snapshot('one',10,20,100,'1.1.12.20',{'server_time':100000,
        'resources':{str(i):1000 for i in range(1,7)},'gather_count':2,
        'gather_troops':{'71':army('71',2,70),'31':army('31',5,30)},
        'troops':{'1':{'unitId':4,'unitCount':100,'maxCount':200,'hurt':0,'badHurt':0}}})


def observation(state):
    return ReturnObservation(state,{'71':{'resource':2,'minimum':315000,'units':{'4':70}}})


def test_user_gem_return_is_accounted_separately_and_never_completes_research():
    state=baseline();observer=observation(state);observer.sample(state)
    state=deepcopy(state);v=state.values
    del v['gather_troops']['31'];v['gather_count']=1
    v['troops']['1']['unitCount']+=30;v['resources']['5']+=250
    sample=observer.sample(state)
    assert sample['unrelated_returned']==['31'] and not sample['research_returned']
    assert sample['exact_healthy_units'] and not sample['complete']
    v['gather_troops']['71'].update(state=2,collected=315000,target={'resType':0,'charType':3})
    observer.sample(state)
    del v['gather_troops']['71'];v['gather_count']=0
    # Removal, healthy units, and resource credit may be delivered separately.
    assert not observer.sample(state)['complete']
    v['troops']['1']['unitCount']+=70
    assert not observer.sample(state)['complete']
    v['resources']['2']+=349650
    result=observer.sample(state)
    assert result['complete'] and result['resource_delta']['2']==349650
    assert result['resource_delta']['5']==250 and observer.collected=={'71':315000}


def test_full_resource_income_cannot_hide_lost_units_or_missing_collection_evidence():
    state=baseline();observer=observation(state);observer.sample(state)
    after=deepcopy(state);v=after.values
    del v['gather_troops']['71'];v['gather_count']=1
    v['resources']['2']+=349650;v['troops']['1']['unitCount']+=70
    assert not observer.sample(after)['complete']  # No observed full load.
    observer=observation(state)
    state.values['gather_troops']['71']['collected']=315000;observer.sample(state)
    v['troops']['1']['unitCount']-=1
    assert not observer.sample(after)['complete']
    v['troops']['1']['unitCount']+=1
    assert observer.sample(after)['complete']


@pytest.mark.parametrize('fault',['identity','new_army','lost_army_unit','spending','clock'])
def test_external_changes_invalidate_attribution(fault):
    state=baseline();observer=observation(state);after=deepcopy(state);v=after.values
    if fault=='identity':after=replace(after,pid=11)
    elif fault=='new_army':
        v['gather_troops']['99']=deepcopy(v['gather_troops']['31'])
        v['gather_troops']['99']['troopId']=99;v['gather_count']=3
    elif fault=='lost_army_unit':v['gather_troops']['71']['troop']['units']['1']['unitCount']-=1
    elif fault=='spending':v['resources']['5']-=1
    else:v['server_time']-=1
    with pytest.raises(RuntimeError):observer.sample(after)


def test_overlapping_non_gem_marches_require_their_own_receipts():
    state=baseline();state.values['gather_troops']['31']['carrier']['resType']=2
    with pytest.raises(RuntimeError,match='Only identified gem'):observation(state)


def test_old_or_already_completed_receipts_are_rejected_at_baseline():
    state=baseline();state.values['gather_troops']['71']['collected']=315000
    with pytest.raises(RuntimeError,match='precede collection'):observation(state)


def test_earlier_background_income_does_not_prove_a_research_return():
    state=baseline();observer=observation(state)
    v=state.values;v['resources']['1']+=20000;v['resources']['2']+=400000
    sample=observer.sample(state)
    assert not sample['complete'] and sample['background_income']['2']==400000
    v['server_time']+=60000;v['gather_troops']['71']['collected']=315000
    observer.sample(state)
    del v['gather_troops']['71'];v['gather_count']=1;v['troops']['1']['unitCount']+=70
    assert not observer.sample(state)['complete']
    v['server_time']+=5000;v['resources']['2']+=349650
    sample=observer.sample(state)
    assert sample['complete'] and sample['research_income']=={'2':349650}
    assert sample['background_income']['2']==400000


def test_returning_gem_march_requires_prior_identity_and_exact_unit_evidence():
    state=baseline();v=state.values;v['gather_city_id']=57610300
    v['gather_troops']['31'].update(state=2,collected=30000,target={'resType':0,'charType':3,'charId':57610300})
    expected={'71':{'resource':2,'minimum':315000,'units':{'4':70}}}
    with pytest.raises(RuntimeError,match='Only identified gem'):ReturnObservation(state,expected)
    with pytest.raises(RuntimeError,match='Only identified gem'):ReturnObservation(state,expected,{'31':{'4':29}})
    assert ReturnObservation(state,expected,{'31':{'4':30}}).unrelated=={'31'}


@pytest.mark.parametrize('change',['none','moves','returns','collects','new_target'])
def test_stationary_user_army_is_never_credited_or_allowed_to_change(change):
    state=baseline();row=state.values['gather_troops']['31']
    row.update(state=4,charType=1,charId=90100,pos={'x':10.,'y':20.},collected=10000)
    observer=observation(state);after=deepcopy(state);row=after.values['gather_troops']['31']
    if change=='moves':row['pos']['x']+=1
    elif change=='returns':del after.values['gather_troops']['31'];after.values['gather_count']=1
    elif change=='collects':row['collected']+=1
    elif change=='new_target':row['target']={'resType':2,'charType':6}
    if change=='none':
        sample=observer.sample(after)
        assert sample['stationary_user_armies']==['31'] and not sample['verified_armies']
    else:
        with pytest.raises(RuntimeError,match='Stationary user army'):observer.sample(after)


def test_individual_return_evidence_survives_another_pending_research_army():
    state=baseline();v=state.values
    v['gather_troops']['31']['carrier']['resType']=3
    expected={'71':{'resource':2,'minimum':315000,'units':{'4':70}},
              '31':{'resource':3,'minimum':354375,'units':{'4':30}}}
    observer=ReturnObservation(state,expected)
    v['gather_troops']['71']['collected']=315000;observer.sample(state)
    del v['gather_troops']['71'];v['gather_count']=1
    v['troops']['1']['unitCount']+=70;v['resources']['2']+=333900
    sample=observer.sample(state)
    assert sample['verified_armies']==['71'] and not sample['complete']
