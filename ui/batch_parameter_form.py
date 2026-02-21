"""Batch parameter form for variable ATH parameters."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ui.form_builder import (
    AccordionGroupBox,
    ElidedFixedLabel,
    NullableCodeEditorInput,
    NullableListTableInput,
    NullableVector4Input,
    ObjectFieldEditor,
    ScalarFieldEditor,
    SegmentedEnumInput,
)
from ui.form_metrics import FORM_METRICS
from ui.form_schema import FieldSpec, FormSchema, ModeStackSpec, build_project_form_schema, field_display_priority

try:
    from PySide6.QtCore import QPoint, Qt, QTimer, Signal
    from PySide6.QtGui import QDoubleValidator, QIntValidator
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QSizePolicy,
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


def _enum_numeric_options(field: FieldSpec) -> List[int]:
    values: List[int] = []
    for item in list(field.enum_options or []):
        raw = getattr(item, "value", None)
        if raw is None:
            continue
        try:
            values.append(int(float(raw)))
        except Exception:
            continue
    return sorted(set(values))


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
        root.setSpacing(4)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(max(18, int(FORM_METRICS.column_gap) - 2))
        grid.setVerticalSpacing(2)
        left_slot = True
        row_cursor = 0
        for row_index, property_field in enumerate(list(field.object_properties)):
            label = QLabel(str(property_field.label))
            label.setFixedWidth(max(130, int(FORM_METRICS.label_width) - 30))
            editor = ScalarFieldEditor(property_field)
            editor.changed.connect(self.changed.emit)
            editor.set_is_set(False)
            if left_slot:
                grid.addWidget(label, row_cursor, 0, 1, 1, Qt.AlignVCenter)
                grid.addWidget(editor, row_cursor, 1, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
                left_slot = False
            else:
                grid.addWidget(label, row_cursor, 3, 1, 1, Qt.AlignVCenter)
                grid.addWidget(editor, row_cursor, 4, 1, 1, Qt.AlignLeft | Qt.AlignVCenter)
                row_cursor += 1
                left_slot = True
            self.property_editors[property_field.key] = editor
        if not left_slot:
            row_cursor += 1
        grid.setColumnMinimumWidth(2, max(14, int(FORM_METRICS.column_gap) - 4))
        root.addLayout(grid)

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
    sweep_popup: QWidget
    helper_label: QLabel
    button_layout: bool
    sweep_capable: bool


@dataclass
class _SubgroupHeader:
    group_name: str
    subgroup_name: str
    label: QLabel
    keys: set[str]


@dataclass(frozen=True)
class _FormGridSpec:
    label_width: int
    button_label_width: int
    compact_editor_width: int
    row_right_margin: int
    row_spacing: int


class _ResponsiveFieldGrid(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: List[Tuple[str, QWidget, int]] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(max(34, int(FORM_METRICS.column_gap) + 14))
        self._grid.setVerticalSpacing(max(8, int(FORM_METRICS.row_gap) + 1))
        self._min_three_width = 1500

    def add_cell(self, widget: QWidget) -> None:
        self._items.append(("cell", widget, 1))
        self._relayout()

    def add_full_width(self, widget: QWidget) -> None:
        self._items.append(("full", widget, 1))
        self._relayout()

    def add_gap(self, *, min_cols: int = 3) -> None:
        spacer = QWidget(self)
        spacer.setObjectName("BatchGridGapCell")
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._items.append(("gap", spacer, max(1, int(min_cols))))
        self._relayout()

    def remove_widget(self, widget: QWidget) -> None:
        target_id = id(widget)
        self._items = [(kind, item, min_cols) for kind, item, min_cols in self._items if id(item) != target_id]
        self._relayout()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self)
        if not self._items:
            return
        cols = 3 if int(self.width()) >= int(self._min_three_width) else 2
        row = 0
        col = 0
        for kind, widget, min_cols in self._items:
            if kind == "gap" and cols < int(min_cols):
                continue
            if kind == "full":
                if col != 0:
                    row += 1
                    col = 0
                self._grid.addWidget(widget, row, 0, 1, cols)
                row += 1
                continue
            self._grid.addWidget(widget, row, col)
            col += 1
            if col >= cols:
                row += 1
                col = 0
        for index in range(max(cols, 1)):
            self._grid.setColumnStretch(index, 1)


class _SweepPopover(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("SweepPopover")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(6)
        title = QLabel("Sweep range")
        title.setObjectName("IssuesPanelGroupTitle")
        root.addWidget(title)
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(6)
        self._grid.setVerticalSpacing(4)
        root.addLayout(self._grid)

    def bind_inputs(self, *, start: QLineEdit, end: QLineEdit, steps: QLineEdit) -> None:
        start_label = QLabel("start")
        end_label = QLabel("end")
        steps_label = QLabel("steps")
        for widget in (start, end, steps):
            widget.setMinimumHeight(int(FORM_METRICS.control_height))
            widget.setFixedWidth(max(88, int(FORM_METRICS.input_width // 2)))
        self._grid.addWidget(start_label, 0, 0)
        self._grid.addWidget(end_label, 0, 1)
        self._grid.addWidget(steps_label, 0, 2)
        self._grid.addWidget(start, 1, 0)
        self._grid.addWidget(end, 1, 1)
        self._grid.addWidget(steps, 1, 2)

    def open_for(self, anchor: QWidget) -> None:
        self.adjustSize()
        pos = anchor.mapToGlobal(QPoint(0, anchor.height() + 6))
        self.move(pos)
        self.show()
        self.raise_()


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
        self._manual_highlight_widgets: List[QWidget] = []
        self._manual_hint_restore: Dict[int, str] = {}
        self._compat_ui_state: Dict[str, Any] = {}
        self._blocked_keys: set[str] = set()
        self._hidden_ui_keys: set[str] = set()
        self._risk_targets_by_key: Dict[str, List[QWidget]] = {}
        self._risk_original_tooltips: Dict[int, str] = {}
        self._subgroup_headers: List[_SubgroupHeader] = []
        self._blink_tokens_by_key: Dict[str, int] = {}
        self._advanced_keys_by_group: Dict[str, set[str]] = {}
        self._group_grids: Dict[str, _ResponsiveFieldGrid] = {}
        self._policy_default_suggestions: Dict[str, Any] = {}
        self._latest_issues_by_key: Dict[str, List[Dict[str, Any]]] = {}
        self._detached_rows_host = QWidget(self)
        self._detached_rows_host.hide()
        self._detached_rows_layout = QVBoxLayout(self._detached_rows_host)
        self._detached_rows_layout.setContentsMargins(0, 0, 0, 0)
        self._detached_rows_layout.setSpacing(0)
        self._enclosure_box: Optional[AccordionGroupBox] = None
        self._enclosure_box_home: Optional[QVBoxLayout] = None
        self._mesh_advanced_button: Optional[QPushButton] = None
        self._mesh_advanced_row_keys: List[str] = []
        self._control_height = int(FORM_METRICS.control_height)
        self._default_form_grid_spec = _FormGridSpec(
            label_width=max(130, int(FORM_METRICS.label_width) - 26),
            button_label_width=max(124, int(FORM_METRICS.label_width) - 30),
            compact_editor_width=max(232, int(FORM_METRICS.editor_total_width) - 16),
            row_right_margin=6,
            row_spacing=1,
        )
        self._basics_form_grid_spec = _FormGridSpec(
            label_width=max(124, int(FORM_METRICS.label_width) - 30),
            button_label_width=max(124, int(FORM_METRICS.label_width) - 30),
            compact_editor_width=max(232, int(FORM_METRICS.editor_total_width) - 16),
            row_right_margin=6,
            row_spacing=1,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setObjectName("BatchVariableScroll")
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

    @classmethod
    def _supports_sweep(cls, field: FieldSpec) -> bool:
        key = str(field.key)
        if key.startswith("Mesh."):
            return False
        if key in {"Throat.Profile", "GCurve.Type", "Morph.TargetShape", "Mesh.Enclosure"}:
            return False
        if field.widget_kind in {"float", "int", "expr", "ex"}:
            return True
        return False

    def _make_base_editor(self, field: FieldSpec) -> QWidget:
        if field.widget_kind == "object":
            return ObjectFieldEditor(field, use_toggle=(field.key == "Mesh.Enclosure"))
        return ScalarFieldEditor(field)

    @staticmethod
    def _is_tall_scalar_editor(editor: QWidget) -> bool:
        if not isinstance(editor, ScalarFieldEditor):
            return False
        value_widget = editor.value_widget()
        return isinstance(value_widget, (NullableVector4Input, NullableListTableInput, NullableCodeEditorInput))

    def _sweep_control_size(self, base_editor: QWidget) -> tuple[int, int]:
        width = 0
        height = 0
        if isinstance(base_editor, ScalarFieldEditor):
            value_widget = base_editor.value_widget()
            width = int(value_widget.sizeHint().width() or value_widget.minimumSizeHint().width() or value_widget.width())
            height = int(value_widget.sizeHint().height() or value_widget.minimumSizeHint().height() or value_widget.height())
        if width <= 0:
            width = int(base_editor.sizeHint().width() or base_editor.minimumSizeHint().width() or 96)
        if height <= 0:
            height = int(base_editor.sizeHint().height() or base_editor.minimumSizeHint().height() or self._control_height)
        return (max(72, int(width)), max(self._control_height, int(height)))

    def _mode_label_map(self, stack: ModeStackSpec) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for page in list(stack.pages or []):
            if page.value is None:
                result["<unset>"] = str(page.label).strip() or "Default"
                continue
            result[str(page.value)] = str(page.label).strip() or str(page.value)
        return result

    @staticmethod
    def _field_sort_tuple(field: FieldSpec) -> tuple[int, int, str]:
        return (field_display_priority(str(field.key)), int(field.order), str(field.key))

    def _subgroup_for_field(self, field: FieldSpec, group_name: str) -> Tuple[int, str]:
        if field.key in self._mode_stacks:
            return (0, "Mode")

        if group_name == "Basics":
            key = str(field.key)
            if key == "Length":
                return (0, "Primary")
            if key in {"Throat.Diameter", "Throat.Angle", "Coverage.Angle"}:
                return (1, "Throat")
            if key in {"Throat.Ext.Length", "Throat.Ext.Angle"}:
                return (2, "Throat Extension")
            if key == "Slot.Length":
                return (3, "Slot")
            if key == "Rot":
                return (4, "Orientation")
            return (5, "General")

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
            key = str(field.key)
            if key in {"GCurve.Dist", "GCurve.Width", "GCurve.AspectRatio", "GCurve.Rot"}:
                return (1, "Common")
            if key == "GCurve.SE.n":
                return (2, "Superellipse")
            if key.startswith("GCurve.SF"):
                return (3, "Superformula")
            mode = _extract_mode_tag_value(field.ui_mode_tags, "GCurve.Type")
            if mode == "<unset>":
                return (4, "Coverage")
            return (4, "General")

        if group_name == "Morph":
            key = str(field.key)
            if key == "Morph.TargetShape":
                return (0, "Mode")
            if key in {"Morph.TargetWidth", "Morph.TargetHeight"}:
                return (1, "Target")
            if key in {"Morph.CornerRadius", "Morph.AllowShrinkage"}:
                return (2, "Shape")
            if key in {"Morph.FixedPart", "Morph.Rate"}:
                return (3, "Transition")
            return (4, "General")

        if group_name == "Mesh":
            key = str(field.key)
            if key in {"Mesh.Quadrants", "Mesh.RearShape"}:
                return (0, "Topology")
            if key in {"Mesh.ThroatResolution", "Mesh.MouthResolution"}:
                return (1, "Required")
            if key in {"Mesh.AngularSegments", "Mesh.LengthSegments", "Mesh.CornerSegments", "Mesh.ThroatSegments"}:
                return (2, "Segments")
            if key in {"Mesh.InterfaceResolution", "Mesh.SubdomainSlices", "Mesh.InterfaceOffset", "Mesh.InterfaceDraw"}:
                return (3, "Interfaces")
            if key in {"Mesh.ZMapPoints", "Mesh.WallThickness", "Mesh.RearResolution"}:
                return (4, "Advanced")
            return (5, "General")

        if group_name == "Enclosure":
            key = str(field.key)
            if key == "Mesh.Enclosure":
                return (0, "Cabinet")
            if key == "Mesh.InterfaceOffset":
                return (1, "Interfaces")
            return (2, "General")

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
            rows.sort(key=self._field_sort_tuple)

        for group_name in self._ordered_group_names(grouped):
            box = AccordionGroupBox(group_name)
            box.set_collapsed(True)
            if str(group_name) != "Enclosure":
                self._register_box(box)
            self._group_boxes[group_name] = box
            if str(group_name) == "Enclosure":
                self._detached_rows_layout.addWidget(box)
                self._enclosure_box = box
                self._enclosure_box_home = self._detached_rows_layout
            else:
                self.content_layout.addWidget(box)
            box.reset_requested.connect(
                lambda target_group=str(group_name): self.reset_overrides_in_block(target_group)
            )

            group_fields = list(grouped.get(group_name, []))
            self._advanced_keys_by_group[str(group_name)] = {
                str(field.key) for field in group_fields if bool(getattr(field, "advanced", False))
            }

            field_grid = _ResponsiveFieldGrid()
            box.body_layout().addWidget(field_grid)
            self._group_grids[str(group_name)] = field_grid

            last_subgroup = None
            ordered_fields = sorted(
                grouped.get(group_name, []),
                key=lambda field: (
                    self._subgroup_for_field(field, group_name)[0],
                    self._subgroup_for_field(field, group_name)[1],
                    field_display_priority(str(field.key)),
                    int(field.order),
                    str(field.key),
                ),
            )
            subgroup_keys: Dict[str, set[str]] = {}
            for field in ordered_fields:
                subgroup_name = self._subgroup_for_field(field, group_name)[1]
                if subgroup_name == "General":
                    continue
                subgroup_keys.setdefault(str(subgroup_name), set()).add(str(field.key))
            for field in ordered_fields:
                subgroup_order, subgroup_name = self._subgroup_for_field(field, group_name)
                _ = subgroup_order
                skip_subgroup_heading = (
                    (str(group_name) == "Throat Profile" and subgroup_name in {"Mode", "OS-SE", "R-OSSE", "Circular Arc"})
                    or (str(group_name) == "GCurve" and subgroup_name in {"Mode", "Superformula", "Superellipse"})
                    or (str(group_name) == "Mesh" and subgroup_name == "Advanced")
                )
                if subgroup_name != "General" and subgroup_name != last_subgroup and not skip_subgroup_heading:
                    subgroup_label = QLabel(subgroup_name)
                    subgroup_label.setObjectName("IssuesPanelGroupTitle")
                    field_grid.add_full_width(subgroup_label)
                    self._subgroup_headers.append(
                        _SubgroupHeader(
                            group_name=str(group_name),
                            subgroup_name=str(subgroup_name),
                            label=subgroup_label,
                            keys=set(subgroup_keys.get(str(subgroup_name), set())),
                        )
                    )
                    last_subgroup = subgroup_name
                if subgroup_name == "General":
                    last_subgroup = "General"
                if str(group_name) == "GCurve" and subgroup_name == "Superformula" and str(last_subgroup) == "Common":
                    field_grid.add_gap(min_cols=3)
                    last_subgroup = "Superformula"
                if str(field.key) == "R-OSSE" and str(field.widget_kind) == "object":
                    self._build_rosse_property_rows(field_grid, field, group_name)
                    continue
                self._build_row(field_grid, field, group_name)
            if str(group_name) == "Mesh":
                self._mesh_advanced_row_keys = sorted(
                    set(str(key) for key in list(self._advanced_keys_by_group.get("Mesh", set()))) | {"Mesh.InterfaceOffset"}
                )
                self._detach_mesh_advanced_rows(field_grid)
                advanced_wrap = QWidget()
                advanced_layout = QHBoxLayout(advanced_wrap)
                advanced_layout.setContentsMargins(0, 2, 0, 2)
                advanced_layout.setSpacing(0)
                advanced_layout.addStretch(1)
                self._mesh_advanced_button = QPushButton("Advanced")
                self._mesh_advanced_button.setObjectName("StatusActionButton")
                self._mesh_advanced_button.setMinimumHeight(max(28, self._control_height))
                self._mesh_advanced_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                self._mesh_advanced_button.clicked.connect(self.open_mesh_advanced_dialog)
                advanced_layout.addWidget(self._mesh_advanced_button, 0, Qt.AlignRight)
                field_grid.add_full_width(advanced_wrap)
        self._detach_remaining_mesh_advanced_rows()
        self._update_group_reset_buttons()
        self._refresh_group_headers()
        self._refresh_visibility()

    def _build_row(self, grid: _ResponsiveFieldGrid, field: FieldSpec, group_name: str) -> None:
        key = str(field.key)
        display_label = str(field.label)
        if key in {"Throat.Profile", "GCurve.Type"}:
            display_label = "Mode"
        grid_spec = self._grid_spec_for_group(group_name)
        row_wrap = QWidget()
        row_wrap.setObjectName("BatchFieldCell")
        row_root = QVBoxLayout(row_wrap)
        row_root.setContentsMargins(0, 0, 0, 0)
        row_root.setSpacing(int(grid_spec.row_spacing))

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, int(grid_spec.row_right_margin), 0)
        row_layout.setSpacing(2)

        base_editor = self._make_base_editor(field)
        is_tall_control = self._is_tall_scalar_editor(base_editor)
        wide_button_row = self._is_button_layout(field) and self._segment_option_count(base_editor) >= 3
        if isinstance(base_editor, ScalarFieldEditor) and not is_tall_control and not wide_button_row:
            compact_width = int(grid_spec.compact_editor_width)
            base_editor.setFixedWidth(compact_width)
        if hasattr(base_editor, "changed"):
            base_editor.changed.connect(lambda *_ignored, row_key=key: self._on_field_edited(row_key))  # type: ignore[attr-defined]

        sweep_toggle = QPushButton("\u2195")
        sweep_toggle.setObjectName("SweepButton")
        sweep_toggle.setProperty("segment", "true")
        sweep_toggle.setCheckable(True)
        sweep_toggle.setFixedSize(int(FORM_METRICS.action_width), self._control_height)
        sweep_toggle.setToolTip("Sweep range")

        sweep_popup = _SweepPopover(self)
        start_edit = QLineEdit()
        start_edit.setPlaceholderText("start")
        start_edit.setValidator(QDoubleValidator(start_edit))
        start_edit.textChanged.connect(lambda _text, row_key=key: self._on_field_edited(row_key))

        end_edit = QLineEdit()
        end_edit.setPlaceholderText("end")
        end_edit.setValidator(QDoubleValidator(end_edit))
        end_edit.textChanged.connect(lambda _text, row_key=key: self._on_field_edited(row_key))

        steps_edit = QLineEdit("3")
        steps_edit.setPlaceholderText("steps")
        steps_edit.setValidator(QIntValidator(1, 9999, steps_edit))
        steps_edit.textChanged.connect(lambda _text, row_key=key: self._on_field_edited(row_key))
        sweep_popup.bind_inputs(start=start_edit, end=end_edit, steps=steps_edit)
        enum_options = _enum_numeric_options(field)
        if enum_options:
            start_edit.setValidator(QIntValidator(int(min(enum_options)), int(max(enum_options)), start_edit))
            end_edit.setValidator(QIntValidator(int(min(enum_options)), int(max(enum_options)), end_edit))

        if is_tall_control:
            row_wrap.setProperty("tallControl", "true")
            top_label = QLabel(display_label)
            top_label.setObjectName("ContextTitle")
            top_label.setToolTip(str(display_label or ""))
            row_root.addWidget(top_label, 0, Qt.AlignLeft)
            row_layout.addWidget(base_editor, 0, Qt.AlignLeft | Qt.AlignTop)
            if self._supports_sweep(field):
                row_layout.addWidget(sweep_toggle, 0, Qt.AlignLeft | Qt.AlignTop)
            else:
                sweep_toggle.setVisible(False)
        elif wide_button_row:
            row_wrap.setProperty("buttonRow", "true")
            label_width = int(grid_spec.button_label_width)
            label = ElidedFixedLabel(display_label, label_width)
            label.setMinimumHeight(self._control_height)
            row_layout.addWidget(label, 0, Qt.AlignVCenter)
            if hasattr(base_editor, "setSizePolicy"):
                base_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row_layout.addWidget(base_editor, 1, Qt.AlignLeft | Qt.AlignVCenter)
            sweep_toggle.setVisible(False)
        else:
            label_width = int(grid_spec.label_width)
            label = ElidedFixedLabel(display_label, label_width)
            label.setMinimumHeight(self._control_height)
            row_layout.addWidget(label, 0, Qt.AlignVCenter)
            row_layout.addWidget(base_editor, 0, Qt.AlignLeft | Qt.AlignVCenter)
            row_layout.addWidget(sweep_toggle, 0, Qt.AlignLeft | Qt.AlignVCenter)
        row_layout.addStretch(1)
        row_root.addWidget(row)

        helper = QLabel("")
        helper.setObjectName("FieldStateHint")
        helper.setProperty("severity", "info")
        helper.setVisible(False)
        helper.setWordWrap(True)
        row_root.addWidget(helper)

        if field.widget_kind == "object" or is_tall_control or wide_button_row:
            grid.add_full_width(row_wrap)
        else:
            grid.add_cell(row_wrap)
        row_data = _FieldRow(
            field=field,
            label=str(display_label),
            group_name=group_name,
            container=row_wrap,
            base_editor=base_editor,
            sweep_toggle=sweep_toggle,
            start_edit=start_edit,
            end_edit=end_edit,
            steps_edit=steps_edit,
            sweep_popup=sweep_popup,
            helper_label=helper,
            button_layout=self._is_button_layout(field),
            sweep_capable=self._supports_sweep(field),
        )
        self._rows[key] = row_data
        self._mark_batch_widget_tree(row_wrap)
        self._apply_segment_compact_mode(row_data)
        self._wire_row_blocked_interactions(key)
        sweep_toggle.clicked.connect(lambda checked, row_key=key: self._on_sweep_clicked(row_key, bool(checked)))
        sweep_toggle.toggled.connect(lambda enabled, row_key=key: self._on_sweep_toggled(row_key, enabled))

    def _build_rosse_property_rows(self, grid: _ResponsiveFieldGrid, field: FieldSpec, group_name: str) -> None:
        ui_mode_tags = tuple(field.ui_mode_tags) if field.ui_mode_tags else ("Throat.Profile=2",)
        properties = sorted(list(field.object_properties or ()), key=self._field_sort_tuple)
        for property_field in properties:
            synthetic = replace(property_field, ui_mode_tags=ui_mode_tags)
            self._build_row(grid, synthetic, group_name)

    def _grid_spec_for_group(self, group_name: str) -> _FormGridSpec:
        if str(group_name) == "Basics":
            return self._basics_form_grid_spec
        return self._default_form_grid_spec

    def _detach_mesh_advanced_rows(self, grid: _ResponsiveFieldGrid) -> None:
        detach_keys = [key for key in list(self._mesh_advanced_row_keys) if key in self._rows]
        if not detach_keys:
            return
        for key in detach_keys:
            row = self._rows.get(str(key))
            if row is None:
                continue
            grid.remove_widget(row.container)
            self._detached_rows_layout.addWidget(row.container)
            row.container.setProperty("meshAdvancedDetached", "true")

    def _detach_remaining_mesh_advanced_rows(self) -> None:
        for key in list(self._mesh_advanced_row_keys):
            row = self._rows.get(str(key))
            if row is None:
                continue
            if str(row.container.property("meshAdvancedDetached") or "false").lower() == "true":
                continue
            parent = row.container.parentWidget()
            if parent is not None and parent.layout() is not None:
                parent.layout().removeWidget(row.container)
            self._detached_rows_layout.addWidget(row.container)
            row.container.setProperty("meshAdvancedDetached", "true")

    @staticmethod
    def _move_widgets_to_layout(widgets: Sequence[QWidget], layout: QVBoxLayout) -> None:
        for widget in list(widgets):
            parent = widget.parentWidget()
            if parent is not None and parent.layout() is not None:
                parent.layout().removeWidget(widget)
            layout.addWidget(widget)

    def open_mesh_advanced_dialog(self) -> None:
        rows = [self._rows[key].container for key in list(self._mesh_advanced_row_keys) if key in self._rows]
        if not rows:
            return
        dialog = QDialog(self.window())
        dialog.setWindowTitle("Mesh Advanced")
        dialog.setModal(True)
        dialog.resize(980, 620)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        title = QLabel("Mesh Advanced")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        scroll = QScrollArea()
        scroll.setObjectName("BatchAdvancedScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(4)
        self._move_widgets_to_layout(rows, host_layout)
        host_layout.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("BatchSecondaryButton")
        close_btn.clicked.connect(dialog.accept)
        close_row = QHBoxLayout()
        close_row.setContentsMargins(0, 0, 0, 0)
        close_row.addStretch(1)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)
        dialog.exec()
        self._move_widgets_to_layout(rows, self._detached_rows_layout)

    def open_enclosure_dialog(self) -> None:
        box = self._enclosure_box
        home_layout = self._enclosure_box_home
        if box is None or home_layout is None:
            return
        dialog = QDialog(self.window())
        dialog.setWindowTitle("Simulate Enclosure")
        dialog.setModal(True)
        dialog.resize(960, 620)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)
        title = QLabel("Simulate Enclosure")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        body = QScrollArea()
        body.setObjectName("BatchAdvancedScroll")
        body.setWidgetResizable(True)
        body.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(0)
        if box.parentWidget() is not None and box.parentWidget().layout() is not None:
            box.parentWidget().layout().removeWidget(box)
        container_layout.addWidget(box)
        body.setWidget(container)
        root.addWidget(body, 1)
        close_btn = QPushButton("Close")
        close_btn.setObjectName("BatchSecondaryButton")
        close_btn.clicked.connect(dialog.accept)
        close_row = QHBoxLayout()
        close_row.setContentsMargins(0, 0, 0, 0)
        close_row.addStretch(1)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)
        dialog.exec()
        container_layout.removeWidget(box)
        home_layout.addWidget(box)

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

    def _clear_row_override(self, row: _FieldRow) -> bool:
        was_set, _value = self._current_state(row)
        changed = bool(was_set)
        editor = row.base_editor
        editor.blockSignals(True)
        try:
            if hasattr(editor, "set_is_set"):
                editor.set_is_set(False)  # type: ignore[attr-defined]
            elif hasattr(editor, "clear"):
                editor.clear()  # type: ignore[attr-defined]
        finally:
            editor.blockSignals(False)
        return changed

    def _group_has_overrides(self, group_name: str) -> bool:
        for row in self._rows.values():
            if str(row.group_name) != str(group_name):
                continue
            is_set, _value = self._current_state(row)
            if is_set:
                return True
        return False

    def _update_group_reset_buttons(self) -> None:
        for group_name, box in self._group_boxes.items():
            enabled = self._group_has_overrides(group_name)
            box.set_header_reset_available(bool(enabled))

    def reset_overrides_in_block(self, group_name: str) -> None:
        changed = False
        for row in self._rows.values():
            if str(row.group_name) != str(group_name):
                continue
            changed = self._clear_row_override(row) or changed
        self._update_group_reset_buttons()
        if changed:
            self.clear_manual_highlights()
            self.changed.emit()

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
            for attr in ("edit", "combo", "segment", "spin", "table"):
                maybe = getattr(value_widget, attr, None)
                if isinstance(maybe, QWidget):
                    targets.append(maybe)
                if attr == "spin" and hasattr(maybe, "lineEdit"):
                    line_edit = maybe.lineEdit()
                    if isinstance(line_edit, QWidget):
                        targets.append(line_edit)
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
            if hasattr(value_widget, "spin"):
                maybe = getattr(value_widget, "spin")
                if isinstance(maybe, QWidget):
                    targets.append(maybe)
                    if hasattr(maybe, "lineEdit"):
                        line_edit = maybe.lineEdit()
                        if isinstance(line_edit, QWidget):
                            targets.append(line_edit)
            if hasattr(value_widget, "table"):
                maybe = getattr(value_widget, "table")
                if isinstance(maybe, QWidget):
                    targets.append(maybe)
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

    def _list_widget_for_key(self, key: str) -> Optional[NullableListTableInput]:
        row = self._rows.get(str(key))
        if row is None:
            return None
        if not isinstance(row.base_editor, ScalarFieldEditor):
            return None
        value_widget = row.base_editor.value_widget()
        if isinstance(value_widget, NullableListTableInput):
            return value_widget
        return None

    def _sync_interface_list_lengths(self, changed_key: str) -> None:
        keys = ("Mesh.SubdomainSlices", "Mesh.InterfaceOffset", "Mesh.InterfaceDraw")
        trigger = str(changed_key or "").strip()
        if trigger not in keys:
            return
        widgets = {key: self._list_widget_for_key(key) for key in keys}
        lengths = [widget.entry_count() for widget in widgets.values() if widget is not None]
        if not lengths:
            return
        target = max(int(length) for length in lengths)
        if target <= 0:
            return
        for key, widget in widgets.items():
            if widget is None or key == trigger:
                continue
            widget.blockSignals(True)
            try:
                widget.set_entry_count(target)
            finally:
                widget.blockSignals(False)

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
        if trigger_key == "Mesh.Enclosure":
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

        if str(trigger.group_name) not in {"Throat Profile", "GCurve", "Morph"}:
            trigger.helper_label.setText(message)
            trigger.helper_label.setProperty("severity", "info")
            trigger.helper_label.setVisible(True)
            self._repolish(trigger.helper_label)

        for widget in self._iter_hint_targets(trigger):
            widget.setProperty("disclosureHint", "true")
            self._repolish(widget)
            self._hint_widgets.append(widget)

    def _on_group_advanced_toggled(self, group_name: str, enabled: bool) -> None:
        _ = (group_name, enabled)
        return

    def _on_sweep_clicked(self, key: str, checked: bool) -> None:
        if not checked:
            return
        row = self._rows.get(str(key))
        if row is None:
            return
        # Defer popup opening until after the click event completes; otherwise
        # Qt.Popup can immediately close due to the same mouse event.
        QTimer.singleShot(0, lambda r=row: self._open_sweep_popup(r))

    def _open_sweep_popup(self, row: _FieldRow) -> None:
        popup = row.sweep_popup
        if isinstance(popup, _SweepPopover):
            popup.open_for(row.sweep_toggle)

    def _on_field_edited(self, key: str) -> None:
        self.clear_manual_highlights()
        row = self._rows.get(str(key))
        if row is not None:
            self._last_changed_key = str(key)
            self._active_group_name = row.group_name
        self._sync_interface_list_lengths(str(key))
        self._update_group_reset_buttons()
        self._refresh_group_headers()
        self.changed.emit()

    @staticmethod
    def _risk_rank(value: str) -> int:
        order = {"fatal": 0, "warn": 1, "incomplete": 2, "ok": 3, "info": 4}
        return order.get(str(value).lower(), 99)

    def _field_is_set(self, key: str) -> bool:
        row = self._rows.get(str(key))
        if row is None:
            return False
        if str(row.container.property("compatVisible") or "false").lower() != "true":
            return False
        is_set, _value = self._current_state(row)
        return bool(is_set)

    def _risk_targets_for_key(self, key: str) -> List[QWidget]:
        cache = self._risk_targets_by_key.get(str(key))
        if cache is not None:
            return cache
        row = self._rows.get(str(key))
        if row is None:
            return []
        targets = self._iter_hint_targets(row)
        if not targets:
            targets = [row.base_editor]
        dedup = self._dedup_widgets(targets)
        self._risk_targets_by_key[str(key)] = dedup
        return dedup

    def _clear_ui_risks(self) -> None:
        for key in list(self._rows.keys()):
            row = self._rows.get(key)
            if row is None:
                continue
            if hasattr(row.base_editor, "set_field_state_visual"):
                row.base_editor.set_field_state_visual("neutral")  # type: ignore[attr-defined]
            for target in self._risk_targets_for_key(key):
                target.setProperty("fieldState", "neutral")
                target.setProperty("riskLevel", "")
                target_id = id(target)
                if target_id in self._risk_original_tooltips:
                    target.setToolTip(self._risk_original_tooltips[target_id])
                self._repolish(target)
            row.sweep_toggle.setProperty("riskLevel", "")
            sweep_id = id(row.sweep_toggle)
            if sweep_id in self._risk_original_tooltips:
                row.sweep_toggle.setToolTip(self._risk_original_tooltips[sweep_id])
            self._repolish(row.sweep_toggle)
        self._risk_original_tooltips.clear()

    @staticmethod
    def _risk_tooltip(issues: List[Dict[str, Any]]) -> str:
        lines: List[str] = []
        for item in list(issues or []):
            severity = str(item.get("severity", "")).strip().lower()
            marker = "Warning"
            if severity == "fatal":
                marker = "Error"
            elif severity == "incomplete":
                marker = "Incomplete"
            message = str(item.get("message", "")).strip()
            if not message:
                continue
            lines.append(f"{marker}: {message}")
        return "\n".join(lines[:8]).strip()

    def apply_ui_risks(self, issues: List[Dict[str, Any]]) -> None:
        self._clear_ui_risks()
        self._latest_issues_by_key = {}
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for issue in list(issues or []):
            if not isinstance(issue, Mapping):
                continue
            key = str(issue.get("field_key") or issue.get("key") or "").strip()
            if not key or key not in self._rows:
                continue
            grouped.setdefault(key, []).append(dict(issue))
            self._latest_issues_by_key.setdefault(key, []).append(dict(issue))

        for key, row_issues in grouped.items():
            if not row_issues:
                continue
            highest = min(
                (str(item.get("severity", "info")).lower() for item in row_issues),
                key=self._risk_rank,
            )
            if highest not in {"fatal", "warn", "incomplete", "ok"}:
                continue
            visual = "neutral" if highest == "incomplete" else highest
            row = self._rows.get(key)
            if row is None:
                continue
            if hasattr(row.base_editor, "set_field_state_visual"):
                row.base_editor.set_field_state_visual("ok" if highest == "incomplete" else highest)  # type: ignore[attr-defined]
            for target in self._risk_targets_for_key(key):
                target_id = id(target)
                self._risk_original_tooltips.setdefault(target_id, target.toolTip())
                target.setProperty("fieldState", visual)
                target.setProperty("riskLevel", visual)
                tooltip = self._risk_tooltip(row_issues)
                if tooltip:
                    base_tooltip = self._risk_original_tooltips.get(target_id, "")
                    target.setToolTip(f"{base_tooltip}\n\n{tooltip}".strip() if base_tooltip else tooltip)
                self._repolish(target)
            row.sweep_toggle.setProperty("riskLevel", "warn" if highest == "warn" else "")
            sweep_id = id(row.sweep_toggle)
            self._risk_original_tooltips.setdefault(sweep_id, row.sweep_toggle.toolTip())
            sweep_tip = self._risk_tooltip(row_issues)
            if sweep_tip:
                base_sweep_tip = self._risk_original_tooltips.get(sweep_id, "")
                row.sweep_toggle.setToolTip(
                    f"{base_sweep_tip}\n\n{sweep_tip}".strip() if base_sweep_tip else sweep_tip
                )
            self._repolish(row.sweep_toggle)
        self._refresh_group_headers()

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
        self._hidden_ui_keys = {
            str(item)
            for item in list(self._compat_ui_state.get("hidden_keys", []) or [])
            if str(item).strip()
        }
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

    def _clear_hidden_row_state(self, row: _FieldRow, key: str) -> bool:
        changed = False
        if row.sweep_popup.isVisible():
            row.sweep_popup.hide()
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
        self._blink_tokens_by_key[str(key)] = int(self._blink_tokens_by_key.get(str(key), 0)) + 1
        self._set_blink_state(row, False)
        return changed

    def _refresh_visibility(self) -> tuple[set[str], bool]:
        throat_mode = self._controller_value("Throat.Profile")
        gcurve_mode = self._controller_value("GCurve.Type")
        effective_visible: set[str] = set()
        changed_hidden = False
        group_has_compatible_rows: Dict[str, bool] = {}

        for key, row in self._rows.items():
            visible_ok = (not self._visible_keys) or (key in self._visible_keys)
            if key.startswith("R-OSSE.") and not visible_ok and "R-OSSE" in self._visible_keys:
                visible_ok = True
            allowed = bool(visible_ok and key not in self._project_fixed_keys)
            if key in self._hidden_ui_keys:
                allowed = False
            if key == "R-OSSE" or key.startswith("R-OSSE."):
                allowed = bool(allowed and throat_mode == 2)
            if allowed:
                group_has_compatible_rows[str(row.group_name)] = True
            advanced_keys = self._advanced_keys_by_group.get(str(row.group_name), set())
            group_name = str(row.group_name)
            if key.startswith("R-OSSE."):
                advanced_visible = bool(throat_mode == 2)
            elif key in set(self._mesh_advanced_row_keys):
                advanced_visible = False
            elif group_name == "Throat Profile" and key in advanced_keys:
                advanced_visible = bool(throat_mode == 2)
            elif group_name == "GCurve" and key in advanced_keys:
                advanced_visible = bool(gcurve_mode == 2)
            else:
                advanced_visible = True
            is_visible = bool(allowed and advanced_visible)
            rosse_parent_blocked = bool(key.startswith("R-OSSE.") and "R-OSSE" in self._blocked_keys)
            rosse_parent_locked = bool(key.startswith("R-OSSE.") and ("R-OSSE" in self._locked_keys or rosse_parent_blocked))
            is_locked = bool(key in self._locked_keys or key in self._blocked_keys or rosse_parent_locked)
            row.container.setVisible(is_visible)
            row.container.setProperty("rowVisible", "true" if is_visible else "false")
            row.container.setProperty("compatVisible", "true" if allowed else "false")
            is_blocked = bool(key in self._blocked_keys or rosse_parent_blocked)
            row.base_editor.setProperty("compatBlocked", "true" if is_blocked else "false")
            self._repolish(row.base_editor)
            sweepable = bool(key in self._sweepable_keys)
            if key.startswith("R-OSSE.") and not sweepable and "R-OSSE" in self._sweepable_keys:
                sweepable = True
            can_sweep = bool(allowed and row.sweep_capable and sweepable and (not is_locked))

            row.sweep_toggle.setVisible(bool(row.sweep_capable))
            row.sweep_toggle.setEnabled(can_sweep)
            row.sweep_toggle.setProperty("sweepActive", bool(row.sweep_toggle.isChecked() and can_sweep))
            self._repolish(row.sweep_toggle)
            if not can_sweep and row.sweep_toggle.isChecked():
                row.sweep_toggle.setChecked(False)

            sweep_active = bool(row.sweep_toggle.isChecked() and can_sweep)
            self._set_editor_locked(row, bool(is_locked or sweep_active))
            self._set_editor_sweep_visual(row, sweep_active)
            row.start_edit.setEnabled(can_sweep)
            row.end_edit.setEnabled(can_sweep)
            row.steps_edit.setEnabled(can_sweep)
            if (not is_visible) or (not can_sweep):
                row.sweep_popup.hide()

            if not bool(allowed):
                changed_hidden = self._clear_hidden_row_state(row, key) or changed_hidden
            if allowed and is_visible:
                effective_visible.add(key)

        for group_name, box in self._group_boxes.items():
            if str(group_name) == "Enclosure":
                box.setVisible(False)
                continue
            any_visible = any(
                (row.group_name == group_name)
                and (str(row.container.property("rowVisible") or "false").lower() == "true")
                for row in self._rows.values()
            )
            box.setVisible(bool(any_visible or group_has_compatible_rows.get(str(group_name), False)))
        for header in self._subgroup_headers:
            visible = any(
                (key in self._rows)
                and (str(self._rows[key].container.property("rowVisible") or "false").lower() == "true")
                for key in list(header.keys or set())
            )
            header.label.setVisible(bool(visible))

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
        self._update_group_reset_buttons()
        self._refresh_group_headers()
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
        row.start_edit.setEnabled(row.sweep_toggle.isEnabled())
        row.end_edit.setEnabled(row.sweep_toggle.isEnabled())
        row.steps_edit.setEnabled(row.sweep_toggle.isEnabled())
        row_locked = key in self._locked_keys
        self._set_editor_locked(row, bool(row_locked or can_show))
        self._set_editor_sweep_visual(row, can_show)
        if can_show:
            _is_set, current_value = self._current_state(row)
            base = _as_float(current_value)
            enum_values = _enum_numeric_options(row.field) if str(row.field.ath_type).strip().lower() == "enum" else []
            if base is not None:
                if not row.start_edit.text().strip():
                    if enum_values:
                        row.start_edit.setText(str(int(round(base))))
                    else:
                        row.start_edit.setText(str(base))
                if not row.end_edit.text().strip():
                    if enum_values:
                        row.end_edit.setText(str(int(round(base))))
                    else:
                        row.end_edit.setText(str(base))
            else:
                self._blink_base_editor(row, str(key))
            if not row.steps_edit.text().strip():
                row.steps_edit.setText("3")
        else:
            self._blink_tokens_by_key[str(key)] = int(self._blink_tokens_by_key.get(str(key), 0)) + 1
            self._set_blink_state(row, False)
            row.sweep_popup.hide()
        self.changed.emit()

    def _blink_base_editor(self, row: _FieldRow, key: str) -> None:
        token = int(self._blink_tokens_by_key.get(str(key), 0)) + 1
        self._blink_tokens_by_key[str(key)] = token
        targets = self._iter_hint_targets(row) or [row.base_editor]

        def _set(value: bool) -> None:
            if int(self._blink_tokens_by_key.get(str(key), 0)) != token:
                return
            blink_value = "true" if bool(value) else "false"
            for widget in targets:
                widget.setProperty("sweepNeedsBaseFlash", blink_value)  # type: ignore[arg-type]
                self._repolish(widget)

        QTimer.singleShot(0, lambda: _set(True))
        QTimer.singleShot(130, lambda: _set(False))
        QTimer.singleShot(260, lambda: _set(True))
        QTimer.singleShot(390, lambda: _set(False))

    def _set_blink_state(self, row: _FieldRow, active: bool) -> None:
        token = "true" if bool(active) else "false"
        for widget in self._iter_hint_targets(row) or [row.base_editor]:
            widget.setProperty("sweepNeedsBaseFlash", token)
            self._repolish(widget)

    def selected_params_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        rosse_payload: Dict[str, Any] = {}
        rosse_visible = False
        for key, row in self._rows.items():
            if str(row.container.property("compatVisible") or "false").lower() != "true":
                continue
            is_set, value = self._current_state(row)
            if key.startswith("R-OSSE."):
                rosse_visible = True
                if is_set:
                    rosse_payload[key.split(".", 1)[1]] = value
                continue
            payload[key] = value if is_set else None
        if rosse_visible:
            payload["R-OSSE"] = dict(rosse_payload) if rosse_payload else None
        return payload

    def sweeps_payload(self) -> Dict[str, Dict[str, Any]]:
        payload: Dict[str, Dict[str, Any]] = {}
        for key, row in self._rows.items():
            if str(row.container.property("compatVisible") or "false").lower() != "true":
                continue
            if row.sweep_toggle.isHidden() or not row.sweep_toggle.isChecked():
                continue
            start = _to_float(row.start_edit.text())
            end = _to_float(row.end_edit.text())
            steps = _to_int(row.steps_edit.text())
            if start is None or end is None or steps is None or int(steps) < 1:
                # Keep sweep UI active, but suppress invalid draft payloads until fields are complete.
                continue
            if str(row.field.ath_type).strip().lower() == "enum":
                start_i = int(round(start))
                end_i = int(round(end))
                enum_values = _enum_numeric_options(row.field)
                if enum_values and (start_i not in enum_values or end_i not in enum_values):
                    continue
                start = float(start_i)
                end = float(end_i)
            payload[key] = {
                "start": float(start),
                "end": float(end),
                "steps": int(steps),
                "spacing": "linear",
            }
        return payload

    def set_selected_params(self, payload: Dict[str, Any]) -> None:
        raw = dict(payload or {})
        rosse_value = raw.get("R-OSSE")
        if isinstance(rosse_value, Mapping):
            for sub_key, sub_value in dict(rosse_value).items():
                token = f"R-OSSE.{str(sub_key).strip()}"
                if token.strip(".") and token not in raw:
                    raw[token] = sub_value
        for key, row in self._rows.items():
            self._set_editor_value(row, raw.get(key))
        self._sync_interface_list_lengths("Mesh.SubdomainSlices")
        self._update_group_reset_buttons()
        self._refresh_group_headers()
        self.clear_manual_highlights()

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
        self._update_group_reset_buttons()
        self._refresh_group_headers()
        self.clear_manual_highlights()

    def _normalize_policy_key_for_row(self, key: str) -> str:
        token = str(key or "").strip()
        if not token:
            return ""
        if token.startswith("R-OSSE."):
            return token if token in self._rows else "R-OSSE"
        if token in {"R-OSSE", "Throat.Profile"}:
            return token
        return token

    def _row_for_policy_key(self, key: str) -> Optional[_FieldRow]:
        normalized = self._normalize_policy_key_for_row(str(key))
        if not normalized:
            return None
        row = self._rows.get(normalized)
        if row is not None:
            return row
        if "." in normalized:
            parent = normalized.rsplit(".", 1)[0]
            return self._rows.get(parent)
        return None

    def clear_manual_highlights(self) -> None:
        for widget in list(self._manual_highlight_widgets):
            restore_value = self._manual_hint_restore.get(id(widget), "false")
            widget.setProperty("disclosureHint", restore_value)
            self._repolish(widget)
        self._manual_highlight_widgets = []
        self._manual_hint_restore = {}
        for row in self._rows.values():
            if row.helper_label.isVisible() and "Use defaults" in str(row.helper_label.text() or ""):
                row.helper_label.setText("")
                row.helper_label.setVisible(False)
                self._repolish(row.helper_label)

    @staticmethod
    def _segment_option_count(editor: QWidget) -> int:
        if isinstance(editor, ScalarFieldEditor):
            value_widget = editor.value_widget()
            if isinstance(value_widget, SegmentedEnumInput):
                return len(list(getattr(value_widget, "_buttons", []) or []))
            maybe = getattr(value_widget, "segment", None)
            if isinstance(maybe, SegmentedEnumInput):
                return len(list(getattr(maybe, "_buttons", []) or []))
        if isinstance(editor, ObjectFieldEditor) and isinstance(editor.toggle, SegmentedEnumInput):
            return len(list(getattr(editor.toggle, "_buttons", []) or []))
        return 0

    def _apply_segment_compact_mode(self, row: _FieldRow) -> None:
        for segment in self._row_segments(row):
            buttons = [btn for btn in list(getattr(segment, "_buttons", []) or []) if isinstance(btn, QPushButton)]
            for button in buttons:
                button.setMinimumWidth(40)
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    @staticmethod
    def _mark_batch_widget_tree(root: QWidget) -> None:
        widgets = [root, *root.findChildren(QWidget)]
        for widget in widgets:
            widget.setProperty("batchField", "true")
            if isinstance(widget, QComboBox):
                widget.setObjectName("BatchFieldCombo")

    @staticmethod
    def _enum_label(mapping: Mapping[int, str], value: Any, fallback: str) -> str:
        try:
            token = int(float(value))
        except Exception:
            return fallback
        return str(mapping.get(token, fallback))

    def _field_value(self, key: str) -> tuple[bool, Any]:
        row = self._rows.get(str(key))
        if row is None:
            return (False, None)
        return self._current_state(row)

    def _chips_for_group(self, group_name: str) -> List[str]:
        chips: List[str] = []
        title = str(group_name).strip()
        if title == "Throat Profile":
            is_set, value = self._field_value("Throat.Profile")
            if is_set:
                chips.append(self._enum_label({1: "OS-SE", 2: "R-OSSE", 3: "Circular Arc"}, value, "unset"))
        elif title == "GCurve":
            is_set, value = self._field_value("GCurve.Type")
            if not is_set:
                chips.append("No GCurve")
            else:
                chips.append(self._enum_label({0: "No GCurve", 1: "Superellipse", 2: "Superformula"}, value, "No GCurve"))
        elif title == "Morph":
            is_set, value = self._field_value("Morph.TargetShape")
            target = value if is_set else 0
            chips.append(self._enum_label({0: "Original", 1: "Rectangle", 2: "Circle"}, target, "Original"))
        elif title == "Mesh":
            is_set, value = self._field_value("Mesh.Quadrants")
            if is_set and value is not None:
                chips.append(f"Quadrants={value}")
        elif title == "Enclosure":
            is_set, _value = self._field_value("Mesh.Enclosure")
            chips.append("enabled" if is_set else "disabled")
        elif title == "Basics":
            d_set, d_value = self._field_value("Throat.Diameter")
            l_set, l_value = self._field_value("Length")
            if d_set and d_value is not None:
                chips.append(f"Throat={d_value}")
            if l_set and l_value is not None:
                chips.append(f"Length={l_value}")
        return chips

    def _refresh_group_headers(self) -> None:
        for group_name, box in self._group_boxes.items():
            group_keys = [key for key, row in self._rows.items() if str(row.group_name) == str(group_name)]
            compatible_keys = [
                key
                for key in group_keys
                if str(self._rows[key].container.property("compatVisible") or "false").lower() == "true"
            ]
            active_count = sum(1 for key in compatible_keys if self._field_is_set(key))
            total_fields = len(compatible_keys)
            warn_count = 0
            fatal_count = 0
            incomplete_count = 0
            for key in compatible_keys:
                for issue in list(self._latest_issues_by_key.get(key, [])):
                    severity = str(issue.get("severity", "")).strip().lower()
                    if severity == "warn":
                        warn_count += 1
                    elif severity == "incomplete":
                        incomplete_count += 1
                    elif severity == "fatal":
                        if self._field_is_set(key):
                            fatal_count += 1
                        else:
                            incomplete_count += 1
            ok_count = active_count if (warn_count == 0 and fatal_count == 0 and incomplete_count == 0) else 0
            box.set_summary_chips(self._chips_for_group(str(group_name)))
            box.set_status_counts(
                ok_count=int(ok_count),
                warn_count=int(warn_count),
                fatal_count=int(fatal_count),
                incomplete_count=int(incomplete_count),
                active_count=int(active_count),
                total_fields=int(total_fields),
            )

    def highlight_policy_missing_keys(self, keys: Sequence[str]) -> List[str]:
        self.clear_manual_highlights()
        highlighted: List[str] = []
        for raw in list(keys or []):
            key = str(raw).strip()
            if not key:
                continue
            row = self._row_for_policy_key(key)
            if row is None or row.container.isHidden():
                continue
            targets = self._iter_hint_targets(row) or [row.base_editor]
            for widget in targets:
                widget_id = id(widget)
                if widget_id not in self._manual_hint_restore:
                    self._manual_hint_restore[widget_id] = str(widget.property("disclosureHint") or "false")
                widget.setProperty("disclosureHint", "true")
                self._repolish(widget)
                self._manual_highlight_widgets.append(widget)
            row.helper_label.setText("Use defaults available for run.")
            row.helper_label.setProperty("severity", "info")
            row.helper_label.setVisible(True)
            self._repolish(row.helper_label)
            normalized = self._normalize_policy_key_for_row(key)
            if normalized and normalized not in highlighted:
                highlighted.append(normalized)
        self._manual_highlight_widgets = self._dedup_widgets(self._manual_highlight_widgets)
        return highlighted

    def apply_default_values(self, defaults: Mapping[str, Any]) -> None:
        merged = dict(self.selected_params_payload() or {})
        for raw_key, raw_value in dict(defaults or {}).items():
            key = str(raw_key).strip()
            if not key:
                continue
            if key.startswith("R-OSSE."):
                obj = dict(merged.get("R-OSSE") or {})
                sub_key = key.split(".", 1)[1]
                if obj.get(sub_key) is None:
                    obj[sub_key] = raw_value
                merged["R-OSSE"] = obj
                continue
            if key.startswith("Mesh.Enclosure."):
                obj = dict(merged.get("Mesh.Enclosure") or {})
                sub_key = key.split(".", 2)[-1]
                if obj.get(sub_key) is None:
                    obj[sub_key] = raw_value
                merged["Mesh.Enclosure"] = obj
                continue
            if key == "R-OSSE" and isinstance(raw_value, Mapping):
                obj = dict(merged.get("R-OSSE") or {})
                for sub_key, sub_value in dict(raw_value).items():
                    if obj.get(str(sub_key)) is None:
                        obj[str(sub_key)] = sub_value
                merged["R-OSSE"] = obj
                continue
            if key == "Mesh.Enclosure" and isinstance(raw_value, Mapping):
                obj = dict(merged.get("Mesh.Enclosure") or {})
                for sub_key, sub_value in dict(raw_value).items():
                    if obj.get(str(sub_key)) is None:
                        obj[str(sub_key)] = sub_value
                merged["Mesh.Enclosure"] = obj
                continue
            if merged.get(key) is None:
                merged[key] = raw_value
        self.set_selected_params(merged)

    @staticmethod
    def _flatten_policy_default_values(defaults: Mapping[str, Any]) -> Dict[str, Any]:
        flat: Dict[str, Any] = {}
        for raw_key, raw_value in dict(defaults or {}).items():
            key = str(raw_key).strip()
            if not key:
                continue
            if key in {"R-OSSE", "Mesh.Enclosure"} and isinstance(raw_value, Mapping):
                for sub_key, sub_value in dict(raw_value).items():
                    token = f"{key}.{str(sub_key).strip()}"
                    if token.strip("."):
                        flat[token] = sub_value
                continue
            flat[key] = raw_value
        return flat

    def _apply_policy_default_suggestions(self) -> None:
        for key, row in self._rows.items():
            editor = row.base_editor
            if isinstance(editor, ScalarFieldEditor):
                if key in self._policy_default_suggestions:
                    editor.set_policy_suggested_default(self._policy_default_suggestions[key], source="policy_minimal")
                else:
                    editor.clear_policy_suggested_default()
                continue
            property_editors = getattr(editor, "property_editors", None)
            if not isinstance(property_editors, dict):
                continue
            for property_key, property_editor in property_editors.items():
                if not isinstance(property_editor, ScalarFieldEditor):
                    continue
                p_key = str(property_key)
                if p_key in self._policy_default_suggestions:
                    property_editor.set_policy_suggested_default(
                        self._policy_default_suggestions[p_key],
                        source="policy_minimal",
                    )
                else:
                    property_editor.clear_policy_suggested_default()

    def set_policy_default_suggestions(self, defaults: Mapping[str, Any]) -> None:
        self._policy_default_suggestions = self._flatten_policy_default_values(defaults)
        self._apply_policy_default_suggestions()

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

    def value_widget_for_key(self, key: str) -> Optional[QWidget]:
        row = self._rows.get(str(key))
        if row is None:
            return None
        if isinstance(row.base_editor, ScalarFieldEditor):
            return row.base_editor.value_widget()
        return row.base_editor

    def field_label_map(self) -> Dict[str, str]:
        return {key: row.label for key, row in self._rows.items()}

    def sweep_toggle_for_key(self, key: str) -> Optional[QPushButton]:
        row = self._rows.get(str(key))
        return None if row is None else row.sweep_toggle

    def sweep_panel_for_key(self, key: str) -> Optional[QWidget]:
        row = self._rows.get(str(key))
        if row is None:
            return None
        return row.sweep_popup

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

    def block_reset_button_for_group(self, group_name: str) -> Optional[QPushButton]:
        box = self._group_boxes.get(str(group_name))
        if box is None:
            return None
        header = box.header_row()
        buttons = header.findChildren(QPushButton, "AccordionHeaderResetButton")
        return buttons[0] if buttons else None

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
