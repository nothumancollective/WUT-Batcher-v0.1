from __future__ import annotations

from dataclasses import dataclass, replace
import ctypes
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple

from pywinauto import Desktop


BM_GETCHECK = 0x00F0
BM_SETCHECK = 0x00F1
BM_CLICK = 0x00F5
BST_UNCHECKED = 0
BST_CHECKED = 1
BST_INDETERMINATE = 2
GWL_STYLE = -16
DEFAULT_SETTER_METHODS: Tuple[str, ...] = ("bm_setcheck", "bm_click", "uia_toggle", "uia_invoke")
DEFAULT_PROBE_REPORT_PATH = Path(__file__).resolve().parents[1] / "docs" / "vacs_export_setter_probe_report.json"


STATE_LABELS = {
    BST_UNCHECKED: "UNCHECKED",
    BST_CHECKED: "CHECKED",
    BST_INDETERMINATE: "INDETERMINATE",
}


def _state_label(value: Optional[int]) -> str:
    if value is None:
        return "UNKNOWN"
    return STATE_LABELS.get(int(value), f"UNKNOWN({int(value)})")


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(fallback)


class ExportConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class RequiredControlSpec:
    purpose: str
    expected_state: int
    settable: bool
    selector: Mapping[str, Any]
    methods: Tuple[str, ...] = DEFAULT_SETTER_METHODS


@dataclass
class ControlRecord:
    handle: int
    class_name: str
    control_type: str
    automation_id: str
    title: str
    text: str
    ctrl_id: int
    style: int
    win32_index: Optional[int]
    checkbox_index: Optional[int]
    rect_top: int
    rect_left: int
    wrapper: Optional[Any]


@dataclass(frozen=True)
class EnforcedControlResult:
    purpose: str
    expected_state: int
    before_state: Optional[int]
    after_state: Optional[int]
    selector_used: str
    attempted_methods: Tuple[str, ...]
    changed: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "purpose": self.purpose,
            "expected_state": _state_label(self.expected_state),
            "before_state": _state_label(self.before_state),
            "after_state": _state_label(self.after_state),
            "selector_used": self.selector_used,
            "attempted_methods": list(self.attempted_methods),
            "changed": bool(self.changed),
        }


# Built from deterministic dialog evidence (phase0 + phase2 probe):
# - `Export of parameters` must stay checked to keep Param_Coord_x2/x3 header metadata.
# - Matrix/abscissa/single-file/phase-radian toggles stay unchecked for legacy polar matrix output.
# - Live 2026-07-31 evidence shows VACS opens ``Try matrix form`` checked for
#   ``TForm_DatGraph`` (Radiation Impedance), while it is unchecked for
#   ``TForm_DatContour`` (polar data).  That control must therefore be resolved
#   from the graph class instead of applying the polar contract globally.
# No stable AutomationId has been observed for these controls in contour exports,
# so robust fallback selectors include class/title regex and checkbox ordering.
REQUIRED_EXPORT_CONTROLS: Tuple[RequiredControlSpec, ...] = (
    RequiredControlSpec(
        purpose="IncludeHeader",
        expected_state=BST_CHECKED,
        settable=False,
        selector={
            # Probe 2026-02-21 (live VACS): TRzCheckBox "Export of parameters"
            "automation_ids": ("1050536",),
            "ctrl_ids": (1050536,),
            "class_name_regex": r"(TRzCheckBox|Button)",
            "name_regex": r"(export.*parameters|parameter.*export|parameter.*ausgabe)",
            "checkbox_indices": (3,),
            "win32_indices": (6,),
        },
    ),
    RequiredControlSpec(
        purpose="AbscissaDataBlocks",
        expected_state=BST_UNCHECKED,
        settable=False,
        selector={
            # Probe 2026-02-21 (live VACS): TRzCheckBox "Abscissa separat"
            "automation_ids": ("2033636",),
            "ctrl_ids": (2033636,),
            "class_name_regex": r"(TRzCheckBox|Button)",
            "name_regex": r"(abscissa|abzisse|abscissa separat)",
            "checkbox_indices": (5,),
            "win32_indices": (11,),
        },
    ),
    RequiredControlSpec(
        purpose="TryMatrixForm",
        expected_state=BST_UNCHECKED,
        settable=False,
        selector={
            # Probe 2026-02-21 (live VACS): TRzCheckBox "Try matrix form"
            "automation_ids": (),
            "ctrl_ids": (),
            "class_name_regex": r"(TRzCheckBox|Button)",
            "name_regex": r"(try\s*matrix\s*form|matrix\s*form)",
            "checkbox_indices": (0,),
            "win32_indices": (12,),
        },
    ),
    RequiredControlSpec(
        purpose="SingleFile",
        expected_state=BST_UNCHECKED,
        settable=False,
        selector={
            # Probe 2026-02-21 (live VACS): TRzCheckBox "Single file"
            "automation_ids": (),
            "ctrl_ids": (),
            "class_name_regex": r"(TRzCheckBox|Button)",
            "name_regex": r"(single file|single)",
            "checkbox_indices": (7,),
            "win32_indices": (3,),
        },
    ),
    RequiredControlSpec(
        purpose="ComplexFormat",
        expected_state=BST_UNCHECKED,
        settable=False,
        selector={
            # Probe 2026-02-21 (live VACS): TRzCheckBox "Phase as radiant"
            "automation_ids": ("788396",),
            "ctrl_ids": (788396,),
            "class_name_regex": r"(TRzCheckBox|Button)",
            "name_regex": r"(phase\s*as\s*radiant|phase.*radian)",
            "checkbox_indices": (8,),
            "win32_indices": (7,),
        },
    ),
)


