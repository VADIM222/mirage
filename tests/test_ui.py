from dataclasses import replace
from datetime import datetime
import threading
import time

import pytest
from PySide6.QtCore import Qt, QTimer

from mirage.controller import Controller
from mirage.model import Instance, Power, Profile, Provider, RunState, Slot, Snapshot
from mirage.storage import Store
from mirage.ui import SlotDialog, Window


def create(qtbot, tmp_path):
    store = Store(tmp_path / "mirage.db")
    controller = Controller(store, auto_refresh=False)
    first = Instance("bs:first", Provider.BLUESTACKS, "Pie64", "First", "C:/BS", "adb", "127.0.0.1:5555", Power.ONLINE,
                     cpus=2, memory_mb=2048)
    second = replace(first, id="bs:second", key="Other", name="Second", power=Power.OFF)
    controller.instances = [first, second]
    window = Window(store, controller)
    qtbot.addWidget(window)
    window.show()
    return store, controller, window


def test_barbarian_modes_have_independent_atomic_settings_and_reload_per_instance(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path);window.select_instance('bs:first')
    window.task_tree.setCurrentItem(window.task_items['barbarians'])
    window.barbarian_fields['reserve_ap'].setValue(300)
    store.update_profile('bs:first',lambda p:p.tasks['barbarians'].update(interval=123))
    window.barbarian_fields['max_battles'].setValue(4)
    window.task_tree.setCurrentItem(window.task_items['barbarian_chain'])
    assert window.barbarian_fields['reserve_ap'].value()==100
    window.barbarian_fields['reserve_ap'].setValue(500)
    assert store.profile('bs:first').tasks['barbarians']=={'reserve_ap':300,'interval':123,'max_battles':4}
    assert store.profile('bs:first').tasks['barbarian_chain']=={'reserve_ap':500}
    window.select_instance('bs:second');assert window.barbarian_fields['reserve_ap'].value()==100
    window.select_instance('bs:first');assert window.barbarian_fields['reserve_ap'].value()==500


def test_named_commander_pair_autosaves_and_primary_swap_clears_duplicate(qtbot,tmp_path):
    from test_commanders import roster
    store,controller,window=create(qtbot,tmp_path)
    controller.snapshots['bs:first']=Snapshot('bs:first',1,7,0,'1.1.12.20',{'player':{'_commanders':roster()}})
    window.select_instance('bs:first');window.task_tree.setCurrentItem(window.task_items['barbarians'])
    primary=window.barbarian_commanders['primary'];deputy=window.barbarian_commanders['deputy']
    assert 'Sun Tzu' in primary.currentText() and deputy.isEnabled()
    assert deputy.findData(3)==-1
    deputy.setCurrentIndex(deputy.findData(15))
    assert store.profile('bs:first').tasks['barbarians']['deputy']==15
    store.update_profile('bs:first',lambda p:p.tasks['barbarians'].update(interval=333))
    primary.setCurrentIndex(primary.findData(15))
    assert store.profile('bs:first').tasks['barbarians']=={'primary':15,'deputy':0,'interval':333}
    assert not deputy.isEnabled()
    window.task_tree.setCurrentItem(window.task_items['barbarian_chain'])
    assert primary.currentData()==3 and deputy.currentData()==0
    window.select_instance('bs:second');assert not primary.isEnabled()


def test_checkboxes_autosave_and_survive_instance_switch_and_refresh(qtbot, tmp_path):
    store, controller, window = create(qtbot, tmp_path)
    window.select_instance("bs:first")
    window.task_items["tavern"].setCheckState(0, Qt.CheckState.Checked)
    window.select_instance("bs:second")
    window.task_items["training"].setCheckState(0, Qt.CheckState.Checked)
    window.refresh()
    window.select_instance("bs:first")
    assert window.task_items["tavern"].checkState(0) == Qt.CheckState.Checked
    assert window.task_items["training"].checkState(0) == Qt.CheckState.Unchecked
    assert store.profile("bs:first").tasks["tavern"]["enabled"]
    assert store.profile("bs:second").tasks["training"]["enabled"]


def test_autosave_does_not_undo_manual_stop(qtbot, tmp_path):
    store, controller, window = create(qtbot, tmp_path)
    window.select_instance("bs:first")
    controller.stop("bs:first")
    window.task_items["tavern"].setCheckState(0, Qt.CheckState.Checked)
    assert store.profile("bs:first").manual_pause


