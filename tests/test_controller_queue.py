"""Exercise queued live-read work through the actual controller and bounded pool."""
from dataclasses import replace
import threading
import time

import pytest

from mirage.controller import Controller
from mirage.model import Instance, Power, Profile, Provider, Snapshot
from mirage.storage import Store


@pytest.mark.parametrize("blocked",["identity","pause"])
def test_three_waiting_games_survive_expired_gui_telemetry_and_recheck_identity(qtbot,tmp_path,blocked):
    store = Store(tmp_path/"mirage.sqlite3")
    store.set_preference("workers",1)
    controller = Controller(store,auto_refresh=False)
    release = threading.Event()
    entered = threading.Event()
    def occupy(cancelled):
        entered.set()
        release.wait(3)
        return "cancelled",
    assert controller._submit("__occupied__",occupy)
    assert entered.wait(1)
    inputs = []
    class Adb:
        def tap(self,*args,**kwargs):inputs.append(args)
    class Reader:
        adb = Adb()
        def __init__(self,key,player):self.key,self.player = key,player
        def snapshot(self):
            return Snapshot(self.key,10,self.player,time.monotonic(),"1.1.12.20",{
                "player":{"PlayerID":self.player,"AllianceID":1},"hud_visible":True,"hud_menu":False,
                "in_city":True,"city_enabled":True,"views":{"MapHudPanel":True},"queue_panel":{"known":True,"visible":False},
                "city_selection_known":True,"city_selection":None,"vip_visible":False,"alliance_help_count":0})
        def close(self):pass
    try:
        for index in range(3):
            key = f"ld:test:{index}"
            controller.instances.append(Instance(key,Provider.LDPLAYER,str(index),key,"LD","adb",key,
                Power.ONLINE,cpus=2,memory_mb=2048,width=960,height=540))
            store.save_profile(Profile(key,manual_run=True,tasks={"alliance_help":{"enabled":True,"interval":86400}}))
            controller.readers[key] = Reader(key,99 if index == 1 and blocked == "identity" else 20)
            controller.snapshots[key] = replace(controller.readers[key].snapshot(),player_id=20)
        controller._last_memory_poll = time.monotonic()+3600
        controller.tick()
        assert len(controller._active_tasks) == 3
        for key in controller.snapshots:
            controller.snapshots[key] = replace(controller.snapshots[key],captured_at=time.monotonic()-20)
        controller.tick()
        if blocked == "pause":
            controller.stop("ld:test:1")
        release.set()
        qtbot.waitUntil(lambda:not controller._active_tasks)
        for index in (0,2):
            assert controller._due[(f"ld:test:{index}","alliance_help")] > time.monotonic()
        assert ("ld:test:1","alliance_help") not in controller._due
        if blocked == "identity":
            assert "изменился" in controller._task_errors["ld:test:1"]
        else:
            assert "ld:test:1" not in controller._task_errors
        assert not inputs
    finally:
        release.set()
        controller.shutdown()


def test_research_building_prerequisite_does_not_consume_the_full_research_interval(qtbot,tmp_path,monkeypatch):
    store=Store(tmp_path/'mirage.sqlite3');key='ld:test:1'
    store.save_profile(Profile(key,tasks={'research':{'types':[243],'interval':86400}}))
    controller=Controller(store,auto_refresh=False)
    monkeypatch.setattr(controller.dispatcher,'acknowledge',lambda *args:True)
    snapshot=Snapshot(key,10,20,time.monotonic(),'1.1.12.20',{'research_prerequisite_pending':True})
    try:
        now=time.monotonic();controller._completed(key,1,('task',key,'research',snapshot,None),None)
        assert now+4<=controller._due[(key,'research')]<=now+7
        assert controller.snapshots[key] is snapshot and 'предпосылка' in controller.reasons[key]
    finally:controller.shutdown()


