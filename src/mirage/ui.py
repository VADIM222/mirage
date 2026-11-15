from __future__ import annotations

from dataclasses import replace
import importlib.resources
import json
import os
from pathlib import Path
import re
import sqlite3
import uuid

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QTimer, Signal, QSize
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QInputDialog,
    QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter, QStackedWidget,
    QTableView, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .controller import Controller
from .commanders import commander_catalog,commander_name,set_commander
from .model import BUILDING_TYPES, BarbarianOptions, BuildingOptions, DonationOptions, GATHER_RESOURCES, GatherOptions, Instance, LucerneOptions, MATERIALS, MaterialOptions, Power, Profile, RESEARCH_TYPES, ResearchOptions, RunState, Slot, SupplyBoxOptions, TASKS, TrainingOptions, TutorialOptions, VIP_SHOP_ITEMS, VipShopOptions, validate_slots
from .research_priority_ui import ResearchPriorityEditor
from .storage import Store
from .workflows import VERIFIED_WORKFLOWS
from .i18n import LANGUAGES, Verbatim, get_language, language_for, set_language, translate
from .localized_widgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QLabel, QLineEdit, QListWidgetItem, QMainWindow, QMessageBox, QInputDialog,
    QPlainTextEdit, QPushButton, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem,
    configure_qt_language, retranslate_widgets)


POWER_TEXT = {Power.ONLINE: "Включён", Power.OFF: "Выключен", Power.BOOTING: "Загрузка", Power.UNKNOWN: "Неизвестно"}
STATE_TEXT = {RunState.STOPPED: "Остановлено", RunState.WAIT_EMULATOR: "Ожидание эмулятора",
              RunState.WAIT_GAME: "Ожидание игры",
              RunState.WAIT_SLOT: "Вне расписания", RunState.WAIT_ADAPTER: "Ожидание памяти",
              RunState.PAUSED: "Пауза", RunState.RUNNING: "Работает", RunState.ERROR: "Ошибка"}


def label(text="", role=""):
    result = QLabel(text)
    if role:
        result.setObjectName(role)
    return result


def button(text, callback, role=""):
    result = QPushButton(text)
    if role:
        result.setObjectName(role)
    result.clicked.connect(callback)
    return result


def nav_icon(path):
    icon = QIcon()
    for state,color in ((QIcon.State.Off,"#A5A6AF"),(QIcon.State.On,"#DFB47A")):
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{path}</svg>'
        pixmap = QPixmap()
        pixmap.loadFromData(svg.encode(),"SVG")
        icon.addPixmap(pixmap,QIcon.Mode.Normal,state)
    return icon


class FleetModel(QAbstractTableModel):
    HEADERS = ("ЭМУЛЯТОР", "ПИТАНИЕ", "АВТОМАТИЗАЦИЯ", "ПАМЯТЬ / СОСТОЯНИЕ", "РАСПИСАНИЕ")

    def __init__(self, controller: Controller):
        super().__init__()
        self.controller = controller
        self.rows: list[Instance] = []

    def refresh(self):
        self.beginResetModel()
        self.rows = list(self.controller.instances)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return translate(self.HEADERS[section])
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        instance = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return instance.id
        if role == Qt.ItemDataRole.ForegroundRole:
            return QColor("#8DBBA2" if index.column() == 1 and instance.power == Power.ONLINE else "#A5A6AF" if index.column() else "#E7E7E9")
        if role == Qt.ItemDataRole.DisplayRole:
            profile = self.controller.store.profile(instance.id)
            decision = self.controller.decisions.get(instance.id)
            schedule = ", ".join(f"{slot.start}–{slot.end}" for slot in profile.slots) if profile.schedule_enabled else "Вручную"
            values = (f"{instance.name}  ·  {instance.key}", translate(POWER_TEXT[instance.power]),
                      translate(STATE_TEXT[decision.state] if decision else "Остановлено"),
                      translate(self.controller.reasons.get(instance.id, "Не подключено")), translate(schedule or "Нет слотов"))
            return values[index.column()]
        if role == Qt.ItemDataRole.ToolTipRole:
            return translate(self.controller.reasons[instance.id]) if instance.id in self.controller.reasons else instance.install_dir
        return None


class SlotDialog(QDialog):
    def __init__(self, slot: Slot | None, parent=None, on_change=None):
        super().__init__(parent)
        self.setWindowTitle("Изменить слот" if slot else "Добавить слот")
        self.resize(430, 470)
        self.slot_id = slot.id if slot else uuid.uuid4().hex
        self.on_change = on_change
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.start = QLineEdit(slot.start if slot else "08:00")
        self.end = QLineEdit(slot.end if slot else "23:00")
        self.start.setPlaceholderText("ЧЧ:ММ")
        self.end.setPlaceholderText("ЧЧ:ММ; допустимо 24:00")
        form.addRow("Начало", self.start)
        form.addRow("Окончание", self.end)
        layout.addLayout(form)
        layout.addWidget(label("Задачи в этом интервале", "section"))
        self.tasks = QListWidget()
        selected = set(slot.tasks if slot else ())
        for key, (name, group) in TASKS.items():
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key in selected else Qt.CheckState.Unchecked)
            self.tasks.addItem(item)
        layout.addWidget(self.tasks)
        self.message = label("Расписание действует только в работающем эмуляторе.", "muted")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        controls = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        controls.rejected.connect(self.accept)
        layout.addWidget(controls)
        self.start.textEdited.connect(self.autosave)
        self.end.textEdited.connect(self.autosave)
        self.tasks.itemChanged.connect(self.autosave)
        if slot is None:
            QTimer.singleShot(0, self.autosave)

    def value(self) -> Slot:
        selected = tuple(self.tasks.item(i).data(Qt.ItemDataRole.UserRole)
                         for i in range(self.tasks.count()) if self.tasks.item(i).checkState() == Qt.CheckState.Checked)
        return Slot(self.slot_id, self.start.text().strip(), self.end.text().strip(), selected)

    def autosave(self, *args):
        try:
            value = self.value()
            if self.on_change:
                self.on_change(value)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.message.setText(str(error))
            return
        self.message.setText("Сохранено автоматически")