def required_export_controls_for_graph_class(
    graph_class_name: str,
    required_controls: Iterable[RequiredControlSpec] = REQUIRED_EXPORT_CONTROLS,
) -> Tuple[RequiredControlSpec, ...]:
    """Return the export-dialog contract for a VACS graph-window class.

    Unknown/empty graph classes keep the historic contour contract so existing
    callers remain conservative.  VACS makes ``Try matrix form`` read-only in
    the observed dialogs, so accepting either state would hide a wrong target;
    selecting the expected state from the graph class preserves fail-fast
    verification without rejecting valid 1-D graph exports.
    """

    is_data_graph = str(graph_class_name or "").strip().casefold() == "tform_datgraph"
    expected_matrix_state = BST_CHECKED if is_data_graph else BST_UNCHECKED
    return tuple(
        replace(spec, expected_state=expected_matrix_state)
        if spec.purpose == "TryMatrixForm"
        else spec
        for spec in required_controls
    )


class EnforcerBackend(Protocol):
    def resolve_control(self, spec: RequiredControlSpec) -> Tuple[Optional[Any], str]:
        ...

    def read_state(self, control: Any) -> Optional[int]:
        ...

    def apply_method(self, control: Any, method: str, expected_state: int) -> Optional[int]:
        ...

    def is_alive(self, control: Any) -> bool:
        ...


