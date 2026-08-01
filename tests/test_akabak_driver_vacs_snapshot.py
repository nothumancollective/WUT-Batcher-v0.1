from __future__ import annotations

import json
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

from app.akabak_driver import AkabakDriver, _solve_menu_candidate


class AkabakDriverVacsSnapshotTests(unittest.TestCase):
    def test_native_menu_command_enabled_decodes_exact_windows_menu_state(self) -> None:
        class FakeFunction:
            def __init__(self, result: int) -> None:
                self.result = result
                self.restype = None

            def __call__(self, *_args: object) -> int:
                return self.result

        driver = AkabakDriver.__new__(AkabakDriver)
        fake_user32 = SimpleNamespace(
            GetMenu=FakeFunction(900),
            GetMenuState=FakeFunction(0),
        )
        driver._user32 = Mock(return_value=fake_user32)

        with patch("app.akabak_driver.os.name", "nt"):
            self.assertTrue(driver._native_menu_command_enabled(101, 94))
            fake_user32.GetMenuState.result = 1
            self.assertFalse(driver._native_menu_command_enabled(101, 94))
            fake_user32.GetMenuState.result = 2
            self.assertFalse(driver._native_menu_command_enabled(101, 94))
            fake_user32.GetMenuState.result = 0xFFFFFFFF
            self.assertIsNone(driver._native_menu_command_enabled(101, 94))

    def test_vacs_startup_editors_close_only_on_exact_class_title_and_content(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver._native_process_window_rows = Mock(
            return_value=[
                {"native_handle": 101, "class_name": "TForm_Editor", "title": "Editor - 1"},
                {"native_handle": 102, "class_name": "TForm_Editor", "title": "My measurements"},
                {"native_handle": 103, "class_name": "TForm_DatGraph", "title": "Editor - 2"},
            ]
        )
        driver._native_descendant_window_rows = Mock(
            side_effect=lambda **kwargs: [
                {
                    "title": "Welcome to Visualize Acoustics ! Skip this note next time Import some data",
                    "class_name": "TRichEdit",
                    "native_handle": 201,
                }
            ]
            if kwargs["parent_handle"] == 101
            else []
        )
        driver._send_message_timeout = Mock(return_value=True)

        actions = driver._dismiss_vacs_startup_editors([77])

        self.assertEqual([item["native_handle"] for item in actions], [101])
        driver._send_message_timeout.assert_called_once_with(101, 0x0010, timeout_ms=1000)

    def test_windows_solve_trigger_uses_native_hwnd_without_resolving_uia_control(self) -> None:
        class HandleOnlyMainWindow:
            def __init__(self) -> None:
                self._wut_native_handle = 101

            def set_focus(self) -> None:
                raise AssertionError("Windows solve must not resolve the UIA wrapper")

            def type_keys(self, *_args, **_kwargs) -> None:
                raise AssertionError("Windows solve must not type through UIA")

        driver = AkabakDriver.__new__(AkabakDriver)
        driver.state = "project_open"
        driver.last_solve_diagnostics_path = None
        driver.solve_context = {}
        driver.step_timeout_s = 30.0
        driver.watchdog = None
        driver.session = SimpleNamespace(process_id=77, find_window=Mock(return_value=HandleOnlyMainWindow()))
        driver._connect = Mock()
        driver._log = Mock()
        driver._list_akabak_process_ids = Mock(return_value=[77])
        driver._list_vacs_process_ids = Mock(return_value=[])
        driver._find_main_process_modal = Mock(return_value=None)
        driver._trigger_solve_native = Mock(
            return_value={"trigger": "hwnd_menu_command", "status": "sent", "command_id": 42}
        )
        driver._solve_signal_snapshot = Mock(
            return_value={
                "akabak_pids": [77],
                "vacs_pids": [],
                "akabak_cpu_times_s": {"77": 1.0},
                "progress_window_present": True,
            }
        )

        with patch("app.akabak_driver.os.name", "nt"), patch(
            "app.akabak_driver._process_cpu_time_seconds", return_value=1.0
        ):
            result = driver.run_solve()

        self.assertTrue(result.ok)
        self.assertEqual(result.details["started"]["start_signal"], "progress_window_present")
        driver._trigger_solve_native.assert_called_once_with(101)

    def test_solve_menu_candidate_prefers_explicit_f4_accelerator(self) -> None:
        candidate = _solve_menu_candidate(
            [
                {"title": "Open", "command_id": 10},
                {"title": "&Calculate\tF4", "command_id": 42, "path": "Calculation -> Calculate"},
            ]
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["command_id"], 42)

    def test_solve_menu_candidate_uses_present_calculate_all_command_id(self) -> None:
        candidate = _solve_menu_candidate(
            [
                {"title": "", "command_id": 94, "path": "Processing"},
                {"title": "Unknown localized item", "command_id": 95},
            ]
        )

        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["command_id"], 94)

    def test_solve_trigger_does_not_double_send_after_menu_dispatch_timeout(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver._native_menu_rows = Mock(
            return_value=[{"title": "Calculate all\tF4", "command_id": 94, "path": "Processing"}]
        )
        driver._send_message_timeout = Mock(return_value=False)
        driver._send_key_f4 = Mock(return_value=True)

        result = driver._trigger_solve_native(101)

        self.assertEqual(result["status"], "dispatch_timed_out")
        self.assertEqual(result["command_id"], 94)
        driver._send_key_f4.assert_not_called()

    def test_windows_process_inventory_uses_native_snapshot(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)

        with patch("app.akabak_driver.os.name", "nt"), patch(
            "app.akabak_driver._native_process_ids_by_image", return_value=[77, 88]
        ) as snapshot:
            rows = driver._list_process_ids_by_image("AKABAK.exe")

        self.assertEqual(rows, [77, 88])
        snapshot.assert_called_once_with("akabak.exe")

    def test_apply_waits_for_import_report_to_be_complete_and_stable(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        interpreter = object()
        apply_button = Mock()
        apply_button.is_enabled.return_value = True
        apply_button.element_info = SimpleNamespace(handle=404)
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
        self.assertNotIn("apply_button", second)
        json.dumps(second)

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
        user32.SendMessageTimeoutW.side_effect = lambda *_: (rows.clear() or 1)
        driver._user32 = lambda: user32
        driver._native_process_window_rows = lambda **_: list(rows)
        driver._child_windows = lambda *_args, **_kwargs: self.fail("UIA wrapper lookup must not run")
        driver._log = Mock()

        with patch("app.akabak_driver.os.name", "nt"):
            driver._dismiss_startup_windows(main_window=main_window, step="open_project")

        user32.SendMessageTimeoutW.assert_called_once()
        self.assertEqual(rows, [])

    def test_startup_popup_reappearing_after_import_is_closed_narrowly(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        driver.step_timeout_s = 1.0
        driver._window_handle = Mock(return_value=101)
        main_row = {
            "native_handle": 101,
            "title": "Akabak-Demo - input",
            "class_name": "TForm_Main",
            "is_visible": True,
        }
        example_row = {
            "native_handle": 202,
            "title": "Example Files",
            "class_name": "TForm_ExampleFiles",
            "is_visible": True,
        }
        rows = [main_row, example_row]
        driver._process_top_level_windows = Mock(side_effect=lambda: list(rows))
        driver._window_signature_row = Mock(side_effect=lambda row: dict(row))
        driver._is_interpreter_window_row = Mock(return_value=False)

        def _close(hwnd: int, message: int, **_kwargs: object) -> bool:
            self.assertEqual((hwnd, message), (202, 0x0010))
            rows.remove(example_row)
            return True

        driver._send_message_timeout = Mock(side_effect=_close)
        driver._log = Mock()

        state = driver._ensure_import_window_closed(main_window=object(), step="import_if_needed")

        self.assertEqual(state["status"], "main_only_open")
        self.assertEqual(state["closed_startup_handles"], [202])
        driver._send_message_timeout.assert_called_once_with(202, 0x0010)
        driver._log.assert_called_once_with(
            level="info",
            step="import_if_needed",
            event="startup_modal_closed_after_import",
            payload={"class_name": "TForm_ExampleFiles", "handle": 202},
        )

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

    def test_dialog_filename_readback_falls_back_to_container_for_blank_nested_edit(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        user32 = Mock()
        user32.GetDlgItem.return_value = 202
        driver._user32 = lambda: user32
        driver._dialog_filename_edit_handle = Mock(return_value=303)
        driver._read_window_text_by_handle = Mock(
            side_effect=lambda hwnd: "C:\\horns\\Project.abec" if hwnd == 202 else ""
        )

        value = driver._dialog_filename_readback(101)

        self.assertEqual(value, "C:\\horns\\Project.abec")
        self.assertEqual(driver._read_window_text_by_handle.call_args_list, [call(303), call(202)])

    def test_cross_process_window_messages_are_bounded(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        user32 = Mock()
        user32.SendMessageTimeoutW.return_value = 1
        driver._user32 = lambda: user32

        sent = driver._send_message_timeout(101, 0x0010, timeout_ms=250)

        self.assertTrue(sent)
        user32.SendMessageTimeoutW.assert_called_once()
        self.assertEqual(user32.SendMessageTimeoutW.call_args.args[0:2], (101, 0x0010))
        self.assertEqual(user32.SendMessageTimeoutW.call_args.args[5], 250)

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
        driver.initial_akabak_pids = set()
        driver.initial_vacs_pids = set()
        driver.owned_akabak_pids = set()
        driver.owned_vacs_pids = set()
        driver._list_akabak_process_ids = Mock(return_value=[])
        driver._list_vacs_process_ids = Mock(return_value=[])
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

    def test_native_dialog_enter_rejects_missing_exact_handles(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)

        self.assertFalse(driver._send_native_dialog_enter(0, 303))
        self.assertFalse(driver._send_native_dialog_enter(101, 0))

    def test_filename_writer_verifies_standard_dialog_write_before_submit(self) -> None:
        driver = AkabakDriver.__new__(AkabakDriver)
        user32 = Mock()
        user32.GetDlgItem.return_value = 202
        values = {202: "", 303: ""}

        def set_dialog_text(_dialog, _control_id, pointer) -> int:
            values[202] = str(pointer.value)
            return 1

        def set_common_dialog_text(*_args) -> int:
            values[202] = "C:\\horns\\Project.abec"
            return 1

        def set_window_text(hwnd, pointer) -> int:
            values[hwnd] = str(pointer.value)
            return 1

        user32.SendMessageTimeoutW.side_effect = set_common_dialog_text
        user32.SetDlgItemTextW.side_effect = set_dialog_text
        user32.SetWindowTextW.side_effect = set_window_text
        driver._user32 = lambda: user32
        driver._dialog_filename_edit_handle = lambda _dialog: 303
        driver._read_window_text_by_handle = lambda hwnd: values.get(hwnd, "")
        driver._dialog_filename_readback = lambda _dialog: values[303]

        result = driver._write_dialog_filename_verified(dialog_handle=101, value="C:\\horns\\Project.abec")

        self.assertTrue(result["verified"])
        self.assertEqual(result["method"], "SetWindowTextW_edit")
        self.assertEqual(result["readbacks"]["edit"], "C:\\horns\\Project.abec")
        user32.SendMessageTimeoutW.assert_called_once()
        user32.SetDlgItemTextW.assert_called_once()
        user32.SetWindowTextW.assert_called_once()

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
