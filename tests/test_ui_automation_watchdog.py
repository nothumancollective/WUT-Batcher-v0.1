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

    def test_directui_save_prompt_is_matched_from_bounded_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchdog = ModalDialogWatchdog(process_id=77, output_dir=Path(tmp_dir))
            window = Mock()
            window.window_text.return_value = "Warning"
            window.element_info.handle = 101
            watchdog._candidate_dialogs = Mock(return_value=[window])  # type: ignore[method-assign]
            watchdog._window_message = Mock(return_value="Warning")  # type: ignore[method-assign]
            watchdog._click_action = Mock(return_value=True)  # type: ignore[method-assign]

            with patch(
                "app.ui_automation.watchdog._bounded_uia_dialog_snapshot",
                return_value={
                    "status": "ok",
                    "children": [
                        {"title": "Save project? To file: input.akp", "control_type": "Text"},
                        {"title": "No", "control_type": "Button"},
                    ],
                },
            ):
                handled = watchdog.handle_once()

        self.assertEqual(handled[0]["rule_id"], "discard_imported_project_changes")
        self.assertEqual(handled[0]["action"], "discard")
        watchdog._click_action.assert_called_once_with(window=window, action="discard")

    def test_directui_vacs_registration_warning_is_matched_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchdog = ModalDialogWatchdog(process_id=77, output_dir=Path(tmp_dir))
            window = Mock()
            window.window_text.return_value = "Error"
            window.element_info.handle = 101
            watchdog._candidate_dialogs = Mock(return_value=[window])  # type: ignore[method-assign]
            watchdog._window_message = Mock(return_value="Error")  # type: ignore[method-assign]
            watchdog._click_action = Mock(return_value=True)  # type: ignore[method-assign]

            with patch(
                "app.ui_automation.watchdog._bounded_uia_dialog_snapshot",
                return_value={
                    "status": "ok",
                    "children": [
                        {
                            "title": (
                                "Cannot locate Vacs.exe or VacsViewer.exe. Vacs seems not to be properly "
                                "registered in order to provide a COM service. Use Vacs /RegServer."
                            ),
                            "control_type": "Text",
                        },
                        {"title": "OK", "control_type": "Button"},
                    ],
                },
            ):
                handled = watchdog.handle_once()

        self.assertEqual(handled[0]["rule_id"], "vacs_com_registration_missing_continue")
        self.assertEqual(handled[0]["action"], "ok")
        watchdog._click_action.assert_called_once_with(window=window, action="ok")

    def test_discard_action_never_falls_back_to_default_enter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            watchdog = ModalDialogWatchdog(process_id=77, output_dir=Path(tmp_dir))
            window = Mock()
            missing = Mock()
            missing.exists.return_value = False
            window.child_window.return_value = missing

            clicked = watchdog._click_action(window=window, action="discard")

        self.assertFalse(clicked)
        window.type_keys.assert_not_called()

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