class Win32UiaExportDialogBackend:
    def __init__(self, dialog: Any) -> None:
        self.dialog = dialog
        self._controls = self._enumerate_controls(dialog)

    @property
    def controls(self) -> List[ControlRecord]:
        return list(self._controls)

    def _window_text(self, ctrl: Any) -> str:
        try:
            return str(ctrl.window_text() or "").strip()
        except Exception:
            try:
                return str(getattr(ctrl.element_info, "name", "") or "").strip()
            except Exception:
                return ""

    def _win32_children(self, hwnd: int) -> List[Dict[str, Any]]:
        if int(hwnd or 0) <= 0:
            return []
        user32 = ctypes.windll.user32
        get_class = user32.GetClassNameW
        get_text = user32.GetWindowTextW
        get_id = user32.GetDlgCtrlID
        get_style = user32.GetWindowLongW
        get_rect = user32.GetWindowRect
        rows: List[Dict[str, Any]] = []
        enum_child_proc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def _class_name(handle: int) -> str:
            buf = ctypes.create_unicode_buffer(256)
            get_class(int(handle), buf, 255)
            return str(buf.value or "")

        def _text(handle: int) -> str:
            buf = ctypes.create_unicode_buffer(512)
            get_text(int(handle), buf, 511)
            return str(buf.value or "")

        def _cb(chwnd, _lparam):
            handle = int(chwnd)
            rect = ctypes.wintypes.RECT()
            has_rect = bool(get_rect(int(handle), ctypes.byref(rect)))
            rows.append(
                {
                    "handle": handle,
                    "class_name": _class_name(handle),
                    "text": _text(handle),
                    "ctrl_id": int(get_id(handle)),
                    "style": int(get_style(int(handle), int(GWL_STYLE))),
                    "rect_top": int(rect.top) if has_rect else 0,
                    "rect_left": int(rect.left) if has_rect else 0,
                }
            )
            return True

        user32.EnumChildWindows(int(hwnd), enum_child_proc(_cb), 0)
        return rows

    def _enumerate_controls(self, dialog: Any) -> List[ControlRecord]:
        dialog_info = getattr(dialog, "element_info", None)
        dialog_handle = int(getattr(dialog_info, "handle", 0) or 0)
        controls_by_handle: Dict[int, ControlRecord] = {}

        for wrapper in list(dialog.descendants()):
            info = getattr(wrapper, "element_info", None)
            handle = int(getattr(info, "handle", 0) or 0)
            record = controls_by_handle.get(handle)
            if record is None:
                record = ControlRecord(
                    handle=handle,
                    class_name=str(getattr(info, "class_name", "") or ""),
                    control_type=str(getattr(info, "control_type", "") or ""),
                    automation_id=str(getattr(info, "automation_id", "") or ""),
                    title=str(getattr(info, "name", "") or ""),
                    text=self._window_text(wrapper),
                    ctrl_id=-1,
                    style=0,
                    win32_index=None,
                    checkbox_index=None,
                    rect_top=0,
                    rect_left=0,
                    wrapper=wrapper,
                )
                controls_by_handle[handle] = record
            else:
                record.wrapper = wrapper

        for index, row in enumerate(self._win32_children(dialog_handle)):
            handle = int(row.get("handle", 0) or 0)
            existing = controls_by_handle.get(handle)
            if existing is None:
                existing = ControlRecord(
                    handle=handle,
                    class_name=str(row.get("class_name", "") or ""),
                    control_type="",
                    automation_id="",
                    title="",
                    text=str(row.get("text", "") or ""),
                    ctrl_id=int(row.get("ctrl_id", -1) or -1),
                    style=int(row.get("style", 0) or 0),
                    win32_index=index,
                    checkbox_index=None,
                    rect_top=int(row.get("rect_top", 0) or 0),
                    rect_left=int(row.get("rect_left", 0) or 0),
                    wrapper=None,
                )
                controls_by_handle[handle] = existing
            else:
                existing.class_name = str(row.get("class_name", existing.class_name) or existing.class_name)
                if not existing.text:
                    existing.text = str(row.get("text", "") or "")
                existing.ctrl_id = int(row.get("ctrl_id", existing.ctrl_id) or existing.ctrl_id)
                existing.style = int(row.get("style", existing.style) or existing.style)
                existing.win32_index = index
                existing.rect_top = int(row.get("rect_top", existing.rect_top) or existing.rect_top)
                existing.rect_left = int(row.get("rect_left", existing.rect_left) or existing.rect_left)

        controls = list(controls_by_handle.values())
        checkbox_rows = [
            record
            for record in controls
            if (
                str(record.control_type).lower() == "checkbox"
                or re.search(r"checkbox", str(record.class_name), re.IGNORECASE)
                or re.search(r"(TRzCheckBox|Button)", str(record.class_name), re.IGNORECASE)
            )
        ]
        checkbox_rows.sort(key=lambda item: (item.rect_top, item.rect_left, item.handle))
        for idx, record in enumerate(checkbox_rows):
            record.checkbox_index = idx
        return controls

    def resolve_control(self, spec: RequiredControlSpec) -> Tuple[Optional[ControlRecord], str]:
        selector = dict(spec.selector or {})
        automation_ids = {
            str(value).strip().lower()
            for value in list(selector.get("automation_ids", []) or [])
            if str(value).strip()
        }
        ctrl_ids = {_safe_int(value, -1) for value in list(selector.get("ctrl_ids", []) or [])}
        class_regex = str(selector.get("class_name_regex", "") or "").strip()
        name_regex = str(selector.get("name_regex", "") or "").strip()
        checkbox_indices = {_safe_int(value, -1) for value in list(selector.get("checkbox_indices", []) or [])}
        win32_indices = {_safe_int(value, -1) for value in list(selector.get("win32_indices", []) or [])}

        scored: List[Tuple[int, str, ControlRecord]] = []
        for control in self._controls:
            score = 0
            reasons: List[str] = []
            if automation_ids:
                aid = str(control.automation_id or "").strip().lower()
                if aid and aid in automation_ids:
                    score += 100
                    reasons.append(f"automation_id={control.automation_id}")
            if ctrl_ids and int(control.ctrl_id) in ctrl_ids:
                score += 90
                reasons.append(f"ctrl_id={control.ctrl_id}")
            if class_regex and re.search(class_regex, str(control.class_name or ""), re.IGNORECASE):
                score += 20
                reasons.append(f"class={control.class_name}")
            if name_regex:
                hay = " ".join([str(control.title or ""), str(control.text or ""), str(control.automation_id or "")])
                if re.search(name_regex, hay, re.IGNORECASE):
                    score += 60
                    reasons.append(f"name~{name_regex}")
            if checkbox_indices and control.checkbox_index is not None and int(control.checkbox_index) in checkbox_indices:
                score += 10
                reasons.append(f"checkbox_index={control.checkbox_index}")
            if win32_indices and control.win32_index is not None and int(control.win32_index) in win32_indices:
                score += 8
                reasons.append(f"win32_index={control.win32_index}")
            if score <= 0:
                continue
            scored.append((score, ",".join(reasons), control))

        if not scored:
            return None, "no_match"

        scored.sort(
            key=lambda item: (
                -item[0],
                int(item[2].checkbox_index if item[2].checkbox_index is not None else 10_000),
                int(item[2].win32_index if item[2].win32_index is not None else 10_000),
                int(item[2].handle),
            )
        )
        best = scored[0]
        return best[2], best[1]

    def read_state(self, control: ControlRecord) -> Optional[int]:
        handle = int(control.handle or 0)
        if handle > 0:
            try:
                value = int(ctypes.windll.user32.SendMessageW(int(handle), BM_GETCHECK, 0, 0))
                if value in {BST_UNCHECKED, BST_CHECKED, BST_INDETERMINATE}:
                    return value
            except Exception:
                pass

        wrapper = control.wrapper
        if wrapper is None:
            return None
        try:
            iface_toggle = getattr(wrapper, "iface_toggle", None)
            if iface_toggle is not None:
                value = int(iface_toggle.CurrentToggleState())
                if value in {BST_UNCHECKED, BST_CHECKED, BST_INDETERMINATE}:
                    return value
        except Exception:
            pass
        try:
            get_toggle = getattr(wrapper, "get_toggle_state", None)
            if callable(get_toggle):
                value = int(get_toggle())
                if value in {BST_UNCHECKED, BST_CHECKED, BST_INDETERMINATE}:
                    return value
        except Exception:
            pass
        return None

    def apply_method(self, control: ControlRecord, method: str, expected_state: int) -> Optional[int]:
        handle = int(control.handle or 0)
        wrapper = control.wrapper
        if method == "bm_setcheck":
            if handle > 0:
                ctypes.windll.user32.SendMessageW(int(handle), BM_SETCHECK, int(expected_state), 0)
        elif method == "bm_click":
            if handle > 0:
                ctypes.windll.user32.SendMessageW(int(handle), BM_CLICK, 0, 0)
        elif method == "uia_toggle":
            if wrapper is not None:
                iface_toggle = getattr(wrapper, "iface_toggle", None)
                if iface_toggle is not None:
                    iface_toggle.Toggle()
                else:
                    toggle = getattr(wrapper, "toggle", None)
                    if callable(toggle):
                        toggle()
        elif method == "uia_invoke":
            if wrapper is not None:
                invoke = getattr(wrapper, "invoke", None)
                if callable(invoke):
                    invoke()
                else:
                    click = getattr(wrapper, "click", None)
                    if callable(click):
                        click()
        else:
            raise ValueError(f"Unsupported method: {method}")
        time.sleep(0.05)
        return self.read_state(control)

    def is_alive(self, control: ControlRecord) -> bool:
        handle = int(getattr(control, "handle", 0) or 0)
        if handle <= 0:
            return False
        try:
            return bool(ctypes.windll.user32.IsWindow(int(handle)))
        except Exception:
            return True