def test_text_autosaves_each_edit_without_losing_remote_task_changes(qtbot, tmp_path):
    store, controller, window = create(qtbot, tmp_path)
    window.select_instance("bs:first")
    window.tabs.setCurrentIndex(2)
    store.update_profile("bs:first", lambda profile: profile.tasks.update(training={"enabled":True}))
    qtbot.keyClicks(window.account_name, "Farm1")
    assert store.profile("bs:first").account_name == "Farm1"
    assert store.profile("bs:first").tasks["training"]["enabled"]
    assert window.task_items["training"].checkState(0) == Qt.CheckState.Checked
    assert not hasattr(window, "save_button")


def test_training_options_autosave_and_preserve_other_remote_fields(qtbot, tmp_path):
    store, controller, window = create(qtbot,tmp_path)
    window.select_instance("bs:first")
    window.task_tree.setCurrentItem(window.task_items["training"])
    window.training_units[4].setChecked(True)
    window.training_count.setValue(12)
    window.training_tier.setValue(2)
    store.update_profile("bs:first",lambda profile:profile.tasks["training"].update(interval=777))
    window.training_reserves["1"].setValue(20000)
    settings = store.profile("bs:first").tasks["training"]
    assert settings == {"units":[4],"count":12,"tier":2,"interval":777,"reserves":{"1":20000}}
    window.select_instance("bs:second")
    assert not window.training_units[4].isChecked()
    window.select_instance("bs:first")
    assert window.training_units[4].isChecked() and window.training_count.value() == 12
    assert window.training_tier.value() == 2 and window.training_reserves["1"].value() == 20000


def test_training_start_requires_a_configured_type(qtbot,tmp_path):
    store,controller,window = create(qtbot,tmp_path)
    store.save_profile(Profile("bs:first",tasks={"training":{"enabled":True}}))
    assert not controller.start("bs:first")
    assert not store.profile("bs:first").manual_run
    assert "тип войск" in window.footer.text()


def test_donation_options_autosave_and_preserve_remote_interval(qtbot,tmp_path):
    store,controller,window = create(qtbot,tmp_path)
    window.select_instance("bs:first")
    window.task_tree.setCurrentItem(window.task_items["alliance_donate"])
    window.donation_goal.setValue(500)
    store.update_profile("bs:first",lambda profile:profile.tasks["alliance_donate"].update(interval=777))
    window.donation_reserves["2"].setValue(100000)
    assert store.profile("bs:first").tasks["alliance_donate"] == {
        "daily_goal":500,"interval":777,"reserves":{"2":100000}}
    window.select_instance("bs:second")
    assert window.donation_goal.value() == 100 and window.donation_reserves["2"].value() == 0
    window.select_instance("bs:first")
    assert window.donation_goal.value() == 500 and window.donation_reserves["2"].value() == 100000


def test_material_options_autosave_without_overwriting_remote_task_fields(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path)
    window.select_instance("bs:first")
    window.task_tree.setCurrentItem(window.task_items["materials"])
    window.material_item.setCurrentIndex(window.material_item.findData(417))
    store.update_profile("bs:first",lambda p:p.tasks["materials"].update(interval=777))
    window.material_limit.setValue(3)
    assert store.profile("bs:first").tasks["materials"]=={"item_id":417,"max_orders":3,"interval":777}
    window.select_instance("bs:second")
    assert window.material_item.currentData()==412 and window.material_limit.value()==5
    window.select_instance("bs:first")
    assert window.material_item.currentData()==417 and window.material_limit.value()==3


def test_gather_options_autosave_preserve_telegram_edits_and_reload_per_instance(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path)
    window.select_instance('bs:first')
    window.task_tree.setCurrentItem(window.task_items['gather_resources'])
    window.gather_fields['max_level'].setValue(5)
    store.update_profile('bs:first',lambda p:p.tasks['gather_resources'].update(interval=123))
    window.gather_fields['max_travel'].setValue(90)
    window.gather_resource.setCurrentIndex(window.gather_resource.findData(4))
    window.gather_fields['max_marches'].setValue(4)
    assert store.profile('bs:first').tasks['gather_resources']=={'max_level':5,'max_travel':90,'interval':123,'resource':4,'max_marches':4}
    window.select_instance('bs:second')
    assert window.gather_fields['max_level'].value()==8
    assert window.gather_resource.currentData()==1 and window.gather_fields['max_marches'].value()==1
    window.select_instance('bs:first')
    assert window.gather_fields['max_level'].value()==5 and window.gather_fields['max_travel'].value()==90
    assert window.gather_resource.currentData()==4 and window.gather_fields['max_marches'].value()==4


