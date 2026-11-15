from dataclasses import replace
import json
import os
import threading

import httpx
import pytest

from mirage.model import Instance, Power, Profile, Provider, Slot
from mirage.secrets import decrypt, encrypt, redact
from mirage.storage import Store
from mirage.telegram import Api, Router, Service, TelegramError


TOKEN = "12345678:" + "a" * 35


class Recorder:
    def __init__(self):
        self.calls = []

    def call(self, method, values=None, photo=None):
        self.calls.append((method, values, photo))
        return {}


class Backend:
    def __init__(self):
        self.actions = []
        self.farm = Instance("ld:abc:1", Provider.LDPLAYER, "1", "Ферма", "C:/LD", "adb", "127.0.0.1:5557", Power.ONLINE)

    def instances(self):
        return [self.farm]

    def start(self, key):
        self.actions.append(("start", key))
        return "Принято"

    def stop(self, key):
        self.actions.append(("stop", key))
        return "Пауза"

    def screenshot(self, key):
        return b"PNG"

    def status(self, key):
        return "Остановлено"

    def rotation(self, enabled):
        self.actions.append(("rotation", enabled))
        return "Принято"


def message(user, text, *, chat_type="private"):
    return {"message":{"from":{"id":user},"chat":{"id":user,"type":chat_type},"text":text}}


def callback(user, data):
    return {"callback_query":{"id":"click","from":{"id":user},"data":data,
                              "message":{"chat":{"id":user,"type":"private"}}}}


def setup(tmp_path):
    store = Store(tmp_path / "mirage.db")
    recorder = Recorder()
    backend = Backend()
    router = Router(recorder, store, backend)
    return store, recorder, backend, router


def test_barbarian_modes_validate_independent_parameters_and_preserve_desktop_changes(tmp_path):
    store,api,backend,router=setup(tmp_path);key=backend.farm.id;store.set_preference('telegram_owner',10)
    router.handle(callback(10,'barbarians:'+key))
    button=next(button for row in api.calls[-1][1]['reply_markup']['inline_keyboard'] for button in row
        if button['text'].startswith('Резерв AP:'))
    router.handle(callback(10,button['callback_data']));router.handle(message(10,'10001'))
    assert router.pending is not None and not store.profile(key).tasks.get('barbarians')
    store.update_profile(key,lambda p:p.tasks.update(barbarians={'interval':321},barbarian_chain={'reserve_ap':777}))
    router.handle(message(10,'500'))
    assert store.profile(key).tasks['barbarians']=={'interval':321,'reserve_ap':500}
    assert store.profile(key).tasks['barbarian_chain']=={'reserve_ap':777}
    router.handle(callback(10,'barbarianchain:'+key))
    assert any('Резерв AP: 777'==button['text'] for row in api.calls[-1][1]['reply_markup']['inline_keyboard'] for button in row)


def test_named_pair_buttons_recheck_account_and_preserve_other_settings(tmp_path):
    from test_commanders import roster
    store,api,backend,router=setup(tmp_path);key=backend.farm.id;store.set_preference('telegram_owner',10)
    store.set_preference('commander-roster:'+key,roster())
    def button(prefix):
        return next(b['callback_data'] for row in api.calls[-1][1]['reply_markup']['inline_keyboard'] for b in row if b['text'].startswith(prefix))
    router.handle(callback(10,'barbarians:'+key));router.handle(callback(10,button('Второй:')))
    pick=button('Joan of Arc')
    store.update_profile(key,lambda p:p.tasks.update(barbarians={'interval':444}))
    router.handle(callback(10,pick));assert store.profile(key).tasks['barbarians']=={'deputy':15,'interval':444}
    router.handle(callback(10,button('Основной:')));stale=button('Joan of Arc')
    store.set_preference('commander-roster:'+key,roster(8))
    router.handle(callback(10,stale));assert store.profile(key).tasks['barbarians']['deputy']==15
    router.handle(callback(10,'barbarians:'+key));router.handle(callback(10,button('Основной:')))
    router.handle(callback(10,button('Joan of Arc')))
    assert store.profile(key).tasks['barbarians']=={'primary':15,'deputy':0,'interval':444}
    assert 'barbarian_chain' not in store.profile(key).tasks


