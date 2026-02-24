from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.settings_store import (
    ANALYZER_DISPLAY_COLOR_BAD_DEFAULT,
    ANALYZER_DISPLAY_COLOR_GOOD_DEFAULT,
    ANALYZER_DISPLAY_COLOR_WARN_DEFAULT,
    ANALYZER_DISPLAY_SHOW_BAD_BAND_DEFAULT,
    ANALYZER_DISPLAY_SHOW_BAD_LINE_DEFAULT,
    ANALYZER_DISPLAY_SHOW_GOOD_BAND_DEFAULT,
    ANALYZER_DISPLAY_SHOW_WARN_BAND_DEFAULT,
    ANALYZER_DISPLAY_SHOW_WARN_LINE_DEFAULT,
    SettingsStore,
    UserSettings,
)


class SettingsStoreAnalyzerDisplayDefaultsTests(unittest.TestCase):
    def test_user_settings_defaults_include_metric_band_component_visibility_and_colors(self) -> None:
        settings = UserSettings.from_dict({})
        self.assertEqual(bool(settings.analyzer_display_show_good_band), bool(ANALYZER_DISPLAY_SHOW_GOOD_BAND_DEFAULT))
        self.assertEqual(bool(settings.analyzer_display_show_warn_band), bool(ANALYZER_DISPLAY_SHOW_WARN_BAND_DEFAULT))
        self.assertEqual(bool(settings.analyzer_display_show_bad_band), bool(ANALYZER_DISPLAY_SHOW_BAD_BAND_DEFAULT))
        self.assertEqual(bool(settings.analyzer_display_show_warn_line), bool(ANALYZER_DISPLAY_SHOW_WARN_LINE_DEFAULT))
        self.assertEqual(bool(settings.analyzer_display_show_bad_line), bool(ANALYZER_DISPLAY_SHOW_BAD_LINE_DEFAULT))
        self.assertEqual(str(settings.analyzer_display_color_good), str(ANALYZER_DISPLAY_COLOR_GOOD_DEFAULT))
        self.assertEqual(str(settings.analyzer_display_color_warn), str(ANALYZER_DISPLAY_COLOR_WARN_DEFAULT))
        self.assertEqual(str(settings.analyzer_display_color_bad), str(ANALYZER_DISPLAY_COLOR_BAD_DEFAULT))

    def test_settings_store_persists_metric_band_display_controls(self) -> None:
        with tempfile.TemporaryDirectory(prefix="wut_settings_display_controls_") as tmp:
            path = Path(tmp) / "settings.json"
            store = SettingsStore(path)
            store.save(
                UserSettings(
                    library_root=str(Path(tmp)),
                    analyzer_display_show_good_band=False,
                    analyzer_display_show_warn_band=True,
                    analyzer_display_show_bad_band=False,
                    analyzer_display_show_warn_line=True,
                    analyzer_display_show_bad_line=True,
                    analyzer_display_color_good="#5E7082",
                    analyzer_display_color_warn="#6F8294",
                    analyzer_display_color_bad="#7F8D9B",
                )
            )
            loaded = store.load()
            self.assertFalse(bool(loaded.analyzer_display_show_good_band))
            self.assertTrue(bool(loaded.analyzer_display_show_warn_band))
            self.assertFalse(bool(loaded.analyzer_display_show_bad_band))
            self.assertTrue(bool(loaded.analyzer_display_show_warn_line))
            self.assertTrue(bool(loaded.analyzer_display_show_bad_line))
            self.assertEqual(str(loaded.analyzer_display_color_good), "#5E7082")
            self.assertEqual(str(loaded.analyzer_display_color_warn), "#6F8294")
            self.assertEqual(str(loaded.analyzer_display_color_bad), "#7F8D9B")


if __name__ == "__main__":
    unittest.main()
