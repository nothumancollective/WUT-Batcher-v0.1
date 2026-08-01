from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.vacs_export_save_all import (
    _discover_save_filename_target,
    _find_save_as_dialog_fast,
    _is_save_as_dialog_candidate,
    _set_save_path,
)


class VacsExportSaveAllDialogTests(unittest.TestCase):
    def test_accepts_german_modern_save_as_without_win32_edit(self) -> None:
        dialog = object()
        with (
            patch(
                "scripts.vacs_export_save_all._sig",
                return_value={"handle": 401, "class_name": "#32770", "title": "Speichern unter"},
            ),
            patch("scripts.vacs_export_save_all._win32_children", return_value=[]),
        ):
            self.assertTrue(_is_save_as_dialog_candidate(dialog))

    def test_accepts_english_modern_save_as_without_win32_edit(self) -> None:
        dialog = object()
        with (
            patch(
                "scripts.vacs_export_save_all._sig",
                return_value={"handle": 402, "class_name": "#32770", "title": "Save As"},
            ),
            patch("scripts.vacs_export_save_all._win32_children", return_value=[]),
        ):
            self.assertTrue(_is_save_as_dialog_candidate(dialog))

    def test_rejects_unrelated_common_dialog_without_filename_edit(self) -> None:
        dialog = object()
        with (
            patch(
                "scripts.vacs_export_save_all._sig",
                return_value={"handle": 403, "class_name": "#32770", "title": "Warning"},
            ),
            patch("scripts.vacs_export_save_all._win32_children", return_value=[]),
        ):
            self.assertFalse(_is_save_as_dialog_candidate(dialog))

    def test_retains_classic_filename_edit_detection(self) -> None:
        dialog = object()
        with (
            patch(
                "scripts.vacs_export_save_all._sig",
                return_value={"handle": 404, "class_name": "#32770", "title": "Custom title"},
            ),
            patch(
                "scripts.vacs_export_save_all._win32_children",
                return_value=[{"ctrl_id": 1148, "class_name": "Edit"}],
            ),
        ):
            self.assertTrue(_is_save_as_dialog_candidate(dialog))

    def test_fast_finder_falls_back_to_uia_for_modern_save_dialog(self) -> None:
        dialog = object()
        main = object()
        with (
            patch("scripts.vacs_export_save_all.time.perf_counter", side_effect=[0.0, 0.0, 1.0]),
            patch("scripts.vacs_export_save_all.time.sleep"),
            patch("scripts.vacs_export_save_all._top_windows_for_pid_fast", return_value=[]),
            patch("scripts.vacs_export_save_all._find_main_fast", return_value=main),
            patch(
                "scripts.vacs_export_save_all._sig",
                return_value={"handle": 501, "class_name": "TForm_DatMain", "title": "VacsViewer"},
            ),
            patch("scripts.vacs_export_save_all._find_save_as_dialog", return_value=dialog) as fallback,
        ):
            result = _find_save_as_dialog_fast(13632, timeout_s=0.5)

        self.assertIs(result, dialog)
        fallback.assert_called_once_with(13632, 501, timeout_s=0.35)

    def test_filename_discovery_retries_transient_missing_edit(self) -> None:
        dialog = object()
        save_row = {"handle": 601, "ctrl_id": 1, "class_name": "Button"}
        edit_row = {"handle": 602, "ctrl_id": 1148, "class_name": "Edit"}
        with (
            patch("scripts.vacs_export_save_all._sig", return_value={"handle": 600}),
            patch(
                "scripts.vacs_export_save_all._win32_children",
                side_effect=[[save_row], [save_row, edit_row]],
            ),
            patch("scripts.vacs_export_save_all.Desktop") as desktop,
            patch("scripts.vacs_export_save_all.time.perf_counter", side_effect=[0.0, 0.0]),
            patch("scripts.vacs_export_save_all.time.sleep"),
        ):
            desktop.return_value.window.return_value.descendants.return_value = []
            result = _discover_save_filename_target(dialog, timeout_s=0.5)

        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["filename_row"], edit_row)

    def test_missing_filename_control_never_clicks_default_save(self) -> None:
        dialog = object()
        with (
            patch(
                "scripts.vacs_export_save_all._discover_save_filename_target",
                return_value={
                    "attempts": 3,
                    "rows": [{"handle": 701, "ctrl_id": 1, "class_name": "Button"}],
                    "filename_row": None,
                    "uia_dialog": None,
                    "uia_edit": None,
                },
            ),
            patch("scripts.vacs_export_save_all._click_handle") as click_handle,
        ):
            result = _set_save_path(dialog, Path("C:/tmp/expected.txt"), quick=True)

        click_handle.assert_not_called()
        self.assertEqual(result["filename_uia"], "missing_edit")
        self.assertEqual(result["save_action"]["method"], "skipped_filename_control_missing")


if __name__ == "__main__":
    unittest.main()