def test_only_explicit_pairing_code_binds_owner(tmp_path):
    store, api, backend, router = setup(tmp_path)
    router.handle(message(10, "/start"))
    assert store.preference("telegram_owner") is None
    router.handle(message(10, "/start " + router.pair_code))
    assert store.preference("telegram_owner") == 10
    router.handle(callback(99, "stop:ld:abc:1"))
    assert not backend.actions
    router.handle(callback(10, "stop:ld:abc:1"))
    assert backend.actions == [("stop", "ld:abc:1")]


def test_vip_shop_atomic_settings_validation_and_cancel(tmp_path):
    store,api,backend,router=setup(tmp_path);key=backend.farm.id
    store.set_preference('telegram_owner',10)
    router.handle(callback(10,'vipshop:'+key))
    row=api.calls[-1][1]['reply_markup']['inline_keyboard'][2][0]
    router.handle(callback(10,row['callback_data']))
    assert store.profile(key).tasks['vip_shop']['item_id']==8011
    router.handle(callback(10,'vipprice:'+key));router.handle(message(10,'0'))
    assert router.pending is not None and 'max_price' not in store.profile(key).tasks['vip_shop']
    store.update_profile(key,lambda p:p.tasks['vip_shop'].update(interval=333,enabled=True))
    router.handle(message(10,'10000'))
    router.handle(callback(10,'vipreserve:'+key));router.handle(message(10,'500000'))
    assert store.profile(key).tasks['vip_shop']=={
        'item_id':8011,'max_price':10000,'reserve':500000,'interval':333,'enabled':True}
    router.handle(callback(10,'vipprice:'+key));router.handle(message(10,'/cancel'))
    assert router.pending is None and store.profile(key).tasks['vip_shop']['max_price']==10000


def test_lucerne_limit_validation_merges_desktop_changes(tmp_path):
    store,api,backend,router=setup(tmp_path);key=backend.farm.id
    store.set_preference('telegram_owner',10)
    router.handle(callback(10,'lucernelimit:'+key));router.handle(message(10,'33'))
    assert router.pending is not None and not store.profile(key).tasks.get('lucerne')
    store.update_profile(key,lambda p:p.tasks.setdefault('lucerne',{}).update(interval=444,enabled=True))
    router.handle(message(10,'5'))
    assert router.pending is None and store.profile(key).tasks['lucerne']=={'max_claims':5,'interval':444,'enabled':True}


def test_building_type_callbacks_merge_desktop_edits_and_allow_empty_choice(tmp_path):
    store,api,backend,router=setup(tmp_path);key=backend.farm.id
    store.set_preference('telegram_owner',10)
    router.handle(callback(10,'buildings:'+key))
    rows=api.calls[-1][1]['reply_markup']['inline_keyboard']
    town=rows[0][0]['callback_data'];quarry=rows[3][0]['callback_data']
    store.update_profile(key,lambda p:p.tasks.setdefault('buildings',{}).update(types=[4,6],interval=333))
    router.handle(callback(10,town))
    assert store.profile(key).tasks['buildings']=={'types':[1,4,6],'interval':333}
    router.handle(callback(10,quarry))
    assert store.profile(key).tasks['buildings']['types']==[1,6]
    store.update_profile(key,lambda p:p.tasks['buildings'].update(types=[1]))
    router.handle(callback(10,town))
    assert store.profile(key).tasks['buildings']['types']==[]
    router.handle(callback(10,'buildpacks:'+key))
    assert store.profile(key).tasks['buildings']=={'types':[],'interval':333,'use_resource_packs':True}


