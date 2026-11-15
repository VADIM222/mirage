"""Research priority tables: internal row moves preserve every technology exactly once."""
import json

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QHBoxLayout, QHeaderView,
    QLabel, QPushButton, QStackedWidget, QTableView, QTabWidget, QVBoxLayout, QWidget)

from .model import RESEARCH_MODES, RESEARCH_TYPES, research_default_order
from .i18n import translate
from .localized_widgets import QComboBox, QLabel, QPushButton, QTabWidget


class PriorityModel(QAbstractTableModel):
    orderChanged=Signal(object)
    MIME='application/x-mirage-research-priority'

    def __init__(self,order,parent=None):
        super().__init__(parent);self.order=list(order)

    def rowCount(self,parent=QModelIndex()):return 0 if parent.isValid() else len(self.order)
    def columnCount(self,parent=QModelIndex()):return 0 if parent.isValid() else 3

    def data(self,index,role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0<=index.row()<len(self.order):return None
        kind=self.order[index.row()]
        if role==Qt.ItemDataRole.DisplayRole:
            return translate((str(index.row()+1),RESEARCH_TYPES[kind],'Экономика' if kind<200 else 'Военные')[index.column()])
        if role==Qt.ItemDataRole.UserRole:return kind
        if role==Qt.ItemDataRole.ToolTipRole:return translate('Перетащите строку выше или ниже, чтобы изменить приоритет')

    def headerData(self,section,orientation,role=Qt.ItemDataRole.DisplayRole):
        if orientation==Qt.Orientation.Horizontal and role==Qt.ItemDataRole.DisplayRole:
            return translate(('Приоритет','Технология','Ветка')[section])

    def flags(self,index):
        if not index.isValid():return Qt.ItemFlag.ItemIsDropEnabled
        return Qt.ItemFlag.ItemIsEnabled|Qt.ItemFlag.ItemIsSelectable|Qt.ItemFlag.ItemIsDragEnabled|Qt.ItemFlag.ItemIsDropEnabled

    def mimeTypes(self):return [self.MIME]
    def supportedDropActions(self):return Qt.DropAction.MoveAction
    def supportedDragActions(self):return Qt.DropAction.MoveAction

    def mimeData(self,indexes):
        mime=QMimeData();rows=sorted({i.row() for i in indexes if i.isValid()})
        if len(rows)==1:
            mime.setData(self.MIME,json.dumps({'model':id(self),'kind':self.order[rows[0]]}).encode())
        return mime

    def dropMimeData(self,mime,action,row,column,parent):
        if action!=Qt.DropAction.MoveAction or not mime.hasFormat(self.MIME):return False
        try:
            payload=json.loads(bytes(mime.data(self.MIME)))
            if payload.get('model')!=id(self) or type(payload.get('kind')) is not int:return False
            source=self.order.index(payload['kind'])
        except (ValueError,TypeError,AttributeError):return False
        destination=row if row>=0 else parent.row() if parent.isValid() else len(self.order)
        return self.moveRows(QModelIndex(),source,1,QModelIndex(),destination)

    def moveRows(self,sourceParent,sourceRow,count,destinationParent,destinationChild):
        if (sourceParent.isValid() or destinationParent.isValid() or count!=1
                or not 0<=sourceRow<len(self.order) or not 0<=destinationChild<=len(self.order)
                or destinationChild in (sourceRow,sourceRow+1)):return False
        if not self.beginMoveRows(sourceParent,sourceRow,sourceRow,destinationParent,destinationChild):return False
        kind=self.order.pop(sourceRow)
        self.order.insert(destinationChild-1 if destinationChild>sourceRow else destinationChild,kind)
        self.endMoveRows()
        self.dataChanged.emit(self.index(0,0),self.index(len(self.order)-1,0),[Qt.ItemDataRole.DisplayRole])
        self.orderChanged.emit(tuple(self.order));return True

    def set_order(self,order):
        order=list(order)
        if order==self.order:return
        self.beginResetModel();self.order=order;self.endResetModel()


class PriorityView(QTableView):
    def dropEvent(self,event):
        if event.source() is not self:event.ignore();return
        position=self.indexAt(event.position().toPoint())
        row=position.row() if position.isValid() else self.model().rowCount()
        if position.isValid() and event.position().y()>self.visualRect(position).center().y():row+=1
        if self.model().dropMimeData(event.mimeData(),Qt.DropAction.MoveAction,row,0,QModelIndex()):
            event.setDropAction(Qt.DropAction.MoveAction);event.accept()
        else:event.ignore()


class PriorityTable(QWidget):
    def __init__(self,order,parent=None):
        super().__init__(parent);layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.model=PriorityModel(order,self);self.view=PriorityView();self.view.setModel(self.model)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.view.setDragDropOverwriteMode(False);self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.setDropIndicatorShown(True);self.view.setAlternatingRowColors(True)
        self.view.setMinimumHeight(220);self.view.verticalHeader().hide()
        header=self.view.horizontalHeader();header.setSectionResizeMode(0,QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1,QHeaderView.ResizeMode.Stretch);header.setSectionResizeMode(2,QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.view);buttons=QHBoxLayout()
        self.up=QPushButton('↑ Выше');self.down=QPushButton('↓ Ниже')
        self.up.clicked.connect(lambda:self.move(-1));self.down.clicked.connect(lambda:self.move(1))
        buttons.addWidget(self.up);buttons.addWidget(self.down);buttons.addStretch();layout.addLayout(buttons)

    def move(self,delta):
        row=self.view.currentIndex().row();target=row+delta
        if row<0 or not 0<=target<self.model.rowCount():return
        if self.model.moveRows(QModelIndex(),row,1,QModelIndex(),target if delta<0 else target+1):
            self.view.selectRow(target);self.view.scrollTo(self.model.index(target,0))


class ResearchPriorityEditor(QWidget):
    modeChanged=Signal(str)
    orderChanged=Signal(str,object)

    def __init__(self,parent=None):
        super().__init__(parent);self.loading=False
        layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        self.mode=QComboBox()
        for key,title in RESEARCH_MODES.items():self.mode.addItem(title,key)
        layout.addWidget(self.mode);self.pages=QStackedWidget();layout.addWidget(self.pages)
        self.tables={}
        for mode in RESEARCH_MODES:
            if mode=='balanced':
                tabs=QTabWidget()
                for branch,title in (('economy','Экономика'),('military','Военные')):
                    table=PriorityTable(research_default_order(branch));self.tables['balanced_'+branch]=table
                    table.model.orderChanged.connect(lambda order,branch=branch:self.changed('balanced',branch,order))
                    tabs.addTab(table,title)
                self.pages.addWidget(tabs)
            else:
                table=PriorityTable(research_default_order(mode));self.tables[mode]=table
                table.model.orderChanged.connect(lambda order,mode=mode:self.changed(mode,None,order))
                self.pages.addWidget(table)
        self.note=QLabel();self.note.setWordWrap(True);layout.addWidget(self.note)
        self.mode.currentIndexChanged.connect(self.mode_changed);self.mode_changed(0)

    def mode_changed(self,index):
        self.pages.setCurrentIndex(index)
        mode=self.mode.currentData()
        text=('50/50: один запуск экономики, один военный. Здесь задаётся порядок внутри каждой ветки; '
            'если ветка недоступна, бот проверит вторую.' if mode=='balanced' else
            'Чем выше строка, тем выше приоритет. Перетаскивайте строки или используйте ↑ / ↓.')
        self.note.setText(text+' Порядок каждого режима сохраняется отдельно.')
        if not self.loading:self.modeChanged.emit(mode)

    def changed(self,mode,branch,order):
        if self.loading:return
        if mode=='balanced':
            order=tuple(self.tables['balanced_economy'].model.order)+tuple(self.tables['balanced_military'].model.order)
        self.orderChanged.emit(mode,tuple(order))

    def set_options(self,options):
        self.loading=True
        try:
            for mode in RESEARCH_MODES:
                order=options.order_for(mode)
                if mode=='balanced':
                    self.tables['balanced_economy'].model.set_order(k for k in order if k<200)
                    self.tables['balanced_military'].model.set_order(k for k in order if k>=200)
                else:self.tables[mode].model.set_order(order)
            mode='custom' if options.priority_mode=='legacy' else options.priority_mode
            self.mode.setCurrentIndex(self.mode.findData(mode));self.mode_changed(self.mode.currentIndex())
        finally:self.loading=False