def test_balanced_research_branch_is_durable_and_prerequisite_wait_does_not_toggle_it(qtbot,tmp_path,monkeypatch):
    store=Store(tmp_path/'mirage.sqlite3');key='ld:test:1'
    store.save_profile(Profile(key,tasks={'research':{'priority_mode':'balanced','interval':300}}))
    controller=Controller(store,auto_refresh=False)
    monkeypatch.setattr(controller.dispatcher,'acknowledge',lambda *args:True)
    try:
        snapshot=Snapshot(key,10,20,time.monotonic(),'1.1.12.20',{'research_next_branch':'military'})
        controller._completed(key,1,('task',key,'research',snapshot,None),None)
        assert Store(store.path).profile(key).tasks['research']['next_branch']=='military'
        waiting=replace(snapshot,values={'research_prerequisite_pending':True})
        controller._completed(key,2,('task',key,'research',waiting,None),None)
        assert store.profile(key).tasks['research']['next_branch']=='military'
    finally:controller.shutdown()


def test_a_battle_session_is_rechecked_promptly_and_the_full_interval_starts_after_return(qtbot,tmp_path,monkeypatch):
    store=Store(tmp_path/'mirage.sqlite3');key='ld:test:1'
    store.save_profile(Profile(key,tasks={'barbarians':{'interval':600}}))
    controller=Controller(store,auto_refresh=False)
    monkeypatch.setattr(controller.dispatcher,'acknowledge',lambda *args:True)
    try:
        snapshot=Snapshot(key,10,20,time.monotonic(),'1.1.12.20',{'barbarian_pending':True,
            'barbarian_paid_attacks':2,'barbarian_phase':'returning'})
        now=time.monotonic();controller._completed(key,1,('task',key,'barbarians',snapshot,None),None)
        assert now+4<=controller._due[(key,'barbarians')]<=now+7
        assert 'возврат армии' in controller.reasons[key] and 'платных атак: 2' in controller.reasons[key]
        complete=replace(snapshot,values={'barbarian_session_completed':True,'barbarian_paid_attacks':2})
        now=time.monotonic();controller._completed(key,2,('task',key,'barbarians',complete,None),None)
        assert now+599<=controller._due[(key,'barbarians')]<=now+602
        assert 'заход завершён' in controller.reasons[key]
    finally:controller.shutdown()


def test_chain_journal_preserves_confirmed_free_victories_and_explains_missing_clusters(qtbot,tmp_path,monkeypatch):
    store=Store(tmp_path/'mirage.sqlite3');key='ld:test:1';store.save_profile(Profile(key))
    controller=Controller(store,auto_refresh=False)
    monkeypatch.setattr(controller.dispatcher,'acknowledge',lambda *args:True)
    try:
        snapshot=Snapshot(key,10,20,time.monotonic(),'1.1.12.20',{'barbarian_pending':True,
            'barbarian_paid_attacks':1,'barbarian_chain_free_defeated':2,'barbarian_phase':'field'})
        controller._completed(key,1,('task',key,'barbarian_chain',snapshot,None),None)
        assert 'платных атак: 1' in controller.reasons[key] and 'бесплатных побед: 2' in controller.reasons[key]
        assert store.events(1)[0][4]==controller.reasons[key]
        empty=replace(snapshot,values={'barbarian_no_cluster':True,'barbarian_chain_reason':'Нет свободного соседа в секторе'})
        controller._completed(key,2,('task',key,'barbarian_chain',empty,None),None)
        assert 'Нет свободного соседа в секторе' in controller.reasons[key]
    finally:controller.shutdown()


def test_only_chain_survey_gets_fast_retry_without_speeding_up_resource_gathering(qtbot,tmp_path,monkeypatch):
    store=Store(tmp_path/'mirage.sqlite3');key='ld:test:1'
    store.save_profile(Profile(key,tasks={'barbarian_chain':{'interval':600},'gather_resources':{'interval':600}}))
    controller=Controller(store,auto_refresh=False)
    monkeypatch.setattr(controller.dispatcher,'acknowledge',lambda *args:True)
    try:
        snapshot=Snapshot(key,10,20,time.monotonic(),'1.1.12.20',{'barbarian_pending':True,'barbarian_survey_pending':True})
        now=time.monotonic();controller._completed(key,1,('task',key,'barbarian_chain',snapshot,None),None)
        assert now+.8<=controller._due[(key,'barbarian_chain')]<=now+2
        now=time.monotonic();controller._completed(key,2,('task',key,'gather_resources',snapshot,None),None)
        assert now+599<=controller._due[(key,'gather_resources')]<=now+602
    finally:controller.shutdown()