def test_research_callbacks_merge_desktop_edits_and_validate_reserves(tmp_path):
    store,api,backend,router=setup(tmp_path);key=backend.farm.id;store.set_preference('telegram_owner',10)
    router.handle(callback(10,'research:'+key))
    rows=api.calls[-1][1]['reply_markup']['inline_keyboard'];first=rows[0][0]['callback_data']
    store.update_profile(key,lambda p:p.tasks.setdefault('research',{}).update(types=[103],interval=321))
    router.handle(callback(10,first))
    settings=store.profile(key).tasks['research']
    assert settings['priority_mode']=='economy' and settings['interval']==321
    assert settings['priority_orders']['custom'][0]==103 and len(settings['priority_orders']['custom'])==71
    router.handle(callback(10,'researchlevel:'+key));router.handle(message(10,'3'))
    router.handle(callback(10,'researchreserves:'+key));router.handle(message(10,'100 200 300 400'))
    settings=store.profile(key).tasks['research']
    assert settings['priority_mode']=='economy' and settings['interval']==321 and settings['max_level']==3
    assert settings['reserves']=={'1':100,'2':200,'3':300,'4':400}
    router.handle(callback(10,'researchlevel:'+key));router.handle(message(10,'11'))
    assert router.pending is not None and store.profile(key).tasks['research']['max_level']==3


def test_research_remote_priority_move_is_branch_local_and_keeps_desktop_changes(tmp_path):
    from mirage.model import ResearchOptions
    store,api,backend,router=setup(tmp_path);key=backend.farm.id;store.set_preference('telegram_owner',10)
    store.update_profile(key,lambda p:p.tasks.update(research={'priority_mode':'balanced','interval':654}))
    router.research_order_menu(10,key,'balanced','military')
    rows=api.calls[-1][1]['reply_markup']['inline_keyboard']
    move=next(b['callback_data'] for row in rows for b in row if b['text']=='В начало 3')
    store.update_profile(key,lambda p:p.tasks['research'].update(reserves={'1':900}))
    router.handle(callback(10,move))
    settings=store.profile(key).tasks['research'];options=ResearchOptions.from_settings(settings)
    assert [k for k in options.order_for('balanced') if k>=200][:3]==[203,201,202]
    assert [k for k in options.order_for('balanced') if k<200]==list(range(101,129))
    assert settings['interval']==654 and settings['reserves']=={'1':900}
    router.research_order_menu(10,key,'balanced','military',5)
    text=api.calls[-1][1]['text']
    assert '6/6' in text and '43.' in text


def test_tutorial_limit_validation_preserves_other_profile_changes(tmp_path):
    store,api,backend,router=setup(tmp_path);key=backend.farm.id
    store.set_preference('telegram_owner',10)
    router.handle(callback(10,'tutoriallimit:'+key));router.handle(message(10,'33'))
    assert router.pending is not None and not store.profile(key).tasks.get('tutorial')
    store.update_profile(key,lambda p:p.tasks.setdefault('tutorial',{}).update(interval=444,enabled=True))
    router.handle(message(10,'5'))
    assert router.pending is None and store.profile(key).tasks['tutorial']=={'max_actions':5,'interval':444,'enabled':True}


def test_groups_cannot_bind_or_execute_commands(tmp_path):
    store, api, backend, router = setup(tmp_path)
    router.handle(message(10, "/start " + router.pair_code, chat_type="group"))
    assert store.preference("telegram_owner") is None
    assert not api.calls


def test_schedule_editor_keeps_slot_identity_and_rejects_overlap(tmp_path):
    store, api, backend, router = setup(tmp_path)
    store.set_preference("telegram_owner", 10)
    store.save_profile(Profile(backend.farm.id, slots=[Slot("first","08:00","12:00",("tavern",)), Slot("second","12:00","20:00",())]))
    router.schedule(10, backend.farm.id)
    first_alias = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    router.handle(callback(10, first_alias))
    router.handle(message(10, "07:00 13:00"))
    assert store.profile(backend.farm.id).slots[0].start == "08:00"
    assert router.pending is not None
    router.handle(message(10, "07:00 12:00"))
    result = next(s for s in store.profile(backend.farm.id).slots if s.id == "first")
    assert result.start == "07:00"
    assert result.tasks == ("tavern",)


