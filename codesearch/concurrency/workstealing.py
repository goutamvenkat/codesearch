from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Callable, Generic, Iterable, Optional, TypeVar


InT = TypeVar("InT")
EventT = TypeVar("EventT")


@dataclass(frozen=True)
class WorkResult(Generic[InT, EventT]):
    new_items: list[InT]
    events: list[EventT]


class WorkStealingPool(Generic[InT, EventT]):
    def __init__(
        self,
        *,
        workers: int,
        process_fn: Callable[[InT], WorkResult[InT, EventT]],
        on_event: Optional[Callable[[EventT], None]] = None,
        on_error: Optional[Callable[[BaseException], None]] = None,
        queue_maxsize: int = 0,
    ) -> None:
        self.workers = max(1, int(workers))
        self.process_fn = process_fn
        self.on_event = on_event
        self.on_error = on_error
        self._q: "queue.Queue[InT]" = queue.Queue(maxsize=queue_maxsize)
        self._stop = threading.Event()
        self._in_flight = 0
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._threads: list[threading.Thread] = []

    def run(self, seed_items: Iterable[InT]) -> None:
        for item in seed_items:
            self._q.put(item)

        self._threads = [
            threading.Thread(target=self._worker_loop, name=f"worksteal-{i}", daemon=True)
            for i in range(self.workers)
        ]
        for t in self._threads:
            t.start()

        with self._idle:
            while not (self._q.empty() and self._in_flight == 0):
                self._idle.wait(timeout=0.2)

        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)

    def _worker_loop(self) -> None:
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.1)
            except queue.Empty:
                with self._idle:
                    if self._q.empty() and self._in_flight == 0:
                        self._idle.notify_all()
                continue

            with self._idle:
                self._in_flight += 1

            try:
                result = self.process_fn(item)
                for new_item in result.new_items:
                    self._q.put(new_item)
                if self.on_event is not None:
                    for ev in result.events:
                        self.on_event(ev)
            except BaseException as e:
                if self.on_error is not None:
                    self.on_error(e)
            finally:
                with self._idle:
                    self._in_flight -= 1
                    if self._q.empty() and self._in_flight == 0:
                        self._idle.notify_all()

