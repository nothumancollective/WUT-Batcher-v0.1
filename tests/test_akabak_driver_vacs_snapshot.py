from __future__ import annotations

import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.akabak_driver import AkabakDriver


class AkabakDriverVacsSnapshotTests(unittest.TestCase):
    def test_apply_waits_for_import_report_to_be_complete_and_stable(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        interpreter = object()
        apply_button = Mock()
        apply_button.is_enabled.return_value = True
        driver._find_interpreter_window = lambda **_: interpreter
        driver._find_interpreter_modal = lambda **_: None
        driver._find_first_control = lambda *_args, **_kwargs: apply_button
        driver._read_interpreter_report_text = lambda _window: (
            "Importing whole ABEC project\nLoading Data File: input.msh\n"
            "Opening Observation script: observation.txt"
        )
        driver._import_report_candidate = ""
        driver._import_report_stable_since = 0.0

        with patch("app.akabak_driver.time.monotonic", side_effect=[10.0, 11.0]):
            first_ready, first = driver._import_apply_ready_state(main_window=object())
            second_ready, second = driver._import_apply_ready_state(main_window=object())

        self.assertFalse(first_ready)
        self.assertEqual(first["status"], "waiting_import_report_stable")
        self.assertTrue(second_ready)
        self.assertEqual(second["status"], "apply_ready")
        self.assertGreaterEqual(second["report_stable_for_s"], 0.75)

    def test_apply_wait_reports_akabak_exit_instead_of_successful_auto_close(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        main_window = SimpleNamespace(_wut_native_handle=101)
        driver.session = SimpleNamespace(process_id=77)
        driver._find_interpreter_window = Mock(return_value=None)
        driver._list_akabak_process_ids = Mock(return_value=[])
        user32 = Mock()
        user32.IsWindow.return_value = 0
        driver._user32 = lambda: user32

        ready, state = driver._import_apply_ready_state(main_window=main_window)

        self.assertTrue(ready)
        self.assertEqual(state["status"], "akabak_exited_before_apply")
        self.assertFalse(state["main_present"])
        self.assertFalse(state["process_present"])

    def test_apply_wait_accepts_interpreter_auto_close_only_while_main_process_lives(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        main_window = SimpleNamespace(_wut_native_handle=101)
        driver.session = SimpleNamespace(process_id=77)
        driver._find_interpreter_window = Mock(return_value=None)
        driver._list_akabak_process_ids = Mock(return_value=[77])
        user32 = Mock()
        user32.IsWindow.return_value = 1
        driver._user32 = lambda: user32

        ready, state = driver._import_apply_ready_state(main_window=main_window)

        self.assertTrue(ready)
        self.assertEqual(state["status"], "interpreter_closed_before_apply")

    def test_interpreter_button_container_is_not_treated_as_modal(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        candidate_classes = ["TRzDialogButtons"]
        driver._child_windows = lambda _window, class_name_regex: [
            item for item in candidate_classes if re.search(class_name_regex, item, re.IGNORECASE)
        ]

        modal = driver._find_interpreter_modal(interpreter_window=object())

        self.assertIsNone(modal)

    def test_top_level_window_lookup_wraps_native_handles_without_uia_enumeration(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.session = SimpleNamespace(process_id=77)
        driver._native_process_window_rows = lambda **_: [
            {"native_handle": 101, "title": "AKABAK", "class_name": "TForm_Main"},
            {"native_handle": 202, "title": "Script Interpreter", "class_name": "TForm_ScriptInterpreter"},
        ]
        desktop = Mock()
        desktop.window.side_effect = lambda *, handle: f"window-{handle}"

        with patch("pywinauto.Desktop", return_value=desktop):
            windows = driver._process_top_level_windows()

        self.assertEqual(windows, ["window-101", "window-202"])
        desktop.windows.assert_not_called()

    def test_child_window_lookup_filters_native_rows_without_children_traversal(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.session = SimpleNamespace(process_id=77)
        parent = SimpleNamespace(element_info=SimpleNamespace(handle=101))
        driver._native_process_window_rows = lambda **_: [
            {"native_handle": 101, "title": "AKABAK", "class_name": "TForm_Main"},
            {"native_handle": 202, "title": "Script Interpreter", "class_name": "TForm_ScriptInterpreter"},
            {"native_handle": 303, "title": "Open", "class_name": "#32770"},
        ]
        driver._uia_windows_from_native_rows = lambda rows: [row["native_handle"] for row in rows]

        matches = driver._child_windows(
            parent,
            class_name_regex=r"TForm_ScriptInterpreter",
            title_regex=r"Script Interpreter",
        )

        self.assertEqual(matches, [202])

    def test_child_window_lookup_does_not_treat_dialog_button_panel_as_modal(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.session = SimpleNamespace(process_id=77)
        parent = SimpleNamespace(element_info=SimpleNamespace(handle=101))
        driver._native_process_window_rows = lambda **_: [
            {"native_handle": 202, "title": "", "class_name": "TRzDialogButtons"},
            {"native_handle": 303, "title": "Warning", "class_name": "#32770"},
        ]
        driver._uia_windows_from_native_rows = lambda rows: [row["native_handle"] for row in rows]

        with patch("app.akabak_driver.os.name", "nt"):
            matches = driver._child_windows(parent, class_name_regex=r"(#32770|Dialog)")

        self.assertEqual(matches, [303])

    def test_cached_window_handle_and_title_do_not_resolve_element_info(self) -> None:
        class HandleOnlySpecification:
            def __init__(self) -> None:
                self.criteria = [{"handle": 404, "backend": "uia"}]
                self._wut_native_title = "AKABAK"

            @property
            def element_info(self):
                raise AssertionError("COM element resolution must not run for a known HWND")

        driver = AkabakDriver.__new__(AkabakDriver)
        window = HandleOnlySpecification()

        self.assertEqual(driver._window_handle(window), 404)
        self.assertEqual(driver._window_title(window), "AKABAK")

    def test_find_first_control_uses_native_descendants_for_known_hwnd(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        root = SimpleNamespace(element_info=SimpleNamespace(handle=101))
        start = SimpleNamespace(
            element_info=SimpleNamespace(
                handle=202,
                name="Start Importing",
                class_name="TRzBitBtn",
                control_type="Button",
                automation_id="7",
            )
        )
        driver._native_descendant_controls = lambda _handle: [start]

        found = driver._find_first_control(
            root,
            class_name_regex=r"TRzBitBtn",
            title_regex=r"start\s+importing",
        )

        self.assertIs(found, start)

    def test_startup_popup_is_closed_by_native_handle_without_uia_wrapper(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.session = SimpleNamespace(process_id=77)
        main_window = SimpleNamespace(_wut_native_handle=101)
        rows = [
            {
                "native_handle": 202,
                "title": "Examples",
                "class_name": "TForm_ExampleFiles",
                "is_visible": True,
            }
        ]
        user32 = Mock()
        user32.SendMessageW.side_effect = lambda *_: rows.clear()
        driver._user32 = lambda: user32
        driver._native_process_window_rows = lambda **_: list(rows)
        driver._child_windows = lambda *_args, **_kwargs: self.fail("UIA wrapper lookup must not run")
        driver._log = Mock()

        with patch("app.akabak_driver.os.name", "nt"):
            driver._dismiss_startup_windows(main_window=main_window, step="open_project")

        user32.SendMessageW.assert_called_once()
        self.assertEqual(rows, [])

    def test_interpreter_button_uses_native_child_handle_without_descendants(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.session = SimpleNamespace(process_id=77)
        interpreter = SimpleNamespace(_wut_native_handle=101)
        driver._native_process_window_rows = lambda **_: [
            {"native_handle": 202, "title": "Open ABEC Project", "class_name": "TRzBitBtn"},
        ]
        driver._post_native_mouse_click = Mock(return_value=True)
        driver._send_bm_click = Mock(return_value=True)
        driver._send_wm_command_click = Mock(return_value=True)
        driver._find_first_control = lambda *_args, **_kwargs: self.fail("UIA descendants must not run")

        with patch("app.akabak_driver.os.name", "nt"):
            result = driver._invoke_interpreter_button(
                interpreter_window=interpreter,
                title_regex=r"open\s+abec\s+project",
                step="open_project",
                action_name="open_abec_project",
            )

        self.assertEqual(result["handle"], 202)
        self.assertEqual(result["invoke_method"], "native_window_mouse_click")
        driver._post_native_mouse_click.assert_called_once_with(202)
        driver._send_bm_click.assert_not_called()
        driver._send_wm_command_click.assert_not_called()

    def test_interpreter_button_retry_prefers_bounded_bm_click(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.session = SimpleNamespace(process_id=77)
        interpreter = SimpleNamespace(_wut_native_handle=101)
        driver._native_process_window_rows = lambda **_: [
            {"native_handle": 202, "title": "Start Importing", "class_name": "TRzBitBtn"},
        ]
        driver._send_bm_click = Mock(return_value=True)
        driver._post_native_mouse_click = Mock(return_value=True)
        driver._send_wm_command_click = Mock(return_value=True)

        with patch("app.akabak_driver.os.name", "nt"):
            result = driver._invoke_interpreter_button(
                interpreter_window=interpreter,
                title_regex=r"start\s+importing",
                step="import_if_needed",
                action_name="start_importing_retry",
                prefer_bm_click=True,
            )

        self.assertEqual(result["invoke_method"], "native_bm_click")
        driver._send_bm_click.assert_called_once_with(202)
        driver._post_native_mouse_click.assert_not_called()

    def test_open_dialog_is_resolved_from_native_hwnd_without_desktop_enumeration(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.session = SimpleNamespace(process_id=77)
        main_window = SimpleNamespace(_wut_native_handle=101)
        interpreter = SimpleNamespace(_wut_native_handle=202)
        driver._find_interpreter_window = lambda **_: interpreter
        driver._native_process_window_rows = lambda **_: [
            {"native_handle": 303, "title": "Open", "class_name": "#32770"},
        ]
        user32 = Mock()
        user32.GetDlgCtrlID.return_value = 0
        driver._user32 = lambda: user32
        driver._dialog_has_filename_control = Mock(return_value=True)

        with patch("app.akabak_driver.os.name", "nt"):
            dialog = driver._find_open_file_dialog(main_window=main_window)

        self.assertIsNotNone(dialog)
        self.assertEqual(driver._window_handle(dialog), 303)
        driver._dialog_has_filename_control.assert_called_once()

    def test_dialog_filename_control_uses_nested_edit_below_control_1148(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        user32 = Mock()
        user32.GetDlgItem.return_value = 202
        user32.GetDlgCtrlID.return_value = 1001
        user32.GetWindowTextW.side_effect = lambda _hwnd, buffer, _size: setattr(buffer, "value", "horn.abec")
        user32.EnumChildWindows.side_effect = lambda _parent, callback, _lparam: callback(303, 0)
        driver._user32 = lambda: user32
        driver._native_window_class = lambda hwnd: "ComboBoxEx32" if hwnd == 202 else "Edit"
        driver._native_window_text = lambda _hwnd: "horn.abec"

        edit_handle = driver._dialog_filename_edit_handle(101)

        self.assertEqual(edit_handle, 303)
        dialog = SimpleNamespace(_wut_native_handle=101)
        edit, _button = driver._find_open_dialog_controls(dialog)
        self.assertIsNotNone(edit)
        self.assertEqual(driver._window_handle(edit), 303)

    def test_close_uses_known_native_main_handle_without_resolving_uia_wrapper(self) -> None:
        class HandleOnlyWindow:
            def __init__(self) -> None:
                self._wut_native_handle = 404

            def close(self) -> None:
                raise AssertionError("known HWND must not resolve or close a UIA wrapper")

        driver = AkabakDriver.__new__(AkabakDriver)
        driver.state = "ready"
        driver.session = SimpleNamespace(
            find_window=Mock(return_value=HandleOnlyWindow()),
            close=Mock(),
        )
        user32 = Mock()
        user32.SendMessageTimeoutW.return_value = 1
        driver._user32 = lambda: user32
        driver._log = Mock()

        with patch("app.akabak_driver.os.name", "nt"):
            result = driver.close()

        self.assertTrue(result.ok)
        self.assertEqual(result.status, "closed")
        user32.SendMessageTimeoutW.assert_called_once()
        driver.session.close.assert_called_once()

    def test_confirm_without_detected_modal_does_not_send_blind_enter_on_windows(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        main_window = SimpleNamespace(_wut_native_handle=101)
        interpreter = SimpleNamespace(_wut_native_handle=202)
        driver._run_watchdog_modal_sweep = Mock(return_value={"handled": 0, "status": "ok"})
        driver._find_interpreter_window = Mock(return_value=interpreter)
        driver._find_interpreter_modal = Mock(return_value=None)
        driver._send_key_enter = Mock()

        with patch("app.akabak_driver.os.name", "nt"):
            result = driver._confirm_after_interpreter_action(
                main_window=main_window,
                step="import_if_needed",
                phase="confirm_after_start",
            )

        self.assertEqual(result["status"], "no_confirm_needed")
        driver._send_key_enter.assert_not_called()

    def test_cross_process_text_readback_uses_wm_gettext(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        user32 = Mock()

        def send_message(_hwnd, _message, _limit, buffer, _flags, _timeout, _result) -> int:
            buffer.value = "C:\\horns\\Project.abec"
            return 1

        user32.SendMessageTimeoutW.side_effect = send_message
        driver._user32 = lambda: user32

        value = driver._read_window_text_by_handle(303)

        self.assertEqual(value, "C:\\horns\\Project.abec")
        user32.GetWindowTextW.assert_not_called()

    def test_native_text_entry_sends_characters_to_exact_edit_handle(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        user32 = Mock()
        user32.SendMessageTimeoutW.return_value = 1
        driver._user32 = lambda: user32

        written = driver._post_native_text_entry(303, "A b")

        self.assertTrue(written)
        self.assertEqual(user32.SendMessageTimeoutW.call_count, 5)
        self.assertEqual(
            [call.args[2] for call in user32.SendMessageTimeoutW.call_args_list[2:]],
            [ord("A"), ord(" "), ord("b")],
        )
        self.assertTrue(all(call.args[0] == 303 for call in user32.SendMessageTimeoutW.call_args_list))

    def test_filename_writer_verifies_standard_dialog_write_before_submit(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        user32 = Mock()
        user32.GetDlgItem.return_value = 202
        values = {202: "", 303: ""}

        def set_dialog_text(_dialog, _control_id, pointer) -> int:
            values[303] = str(pointer.value)
            return 1

        user32.SetDlgItemTextW.side_effect = set_dialog_text
        driver._user32 = lambda: user32
        driver._dialog_filename_edit_handle = lambda _dialog: 303
        driver._read_window_text_by_handle = lambda hwnd: values.get(hwnd, "")
        driver._dialog_filename_readback = lambda _dialog: values[303]

        result = driver._write_dialog_filename_verified(dialog_handle=101, value="C:\\horns\\Project.abec")

        self.assertTrue(result["verified"])
        self.assertEqual(result["method"], "SetDlgItemTextW_id1148")
        self.assertEqual(result["readbacks"]["edit"], "C:\\horns\\Project.abec")
        user32.SetWindowTextW.assert_not_called()

    def test_filename_writer_rejects_success_without_matching_readback(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        user32 = Mock()
        user32.GetDlgItem.return_value = 202
        user32.SetDlgItemTextW.return_value = 1
        user32.SetWindowTextW.return_value = 1
        user32.SendMessageTimeoutW.return_value = 1
        driver._user32 = lambda: user32
        driver._dialog_filename_edit_handle = lambda _dialog: 303
        driver._read_window_text_by_handle = lambda _hwnd: ""
        driver._dialog_filename_readback = lambda _dialog: ""

        result = driver._write_dialog_filename_verified(dialog_handle=101, value="C:\\horns\\Project.abec")

        self.assertFalse(result["verified"])
        self.assertEqual(result["method"], "")
        self.assertGreaterEqual(len(result["attempts"]), 3)

    def test_polling_snapshot_uses_native_metrics_without_uia_tree(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver._list_vacs_process_ids = lambda: [101, 202]
        native_calls: list[int] = []

        def native_metrics(process_id: int):
            native_calls.append(process_id)
            rows = [
                {
                    "title": "VacsViewer",
                    "class_name": "TForm_DatMain",
                    "controls_count": 22 if process_id == 101 else 151,
                    "graph_keyword_hits": 1 if process_id == 101 else 9,
                    "is_visible": True,
                }
            ]
            if process_id == 202:
                rows = [
                    {
                        "title": f"helper-{index}",
                        "class_name": "TPUtilWindow",
                        "controls_count": index,
                        "graph_keyword_hits": 0,
                        "is_visible": False,
                    }
                    for index in range(9)
                ] + rows
            return rows

        driver._native_vacs_window_metrics = native_metrics
        driver._process_top_level_windows = lambda **_: self.fail("UIA polling must not run")

        snapshot = driver._vacs_ui_snapshot()

        self.assertEqual(native_calls, [101, 202])
        self.assertEqual(snapshot["pids"], [101, 202])
        self.assertEqual(snapshot["max_controls_count"], 151)
        self.assertEqual(snapshot["max_graph_keyword_hits"], 9)
        self.assertEqual(snapshot["snapshot_backend"], "win32_hwnd")
        self.assertEqual(snapshot["windows"]["202"][0]["title"], "VacsViewer")
        self.assertLessEqual(len(snapshot["windows"]["202"]), 8)


if __name__ == "__main__":
    unittest.main()