def test_deleted_slot_callback_does_not_crash_service(tmp_path):
    store, api, backend, router = setup(tmp_path)
    store.set_preference("telegram_owner", 10)
    store.save_profile(Profile(backend.farm.id, slots=[Slot("first","08:00","12:00",())]))
    router.schedule(10, backend.farm.id)
    alias = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    store.save_profile(Profile(backend.farm.id))
    router.handle(callback(10, alias))
    assert "уже удалён" in api.calls[-1][1]["text"]


def test_api_rejects_bad_responses_without_leaking_token():
    transport = httpx.MockTransport(lambda request: httpx.Response(401, request=request))
    with httpx.Client(transport=transport) as client:
        api = Api(TOKEN, client)
        with pytest.raises(TelegramError) as error:
            api.call("getMe")
        assert TOKEN not in str(error.value)
        assert "<telegram-token>" in str(error.value)


def test_photo_upload_uses_multipart_and_owner_chat():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"ok":True,"result":{"message_id":1}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        Api(TOKEN, client).call("sendPhoto", {"chat_id":10}, b"example")
    assert requests[0].headers["content-type"].startswith("multipart/form-data")
    assert b"example" in requests[0].content


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI")
def test_windows_secret_roundtrip():
    protected = encrypt(TOKEN)
    assert TOKEN not in protected
    assert decrypt(protected) == TOKEN


def test_redaction_does_not_depend_on_exception_type():
    assert TOKEN not in redact("failed https://api.telegram.org/bot" + TOKEN + "/sendMessage")


def test_task_toggle_interval_and_preset_apply_share_profile_storage(tmp_path):
    store, api, backend, router = setup(tmp_path)
    store.set_preference("telegram_owner", 10)
    router.handle(callback(10, "tasks:" + backend.farm.id))
    row = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0]
    router.handle(callback(10, row[0]["callback_data"]))
    assert store.profile(backend.farm.id).tasks["alliance_help"]["enabled"]
    router.handle(callback(10, row[1]["callback_data"]))
    router.handle(message(10, "120"))
    assert store.profile(backend.farm.id).tasks["alliance_help"]["interval"] == 120
    router.handle(callback(10, "savepreset:" + backend.farm.id))
    router.handle(message(10, "Telegram farm"))
    assert store.presets() == ["Telegram farm"]
    router.handle(callback(10, "presets:" + backend.farm.id))
    data = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    router.handle(callback(10, data))
    assert ("stop", backend.farm.id) in backend.actions
    assert store.profile(backend.farm.id).manual_pause


def test_rotation_configuration_requires_explicit_start(tmp_path):
    store, api, backend, router = setup(tmp_path)
    store.set_preference("telegram_owner", 10)
    router.handle(callback(10, "rotation"))
    data = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    router.handle(callback(10, data))
    router.handle(callback(10, "rotsettings"))
    router.handle(message(10, "3 45"))
    assert store.preference("rotation") == {"members":[backend.farm.id], "parallel":3, "duration":2700}
    assert not backend.actions
    router.handle(callback(10, "rotstart"))
    assert backend.actions == [("rotation", True)]


