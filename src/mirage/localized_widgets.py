"""Text-only Qt adapters with reversible, signal-blocked live retranslation."""
import weakref

from PySide6 import QtWidgets as QtW
from PySide6.QtCore import QCoreApplication, QLibraryInfo, QSignalBlocker, Qt, QTranslator

from .i18n import get_language, translate


_objects = weakref.WeakValueDictionary()
SOURCE_ROLE = int(Qt.ItemDataRole.UserRole) + 901


def configure_qt_language(language):
    app = QtW.QApplication.instance()
    previous = getattr(app, '_mirage_qt_translator', None)
    if previous is not None:
        app.removeTranslator(previous)
        previous.deleteLater()
    app._mirage_qt_translator = None
    if language == 'ru':
        translator = QTranslator(app)
        if translator.load('qtbase_ru', QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            app.installTranslator(translator)
            app._mirage_qt_translator = translator


def retranslate_widgets():
    for obj in list(_objects.values()):
        try:
            obj.retranslate()
        except RuntimeError:
            # Qt may have deleted a child before its Python wrapper is collected.
            _objects.pop(id(obj), None)


def _widget(base, *, text=False, extra=()):
    properties = ['toolTip', 'windowTitle', *extra]
    if text:
        properties.append('text')

    class Localized(base):
        def __init__(self, *args, **kwargs):
            self._sources = {}
            super().__init__(*args, **kwargs)
            for name in properties:
                value = args[0] if name == 'text' and args and isinstance(args[0], str) else getattr(self, name)()
                self._sources[name] = value
                getattr(base, 'set' + name[0].upper() + name[1:])(self, translate(value))
            _objects[id(self)] = self

        def retranslate(self):
            with QSignalBlocker(self):
                for name, source in self._sources.items():
                    getattr(base, 'set' + name[0].upper() + name[1:])(self, translate(source))

    for name in properties:
        setter = 'set' + name[0].upper() + name[1:]
        def assign(self, value, _name=name, _setter=setter):
            self._sources[_name] = value
            getattr(base, _setter)(self, translate(value))
        setattr(Localized, setter, assign)
    Localized.__name__ = base.__name__
    return Localized


QLabel = _widget(QtW.QLabel, text=True)
QPushButton = _widget(QtW.QPushButton, text=True)
QCheckBox = _widget(QtW.QCheckBox, text=True)
QLineEdit = _widget(QtW.QLineEdit, extra=('placeholderText',))
QSpinBox = _widget(QtW.QSpinBox, extra=('suffix', 'prefix'))
QDialog = _widget(QtW.QDialog)
QMainWindow = _widget(QtW.QMainWindow)


class QDialogButtonBox(_widget(QtW.QDialogButtonBox)):
    def retranslate(self):
        super().retranslate()
        labels = {'Close': 'Close', 'Cancel': 'Cancel', 'Ok': 'OK', 'Yes': 'Yes',
                  'No': 'No', 'Save': 'Save', 'Open': 'Open', 'Apply': 'Apply'}
        for name, source in labels.items():
            control = self.button(getattr(self.StandardButton, name))
            if control is not None:
                control.setText(QCoreApplication.translate('QPlatformTheme', source))


class QPlainTextEdit(_widget(QtW.QPlainTextEdit, extra=('placeholderText',))):
    def setPlainText(self, text):
        self._plain_source = text
        super().setPlainText(translate(text))

    def appendPlainText(self, text):
        self._plain_source = getattr(self, '_plain_source', '')
        self._plain_source = '\n'.join((self._plain_source, text)).lstrip('\n')
        maximum = self.maximumBlockCount()
        if maximum:
            self._plain_source = '\n'.join(self._plain_source.split('\n')[-maximum:])
        super().appendPlainText(translate(text))

    def clear(self):
        self._plain_source = ''
        super().clear()

    def retranslate(self):
        super().retranslate()
        if hasattr(self, '_plain_source'):
            scroll = self.verticalScrollBar().value()
            with QSignalBlocker(self):
                super().setPlainText(translate(self._plain_source))
            self.verticalScrollBar().setValue(scroll)


class QFormLayout(QtW.QFormLayout):
    def addRow(self, *args):
        if args and isinstance(args[0], str):
            args = (QLabel(args[0]), *args[1:])
        return super().addRow(*args)


class QComboBox(_widget(QtW.QComboBox)):
    def addItem(self, *args):
        index = self.count()
        super().addItem(*args)
        source = next((arg for arg in args if isinstance(arg, str)), self.itemText(index))
        if not hasattr(self, '_item_sources'):
            self._item_sources = {}
        self._item_sources[index] = source
        self.setItemData(index, source, SOURCE_ROLE)
        super().setItemText(index, translate(source))

    def addItems(self, texts):
        for text in texts:
            self.addItem(text)

    def setItemText(self, index, text):
        self._item_sources[index] = text
        self.setItemData(index, text, SOURCE_ROLE)
        super().setItemText(index, translate(text))

    def retranslate(self):
        super().retranslate()
        with QSignalBlocker(self):
            for index in range(self.count()):
                source = getattr(self, '_item_sources', {}).get(index, self.itemData(index, SOURCE_ROLE))
                if source is not None:
                    super().setItemText(index, translate(source))


class QTabWidget(_widget(QtW.QTabWidget)):
    def addTab(self, *args):
        source = args[-1]
        index = super().addTab(*args[:-1], translate(source))
        self.widget(index).setProperty('_mirage_tab_source', source)
        return index

    def retranslate(self):
        super().retranslate()
        for index in range(self.count()):
            source = self.widget(index).property('_mirage_tab_source')
            if source is not None:
                self.setTabText(index, translate(source))


class QTreeWidget(_widget(QtW.QTreeWidget)):
    def setHeaderLabels(self, labels):
        self._header_sources = list(labels)
        super().setHeaderLabels([translate(text) for text in labels])

    def retranslate(self):
        super().retranslate()
        if hasattr(self, '_header_sources'):
            super().setHeaderLabels([translate(text) for text in self._header_sources])


class QTreeWidgetItem(QtW.QTreeWidgetItem):
    def __init__(self, *args):
        self._sources = {}
        super().__init__(*args)
        for column in range(self.columnCount()):
            self._sources[column] = super().text(column)
            super().setText(column, translate(self._sources[column]))
        _objects[id(self)] = self

    def setText(self, column, text):
        self._sources[column] = text
        super().setText(column, translate(text))

    def retranslate(self):
        tree = self.treeWidget()
        blocker = QSignalBlocker(tree) if tree is not None else None
        try:
            for column, source in self._sources.items():
                super().setText(column, translate(source))
        finally:
            del blocker


class QListWidgetItem(QtW.QListWidgetItem):
    def __init__(self, *args):
        super().__init__(*args)
        self._source = next((arg for arg in args if isinstance(arg, str)), super().text())
        super().setText(translate(self._source))
        _objects[id(self)] = self

    def setText(self, text):
        self._source = text
        super().setText(translate(text))

    def retranslate(self):
        widget = self.listWidget()
        blocker = QSignalBlocker(widget) if widget is not None else None
        try:
            super().setText(translate(self._source))
        finally:
            del blocker


class QMessageBox:
    @staticmethod
    def information(parent, title, text, *args):
        return QtW.QMessageBox.information(parent, translate(title), translate(text), *args)


class QInputDialog:
    @staticmethod
    def getText(parent, title, text, *args, **kwargs):
        return QtW.QInputDialog.getText(parent, translate(title), translate(text), *args, **kwargs)

    @staticmethod
    def getItem(parent, title, text, items, *args, **kwargs):
        return QtW.QInputDialog.getItem(parent, translate(title), translate(text), items, *args, **kwargs)


class QFileDialog:
    @staticmethod
    def getSaveFileName(parent, caption='', directory='', filter='', *args, **kwargs):
        if get_language() == 'en':
            kwargs['options'] = kwargs.get('options', QtW.QFileDialog.Option(0)) | QtW.QFileDialog.Option.DontUseNativeDialog
        return QtW.QFileDialog.getSaveFileName(parent, translate(caption), directory, translate(filter), *args, **kwargs)

    @staticmethod
    def getOpenFileName(parent, caption='', directory='', filter='', *args, **kwargs):
        if get_language() == 'en':
            kwargs['options'] = kwargs.get('options', QtW.QFileDialog.Option(0)) | QtW.QFileDialog.Option.DontUseNativeDialog
        return QtW.QFileDialog.getOpenFileName(parent, translate(caption), directory, translate(filter), *args, **kwargs)
