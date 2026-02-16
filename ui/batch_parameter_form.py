"""Batch parameter form for variable ATH parameters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ui.form_builder import AccordionGroupBox, ContextFrame, ObjectFieldEditor, ScalarFieldEditor, SegmentedEnumInput
from ui.form_schema import FieldSpec, FormSchema, ModeStackSpec, build_project_form_schema

try:
    from PySide6.QtCore import Qt, QTimer, Signal
    from PySide6.QtGui import QDoubleValidator, QIntValidator
    from PySide6.QtWidgets import (
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
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


def _extract_mode_tag_value(ui_mode_tags: Sequence[str], controller_key: str) -> Optional[str]:
    prefix = f"{controller_key}="
    for raw in list(ui_mode_tags or []):
        value = str(raw).strip()
        if value.startswith(prefix):
            return value[len(prefix) :].strip()
    return None


class _SingleColumnObjectEditor(QWidget):
    changed = Signal()

    def __init__(self, field: FieldSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field
        self.property_editors: Dict[str, ScalarFieldEditor] = {}
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        frame = ContextFrame("Details")
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        for row_index, property_field in enumerate(list(field.object_properties)):
            label = QLabel(str(property_field.label))
            label.setMinimumWidth(120)
            editor = ScalarFieldEditor(property_field)
            editor.changed.connect(self.changed.emit)
            editor.set_is_set(False)
            grid.addWidget(label, row_index, 0, 1, 1, Qt.AlignVCenter)
            grid.addWidget(editor, row_index, 1, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
            self.property_editors[property_field.key] = editor
        frame.content_layout.addLayout(grid)
        root.addWidget(frame)

    def current_state(self) -> Any:
        value: Dict[str, Any] = {}
        for property_key, editor in self.property_editors.items():
            state = editor.current_state()
            if not bool(state.is_set):
                continue
            property_name = property_key.rsplit(".", 1)[-1]
            value[property_name] = state.value
        if not value:
            return type("State", (), {"is_set": False, "value": None})()
        return type("State", (), {"is_set": True, "value": value})()

    def set_is_set(self, enabled: bool) -> None:
        if enabled:
            return
        for editor in self.property_editors.values():
            editor.set_is_set(False)

    def set_locked(self, locked: bool) -> None:
        for editor in self.property_editors.values():
            editor.set_locked(locked)


@dataclass
class _FieldRow:
    field: FieldSpec
    label: str
    group_name: str
    container: QWidget
    base_editor: QWidget
    sweep_toggle: QPushButton
    start_edit: QLineEdit
    end_edit: QLineEdit
    steps_edit: QLineEdit
    helper_label: QLabel
    button_layout: bool


class BatchParameterForm(QWidget):
    changed = Signal()
    blocked_interaction = Signal(str, str, str)

    _GROUP_ORDER = ["Basics", "Throat Profile", "GCurve", "Morph", "Mesh", "Enclosure"]

    def __init__(self, schema: Optional[FormSchema] = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.schema = schema or build_project_form_schema()
        self._rows: Dict[str, _FieldRow] = {}
        self._group_boxes: Dict[str, AccordionGroupBox] = {}
        self._accordion_boxes: List[AccordionGroupBox] = []
        self._accordion_sync = False
        self._mode_stacks = {stack.controller_key: stack for stack in list(self.schema.mode_stacks or [])}
        self._controller_group_name = {
            stack.controller_key: (str(stack.label).strip() or str(stack.controller_key))
            for stack in list(self.schema.mode_stacks or [])
        }

        self._visible_keys: set[str] = set()
        self._locked_keys: set[str] = set()
        self._project_fixed_keys: set[str] = set()
        self._sweepable_keys: set[str] = set()
        self._active_group_name: Optional[str] = None
        self._last_changed_key: Optional[str] = None
        self._prev_visible_keys: set[str] = set()
        self._hint_widgets: List[QWidget] = []
        self._compat_ui_state: Dict[str, Any] = {}
        self._blocked_keys: set[str] = set()

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

    def _display_group_name(self, field: FieldSpec) -> str:
        if field.key in self._controller_group_name:
            return self._controller_group_name[field.key]
        if len(field.group_path) >= 2:
            name = str(field.group_path[1])
            return "Mesh" if name == "Core" else name
        if field.group_path:
            return str(field.group_path[0])
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
            if str(field.key).strip() == "R-OSSE":
                return _SingleColumnObjectEditor(field)
            return ObjectFieldEditor(field, use_toggle=(field.key == "Mesh.Enclosure"))
        return ScalarFieldEditor(field)

    def _mode_label_map(self, stack: ModeStackSpec) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for page in list(stack.pages or []):
            if page.value is None:
                result["<unset>"] = str(page.label).strip() or "Default"
                continue
            result[str(page.value)] = str(page.label).strip() or str(page.value)
        return result

    def _subgroup_for_field(self, field: FieldSpec, group_name: str) -> Tuple[int, str]:
        if field.key in self._mode_stacks:
            return (0, "Mode")

        if group_name == "Throat Profile":
            mode = _extract_mode_tag_value(field.ui_mode_tags, "Throat.Profile")
            if mode == "1":
                return (1, "OS-SE")
            if mode == "2":
                return (2, "R-OSSE")
            if mode == "3":
                return (3, "Circular Arc")
            return (4, "General")

        if group_name == "GCurve":
            mode = _extract_mode_tag_value(field.ui_mode_tags, "GCurve.Type")
            if mode == "1":
                return (1, "Superellipse")
            if mode == "2":
                return (2, "Superformula")
            if mode == "<unset>":
                return (3, "Coverage")
            return (4, "General")

        return (0, "General")

    def _ordered_group_names(self, grouped: Dict[str, List[FieldSpec]]) -> List[str]:
        ordered: List[str] = [name for name in self._GROUP_ORDER if name in grouped]
        rest = sorted(name for name in grouped.keys() if name not in ordered)
        ordered.extend(rest)
        return ordered

    def _register_box(self, box: AccordionGroupBox) -> None:
        self._accordion_boxes.append(box)
        box.toggled.connect(lambda expanded, current=box: self._on_group_toggled(current, expanded))

    def _on_group_toggled(self, current: AccordionGroupBox, expanded: bool) -> None:
        if self._accordion_sync:
            return
        if expanded:
            self._active_group_name = str(current.title())
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
            group_name = self._display_group_name(field)
            grouped.setdefault(group_name, []).append(field)
        for rows in grouped.values():
            rows.sort(key=lambda item: (int(item.order), str(item.key)))

        for group_name in self._ordered_group_names(grouped):
            box = AccordionGroupBox(group_name)
            box.set_collapsed(True)
            self._register_box(box)
            self._group_boxes[group_name] = box
            self.content_layout.addWidget(box)

            last_subgroup = None
            ordered_fields = sorted(
                grouped.get(group_name, []),
                key=lambda field: (
                    self._subgroup_for_field(field, group_name)[0],
                    self._subgroup_for_field(field, group_name)[1],
                    int(field.order),
                    str(field.key),
                ),
            )
            for field in ordered_fields:
                subgroup_order, subgroup_name = self._subgroup_for_field(field, group_name)
                _ = subgroup_order
                if subgroup_name != "General" and subgroup_name != last_subgroup:
                    subgroup_label = QLabel(subgroup_name)
                    subgroup_label.setObjectName("IssuesPanelGroupTitle")
                    box.body_layout().addWidget(subgroup_label)
                    last_subgroup = subgroup_name
                if subgroup_name == "General":
                    last_subgroup = "General"
                self._build_row(box, field, group_name)

    def _build_row(self, box: AccordionGroupBox, field: FieldSpec, group_name: str) -> None:
        key = str(field.key)
        row_wrap = QWidget()
        row_root = QVBoxLayout(row_wrap)
        row_root.setContentsMargins(0, 0, 0, 0)
        row_root.setSpacing(2)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        label = QLabel(str(field.label))
        label.setMinimumWidth(250)
        label.setWordWrap(False)
        label.setMinimumHeight(28)
        row_layout.addWidget(label, 0, Qt.AlignVCenter)

        base_editor = self._make_base_editor(field)
        if hasattr(base_editor, "changed"):
            base_editor.changed.connect(lambda *_ignored, row_key=key: self._on_field_edited(row_key))  # type: ignore[attr-defined]
        row_layout.addWidget(base_editor, 0, Qt.AlignLeft | Qt.AlignVCenter)

        sweep_toggle = QPushButton("Sweep")
        sweep_toggle.setProperty("segment", "true")
        sweep_toggle.setCheckable(True)
        sweep_toggle.setMinimumHeight(28)
        row_layout.addWidget(sweep_toggle, 0, Qt.AlignLeft | Qt.AlignVCenter)

        start_edit = QLineEdit()
        start_edit.setPlaceholderText("start")
        start_edit.setFixedHeight(28)
        start_edit.setMaximumWidth(96)
        start_edit.setValidator(QDoubleValidator(start_edit))
        start_edit.setVisible(False)
        start_edit.textChanged.connect(lambda _text, row_key=key: self._on_field_edited(row_key))
        row_layout.addWidget(start_edit, 0, Qt.AlignLeft | Qt.AlignVCenter)

        end_edit = QLineEdit()
        end_edit.setPlaceholderText("end")
        end_edit.setFixedHeight(28)
        end_edit.setMaximumWidth(96)
        end_edit.setValidator(QDoubleValidator(end_edit))
        end_edit.setVisible(False)
        end_edit.textChanged.connect(lambda _text, row_key=key: self._on_field_edited(row_key))
        row_layout.addWidget(end_edit, 0, Qt.AlignLeft | Qt.AlignVCenter)

        steps_edit = QLineEdit("3")
        steps_edit.setPlaceholderText("steps")
        steps_edit.setFixedHeight(28)
        steps_edit.setMaximumWidth(78)
        steps_edit.setValidator(QIntValidator(1, 9999, steps_edit))
        steps_edit.setVisible(False)
        steps_edit.textChanged.connect(lambda _text, row_key=key: self._on_field_edited(row_key))
        row_layout.addWidget(steps_edit, 0, Qt.AlignLeft | Qt.AlignVCenter)
        row_layout.addStretch(1)
        row_root.addWidget(row)

        helper = QLabel("")
        helper.setObjectName("FieldStateHint")
        helper.setProperty("severity", "info")
        helper.setVisible(False)
        helper.setWordWrap(True)
        row_root.addWidget(helper)

        box.body_layout().addWidget(row_wrap)
        row_data = _FieldRow(
            field=field,
            label=str(field.label),
            group_name=group_name,
            container=row_wrap,
            base_editor=base_editor,
            sweep_toggle=sweep_toggle,
            start_edit=start_edit,
            end_edit=end_edit,
            steps_edit=steps_edit,
            helper_label=helper,
            button_layout=self._is_button_layout(field),
        )
        self._rows[key] = row_data
        self._wire_row_blocked_interactions(key)
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
        self._active_group_name = str(visible_boxes[0].title())

    def _current_state(self, row: _FieldRow) -> tuple[bool, Any]:
        editor = row.base_editor
        if isinstance(editor, ScalarFieldEditor):
            state = editor.current_state()
            return (bool(state.is_set), state.value)
        if hasattr(editor, "current_state"):
            state = editor.current_state()  # type: ignore[attr-defined]
            return (bool(getattr(state, "is_set", False)), getattr(state, "value", None))
        if hasattr(editor, "is_set") and hasattr(editor, "value"):
            return (bool(editor.is_set()), editor.value())  # type: ignore[attr-defined]
        return (False, None)

    def _set_editor_value(self, row: _FieldRow, value: Any) -> None:
        editor = row.base_editor
        if isinstance(editor, ScalarFieldEditor):
            if value is None:
                editor.set_is_set(False)
            else:
                editor.set_value(value)
            return
        if isinstance(editor, ObjectFieldEditor):
            if value is None:
                editor.set_is_set(False)
                return
            if isinstance(value, dict):
                editor.set_is_set(True)
                for property_key, property_editor in editor.property_editors.items():
                    property_name = property_key.rsplit(".", 1)[-1]
                    property_value = value.get(property_name, value.get(property_key))
                    if property_value is None:
                        property_editor.set_is_set(False)
                    else:
                        property_editor.set_value(property_value)
                return
            editor.set_is_set(bool(value))
            return
        property_editors = getattr(editor, "property_editors", None)
        if isinstance(property_editors, dict):
            if value is None:
                if hasattr(editor, "set_is_set"):
                    editor.set_is_set(False)  # type: ignore[attr-defined]
                return
            if isinstance(value, dict):
                if hasattr(editor, "set_is_set"):
                    editor.set_is_set(True)  # type: ignore[attr-defined]
                for property_key, property_editor in property_editors.items():
                    property_name = str(property_key).rsplit(".", 1)[-1]
                    property_value = value.get(property_name, value.get(property_key))
                    if property_value is None:
                        property_editor.set_is_set(False)
                    else:
                        property_editor.set_value(property_value)
                return
            if hasattr(editor, "set_is_set"):
                editor.set_is_set(bool(value))  # type: ignore[attr-defined]
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

    def _set_editor_sweep_visual(self, row: _FieldRow, active: bool) -> None:
        targets: List[QWidget] = [row.base_editor]
        editor = row.base_editor
        if isinstance(editor, ScalarFieldEditor):
            value_widget = editor.value_widget()
            if isinstance(value_widget, QWidget):
                targets.append(value_widget)
            for attr in ("edit", "combo", "segment"):
                maybe = getattr(value_widget, attr, None)
                if isinstance(maybe, QWidget):
                    targets.append(maybe)
        for widget in self._dedup_widgets(targets):
            widget.setProperty("baseLockedBySweep", bool(active))
            self._repolish(widget)

    def _row_segments(self, row: _FieldRow) -> List[SegmentedEnumInput]:
        editor = row.base_editor
        segments: List[SegmentedEnumInput] = []
        if isinstance(editor, ScalarFieldEditor):
            value_widget = editor.value_widget()
            if isinstance(value_widget, SegmentedEnumInput):
                segments.append(value_widget)
            maybe = getattr(value_widget, "segment", None)
            if isinstance(maybe, SegmentedEnumInput):
                segments.append(maybe)
        if isinstance(editor, ObjectFieldEditor):
            if isinstance(editor.toggle, SegmentedEnumInput):
                segments.append(editor.toggle)
        dedup: List[SegmentedEnumInput] = []
        seen: set[int] = set()
        for segment in segments:
            seg_id = id(segment)
            if seg_id in seen:
                continue
            seen.add(seg_id)
            dedup.append(segment)
        return dedup

    def _wire_row_blocked_interactions(self, key: str) -> None:
        row = self._rows.get(str(key))
        if row is None:
            return
        for segment in self._row_segments(row):
            if bool(getattr(segment, "_blocked_signal_wired", False)):
                continue
            segment._blocked_signal_wired = True  # type: ignore[attr-defined]
            segment.blocked_interaction.connect(  # type: ignore[attr-defined]
                lambda value, cause_key, message, target_key=key: self.blocked_interaction.emit(
                    str(target_key),
                    str(cause_key or ""),
                    str(message or ""),
                )
            )

    @staticmethod
    def _dedup_widgets(widgets: Sequence[QWidget]) -> List[QWidget]:
        dedup: List[QWidget] = []
        seen: set[int] = set()
        for widget in list(widgets):
            widget_id = id(widget)
            if widget_id in seen:
                continue
            seen.add(widget_id)
            dedup.append(widget)
        return dedup

    @staticmethod
    def _segment_buttons(root: QWidget) -> List[QPushButton]:
        return [
            button
            for button in root.findChildren(QPushButton)
            if str(button.property("segment") or "").strip().lower() == "true"
        ]

    def _segment_hint_targets(self, segment: QWidget) -> List[QWidget]:
        buttons: List[QPushButton]
        if isinstance(segment, SegmentedEnumInput):
            buttons = [button for button in list(getattr(segment, "_buttons", []) or []) if isinstance(button, QPushButton)]
            checked = segment.group.checkedButton()
        else:
            buttons = self._segment_buttons(segment)
            checked = next((button for button in buttons if button.isChecked()), None)
        selected_buttons = [checked] if isinstance(checked, QPushButton) else buttons
        return self._dedup_widgets([segment, *selected_buttons])

    def _iter_hint_targets(self, row: _FieldRow) -> List[QWidget]:
        targets: List[QWidget] = []
        editor = row.base_editor
        if isinstance(editor, ScalarFieldEditor):
            value_widget = editor.value_widget()
            targets.append(editor)
            if isinstance(value_widget, QWidget):
                targets.append(value_widget)
            if hasattr(value_widget, "edit"):
                maybe = getattr(value_widget, "edit")
                if isinstance(maybe, QWidget):
                    targets.append(maybe)
            if hasattr(value_widget, "combo"):
                maybe = getattr(value_widget, "combo")
                if isinstance(maybe, QWidget):
                    targets.append(maybe)
            if hasattr(value_widget, "segment"):
                maybe = getattr(value_widget, "segment")
                if isinstance(maybe, QWidget):
                    targets.extend(self._segment_hint_targets(maybe))
        elif isinstance(editor, ObjectFieldEditor):
            targets.append(editor)
            if isinstance(editor.toggle, QWidget):
                targets.extend(self._segment_hint_targets(editor.toggle))
        else:
            targets.append(editor)
            if hasattr(editor, "segment"):
                maybe = getattr(editor, "segment")
                if isinstance(maybe, QWidget):
                    targets.extend(self._segment_hint_targets(maybe))
        return self._dedup_widgets(targets)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    def _clear_disclosure_hints(self) -> None:
        for widget in self._hint_widgets:
            widget.setProperty("disclosureHint", "false")
            self._repolish(widget)
        self._hint_widgets = []
        for row in self._rows.values():
            row.helper_label.setText("")
            row.helper_label.setVisible(False)
            row.helper_label.setProperty("severity", "info")
            self._repolish(row.helper_label)

    def _apply_disclosure_hint(self, previous_visible: set[str], current_visible: set[str]) -> None:
        self._clear_disclosure_hints()
        trigger_key = str(self._last_changed_key or "").strip()
        if not trigger_key:
            return
        trigger = self._rows.get(trigger_key)
        if trigger is None:
            return

        newly_hidden = [key for key in sorted(previous_visible) if key not in current_visible and key != trigger_key]
        hidden_rows = [self._rows[key] for key in newly_hidden if key in self._rows]
        if not hidden_rows:
            return

        groups = sorted({row.group_name for row in hidden_rows})
        params = [row.label for row in hidden_rows[:4]]
        extra_count = max(0, len(hidden_rows) - len(params))
        cards_text = ", ".join(groups[:3]) if groups else trigger.group_name
        params_text = ", ".join(params) if params else "-"
        if extra_count > 0:
            params_text = f"{params_text}, +{extra_count}"
        if groups == [trigger.group_name]:
            message = f"Diese Auswahl blendet in dieser Karte aus: Parameter [{params_text}]"
        else:
            message = f"Diese Auswahl blendet aus: Karten [{cards_text}] - Parameter [{params_text}]"

        trigger.helper_label.setText(message)
        trigger.helper_label.setProperty("severity", "info")
        trigger.helper_label.setVisible(True)
        self._repolish(trigger.helper_label)

        for widget in self._iter_hint_targets(trigger):
            widget.setProperty("disclosureHint", "true")
            self._repolish(widget)
            self._hint_widgets.append(widget)

    def _on_field_edited(self, key: str) -> None:
        row = self._rows.get(str(key))
        if row is not None:
            self._last_changed_key = str(key)
            self._active_group_name = row.group_name
        self.changed.emit()

    def set_project_fixed_keys(self, keys: Sequence[str]) -> None:
        self._project_fixed_keys = {str(item) for item in list(keys or []) if str(item).strip()}
        _current, changed_hidden = self._refresh_visibility()
        if changed_hidden:
            self.changed.emit()

    def apply_compatibility(self, state: Dict[str, Any]) -> None:
        previous = set(self._prev_visible_keys)
        self._visible_keys = {str(item) for item in list(state.get("visible_keys", []) or []) if str(item).strip()}
        self._locked_keys = {str(item) for item in list(state.get("locked_keys", []) or []) if str(item).strip()}
        self._sweepable_keys = {str(item) for item in list(state.get("sweepable_keys", []) or []) if str(item).strip()}
        self._compat_ui_state = dict(state.get("compat_ui_state", {}) or {})
        self._blocked_keys = {
            str(item)
            for item in list(self._compat_ui_state.get("blocked_keys", []) or [])
            if str(item).strip()
        }
        current, changed_hidden = self._refresh_visibility()
        self._apply_blocked_option_state()
        self._apply_disclosure_hint(previous, current)
        self._prev_visible_keys = set(current)
        if changed_hidden:
            self.changed.emit()

    def _controller_value(self, key: str) -> Optional[int]:
        row = self._rows.get(str(key))
        if row is None:
            return None
        is_set, value = self._current_state(row)
        if not is_set:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _clear_hidden_row_state(self, row: _FieldRow) -> bool:
        changed = False
        row.sweep_toggle.blockSignals(True)
        if row.sweep_toggle.isChecked():
            changed = True
        row.sweep_toggle.setChecked(False)
        row.sweep_toggle.blockSignals(False)
        for edit in (row.start_edit, row.end_edit, row.steps_edit):
            edit.blockSignals(True)
            if edit is row.steps_edit:
                changed = changed or str(edit.text()).strip() not in {"", "3"}
            else:
                changed = changed or bool(str(edit.text()).strip())
            if edit is row.steps_edit:
                edit.setText("3")
            else:
                edit.setText("")
            edit.blockSignals(False)
        editor = row.base_editor
        is_set = False
        if hasattr(editor, "current_state"):
            state = editor.current_state()  # type: ignore[attr-defined]
            is_set = bool(getattr(state, "is_set", False))
        changed = changed or is_set
        editor.blockSignals(True)
        if hasattr(editor, "set_is_set"):
            editor.set_is_set(False)  # type: ignore[attr-defined]
        elif hasattr(editor, "clear"):
            editor.clear()  # type: ignore[attr-defined]
        editor.blockSignals(False)
        return changed

    def _refresh_visibility(self) -> tuple[set[str], bool]:
        throat_mode = self._controller_value("Throat.Profile")
        effective_visible: set[str] = set()
        changed_hidden = False

        for key, row in self._rows.items():
            allowed = (not self._visible_keys or key in self._visible_keys) and key not in self._project_fixed_keys
            if key == "R-OSSE":
                allowed = bool(allowed and throat_mode == 2)
            is_visible = bool(allowed)
            is_locked = bool(key in self._locked_keys or key in self._blocked_keys)
            row.container.setVisible(is_visible)
            row.base_editor.setProperty("compatBlocked", "true" if key in self._blocked_keys else "false")
            self._repolish(row.base_editor)
            can_sweep = bool(allowed and (key in self._sweepable_keys) and (not is_locked) and (not row.button_layout))

            row.sweep_toggle.setVisible(not row.button_layout)
            row.sweep_toggle.setEnabled(can_sweep)
            row.sweep_toggle.setProperty("sweepActive", bool(row.sweep_toggle.isChecked() and can_sweep))
            self._repolish(row.sweep_toggle)
            if not can_sweep and row.sweep_toggle.isChecked():
                row.sweep_toggle.setChecked(False)

            show_sweep_inputs = bool(row.sweep_toggle.isChecked() and can_sweep)
            self._set_editor_locked(row, bool(is_locked or show_sweep_inputs))
            self._set_editor_sweep_visual(row, show_sweep_inputs)
            row.start_edit.setVisible(show_sweep_inputs)
            row.end_edit.setVisible(show_sweep_inputs)
            row.steps_edit.setVisible(show_sweep_inputs)
            row.start_edit.setEnabled(show_sweep_inputs)
            row.end_edit.setEnabled(show_sweep_inputs)
            row.steps_edit.setEnabled(show_sweep_inputs)

            if not is_visible:
                changed_hidden = self._clear_hidden_row_state(row) or changed_hidden
            if allowed and is_visible:
                effective_visible.add(key)

        for group_name, box in self._group_boxes.items():
            any_visible = any((row.group_name == group_name) and (not row.container.isHidden()) for row in self._rows.values())
            box.setVisible(any_visible)

        visible_boxes = [box for box in self._accordion_boxes if box.isVisible()]
        expanded = [box for box in visible_boxes if not box.is_collapsed()]
        if visible_boxes and not expanded:
            self._open_first_visible_group()
        elif len(expanded) > 1:
            keep = expanded[0]
            self._accordion_sync = True
            try:
                for box in expanded[1:]:
                    box.set_collapsed(True)
            finally:
                self._accordion_sync = False
            keep.set_collapsed(False)
        return effective_visible, changed_hidden

    def _apply_blocked_option_state(self) -> None:
        blocked_by_key = {
            str(key): dict(value)
            for key, value in dict(self._compat_ui_state.get("blocked_options", {}) or {}).items()
            if isinstance(value, dict)
        }
        for key, row in self._rows.items():
            blocked_options = blocked_by_key.get(str(key), {})
            for segment in self._row_segments(row):
                segment.set_blocked_option_map(blocked_options)

    def _on_sweep_toggled(self, key: str, enabled: bool) -> None:
        row = self._rows.get(str(key))
        if row is None:
            return
        self._last_changed_key = str(key)
        self._active_group_name = row.group_name
        can_show = bool(enabled and row.sweep_toggle.isEnabled() and not row.container.isHidden())
        row.sweep_toggle.setProperty("sweepActive", bool(can_show))
        self._repolish(row.sweep_toggle)
        row.start_edit.setVisible(can_show)
        row.end_edit.setVisible(can_show)
        row.steps_edit.setVisible(can_show)
        row.start_edit.setEnabled(can_show)
        row.end_edit.setEnabled(can_show)
        row.steps_edit.setEnabled(can_show)
        row_locked = key in self._locked_keys
        self._set_editor_locked(row, bool(row_locked or can_show))
        self._set_editor_sweep_visual(row, can_show)
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

    def selected_params_payload(self) -> Dict[str, Any]:
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

    def sweep_toggle_for_key(self, key: str) -> Optional[QPushButton]:
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

    def group_name_for_key(self, key: str) -> Optional[str]:
        row = self._rows.get(str(key))
        return None if row is None else row.group_name

    def last_changed_key(self) -> Optional[str]:
        value = str(self._last_changed_key or "").strip()
        return value or None

    def flash_cause_key(self, key: str) -> None:
        row = self._rows.get(str(key))
        if row is None:
            return
        targets = self._iter_hint_targets(row) or [row.base_editor]
        for widget in targets:
            widget.setProperty("compatCauseFlash", "true")
            self._repolish(widget)

        def _clear() -> None:
            for widget in targets:
                widget.setProperty("compatCauseFlash", "false")
                self._repolish(widget)

        QTimer.singleShot(460, _clear)