def test_training_menu_edits_preserve_desktop_settings_and_reject_invalid_values(tmp_path):
    store,api,backend,router = setup(tmp_path)
    store.set_preference("telegram_owner",10)
    key = backend.farm.id
    router.handle(callback(10,"training:"+key))
    rows = api.calls[-1][1]["reply_markup"]["inline_keyboard"]
    router.handle(callback(10,rows[3][0]["callback_data"]))
    assert store.profile(key).tasks["training"]["units"] == [4]
    rows = api.calls[-1][1]["reply_markup"]["inline_keyboard"]
    router.handle(callback(10,rows[4][1]["callback_data"]))
    store.update_profile(key,lambda profile:profile.tasks["training"].update(tier=2,enabled=True,interval=45))
    router.handle(message(10,"0"))
    assert router.pending is not None
    assert "count" not in store.profile(key).tasks["training"]
    router.handle(message(10,"12"))
    assert store.profile(key).tasks["training"] == {"units":[4],"tier":2,"enabled":True,"interval":45,"count":12}
    router.handle(callback(10,"trainreserves:"+key))
    router.handle(message(10,"1000 2000 3000 4000"))
    assert store.profile(key).tasks["training"]["reserves"] == {"1":1000,"2":2000,"3":3000,"4":4000}
    assert not backend.actions


def test_training_callbacks_are_owner_only_and_remain_under_telegram_limit(tmp_path):
    store,api,backend,router = setup(tmp_path)
    store.set_preference("telegram_owner",10)
    router.handle(callback(99,"training:"+backend.farm.id))
    assert not api.calls
    router.handle(callback(10,"training:"+backend.farm.id))
    buttons = [button for row in api.calls[-1][1]["reply_markup"]["inline_keyboard"] for button in row]
    assert all(len(button["callback_data"].encode("utf-8")) <= 64 for button in buttons)
    router.handle(callback(99,buttons[0]["callback_data"]))
    assert not store.profile(backend.farm.id).tasks


def test_donation_controls_are_owner_only_atomic_and_validated(tmp_path):
    store,api,backend,router = setup(tmp_path)
    store.set_preference("telegram_owner",10)
    key = backend.farm.id
    router.handle(callback(99,"donation:"+key))
    assert not api.calls
    router.handle(callback(10,"donation:"+key))
    buttons = [button for row in api.calls[-1][1]["reply_markup"]["inline_keyboard"] for button in row]
    assert all(len(button["callback_data"].encode()) <= 64 for button in buttons)
    router.handle(callback(10,"donategoal:"+key))
    store.update_profile(key,lambda profile:profile.tasks.setdefault("alliance_donate",{}).update(interval=45,enabled=True))
    router.handle(message(10,"0"))
    assert router.pending is not None
    assert "daily_goal" not in store.profile(key).tasks["alliance_donate"]
    router.handle(message(10,"500"))
    router.handle(callback(10,"donatereserves:"+key))
    router.handle(message(10,"10000 20000 30000 40000"))
    assert store.profile(key).tasks["alliance_donate"] == {"interval":45,"enabled":True,"daily_goal":500,
        "reserves":{"1":10000,"2":20000,"3":30000,"4":40000}}
    assert not backend.actions


def test_material_controls_are_owner_only_and_preserve_parallel_interval_edits(tmp_path):
    store,api,backend,router=setup(tmp_path)
    store.set_preference("telegram_owner",10)
    key=backend.farm.id
    router.handle(callback(99,"materials:"+key))
    assert not api.calls
    router.handle(callback(10,"materials:"+key))
    buttons=[button for row in api.calls[-1][1]["reply_markup"]["inline_keyboard"] for button in row]
    assert all(len(button["callback_data"].encode())<=64 for button in buttons)
    bone=next(button["callback_data"] for button in buttons if "Кость" in button["text"])
    store.update_profile(key,lambda p:p.tasks.setdefault("materials",{}).update(enabled=True,interval=75))
    router.handle(callback(10,bone))
    router.handle(callback(10,"matlimit:"+key))
    router.handle(message(10,"6"))
    assert router.pending is not None and "max_orders" not in store.profile(key).tasks["materials"]
    router.handle(message(10,"2"))
    assert store.profile(key).tasks["materials"]=={"item_id":414,"max_orders":2,"enabled":True,"interval":75}
    assert not backend.actions


