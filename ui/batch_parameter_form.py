"""Batch parameter form for variable ATH parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ui.form_builder import AccordionGroupBox
from ui.form_schema import FieldSpec, FormSchema, build_project_form_schema

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QDoubleValidator, QIntValidator
    from PySide6.QtWidgets import (
        QCheckBox,
        QFrame,
        QFormLayout,
        QHBoxLayout,
        QLineEdit,
        QScrollArea,
        QToolButton,
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


@dataclass
class _FieldRow:
    key: str
    label: str
    group_path: Tuple[str, ...]
    container: QWidget
    base_edit: QLineEdit
    sweep_toggle: QCheckBox
    sweep_panel: QWidget
    start_edit: QLineEdit
    end_edit: QLineEdit
    steps_edit: QLineEdit
    spacing_button: QToolButton


class BatchParameterForm(QWidget):
    changed = Signal()

    def __init__(self, schema: Optional[FormSchema] = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.schema = schema or build_project_form_schema()
        self._rows: Dict[str, _FieldRow] = {}
        self._group_boxes: Dict[Tuple[str, ...], AccordionGroupBox] = {}
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

    def _field_sort_key(self, spec: FieldSpec) -> Tuple[str, str, int, str]:
        group = tuple(spec.group_path[:2] or ("Other",))
        top = str(group[0]) if len(group) >= 1 else "Other"
        sub = str(group[1]) if len(group) >= 2 else "General"
        return (top, sub, int(spec.order), spec.key)

    def _group_title(self, group_path: Sequence[str]) -> str:
        group = tuple(group_path[:2] or ("Other",))
        if len(group) >= 2:
            return str(group[1])
        if group:
            return str(group[0])
        return "General"

    def _build(self) -> None:
        ordered_fields = sorted(self.schema.fields, key=self._field_sort_key)
        for spec in ordered_fields:
            key = str(spec.key)
            group_key = tuple(spec.group_path[:2] or ("Other",))
            box = self._group_boxes.get(group_key)
            if box is None:
                box = AccordionGroupBox(self._group_title(group_key))
                box.set_collapsed(False)
                self._group_boxes[group_key] = box
                self.content_layout.addWidget(box)

            row_wrap = QWidget()
            row_layout = QVBoxLayout(row_wrap)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(4)

            head = QWidget()
            head_layout = QHBoxLayout(head)
            head_layout.setContentsMargins(0, 0, 0, 0)
            head_layout.setSpacing(8)

            value_edit = QLineEdit()
            value_edit.setPlaceholderText("base")
            value_edit.setClearButtonEnabled(True)
            value_edit.setMaximumWidth(220)
            value_edit.setValidator(QDoubleValidator(value_edit))
            if spec.tooltip:
                value_edit.setToolTip(spec.tooltip)
            value_edit.textChanged.connect(self.changed.emit)
            head_layout.addWidget(value_edit, 0, Qt.AlignLeft)

            sweep_toggle = QCheckBox("Sweep")
            head_layout.addWidget(sweep_toggle, 0, Qt.AlignLeft)
            head_layout.addStretch(1)
            row_layout.addWidget(head)

            sweep_panel = QWidget()
            sweep_layout = QHBoxLayout(sweep_panel)
            sweep_layout.setContentsMargins(18, 0, 0, 0)
            sweep_layout.setSpacing(6)

            start_edit = QLineEdit()
            start_edit.setPlaceholderText("start")
            start_edit.setMaximumWidth(120)
            start_edit.setValidator(QDoubleValidator(start_edit))
            start_edit.textChanged.connect(self.changed.emit)
            sweep_layout.addWidget(start_edit, 0, Qt.AlignLeft)

            end_edit = QLineEdit()
            end_edit.setPlaceholderText("end")
            end_edit.setMaximumWidth(120)
            end_edit.setValidator(QDoubleValidator(end_edit))
            end_edit.textChanged.connect(self.changed.emit)
            sweep_layout.addWidget(end_edit, 0, Qt.AlignLeft)

            steps_edit = QLineEdit("3")
            steps_edit.setPlaceholderText("steps")
            steps_edit.setMaximumWidth(80)
            steps_edit.setValidator(QIntValidator(1, 9999, steps_edit))
            steps_edit.textChanged.connect(self.changed.emit)
            sweep_layout.addWidget(steps_edit, 0, Qt.AlignLeft)

            spacing_button = QToolButton()
            spacing_button.setText("linear")
            spacing_button.setEnabled(False)
            spacing_button.setToolTip("Spacing selection comes in a later iteration.")
            sweep_layout.addWidget(spacing_button, 0, Qt.AlignLeft)
            sweep_layout.addStretch(1)
            sweep_panel.setVisible(False)
            row_layout.addWidget(sweep_panel)

            box.body_layout().addRow(f"{spec.label} ({key})", row_wrap)
            row = _FieldRow(
                key=key,
                label=str(spec.label),
                group_path=group_key,
                container=row_wrap,
                base_edit=value_edit,
                sweep_toggle=sweep_toggle,
                sweep_panel=sweep_panel,
                start_edit=start_edit,
                end_edit=end_edit,
                steps_edit=steps_edit,
                spacing_button=spacing_button,
            )
            self._rows[key] = row
            sweep_toggle.toggled.connect(lambda enabled, row_key=key: self._on_sweep_toggled(row_key, enabled))

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
            can_sweep = key in self._sweepable_keys and not is_locked
            row.container.setVisible(is_visible)
            row.base_edit.setEnabled(is_visible and not is_locked)
            row.sweep_toggle.setEnabled(is_visible and can_sweep)
            if not row.sweep_toggle.isEnabled():
                row.sweep_toggle.setChecked(False)
            row.sweep_panel.setVisible(is_visible and row.sweep_toggle.isChecked())
            row.start_edit.setEnabled(is_visible and can_sweep)
            row.end_edit.setEnabled(is_visible and can_sweep)
            row.steps_edit.setEnabled(is_visible and can_sweep)

        for group_key, box in self._group_boxes.items():
            any_visible = any(
                self._rows[key].container.isVisible()
                for key, row in self._rows.items()
                if tuple(row.group_path) == tuple(group_key)
            )
            box.setVisible(any_visible)

    def _on_sweep_toggled(self, key: str, enabled: bool) -> None:
        row = self._rows.get(str(key))
        if row is None:
            return
        row.sweep_panel.setVisible(bool(enabled) and row.container.isVisible())
        if enabled:
            base = _to_float(row.base_edit.text())
            if base is not None:
                if not row.start_edit.text().strip():
                    row.start_edit.setText(str(base))
                if not row.end_edit.text().strip():
                    row.end_edit.setText(str(base))
            if not row.steps_edit.text().strip():
                row.steps_edit.setText("3")
        self.changed.emit()

    def selected_params_payload(self) -> Dict[str, Optional[float]]:
        payload: Dict[str, Optional[float]] = {}
        for key, row in self._rows.items():
            if not row.container.isVisible():
                continue
            payload[key] = _to_float(row.base_edit.text())
        return payload

    def sweeps_payload(self) -> Dict[str, Dict[str, Any]]:
        payload: Dict[str, Dict[str, Any]] = {}
        for key, row in self._rows.items():
            if not row.container.isVisible() or not row.sweep_toggle.isChecked():
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
            if key not in raw:
                row.base_edit.setText("")
                continue
            value = raw.get(key)
            if value is None:
                row.base_edit.setText("")
            else:
                row.base_edit.setText(str(value))

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
            start = spec.get("start")
            end = spec.get("end")
            steps = spec.get("steps", 3)
            row.start_edit.setText("" if start is None else str(start))
            row.end_edit.setText("" if end is None else str(end))
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
        return row.base_edit

    def field_label_map(self) -> Dict[str, str]:
        return {key: row.label for key, row in self._rows.items()}

    def sweep_toggle_for_key(self, key: str) -> Optional[QCheckBox]:
        row = self._rows.get(str(key))
        return None if row is None else row.sweep_toggle

    def sweep_panel_for_key(self, key: str) -> Optional[QWidget]:
        row = self._rows.get(str(key))
        return None if row is None else row.sweep_panel

    def visible_field_keys(self) -> List[str]:
        return [key for key, row in self._rows.items() if row.container.isVisible()]

    def active_sweep_count(self) -> int:
        return sum(
            1
            for row in self._rows.values()
            if row.container.isVisible() and row.sweep_toggle.isChecked()
        )
