"""Qt form builder for metadata-driven ATH parameter editing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ui.form_schema import FieldSpec, FormSchema, ModeStackSpec, build_project_form_schema

try:
    from PySide6.QtCore import QRegularExpression, Qt, Signal
    from PySide6.QtGui import QRegularExpressionValidator
    from PySide6.QtWidgets import (
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QStackedWidget,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for form builder.") from exc


INPUT_TOTAL_WIDTH = 220
UNIT_LABEL_WIDTH = 44
INPUT_COLUMN_WIDTH = 280


@dataclass(frozen=True)
class FieldState:
    is_set: bool
    value: Any


class TriStateOptionalCheckBox(QCheckBox):
    """Cycles through unset -> true -> false -> unset."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTristate(True)
        self.setCheckState(Qt.PartiallyChecked)

    def nextCheckState(self) -> None:  # type: ignore[override]
        state = self.checkState()
        if state == Qt.PartiallyChecked:
            self.setCheckState(Qt.Checked)
            return
        if state == Qt.Checked:
            self.setCheckState(Qt.Unchecked)
            return
        self.setCheckState(Qt.PartiallyChecked)


class CollapsibleSection(QWidget):
    def __init__(self, title: str, *, expanded: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(expanded)
        self.toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        root.addWidget(self.toggle, alignment=Qt.AlignLeft)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(10)
        self.content.setVisible(expanded)
        root.addWidget(self.content)

        self.toggle.toggled.connect(self._on_toggled)

    def _on_toggled(self, checked: bool) -> None:
        self.toggle.setArrowType(Qt.DownArrow if checked else Qt.RightArrow)
        self.content.setVisible(checked)


class NullableNumericInput(QWidget):
    changed = Signal()

    def __init__(
        self,
        *,
        is_float: bool,
        decimals: int,
        minimum: Optional[float],
        maximum: Optional[float],
        unit: Optional[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_float = bool(is_float)
        self._decimals = int(decimals if is_float else 0)
        self._minimum = minimum
        self._maximum = maximum

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.setFixedWidth(INPUT_TOTAL_WIDTH)

        self.edit = QLineEdit()
        self.edit.setObjectName("NullableInput")
        self.edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.edit.setFixedWidth(INPUT_TOTAL_WIDTH)
        self.edit.setPlaceholderText("optional")
        self.edit.setClearButtonEnabled(True)
        root.addWidget(self.edit, 0, Qt.AlignLeft)

        self.unit_label: Optional[QLabel] = None
        if unit:
            self.unit_label = QLabel(str(unit))
            self.unit_label.setObjectName("InputUnit")
            self.unit_label.setFixedWidth(UNIT_LABEL_WIDTH)
            self.edit.setFixedWidth(INPUT_TOTAL_WIDTH - UNIT_LABEL_WIDTH - 6)
            root.addWidget(self.unit_label, 0, Qt.AlignLeft)
        self._install_validator()
        self.edit.textChanged.connect(lambda *_: self.changed.emit())

    def _install_validator(self) -> None:
        if self._is_float:
            regex = QRegularExpression(rf"^-?\\d*(?:[.,]\\d{{0,{max(self._decimals, 0)}}})?$")
        else:
            regex = QRegularExpression(r"^-?\\d*$")
        self.edit.setValidator(QRegularExpressionValidator(regex, self.edit))

    def decimals(self) -> int:
        return self._decimals if self._is_float else 0

    def is_set(self) -> bool:
        return bool(self.edit.text().strip())

    def clear(self) -> None:
        self.edit.clear()

    def value(self) -> Optional[float | int]:
        if not self.is_set():
            return None
        normalized = self.edit.text().strip().replace(",", ".")
        if not normalized:
            return None
        try:
            parsed: float | int
            if self._is_float:
                parsed = float(normalized)
            else:
                parsed = int(normalized)
        except ValueError:
            return None
        if self._minimum is not None and float(parsed) < float(self._minimum):
            return None
        if self._maximum is not None and float(parsed) > float(self._maximum):
            return None
        return parsed

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        if self._is_float:
            try:
                number = float(value)
            except (TypeError, ValueError):
                self.clear()
                return
            text = f"{number:.{self._decimals}f}".rstrip("0").rstrip(".")
            self.edit.setText(text if text else "0")
            return
        try:
            number_i = int(float(value))
        except (TypeError, ValueError):
            self.clear()
            return
        self.edit.setText(str(number_i))

    def set_locked(self, locked: bool) -> None:
        self.edit.setEnabled(not locked)
        if self.unit_label is not None:
            self.unit_label.setEnabled(not locked)


class NullableTextInput(QWidget):
    changed = Signal()

    def __init__(
        self,
        *,
        placeholder: str = "",
        width: Optional[int] = None,
        value_parser: Optional[Callable[[str], Any]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value_parser = value_parser

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.edit = QLineEdit()
        self.edit.setClearButtonEnabled(True)
        self.setFixedWidth(int(width or INPUT_TOTAL_WIDTH))
        self.edit.setFixedWidth(int(width or INPUT_TOTAL_WIDTH))
        if placeholder:
            self.edit.setPlaceholderText(placeholder)
        root.addWidget(self.edit, 0, Qt.AlignLeft)

        self.edit.textChanged.connect(lambda *_: self.changed.emit())

    def is_set(self) -> bool:
        return bool(self.edit.text().strip())

    def clear(self) -> None:
        self.edit.clear()

    def value(self) -> Any:
        if not self.is_set():
            return None
        text = self.edit.text().strip()
        if self._value_parser is None:
            return text
        return self._value_parser(text)

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        if isinstance(value, list):
            self.edit.setText(",".join(str(item) for item in value))
            return
        self.edit.setText(str(value))

    def set_locked(self, locked: bool) -> None:
        self.edit.setEnabled(not locked)

class NullableBoolInput(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.checkbox = TriStateOptionalCheckBox()
        self.checkbox.setToolTip("Unset / On / Off")
        root.addWidget(self.checkbox, 0, Qt.AlignLeft)
        root.addStretch(1)

        self.checkbox.stateChanged.connect(lambda *_: self.changed.emit())

    def is_set(self) -> bool:
        return self.checkbox.checkState() != Qt.PartiallyChecked

    def clear(self) -> None:
        self.checkbox.setCheckState(Qt.PartiallyChecked)

    def value(self) -> Optional[bool]:
        if not self.is_set():
            return None
        return self.checkbox.checkState() == Qt.Checked

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        self.checkbox.setCheckState(Qt.Checked if bool(value) else Qt.Unchecked)

    def set_locked(self, locked: bool) -> None:
        self.checkbox.setEnabled(not locked)


class SegmentedEnumInput(QWidget):
    changed = Signal()

    def __init__(self, options: List[Tuple[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values_by_id: Dict[int, Any] = {}
        self._buttons: List[QPushButton] = []
        self._pressed_checked: Dict[int, bool] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        for index, (label, value) in enumerate(options):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("segment", "true")
            self.group.addButton(button, index)
            self._values_by_id[index] = value
            self._buttons.append(button)
            root.addWidget(button)
            button.pressed.connect(lambda idx=index: self._on_pressed(idx))
            button.clicked.connect(lambda checked, idx=index: self._on_clicked(idx, checked))
        root.addStretch(1)

    def _on_pressed(self, button_id: int) -> None:
        button = self.group.button(button_id)
        self._pressed_checked[button_id] = bool(button and button.isChecked())

    def _on_clicked(self, button_id: int, checked: bool) -> None:
        if self._pressed_checked.get(button_id, False) and checked:
            self.clear()
            return
        self.changed.emit()

    def clear(self, *, emit: bool = True) -> None:
        self.group.setExclusive(False)
        for button in self._buttons:
            button.setChecked(False)
        self.group.setExclusive(True)
        if emit:
            self.changed.emit()

    def is_set(self) -> bool:
        return self.group.checkedId() >= 0

    def value(self) -> Any:
        checked = self.group.checkedId()
        if checked < 0:
            return None
        return self._values_by_id.get(checked)

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear(emit=False)
            return
        for button_id, option_value in self._values_by_id.items():
            if option_value == value:
                button = self.group.button(button_id)
                if button is not None:
                    button.setChecked(True)
                return

    def set_locked(self, locked: bool) -> None:
        for button in self._buttons:
            button.setEnabled(not locked)


class NullableEnumComboInput(QWidget):
    changed = Signal()

    def __init__(self, options: List[Tuple[str, Any]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.setFixedWidth(INPUT_TOTAL_WIDTH)

        self.combo = QComboBox()
        self.combo.setFixedWidth(INPUT_TOTAL_WIDTH)
        self.combo.addItem("-", None)
        for label, value in options:
            self.combo.addItem(label, value)
        self.combo.setCurrentIndex(0)
        root.addWidget(self.combo, 0, Qt.AlignLeft)

        self.combo.currentIndexChanged.connect(lambda *_: self.changed.emit())

    def clear(self) -> None:
        self.combo.setCurrentIndex(0)

    def is_set(self) -> bool:
        return self.combo.currentData() is not None

    def value(self) -> Any:
        return self.combo.currentData() if self.is_set() else None

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        index = self.combo.findData(value)
        self.combo.setCurrentIndex(index if index >= 0 else 0)

    def set_locked(self, locked: bool) -> None:
        self.combo.setEnabled(not locked)


class ScalarFieldEditor(QWidget):
    changed = Signal()

    def __init__(self, field: FieldSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field
        self._value_widget: QWidget

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._value_widget = self._build_value_widget()
        root.addWidget(self._value_widget, 1)

        if field.tooltip:
            self.setToolTip(field.tooltip)
            self._value_widget.setToolTip(field.tooltip)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._wire_signals()

        if field.key == "Throat.Profile":
            self.set_value(1)
        else:
            self.set_is_set(False)

    def _wire_signals(self) -> None:
        if hasattr(self._value_widget, "changed"):
            self._value_widget.changed.connect(lambda *_: self.changed.emit())  # type: ignore[attr-defined]

    def _build_value_widget(self) -> QWidget:
        if self.field.key == "Rollback":
            return SegmentedEnumInput(options=[("disabled", 0), ("enabled", 1)])
        if self.field.widget_kind == "float":
            return NullableNumericInput(
                is_float=True,
                decimals=int(self.field.decimals or 2),
                minimum=self.field.minimum,
                maximum=self.field.maximum,
                unit=self.field.unit,
            )
        if self.field.widget_kind == "int":
            return NullableNumericInput(
                is_float=False,
                decimals=0,
                minimum=self.field.minimum,
                maximum=self.field.maximum,
                unit=self.field.unit,
            )
        if self.field.widget_kind == "bool":
            return NullableBoolInput()
        if self.field.widget_kind == "enum":
            options = [(option.label, option.value) for option in list(self.field.enum_options)]
            if 1 < len(options) <= 4:
                return SegmentedEnumInput(options=options)
            return NullableEnumComboInput(options=options)
        if self.field.widget_kind == "list":
            return NullableTextInput(placeholder="e.g. 1,2,3", width=INPUT_TOTAL_WIDTH, value_parser=self._parse_list)
        if self.field.widget_kind == "ex":
            return NullableTextInput(
                placeholder=self.field.placeholder or "e.g. 40 + 10*cos(p)^2",
                width=INPUT_TOTAL_WIDTH,
            )
        return NullableTextInput(placeholder="", width=INPUT_TOTAL_WIDTH)

    def _parse_list(self, text: str) -> List[Any]:
        if not text.strip():
            return []
        values: List[Any] = []
        for token in [item.strip() for item in text.replace(";", ",").split(",")]:
            if not token:
                continue
            normalized = token.replace(",", ".")
            try:
                if "int" in self.field.ath_type:
                    values.append(int(float(normalized)))
                else:
                    values.append(float(normalized))
            except ValueError:
                values.append(token)
        return values

    def value_widget(self) -> QWidget:
        return self._value_widget

    def is_set(self) -> bool:
        if not hasattr(self._value_widget, "is_set"):
            return False
        return bool(self._value_widget.is_set())  # type: ignore[attr-defined]

    def set_is_set(self, enabled: bool) -> None:
        if enabled:
            if not self.is_set() and self.field.default is not None:
                self.set_value(self.field.default)
            return
        if hasattr(self._value_widget, "clear"):
            self._value_widget.clear()  # type: ignore[attr-defined]

    def set_value(self, value: Any) -> None:
        if hasattr(self._value_widget, "set_value"):
            self._value_widget.set_value(value)  # type: ignore[attr-defined]

    def current_state(self) -> FieldState:
        if not self.is_set():
            return FieldState(is_set=False, value=None)
        if hasattr(self._value_widget, "value"):
            return FieldState(is_set=True, value=self._value_widget.value())  # type: ignore[attr-defined]
        return FieldState(is_set=False, value=None)

    def set_locked(self, locked: bool) -> None:
        if locked:
            self.setToolTip("Locked by runner mode.")
        if hasattr(self._value_widget, "set_locked"):
            self._value_widget.set_locked(locked)  # type: ignore[attr-defined]
        else:
            self._value_widget.setEnabled(not locked)

class ObjectFieldEditor(QWidget):
    changed = Signal()

    def __init__(self, field: FieldSpec, *, use_toggle: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field
        self._use_toggle = use_toggle
        self.property_editors: Dict[str, ScalarFieldEditor] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self.toggle: Optional[SegmentedEnumInput] = None
        if self._use_toggle:
            self.toggle = SegmentedEnumInput(options=[("disabled", 0), ("enabled", 1)])
            root.addWidget(self.toggle, alignment=Qt.AlignLeft)

        self.props_box = QGroupBox("Details")
        props_grid = QGridLayout(self.props_box)
        _configure_grid(props_grid)

        for index, property_field in enumerate(field.object_properties):
            label = QLabel(property_field.label)
            editor = ScalarFieldEditor(property_field)
            editor.changed.connect(self._on_child_changed)
            editor.set_is_set(False)
            row = index // 2
            col = index % 2
            base_col = col * 2
            props_grid.addWidget(label, row, base_col)
            props_grid.addWidget(editor, row, base_col + 1)
            self.property_editors[property_field.key] = editor

        root.addWidget(self.props_box)

        if field.tooltip:
            self.setToolTip(field.tooltip)
            self.props_box.setToolTip(field.tooltip)

        if self.toggle is not None:
            self.toggle.changed.connect(self._on_toggle_changed)
            self.toggle.set_value(0)
        self._apply_enabled_state()

    def _toggle_enabled(self) -> bool:
        if self.toggle is None:
            return True
        value = self.toggle.value()
        return bool(value == 1)

    def _on_toggle_changed(self) -> None:
        if not self._toggle_enabled():
            for editor in self.property_editors.values():
                editor.set_is_set(False)
        self._apply_enabled_state()
        self.changed.emit()

    def _on_child_changed(self) -> None:
        if self.toggle is not None and any(editor.is_set() for editor in self.property_editors.values()):
            if not self._toggle_enabled():
                self.toggle.set_value(1)
        self.changed.emit()

    def _apply_enabled_state(self) -> None:
        enabled = self._toggle_enabled()
        self.props_box.setVisible(enabled if self.toggle is not None else True)
        for editor in self.property_editors.values():
            editor.setEnabled(enabled)

    def is_set(self) -> bool:
        if self.toggle is not None:
            return self._toggle_enabled()
        return any(editor.is_set() for editor in self.property_editors.values())

    def set_is_set(self, enabled: bool) -> None:
        if self.toggle is not None:
            self.toggle.set_value(1 if enabled else 0)
            self._apply_enabled_state()
            if not enabled:
                for editor in self.property_editors.values():
                    editor.set_is_set(False)
            return
        if not enabled:
            for editor in self.property_editors.values():
                editor.set_is_set(False)

    def current_state(self) -> FieldState:
        if self.toggle is not None and not self._toggle_enabled():
            return FieldState(is_set=False, value=None)

        value: Dict[str, Any] = {}
        for property_key, editor in self.property_editors.items():
            state = editor.current_state()
            if not state.is_set:
                continue
            property_name = property_key.rsplit(".", 1)[-1]
            value[property_name] = state.value

        if self.toggle is None:
            if not value:
                return FieldState(is_set=False, value=None)
            return FieldState(is_set=True, value=value)
        return FieldState(is_set=True, value=value)

    def set_locked(self, locked: bool) -> None:
        if self.toggle is not None:
            self.toggle.set_locked(locked)
        for editor in self.property_editors.values():
            editor.set_locked(locked)
        if locked:
            self.setToolTip("Locked by runner mode.")


def _configure_grid(grid: QGridLayout) -> None:
    grid.setColumnStretch(1, 1)
    grid.setColumnStretch(3, 1)
    grid.setColumnMinimumWidth(1, INPUT_COLUMN_WIDTH)
    grid.setColumnMinimumWidth(3, INPUT_COLUMN_WIDTH)


class ParameterForm(QWidget):
    changed = Signal(dict)

    def __init__(self, schema: FormSchema | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.schema = schema or build_project_form_schema()
        self._field_specs = self.schema.by_key()
        self._field_editors: Dict[str, QWidget] = {}
        self._field_labels: Dict[str, QLabel] = {}
        self._mode_widgets: Dict[str, Tuple[QStackedWidget, Dict[Optional[int], int]]] = {}
        self._compat_state: Dict[str, Any] = {"visible_keys": [], "locked_keys": [], "issues": []}
        self._compat_visible_keys: set[str] = set()
        self._suspend_emit = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(12)

        self.geometry_scroll = QScrollArea()
        self.geometry_scroll.setWidgetResizable(True)
        self.mesh_scroll = QScrollArea()
        self.mesh_scroll.setWidgetResizable(True)
        root.addWidget(self.geometry_scroll, 1)
        root.addWidget(self.mesh_scroll, 1)

        geometry_container = QWidget()
        self.geometry_scroll.setWidget(geometry_container)
        geometry_layout = QVBoxLayout(geometry_container)
        geometry_layout.setContentsMargins(0, 0, 0, 0)
        geometry_layout.setSpacing(12)
        self.geometry_section = CollapsibleSection("Geometry", expanded=True)
        geometry_layout.addWidget(self.geometry_section)
        geometry_layout.addStretch(1)

        mesh_container = QWidget()
        self.mesh_scroll.setWidget(mesh_container)
        mesh_layout = QVBoxLayout(mesh_container)
        mesh_layout.setContentsMargins(0, 0, 0, 0)
        mesh_layout.setSpacing(12)
        self.mesh_section = CollapsibleSection("Mesh", expanded=True)
        mesh_layout.addWidget(self.mesh_section)
        mesh_layout.addStretch(1)

        self._build_sections()
        self._refresh_mode_stacks()
        self._apply_local_disclosure()
        self.changed.emit(self.payload())

    def _build_sections(self) -> None:
        mode_controller_keys = {stack.controller_key for stack in self.schema.mode_stacks}
        mode_detail_keys = {key for stack in self.schema.mode_stacks for page in stack.pages for key in page.field_keys}
        reserved_mode_keys = mode_controller_keys.union(mode_detail_keys)
        stacks_by_controller = {stack.controller_key: stack for stack in self.schema.mode_stacks}

        geometry_regular = [
            field
            for field in self.schema.fields
            if field.group_path[0] == "Geometry" and field.key not in reserved_mode_keys
        ]
        mesh_fields = [field for field in self.schema.fields if field.group_path[0] == "Mesh"]

        grouped_geometry = self._fields_by_group(geometry_regular)
        grouped_mesh = self._fields_by_group(mesh_fields)

        self._add_group_by_name(self.geometry_section.content_layout, grouped_geometry, "Basics")
        self._add_mode_group(self.geometry_section.content_layout, stacks_by_controller.get("Throat.Profile"))
        self._add_group_by_name(self.geometry_section.content_layout, grouped_geometry, "Morph")
        self._add_mode_group(self.geometry_section.content_layout, stacks_by_controller.get("GCurve.Type"))
        self._add_group_by_name(self.geometry_section.content_layout, grouped_geometry, "Rollback")

        self._add_group_by_name(self.mesh_section.content_layout, grouped_mesh, "Core")
        self._add_group_by_name(self.mesh_section.content_layout, grouped_mesh, "Enclosure")

    def _fields_by_group(self, fields: Iterable[FieldSpec]) -> Dict[str, List[FieldSpec]]:
        grouped: Dict[str, List[FieldSpec]] = {}
        for field in fields:
            group_name = field.group_path[1] if len(field.group_path) >= 2 else "General"
            grouped.setdefault(group_name, []).append(field)
        return grouped

    def _add_group_by_name(
        self,
        parent_layout: QVBoxLayout,
        grouped_fields: Dict[str, List[FieldSpec]],
        group_name: str,
    ) -> None:
        fields = list(grouped_fields.get(group_name, []))
        if not fields:
            return
        self._add_grouped_fields(parent_layout, fields, forced_group_name=group_name)

    def _add_mode_group(self, parent_layout: QVBoxLayout, stack: Optional[ModeStackSpec]) -> None:
        if stack is None:
            return
        self._add_mode_groups(parent_layout, [stack])

    def _add_grouped_fields(
        self,
        parent_layout: QVBoxLayout,
        fields: Iterable[FieldSpec],
        *,
        forced_group_name: Optional[str] = None,
    ) -> None:
        grouped: Dict[str, List[FieldSpec]] = {}
        if forced_group_name is not None:
            grouped[forced_group_name] = list(fields)
        else:
            grouped = self._fields_by_group(fields)

        for group_name, group_fields in grouped.items():
            box = QGroupBox(group_name)
            grid = QGridLayout(box)
            _configure_grid(grid)
            ordered = sorted(group_fields, key=lambda field: field.order)
            for index, field in enumerate(ordered):
                label = QLabel(field.label)
                editor = self._ensure_editor(field)
                row = index // 2
                col = index % 2
                base_col = col * 2
                grid.addWidget(label, row, base_col)
                grid.addWidget(editor, row, base_col + 1)
                self._field_labels[field.key] = label
            parent_layout.addWidget(box)

    def _add_mode_groups(self, parent_layout: QVBoxLayout, stacks: Iterable[ModeStackSpec]) -> None:
        for stack in stacks:
            controller = self._field_specs.get(stack.controller_key)
            if controller is None:
                continue

            box = QGroupBox(stack.label)
            box_layout = QVBoxLayout(box)

            controller_grid = QGridLayout()
            _configure_grid(controller_grid)
            controller_label = QLabel(controller.label)
            controller_editor = self._ensure_editor(controller)
            controller_grid.addWidget(controller_label, 0, 0)
            controller_grid.addWidget(controller_editor, 0, 1)
            self._field_labels[controller.key] = controller_label
            box_layout.addLayout(controller_grid)

            keyed_pages = [page for page in stack.pages if page.value is not None]
            common_keys: set[str] = set()
            if len(keyed_pages) >= 2:
                common_keys = set(keyed_pages[0].field_keys)
                for page in keyed_pages[1:]:
                    common_keys &= set(page.field_keys)

            if common_keys:
                common_box = QGroupBox("Common")
                common_grid = QGridLayout(common_box)
                _configure_grid(common_grid)
                for index, key in enumerate(sorted(common_keys)):
                    field = self._field_specs.get(key)
                    if field is None:
                        continue
                    label = QLabel(field.label)
                    editor = self._ensure_editor(field)
                    row = index // 2
                    col = index % 2
                    base_col = col * 2
                    common_grid.addWidget(label, row, base_col)
                    common_grid.addWidget(editor, row, base_col + 1)
                    self._field_labels[key] = label
                box_layout.addWidget(common_box)

            pages = QStackedWidget()
            index_by_value: Dict[Optional[int], int] = {}
            for page in stack.pages:
                page_widget = QWidget()
                page_grid = QGridLayout(page_widget)
                _configure_grid(page_grid)
                page_fields = [key for key in page.field_keys if key not in common_keys]
                page_grid.addWidget(QLabel(page.label), 0, 0, 1, 4)

                for row_index, key in enumerate(page_fields, start=1):
                    field = self._field_specs.get(key)
                    if field is None:
                        continue
                    label = QLabel(field.label)
                    editor = self._ensure_editor(field)
                    row = (row_index - 1) // 2 + 1
                    col = (row_index - 1) % 2
                    base_col = col * 2
                    page_grid.addWidget(label, row, base_col)
                    page_grid.addWidget(editor, row, base_col + 1)
                    self._field_labels[key] = label
                page_grid.setRowStretch(99, 1)
                page_index = pages.addWidget(page_widget)
                index_by_value[page.value] = page_index

            box_layout.addWidget(pages)
            self._mode_widgets[stack.controller_key] = (pages, index_by_value)
            parent_layout.addWidget(box)

    def _ensure_editor(self, field: FieldSpec) -> QWidget:
        existing = self._field_editors.get(field.key)
        if existing is not None:
            return existing

        if field.widget_kind == "object":
            editor: QWidget = ObjectFieldEditor(field, use_toggle=(field.key == "Mesh.Enclosure"))
        else:
            editor = ScalarFieldEditor(field)

        if hasattr(editor, "changed"):
            editor.changed.connect(self._on_any_field_changed)  # type: ignore[attr-defined]
        self._field_editors[field.key] = editor
        return editor

    def _controller_value(self, key: str) -> Optional[int]:
        editor = self._field_editors.get(key)
        if editor is None or not hasattr(editor, "current_state"):
            return None
        state = editor.current_state()  # type: ignore[attr-defined]
        if not state.is_set:
            return None
        try:
            return int(state.value)
        except (TypeError, ValueError):
            return None

    def _refresh_mode_stacks(self) -> None:
        for controller_key, (stacked, index_by_value) in self._mode_widgets.items():
            value = self._controller_value(controller_key)
            page_index = index_by_value.get(value)
            if page_index is None:
                page_index = index_by_value.get(None, 0)
            stacked.setCurrentIndex(page_index)

    def _sync_mode_side_effects(self) -> None:
        profile_value = self._controller_value("Throat.Profile")
        rosse_editor = self._field_editors.get("R-OSSE")
        if rosse_editor is None or not hasattr(rosse_editor, "set_is_set"):
            return
        if profile_value == 2:
            rosse_editor.set_is_set(True)  # type: ignore[attr-defined]
        else:
            rosse_editor.set_is_set(False)  # type: ignore[attr-defined]

    def _on_any_field_changed(self, *_: Any) -> None:
        if self._suspend_emit:
            return
        self._refresh_mode_stacks()
        self._sync_mode_side_effects()
        self._apply_local_disclosure()
        self.changed.emit(self.payload())

    def _rollback_enabled(self) -> bool:
        editor = self._field_editors.get("Rollback")
        if editor is None or not hasattr(editor, "current_state"):
            return False
        state = editor.current_state()  # type: ignore[attr-defined]
        if not state.is_set:
            return False
        value = state.value
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return int(value) != 0
        return str(value).strip().lower() in {"1", "true", "enabled", "on"}

    def _apply_local_disclosure(self) -> bool:
        changed = False
        rollback_enabled = self._rollback_enabled()
        rollback_detail_keys = ("Rollback.Angle", "Rollback.Exp", "Rollback.StartAt")

        for key in rollback_detail_keys:
            editor = self._field_editors.get(key)
            if editor is None:
                continue
            label = self._field_labels.get(key)
            compat_visible = key in self._compat_visible_keys if self._compat_visible_keys else True
            should_show = compat_visible and rollback_enabled
            if label is not None:
                label.setVisible(should_show)
            editor.setVisible(should_show)
            if not should_show and hasattr(editor, "set_is_set") and hasattr(editor, "current_state"):
                state = editor.current_state()  # type: ignore[attr-defined]
                if getattr(state, "is_set", False):
                    editor.set_is_set(False)  # type: ignore[attr-defined]
                    changed = True
        return changed

    def payload(self) -> Dict[str, Any]:
        fixed_params: Dict[str, Any] = {}
        limits: Dict[str, Any] = {}
        param_states: List[Dict[str, Any]] = []

        for field in self.schema.fields:
            editor = self._field_editors.get(field.key)
            if editor is None or not hasattr(editor, "current_state"):
                continue
            state: FieldState = editor.current_state()  # type: ignore[assignment]
            if editor.isHidden():
                state = FieldState(is_set=False, value=None)

            param_states.append(
                {
                    "param_name": field.key,
                    "is_set": 1 if state.is_set else 0,
                    "value": state.value if state.is_set else None,
                }
            )
            if not state.is_set:
                continue

            if field.key == "Throat.Profile" and state.value == 2:
                # Internal UI mode selector value; omit from rendered cfg parameter map.
                continue

            target = limits if field.scope == "limits" else fixed_params
            target[field.key] = state.value

        return {
            "fixed_params": fixed_params,
            "limits": limits,
            "param_states": param_states,
        }

    def apply_compatibility(self, state: Dict[str, Any]) -> None:
        self._compat_state = dict(state)
        visible_keys = set(str(item) for item in list(state.get("visible_keys", []) or []))
        locked_keys = set(str(item) for item in list(state.get("locked_keys", []) or []))
        self._compat_visible_keys = set(visible_keys)

        self._suspend_emit = True
        changed_hidden = False
        try:
            for key, editor in self._field_editors.items():
                is_visible = key in visible_keys
                label = self._field_labels.get(key)
                if label is not None:
                    label.setVisible(is_visible)
                if not is_visible and hasattr(editor, "set_is_set"):
                    should_clear = False
                    if hasattr(editor, "current_state"):
                        current_state = editor.current_state()  # type: ignore[attr-defined]
                        should_clear = bool(getattr(current_state, "is_set", False))
                    if should_clear:
                        editor.set_is_set(False)  # type: ignore[attr-defined]
                        changed_hidden = True
                editor.setVisible(is_visible)

                if hasattr(editor, "set_locked"):
                    editor.set_locked(key in locked_keys)  # type: ignore[attr-defined]
            changed_hidden = self._apply_local_disclosure() or changed_hidden
        finally:
            self._suspend_emit = False

        self._refresh_mode_stacks()
        if changed_hidden:
            self.changed.emit(self.payload())

    def value_widget_for_key(self, key: str) -> Optional[QWidget]:
        editor = self._field_editors.get(key)
        if editor is None:
            return None
        if hasattr(editor, "value_widget"):
            return editor.value_widget()  # type: ignore[attr-defined]
        return editor

    def editor_for_key(self, key: str) -> Optional[QWidget]:
        return self._field_editors.get(key)


class FormBuilder:
    """Constructs metadata-driven parameter forms from FieldSpec schema."""

    def __init__(self, schema: FormSchema | None = None) -> None:
        self.schema = schema or build_project_form_schema()

    def build(self, parent: QWidget | None = None) -> ParameterForm:
        return ParameterForm(schema=self.schema, parent=parent)