def find_export_dialog(*, process_id: Optional[int] = None, timeout_s: float = 3.0) -> Optional[Any]:
    deadline = time.perf_counter() + max(0.1, float(timeout_s))
    while time.perf_counter() < deadline:
        windows: List[Any]
        try:
            windows = (
                list(Desktop(backend="uia").windows(process=int(process_id)))
                if process_id is not None
                else list(Desktop(backend="uia").windows())
            )
        except Exception:
            windows = []

        # Some VACS builds expose TForm_Export as a child window under TForm_DatMain
        # instead of a top-level desktop window.
        descendant_candidates: List[Any] = []
        for window in list(windows):
            try:
                info = getattr(window, "element_info", None)
                class_name = str(getattr(info, "class_name", "") or "")
                if class_name != "TForm_DatMain":
                    continue
                for child in list(window.descendants()):
                    child_info = getattr(child, "element_info", None)
                    if str(getattr(child_info, "control_type", "") or "") != "Window":
                        continue
                    handle = int(getattr(child_info, "handle", 0) or 0)
                    if handle <= 0:
                        continue
                    descendant_candidates.append(child)
            except Exception:
                continue

        if descendant_candidates:
            by_handle: Dict[int, Any] = {}
            for row in list(windows) + list(descendant_candidates):
                info = getattr(row, "element_info", None)
                handle = int(getattr(info, "handle", 0) or 0)
                if handle > 0:
                    by_handle[handle] = row
            windows = list(by_handle.values())
        candidates: List[Any] = []
        for window in windows:
            info = getattr(window, "element_info", None)
            class_name = str(getattr(info, "class_name", "") or "")
            title = str(getattr(info, "name", "") or "")
            if not re.search(r"(#32770|Dialog|TForm_Export|TForm_Edit|TForm_Picture)", class_name, re.IGNORECASE):
                continue
            if not re.search(r"(Data Export|Export|ASCII|TXT)", title, re.IGNORECASE):
                continue
            candidates.append(window)
        if candidates:
            candidates.sort(
                key=lambda item: (
                    0 if str(getattr(getattr(item, "element_info", None), "class_name", "") or "") == "TForm_Export" else 1,
                    -int(getattr(getattr(item, "element_info", None), "handle", 0) or 0),
                )
            )
            return candidates[0]
        time.sleep(0.05)
    return None


