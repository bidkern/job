from __future__ import annotations

import asyncio
import inspect
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any, Callable


class BackgroundRefreshQueue:
    def __init__(self, max_workers: int = 1):
        self.max_workers = max(1, int(max_workers))
        self._executor: ThreadPoolExecutor | None = None
        self._in_flight: set[str] = set()
        self._lock = Lock()

    def start(self) -> None:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="job-refresh")

    def stop(self) -> None:
        with self._lock:
            executor = self._executor
            self._executor = None
            self._in_flight.clear()
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, key: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
        with self._lock:
            if key in self._in_flight:
                return False
            if self._executor is None:
                self._executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="job-refresh")
            self._in_flight.add(key)
            executor = self._executor

        executor.submit(self._run, key, func, args, kwargs)
        return True

    def _run(self, key: str, func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
        try:
            result = func(*args, **kwargs)
            if inspect.iscoroutine(result):
                asyncio.run(result)
        except Exception:
            # Background refresh should not crash the app or the worker thread.
            pass
        finally:
            with self._lock:
                self._in_flight.discard(key)


refresh_queue = BackgroundRefreshQueue(max_workers=1)


def start_refresh_queue() -> None:
    refresh_queue.start()


def stop_refresh_queue() -> None:
    refresh_queue.stop()


def enqueue_refresh(key: str, func: Callable[..., Any], *args: Any, **kwargs: Any) -> bool:
    return refresh_queue.submit(key, func, *args, **kwargs)
