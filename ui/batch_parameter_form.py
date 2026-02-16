"""Batch parameter form for variable ATH parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from ui.form_builder import AccordionGroupBox, ScalarFieldEditor, SegmentedEnumInput
from ui.form_schema import FieldSpec, FormSchema, build_project_form_schema

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QDoubleValidator, QIntValidator
    from PySide6.QtWidgets import (
        QCheckBox,
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for batch parameter form.") from exc


def _to_float(raw: str) -> Optional[float]:
    text = str(raw or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _to_int(raw: str) -> Optional[int]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except Exception:
        return None


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


class _ObjectToggleInput(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.segment = SegmentedEnumInput(
            options=[("disabled", 0), ("enabled", 1)],
            fallback_value=0,
            enforce_fallback=True,
        )
        self.segment.set_value(0)
        self.segment.changed.connect(lambda *_: self.changed.emit())
        root.addWidget(self.segment, 0, Qt.AlignLeft)
        root.addStretch(1)

    def is_set(self) -> bool:
        return self.segment.value() == 1

    def value(self) -> Optional[int]:
        return 1 if self.is_set() else None

    def set_value(self, value: Any) -> None:
        self.segment.set_value(1 if bool(value) else 0)

    def clear(self) -> None:
        self.segment.set_value(0)

    def set_locked(self, locked: bool) -> None:
        self.segment.set_locked(locked)


@dataclass
class _FieldRow:
    field: FieldSpec
    label: str
    group_name: str
    container: QWidget
    base_editor: QWidget
    sweep_toggle: QCheckBox
    start_edit: QLineEdit
    end_edit: QLineEdit
    steps_edit: QLineEdit
    button_layout: bool


class BatchParameterForm(QWidget):
    changed = Signal()

    _GROUP_ORDER = ["Basics", "Throat Profile", "Morph", "GCurve", "Core", "Enclosure"]

    def __init__(self, schema: Optional[FormSchema] = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.schema = schema or build_project_form_schema()
        self._rows: Dict[str, _FieldRow] = {}
        self._group_boxes: Dict[str, AccordionGroupBox] = {}
        self._accordion_boxes: List[AccordionGroupBox] = []
        self._accordion_sync = False

        self._visible_keys: set[str] = set()
        self._locked_keys: set[str] = set()
        self._project_fixed_keys: set[str] = set()
        self._sweepable_keys: set[str] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(self.scroll, 1)

        self.content = QWidget()
        self.scroll.setWidget(self.content)
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)

        self._build()
        self.content_layout.addStretch(1)
        self._open_first_visible_group()

    @staticmethod
    def _group_name(spec: FieldSpec) -> str:
        if len(spec.group_path) >= 2:
            return str(spec.group_path[1])
        if spec.group_path:
            return str(spec.group_path[0])
        return "General"

    @staticmethod
    def _is_button_layout(field: FieldSpec) -> bool:
        if field.widget_kind == "object":
            return True
        if field.key == "Rollback":
            return True
        if field.widget_kind == "bool":
            return True
        if field.widget_kind == "enum":
            if field.key == "Mesh.Enclosure.EdgeType":
                return False
            return 1 < len(list(field.enum_options)) <= 4
        return False

    def _make_base_editor(self, field: FieldSpec) -> QWidget:
        if field.widget_kind == "object":
            return _ObjectToggleInput()
        return ScalarFieldEditor(field)

    def _ordered_group_names(self, grouped: Dict[str, List[FieldSpec]]) -> List[str]:
        ordered: List[str] = [name for name in self._GROUP_ORDER if name in grouped]
        rest = sorted(name for name in grouped.keys() if name not in ordered)
        ordered.extend(rest)
        return ordered

    def _register_box(self, box: AccordionGroupBox) -> None:
        self._accordion_boxes.append(box)
        box.toggled.connect(lambda expanded, current=box: self._on_group_toggled(current, expanded))

    def _on_group_toggled(self, current: AccordionGroupBox, expanded: bool) -> None:
        if self._accordion_sync or not expanded:
            return
        self._accordion_sync = True
        try:
            for box in self._accordion_boxes:
                if box is current:
                    continue
                if box.isVisible():
                    box.set_collapsed(True)
        finally:
            self._accordion_sync = False

    def _build(self) -> None:
        grouped: Dict[str, List[FieldSpec]] = {}
        for field in list(self.schema.fields):
            group = self._group_name(field)
            grouped.setdefault(group, []).append(field)
        for values in grouped.values():
            values.sort(key=lambda item: (int(item.order), str(item.key)))

        for group_name in self._ordered_group_names(grouped):
            box = AccordionGroupBox(group_name)
            box.set_collapsed(True)
            self._register_box(box)
            self._group_boxes[group_name] = box
            self.content_layout.addWidget(box)

            for spec in grouped.get(group_name, []):
                self._build_row(box, spec, group_name)

    def _build_row(self, box: AccordionGroupBox, field: FieldSpec, group_name: str) -> None:
        key = str(field.key)
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = QLabel(f"{field.label} ({key})")
        label.setMinimumWidth(250)
        label.setWordWrap(True)
        row_layout.addWidget(label, 0, Qt.AlignTop)

        base_editor = self._make_base_editor(field)
        if hasattr(base_editor, "changed"):
            base_editor.changed.connect(lambda *_: self.changed.emit())  # type: ignore[attr-defined]
        row_layout.addWidget(base_editor, 0, Qt.AlignLeft | Qt.AlignVCenter)

        sweep_toggle = QCheckBox("Sweep")
        row_layout.addWidget(sweep_toggle, 0, Qt.AlignLeft | Qt.AlignVCenter)

        start_edit = QLineEdit()
        start_edit.setPlaceholderText("start")
        start_edit.setMaximumWidth(100)
        start_edit.setValidator(QDoubleValidator(start_edit))
        start_edit.setVisible(False)
        start_edit.textChanged.connect(lambda _text: self.changed.emit())
        row_layout.addWidget(start_edit, 0, Qt.AlignLeft | Qt.AlignVCenter)

        end_edit = QLineEdit()
        end_edit.setPlaceholderText("end")
        end_edit.setMaximumWidth(100)
        end_edit.setValidator(QDoubleValidator(end_edit))
        end_edit.setVisible(False)
        end_edit.textChanged.connect(lambda _text: self.changed.emit())
        row_layout.addWidget(end_edit, 0, Qt.AlignLeft | Qt.AlignVCenter)

        steps_edit = QLineEdit("3")
        steps_edit.setPlaceholderText("steps")
        steps_edit.setMaximumWidth(80)
        steps_edit.setValidator(QIntValidator(1, 9999, steps_edit))
        steps_edit.setVisible(False)
        steps_edit.textChanged.connect(lambda _text: self.changed.emit())
        row_layout.addWidget(steps_edit, 0, Qt.AlignLeft | Qt.AlignVCenter)
        row_layout.addStretch(1)

        box.body_layout().addWidget(row_widget)
        row = _FieldRow(
            field=field,
            label=str(field.label),
            group_name=group_name,
            container=row_widget,
            base_editor=base_editor,
            sweep_toggle=sweep_toggle,
            start_edit=start_edit,
            end_edit=end_edit,
            steps_edit=steps_edit,
            button_layout=self._is_button_layout(field),
        )
        self._rows[key] = row
        sweep_toggle.toggled.connect(lambda enabled, row_key=key: self._on_sweep_toggled(row_key, enabled))

    def _open_first_visible_group(self) -> None:
        visible_boxes = [box for box in self._accordion_boxes if box.isVisible()]
        if not visible_boxes:
            return
        self._accordion_sync = True
        try:
            for index, box in enumerate(visible_boxes):
                box.set_collapsed(index != 0)
        finally:
            self._accordion_sync = False

    def _current_state(self, row: _FieldRow) -> tuple[bool, Any]:
        editor = row.base_editor
        if isinstance(editor, ScalarFieldEditor):
            state = editor.current_state()
            return bool(state.is_set), state.value
        if hasattr(editor, "is_set") and hasattr(editor, "value"):
            is_set = bool(editor.is_set())  # type: ignore[attr-defined]
            value = editor.value()  # type: ignore[attr-defined]
            return is_set, value
        return (False, None)

    def _set_editor_value(self, row: _FieldRow, value: Any) -> None:
        editor = row.base_editor
        if isinstance(editor, ScalarFieldEditor):
            if value is None:
                editor.set_is_set(False)
            else:
                editor.set_value(value)
            return
        if value is None:
            if hasattr(editor, "clear"):
                editor.clear()  # type: ignore[attr-defined]
            return
        if hasattr(editor, "set_value"):
            editor.set_value(value)  # type: ignore[attr-defined]

    def _set_editor_locked(self, row: _FieldRow, locked: bool) -> None:
        editor = row.base_editor
        if isinstance(editor, ScalarFieldEditor):
            editor.set_locked(locked)
            return
        if hasattr(editor, "set_locked"):
            editor.set_locked(locked)  # type: ignore[attr-defined]
            return
        editor.setEnabled(not locked)

    def set_project_fixed_keys(self, keys: Sequence[str]) -> None:
        self._project_fixed_keys = {str(item) for item in list(keys or []) if str(item).strip()}
        self._refresh_visibility()

    def apply_compatibility(self, state: Dict[str, Any]) -> None:
        self._visible_keys = {str(item) for item in list(state.get("visible_keys", []) or []) if str(item).strip()}
        self._locked_keys = {str(item) for item in list(state.get("locked_keys", []) or []) if str(item).strip()}
        self._sweepable_keys = {str(item) for item in list(state.get("sweepable_keys", []) or []) if str(item).strip()}
        self._refresh_visibility()

    def _refresh_visibility(self) -> None:
        for key, row in self._rows.items():
            is_visible = (not self._visible_keys or key in self._visible_keys) and key not in self._project_fixed_keys
            is_locked = key in self._locked_keys
            can_sweep = is_visible and (key in self._sweepable_keys) and (not is_locked) and (not row.button_layout)

            row.container.setVisible(is_visible)
            self._set_editor_locked(row, is_locked)
            row.sweep_toggle.setVisible(not row.button_layout)
            row.sweep_toggle.setEnabled(can_sweep)
            if not can_sweep and row.sweep_toggle.isChecked():
                row.sweep_toggle.setChecked(False)

            show_sweep_inputs = bool(row.sweep_toggle.isChecked() and can_sweep)
            row.start_edit.setVisible(show_sweep_inputs)
            row.end_edit.setVisible(show_sweep_inputs)
            row.steps_edit.setVisible(show_sweep_inputs)
            row.start_edit.setEnabled(show_sweep_inputs)
            row.end_edit.setEnabled(show_sweep_inputs)
            row.steps_edit.setEnabled(show_sweep_inputs)

        for group_name, box in self._group_boxes.items():
            any_visible = any(
                (row.group_name == group_name) and (not row.container.isHidden())
                for row in self._rows.values()
            )
            box.setVisible(any_visible)

        visible_boxes = [box for box in self._accordion_boxes if box.isVisible()]
        expanded = [box for box in visible_boxes if not box.is_collapsed()]
        if not visible_boxes:
            return
        if not expanded:
            self._open_first_visible_group()
            return
        if len(expanded) > 1:
            keep = expanded[0]
            self._accordion_sync = True
            try:
                for box in expanded[1:]:
                    box.set_collapsed(True)
            finally:
                self._accordion_sync = False
            keep.set_collapsed(False)

    def _on_sweep_toggled(self, key: str, enabled: bool) -> None:
        row = self._rows.get(str(key))
        if row is None:
            return
        can_show = bool(enabled) and row.sweep_toggle.isEnabled() and not row.container.isHidden()
        row.start_edit.setVisible(can_show)
        row.end_edit.setVisible(can_show)
        row.steps_edit.setVisible(can_show)
        row.start_edit.setEnabled(can_show)
        row.end_edit.setEnabled(can_show)
        row.steps_edit.setEnabled(can_show)
        if can_show:
            _is_set, current_value = self._current_state(row)
            base = _as_float(current_value)
            if base is not None:
                if not row.start_edit.text().strip():
                    row.start_edit.setText(str(base))
                if not row.end_edit.text().strip():
                    row.end_edit.setText(str(base))
            if not row.steps_edit.text().strip():
                row.steps_edit.setText("3")
        self.changed.emit()

    def selected_params_payload(self) -> Dict[str, Optional[float]]:
        payload: Dict[str, Any] = {}
        for key, row in self._rows.items():
            if row.container.isHidden():
                continue
            is_set, value = self._current_state(row)
            payload[key] = value if is_set else None
        return payload

    def sweeps_payload(self) -> Dict[str, Dict[str, Any]]:
        payload: Dict[str, Dict[str, Any]] = {}
        for key, row in self._rows.items():
            if row.container.isHidden() or row.sweep_toggle.isHidden() or not row.sweep_toggle.isChecked():
                continue
            payload[key] = {
                "start": _to_float(row.start_edit.text()),
                "end": _to_float(row.end_edit.text()),
                "steps": _to_int(row.steps_edit.text()),
                "spacing": "linear",
            }
        return payload

    def set_selected_params(self, payload: Dict[str, Any]) -> None:
        raw = dict(payload or {})
        for key, row in self._rows.items():
            self._set_editor_value(row, raw.get(key))

    def set_sweeps(self, payload: Dict[str, Any]) -> None:
        raw = dict(payload or {})
        for key, row in self._rows.items():
            spec = raw.get(key)
            if not isinstance(spec, dict):
                row.sweep_toggle.setChecked(False)
                row.start_edit.setText("")
                row.end_edit.setText("")
                row.steps_edit.setText("3")
                continue
            row.sweep_toggle.setChecked(True)
            row.start_edit.setText("" if spec.get("start") is None else str(spec.get("start")))
            row.end_edit.setText("" if spec.get("end") is None else str(spec.get("end")))
            steps = spec.get("steps", 3)
            row.steps_edit.setText("" if steps is None else str(steps))

    def set_from_batch(self, batch: Any) -> None:
        selected_payload: Dict[str, Any] = {}
        for key, selection in dict(getattr(batch, "selected_params", {}) or {}).items():
            if isinstance(selection, dict):
                selected_payload[str(key)] = selection.get("value")
                continue
            selected_payload[str(key)] = getattr(selection, "value", selection)
        self.set_selected_params(selected_payload)

        sweeps_payload: Dict[str, Any] = {}
        for key, spec in dict(getattr(batch, "sweeps", {}) or {}).items():
            if isinstance(spec, dict):
                sweeps_payload[str(key)] = dict(spec)
                continue
            sweeps_payload[str(key)] = {
                "start": getattr(spec, "start", None),
                "end": getattr(spec, "end", None),
                "steps": getattr(spec, "steps", None),
                "spacing": getattr(spec, "spacing", "linear"),
            }
        self.set_sweeps(sweeps_payload)

    def editor_for_key(self, key: str) -> Optional[QLineEdit]:
        row = self._rows.get(str(key))
        if row is None:
            return None
        editor = row.base_editor
        if isinstance(editor, ScalarFieldEditor):
            value_widget = editor.value_widget()
            if hasattr(value_widget, "edit"):
                return value_widget.edit  # type: ignore[attr-defined]
        return None

    def field_label_map(self) -> Dict[str, str]:
        return {key: row.label for key, row in self._rows.items()}

    def sweep_toggle_for_key(self, key: str) -> Optional[QCheckBox]:
        row = self._rows.get(str(key))
        return None if row is None else row.sweep_toggle

    def sweep_panel_for_key(self, key: str) -> Optional[QWidget]:
        row = self._rows.get(str(key))
        if row is None:
            return None
        return row.start_edit

    def sweep_inputs_for_key(self, key: str) -> Optional[Dict[str, QLineEdit]]:
        row = self._rows.get(str(key))
        if row is None:
            return None
        return {
            "start": row.start_edit,
            "end": row.end_edit,
            "steps": row.steps_edit,
        }

    def visible_field_keys(self) -> List[str]:
        return [key for key, row in self._rows.items() if not row.container.isHidden()]

    def active_sweep_count(self) -> int:
        return sum(
            1
            for row in self._rows.values()
            if not row.container.isHidden() and not row.sweep_toggle.isHidden() and row.sweep_toggle.isChecked()
        )
