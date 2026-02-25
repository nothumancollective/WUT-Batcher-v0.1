"""In-memory LRU cache for Analyzer polar plot payloads."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import threading
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class AnalyzerCachePolicy:
    mode: str
    size_limit_mb: int
    keep_last_n: int

    @property
    def size_limit_bytes(self) -> int:
        return max(int(self.size_limit_mb), 0) * 1024 * 1024


_MODE_DEFAULTS: Dict[str, Tuple[int, int]] = {
    "low": (0, 1),
    "balanced": (240, 5),
    "high": (720, 15),
    "extreme": (1440, 30),
}


def resolve_cache_policy(
    *,
    mode: str,
    custom_limit_mb: int,
    custom_keep_last_n: int,
) -> AnalyzerCachePolicy:
    token = str(mode or "balanced").strip().lower()
    if token == "custom":
        limit_mb = max(min(int(custom_limit_mb), 10 * 1024), 0)
        keep_last_n = max(min(int(custom_keep_last_n), 200), 1)
        return AnalyzerCachePolicy(mode="custom", size_limit_mb=limit_mb, keep_last_n=keep_last_n)
    if token not in _MODE_DEFAULTS:
        token = "balanced"
    limit_mb, keep_last_n = _MODE_DEFAULTS[token]
    return AnalyzerCachePolicy(mode=token, size_limit_mb=limit_mb, keep_last_n=keep_last_n)


def estimate_payload_bytes(payload: Dict[str, Any]) -> int:
    freqs = list(payload.get("freqs_hz", []) or [])
    angles = list(payload.get("angles_deg", []) or [])
    matrix = list(payload.get("matrix_db", []) or [])
    display_freqs = list(payload.get("display_freqs_hz", []) or [])
    display_matrix = list(payload.get("display_matrix_db", []) or [])
    beamwidth = list(payload.get("beamwidth_curve", []) or [])
    count_matrix = sum(len(list(row or [])) for row in matrix)
    count_display = sum(len(list(row or [])) for row in display_matrix)
    # 8 bytes per float + light overhead multiplier.
    base_count = len(freqs) + len(angles) + len(display_freqs) + (2 * len(beamwidth)) + count_matrix + count_display
    return int(max(base_count, 1) * 8 * 1.12)


class AnalyzerPlotCache:
    """Thread-safe LRU cache with soft byte limit and keep-last policy."""

    def __init__(self, policy: AnalyzerCachePolicy) -> None:
        self._lock = threading.RLock()
        self._policy = policy
        self._items: "OrderedDict[str, Tuple[int, Dict[str, Any]]]" = OrderedDict()
        self._size_bytes = 0

    @property
    def policy(self) -> AnalyzerCachePolicy:
        with self._lock:
            return self._policy

    @property
    def size_bytes(self) -> int:
        with self._lock:
            return int(self._size_bytes)

    def configure(self, policy: AnalyzerCachePolicy) -> None:
        with self._lock:
            self._policy = policy
            self._evict_locked()

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._size_bytes = 0

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            item = self._items.pop(str(key), None)
            if item is None:
                return None
            self._items[str(key)] = item
            return dict(item[1])

    def put(self, key: str, payload: Dict[str, Any]) -> None:
        k = str(key)
        with self._lock:
            previous = self._items.pop(k, None)
            if previous is not None:
                self._size_bytes -= int(previous[0])
            size = max(int(estimate_payload_bytes(payload)), 1)
            self._items[k] = (size, dict(payload))
            self._size_bytes += size
            self._evict_locked()

    def _evict_locked(self) -> None:
        keep_last = max(int(self._policy.keep_last_n), 1)
        size_limit = int(self._policy.size_limit_bytes)

        while len(self._items) > keep_last:
            _, (size, _) = self._items.popitem(last=False)
            self._size_bytes -= int(size)

        if size_limit <= 0:
            while len(self._items) > 1:
                _, (size, _) = self._items.popitem(last=False)
                self._size_bytes -= int(size)
            return

        while self._size_bytes > size_limit and len(self._items) > 1:
            _, (size, _) = self._items.popitem(last=False)
            self._size_bytes -= int(size)
