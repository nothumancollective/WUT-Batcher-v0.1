"""Batch parameter form for variable ATH parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ui.form_builder import AccordionGroupBox
from ui.form_schema import FieldSpec, FormSchema, build_project_form_schema

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QDoubleValidator
    from PySide6.QtWidgets import (
        QFrame,
        QFormLayout,
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


@dataclass
class _FieldRow:
    key: str
    label: str
    group_path: Tuple[str, ...]
    container: QWidget
    input_edit: QLineEdit


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
            row_layout = QHBoxLayout(row_wrap)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)

            value_edit = QLineEdit()
            value_edit.setPlaceholderText("base value")
            value_edit.setClearButtonEnabled(True)
            value_edit.setMaximumWidth(220)
            value_edit.setValidator(QDoubleValidator(value_edit))
            if spec.tooltip:
                value_edit.setToolTip(spec.tooltip)
            value_edit.textChanged.connect(self.changed.emit)

            row_layout.addWidget(value_edit, 0, Qt.AlignLeft)
            row_layout.addStretch(1)

            box.body_layout().addRow(f"{spec.label} ({key})", row_wrap)
            self._rows[key] = _FieldRow(
                key=key,
                label=str(spec.label),
                group_path=group_key,
                container=row_wrap,
                input_edit=value_edit,
            )

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
            row.container.setVisible(is_visible)
            row.input_edit.setEnabled(is_visible and not is_locked)

        for group_key, box in self._group_boxes.items():
            any_visible = any(
                self._rows[key].container.isVisible()
                for key, row in self._rows.items()
                if tuple(row.group_path) == tuple(group_key)
            )
            box.setVisible(any_visible)

    def selected_params_payload(self) -> Dict[str, Optional[float]]:
        payload: Dict[str, Optional[float]] = {}
        for key, row in self._rows.items():
            if not row.container.isVisible():
                continue
            payload[key] = _to_float(row.input_edit.text())
        return payload

    def set_selected_params(self, payload: Dict[str, Any]) -> None:
        raw = dict(payload or {})
        for key, row in self._rows.items():
            if key not in raw:
                row.input_edit.setText("")
                continue
            value = raw.get(key)
            if value is None:
                row.input_edit.setText("")
            else:
                row.input_edit.setText(str(value))

    def editor_for_key(self, key: str) -> Optional[QLineEdit]:
        row = self._rows.get(str(key))
        if row is None:
            return None
        return row.input_edit

    def field_label_map(self) -> Dict[str, str]:
        return {key: row.label for key, row in self._rows.items()}
