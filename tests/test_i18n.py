"""User-facing coverage and live switching without touching automation state."""
import ast
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLabel, QLineEdit

from mirage.i18n import CYRILLIC, Verbatim, catalog, get_language, set_language, translate


@pytest.fixture(autouse=True)
def restore_language():
    previous = get_language()
    yield
    set_language(previous)


def test_all_application_owned_source_messages_have_offline_english():
    missing = []
    for path in (Path(__file__).parents[1] / 'src/mirage').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and CYRILLIC.search(node.value):
                if node.value not in catalog():
                    missing.append(f'{path.name}:{node.lineno}: {node.value}')
    assert not missing, '\n'.join(missing)
    assert all(text and not CYRILLIC.search(text) for text in catalog().values())


def test_rendered_diagnostics_keep_numbers_paths_and_native_ids():
    text = 'Цепочка: обзор «Ресурсы», радиус450; осмотр продолжается, участков9'
    assert translate(text, 'en') == 'Chain: Resources view, radius 450; survey continues, regions 9'
    assert translate(text, 'ru') == text
    assert translate(Verbatim('Ферма'), 'en') == 'Ферма'
    assert translate('id=17374920100 apTarget=171964501 C:/Mirage', 'en') == 'id=17374920100 apTarget=171964501 C:/Mirage'
    assert translate('Ошибка: C:/Ферма/Кожа.txt', 'en') == 'Error: C:/Ферма/Кожа.txt'
    assert translate('Ошибка: "C:/Моя Ферма/Кожа.txt"', 'en') == 'Error: "C:/Моя Ферма/Кожа.txt"'


def test_live_switch_covers_tasks_logs_dialogs_and_preserves_stop_and_ids(qtbot, tmp_path):
    from test_ui import create
    from mirage.ui import SlotDialog
    from mirage.model import Slot
    from mirage.localized_widgets import SOURCE_ROLE
    store, controller, window = create(qtbot, tmp_path)
    key = controller.instances[0].id
    controller.instances[0] = replace(controller.instances[0], name='Ферма')
    store.update_profile(key, lambda profile: (setattr(profile, 'manual_pause', True),
        profile.tasks.update(barbarian_chain={'enabled': True, 'level': 17}, gather_resources={'interval': 600})))
    store.event(key, 'info', 'Ручная остановка; автоматическое возобновление приостановлено')
    window.refresh()
    before = store.profile(key).to_dict()
    events = store.events()
    window.task_tree.setCurrentItem(window.task_items['barbarian_chain'])
    dialog = SlotDialog(Slot('slot', '08:00', '12:00', ('barbarian_chain',)), window)
    qtbot.addWidget(dialog)
    dialog.show()
    window.language.setCurrentIndex(window.language.findData('en'))
    assert store.preference('language') == 'en'
    assert window.nav_buttons['settings'].text() == 'Settings'
    assert window.task_items['barbarian_chain'].text(0) == 'Barbarian Chaining'
    assert window.task_items['barbarian_chain'].data(0, Qt.ItemDataRole.UserRole) == 'barbarian_chain'
    assert window.task_items['barbarian_chain'].checkState(0) == Qt.CheckState.Checked
    assert dialog.windowTitle() == 'Edit Slot'
    assert 'Barbarian Chaining' in [dialog.tasks.item(i).text() for i in range(dialog.tasks.count())]
    assert 'Manual stop; automatic resumption is paused' in window.logs.toPlainText()
    assert 'Ферма' in window.logs.toPlainText() and 'Ферма' in window.selected_label.text()
    assert window.model.headerData(0, Qt.Orientation.Horizontal) == 'EMULATOR'
    assert window.research_priority.tables['economy'].model.headerData(1, Qt.Orientation.Horizontal) == 'Technology'
    assert store.profile(key).to_dict() == before and store.events() == events
    assert window.gather_resource.itemData(0, SOURCE_ROLE) == 'Еда'
    assert window.gather_resource.itemText(0) == 'Food'
    for widget in window.findChildren(QLabel) + window.findChildren(QAbstractButton):
        if widget is not window.selected_label:
            assert not CYRILLIC.search(widget.text()), widget.text()
    window.language.setCurrentIndex(window.language.findData('ru'))
    assert window.task_items['barbarian_chain'].text(0) == 'Фарм варваров цепочкой'
    assert 'Ручная остановка' in window.logs.toPlainText()
    assert dialog.windowTitle() == 'Изменить слот'
    assert store.profile(key).to_dict() == before and store.events() == events