def test_building_limits_and_reserves_autosave_without_losing_remote_changes(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path)
    window.select_instance('bs:first')
    window.task_tree.setCurrentItem(window.task_items['buildings'])
    window.building_level.setValue(22)
    store.update_profile('bs:first',lambda p:p.tasks['buildings'].update(interval=777))
    window.building_reserves['2'].setValue(2000000)
    assert store.profile('bs:first').tasks['buildings']=={'max_level':22,'interval':777,'reserves':{'2':2000000}}
    window.select_instance('bs:second')
    assert window.building_level.value()==20 and window.building_reserves['2'].value()==0
    window.select_instance('bs:first')
    assert window.building_level.value()==22 and window.building_reserves['2'].value()==2000000
    window.building_types[1].setChecked(True)
    store.update_profile('bs:first',lambda p:p.tasks['buildings'].update(types=[1,6],interval=778))
    window.building_types[3].setChecked(True)
    assert store.profile('bs:first').tasks['buildings']['types']==[1,3,6]
    window.select_instance('bs:second')
    assert window.building_types[4].isChecked() and not window.building_types[1].isChecked()
    window.select_instance('bs:first')
    assert all(window.building_types[k].isChecked() for k in (1,3,6))
    assert not window.building_types[4].isChecked()
    assert store.profile('bs:first').tasks['buildings']['interval']==778
    window.building_packs.setChecked(True)
    assert store.profile('bs:first').tasks['buildings']['use_resource_packs'] is True
    assert store.profile('bs:first').tasks['buildings']['types']==[1,3,6]


def test_research_options_merge_remote_edits_and_reload_for_each_instance(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path);window.select_instance('bs:first')
    window.task_tree.setCurrentItem(window.task_items['research'])
    editor=window.research_priority
    editor.mode.setCurrentIndex(editor.mode.findData('military'))
    store.update_profile('bs:first',lambda p:p.tasks['research'].update(interval=777))
    table=editor.tables['military'];table.view.selectRow(2);table.up.click()
    window.research_level.setValue(3)
    window.research_reserves['1'].setValue(900)
    settings=store.profile('bs:first').tasks['research']
    assert settings['priority_mode']=='military' and settings['priority_orders']['military'][:3]==[201,203,202]
    assert settings['max_level']==3 and settings['interval']==777 and settings['reserves']=={'1':900}
    assert all(k>=200 for k in table.model.order) and table.model.rowCount()==43
    editor.mode.setCurrentIndex(editor.mode.findData('economy'))
    assert len(editor.tables['economy'].model.order)==28
    editor.mode.setCurrentIndex(editor.mode.findData('military'))
    assert editor.tables['military'].model.order[:3]==[201,203,202]
    window.select_instance('bs:second')
    assert editor.mode.currentData()=='economy' and window.research_level.value()==10
    window.select_instance('bs:first')
    assert editor.mode.currentData()=='military' and window.research_reserves['1'].value()==900
    assert editor.tables['military'].model.order[:3]==[201,203,202]


def test_expanded_research_tables_autosave_and_refresh_the_embedded_editor(qtbot,tmp_path):
    from PySide6.QtWidgets import QApplication
    from mirage.research_priority_ui import ResearchPriorityEditor
    store,controller,window=create(qtbot,tmp_path);window.select_instance('bs:first')
    window.task_tree.setCurrentItem(window.task_items['research'])
    def edit():
        dialog=QApplication.activeModalWidget();editor=dialog.findChild(ResearchPriorityEditor)
        editor.mode.setCurrentIndex(editor.mode.findData('custom'))
        table=editor.tables['custom'];table.view.selectRow(3);table.up.click()
        dialog.reject()
    QTimer.singleShot(0,edit);window.research_expand.click()
    settings=store.profile('bs:first').tasks['research']
    assert settings['priority_mode']=='custom' and settings['priority_orders']['custom'][:4]==[101,102,104,103]
    assert window.research_priority.tables['custom'].model.order[:4]==[101,102,104,103]


