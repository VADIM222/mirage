from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import threading
from typing import Callable


@dataclass
class Ticket:
    key: str
    generation: int
    cancelled: threading.Event
    future: Future | None = None


class Dispatcher:
    """At most one job per instance, bounded queue and shared CPU workers."""

    def __init__(self, workers: int = 2, capacity: int = 50):
        if workers < 1 or not 1 <= capacity <= 50:
            raise ValueError("Некорректные лимиты диспетчера")
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mirage")
        self._lock = threading.RLock()
        self._tickets: dict[str, Ticket] = {}
        self._generations: dict[str, int] = {}
        self._closed = False
        self.capacity = capacity

    def submit(self, key: str, function: Callable[[threading.Event], object],
               callback: Callable[[str, int, object, Exception | None], None]) -> bool:
        with self._lock:
            if self._closed or key in self._tickets or len(self._tickets) >= self.capacity:
                return False
            generation = self._generations.get(key, 0)
            ticket = Ticket(key, generation, threading.Event())
            self._tickets[key] = ticket
            future = self._pool.submit(function, ticket.cancelled)
            ticket.future = future

        def complete(done: Future):
            result, error = None, None
            try:
                result = done.result()
            except Exception as exception:
                error = exception
            with self._lock:
                current = self._generations.get(key, 0) == generation and not ticket.cancelled.is_set()
            # Cleanups remain the worker's responsibility when cancellation is requested.
            callback(key, generation, result, error if current else RuntimeError("Результат отменённого задания"))

        future.add_done_callback(complete)
        return True

    def acknowledge(self, key: str, generation: int) -> bool:
        """Release the instance only when its result reaches the owning thread."""
        with self._lock:
            ticket = self._tickets.get(key)
            if ticket is None or ticket.generation != generation:
                return False
            del self._tickets[key]
            return self._generations.get(key, 0) == generation and not ticket.cancelled.is_set()

    def cancel(self, key: str) -> None:
        with self._lock:
            self._generations[key] = self._generations.get(key, 0) + 1
            ticket = self._tickets.get(key)
            if ticket:
                ticket.cancelled.set()
                if ticket.future:
                    ticket.future.cancel()

    def busy(self, key: str) -> bool:
        with self._lock:
            return key in self._tickets

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            for ticket in self._tickets.values():
                ticket.cancelled.set()
        self._pool.shutdown(wait=wait, cancel_futures=True)
