"""Shared Polar heatmap style primitives for Analyzer."""

from __future__ import annotations

from typing import List, Sequence, Tuple


_VACS_COLOR_STOPS: Sequence[Tuple[float, Tuple[int, int, int]]] = (
    (0.00, (14, 30, 82)),    # cool / dark blue
    (0.20, (31, 87, 166)),   # blue
    (0.40, (43, 158, 191)),  # cyan-blue
    (0.58, (74, 196, 120)),  # greenish mid
    (0.76, (233, 213, 92)),  # yellow
    (0.90, (246, 144, 67)),  # orange
    (1.00, (248, 78, 68)),   # warm red
)

COMPARE_OVERLAY_COLORS: Sequence[Tuple[int, int, int]] = (
    (93, 168, 255),   # blue
    (255, 179, 71),   # amber
    (125, 218, 88),   # green
    (255, 107, 107),  # red
    (192, 132, 252),  # violet
)


def _interpolate(a: int, b: int, t: float) -> int:
    return int(round(float(a) + ((float(b) - float(a)) * float(t))))


def get_vacs_like_lut(size: int = 256) -> List[Tuple[int, int, int]]:
    count = max(int(size), 2)
    lut: List[Tuple[int, int, int]] = []
    stops = list(_VACS_COLOR_STOPS)
    for index in range(count):
        u = float(index) / float(count - 1)
        left = stops[0]
        right = stops[-1]
        for stop_idx in range(len(stops) - 1):
            a = stops[stop_idx]
            b = stops[stop_idx + 1]
            if a[0] <= u <= b[0]:
                left = a
                right = b
                break
        if right[0] <= left[0]:
            ratio = 0.0
        else:
            ratio = (u - float(left[0])) / float(right[0] - left[0])
        r = _interpolate(left[1][0], right[1][0], ratio)
        g = _interpolate(left[1][1], right[1][1], ratio)
        b = _interpolate(left[1][2], right[1][2], ratio)
        lut.append((r, g, b))
    return lut


def compare_overlay_color(index: int) -> Tuple[int, int, int]:
    colors = list(COMPARE_OVERLAY_COLORS)
    if not colors:
        return (93, 168, 255)
    safe_index = max(int(index), 0) % len(colors)
    return colors[safe_index]
