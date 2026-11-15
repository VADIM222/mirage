from concurrent.futures import Future, TimeoutError

from PySide6.QtCore import QObject, Signal, Slot

from .adb import Adb
from .model import Power
from .ui import STATE_TEXT
from .workflows import VERIFIED_WORKFLOWS


class RemoteBackend(QObject):
    requested = Signal(object)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.requested.connect(self._request)

    def instances(self):
        return list(self.controller.instances)

    def _call(self, method, key):
        future = Future()
        self.requested.emit((method, key, future))
        try:
            return future.result(timeout=10)
        except TimeoutError:
            future.cancel()
            raise RuntimeError("Команда не выполнена: окно Mirage не ответило за 10 секунд") from None

    @Slot(object)
    def _request(self, request):
        method, key, future = request
        if not future.set_running_or_notify_cancel():
            return
        try:
            if method not in ("rotation_start", "rotation_stop"):
                self.controller.instance(key)
            if method == "start":
                if not self.controller.start(key):
                    raise RuntimeError("Запуск не выполнен: проверьте выбранные задачи и готовность игровых сценариев в Mirage")
                result = "Запуск задач принят. Состояние видно в меню эмулятора."
            elif method == "stop":
                self.controller.stop(key)
                result = "Задачи остановлены; ручная пауза включена."
            elif method == "rotation_start":
                self.controller.enable_rotation()
                result = "Ротация включена"
            elif method == "rotation_stop":
                self.controller.disable_rotation()
                result = "Ротация остановлена"
            else:
                raise ValueError("Неизвестная команда")
            future.set_result(result)
        except Exception as error:
            future.set_exception(error)

    def start(self, key):
        return self._call("start", key)

    def stop(self, key):
        return self._call("stop", key)

    def rotation(self, enabled):
        return self._call("rotation_start" if enabled else "rotation_stop", "")

    def live_url(self):
        return self.controller.live_url

    def screenshot(self, key):
        instance = next(instance for instance in self.instances() if instance.id == key)
        if instance.power != Power.ONLINE:
            raise RuntimeError("Эмулятор выключен")
        adb = Adb(instance)
        adb.connect()
        return adb.screenshot()

    def status(self, key):
        decision = self.controller.decisions.get(key)
        return (STATE_TEXT[decision.state] + " · " + decision.reason) if decision else "Автоматизация остановлена"
