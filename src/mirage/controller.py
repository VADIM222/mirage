from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Signal, Slot, QTimer

from .adb import Adb
from .commanders import commander_catalog
from .dispatcher import Dispatcher
from .emulators import CommandError, Discovery, close, launch
from .memory import MemoryError, Reader
from .model import Instance, MIN_CPUS, MIN_MEMORY_MB, Power, Profile, RunState, Snapshot, TASKS
from .scheduler import Decision, Rotation, decide
from .storage import Store
from .workflows import Cancelled, Engine, NotReady, RETURN_TO_CITY, VERIFIED_WORKFLOWS, workflow_for
from .model import BarbarianOptions, BuildingOptions, DonationOptions, GatherOptions, LucerneOptions, MaterialOptions, ResearchOptions, SupplyBoxOptions, TrainingOptions, TutorialOptions, VipShopOptions


class Controller(QObject):
    updated = Signal()
    error = Signal(str)
    image_ready = Signal(str, bytes)
    job_finished = Signal(str, int, object, object)
    live_status = Signal(str)
    notice = Signal(str, str, str)

    def __init__(self, store: Store, *, auto_refresh: bool = True):
        super().__init__()
        self.store = store
        self.instances: list[Instance] = []
        self.readers: dict[str, Reader] = {}
        self.snapshots: dict[str, Snapshot] = {}
        self.reasons: dict[str, str] = {}
        self.decisions = {}
        self.dispatcher = Dispatcher(workers=int(store.preference("workers", 2)))
        self.job_finished.connect(self._completed)
        self._closing = False
        self._auto_refresh = auto_refresh
        self._initial_ids: set[str] = set()
        self._last_memory_poll = 0.0
        self._last_discovery = 0.0
        self._due: dict[tuple[str,str],float] = {}
        self._task_errors: dict[str,str] = {}
        self._waiting_game: dict[str,str] = {}
        self._retry_at: dict[str,float] = {}
        self._reconnect_attempts: dict[str,int] = {}
        self._reconnect_player: dict[str,int] = {}
        self._entry_started: dict[str,float] = {}
        self._entry_attempted: dict[str,set[int]] = {}
        self._game_launch_attempted: set[str] = set()
        self._active_tasks: dict[str, tuple[str, str | None]] = {}
        self._active_observations: dict[str, list[Snapshot | None]] = {}
        self._launching: set[str] = set()
        self._launch_deadlines: dict[str,float] = {}
        self._pending_close: set[str] = set()
        self._closing_instances: set[str] = set()
        self._pending_prepare: set[str] = set()
        self._pending_retire: set[str] = set()
        self.rotation: Rotation | None = None
        self.live_server = None
        self.live_tunnel = None
        self.live_url = ""
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        if auto_refresh:
            self.timer.start()
            self.refresh()

    def instance(self, key: str) -> Instance:
        return next(instance for instance in self.instances if instance.id == key)

    def _submit(self, key, operation):
        if self._closing:
            return False
        return self.dispatcher.submit(key, operation,
                                      lambda k,g,r,e: self.job_finished.emit(k,g,r,e))

    def log(self, key, message, level="info"):
        self.store.event(key, level, message)
        if level == "error":
            self.notice.emit(key or "Mirage", message, level)

    def refresh(self):
        self._last_discovery = time.monotonic()
        def work(cancelled):
            discovery = Discovery(self.store.preference("emulator_dirs", []))
            return "discovery", discovery.discover(), discovery.errors
        self._submit("__discovery__", work)

    def probe(self, key: str):
        instance = self.instance(key)
        if instance.power != Power.ONLINE:
            self.error.emit("Сначала запустите выбранный эмулятор")
            return
        if instance.cpus < MIN_CPUS or instance.memory_mb < MIN_MEMORY_MB:
            self.error.emit("Для игры нужны минимум 2 CPU-ядра и 2 ГБ ОЗУ; выполните подготовку экземпляра")
            return
        server = self.store.preference("runtime_path", "/data/local/tmp/mirage-frida-server")
        expected_player = self._reconnect_player.get(key)
        previous = self.snapshots.get(key)
        if (expected_player is None and previous is not None
                and decide(instance,self.store.profile(key),datetime.now(),True).state == RunState.RUNNING):
            expected_player = previous.player_id

        def entry_allowed():
            current = self.instance(key)
            return (current.power == Power.ONLINE and current.cpus >= MIN_CPUS and current.memory_mb >= MIN_MEMORY_MB
                    and key not in self._closing_instances
                    and decide(current,self.store.profile(key),datetime.now(),True).state == RunState.RUNNING)

        def work(cancelled):
            reader = self.readers.get(key)
            if reader and reader.instance != instance:
                reader.close()
                reader = None
            reader = reader or Reader(instance, server)
            new = getattr(reader, "script", None) is None
            try:
                if new:
                    reader.connect()
                snapshot = reader.snapshot()
                if expected_player is not None and snapshot.player_id != expected_player:
                    raise MemoryError("После переподключения открыт другой персонаж; ввод остановлен")
                if cancelled.is_set():
                    reader.close()
                    return "cancelled",
                return "memory", key, reader, snapshot
            except Exception as error:
                reader.close()
                if cancelled.is_set():
                    return "cancelled",
                from .bootstrap import enter_game, loading_error, missing_process, start_game
                if (loading_error(error) or missing_process(error)) and entry_allowed():
                    started = self._entry_started.setdefault(key,time.monotonic())
                    if time.monotonic()-started >= 180:
                        return "entry_failed", key, "Вход в игру не завершился за 180 секунд"
                    try:
                        entry = (start_game(reader,cancelled,entry_allowed,self._game_launch_attempted)
                            if missing_process(error) else
                            enter_game(reader,cancelled,entry_allowed,self._entry_attempted.setdefault(key,set())))
                    except Cancelled:
                        return "cancelled",
                    return "entry_wait", key, entry, expected_player
                if expected_player is not None:
                    return "reconnect", key, str(error), expected_player
                raise

        if self._submit(key, work):
            if key not in self.snapshots:
                self.reasons[key] = "Подключение к данным игры…"
            self.updated.emit()

    def screen(self, key):
        instance = self.instance(key)
        if instance.power != Power.ONLINE:
            self.error.emit("Эмулятор выключен")
            return

        def work(cancelled):
            adb = Adb(instance)
            adb.connect()
            return "image", key, adb.screenshot()

        self._submit(key, work)

    def install_runtime(self, key, path):
        from .runtime import install
        instance = self.instance(key)
        self._submit(key, lambda cancelled: ("runtime", key, install(instance,Path(path))))

    def start_live(self, backend):
        if self.live_server or self.dispatcher.busy("__live__"):
            raise ValueError("Live уже включён или запускается")
        from .secrets import decrypt
        secret = self.store.preference("telegram_secret")
        if not secret or not self.store.preference("telegram_owner"):
            raise ValueError("Сначала подключите Telegram и привяжите владельца")
        token = decrypt(secret)
        def work(cancelled):
            from .live import Server, Tunnel, ensure_cloudflared
            server = Server(backend, token, lambda: self.store.preference("telegram_owner"))
            tunnel = Tunnel()
            try:
                binary = ensure_cloudflared(self.store.path.parent / "runtime", cancelled, self.live_status.emit)
                if cancelled.is_set():
                    return "cancelled",
                self.live_status.emit("Подключение HTTPS-туннеля…")
                url = tunnel.start(binary, server.start())
                if cancelled.is_set():
                    tunnel.stop()
                    server.stop()
                    return "cancelled",
                return "live", server, tunnel, url
            except Exception:
                tunnel.stop()
                server.stop()
                raise
        self._submit("__live__", work)
        self.live_status.emit("Подключение HTTPS-туннеля…")

    def stop_live(self):
        self.dispatcher.cancel("__live__")
        if self.live_tunnel:
            self.live_tunnel.stop()
            self.live_tunnel = None
        if self.live_server:
            self.live_server.stop()
            self.live_server = None
        self.live_url = ""
        self.live_status.emit("Live выключен")

    @staticmethod
    def _dispose_result(result):
        if result and result[0] == "memory":
            result[2].close()
        elif result and result[0] == "live":
            result[2].stop()
            result[1].stop()

    def prepare_instance(self, key):
        self.stop(key)
        self._pending_prepare.add(key)
        self._prepare_pending(key)

    def _prepare_pending(self, key):
        if self.dispatcher.busy(key):
            return
        from .preparation import prepare
        instance = self.instance(key)
        reader = self.readers.get(key)
        def work(cancelled):
            if reader:
                reader.close()
            message = prepare(instance, self.store.path.parent / "backups", cancelled)
            return "prepared", key, message
        if self._submit(key, work):
            self._pending_prepare.discard(key)

    def launch(self, key):
        instance = self.instance(key)
        if instance.power != Power.OFF or key in self._launching:
            self.error.emit("Экземпляр уже запущен или запускается")
            return False
        occupied = {i.id for i in self.instances if i.power in (Power.ONLINE, Power.BOOTING)} | self._launching
        running = len(occupied)
        if running >= int(self.store.preference("device_limit", 3)):
            self.error.emit("Достигнут лимит одновременно запущенных экземпляров для этого ПК")
            return False
        if instance.cpus < MIN_CPUS or instance.memory_mb < MIN_MEMORY_MB:
            self.error.emit("Для запуска игры нужны минимум 2 CPU-ядра и 2 ГБ ОЗУ")
            return False
        self._launching.add(key)
        self._launch_deadlines[key] = time.monotonic() + 120
        def work(cancelled):
            if cancelled.is_set():
                return "cancelled",
            launch(instance)
            return "emulator", key, "Запуск эмулятора"
        if not self._submit(key, work):
            self._launching.discard(key)
            return False
        return True

    def close_instance(self, key):
        self.stop(key)
        self._pending_close.add(key)
        self._closing_instances.add(key)
        self._close_pending(key)

    def _close_pending(self, key):
        if self.dispatcher.busy(key):
            return
        instance = self.instance(key)
        if instance.power == Power.OFF:
            self._pending_close.discard(key)
            self._closing_instances.discard(key)
            return
        reader = self.readers.get(key)
        def work(cancelled):
            if reader:
                reader.close()
            if cancelled.is_set():
                return "cancelled",
            close(instance)
            return "closed", key, "Эмулятор выключен"
        if self._submit(key, work):
            self._pending_close.discard(key)

    def start(self, key):
        instance = self.instance(key)
        if instance.cpus < MIN_CPUS or instance.memory_mb < MIN_MEMORY_MB:
            self.error.emit("Для игры нужны минимум 2 CPU-ядра и 2 ГБ ОЗУ")
            return False
        def change(profile):
            enabled = [task for task, settings in profile.tasks.items() if settings.get("enabled")]
            if profile.schedule_enabled:
                enabled = list(dict.fromkeys(task for slot in profile.slots for task in slot.tasks))
            if not enabled:
                raise ValueError("Выберите игровые задачи")
            missing = [TASKS[task][0] for task in enabled if task not in VERIFIED_WORKFLOWS]
            if missing:
                raise ValueError("Сценарии ещё не прошли живую проверку: " + ", ".join(missing))
            for task in enabled:
                workflow_for(task,profile.tasks.get(task,{}))
            profile.manual_pause = False
            profile.manual_run = not profile.schedule_enabled
        try:
            self.store.update_profile(key, change)
        except ValueError as error:
            self.error.emit(str(error))
            return False
        self._task_errors.pop(key, None)
        self._waiting_game.pop(key, None)
        self._reconnect_attempts.pop(key, None)
        self._reconnect_player.pop(key, None)
        self._entry_started.pop(key, None)
        self._entry_attempted.pop(key, None)
        self._game_launch_attempted.discard(key)
        if self.rotation:
            self.rotation.resume(key)
        instance = self.instance(key)
        snapshot = self.snapshots.get(key)
        if instance.power == Power.ONLINE and (snapshot is None or not snapshot.fresh(time.monotonic())):
            self.probe(key)
        self.tick()
        return True

    def stop(self, key):
        def change(profile):
            profile.manual_pause = True
            profile.manual_run = False
        self.store.update_profile(key, change)
        self.dispatcher.cancel(key)
        if self.rotation:
            self.rotation.pause(key)
        self.reasons[key] = "Ручная пауза"
        self.log(key, "Ручная остановка; автоматическое возобновление приостановлено")
        self.tick()

    @Slot(str, int, object, object)
    def _completed(self, key, generation, result, error):
        accepted = self.dispatcher.acknowledge(key, generation)
        self._active_tasks.pop(key, None)
        self._active_observations.pop(key, None)
        if not accepted:
            self._dispose_result(result)
            self._launching.discard(key)
            return
        if self._closing:
            self._dispose_result(result)
            return
        if error is not None:
            if key == "__live__":
                self.live_status.emit(str(error))
            self._launching.discard(key)
            self._closing_instances.discard(key)
            if self.rotation and key in self.rotation.members:
                self.rotation.pause(key)
            message = str(error)[:1500]
            if message == "Результат отменённого задания":
                if result and result[0] == "memory":
                    result[2].close()
                self.updated.emit()
                return
            self.reasons[key] = message
            self.snapshots.pop(key, None)
            self._retry_at[key] = time.monotonic() + 30
            self.log(None if key.startswith("__") else key, message, "error")
            self.updated.emit()
            return
        if not result:
            return
        if result[0] == "discovery":
            self.instances = result[1]
            online_ids = {i.id for i in self.instances if i.power == Power.ONLINE}
            for stale in self.readers.keys() - online_ids:
                if stale not in self._pending_retire:
                    self.dispatcher.cancel(stale)
                    self._pending_retire.add(stale)
                self.snapshots.pop(stale, None)
            self._launching.difference_update(i.id for i in self.instances if i.power != Power.OFF)
            self._closing_instances.difference_update(i.id for i in self.instances if i.power == Power.OFF)
            for instance in self.instances:
                if instance.id not in self._initial_ids:
                    self.store.update_profile(instance.id, lambda profile: setattr(profile, "manual_run", False))
                    self._initial_ids.add(instance.id)
            for message in result[2]:
                self.log(None, message, "error")
        elif result[0] == "memory":
            _, instance_id, reader, snapshot = result
            previous = self.snapshots.get(instance_id)
            self.readers[instance_id] = reader
            self.snapshots[instance_id] = snapshot
            commander_catalog(self.store,instance_id,snapshot)
            self._entry_started.pop(instance_id, None)
            self._game_launch_attempted.discard(instance_id)
            self._retry_at.pop(instance_id, None)
            self.reasons[instance_id] = self._waiting_game.get(instance_id) or "Память подключена · PID " + str(snapshot.pid)
            if previous is None:
                self.log(instance_id, f"Получены данные игрового процесса {snapshot.pid}; RoK {snapshot.game_version}")
        elif result[0] in ("entry_wait", "entry_failed"):
            instance_id = result[1]
            self.readers.pop(instance_id, None)
            self.snapshots.pop(instance_id, None)
            if result[0] == "entry_failed":
                self._task_errors[instance_id] = result[2]
                self.reasons[instance_id] = result[2]
                self.log(instance_id,result[2],"error")
            else:
                _,_,entry,player_id = result
                if player_id is not None:
                    self._reconnect_player[instance_id] = player_id
                self.reasons[instance_id] = entry.reason
                self._retry_at[instance_id] = time.monotonic()+3
                if entry.tapped or entry.launched:
                    self.log(instance_id,entry.reason)
        elif result[0] == "reconnect":
            _, instance_id, message, player_id = result
            self.readers.pop(instance_id, None)
            self.snapshots.pop(instance_id, None)
            self._waiting_game.pop(instance_id, None)
            self._reconnect_player[instance_id] = player_id
            attempts = self._reconnect_attempts.get(instance_id, 0)+1
            self._reconnect_attempts[instance_id] = attempts
            if attempts > 3:
                reason = "Переподключение остановлено после трёх попыток: " + message
                self._task_errors[instance_id] = reason
                self.reasons[instance_id] = reason
                self.log(instance_id, reason, "error")
            else:
                self._retry_at[instance_id] = time.monotonic()+5*attempts
                reason = f"Переподключение к тому же персонажу ({attempts}/3): {message}"
                self.reasons[instance_id] = reason
                self.log(instance_id, reason, "warning")
        elif result[0] == "image":
            self.image_ready.emit(result[1], result[2])
        elif result[0] in ("emulator", "closed"):
            if result[0] == "closed":
                self.readers.pop(key, None)
                self.snapshots.pop(key, None)
            self.log(result[1], result[2])
            self.refresh()
        elif result[0] == "runtime":
            self.reasons[result[1]] = result[2]
            self.log(result[1],result[2])
        elif result[0] == "prepared":
            self.readers.pop(key, None)
            self.snapshots.pop(key, None)
            self.reasons[key] = result[2]
            self.log(key, result[2])
            self.refresh()
        elif result[0] == "retired":
            self.readers.pop(key, None)
            self.snapshots.pop(key, None)
        elif result[0] == "live":
            _, self.live_server, self.live_tunnel, self.live_url = result
            self.live_status.emit("Live включён · до 1 кадра/с · кнопка доступна в Telegram")
        elif result[0] == "task":
            _, instance_id, task_id, snapshot, failure = result
            if isinstance(failure, tuple):
                message = failure[1]
                if self._waiting_game.get(instance_id) != message:
                    self.log(instance_id, message)
                self._waiting_game[instance_id] = message
                self.reasons[instance_id] = message
                self._due[(instance_id, task_id)] = time.monotonic() + 5
            elif failure:
                self._task_errors[instance_id] = failure
                self.log(instance_id, failure, "error")
            else:
                if task_id=='research' and snapshot is not None:
                    next_branch=snapshot.values.get('research_next_branch')
                    if next_branch in ('economy','military'):
                        def save_branch(profile):
                            settings=profile.tasks.setdefault('research',{})
                            if settings.get('priority_mode')=='balanced':settings['next_branch']=next_branch
                        self.store.update_profile(instance_id,save_branch)
                interval = self.store.profile(instance_id).tasks.get(task_id, {}).get("interval", 60)
                prerequisite=(task_id=='research' and snapshot is not None
                    and snapshot.values.get('research_prerequisite_pending') is True)
                space_pending=(task_id=='buildings' and snapshot is not None
                    and snapshot.values.get('building_space_pending') is True)
                battle_pending=(task_id in ('barbarians','barbarian_chain') and snapshot is not None
                    and snapshot.values.get('barbarian_pending') is True)
                survey_pending=(task_id=='barbarian_chain' and snapshot is not None
                    and snapshot.values.get('barbarian_survey_pending') is True)
                self._reconnect_attempts.pop(instance_id, None)
                self._reconnect_player.pop(instance_id, None)
                self._due[(instance_id, task_id)] = time.monotonic() + (1 if survey_pending else
                    5 if prerequisite or space_pending or battle_pending else interval)
                self._waiting_game.pop(instance_id, None)
                self.snapshots[instance_id] = snapshot
                if snapshot is not None:commander_catalog(self.store,instance_id,snapshot)
                self.reasons[instance_id] = ('Исследования · строительная предпосылка, повтор через5с' if prerequisite
                    else TASKS[task_id][0] + " · проверка завершена")
                if task_id in ('barbarians','barbarian_chain') and snapshot is not None:
                    values=snapshot.values
                    if values.get('barbarian_no_cluster') is True:
                        self.reasons[instance_id]=TASKS[task_id][0]+' · '+values.get('barbarian_chain_reason','нет подходящего скопления')
                    elif battle_pending or values.get('barbarian_session_completed') is True:
                        phase=values.get('barbarian_phase')
                        status=('возврат армии' if phase in ('returning','recall_intent') else 'армия в поле') if battle_pending else 'заход завершён'
                        text=TASKS[task_id][0]+' · '+status
                        paid=values.get('barbarian_paid_attacks');free=values.get('barbarian_chain_free_defeated')
                        if type(paid) is int and paid>=0:text+=f' · платных атак: {paid}'
                        if task_id=='barbarian_chain' and type(free) is int and free>=0:text+=f' · бесплатных побед: {free}'
                        self.reasons[instance_id]=text
                self.log(instance_id, self.reasons[instance_id])
        self.updated.emit()

    def tick(self):
        if self._closing:
            return
        if (self.live_tunnel is not None and self.live_tunnel.process is not None
                and self.live_tunnel.process.poll() is not None):
            self.stop_live()
            message = "Соединение Live завершилось; включите Live повторно"
            self.live_status.emit(message)
            self.log(None, message, "error")
        instant = time.monotonic()
        for key in list(self._launching):
            if instant >= self._launch_deadlines.get(key, 0):
                self._launching.discard(key)
                self.reasons[key] = "Эмулятор не подтвердил запуск за 120 секунд"
                self.log(key, self.reasons[key], "error")
        for key in list(self._pending_close):
            self._close_pending(key)
        for key in list(self._pending_prepare):
            self._prepare_pending(key)
        for key in list(self._pending_retire):
            if not self.dispatcher.busy(key):
                reader = self.readers.get(key)
                if reader:
                    def retire(cancelled, reader=reader, key=key):
                        reader.close()
                        return "retired", key
                    if self._submit(key, retire):
                        self._pending_retire.discard(key)
                else:
                    self._pending_retire.discard(key)
        self._rotate(instant)
        for instance in self.instances:
            profile = self.store.profile(instance.id)
            snapshot = self.snapshots.get(instance.id)
            progress = self._active_observations.get(instance.id)
            observed = progress[0] if progress else None
            if (observed is not None and snapshot is not None
                    and (observed.pid,observed.player_id) == (snapshot.pid,snapshot.player_id)
                    and observed.captured_at > snapshot.captured_at):
                snapshot = self.snapshots[instance.id] = observed
            # A worker can publish an observation after this tick's initial timestamp.
            ready = bool(snapshot and snapshot.fresh(time.monotonic()))
            decision = decide(instance, profile, datetime.now(), ready)
            if (decision.state in (RunState.RUNNING, RunState.WAIT_ADAPTER)
                    and (instance.cpus < MIN_CPUS or instance.memory_mb < MIN_MEMORY_MB)):
                decision = Decision(RunState.ERROR, reason="Нужны минимум 2 CPU-ядра и 2 ГБ ОЗУ")
            if instance.id in self._closing_instances:
                decision = Decision(RunState.WAIT_EMULATOR, reason="Закрытие экземпляра")
            if decision.state == RunState.RUNNING and any(task not in VERIFIED_WORKFLOWS for task in decision.tasks):
                decision = Decision(RunState.ERROR, reason="Нет проверенного игрового сценария")
            if decision.state in (RunState.RUNNING, RunState.WAIT_ADAPTER) and instance.id in self._task_errors:
                decision = Decision(RunState.ERROR, reason=self._task_errors[instance.id])
            if decision.state == RunState.RUNNING and instance.id in self._waiting_game:
                decision = Decision(RunState.WAIT_GAME, tasks=decision.tasks, reason=self._waiting_game[instance.id], slot_id=decision.slot_id)
            active = self._active_tasks.get(instance.id)
            if active and decision.state == RunState.WAIT_ADAPTER:
                # A bounded worker pool can hold a task longer than the GUI snapshot's
                # lifetime. The worker obtains and validates fresh state before input.
                # Expiring telemetry must not repeatedly cancel work still in the queue.
                policy = decide(instance, profile, datetime.now(), True)
                if policy.state == RunState.RUNNING:
                    decision = Decision(RunState.WAIT_GAME,tasks=policy.tasks,
                        reason="Ожидание свежих данных задачи",slot_id=policy.slot_id)
            if active and (decision.state not in (RunState.RUNNING, RunState.WAIT_GAME) or active[0] not in decision.tasks or active[1] != decision.slot_id):
                self.dispatcher.cancel(instance.id)
            self.decisions[instance.id] = decision
            if (decision.state == RunState.WAIT_ADAPTER and self._auto_refresh
                    and self._retry_at.get(instance.id,0) <= instant and not self.dispatcher.busy(instance.id)):
                self.probe(instance.id)
            if decision.state in (RunState.RUNNING, RunState.WAIT_GAME) and not self.dispatcher.busy(instance.id):
                # Long city routes may outlast the intervals of earlier tasks.
                # Serve the oldest deadline first; profile order breaks equal deadlines.
                task = min((task for task in decision.tasks if self._due.get((instance.id,task),0) <= instant),
                           key=lambda task:self._due.get((instance.id,task),0), default=None)
                if task:
                    self._execute(instance, task, profile, decision.slot_id)
        if instant - self._last_memory_poll >= 2:
            self._last_memory_poll = instant
            for key in list(self.readers):
                try:
                    instance = self.instance(key)
                except StopIteration:
                    continue
                if instance.power == Power.ONLINE and not self.dispatcher.busy(key) and self._retry_at.get(key,0) <= instant:
                    self.probe(key)
        if self._auto_refresh and instant - self._last_discovery >= 10:
            self.refresh()
        self.updated.emit()

    def _execute(self, instance, task_id, profile, slot_id=None):
        snapshot = self.snapshots.get(instance.id)
        reader = self.readers.get(instance.id)
        if snapshot is None or reader is None:
            return
        settings = profile.tasks.get(task_id,{})
        options_type = {"training":TrainingOptions,"alliance_donate":DonationOptions,"materials":MaterialOptions,
                          "gather_resources":GatherOptions,"buildings":BuildingOptions,
                          "supply_boxes":SupplyBoxOptions,"vip_shop":VipShopOptions,"lucerne":LucerneOptions,
                          'tutorial':TutorialOptions,'research':ResearchOptions,
                          'barbarians':BarbarianOptions,'barbarian_chain':BarbarianOptions}.get(task_id)
        options = options_type.from_settings(settings) if options_type else None
        progress = [None]

        def allowed():
            current = self.instance(instance.id)
            current_profile = self.store.profile(instance.id)
            decision = decide(current, current_profile, datetime.now(), True)
            return (current.cpus >= MIN_CPUS and current.memory_mb >= MIN_MEMORY_MB
                    and instance.id not in self._closing_instances and decision.state == RunState.RUNNING
                    and task_id in decision.tasks and decision.slot_id == slot_id
                    and (options is None or options_type.from_settings(current_profile.tasks.get(task_id,{})) == options))

        def work(cancelled):
            try:
                try:
                    workflow = workflow_for(task_id,settings)
                    if task_id in ('barbarians','barbarian_chain'):
                        workflow.steps[0].action.store=self.store
                except ValueError as error:
                    raise NotReady(str(error)) from error
                def check_input():
                    if cancelled.is_set() or not allowed():
                        raise Cancelled("Выполнение отменено перед вводом")
                class Input:
                    def tap(self,x,y,**kwargs):
                        reader.adb.tap(x,y,before_input=check_input,**kwargs)
                    def tap_resolved(self,resolve,**kwargs):
                        reader.adb.tap_resolved(resolve,before_input=check_input,**kwargs)
                    def drag(self,x,y,end_x,end_y,**kwargs):
                        reader.adb.drag(x,y,end_x,end_y,before_input=check_input,**kwargs)
                    def back(self):
                        reader.adb.back(before_input=check_input)
                observe = (lambda: reader.snapshot(workflow.extra_paths)) if workflow.extra_paths else reader.snapshot
                if workflow.requires_city and snapshot.values.get("views",{}).get("BattlePassMain") is True:
                    from .recovery import DISMISS_BATTLE_PASS
                    Engine(Input(),lambda:reader.snapshot(DISMISS_BATTLE_PASS.extra_paths),
                        resolution=(instance.width,instance.height),allowed=allowed,
                        on_observed=lambda state:progress.__setitem__(0,state)).execute(
                            DISMISS_BATTLE_PASS,cancelled,instance_id=instance.id,player_id=snapshot.player_id,pid=snapshot.pid)
                context = progress[0] or snapshot
                if workflow.requires_city and (context.values.get("in_city") is False
                                              or context.values.get("city_enabled") is False):
                    Engine(Input(),lambda:reader.snapshot(RETURN_TO_CITY.extra_paths),
                        resolution=(instance.width,instance.height),allowed=allowed,
                        on_observed=lambda state:progress.__setitem__(0,state)).execute(
                            RETURN_TO_CITY,cancelled,instance_id=instance.id,player_id=snapshot.player_id,pid=snapshot.pid)
                state = Engine(Input(), observe, resolution=(instance.width,instance.height), allowed=allowed,
                               on_observed=lambda state:progress.__setitem__(0,state)).execute(
                    workflow, cancelled, instance_id=instance.id, player_id=snapshot.player_id,pid=snapshot.pid)
                return "task", instance.id, task_id, state, None
            except NotReady as error:
                return "task", instance.id, task_id, None, ("waiting", str(error))
            except Cancelled:
                return "cancelled",
            except (MemoryError, CommandError) as error:
                reader.close()
                return "reconnect", instance.id, str(error), snapshot.player_id
            except Exception as error:
                if cancelled.is_set():
                    return "cancelled",
                return "task", instance.id, task_id, None, str(error)

        if self._submit(instance.id,work):
            self._active_tasks[instance.id] = (task_id, slot_id)
            self._active_observations[instance.id] = progress

    def enable_rotation(self):
        settings = self.store.preference("rotation", {})
        members = settings.get("members", [])
        available = {instance.id: instance for instance in self.instances}
        if any(key not in available for key in members):
            raise ValueError("В пуле есть недоступные экземпляры; обновите список")
        if any(available[key].cpus < MIN_CPUS or available[key].memory_mb < MIN_MEMORY_MB for key in members):
            raise ValueError("Для ротации каждому экземпляру нужны минимум 2 CPU-ядра и 2 ГБ ОЗУ")
        rotation = Rotation(members, parallel=settings.get("parallel", 1), duration=settings.get("duration", 3600))
        now = time.monotonic()
        for key in members:
            profile = self.store.profile(key)
            if profile.manual_pause:
                rotation.pause(key)
            else:
                if not profile.schedule_enabled:
                    def change(current):
                        if not current.schedule_enabled and not current.manual_pause:
                            current.manual_run = True
                    self.store.update_profile(key, change)
                if available[key].power == Power.ONLINE:
                    rotation.current[key] = now
                    rotation.seen_online.add(key)
        rotation.enabled = True
        self.rotation = rotation
        self.log(None, "Ротация включена")
        self.tick()

    def disable_rotation(self):
        if self.rotation:
            self.rotation.enabled = False
        self.log(None, "Ротация остановлена")
        self.updated.emit()

    def resume_rotation_member(self, key):
        if self.rotation:
            self.rotation.resume(key)
        self.tick()

    def _rotate(self, instant):
        if not self.rotation or not self.rotation.enabled:
            return
        online = {i.id for i in self.instances if i.power != Power.OFF} | self._launching
        plan = self.rotation.tick(instant, online, int(self.store.preference("device_limit", 3)))
        for key in plan.close:
            self.dispatcher.cancel(key)
            self._pending_close.add(key)
            self._closing_instances.add(key)
            self._close_pending(key)
        for key in plan.launch:
            if not self.launch(key):
                self.rotation.pause(key)

    def shutdown(self):
        self._closing = True
        self.timer.stop()
        self.dispatcher.shutdown(wait=True)
        # Deliver results already emitted by workers before destroying the window.
        # A newly attached reader may exist only in one of these queued results.
        QCoreApplication.sendPostedEvents(self, QEvent.Type.MetaCall)
        self.stop_live()
        for reader in self.readers.values():
            reader.close()
        self.readers.clear()
