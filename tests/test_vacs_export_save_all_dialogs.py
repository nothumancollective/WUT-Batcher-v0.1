from __future__ import annotations

import unittest
from unittest.mock import patch

from scripts.vacs_export_save_all import _is_save_as_dialog_candidate


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


if __name__ == "__main__":
    unittest.main()