def test_supply_limit_autosaves_preserves_remote_fields_and_reloads_per_instance(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path)
    window.select_instance('bs:first')
    window.task_tree.setCurrentItem(window.task_items['supply_boxes'])
    window.supply_limit.setValue(2)
    store.update_profile('bs:first',lambda p:p.tasks['supply_boxes'].update(interval=111,enabled=True))
    window.supply_limit.setValue(4)
    assert store.profile('bs:first').tasks['supply_boxes']=={'max_boxes':4,'interval':111,'enabled':True}
    window.select_instance('bs:second');assert window.supply_limit.value()==1
    window.select_instance('bs:first');assert window.supply_limit.value()==4


def test_cave_box_limit_is_independent_and_merges_parallel_profile_edits(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path);window.select_instance('bs:first')
    window.task_tree.setCurrentItem(window.task_items['supply_boxes']);window.supply_limit.setValue(2)
    window.task_tree.setCurrentItem(window.task_items['cave_rewards']);window.supply_limit.setValue(3)
    store.update_profile('bs:first',lambda p:p.tasks['cave_rewards'].update(interval=333,enabled=True))
    window.supply_limit.setValue(4)
    assert store.profile('bs:first').tasks['cave_rewards']=={'max_boxes':4,'interval':333,'enabled':True}
    assert store.profile('bs:first').tasks['supply_boxes']['max_boxes']==2
    assert '7014' in window.supply_note.text()
    window.task_tree.setCurrentItem(window.task_items['supply_boxes']);assert window.supply_limit.value()==2


def test_vip_shop_options_merge_remote_edits_and_reload_per_instance(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path)
    window.select_instance('bs:first');window.task_tree.setCurrentItem(window.task_items['vip_shop'])
    window.vip_shop_item.setCurrentIndex(window.vip_shop_item.findData(8011))
    store.update_profile('bs:first',lambda p:p.tasks['vip_shop'].update(interval=777,enabled=True))
    window.vip_shop_fields['max_price'].setValue(10000)
    window.vip_shop_fields['reserve'].setValue(500000)
    assert store.profile('bs:first').tasks['vip_shop']=={
        'item_id':8011,'interval':777,'enabled':True,'max_price':10000,'reserve':500000}
    window.select_instance('bs:second');assert window.vip_shop_item.currentData()==124
    assert window.vip_shop_fields['max_price'].value()==12000
    window.select_instance('bs:first');assert window.vip_shop_item.currentData()==8011
    assert window.vip_shop_fields['reserve'].value()==500000


def test_lucerne_limit_merge_and_reload(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path)
    window.select_instance('bs:first');window.task_tree.setCurrentItem(window.task_items['lucerne'])
    window.lucerne_limit.setValue(3)
    store.update_profile('bs:first',lambda p:p.tasks['lucerne'].update(interval=999))
    window.lucerne_limit.setValue(5)
    assert store.profile('bs:first').tasks['lucerne']=={'max_claims':5,'interval':999}
    window.select_instance('bs:second');assert window.lucerne_limit.value()==32
    window.select_instance('bs:first');assert window.lucerne_limit.value()==5


def test_tutorial_limit_merge_reload_and_supported_boundary(qtbot,tmp_path):
    store,controller,window=create(qtbot,tmp_path)
    window.select_instance('bs:first');window.task_tree.setCurrentItem(window.task_items['tutorial'])
    window.tutorial_limit.setValue(3)
    store.update_profile('bs:first',lambda p:p.tasks['tutorial'].update(interval=999))
    window.tutorial_limit.setValue(5)
    assert store.profile('bs:first').tasks['tutorial']=={'max_actions':5,'interval':999}
    assert 'частично' in window.task_description.text()
    window.select_instance('bs:second');assert window.tutorial_limit.value()==8
    window.select_instance('bs:first');assert window.tutorial_limit.value()==5


