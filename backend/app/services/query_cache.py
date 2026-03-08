from __future__ import annotations

import copy
import json
import time
from collections import OrderedDict
from threading import RLock
from typing import Any


def _normalize_cache_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalize_cache_value(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_cache_value(v) for v in value]
    return value


class TTLQueryCache:
    def __init__(self, *, ttl_seconds: float = 60.0, max_entries: int = 64):
        self.ttl_seconds = max(0.001, float(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = RLock()

    def _make_key(self, namespace: str, params: dict[str, Any]) -> str:
        payload = {"namespace": namespace, "params": _normalize_cache_value(params)}
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)

    def get(self, namespace: str, params: dict[str, Any]) -> Any | None:
        key = self._make_key(namespace, params)
        now = time.monotonic()
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            expires_at, payload = item
            if expires_at <= now:
                self._store.pop(key, None)
                return None
            self._store.move_to_end(key)
            return copy.deepcopy(payload)

    def set(self, namespace: str, params: dict[str, Any], payload: Any) -> None:
        key = self._make_key(namespace, params)
        expires_at = time.monotonic() + self.ttl_seconds
        with self._lock:
            self._store[key] = (expires_at, copy.deepcopy(payload))
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


jobs_query_cache = TTLQueryCache(ttl_seconds=75.0, max_entries=96)


def invalidate_jobs_query_cache() -> None:
    jobs_query_cache.clear()