def test_gather_controls_are_owner_only_validate_bounds_and_preserve_desktop_edits(tmp_path):
    store,api,backend,router=setup(tmp_path)
    store.set_preference('telegram_owner',10);key=backend.farm.id
    router.handle(callback(99,'gather:'+key));assert not api.calls
    router.handle(callback(10,'gather:'+key))
    buttons=[button for row in api.calls[-1][1]['reply_markup']['inline_keyboard'] for button in row]
    assert all(len(button['callback_data'].encode())<=64 for button in buttons)
    maximum=next(button['callback_data'] for button in buttons if button['text'].startswith('Максимум'))
    router.handle(callback(10,maximum))
    store.update_profile(key,lambda p:p.tasks.setdefault('gather_resources',{}).update(enabled=True,interval=100))
    router.handle(message(10,'9'))
    assert router.pending is not None and 'max_level' not in store.profile(key).tasks['gather_resources']
    router.handle(message(10,'4'))
    assert store.profile(key).tasks['gather_resources']=={'enabled':True,'interval':100,'max_level':4}
    router.handle(callback(10,'gather:'+key))
    buttons=[button for row in api.calls[-1][1]['reply_markup']['inline_keyboard'] for button in row]
    gold=next(button['callback_data'] for button in buttons if 'Золото' in button['text'])
    limit=next(button['callback_data'] for button in buttons if button['text'].startswith('Лимит'))
    router.handle(callback(99,gold))
    assert 'resource' not in store.profile(key).tasks['gather_resources']
    router.handle(callback(10,gold));router.handle(callback(10,limit))
    router.handle(message(10,'6'))
    assert router.pending is not None and 'max_marches' not in store.profile(key).tasks['gather_resources']
    router.handle(message(10,'5'))
    assert store.profile(key).tasks['gather_resources']=={'enabled':True,'interval':100,'max_level':4,'resource':4,'max_marches':5}
    assert not backend.actions


def test_building_controls_validate_owner_reserves_and_level_without_losing_interval(tmp_path):
    store,api,backend,router=setup(tmp_path)
    store.set_preference('telegram_owner',10);key=backend.farm.id
    router.handle(callback(99,'buildings:'+key));assert not api.calls
    router.handle(callback(10,'buildlevel:'+key))
    router.handle(message(10,'25'))
    assert router.pending is not None and 'max_level' not in store.profile(key).tasks.get('buildings',{})
    router.handle(message(10,'22'))
    store.update_profile(key,lambda p:p.tasks['buildings'].update(interval=111))
    router.handle(callback(10,'buildreserves:'+key))
    router.handle(message(10,'1000000 2000000 0 0'))
    assert store.profile(key).tasks['buildings']=={'max_level':22,'interval':111,
        'reserves':{'1':1000000,'2':2000000,'3':0,'4':0}}
    assert router.pending is None and not backend.actions


def test_supply_limit_is_owner_only_validated_and_preserves_parallel_edits(tmp_path):
    store,api,backend,router=setup(tmp_path)
    store.set_preference('telegram_owner',10);key=backend.farm.id
    router.handle(callback(99,'supply:'+key));assert not api.calls
    router.handle(callback(10,'supplylimit:'+key))
    router.handle(message(10,'11'))
    assert router.pending is not None and not store.profile(key).tasks.get('supply_boxes')
    store.update_profile(key,lambda p:p.tasks.setdefault('supply_boxes',{}).update(interval=123,enabled=True))
    router.handle(message(10,'3'))
    assert store.profile(key).tasks['supply_boxes']=={'interval':123,'enabled':True,'max_boxes':3}
    assert router.pending is None and not backend.actions
    router.handle(callback(10,'supplylimit:'+key));router.handle(message(10,'/cancel'))
    assert router.pending is None and store.profile(key).tasks['supply_boxes']['max_boxes']==3