@pytest.mark.parametrize("task,setting,should_cancel",[("training","count",True),("training","tier",True),
    ("training","interval",False),("alliance_donate","daily_goal",True),("alliance_donate","reserves",True),
    ("alliance_donate","interval",False),("materials","item_id",True),("materials","max_orders",True),
    ("materials","interval",False),("gather_resources","max_level",True),
    ("gather_resources","max_travel",True),("gather_resources","resource",True),
    ("gather_resources","max_marches",True),("gather_resources","interval",False),
    ("buildings","max_level",True),("buildings","reserves",True),("buildings","interval",False),
    ("supply_boxes","max_boxes",True),("supply_boxes","interval",False),
    ("vip_shop","item_id",True),("vip_shop","max_price",True),("vip_shop","reserve",True),("vip_shop","interval",False),
    ("lucerne","max_claims",True),("lucerne","interval",False),
    ('tutorial','max_actions',True),('tutorial','interval',False)])
def test_task_edits_cancel_old_configuration_but_interval_does_not(qtbot,tmp_path,monkeypatch,task,setting,should_cancel):
    from mirage.workflows import Cancelled
    store,controller,window = create(qtbot,tmp_path)
    key = "bs:first"
    controller.instances[0] = replace(controller.instances[0],width=960,height=540)
    store.save_profile(Profile(key,manual_run=True,tasks={task:{"enabled":True,
        **({"units":[4],"count":1} if task == "training" else {})}}))
    entered,release = threading.Event(),threading.Event()
    permitted = []
    state = Snapshot(key,10,20,time.monotonic(),"1.1.12.20",{"player":{"PlayerID":20}})
    class Reader:
        adb = object()
        def close(self): pass
    class Engine:
        def __init__(self,*args,allowed,**kwargs): self.allowed = allowed
        def execute(self,*args,**kwargs):
            entered.set()
            assert release.wait(3)
            permitted.append(self.allowed())
            if not permitted[-1]: raise Cancelled("settings changed")
            return replace(state,captured_at=time.monotonic())
    monkeypatch.setattr("mirage.controller.Engine",Engine)
    controller.readers[key] = Reader()
    controller.snapshots[key] = state
    controller._last_memory_poll = time.monotonic()
    try:
        controller.tick()
        qtbot.waitUntil(entered.is_set)
        store.update_profile(key,lambda profile:profile.tasks[task].update({setting:
            {"2":2000} if setting == "reserves" else (58 if task=='vip_shop' else 413) if setting == "item_id" else 2}))
        release.set()
        qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
        assert permitted == [not should_cancel]
        assert key not in controller._task_errors
        if should_cancel:
            assert controller._due.get((key,task),0) <= time.monotonic()
    finally:
        release.set()


def test_live_task_observations_keep_a_long_workflow_fresh(qtbot,tmp_path,monkeypatch):
    store,controller,window = create(qtbot,tmp_path)
    key = "bs:first"
    controller.instances[0] = replace(controller.instances[0],width=960,height=540)
    store.save_profile(Profile(key,manual_run=True,tasks={"alliance_help":{"enabled":True}}))
    entered,release = threading.Event(),threading.Event()
    state = Snapshot(key,10,20,time.monotonic(),"1.1.12.20",{"player":{"PlayerID":20}})
    cancelled_at_completion = []
    class Reader:
        adb = object()
        def snapshot(self): return state
        def close(self): pass
    class Engine:
        def __init__(self,*args,on_observed,**kwargs): self.on_observed = on_observed
        def execute(self,workflow,cancelled,**kwargs):
            self.on_observed(state)
            entered.set()
            assert release.wait(3)
            cancelled_at_completion.append(cancelled.is_set())
            return state
    monkeypatch.setattr("mirage.controller.Engine",Engine)
    controller.readers[key] = Reader()
    controller.snapshots[key] = state
    controller._last_memory_poll = time.monotonic()
    try:
        controller.tick()
        qtbot.waitUntil(entered.is_set)
        controller.snapshots[key] = replace(state,captured_at=time.monotonic()-20)
        read_profile = store.profile
        def publish_during_tick(instance_id):
            profile = read_profile(instance_id)
            if instance_id == key:
                controller._active_observations[key][0] = replace(state,captured_at=time.monotonic())
            return profile
        monkeypatch.setattr(store,"profile",publish_during_tick)
        controller.tick()
        assert controller.decisions[key].state == RunState.RUNNING
        assert controller.snapshots[key].captured_at >= state.captured_at
        monkeypatch.setattr(store,"profile",read_profile)
        release.set()
        qtbot.waitUntil(lambda:not controller.dispatcher.busy(key))
        assert cancelled_at_completion == [False]
        assert key not in controller._active_observations
    finally:
        release.set()