def _load_probe_settable_map(probe_report_path: Optional[str | Path]) -> Dict[str, bool]:
    path = Path(probe_report_path) if probe_report_path else DEFAULT_PROBE_REPORT_PATH
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    controls = payload.get("controls")
    if not isinstance(controls, list):
        return {}
    out: Dict[str, bool] = {}
    for row in controls:
        if not isinstance(row, dict):
            continue
        purpose = str(row.get("purpose", "")).strip()
        if not purpose:
            continue
        out[purpose] = bool(row.get("settable", False))
    return out


def resolve_required_controls(
    required_controls: Iterable[RequiredControlSpec] = REQUIRED_EXPORT_CONTROLS,
    *,
    probe_report_path: Optional[str | Path] = None,
) -> Tuple[RequiredControlSpec, ...]:
    probe_settable = _load_probe_settable_map(probe_report_path)
    rows: List[RequiredControlSpec] = []
    for spec in list(required_controls):
        if spec.purpose in probe_settable:
            rows.append(replace(spec, settable=bool(probe_settable[spec.purpose])))
        else:
            rows.append(spec)
    return tuple(rows)


def _configuration_error(purpose: str, expected_state: Optional[int], found: str) -> ExportConfigurationError:
    expected = _state_label(expected_state) if expected_state is not None else "UNKNOWN"
    return ExportConfigurationError(
        "Export configuration invalid: "
        f"[{purpose}] expected [{expected}], found [{found}]. "
        "Please set this option to the expected state in VACS preferences or the export dialog."
    )


