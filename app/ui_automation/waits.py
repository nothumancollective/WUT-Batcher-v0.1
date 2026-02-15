"""State-based wait helpers with incremental backoff for UI automation."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional, Tuple


Predicate = Callable[[], Tuple[bool, Any]]
PollCallback = Callable[[int, float], None]


def wait_until(
    *,
    predicate: Predicate,
    timeout_s: float,
    initial_interval_s: float = 0.1,
    max_interval_s: float = 1.0,
    backoff_factor: float = 2.0,
    on_poll: Optional[PollCallback] = None,
) -> Any:
    deadline = time.perf_counter() + max(0.1, float(timeout_s))
    interval = max(0.01, float(initial_interval_s))
    max_interval = max(interval, float(max_interval_s))
    attempts = 0
    last_value: Any = None

    while True:
        attempts += 1
        ok, value = predicate()
        last_value = value
        if ok:
            return value

        now = time.perf_counter()
        if now >= deadline:
            raise TimeoutError(f"wait_until timeout after {timeout_s}s (attempts={attempts})")

        if on_poll is not None:
            remaining = max(0.0, deadline - now)
            on_poll(attempts, remaining)
        time.sleep(interval)
        interval = min(max_interval, interval * max(1.0, backoff_factor))

    return last_value