def test_rotation_edits_save_automatically_and_reflect_remote_settings(qtbot, tmp_path):
    store, controller, window = create(qtbot, tmp_path)
    window.rotation_members.item(0).setCheckState(Qt.CheckState.Checked)
    window.rotation_parallel.setValue(2)
    assert store.preference("rotation")["members"] == ["bs:first"]
    assert store.preference("rotation")["parallel"] == 2
    store.set_preference("rotation", {"members":["bs:second"], "parallel":1, "duration":2700})
    window.refresh()
    assert window.rotation_members.item(0).checkState() == Qt.CheckState.Unchecked
    assert window.rotation_members.item(1).checkState() == Qt.CheckState.Checked
    assert window.rotation_duration.value() == 45


def test_slot_editor_autosaves_only_valid_times(qtbot, tmp_path):
    from mirage.model import Slot
    saved = []
    dialog = SlotDialog(Slot("slot", "08:00", "12:00", ()), on_change=saved.append)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.start.selectAll()
    qtbot.keyClicks(dialog.start, "09:00")
    assert saved[-1].start == "09:00"
    count = len(saved)
    dialog.end.selectAll()
    qtbot.keyClicks(dialog.end, "25:00")
    assert len(saved) == count


def test_low_memory_blocks_task_start_and_launch(qtbot, tmp_path, monkeypatch):
    store, controller, window = create(qtbot, tmp_path)
    controller.instances[0] = replace(controller.instances[0], memory_mb=1536, power=Power.OFF)
    store.save_profile(Profile("bs:first", tasks={"alliance_help":{"enabled":True}}))
    calls = []
    monkeypatch.setattr("mirage.controller.launch", lambda instance: calls.append(instance.id))
    assert not controller.start("bs:first")
    assert not controller.launch("bs:first")
    assert not calls
    assert "2 ГБ" in window.footer.text()


def test_telegram_token_autosaves_encrypted_without_button(qtbot, tmp_path):
    from mirage.secrets import decrypt
    store, controller, window = create(qtbot, tmp_path)
    window.navigate("telegram")
    token = "12345678:" + "a" * 35
    qtbot.keyClicks(window.telegram_token, token)
    qtbot.waitUntil(lambda: bool(store.preference("telegram_secret")))
    secret = store.preference("telegram_secret")
    assert token not in secret
    assert decrypt(secret) == token
    assert window.telegram_token.text() == ""
    assert not hasattr(window, "cloudflared_path")


def test_unverified_game_tasks_cannot_be_reported_running(qtbot, tmp_path):
    store, controller, window = create(qtbot, tmp_path)
    window.select_instance("bs:first")
    window.task_items["gather_gems"].setCheckState(0, Qt.CheckState.Checked)
    window.start_tasks()
    assert not store.profile("bs:first").manual_run
    assert "не прошли живую проверку" in window.footer.text()


def test_slow_adapter_runs_off_gui_thread_and_cancel_discards_result(qtbot, tmp_path, monkeypatch):
    store, controller, window = create(qtbot, tmp_path)
    gate = threading.Event()
    entered = threading.Event()
    closed = threading.Event()

    class FakeReader:
        def __init__(self, instance, server):
            self.instance = instance

        def connect(self):
            entered.set()
            gate.wait(3)

        def snapshot(self):
            return Snapshot(self.instance.id, 10, 20, time.monotonic(), "1.1.12.20", {"player": {"PlayerID":20}})

        def close(self):
            closed.set()

    monkeypatch.setattr("mirage.controller.Reader", FakeReader)
    controller.probe("bs:first")
    qtbot.waitUntil(entered.is_set)
    pulses = []
    QTimer.singleShot(0, lambda: pulses.append(True))
    qtbot.waitUntil(lambda: bool(pulses))
    controller.stop("bs:first")
    gate.set()
    qtbot.waitUntil(closed.is_set)
    qtbot.waitUntil(lambda: not controller.dispatcher.busy("bs:first"))
    assert "bs:first" not in controller.snapshots


def test_off_instance_does_not_touch_adb(qtbot, tmp_path, monkeypatch):
    store, controller, window = create(qtbot, tmp_path)
    attempts = []
    monkeypatch.setattr("mirage.controller.Reader", lambda *args: attempts.append(args))
    controller.probe("bs:second")
    assert not attempts
    assert "запустите" in window.footer.text()