def test_cave_box_limit_is_owner_only_validated_and_independent(tmp_path):
    store,api,backend,router=setup(tmp_path);store.set_preference('telegram_owner',10);key=backend.farm.id
    router.handle(callback(99,'caveboxes:'+key));assert not api.calls
    router.handle(callback(10,'cavelimit:'+key));router.handle(message(10,'11'))
    assert router.pending is not None and not store.profile(key).tasks.get('cave_rewards')
    store.update_profile(key,lambda p:p.tasks.setdefault('supply_boxes',{}).update(max_boxes=2))
    store.update_profile(key,lambda p:p.tasks.setdefault('cave_rewards',{}).update(interval=321,enabled=True))
    router.handle(message(10,'4'))
    assert store.profile(key).tasks['cave_rewards']=={'interval':321,'enabled':True,'max_boxes':4}
    assert store.profile(key).tasks['supply_boxes']['max_boxes']==2 and router.pending is None


def test_error_notifications_are_owner_only_redacted_and_deduplicated(tmp_path):
    store, api, backend, router = setup(tmp_path)
    store.set_preference("telegram_owner", 10)
    service = Service(store, backend)
    service.thread = threading.current_thread()
    service.api = api
    service.notify(backend.farm.id, "Failed " + TOKEN, "error")
    service.notify(backend.farm.id, "Failed " + TOKEN, "error")
    service._send_notifications()
    assert len(api.calls) == 1
    assert api.calls[0][1]["chat_id"] == 10
    assert TOKEN not in api.calls[0][1]["text"]


def test_slot_tasks_and_deletion_do_not_change_other_slot(tmp_path):
    store, api, backend, router = setup(tmp_path)
    store.set_preference("telegram_owner", 10)
    store.save_profile(Profile(backend.farm.id, slots=[Slot("first","08:00","12:00",()), Slot("second","12:00","20:00",("tavern",))]))
    router.schedule(10, backend.farm.id)
    data = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    router.handle(callback(10, data.replace("slot:", "slottasks:")))
    task = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    router.handle(callback(10, task))
    assert store.profile(backend.farm.id).slots[0].tasks == ("alliance_help",)
    assert store.profile(backend.farm.id).slots[1].tasks == ("tavern",)
    router.handle(callback(10, data.replace("slot:", "deleteslot:")))
    assert [s.id for s in store.profile(backend.farm.id).slots] == ["second"]


def test_pending_slot_edit_does_not_resurrect_remotely_deleted_slot(tmp_path):
    store, api, backend, router = setup(tmp_path)
    store.set_preference("telegram_owner", 10)
    store.save_profile(Profile(backend.farm.id, slots=[Slot("first","08:00","12:00",())]))
    router.schedule(10, backend.farm.id)
    data = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    router.handle(callback(10, data))
    store.save_profile(Profile(backend.farm.id))
    router.handle(message(10, "09:00 12:00"))
    assert store.profile(backend.farm.id).slots == []
    assert "изменён" in api.calls[-1][1]["text"]


def test_telegram_edit_preserves_desktop_edit_arriving_after_a_profile_read(tmp_path, monkeypatch):
    store, api, backend, router = setup(tmp_path)
    store.set_preference("telegram_owner", 10)
    store.save_profile(Profile(backend.farm.id, account_name="Before", manual_pause=True))
    router.tasks(10, backend.farm.id)
    toggle = api.calls[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
    desktop = Store(store.path)
    read = store.profile
    pending = [True]
    def concurrent_read(key):
        profile = read(key)
        if pending[0]:
            pending[0] = False
            desktop.update_profile(key, lambda latest: setattr(latest, "account_name", "Edited on desktop"))
        return profile
    monkeypatch.setattr(store, "profile", concurrent_read)
    router.handle(callback(10, toggle))
    result = desktop.profile(backend.farm.id)
    assert result.account_name == "Edited on desktop"
    assert result.tasks["alliance_help"]["enabled"]
    assert result.manual_pause
