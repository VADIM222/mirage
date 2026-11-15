from copy import deepcopy

import pytest

from mirage.commanders import commander_catalog,hero_ids,set_commander,troop_heroes
from mirage.model import BarbarianOptions,Snapshot
from mirage.storage import Store


def roster(player=7):
    return {'ready':True,'player':player,'heroes':{
        '3':{'id':3,'name':'Sun Tzu','level':20,'star':3},
        '15':{'id':15,'name':'Joan of Arc','level':10,'star':2}}}


def test_old_settings_and_atomic_primary_swap():
    assert BarbarianOptions.from_settings({'primary':15}).heroes=={'1':15}
    settings={'primary':3,'deputy':15,'interval':90}
    set_commander(settings,'primary',15)
    assert settings=={'primary':15,'deputy':0,'interval':90}
    with pytest.raises(ValueError):set_commander(settings,'deputy',15)
    with pytest.raises(ValueError):BarbarianOptions.from_settings({'primary':15,'deputy':15})


def test_roster_cache_rejects_other_account_and_truncated_native_data(tmp_path):
    store=Store(tmp_path/'db');value=roster()
    state=Snapshot('test',1,7,0,'1.1.12.20',{'player':{'_commanders':value}})
    assert commander_catalog(store,'test',state)==value
    assert commander_catalog(store,'test')==value
    wrong=Snapshot('test',1,8,0,'1.1.12.20',{'player':{}})
    assert not commander_catalog(store,'test',wrong)['ready']
    truncated=deepcopy(value);truncated['heroes']['$truncated']=True
    wrong.values['player']['_commanders']=truncated
    assert not commander_catalog(store,'test',wrong)['ready']


def test_exact_pair_uses_labels_and_rejects_duplicates():
    assert troop_heroes({'heros':{'9':{'label':2,'heroId':15},'1':{'label':1,'heroId':3}}})=={'1':3,'2':15}
    assert troop_heroes({'heros':{'1':{'label':1,'heroId':3},'2':{'label':1,'heroId':15}}}) is None
    assert hero_ids({'1':3,'2':3}) is None
    assert hero_ids({'2':15}) is None