def test_concurrent_launch_requests_reserve_device_capacity(qtbot, tmp_path, monkeypatch):
    store, controller, window = create(qtbot, tmp_path)
    store.set_preference("device_limit", 2)
    second = replace(controller.instances[1], cpus=2)
    third = replace(second, id="bs:third", key="Third")
    controller.instances = [controller.instances[0], second, third]
    gate = threading.Event()
    attempts = []
    def launch(instance):
        attempts.append(instance.id)
        gate.wait(3)
    monkeypatch.setattr("mirage.controller.launch", launch)
    try:
        controller.launch(second.id)
        controller.launch(third.id)
        qtbot.waitUntil(lambda: bool(attempts))
        assert attempts == [second.id]
        assert "лимит" in window.footer.text()
    finally:
        gate.set()
    qtbot.waitUntil(lambda: controller.dispatcher.busy(second.id) is False)


def test_close_request_waits_for_cancelled_job_before_closing(qtbot, tmp_path, monkeypatch):
    store, controller, window = create(qtbot, tmp_path)
    entered = threading.Event()
    release = threading.Event()
    operations = []
    def job(cancelled):
        entered.set()
        release.wait(3)
        operations.append("job_finished")
        return "cancelled",
    monkeypatch.setattr("mirage.controller.close", lambda instance: operations.append("closed"))
    controller._submit("bs:first", job)
    qtbot.waitUntil(entered.is_set)
    controller.close_instance("bs:first")
    assert operations == []
    release.set()
    qtbot.waitUntil(lambda: not controller.dispatcher.busy("bs:first"))
    controller.tick()
    qtbot.waitUntil(lambda: "closed" in operations)
    assert operations == ["job_finished", "closed"]


def test_rotation_needs_explicit_enable_and_stop_pauses_member(qtbot, tmp_path, monkeypatch):
    store, controller, window = create(qtbot, tmp_path)
    controller.instances = [replace(i, cpus=2) for i in controller.instances]
    store.set_preference("rotation", {"members": ["bs:first", "bs:second"], "parallel": 1, "duration": 60})
    calls = []
    monkeypatch.setattr("mirage.controller.launch", lambda instance: calls.append(instance.id))
    controller.tick()
    assert not calls
    controller.enable_rotation()
    controller.stop("bs:first")
    assert "bs:first" in controller.rotation.suspended
    assert not calls


def test_shutdown_cleans_reader_waiting_in_queued_completion(qtbot, tmp_path):
    store, controller, window = create(qtbot, tmp_path)
    finished = threading.Event()
    closed = threading.Event()
    release = threading.Event()
    class Reader:
        def close(self):
            closed.set()
    resource = Reader()
    def job(cancelled):
        release.wait(3)
        return "memory", "bs:first", resource, None
    # Await delivery to the Qt queue without pumping its event loop.
    controller.dispatcher.submit("bs:first", job,
        lambda key,generation,result,error: (controller.job_finished.emit(key,generation,result,error), finished.set()))
    release.set()
    assert finished.wait(3)
    assert not closed.is_set()
    controller.shutdown()
    assert closed.is_set()


def test_long_tasks_do_not_starve_other_due_tasks(qtbot, tmp_path, monkeypatch):
    store, controller, window = create(qtbot, tmp_path)
    key = "bs:first"
    tasks = ("training", "tavern", "city_resources", "alliance_help")
    store.save_profile(Profile(key, manual_run=True,
        tasks={task:{"enabled":True,"interval":30} for task in tasks}))
    now = time.monotonic()
    controller.snapshots[key] = Snapshot(key,10,20,now,"1.1.12.20",{"player":{"PlayerID":20}})
    controller._last_memory_poll = now
    # Early tasks became due again while a long harvest was running.
    controller._due.update({(key,"training"):now-60,(key,"tavern"):now-50,
                            (key,"city_resources"):now+30})
    selected = []
    def execute(instance, task, profile, slot_id):
        selected.append(task)
        controller._due[(key,task)] = now+60
    monkeypatch.setattr(controller,"_execute",execute)
    controller.tick()
    controller.tick()
    controller.tick()
    assert selected == ["alliance_help", "training", "tavern"]