class Window(QMainWindow):
    telegram_status_received = Signal(str)

    def __init__(self, store: Store, controller: Controller | None = None):
        super().__init__()
        if os.name == "nt" and "Segoe UI" not in QFontDatabase.families():
            font_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
            for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "seguisym.ttf"):
                if (font_dir / name).exists():
                    QFontDatabase.addApplicationFont(str(font_dir / name))
        self.store = store
        set_language(language_for(store))
        configure_qt_language(language_for(store))
        self.controller = controller or Controller(store)
        self.selected_id: str | None = None
        self.drafts: dict[str, Profile] = {}
        self._loading = False
        self._selected_task = None
        self._last_event_id = 0
        self._telegram_restart = False
        self.token_timer = QTimer(self)
        self.token_timer.setSingleShot(True)
        self.token_timer.setInterval(300)
        self.token_timer.timeout.connect(self.save_telegram)
        self.telegram_restart_timer = QTimer(self)
        self.telegram_restart_timer.setInterval(100)
        self.telegram_restart_timer.timeout.connect(self._restart_telegram_if_ready)
        self.setWindowTitle("Mirage · Графит и песок")
        self.resize(1390, 900)
        self.setMinimumSize(1030, 740)
        assets = importlib.resources.files("mirage").joinpath("assets")
        stylesheet = assets.joinpath("graphite.qss").read_text(encoding="utf-8")
        self.setStyleSheet(stylesheet.replace("__CHECK_ICON__", str(assets.joinpath("check.svg")).replace("\\", "/")))
        self._build()
        from .remote import RemoteBackend
        from .telegram import Service
        self.remote = RemoteBackend(self.controller)
        self.telegram = Service(self.store, self.remote, self.telegram_status_received.emit)
        self.telegram_status_received.connect(self.telegram_status.setText)
        self.controller.notice.connect(self.telegram.notify)
        self.controller.live_status.connect(self.live_status.setText)
        self.controller.updated.connect(self.refresh)
        self.language_timer = QTimer(self)
        self.language_timer.setInterval(1000)
        self.language_timer.timeout.connect(self._sync_language)
        self.language_timer.start()
        self.controller.error.connect(self.show_error)
        self.controller.image_ready.connect(self.show_image)
        self.refresh()
        if (self.controller._auto_refresh and self.store.preference("telegram_secret")
                and self.store.preference("telegram_enabled", True)):
            QTimer.singleShot(0, self.start_telegram)

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(182)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(14, 18, 14, 14)
        nav.addWidget(label("⋈  mirage", "brand"))
        nav.addWidget(label("УПРАВЛЕНИЕ", "eyebrow"))
        self.nav_buttons = {}
        paths={"fleet":'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
               "schedule":'<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18"/>',
               "rotation":'<path d="M20 8A8 8 0 0 0 6 6L3 9m0-6v6h6m-5 7a8 8 0 0 0 14 2l3-3m0 6v-6h-6"/>',
               "telegram":'<path d="m3 11 18-7-4 17-6-6-4 3v-6m0 0 14-8-10 11"/>',
               "settings":'<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3"/><circle cx="15" cy="17" r="3"/>'}
        for key, title in (("fleet", "Эмуляторы"), ("schedule", "Расписание"),
                           ("rotation", "Ротация"), ("telegram", "Telegram"), ("settings", "Настройки")):
            control = button(title, lambda checked=False, k=key: self.navigate(k), "nav")
            control.setIcon(nav_icon(paths[key]))
            control.setIconSize(QSize(17,17))
            control.setCheckable(True)
            self.nav_buttons[key] = control
            nav.addWidget(control)
        self.nav_buttons["fleet"].setChecked(True)
        nav.addStretch()
        nav.addWidget(label("●  Локальный режим", "muted"))
        nav.addWidget(label("Mirage 0.1 · разработка", "muted"))
        shell.addWidget(sidebar)
        main = QVBoxLayout()
        main.setContentsMargins(28, 25, 28, 13)
        main.setSpacing(12)
        shell.addLayout(main, 1)
        main.addWidget(label("Рабочее пространство / Mirage", "muted"))
        heading = QHBoxLayout()
        self.page_title = label("Эмуляторы", "title")
        heading.addWidget(self.page_title)
        heading.addStretch()
        heading.addWidget(button("Обновить", self.controller.refresh))
        self.launch_button = button("Открыть эмулятор", lambda: self.with_selected(self.controller.launch), "primary")
        heading.addWidget(self.launch_button)
        heading.addWidget(button("Закрыть выбранный", lambda: self.with_selected(self.controller.close_instance)))
        main.addLayout(heading)
        self.summary = label("Поиск установленных экземпляров…", "muted")
        main.addWidget(self.summary)
        self.model = FleetModel(self.controller)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.setMinimumHeight(130)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._instance_page())
        self.pages.addWidget(self._rotation_page())
        self.pages.addWidget(self._telegram_page())
        self.pages.addWidget(self._settings_page())
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.table)
        splitter.addWidget(self.pages)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([235, 330])
        main.addWidget(splitter, 1)
        log_header = QHBoxLayout()
        log_header.addWidget(label("Журнал событий", "section"))
        log_header.addStretch()
        log_header.addWidget(label("Все эмуляторы · реальные события", "muted"))
        main.addLayout(log_header)
        self.logs = QPlainTextEdit()
        self.logs.setReadOnly(True)
        self.logs.setMaximumBlockCount(250)
        self.logs.setMinimumHeight(85)
        self.logs.setMaximumHeight(140)
        self.logs.setPlaceholderText("События появятся после обнаружения и подключения экземпляров.")
        main.addWidget(self.logs)
        self.footer = label("Основной движок: root и данные игрового процесса", "muted")
        main.addWidget(self.footer)

    def _instance_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 9, 0, 0)
        header = QHBoxLayout()
        self.selected_label = label("Выберите эмулятор", "section")
        header.addWidget(self.selected_label)
        header.addStretch()
        self.save_status = label("Изменения сохраняются автоматически", "accent")
        header.addWidget(self.save_status)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tasks_page(), "Задачи")
        self.tabs.addTab(self._schedule_page(), "Расписание")
        self.tabs.addTab(self._parameters_page(), "Параметры / данные")
        layout.addWidget(self.tabs, 1)
        actions = QHBoxLayout()
        actions.addWidget(button("Подключить память", lambda: self.with_selected(self.controller.probe)))
        actions.addWidget(button("Установить runtime", self.install_runtime))
        actions.addWidget(button("Скриншот", lambda: self.with_selected(self.controller.screen)))
        actions.addStretch()
        actions.addWidget(button("Стоп", lambda: self.with_selected(self.controller.stop)))
        actions.addWidget(button("Запустить задачи", self.start_tasks, "primary"))
        layout.addLayout(actions)
        return page

    def _tasks_page(self):
        page = QWidget()
        layout = QHBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 4)
        self.task_tree = QTreeWidget()
        self.task_tree.setHeaderLabels(["Задача", "Готовность сценария"])
        self.task_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.task_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        groups = {}
        self.task_items = {}
        for key, (name, group) in TASKS.items():
            if group not in groups:
                groups[group] = QTreeWidgetItem(self.task_tree, [group])
                groups[group].setFirstColumnSpanned(True)
            item = QTreeWidgetItem(groups[group], [name, "Проверен" if key in VERIFIED_WORKFLOWS else "Не подключён"])
            item.setData(0, Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            self.task_items[key] = item
        self.task_tree.expandAll()
        self.task_tree.itemChanged.connect(self._task_changed)
        self.task_tree.currentItemChanged.connect(self._task_selected)
        layout.addWidget(self.task_tree, 3)
        parameters = QWidget()
        form = QVBoxLayout(parameters)
        form.setContentsMargins(12, 2, 0, 0)
        self.task_title = label("Параметры задачи", "section")
        form.addWidget(self.task_title)
        self.task_description = label("Выберите задачу слева. Галочка включает её в профиль.", "muted")
        self.task_description.setWordWrap(True)
        form.addWidget(self.task_description)
        row = QFormLayout()
        self.interval = QSpinBox()
        self.interval.setRange(1, 86400)
        self.interval.setSuffix(" с")
        self.interval.setValue(60)
        self.interval.valueChanged.connect(self._interval_changed)
        row.addRow("Интервал", self.interval)
        form.addLayout(row)
        self.training_options = QWidget()
        training_form = QFormLayout(self.training_options)
        training_form.setContentsMargins(0,8,0,8)
        units = QWidget()
        unit_layout = QGridLayout(units)
        unit_layout.setContentsMargins(0,0,0,0)
        self.training_units = {}
        for i,name in enumerate(("Пехота","Стрелки","Кавалерия","Осадные"),1):
            check = QCheckBox(name)
            check.toggled.connect(lambda checked, unit=i:self._training_unit_changed(unit,checked))
            unit_layout.addWidget(check,(i-1)//2,(i-1)%2)
            self.training_units[i] = check
        training_form.addRow("Обучать",units)
        self.training_tier = QSpinBox()
        self.training_tier.setRange(1,5)
        self.training_tier.setPrefix("T")
        self.training_tier.valueChanged.connect(lambda value:self._training_value_changed("tier",value))
        training_form.addRow("Тир",self.training_tier)
        self.training_count = QSpinBox()
        self.training_count.setRange(1,1000000)
        self.training_count.setValue(1000)
        self.training_count.valueChanged.connect(lambda value:self._training_value_changed("count",value))
        training_form.addRow("Размер партии",self.training_count)
        self.training_reserves = {}
        for i,name in enumerate(("еды","дерева","камня","золота"),1):
            spin = QSpinBox()
            spin.setRange(0,2000000000)
            spin.valueChanged.connect(lambda value, resource=str(i):self._training_reserve_changed(resource,value))
            self.training_reserves[str(i)] = spin
            training_form.addRow("Резерв "+name,spin)
        training_note = label("Обычное обучение. Гемы, ускорения и улучшение существующих войск не используются. Недоступный тир или нехватка ресурсов приостанавливают запуск.","muted")
        training_note.setWordWrap(True)
        training_form.addRow(training_note)
        self.training_options.hide()
        form.addWidget(self.training_options)
        self.donation_options = QWidget()
        donation_form = QFormLayout(self.donation_options)
        donation_form.setContentsMargins(0,8,0,8)
        self.donation_goal = QSpinBox()
        self.donation_goal.setRange(1,100000)
        self.donation_goal.setValue(100)
        self.donation_goal.valueChanged.connect(self._donation_goal_changed)
        donation_form.addRow("Дневная цель очков",self.donation_goal)
        self.donation_reserves = {}
        for i,name in enumerate(("еды","дерева","камня","золота"),1):
            spin = QSpinBox()
            spin.setRange(0,2000000000)
            spin.valueChanged.connect(lambda value,resource=str(i):self._donation_reserve_changed(resource,value))
            self.donation_reserves[str(i)] = spin
            donation_form.addRow("Резерв "+name,spin)
        donation_note = label("Одно ресурсное пожертвование за проверку до достижения дневной цели. "
            "Гемы не используются. Проверена рекомендация Building Durability I (306).","muted")
        donation_note.setWordWrap(True)
        donation_form.addRow(donation_note)
        self.donation_options.hide()
        form.addWidget(self.donation_options)
        self.material_options = QWidget()
        material_form = QFormLayout(self.material_options)
        material_form.setContentsMargins(0,8,0,8)
        self.material_item = QComboBox()
        for item,name in MATERIALS.items():self.material_item.addItem(name,item)
        self.material_item.currentIndexChanged.connect(lambda index:self._material_changed("item_id",self.material_item.currentData()))
        self.material_limit = QSpinBox()
        self.material_limit.setRange(1,5)
        self.material_limit.setValue(5)
        self.material_limit.valueChanged.connect(lambda value:self._material_changed("max_orders",value))
        material_form.addRow("Материал",self.material_item)
        material_form.addRow("Заказов в очереди",self.material_limit)
        material_note = label("Один обычный заказ за проверку, по 15 единиц. Готовые материалы забираются в кузнице. "
            "Гемы, ускорения, слияние и разбор не используются.","muted")
        material_note.setWordWrap(True)
        material_form.addRow(material_note)
        self.material_options.hide()
        form.addWidget(self.material_options)
        self.gather_options = QWidget()
        gather_form = QFormLayout(self.gather_options)
        gather_form.setContentsMargins(0,8,0,8)
        self.gather_resource = QComboBox()
        for resource,name in GATHER_RESOURCES.items():self.gather_resource.addItem(name,resource)
        self.gather_resource.currentIndexChanged.connect(
            lambda:self._gather_changed("resource",self.gather_resource.currentData()))
        gather_form.addRow("Ресурс",self.gather_resource)
        self.gather_fields = {}
        for key,title,low,high,value in (("level","Уровень поиска",1,8,1),
                ("max_level","Максимальный уровень цели",1,8,8),("max_travel","Переход, максимум секунд",1,600,180),
                ("max_marches","Занятых маршей, максимум",1,5,1)):
            widget = QSpinBox()
            widget.setRange(low,high)
            widget.setValue(value)
            widget.valueChanged.connect(lambda value,key=key:self._gather_changed(key,value))
            self.gather_fields[key]=widget
            gather_form.addRow(title,widget)
        gather_note = label("Еда, дерево, камень и золото. Лимит учитывает все ваши марши; за проверку отправляется один новый. "
            "Командиров рекомендует игра; только осадные с достаточной вместимостью. Занятые цели пропускаются.","muted")
        gather_note.setWordWrap(True)
        gather_form.addRow(gather_note)
        self.gather_options.hide()
        form.addWidget(self.gather_options)
        self.barbarian_options=QWidget();barbarian_form=QFormLayout(self.barbarian_options)
        barbarian_form.setContentsMargins(0,8,0,8);self.barbarian_fields={};self.barbarian_labels={}
        self.barbarian_commanders={}
        for slot,title in (('primary','Основной командир'),('deputy','Второй командир')):
            combo=QComboBox();combo.setEditable(True);combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
            combo.currentIndexChanged.connect(lambda index,slot=slot:self._barbarian_commander_changed(slot))
            self.barbarian_commanders[slot]=combo;barbarian_form.addRow(title,combo)
        for key,title,low,high,value in (('level','Уровень поиска',1,25,1),('max_level','Максимальный уровень соседей',1,25,1),('reserve_ap','Резерв AP',0,10000,100),
                ('max_battles','Платных боёв за заход, максимум',1,100,3),('min_health','Возврат при численности ниже, %',1,100,50)):
            spin=QSpinBox();spin.setRange(low,high);spin.setValue(value)
            spin.valueChanged.connect(lambda value,key=key:self._barbarian_changed(key,value))
            self.barbarian_fields[key]=spin;self.barbarian_labels[key]=label(title)
            barbarian_form.addRow(self.barbarian_labels[key],spin)
        self.barbarian_note=label('Оставаться в поле и продолжать той же армией. Цена AP читается из игры. '
            'Бот сам назначает выбранную пару и выводит отряд. Второй командир необязателен. '
            'Возврат по пределу боёв, резерву или здоровью.','muted')
        self.barbarian_note.setWordWrap(True);barbarian_form.addRow(self.barbarian_note)
        self.barbarian_options.hide();form.addWidget(self.barbarian_options)
        self.building_options = QWidget()
        building_form = QFormLayout(self.building_options)
        building_form.setContentsMargins(0,8,0,8)
        building_form.addRow("Выбор",label("Выбранные типы: доступное здание с наименьшим уровнем"))
        self.building_level = QSpinBox()
        self.building_level.setRange(1,24)
        self.building_level.setValue(20)
        self.building_level.valueChanged.connect(lambda value:self._building_changed("max_level",value))
        building_form.addRow("Улучшать до уровня",self.building_level)
        building_types=QWidget();building_grid=QGridLayout(building_types);building_grid.setContentsMargins(0,0,0,0)
        self.building_types={}
        for index,(kind,title) in enumerate(BUILDING_TYPES.items()):
            check=QCheckBox(title);check.setChecked(kind==4)
            check.toggled.connect(lambda enabled,kind=kind:self._building_type_changed(kind,enabled))
            self.building_types[kind]=check;building_grid.addWidget(check,index//2,index%2)
        building_form.addRow('Типы зданий',building_types)
        self.building_packs=QCheckBox('Пополнять еду/дерево из пакетов10000 (до4 за проверку)')
        self.building_packs.toggled.connect(lambda enabled:self._building_changed('use_resource_packs',enabled))
        building_form.addRow(self.building_packs)
        self.building_prerequisites=QCheckBox('Автоматически улучшать здания-предпосылки')
        self.building_prerequisites.toggled.connect(lambda enabled:self._building_changed('auto_prerequisites',enabled))
        building_form.addRow(self.building_prerequisites)
        self.building_create=QCheckBox('Строить выбранные отсутствующие здания')
        self.building_create.toggled.connect(lambda enabled:self._building_changed('create_missing',enabled))
        building_form.addRow(self.building_create)
        self.building_plants=QCheckBox('Освобождать место: упаковывать обычные растения (одно за проверку)')
        self.building_plants.toggled.connect(lambda enabled:self._building_changed('clear_plants',enabled))
        building_form.addRow(self.building_plants)
        self.building_reserves = {}
        for kind,title in (("1","Резерв еды"),("2","Резерв дерева"),("3","Резерв камня"),("4","Резерв золота")):
            widget = QSpinBox()
            widget.setRange(0,2000000000)
            widget.valueChanged.connect(lambda value,kind=kind:self._building_reserve_changed(kind,value))
            self.building_reserves[kind]=widget
            building_form.addRow(title,widget)
        building_note=label("Один обычный запуск за проверку, только постоянный строитель. "
            "Новые запуски ждут освобождения очереди. Гемы и ускорения не используются.","muted")
        building_note.setWordWrap(True)
        building_form.addRow(building_note)
        self.building_options.hide()
        form.addWidget(self.building_options)
        self.research_options=QWidget();research_form=QFormLayout(self.research_options)
        research_form.setContentsMargins(0,8,0,8)
        self.research_level=QSpinBox();self.research_level.setRange(1,10);self.research_level.setValue(10)
        self.research_level.valueChanged.connect(lambda value:self._research_changed('max_level',value))
        research_form.addRow('Исследовать до уровня',self.research_level)
        self.research_expand=button('Таблицы приоритетов ↗',self.show_research_priorities)
        research_form.addRow(self.research_expand)
        self.research_priority=ResearchPriorityEditor()
        self.research_priority.modeChanged.connect(self._research_mode_changed)
        self.research_priority.orderChanged.connect(self._research_order_changed)
        research_form.addRow(self.research_priority)
        self.research_packs=QCheckBox('Пополнять еду/дерево из пакетов10000 (до4 за проверку)')
        self.research_packs.toggled.connect(lambda enabled:self._research_changed('use_resource_packs',enabled))
        research_form.addRow(self.research_packs)
        self.research_prerequisites=QCheckBox('Автоматически выполнять предпосылки: технологии и академия')
        self.research_prerequisites.toggled.connect(lambda enabled:self._research_changed('auto_prerequisites',enabled))
        research_form.addRow(self.research_prerequisites)
        self.research_reserves={}
        for kind,title in (('1','Резерв еды'),('2','Резерв дерева'),('3','Резерв камня'),('4','Резерв золота')):
            spin=QSpinBox();spin.setRange(0,2000000000)
            spin.valueChanged.connect(lambda value,kind=kind:self._research_reserve_changed(kind,value))
            self.research_reserves[kind]=spin;research_form.addRow(title,spin)
        note=label('Один обычный старт при свободной академии.28 экономических и43 военных технологии; '
            'предпосылки и стоимость сверяются с памятью. Гемы и ускорения не используются.','muted')
        note.setWordWrap(True);research_form.addRow(note)
        self.research_options.hide();form.addWidget(self.research_options)
        self.supply_options = QWidget()
        supply_form = QFormLayout(self.supply_options)
        supply_form.setContentsMargins(0,8,0,8)
        self.supply_limit = QSpinBox()
        self.supply_limit.setRange(1,10)
        self.supply_limit.setValue(1)
        self.supply_limit.valueChanged.connect(self._supply_limit_changed)
        supply_form.addRow("Ящиков за проверку",self.supply_limit)
        self.supply_note=label("Обычный Supply Box (7001), по одному с проверкой расхода и полученной награды. "
            "После остановки сначала закрывается уже полученная награда.","muted")
        self.supply_note.setWordWrap(True)
        supply_form.addRow(self.supply_note)
        self.supply_options.hide()
        form.addWidget(self.supply_options)
        self.vip_shop_options=QWidget()
        vip_shop_form=QFormLayout(self.vip_shop_options)
        vip_shop_form.setContentsMargins(0,8,0,8)
        self.vip_shop_item=QComboBox()
        for item,title in VIP_SHOP_ITEMS.items():self.vip_shop_item.addItem(title,item)
        self.vip_shop_item.currentIndexChanged.connect(lambda:self._vip_shop_changed('item_id',self.vip_shop_item.currentData()))
        vip_shop_form.addRow('Товар за еду',self.vip_shop_item)
        self.vip_shop_fields={}
        for key,title,low,value in (('max_price','Максимальная цена',1,12000),('reserve','Резерв еды',0,0)):
            spin=QSpinBox();spin.setRange(low,2000000000);spin.setValue(value)
            spin.valueChanged.connect(lambda value,key=key:self._vip_shop_changed(key,value))
            self.vip_shop_fields[key]=spin;vip_shop_form.addRow(title,spin)
        vip_shop_note=label('Одна покупка за проверку. Оплата только едой, с проверкой цены, остатка и инвентаря. '
            'Купленные предметы не используются автоматически.','muted')
        vip_shop_note.setWordWrap(True);vip_shop_form.addRow(vip_shop_note)
        self.vip_shop_options.hide();form.addWidget(self.vip_shop_options)
        self.lucerne_options=QWidget();lucerne_form=QFormLayout(self.lucerne_options)
        lucerne_form.setContentsMargins(0,8,0,8)
        self.lucerne_limit=QSpinBox();self.lucerne_limit.setRange(1,32);self.lucerne_limit.setValue(32)
        self.lucerne_limit.valueChanged.connect(self._lucerne_limit_changed)
        lucerne_form.addRow('Получений опыта за проверку',self.lucerne_limit)
        note=label('Бесплатный пропуск: ежедневный опыт, готовые испытания и заработанные призы. '
            'Общее получение призов выполняется после опыта, если лимит ещё не исчерпан.','muted')
        note.setWordWrap(True);lucerne_form.addRow(note)
        self.lucerne_options.hide();form.addWidget(self.lucerne_options)
        self.tutorial_options=QWidget();tutorial_form=QFormLayout(self.tutorial_options)
        tutorial_form.setContentsMargins(0,8,0,8)
        self.tutorial_limit=QSpinBox();self.tutorial_limit.setRange(1,32);self.tutorial_limit.setValue(8)
        self.tutorial_limit.valueChanged.connect(self._tutorial_limit_changed)
        tutorial_form.addRow('Действий обучения за проверку',self.tutorial_limit)
        note=label('Вступление slg_2_v4: диалоги, стартовые постройки и награды. '
            'Неизвестный этап возвращает управление; боевое обучение поддержано частично.','muted')
        note.setWordWrap(True);tutorial_form.addRow(note)
        self.tutorial_options.hide();form.addWidget(self.tutorial_options)
        note = label("Готовность определяется живой проверкой игрового сценария. Подключение памяти само по себе не означает готовность фарма.", "muted")
        note.setWordWrap(True)
        form.addWidget(note)
        form.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(parameters)
        layout.addWidget(scroll, 2)
        return page

    def _schedule_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 4)
        row = QHBoxLayout()
        self.schedule_enabled = QCheckBox("Использовать расписание для выбранного эмулятора")
        self.schedule_enabled.toggled.connect(self._schedule_changed)
        row.addWidget(self.schedule_enabled)
        row.addStretch()
        row.addWidget(button("+ Добавить слот", self.add_slot))
        layout.addLayout(row)
        self.slot_list = QListWidget()
        self.slot_list.itemDoubleClicked.connect(lambda item: self.edit_slot())
        layout.addWidget(self.slot_list)
        actions = QHBoxLayout()
        actions.addWidget(label("Выключенный эмулятор расписание не запускает.", "muted"))
        actions.addStretch()
        actions.addWidget(button("Изменить", self.edit_slot))
        actions.addWidget(button("Удалить", self.delete_slot))
        layout.addLayout(actions)
        return page

    def _parameters_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 4)
        self.account_name = QLineEdit()
        self.account_name.setPlaceholderText("Название аккаунта для этого профиля")
        self.account_name.textEdited.connect(self._name_changed)
        layout.addWidget(self.account_name)
        controls = QHBoxLayout()
        controls.addWidget(button("Копировать профиль…", self.copy_profile))
        controls.addWidget(button("Создать пресет…", self.save_preset))
        controls.addWidget(button("Применить пресет…", self.apply_preset))
        controls.addWidget(button("Удалить пресет…", self.delete_preset))
        layout.addLayout(controls)
        transfers = QHBoxLayout()
        transfers.addWidget(button("Экспорт профилей", self.export_profiles))
        transfers.addWidget(button("Импорт профилей", self.import_profiles))
        layout.addLayout(transfers)
        layout.addWidget(button("Подготовить: root · CPU ≥ 2 · ОЗУ ≥ 2 ГБ · 960×540 (перезапуск)",
                                lambda: self.with_selected(self.controller.prepare_instance)))
        self.telemetry = QPlainTextEdit()
        self.telemetry.setReadOnly(True)
        self.telemetry.setPlaceholderText("Нажмите «Подключить память», чтобы прочитать настоящее состояние игры.")
        layout.addWidget(self.telemetry)
        return page

    def _rotation_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Ротация экземпляров", "section"))
        text = label("Ротация по отдельной команде запускает и закрывает экземпляры пула. Расписание ограничивает задачи внутри запущенной игры. Ручной «Стоп» приостанавливает участие экземпляра.", "muted")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.rotation_members = QListWidget()
        layout.addWidget(self.rotation_members)
        form = QFormLayout()
        self.rotation_parallel = QSpinBox()
        self.rotation_parallel.setRange(1, 50)
        settings = self.store.preference("rotation", {})
        self.rotation_parallel.setValue(settings.get("parallel", 3))
        self.rotation_duration = QSpinBox()
        self.rotation_duration.setRange(1, 1440)
        self.rotation_duration.setValue(max(1, settings.get("duration", 3600) // 60))
        self.rotation_duration.setSuffix(" мин")
        form.addRow("Параллельно", self.rotation_parallel)
        form.addRow("На экземпляр", self.rotation_duration)
        layout.addLayout(form)
        self.rotation_members.itemChanged.connect(self._rotation_member_changed)
        self.rotation_parallel.valueChanged.connect(lambda value: self._rotation_setting_changed("parallel", value))
        self.rotation_duration.valueChanged.connect(lambda value: self._rotation_setting_changed("duration", value * 60))
        actions = QHBoxLayout()
        actions.addWidget(button("Включить ротацию", self.start_rotation, "primary"))
        actions.addWidget(button("Остановить ротацию", self.controller.disable_rotation))
        actions.addWidget(button("Возобновить выбранного участника", self.resume_rotation))
        layout.addLayout(actions)
        self.rotation_status = label("Ротация выключена", "muted")
        self.rotation_status.setWordWrap(True)
        layout.addWidget(self.rotation_status)
        return page

    def _telegram_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Telegram", "section"))
        text = label("Вставьте токен от @BotFather — он сохранится автоматически в защищённом хранилище Windows.", "muted")
        text.setWordWrap(True)
        layout.addWidget(text)
        self.telegram_token = QLineEdit()
        self.telegram_token.setEchoMode(QLineEdit.EchoMode.Password)
        self.telegram_token.setPlaceholderText("Новый токен @BotFather")
        self.telegram_token.textEdited.connect(lambda text: self.token_timer.start())
        self.telegram_token.editingFinished.connect(self.save_telegram)
        layout.addWidget(self.telegram_token)
        self.telegram_status = label("Токен сохранён" if self.store.preference("telegram_secret") else "Не подключён", "muted")
        self.telegram_status.setWordWrap(True)
        layout.addWidget(self.telegram_status)
        self.pair_code = label("", "accent")
        self.pair_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pair_code.setWordWrap(True)
        layout.addWidget(self.pair_code)
        actions = QHBoxLayout()
        actions.addWidget(button("Включить бота", self.start_telegram, "primary"))
        actions.addWidget(button("Остановить", self.stop_telegram))
        layout.addLayout(actions)
        layout.addWidget(label("Mirage Live · просмотр до 1 кадра/с", "section"))
        note = label("Cloudflare загружается и настраивается автоматически при включении Live.", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        actions = QHBoxLayout()
        actions.addWidget(button("Включить Live", self.start_live))
        actions.addWidget(button("Выключить Live", self.controller.stop_live))
        layout.addLayout(actions)
        self.live_status = label("Live выключен", "muted")
        self.live_status.setWordWrap(True)
        layout.addWidget(self.live_status)
        layout.addStretch()
        return page

    def _settings_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(label("Настройки Mirage", "section"))
        form = QFormLayout()
        self.language = QComboBox()
        for code, title in LANGUAGES:
            self.language.addItem(Verbatim(title), code)
        self.language.setCurrentIndex(self.language.findData(language_for(self.store)))
        self.language.currentIndexChanged.connect(self.change_language)
        form.addRow("Язык интерфейса", self.language)
        form.addRow("Цветовая схема", label("Графит и песок"))
        layout.addLayout(form)
        self.telegram_autostart = QCheckBox("Подключать Telegram при открытии Mirage")
        self.telegram_autostart.setChecked(self.store.preference("telegram_enabled", True))
        self.telegram_autostart.toggled.connect(lambda enabled: self.store.set_preference("telegram_enabled", enabled))
        layout.addWidget(self.telegram_autostart)
        self.error_notifications = QCheckBox("Отправлять уведомления об ошибках в Telegram")
        self.error_notifications.setChecked(self.store.preference("telegram_notifications", True))
        self.error_notifications.toggled.connect(lambda enabled: self.store.set_preference("telegram_notifications", enabled))
        layout.addWidget(self.error_notifications)
        layout.addWidget(label("Все изменения сохраняются автоматически.", "muted"))
        layout.addStretch()
        return page

    def change_language(self, index):
        language = self.language.itemData(index)
        if language not in ('ru', 'en'):
            return
        self.store.set_preference('language', language)
        set_language(language)
        configure_qt_language(language)
        retranslate_widgets()
        self.model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, len(self.model.HEADERS) - 1)
        for model in self.findChildren(QAbstractTableModel):
            if model.rowCount() and model.columnCount():
                model.dataChanged.emit(model.index(0, 0), model.index(model.rowCount()-1, model.columnCount()-1))
                model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, model.columnCount()-1)
        self.logs.clear()
        self._last_event_id = 0
        self.refresh()

    def _sync_language(self):
        language = language_for(self.store)
        if language != get_language():
            self.language.setCurrentIndex(self.language.findData(language))

    def with_selected(self, callback):
        if self.selected_id and any(i.id == self.selected_id for i in self.controller.instances):
            try:
                callback(self.selected_id)
            except (ValueError, StopIteration) as error:
                self.show_error(str(error) or "Эмулятор больше не найден")
        else:
            self.show_error("Сначала выберите эмулятор")

    def navigate(self, key):
        for name, control in self.nav_buttons.items():
            control.setChecked(name == key)
        self.page_title.setText({"fleet": "Эмуляторы", "schedule": "Расписание", "rotation": "Ротация",
                                 "telegram": "Telegram", "settings": "Настройки"}[key])
        self.pages.setCurrentIndex({"fleet": 0, "schedule": 0, "rotation": 1, "telegram": 2, "settings": 3}[key])
        if key in ("fleet", "schedule"):
            self.tabs.setCurrentIndex(1 if key == "schedule" else 0)

    def refresh(self):
        selected = self.selected_id
        if selected and not any(instance.id == selected for instance in self.controller.instances):
            self.selected_id = None
            selected = None
            self.selected_label.setText("Выберите доступный эмулятор")
        self.table.selectionModel().blockSignals(True)
        self.model.refresh()
        for row, instance in enumerate(self.model.rows):
            if instance.id == selected:
                self.table.selectRow(row)
                break
        self.table.selectionModel().blockSignals(False)
        if self.selected_id is None and self.model.rows:
            self.table.selectRow(0)
        if selected and selected in self.drafts:
            profile = self.store.profile(selected)
            self.drafts[selected] = profile
            self._sync_editor(profile)
        online = sum(instance.power == Power.ONLINE for instance in self.model.rows)
        rotation = self.controller.rotation
        self.rotation_status.setText((f"Ротация включена · в работе: {len(rotation.current)} · на паузе: {len(rotation.suspended)}"
                                      if rotation and rotation.enabled else "Ротация выключена"))
        self.summary.setText(f"{len(self.model.rows):02} всего      ·      {online:02} включены      ·      Лимит этого ПК: {self.store.preference('device_limit',3)}      ·      Память: {len(self.controller.readers)}")
        if selected in self.controller.snapshots:
            snapshot = self.controller.snapshots[selected]
            player = snapshot.values["player"]
            resources = snapshot.values.get("resources") or {}
            fields = {"Версия RoK": snapshot.game_version, "PID": snapshot.pid, "ID персонажа": snapshot.player_id,
                      "Имя": player.get("Name"), "Сервер": player.get("ServerID"), "Мощь": player.get("Power"),
                      "Ратуша": player.get("TownCenterLevel"), "Еда": resources.get("1"), "Дерево": resources.get("2"),
                      "Камень": resources.get("3"), "Золото": resources.get("4"), "Гемы": resources.get("5"),
                      "Игровые часы": snapshot.values.get("server_time")}
            self.telemetry.setPlainText(Verbatim("\n".join(f"{translate(key)}: {value}" for key,value in fields.items())))
        for event_id, created, key, level, message in self.store.events():
            if event_id > self._last_event_id:
                name = next((i.name for i in self.model.rows if i.id == key), "Mirage")
                self.logs.appendPlainText(Verbatim(f"{created[11:]}  {name}  ·  {translate(message)}"))
                self._last_event_id = event_id
        current_members = {self.rotation_members.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.rotation_members.count())}
        self.rotation_members.blockSignals(True)
        if current_members != {i.id for i in self.model.rows}:
            selected_members = set(self.store.preference("rotation", {}).get("members", []))
            self.rotation_members.clear()
            for instance in self.model.rows:
                item = QListWidgetItem(Verbatim(instance.name))
                item.setData(Qt.ItemDataRole.UserRole, instance.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if instance.id in selected_members else Qt.CheckState.Unchecked)
                self.rotation_members.addItem(item)
        rotation_settings = self.store.preference("rotation", {})
        members = set(rotation_settings.get("members", []))
        for index in range(self.rotation_members.count()):
            item = self.rotation_members.item(index)
            item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in members else Qt.CheckState.Unchecked)
        self.rotation_members.blockSignals(False)
        for control, value in ((self.rotation_parallel, rotation_settings.get("parallel", 3)),
                               (self.rotation_duration, max(1, rotation_settings.get("duration", 3600) // 60))):
            control.blockSignals(True)
            control.setValue(value)
            control.blockSignals(False)

    def _selection_changed(self, selected, deselected):
        indices = self.table.selectionModel().selectedRows()
        if not indices:
            return
        self.select_instance(self.model.rows[indices[0].row()].id)

    def select_instance(self, key):
        self.selected_id = key
        profile = self.store.profile(key)
        self.drafts[key] = profile
        self.telemetry.clear()
        self._sync_editor(profile)

    def _sync_editor(self, profile):
        previous_loading = self._loading
        self._loading = True
        try:
            instance = self.controller.instance(profile.instance_id)
            self.selected_label.setText(Verbatim(f"{instance.name} · {instance.key}"))
            for task, item in self.task_items.items():
                item.setCheckState(0, Qt.CheckState.Checked if profile.tasks.get(task, {}).get("enabled") else Qt.CheckState.Unchecked)
            self.schedule_enabled.setChecked(profile.schedule_enabled)
            if self.account_name.text() != profile.account_name:
                self.account_name.setText(profile.account_name)
            self.render_slots()
            self.save_status.setText("Изменения сохраняются автоматически")
            self._task_selected(self.task_tree.currentItem(), None)
        finally:
            self._loading = previous_loading

    def _change_profile(self, change, *, reevaluate=True):
        if self._loading or not self.selected_id:
            return False
        key = self.selected_id
        try:
            self.drafts[key] = self.store.update_profile(key, change)
        except (ValueError, OSError, sqlite3.Error) as error:
            self.show_error(f"Не удалось сохранить: {error}")
            self.select_instance(key)
            return False
        self.save_status.setText("Сохранено автоматически")
        if reevaluate:
            self.controller.tick()
        else:
            self.controller.updated.emit()
        return True

    def _task_changed(self, item, column):
        if self._loading or not self.selected_id:
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key:
            enabled = item.checkState(0) == Qt.CheckState.Checked
            self._change_profile(lambda profile: profile.tasks.setdefault(key, {}).update(enabled=enabled))

    def _task_selected(self, current, previous):
        self._selected_task = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        self.training_options.setVisible(self._selected_task == "training")
        self.donation_options.setVisible(self._selected_task == "alliance_donate")
        self.material_options.setVisible(self._selected_task == "materials")
        self.gather_options.setVisible(self._selected_task == "gather_resources")
        self.barbarian_options.setVisible(self._selected_task in ('barbarians','barbarian_chain'))
        chain=self._selected_task=='barbarian_chain'
        self.barbarian_labels['level'].setText('Минимальный уровень на карте' if chain else 'Уровень поиска')
        self.barbarian_labels['max_level'].setText('Максимальный уровень на карте' if chain else 'Максимальный уровень соседей')
        self.barbarian_note.setText(('Широкий обзор «Ресурсы» через зажатие кнопки города. '
            'До3 участков за проверку, радиус450; без игрового поиска. '
            'Приоритет групп из3+; если цель ушла, осмотр продолжается в поле. ' if chain else
            'Оставаться в поле и продолжать той же армией. ')+
            'Бот сам назначает пару и выводит отряд. Возврат по пределу боёв, резерву или здоровью.')
        self.building_options.setVisible(self._selected_task == "buildings")
        self.research_options.setVisible(self._selected_task=='research')
        self.supply_options.setVisible(self._selected_task in ("supply_boxes","cave_rewards"))
        self.supply_note.setText(("Получение подтверждённых писем пещер и открытие сундуков7014. "
            if self._selected_task=='cave_rewards' else "Обычный Supply Box (7001). ")+
            "По одному с проверкой расхода и награды. После остановки сначала закрывается уже полученная награда.")
        self.vip_shop_options.setVisible(self._selected_task == "vip_shop")
        self.lucerne_options.setVisible(self._selected_task == 'lucerne')
        self.tutorial_options.setVisible(self._selected_task == 'tutorial')
        if not self._selected_task:
            return
        self.task_title.setText(TASKS[self._selected_task][0])
        self.task_description.setText("Сценарий проверен" if self._selected_task in VERIFIED_WORKFLOWS else "Сценарий ещё не подключён к подтверждённым действиям игры.")
        if self._selected_task=='shield':
            self.task_description.setText('Один щит8ч из сумки (49). Действующий щит и военная лихорадка блокируют применение.')
        if self._selected_task=='vip_shop':
            self.task_description.setText('Частично:4 проверенных товара за еду. Полный список с прокруткой, '
                'скупка за ресурсы и отдельные галочки товаров за гемы требуют переделки после открытия магазина.')
        if self._selected_task=='tutorial':
            self.task_description.setText('Вступление slg_2_v4 проверено по этапам; боевое обучение — частично. Полный новый аккаунт ещё не подтверждён.')
        if self.selected_id:
            value = self.drafts[self.selected_id].tasks.get(self._selected_task, {}).get("interval", 60)
            self.interval.blockSignals(True)
            if self.interval.value() != int(value):
                self.interval.setValue(int(value))
            self.interval.blockSignals(False)
            if self._selected_task == "training":
                options = TrainingOptions.from_settings(self.drafts[self.selected_id].tasks.get("training",{}))
                previous_loading = self._loading
                self._loading = True
                try:
                    for unit,check in self.training_units.items():
                        check.setChecked(unit in options.units)
                    self.training_tier.setValue(options.tier)
                    self.training_count.setValue(options.count)
                    for i,reserve in enumerate(options.reserves,1):
                        self.training_reserves[str(i)].setValue(reserve)
                finally:
                    self._loading = previous_loading
            if self._selected_task == "alliance_donate":
                options = DonationOptions.from_settings(self.drafts[self.selected_id].tasks.get("alliance_donate",{}))
                previous_loading = self._loading
                self._loading = True
                try:
                    self.donation_goal.setValue(options.daily_goal)
                    for i,reserve in enumerate(options.reserves,1):
                        self.donation_reserves[str(i)].setValue(reserve)
                finally:
                    self._loading = previous_loading

            if self._selected_task == "materials":
                options = MaterialOptions.from_settings(self.drafts[self.selected_id].tasks.get("materials",{}))
                previous_loading = self._loading
                self._loading = True
                try:
                    self.material_item.setCurrentIndex(self.material_item.findData(options.item_id))
                    self.material_limit.setValue(options.max_orders)
                finally:
                    self._loading = previous_loading
            if self._selected_task == "gather_resources":
                options = GatherOptions.from_settings(self.drafts[self.selected_id].tasks.get("gather_resources",{}))
                previous_loading = self._loading
                self._loading = True
                try:
                    self.gather_resource.setCurrentIndex(self.gather_resource.findData(options.resource))
                    for key,widget in self.gather_fields.items():widget.setValue(getattr(options,key))
                finally:
                    self._loading = previous_loading
            if self._selected_task in ('barbarians','barbarian_chain'):
                options=BarbarianOptions.from_settings(self.drafts[self.selected_id].tasks.get(self._selected_task,{}))
                previous_loading=self._loading;self._loading=True
                try:
                    for key,spin in self.barbarian_fields.items():spin.setValue(getattr(options,key))
                    self._sync_barbarian_commanders(options)
                finally:self._loading=previous_loading
            if self._selected_task == "buildings":
                options = BuildingOptions.from_settings(self.drafts[self.selected_id].tasks.get("buildings",{}))
                previous_loading=self._loading
                self._loading=True
                try:
                    self.building_level.setValue(options.max_level)
                    for kind,check in self.building_types.items():check.setChecked(kind in options.types)
                    self.building_packs.setChecked(options.use_resource_packs)
                    self.building_prerequisites.setChecked(options.auto_prerequisites)
                    self.building_create.setChecked(options.create_missing)
                    self.building_plants.setChecked(options.clear_plants)
                    for i,reserve in enumerate(options.reserves,1):self.building_reserves[str(i)].setValue(reserve)
                finally:self._loading=previous_loading

            if self._selected_task=='research':
                options=ResearchOptions.from_settings(self.drafts[self.selected_id].tasks.get('research',{}))
                previous_loading=self._loading;self._loading=True
                try:
                    self.research_level.setValue(options.max_level)
                    self.research_packs.setChecked(options.use_resource_packs)
                    self.research_prerequisites.setChecked(options.auto_prerequisites)
                    self.research_priority.set_options(options)
                    for i,value in enumerate(options.reserves,1):self.research_reserves[str(i)].setValue(value)
                finally:self._loading=previous_loading

            if self._selected_task in ("supply_boxes","cave_rewards"):
                options=SupplyBoxOptions.from_settings(self.drafts[self.selected_id].tasks.get(self._selected_task,{}))
                previous_loading=self._loading
                self._loading=True
                try:self.supply_limit.setValue(options.max_boxes)
                finally:self._loading=previous_loading
            if self._selected_task == 'vip_shop':
                options=VipShopOptions.from_settings(self.drafts[self.selected_id].tasks.get('vip_shop',{}))
                previous_loading=self._loading;self._loading=True
                try:
                    self.vip_shop_item.setCurrentIndex(self.vip_shop_item.findData(options.item_id))
                    for key,spin in self.vip_shop_fields.items():spin.setValue(getattr(options,key))
                finally:self._loading=previous_loading
            if self._selected_task == 'lucerne':
                options=LucerneOptions.from_settings(self.drafts[self.selected_id].tasks.get('lucerne',{}))
                previous_loading=self._loading;self._loading=True
                try:self.lucerne_limit.setValue(options.max_claims)
                finally:self._loading=previous_loading
            if self._selected_task == 'tutorial':
                options=TutorialOptions.from_settings(self.drafts[self.selected_id].tasks.get('tutorial',{}))
                previous_loading=self._loading;self._loading=True
                try:self.tutorial_limit.setValue(options.max_actions)
                finally:self._loading=previous_loading

    def _training_unit_changed(self, unit, enabled):
        def change(profile):
            settings = profile.tasks.setdefault("training",{})
            units = set(settings.get("units",[]))
            units.add(unit) if enabled else units.discard(unit)
            settings["units"] = sorted(units)
        if self._selected_task == "training":
            self._change_profile(change)

    def _training_value_changed(self, key, value):
        if self._selected_task == "training":
            self._change_profile(lambda profile:profile.tasks.setdefault("training",{}).update({key:value}))

    def _training_reserve_changed(self, resource, value):
        if self._selected_task == "training":
            self._change_profile(lambda profile:profile.tasks.setdefault("training",{}).setdefault("reserves",{}).update({resource:value}))

    def _donation_goal_changed(self, value):
        if self._selected_task == "alliance_donate":
            self._change_profile(lambda profile:profile.tasks.setdefault("alliance_donate",{}).update(daily_goal=value))

    def _donation_reserve_changed(self, resource, value):
        if self._selected_task == "alliance_donate":
            self._change_profile(lambda profile:profile.tasks.setdefault("alliance_donate",{}).setdefault("reserves",{}).update({resource:value}))

    def _material_changed(self, key, value):
        if self._selected_task == "materials":
            self._change_profile(lambda profile:profile.tasks.setdefault("materials",{}).update({key:value}))

    def _gather_changed(self, key, value):
        if self._selected_task == "gather_resources":
            self._change_profile(lambda profile:profile.tasks.setdefault("gather_resources",{}).update({key:value}))

    def _barbarian_changed(self,key,value):
        if self._selected_task in ('barbarians','barbarian_chain'):
            task=self._selected_task
            self._change_profile(lambda profile:profile.tasks.setdefault(task,{}).update({key:value}))

    def _sync_barbarian_commanders(self,options):
        catalog=commander_catalog(self.store,self.selected_id,self.controller.snapshots.get(self.selected_id))
        rows=sorted(catalog['heroes'].values(),key=lambda row:(row['name'].casefold(),row['id']))
        for slot,combo in self.barbarian_commanders.items():
            selected=getattr(options,slot)
            items=[('Без второго командира',0)] if slot=='deputy' else []
            items.extend((row['name']+f" · ур.{row['level']} · {row['star']}★",row['id']) for row in rows
                if slot=='primary' or row['id']!=options.primary)
            if selected and not any(id==selected for _,id in items):
                items.append((commander_name(selected,catalog)+' · список аккаунта ещё не прочитан',selected))
            current=[(combo.itemText(i),combo.itemData(i)) for i in range(combo.count())]
            if current!=items or combo.currentData()!=selected:
                blocked=combo.blockSignals(True)
                try:
                    combo.clear()
                    for name,id in items:combo.addItem(name,id)
                    combo.setCurrentIndex(combo.findData(selected))
                finally:combo.blockSignals(blocked)
            primary=catalog['heroes'].get(str(options.primary),{})
            combo.setEnabled(bool(rows) and (slot=='primary' or primary.get('star',0)>=3))
            combo.setToolTip('Командиры этого аккаунта из памяти игры. Можно искать по имени.' if slot=='primary'
                else 'Второй командир доступен при трёх звёздах основного. «Без второго» оставляет один слот.')

    def _barbarian_commander_changed(self,slot):
        if self._loading or self._selected_task not in ('barbarians','barbarian_chain'):return
        value=self.barbarian_commanders[slot].currentData()
        if type(value) is not int:return
        catalog=commander_catalog(self.store,self.selected_id,self.controller.snapshots.get(self.selected_id))
        if value and str(value) not in catalog['heroes']:return
        task=self._selected_task
        def change(profile):
            settings=profile.tasks.setdefault(task,{})
            if slot=='deputy' and value and catalog['heroes'].get(str(settings.get('primary',3)),{}).get('star',0)<3:return
            set_commander(settings,slot,value)
            if slot=='primary' and catalog['heroes'][str(value)]['star']<3:settings['deputy']=0
        self._change_profile(change)

    def _building_changed(self,key,value):
        if self._selected_task == "buildings":
            self._change_profile(lambda profile:profile.tasks.setdefault("buildings",{}).update({key:value}))

    def _building_type_changed(self,kind,enabled):
        if self._selected_task!='buildings':return
        def change(profile):
            settings=profile.tasks.setdefault('buildings',{});types=set(settings.get('types',[4]))
            types.add(kind) if enabled else types.discard(kind)
            settings['types']=sorted(types)
        self._change_profile(change)

    def _supply_limit_changed(self,value):
        if self._selected_task in ("supply_boxes","cave_rewards"):
            self._change_profile(lambda profile:profile.tasks.setdefault(self._selected_task,{}).update(max_boxes=value))

    def _vip_shop_changed(self,key,value):
        if self._selected_task == 'vip_shop':
            self._change_profile(lambda profile:profile.tasks.setdefault('vip_shop',{}).update({key:value}))

    def _lucerne_limit_changed(self,value):
        if self._selected_task=='lucerne':
            self._change_profile(lambda profile:profile.tasks.setdefault('lucerne',{}).update(max_claims=value))

    def _tutorial_limit_changed(self,value):
        if self._selected_task=='tutorial':
            self._change_profile(lambda profile:profile.tasks.setdefault('tutorial',{}).update(max_actions=value))

    def _building_reserve_changed(self,resource,value):
        if self._selected_task == "buildings":
            self._change_profile(lambda profile:profile.tasks.setdefault("buildings",{}).setdefault("reserves",{}).update({resource:value}))

    def _research_changed(self,key,value):
        if self._selected_task=='research':
            self._change_profile(lambda p:p.tasks.setdefault('research',{}).update({key:value}))

    def show_research_priorities(self):
        if not self.selected_id:return
        key=self.selected_id;dialog=QDialog(self);dialog.setWindowTitle('Приоритеты исследований')
        dialog.resize(800,720);dialog.setMinimumSize(600,480)
        layout=QVBoxLayout(dialog);editor=ResearchPriorityEditor();layout.addWidget(editor)
        def reload():
            editor.set_options(ResearchOptions.from_settings(self.store.profile(key).tasks.get('research',{})))
        reload();editor.modeChanged.connect(self._research_mode_changed);editor.orderChanged.connect(self._research_order_changed)
        self.controller.updated.connect(reload)
        close=QDialogButtonBox(QDialogButtonBox.StandardButton.Close);close.rejected.connect(dialog.reject)
        layout.addWidget(close)
        try:dialog.exec()
        finally:self.controller.updated.disconnect(reload)

    def _research_mode_changed(self,mode):
        if self._selected_task!='research' or self._loading:return
        def change(profile):
            settings=profile.tasks.setdefault('research',{})
            options=ResearchOptions.from_settings(settings)
            settings.setdefault('priority_orders',{}).setdefault('custom',list(options.order_for('custom')))
            settings['priority_mode']=mode;settings.pop('types',None)
        self._change_profile(change)

    def _research_order_changed(self,mode,order):
        if self._selected_task!='research' or self._loading:return
        def change(profile):
            settings=profile.tasks.setdefault('research',{})
            settings.setdefault('priority_orders',{})[mode]=list(order)
            settings['priority_mode']=mode;settings.pop('types',None)
        self._change_profile(change)

    def _research_reserve_changed(self,kind,value):
        if self._selected_task=='research':
            self._change_profile(lambda p:p.tasks.setdefault('research',{}).setdefault('reserves',{}).update({kind:value}))

    def _interval_changed(self, value):
        if self._loading or not self.selected_id or not self._selected_task:
            return
        task = self._selected_task
        self._change_profile(lambda profile: profile.tasks.setdefault(task, {}).update(interval=value))

    def _schedule_changed(self, value):
        if not self._loading and self.selected_id:
            self._change_profile(lambda profile: setattr(profile, "schedule_enabled", value))

    def _name_changed(self, value):
        if self.selected_id and not self._loading:
            self._change_profile(lambda profile: setattr(profile, "account_name", value), reevaluate=False)

    def render_slots(self):
        if not self.selected_id:
            return
        slots = self.drafts[self.selected_id].slots
        rows = [(slot.id, f"{slot.start} — {slot.end}   ·   {', '.join(TASKS[task][0] for task in slot.tasks) or 'Задачи не выбраны'}") for slot in slots]
        existing = [(self.slot_list.item(i).data(Qt.ItemDataRole.UserRole), self.slot_list.item(i).text())
                    for i in range(self.slot_list.count())]
        if rows == existing:
            return
        current = self.slot_list.currentItem()
        selected = current.data(Qt.ItemDataRole.UserRole) if current else None
        self.slot_list.clear()
        for slot in self.drafts[self.selected_id].slots:
            names = ", ".join(TASKS[task][0] for task in slot.tasks)
            item = QListWidgetItem(f"{slot.start} — {slot.end}   ·   {names or 'Задачи не выбраны'}")
            item.setData(Qt.ItemDataRole.UserRole, slot.id)
            self.slot_list.addItem(item)
            if slot.id == selected:
                self.slot_list.setCurrentItem(item)

    def edit_slot(self, new=False):
        if not self.selected_id:
            return
        key = self.selected_id
        profile = self.store.profile(key)
        item = None if new else self.slot_list.currentItem()
        if not new and item is None:
            return
        old = next((slot for slot in profile.slots if item and slot.id == item.data(Qt.ItemDataRole.UserRole)), None)
        last = [old]
        def persist(value):
            def change(current):
                previous = next((s for s in current.slots if s.id == value.id), None)
                if previous != last[0]:
                    raise ValueError("Слот изменён через другое управление; откройте его заново")
                current.slots = [value if s.id == value.id else s for s in current.slots] if previous else current.slots + [value]
            self.drafts[key] = self.store.update_profile(key, change)
            last[0] = value
            self.render_slots()
            self.controller.tick()
        SlotDialog(old, self, persist).exec()

    def add_slot(self):
        self.edit_slot(new=True)

    def delete_slot(self):
        if self.selected_id and self.slot_list.currentItem():
            key = self.slot_list.currentItem().data(Qt.ItemDataRole.UserRole)
            self._change_profile(lambda profile: setattr(profile, "slots", [slot for slot in profile.slots if slot.id != key]))
            self.render_slots()

    def start_tasks(self):
        if self.selected_id:
            self.controller.start(self.selected_id)

    def _rotation_member_changed(self, item):
        key = item.data(Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == Qt.CheckState.Checked
        def change(settings):
            value = dict(settings or {"parallel":3, "duration":3600})
            members = list(value.get("members", []))
            value["members"] = list(dict.fromkeys(members + [key])) if enabled else [member for member in members if member != key]
            return value
        self.store.update_preference("rotation", change)

    def _rotation_setting_changed(self, key, value):
        self.store.update_preference("rotation", lambda settings: {"members":[], "parallel":3, "duration":3600, **(settings or {}), key:value})

    def start_rotation(self):
        try:
            self.controller.enable_rotation()
        except ValueError as error:
            self.show_error(str(error))

    def resume_rotation(self):
        item = self.rotation_members.currentItem()
        if item:
            key = item.data(Qt.ItemDataRole.UserRole)
            self.store.update_profile(key, lambda profile: setattr(profile, "manual_pause", False))
            self.controller.resume_rotation_member(key)

    def install_runtime(self):
        if not self.selected_id:
            self.show_error("Сначала выберите работающий эмулятор")
            return
        path, _ = QFileDialog.getOpenFileName(self,"Frida Server 17.26.2 Android x86_64","","Frida Server (*)")
        if path:
            self.controller.install_runtime(self.selected_id,path)

    def copy_profile(self):
        if not self.selected_id:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Копировать настройки в выбранные экземпляры")
        layout = QVBoxLayout(dialog)
        choices = QListWidget()
        for instance in self.controller.instances:
            if instance.id == self.selected_id:
                continue
            item = QListWidgetItem(Verbatim(instance.name))
            item.setData(Qt.ItemDataRole.UserRole, instance.id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            choices.addItem(item)
        layout.addWidget(choices)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            keys = [choices.item(i).data(Qt.ItemDataRole.UserRole) for i in range(choices.count())
                    if choices.item(i).checkState() == Qt.CheckState.Checked]
            for key in keys:
                self.controller.stop(key)
            self.store.copy_profile(self.selected_id, keys)
            for key in keys:
                self.drafts.pop(key, None)
            self.controller.log(self.selected_id, f"Профиль скопирован в {len(keys)} экземпляров")
            self.refresh()

    def save_preset(self):
        if not self.selected_id:
            return
        name, accepted = QInputDialog.getText(self, "Сохранить пресет", "Название")
        if accepted:
            try:
                self.store.save_preset(name, self.store.profile(self.selected_id))
                self.show_error("Пресет сохранён")
            except ValueError as error:
                self.show_error(str(error))

    def apply_preset(self):
        if not self.selected_id:
            return
        names = self.store.presets()
        if not names:
            self.show_error("Сохранённых пресетов пока нет")
            return
        name, accepted = QInputDialog.getItem(self, "Применить пресет к выбранному экземпляру", "Пресет", names, 0, False)
        if accepted:
            self.controller.stop(self.selected_id)
            self.store.apply_preset(name, [self.selected_id])
            self.drafts.pop(self.selected_id, None)
            self.select_instance(self.selected_id)
            self.controller.tick()

    def delete_preset(self):
        names = self.store.presets()
        if not names:
            return
        name, accepted = QInputDialog.getItem(self, "Удалить пресет", "Пресет", names, 0, False)
        if accepted:
            self.store.delete_preset(name)
            self.show_error("Пресет удалён")

    def export_profiles(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт профилей", "mirage-profiles.json", "JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.store.export_profiles(), ensure_ascii=False, indent=2), encoding="utf-8")

    def import_profiles(self):
        path, _ = QFileDialog.getOpenFileName(self, "Импорт профилей Mirage", "", "JSON (*.json)")
        if path:
            try:
                self.store.import_profiles(json.loads(Path(path).read_text(encoding="utf-8-sig")))
            except (OSError, ValueError, TypeError, KeyError) as error:
                self.show_error(str(error))
                return
            self.drafts.clear()
            if self.selected_id:
                self.select_instance(self.selected_id)
            self.controller.tick()

    def show_error(self, message):
        self.footer.setText(str(message))
        self.footer.setToolTip(str(message))

    def save_telegram(self):
        token = self.telegram_token.text().strip()
        if not token:
            return True
        if not re.fullmatch(r"\d{5,20}:[A-Za-z0-9_-]{20,}", token):
            self.telegram_status.setText("Введите полный токен — он сохранится автоматически")
            return False
        self.token_timer.stop()
        running = bool(self.telegram.thread and self.telegram.thread.is_alive())
        try:
            self.telegram.save_token(token)
        except (ValueError, OSError, RuntimeError) as error:
            self.show_error(str(error))
            return False
        self.telegram_token.clear()
        self.telegram_status.setText("Токен сохранён автоматически")
        if running:
            self.controller.stop_live()
            self.telegram.stop()
            self._telegram_restart = True
            self.telegram_restart_timer.start()
        return True

    def _restart_telegram_if_ready(self):
        if self.telegram.thread and self.telegram.thread.is_alive():
            return
        self.telegram_restart_timer.stop()
        if self._telegram_restart:
            self._telegram_restart = False
            self.start_telegram()

    def start_live(self):
        try:
            self.controller.start_live(self.remote)
        except (ValueError, OSError) as error:
            self.show_error(str(error))

    def start_telegram(self):
        if not self.save_telegram() or self._telegram_restart:
            return
        try:
            code = self.telegram.start()
        except (ValueError, OSError, RuntimeError) as error:
            self.show_error(str(error))
            return
        self.pair_code.setText("Команда для привязки владельца: /start " + code if not self.store.preference("telegram_owner") else "Владелец уже привязан")
        self.telegram_status.setText("Подключение…")

    def stop_telegram(self):
        self._telegram_restart = False
        self.telegram_restart_timer.stop()
        self.telegram.stop()
        self.telegram_status.setText("Остановка…")

    def show_image(self, key, data):
        dialog = QDialog(self)
        dialog.setWindowTitle("Снимок экрана · Mirage")
        layout = QVBoxLayout(dialog)
        picture = QLabel()
        image = QPixmap()
        if not image.loadFromData(data, "PNG"):
            self.show_error("Некорректный снимок экрана")
            return
        picture.setPixmap(image.scaled(1100, 700, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        layout.addWidget(picture)
        dialog.exec()

    def closeEvent(self, event):
        self.language_timer.stop()
        self.token_timer.stop()
        self.telegram_restart_timer.stop()
        if self.telegram_token.text().strip():
            self.save_telegram()
        self._telegram_restart = False
        self.telegram_restart_timer.stop()
        self.telegram.stop()
        self.controller.shutdown()
        event.accept()