def test_saved_english_is_applied_on_open(qtbot, tmp_path):
    from mirage.controller import Controller
    from mirage.storage import Store
    from mirage.ui import Window
    store = Store(tmp_path/'saved.sqlite3')
    store.set_preference('language', 'en')
    window = Window(store, Controller(store, auto_refresh=False))
    qtbot.addWidget(window)
    assert window.language.currentData() == 'en'
    assert window.nav_buttons['fleet'].text() == 'Emulators'
    assert window.task_items['training'].text(0) == 'Train Troops'
    assert window.gather_resource.currentData() == 1


def test_only_telegram_owner_can_change_language_and_desktop_follows(qtbot, tmp_path):
    from test_ui import create
    from test_telegram import Backend, Recorder, callback
    from mirage.telegram import Router
    store, controller, window = create(qtbot, tmp_path)
    store.set_preference('telegram_owner', 10)
    backend = Backend()
    router = Router(Recorder(), store, backend)
    profiles = store.export_profiles()
    router.handle(callback(11, 'language:en'))
    assert store.preference('language', 'ru') == 'ru'
    router.handle(callback(10, 'language:en'))
    qtbot.waitUntil(lambda: window.nav_buttons['settings'].text() == 'Settings', timeout=2500)
    assert window.language.currentData() == 'en'
    assert backend.actions == [] and store.export_profiles() == profiles


def test_telegram_translates_every_menu_without_changing_callback_data(tmp_path):
    from test_telegram import setup
    store, api, backend, router = setup(tmp_path)
    key = backend.farm.id
    router.tasks(10, key)
    russian = api.calls[-1][1]
    store.set_preference('language', 'en')
    router.tasks(10, key)
    english = api.calls[-1][1]
    assert not CYRILLIC.search(english['text'])
    assert 'Unverified' in english['text']
    assert not CYRILLIC.search(str(english['reply_markup']))
    assert len(russian['reply_markup']['inline_keyboard']) == len(english['reply_markup']['inline_keyboard'])
    assert all(b['callback_data'].startswith(('task:', 'interval:', 'instance:'))
        for row in english['reply_markup']['inline_keyboard'] for b in row)
    router.menu(10)
    assert api.calls[-1][1]['reply_markup']['inline_keyboard'][0][0]['text'] == 'Ферма'
    router.instance_menu(10, key)
    assert api.calls[-1][1]['text'] == 'Ферма\nStopped'
    router._send(10, 'Ошибка', {'inline_keyboard': [[{'text': 'Назад', 'callback_data': 'instance:'+key}]]})
    assert api.calls[-1][1]['reply_markup']['inline_keyboard'][0][0] == {'text': 'Back', 'callback_data': 'instance:'+key}


def test_live_html_and_errors_follow_selected_language_without_input(qapp):
    from test_live import Backend, TOKEN
    from mirage.live import Server
    backend = Backend()
    server = Server(backend, TOKEN, lambda: 10)
    url = server.start()
    try:
        with httpx.Client(base_url=url, trust_env=False, timeout=5) as client:
            set_language('en')
            html = client.get('/').text
            assert '<html lang="en">' in html and 'Selected emulator screen' in html
            assert not CYRILLIC.search(html)
            error = client.get('/api/frame?instance=ld:test:1')
            assert error.status_code == 401 and not CYRILLIC.search(error.json()['error'])
            assert backend.captures == []
            set_language('ru')
            assert 'Просмотр экрана' in client.get('/').text
    finally:
        server.stop()
