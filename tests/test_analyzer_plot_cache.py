from __future__ import annotations

import unittest

from app.analyzer.cache import AnalyzerPlotCache, resolve_cache_policy


def _payload(multiplier: int) -> dict:
    freqs = [float(200 * (idx + 1)) for idx in range(32)]
    angles = [float(-60 + (idx * 5)) for idx in range(25)]
    matrix = [[float(-0.5 * ((row + col + multiplier) % 40)) for col in range(len(freqs))] for row in range(len(angles))]
    curve = [{"freq_hz": float(freq), "beamwidth_deg": 60.0 + float((idx + multiplier) % 8)} for idx, freq in enumerate(freqs)]
    return {
        "freqs_hz": freqs,
        "angles_deg": angles,
        "matrix_db": matrix,
        "display_freqs_hz": freqs[::2],
        "display_matrix_db": [row[::2] for row in matrix],
        "beamwidth_curve": curve,
    }


class AnalyzerPlotCacheTests(unittest.TestCase):
    def test_policy_modes_and_custom_limits(self) -> None:
        low = resolve_cache_policy(mode="low", custom_limit_mb=9999, custom_keep_last_n=99)
        self.assertEqual(low.mode, "low")
        self.assertEqual(low.size_limit_mb, 0)
        self.assertEqual(low.keep_last_n, 1)

        custom = resolve_cache_policy(mode="custom", custom_limit_mb=12_000, custom_keep_last_n=0)
        self.assertEqual(custom.mode, "custom")
        self.assertEqual(custom.size_limit_mb, 10 * 1024)
        self.assertEqual(custom.keep_last_n, 1)

    def test_lru_eviction_respects_keep_last_n(self) -> None:
        policy = resolve_cache_policy(mode="custom", custom_limit_mb=512, custom_keep_last_n=2)
        cache = AnalyzerPlotCache(policy)
        cache.put("A", _payload(1))
        cache.put("B", _payload(2))
        cache.put("C", _payload(3))
        self.assertIsNone(cache.get("A"))
        self.assertIsNotNone(cache.get("B"))
        self.assertIsNotNone(cache.get("C"))

    def test_low_mode_keeps_only_last_item(self) -> None:
        cache = AnalyzerPlotCache(resolve_cache_policy(mode="low", custom_limit_mb=0, custom_keep_last_n=1))
        cache.put("first", _payload(1))
        cache.put("second", _payload(2))
        self.assertIsNone(cache.get("first"))
        self.assertIsNotNone(cache.get("second"))


if __name__ == "__main__":
    unittest.main()