def enforce_required_controls_with_backend(
    backend: EnforcerBackend,
    required_controls: Iterable[RequiredControlSpec] = REQUIRED_EXPORT_CONTROLS,
    *,
    logger: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    rows: List[EnforcedControlResult] = []
    for spec in list(required_controls):
        control, selector_used = backend.resolve_control(spec)
        if control is None:
            raise _configuration_error(spec.purpose, spec.expected_state, "MISSING")
        if not backend.is_alive(control):
            raise _configuration_error(spec.purpose, spec.expected_state, "DISAPPEARED")
        before_state = backend.read_state(control)
        if before_state is None:
            raise _configuration_error(spec.purpose, spec.expected_state, "UNKNOWN")
        attempted: List[str] = []
        changed = False
        after_state = before_state
        if int(before_state) != int(spec.expected_state):
            if not bool(spec.settable):
                raise _configuration_error(spec.purpose, spec.expected_state, _state_label(before_state))
            for method in list(spec.methods):
                attempted.append(method)
                try:
                    if not backend.is_alive(control):
                        raise _configuration_error(spec.purpose, spec.expected_state, "DISAPPEARED")
                    after_state = backend.apply_method(control, method, int(spec.expected_state))
                except ExportConfigurationError:
                    raise
                except Exception as exc:
                    if logger:
                        logger(
                            "setter_error",
                            {
                                "purpose": spec.purpose,
                                "method": method,
                                "error": repr(exc),
                            },
                        )
                    after_state = backend.read_state(control)
                if after_state is None:
                    continue
                if int(after_state) == int(spec.expected_state):
                    changed = True
                    break
            if after_state is None or int(after_state) != int(spec.expected_state):
                raise _configuration_error(spec.purpose, spec.expected_state, _state_label(after_state))

        rows.append(
            EnforcedControlResult(
                purpose=spec.purpose,
                expected_state=int(spec.expected_state),
                before_state=before_state,
                after_state=after_state,
                selector_used=selector_used,
                attempted_methods=tuple(attempted),
                changed=bool(changed),
            )
        )
    return {
        "ok": True,
        "controls": [row.to_dict() for row in rows],
    }


def enforce_export_dialog_controls(
    *,
    dialog: Any,
    required_controls: Iterable[RequiredControlSpec] = REQUIRED_EXPORT_CONTROLS,
    probe_report_path: Optional[str | Path] = None,
    logger: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    backend = Win32UiaExportDialogBackend(dialog)
    resolved = resolve_required_controls(required_controls, probe_report_path=probe_report_path)
    return enforce_required_controls_with_backend(backend, required_controls=resolved, logger=logger)


def enforce_export_dialog_for_process(
    *,
    process_id: Optional[int],
    timeout_s: float = 3.0,
    required_controls: Iterable[RequiredControlSpec] = REQUIRED_EXPORT_CONTROLS,
    probe_report_path: Optional[str | Path] = None,
    logger: Optional[Callable[[str, Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    dialog = find_export_dialog(process_id=process_id, timeout_s=timeout_s)
    if dialog is None:
        raise ExportConfigurationError("Export configuration invalid: [ExportDialog] expected [VISIBLE], found [MISSING].")
    return enforce_export_dialog_controls(
        dialog=dialog,
        required_controls=required_controls,
        probe_report_path=probe_report_path,
        logger=logger,
    )


__all__ = [
    "BM_CLICK",
    "BM_GETCHECK",
    "BM_SETCHECK",
    "BST_CHECKED",
    "BST_INDETERMINATE",
    "BST_UNCHECKED",
    "DEFAULT_PROBE_REPORT_PATH",
    "ExportConfigurationError",
    "REQUIRED_EXPORT_CONTROLS",
    "RequiredControlSpec",
    "Win32UiaExportDialogBackend",
    "_state_label",
    "enforce_export_dialog_controls",
    "enforce_export_dialog_for_process",
    "enforce_required_controls_with_backend",
    "find_export_dialog",
    "required_export_controls_for_graph_class",
    "resolve_required_controls",
]