def test_open_menu_defers_help_then_recovers_without_manual_restart(qtbot, tmp_path):
    store, controller, window = create(qtbot, tmp_path)
    controller.instances[0] = replace(controller.instances[0], width=960, height=540)
    store.save_profile(Profile("bs:first", manual_run=True, tasks={"alliance_help":{"enabled":True}}))
    values = {"player":{"PlayerID":20,"AllianceID":10}, "hud_visible":True, "hud_menu":True,
              "queue_panel":{"known":True,"visible":False},
              "city_selection_known":True,"city_selection":None,"vip_visible":False,
              "in_city":True, "city_enabled":True, "views":{"MapHudPanel":True}, "alliance_help_count":0}
    class Reader:
        def snapshot(self):
            return Snapshot("bs:first", 10, 20, time.monotonic(), "1.1.12.20", values)
        def close(self):
            pass
    resource = Reader()
    resource.adb = object()  # No tap is needed when help count is already zero.
    controller.readers["bs:first"] = resource
    controller.snapshots["bs:first"] = resource.snapshot()
    controller._last_memory_poll = time.monotonic()
    controller.tick()
    qtbot.waitUntil(lambda: "bs:first" in controller._waiting_game)
    controller.tick()
    assert controller.decisions["bs:first"].state == RunState.WAIT_GAME
    assert "bs:first" not in controller._task_errors
    values["hud_menu"] = False
    controller._due[("bs:first", "alliance_help")] = 0
    controller.tick()
    qtbot.waitUntil(lambda: "bs:first" not in controller._waiting_game)
    assert store.profile("bs:first").manual_run


@pytest.mark.parametrize("explicit_stop", [True, False])
def test_interrupted_daily_interval_task_retries_on_resume(qtbot, tmp_path, monkeypatch, explicit_stop):
    store, controller, window = create(qtbot, tmp_path)
    key = "bs:first"
    controller.instances[0] = replace(controller.instances[0], width=960, height=540)
    current = [datetime(2026, 11, 9, 10, 30)]
    class Clock:
        @staticmethod
        def now():
            return current[0]
    monkeypatch.setattr("mirage.controller.datetime", Clock)
    profile = Profile(key, manual_run=True, tasks={"alliance_help":{"enabled":True,"interval":86400}})
    if not explicit_stop:
        profile.manual_run = False
        profile.schedule_enabled = True
        profile.slots = [Slot("day", "10:00", "11:00", ("alliance_help",))]
    store.save_profile(profile)
    entered, release = threading.Event(), threading.Event()
    values = {"player":{"PlayerID":20,"AllianceID":10}, "hud_visible":True, "hud_menu":False,
              "queue_panel":{"known":True,"visible":False},
              "city_selection_known":True,"city_selection":None,"vip_visible":False,
              "in_city":True, "city_enabled":True, "views":{"MapHudPanel":True}, "alliance_help_count":0}
    class Reader:
        calls = 0
        adb = object()  # Already handled rewards must not generate another input.
        def snapshot(self):
            self.calls += 1
            if self.calls == 2:
                entered.set()
                assert release.wait(3)
            return Snapshot(key, 10, 20, time.monotonic(), "1.1.12.20", values)
        def close(self):
            pass
    reader = Reader()
    controller.readers[key] = reader
    controller.snapshots[key] = reader.snapshot()
    controller._last_memory_poll = time.monotonic()
    try:
        controller.tick()
        qtbot.waitUntil(entered.is_set)
        if explicit_stop:
            controller.stop(key)
        else:
            # The slot expires in the worker before the next GUI tick cancels its ticket.
            current[0] = datetime(2026, 11, 9, 11, 0)
        release.set()
        qtbot.waitUntil(lambda: not controller.dispatcher.busy(key))
        assert key not in controller._task_errors
        assert controller._due.get((key, "alliance_help"), 0) <= time.monotonic()
        finished_at = time.monotonic()
        if explicit_stop:
            assert controller.start(key)
        else:
            controller.tick()
            assert controller.decisions[key].state == RunState.WAIT_SLOT
            current[0] = datetime(2026, 11, 10, 10, 0)
            controller.tick()
        qtbot.waitUntil(lambda: controller._due.get((key, "alliance_help"), 0) > finished_at)
        assert controller._due[(key, "alliance_help")] >= finished_at + 86400
        assert not any(event[3] == "error" for event in store.events())
        calls = reader.calls
        controller.tick()
        assert reader.calls == calls
    finally:
        release.set()
