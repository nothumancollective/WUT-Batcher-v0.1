from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.ui_automation.watchdog import ModalDialogWatchdog


class ModalDialogWatchdogTests(unittest.TestCase):
    def test_default_rules_cancel_german_save_as_dialog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchdog = ModalDialogWatchdog(process_id=77, output_dir=Path(tmp_dir))

        matches = [
            rule
            for rule in watchdog.whitelist_rules
            if rule.matches(title="Speichern unter", message="")
        ]

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].rule_id, "cancel_project_save_as")
        self.assertEqual(matches[0].action, "cancel")

    def test_default_rules_discard_only_explicit_akabak_save_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchdog = ModalDialogWatchdog(process_id=77, output_dir=Path(tmp_dir))

        save_matches = [
            rule
            for rule in watchdog.whitelist_rules
            if rule.matches(title="Akabak", message="Projekt und Änderungen speichern?")
        ]
        unrelated_matches = [
            rule
            for rule in watchdog.whitelist_rules
            if rule.matches(title="Akabak", message="Unexpected solver failure")
        ]

        self.assertIn("discard_imported_project_changes", [rule.rule_id for rule in save_matches])
        self.assertNotIn("discard_imported_project_changes", [rule.rule_id for rule in unrelated_matches])

    def test_windows_candidate_poll_uses_native_pid_lookup_without_uia_desktop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchdog = ModalDialogWatchdog(process_id=77, output_dir=Path(tmp_dir))
            sentinel = Mock()
            watchdog._candidate_dialogs_native = Mock(return_value=[sentinel])  # type: ignore[method-assign]
            watchdog._import_pywinauto = Mock(  # type: ignore[method-assign]
                side_effect=AssertionError("UIA desktop enumeration must not run on Windows")
            )

            with patch("app.ui_automation.watchdog.os.name", "nt"):
                dialogs = watchdog._candidate_dialogs()

        self.assertEqual(dialogs, [sentinel])
        watchdog._candidate_dialogs_native.assert_called_once()
        watchdog._import_pywinauto.assert_not_called()


if __name__ == "__main__":
    unittest.main()
