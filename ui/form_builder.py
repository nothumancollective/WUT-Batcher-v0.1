"""Qt form builder for metadata-driven ATH parameter editing."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ui.form_metrics import FORM_METRICS, configure_single_column_grid, configure_two_column_grid
from ui.form_schema import FieldSpec, FormSchema, ModeStackSpec, build_project_form_schema, field_display_priority
from ui.text_utils import safe_text

try:
    from PySide6.QtCore import (
        QEasingCurve,
        QEvent,
        QObject,
        QPoint,
        QPropertyAnimation,
        QParallelAnimationGroup,
        QRegularExpression,
        QTimer,
        Qt,
        Signal,
    )
    from PySide6.QtGui import QFontDatabase, QGuiApplication, QRegularExpressionValidator
    from PySide6.QtWidgets import (
        QApplication,
        QAbstractItemView,
        QButtonGroup,
        QCheckBox,
        QComboBox,
        QFrame,
        QGraphicsOpacityEffect,
        QGridLayout,
        QGroupBox,
        QHeaderView,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSlider,
        QSpinBox,
        QSizePolicy,
        QStackedWidget,
        QTableWidget,
        QTableWidgetItem,
        QToolTip,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for form builder.") from exc


INPUT_TOTAL_WIDTH = FORM_METRICS.input_width
EDITOR_TOTAL_WIDTH = FORM_METRICS.editor_total_width
UNIT_LABEL_WIDTH = FORM_METRICS.unit_label_width
LABEL_COLUMN_WIDTH = FORM_METRICS.label_width
CONTROL_HEIGHT = FORM_METRICS.control_height
RESET_CONTROL_WIDTH = 28
STATE_BADGE_WIDTH = 14
_HELPER_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?")


def _format_default_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6g}"
    if isinstance(value, list):
        return ", ".join(_format_default_value(item) for item in value)
    if isinstance(value, tuple):
        return ", ".join(_format_default_value(item) for item in list(value))
    if isinstance(value, Mapping):
        return "{...}"
    return str(value)


@dataclass(frozen=True)
class FieldState:
    is_set: bool
    value: Any


class ContextFrame(QFrame):
    def __init__(self, title: Optional[str] = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ContextFrame")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 10)
        root.setSpacing(8)

        if title:
            heading = QLabel(title)
            heading.setObjectName("ContextTitle")
            root.addWidget(heading)

        self.content_layout = QVBoxLayout()
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        root.addLayout(self.content_layout)


class RiskHelperPopup(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setObjectName("RiskHelperPopup")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self._accent = QFrame()
        self._accent.setObjectName("RiskHelperPopupAccent")
        self._accent.setFixedWidth(3)
        self._accent.setProperty("severity", "neutral")
        row.addWidget(self._accent)
        content = QWidget()
        content.setObjectName("RiskHelperPopupBody")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 8, 10, 8)
        content_layout.setSpacing(0)
        self._label = QLabel("")
        self._label.setObjectName("RiskHelperPopupText")
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(Qt.NoTextInteraction)
        content_layout.addWidget(self._label)
        row.addWidget(content, 1)
        root.addLayout(row)

    def show_for(self, anchor: QWidget, text: str, severity: str, side: str) -> None:
        level = str(severity or "").lower()
        self.setProperty("severity", level)
        self._accent.setProperty("severity", level)
        self._label.setText(str(text or ""))
        if level == "warn":
            self.setMinimumWidth(360)
            self.setMaximumWidth(460)
        else:
            self.setMinimumWidth(320)
            self.setMaximumWidth(420)
        self.adjustSize()
        geo = self.frameGeometry()
        anchor_pos = anchor.mapToGlobal(QPoint(0, 0))
        if side == "left":
            x = anchor_pos.x() - geo.width() - 10
        else:
            x = anchor_pos.x() + anchor.width() + 10
        y = anchor_pos.y() + max(0, (anchor.height() - geo.height()) // 2)
        screen = QGuiApplication.screenAt(anchor_pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = max(available.left() + 4, min(x, available.right() - geo.width() - 4))
            y = max(available.top() + 4, min(y, available.bottom() - geo.height() - 4))
        self.move(x, y)
        self.style().unpolish(self)
        self.style().polish(self)
        self._accent.style().unpolish(self._accent)
        self._accent.style().polish(self._accent)
        self.show()
        self.raise_()


class ElidedFixedLabel(QLabel):
    def __init__(self, text: str, width: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._raw_text = str(text or "")
        self._fixed_width = max(int(width), 72)
        self.setWordWrap(False)
        self.setFixedWidth(self._fixed_width)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.setToolTip(self._raw_text)
        self._apply_elide()

    def set_raw_text(self, text: str) -> None:
        self._raw_text = str(text or "")
        self.setToolTip(self._raw_text)
        self._apply_elide()

    def _apply_elide(self) -> None:
        metrics = self.fontMetrics()
        available = max(int(self.width()) - 2, 8)
        elided = metrics.elidedText(self._raw_text, Qt.ElideRight, available)
        super().setText(elided)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_elide()


class SectionColumn(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        root.addWidget(heading, alignment=Qt.AlignLeft)

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(12)
        root.addWidget(self.content)
        self._root_layout = root

    def set_horizontal_inset(self, inset: int) -> None:
        self._root_layout.setContentsMargins(max(inset, 0), 0, max(inset, 0), 0)


class ResponsiveCompactGrid(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: List[Tuple[str, QWidget]] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(4)
        self._min_three_width = 560

    def add_cell(self, label: QLabel, editor: QWidget) -> None:
        cell = QWidget(self)
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        row.addWidget(editor, 1, Qt.AlignLeft | Qt.AlignVCenter)
        self._items.append(("cell", cell))
        self._relayout()

    def add_full_width_widget(self, widget: QWidget) -> None:
        self._items.append(("full", widget))
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
        cols = 3 if self.width() >= self._min_three_width else 2
        row = 0
        col = 0
        for kind, widget in self._items:
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
        for col in range(max(cols, 1)):
            self._grid.setColumnStretch(col, 1)


class AutoSizingStackedWidget(QStackedWidget):
    def sizeHint(self):  # type: ignore[override]
        current = self.currentWidget()
        if current is not None:
            return current.sizeHint()
        return super().sizeHint()

    def minimumSizeHint(self):  # type: ignore[override]
        current = self.currentWidget()
        if current is not None:
            return current.minimumSizeHint()
        return super().minimumSizeHint()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self.updateGeometry()


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


class AccordionHeaderRow(QFrame):
    clicked = Signal()
    reset_clicked = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("AccordionHeaderRow")
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("severity", "neutral")
        self.setMinimumHeight(48)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._accent = QFrame()
        self._accent.setObjectName("AccordionHeaderAccent")
        self._accent.setFixedWidth(3)
        self._accent.setProperty("severity", "neutral")
        root.addWidget(self._accent)

        content = QWidget()
        content.setObjectName("AccordionHeaderContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 8)
        content_layout.setSpacing(8)

        self._title = QLabel(title)
        self._title.setObjectName("AccordionHeaderTitle")
        content_layout.addWidget(self._title, 0, Qt.AlignVCenter)

        self._reset_btn = QPushButton("\u27f2")
        self._reset_btn.setObjectName("AccordionHeaderResetButton")
        self._reset_btn.setToolTip("Reset overrides in this block")
        self._reset_btn.setVisible(False)
        self._reset_btn.setEnabled(False)
        self._reset_btn.clicked.connect(self.reset_clicked.emit)
        content_layout.addWidget(self._reset_btn, 0, Qt.AlignVCenter)

        self._chips_wrap = QWidget()
        self._chips_wrap.setObjectName("AccordionChipWrap")
        self._chips_layout = QHBoxLayout(self._chips_wrap)
        self._chips_layout.setContentsMargins(0, 0, 0, 0)
        self._chips_layout.setSpacing(6)
        content_layout.addWidget(self._chips_wrap, 0, Qt.AlignVCenter)

        content_layout.addStretch(1)

        self._status_badge = QLabel("")
        self._status_badge.setObjectName("AccordionStatusBadge")
        self._status_badge.setMinimumWidth(42)
        self._status_badge.setAlignment(Qt.AlignCenter)
        self._status_badge.setVisible(True)
        content_layout.addWidget(self._status_badge, 0, Qt.AlignVCenter)

        self._chevron = QLabel("v")
        self._chevron.setObjectName("AccordionChevron")
        content_layout.addWidget(self._chevron, 0, Qt.AlignVCenter)

        root.addWidget(content, 1)
        self._chips: List[str] = []
        self._expanded = True
        self._status_level = "unset"
        self._can_reset = False

    def set_title(self, text: str) -> None:
        self._title.setText(safe_text(text))

    def set_summary_chips(self, chips: Sequence[str]) -> None:
        cleaned: List[str] = []
        for item in list(chips or []):
            token = safe_text(item).strip()
            if token:
                cleaned.append(token)
        self._chips = cleaned
        self._render_chips()

    def set_reset_available(self, available: bool) -> None:
        self._can_reset = bool(available)
        self._reset_btn.setEnabled(self._can_reset)
        self._reset_btn.setProperty("canReset", "true" if self._can_reset else "false")
        self._sync_reset_button_visibility()
        self._reset_btn.style().unpolish(self._reset_btn)
        self._reset_btn.style().polish(self._reset_btn)
        self._reset_btn.update()

    def _sync_reset_button_visibility(self) -> None:
        # Header reset is actionable only when collapsed and overrides exist.
        self._reset_btn.setVisible(bool(self._can_reset and (not self._expanded)))

    def set_expanded(self, expanded: bool) -> None:
        self._expanded = bool(expanded)
        self._chevron.setText("v" if self._expanded else ">")
        self._chips_wrap.setVisible(not self._expanded and bool(self._chips))
        self._sync_reset_button_visibility()
        self.setProperty("expanded", "true" if self._expanded else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def set_status_counts(
        self,
        *,
        ok_count: int,
        warn_count: int,
        fatal_count: int,
        incomplete_count: int = 0,
        active_count: int = 0,
        total_fields: int = 0,
    ) -> None:
        if int(fatal_count) > 0:
            self._status_badge.setText(f"x {int(fatal_count)}")
            self._status_badge.setProperty("severity", "fatal")
            if int(warn_count) > 0:
                self._status_badge.setToolTip(f"fatal: {int(fatal_count)}, warn: {int(warn_count)}")
            else:
                self._status_badge.setToolTip(f"fatal: {int(fatal_count)}")
            level = "fatal"
        elif int(warn_count) > 0:
            self._status_badge.setText(f"! {int(warn_count)}")
            self._status_badge.setProperty("severity", "warn")
            self._status_badge.setToolTip(f"warn: {int(warn_count)}")
            level = "warn"
        elif int(incomplete_count) > 0:
            self._status_badge.setText(f"~ {int(incomplete_count)}")
            self._status_badge.setProperty("severity", "incomplete")
            self._status_badge.setToolTip(f"incomplete: {int(incomplete_count)}")
            level = "incomplete"
        elif int(active_count) > 0:
            self._status_badge.setText("ok")
            self._status_badge.setProperty("severity", "ok")
            self._status_badge.setToolTip(f"configured: {int(active_count)}")
            level = "ok"
        else:
            self._status_badge.setText(".")
            self._status_badge.setProperty("severity", "unset")
            self._status_badge.setToolTip(f"unset: {int(total_fields)}")
            level = "unset"
        self._accent.setProperty("severity", level)
        self.setProperty("severity", level)
        self._status_level = level
        self._render_chips()
        self._status_badge.style().unpolish(self._status_badge)
        self._status_badge.style().polish(self._status_badge)
        self._accent.style().unpolish(self._accent)
        self._accent.style().polish(self._accent)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _render_chips(self) -> None:
        while self._chips_layout.count():
            item = self._chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if not self._chips:
            self._chips_wrap.setVisible(False)
            return
        max_visible = 2
        visible = self._chips[:max_visible]
        remaining = max(0, len(self._chips) - max_visible)
        for value in visible:
            chip = QLabel(safe_text(value))
            chip.setObjectName("AccordionChip")
            chip.setProperty("state", self._status_level)
            self._chips_layout.addWidget(chip, 0, Qt.AlignVCenter)
        if remaining > 0:
            extra = QLabel(f"+{remaining}")
            extra.setObjectName("AccordionChip")
            extra.setProperty("state", self._status_level)
            self._chips_layout.addWidget(extra, 0, Qt.AlignVCenter)
        self._chips_wrap.setVisible(not self._expanded)

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() in {Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space}:
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class AccordionGroupBox(QGroupBox):
    toggled = Signal(bool)
    reset_requested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self._collapsed = False
        self.setProperty("customHeader", "true")
        self.setProperty("expanded", "true")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._header = AccordionHeaderRow(title)
        self._header.clicked.connect(lambda: self.set_collapsed(not self._collapsed))
        self._header.reset_clicked.connect(self.reset_requested.emit)
        root.addWidget(self._header)

        self._body = QWidget(self)
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(8, 8, 8, 8)
        self._body_layout.setSpacing(6)
        root.addWidget(self._body)
        self._body_effect = QGraphicsOpacityEffect(self._body)
        self._body_effect.setOpacity(1.0)
        self._body.setGraphicsEffect(self._body_effect)
        self._anim_group: Optional[QParallelAnimationGroup] = None
        self.setProperty("blockState", "neutral")
        self.setProperty("collapsed", "false")

    def body_layout(self) -> QVBoxLayout:
        return self._body_layout

    def header_row(self) -> AccordionHeaderRow:
        return self._header

    def is_collapsed(self) -> bool:
        return bool(self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        state = bool(collapsed)
        if state == self._collapsed:
            return
        self._collapsed = state
        self._animate_body(expand=not state)
        self.setProperty("collapsed", "true" if state else "false")
        self.setProperty("expanded", "false" if state else "true")
        self._header.set_expanded(not state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.updateGeometry()
        self.toggled.emit(not state)

    def _animate_body(self, *, expand: bool) -> None:
        if self._anim_group is not None:
            self._anim_group.stop()
            self._anim_group.deleteLater()
            self._anim_group = None

        target_height = max(int(self._body.sizeHint().height()), 0)
        raw_current = int(self._body.maximumHeight())

        if expand:
            was_visible = self._body.isVisible()
            self._body.setVisible(True)
            if (not was_visible) or raw_current <= 0 or raw_current > 10_000:
                start_h = 0
            else:
                start_h = max(0, min(raw_current, target_height))
            end_h = target_height
            start_opacity, end_opacity = 0.0, 1.0
        else:
            if raw_current <= 0 or raw_current > 10_000:
                start_h = target_height
            else:
                start_h = max(0, raw_current)
            end_h = 0
            start_opacity, end_opacity = 1.0, 0.0

        height_anim = QPropertyAnimation(self._body, b"maximumHeight", self)
        height_anim.setDuration(180)
        height_anim.setEasingCurve(QEasingCurve.OutCubic)
        height_anim.setStartValue(start_h)
        height_anim.setEndValue(end_h)

        opacity_anim = QPropertyAnimation(self._body_effect, b"opacity", self)
        opacity_anim.setDuration(140)
        opacity_anim.setEasingCurve(QEasingCurve.OutCubic)
        opacity_anim.setStartValue(start_opacity)
        opacity_anim.setEndValue(end_opacity)

        group = QParallelAnimationGroup(self)
        group.addAnimation(height_anim)
        group.addAnimation(opacity_anim)

        def _finish() -> None:
            if expand:
                self._body.setVisible(True)
                self._body.setMaximumHeight(16_777_215)
                self._body_effect.setOpacity(1.0)
            else:
                self._body.setVisible(False)
                self._body.setMaximumHeight(0)
                self._body_effect.setOpacity(1.0)
            self._anim_group = None

        group.finished.connect(_finish)
        self._anim_group = group
        group.start()

    def set_summary_chips(self, chips: Sequence[str]) -> None:
        self._header.set_summary_chips(chips)

    def set_header_reset_available(self, available: bool) -> None:
        self._header.set_reset_available(bool(available))

    def set_status_counts(
        self,
        *,
        ok_count: int,
        warn_count: int,
        fatal_count: int,
        incomplete_count: int = 0,
        active_count: int = 0,
        total_fields: int = 0,
    ) -> None:
        self._header.set_status_counts(
            ok_count=ok_count,
            warn_count=warn_count,
            fatal_count=fatal_count,
            incomplete_count=incomplete_count,
            active_count=active_count,
            total_fields=total_fields,
        )


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
        placeholder: str = "0",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._is_float = bool(is_float)
        self._decimals = int(decimals if is_float else 0)
        self._minimum = minimum
        self._maximum = maximum
        self._base_placeholder = str(placeholder or "")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        base_width = INPUT_TOTAL_WIDTH
        self.setFixedWidth(base_width)

        self.edit = QLineEdit()
        self.edit.setObjectName("NullableInput")
        self.edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.edit.setFixedWidth(INPUT_TOTAL_WIDTH)
        self.edit.setMinimumHeight(CONTROL_HEIGHT)
        self.edit.setPlaceholderText(self._base_placeholder)
        self.edit.setClearButtonEnabled(False)
        root.addWidget(self.edit, 0, Qt.AlignLeft)

        self.unit_label = QLabel(str(unit or ""))
        self.unit_label.setObjectName("InputUnit")
        unit_width = max(UNIT_LABEL_WIDTH, self.unit_label.fontMetrics().horizontalAdvance(str(unit or "")) + 6)
        self.unit_label.setFixedWidth(unit_width)
        self.setFixedWidth(base_width + max(0, unit_width - UNIT_LABEL_WIDTH))
        self.edit.setFixedWidth(base_width - UNIT_LABEL_WIDTH - 6)
        root.addWidget(self.unit_label, 0, Qt.AlignLeft)
        self._install_validator()
        self.edit.textChanged.connect(self._on_text_changed)

    def _install_validator(self) -> None:
        if self._is_float:
            regex = QRegularExpression(rf"^-?\d*(?:[.,]\d{{0,{max(self._decimals, 0)}}})?$")
        else:
            regex = QRegularExpression(r"^-?\d*$")
        self.edit.setValidator(QRegularExpressionValidator(regex, self.edit))

    def _on_text_changed(self, _text: str) -> None:
        self._normalize_decimal_separator()
        self.changed.emit()

    def _normalize_decimal_separator(self) -> None:
        raw = self.edit.text()
        if "," not in raw:
            return
        cursor = self.edit.cursorPosition()
        normalized = raw.replace(",", ".")
        if normalized == raw:
            return
        self.edit.blockSignals(True)
        self.edit.setText(normalized)
        self.edit.setCursorPosition(min(cursor, len(normalized)))
        self.edit.blockSignals(False)

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
        self.unit_label.setEnabled(not locked)

    def set_suggested_text(self, text: str) -> None:
        self.edit.setPlaceholderText(str(text or self._base_placeholder))

    def clear_suggested_text(self) -> None:
        self.edit.setPlaceholderText(self._base_placeholder)


class NullableTextInput(QWidget):
    changed = Signal()

    def __init__(
        self,
        *,
        placeholder: str = "",
        width: Optional[int] = None,
        unit: Optional[str] = None,
        value_parser: Optional[Callable[[str], Any]] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._value_parser = value_parser
        self._base_placeholder = str(placeholder or "")

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        base_width = int(width or INPUT_TOTAL_WIDTH)

        self.edit = QLineEdit()
        self.edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.edit.setClearButtonEnabled(False)
        self.setFixedWidth(base_width)
        self.edit.setFixedWidth(base_width)
        self.edit.setMinimumHeight(CONTROL_HEIGHT)
        if self._base_placeholder:
            self.edit.setPlaceholderText(self._base_placeholder)
        root.addWidget(self.edit, 0, Qt.AlignLeft)

        self.unit_label = QLabel(str(unit or ""))
        self.unit_label.setObjectName("InputUnit")
        unit_width = max(UNIT_LABEL_WIDTH, self.unit_label.fontMetrics().horizontalAdvance(str(unit or "")) + 6)
        self.unit_label.setFixedWidth(unit_width)
        self.setFixedWidth(base_width + max(0, unit_width - UNIT_LABEL_WIDTH))
        self.edit.setFixedWidth(base_width - UNIT_LABEL_WIDTH - 6)
        root.addWidget(self.unit_label, 0, Qt.AlignLeft)

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
        self.unit_label.setEnabled(not locked)

    def set_suggested_text(self, text: str) -> None:
        self.edit.setPlaceholderText(str(text or self._base_placeholder))

    def clear_suggested_text(self) -> None:
        self.edit.setPlaceholderText(self._base_placeholder)


class _ModifierAwareSlider(QSlider):
    def __init__(self, orientation: Qt.Orientation, parent: QWidget | None = None) -> None:
        super().__init__(orientation, parent)
        self._base_step = 10

    def set_base_step(self, step: int) -> None:
        self._base_step = max(1, int(step))

    def _step_for_modifiers(self) -> int:
        mods = QApplication.keyboardModifiers()
        if mods & Qt.ShiftModifier:
            return max(1, int(self._base_step * 10))
        if mods & Qt.ControlModifier:
            return max(1, int(round(self._base_step / 10)))
        return max(1, self._base_step)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta = int(event.angleDelta().y())
        if delta == 0:
            super().wheelEvent(event)
            return
        step = self._step_for_modifiers()
        direction = 1 if delta > 0 else -1
        self.setValue(self.value() + (direction * step))
        event.accept()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() in {Qt.Key_Left, Qt.Key_Down, Qt.Key_Right, Qt.Key_Up}:
            direction = -1 if event.key() in {Qt.Key_Left, Qt.Key_Down} else 1
            self.setValue(self.value() + (direction * self._step_for_modifiers()))
            event.accept()
            return
        super().keyPressEvent(event)


class NullableSliderNumericInput(QWidget):
    changed = Signal()

    def __init__(
        self,
        *,
        minimum: float,
        maximum: float,
        decimals: int = 3,
        placeholder: str = "",
        unit: str | None = None,
        slider_resolution: int = 1000,
        base_slider_step: int = 10,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = float(minimum)
        self._maximum = float(maximum)
        self._decimals = max(0, int(decimals))
        self._slider_resolution = max(10, int(slider_resolution))
        self._base_placeholder = str(placeholder or "")
        self._syncing = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        unit_text = str(unit or "")
        self._slider_width = 72
        min_edit_width = 72
        self.unit_label = QLabel(unit_text)
        self.unit_label.setObjectName("InputUnit")
        unit_width = max(UNIT_LABEL_WIDTH, self.unit_label.fontMetrics().horizontalAdvance(unit_text) + 6)
        base_width = max(INPUT_TOTAL_WIDTH, unit_width + self._slider_width + min_edit_width + 12)
        self.setFixedWidth(base_width)

        self.edit = QLineEdit()
        self.edit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.edit.setPlaceholderText(self._base_placeholder)
        self.edit.setMinimumHeight(CONTROL_HEIGHT)
        regex = QRegularExpression(rf"^-?\d*(?:[.,]\d{{0,{max(self._decimals, 0)}}})?$")
        self.edit.setValidator(QRegularExpressionValidator(regex, self.edit))
        self.unit_label.setFixedWidth(unit_width)
        self.edit.setFixedWidth(base_width - unit_width - self._slider_width - 12)
        root.addWidget(self.edit, 0, Qt.AlignLeft | Qt.AlignVCenter)
        root.addWidget(self.unit_label, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.slider = _ModifierAwareSlider(Qt.Horizontal)
        self.slider.setRange(0, self._slider_resolution)
        self.slider.set_base_step(int(base_slider_step))
        self.slider.setToolTip("Ctrl=fine, Shift=coarse")
        self.slider.setFixedWidth(self._slider_width)
        self.slider.setMinimumHeight(CONTROL_HEIGHT)
        root.addWidget(self.slider, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self.edit.textChanged.connect(self._on_text_changed)
        self.slider.valueChanged.connect(self._on_slider_changed)

    def _to_slider(self, value: float) -> int:
        if self._maximum <= self._minimum:
            return 0
        ratio = (float(value) - self._minimum) / (self._maximum - self._minimum)
        ratio = max(0.0, min(1.0, ratio))
        return int(round(ratio * self._slider_resolution))

    def _from_slider(self, raw: int) -> float:
        if self._slider_resolution <= 0:
            return self._minimum
        ratio = float(raw) / float(self._slider_resolution)
        return self._minimum + ((self._maximum - self._minimum) * ratio)

    def _parse(self, text: str) -> Optional[float]:
        token = str(text or "").strip().replace(",", ".")
        if not token:
            return None
        try:
            value = float(token)
        except ValueError:
            return None
        if value < self._minimum or value > self._maximum:
            return None
        return value

    def _format(self, value: float) -> str:
        text = f"{float(value):.{self._decimals}f}".rstrip("0").rstrip(".")
        return text if text else "0"

    def _on_text_changed(self, _text: str) -> None:
        if self._syncing:
            return
        parsed = self._parse(self.edit.text())
        self._syncing = True
        try:
            if parsed is not None:
                self.slider.setValue(self._to_slider(parsed))
        finally:
            self._syncing = False
        self.changed.emit()

    def _on_slider_changed(self, raw: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            value = self._from_slider(raw)
            self.edit.setText(self._format(value))
        finally:
            self._syncing = False
        self.changed.emit()

    def is_set(self) -> bool:
        return self._parse(self.edit.text()) is not None

    def clear(self) -> None:
        previous_text = self.edit.text()
        previous_slider = int(self.slider.value())
        self._syncing = True
        edit_blocked = self.edit.blockSignals(True)
        slider_blocked = self.slider.blockSignals(True)
        try:
            self.edit.clear()
            self.slider.setValue(0)
        finally:
            self.edit.blockSignals(edit_blocked)
            self.slider.blockSignals(slider_blocked)
            self._syncing = False
        if previous_text.strip() or previous_slider != 0:
            self.changed.emit()

    def value(self) -> Optional[float]:
        return self._parse(self.edit.text())

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            self.clear()
            return
        clamped = min(max(parsed, self._minimum), self._maximum)
        self._syncing = True
        try:
            self.edit.setText(self._format(clamped))
            self.slider.setValue(self._to_slider(clamped))
        finally:
            self._syncing = False

    def set_locked(self, locked: bool) -> None:
        self.edit.setEnabled(not locked)
        self.slider.setEnabled(not locked)
        self.unit_label.setEnabled(not locked)

    def set_suggested_text(self, text: str) -> None:
        self.edit.setPlaceholderText(str(text or self._base_placeholder))

    def clear_suggested_text(self) -> None:
        self.edit.setPlaceholderText(self._base_placeholder)


class NullableIntSpinInput(QWidget):
    changed = Signal()

    def __init__(
        self,
        *,
        minimum: Optional[int] = None,
        maximum: Optional[int] = None,
        step: int = 1,
        placeholder: str = "",
        unit: Optional[str] = None,
        multiple_of: Optional[int] = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._base_placeholder = str(placeholder or "")
        self._multiple_of = int(multiple_of) if multiple_of is not None and int(multiple_of) > 1 else None
        self._is_set = False
        self._base_tooltip = ""

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        base_width = INPUT_TOTAL_WIDTH
        self.setFixedWidth(base_width)

        self.spin = QSpinBox()
        min_value = int(minimum) if minimum is not None else -1_000_000
        max_value = int(maximum) if maximum is not None else 1_000_000
        self.spin.setRange(min_value, max_value)
        self.spin.setSingleStep(max(1, int(step)))
        self.unit_label = QLabel(str(unit or ""))
        self.unit_label.setObjectName("InputUnit")
        unit_width = max(UNIT_LABEL_WIDTH, self.unit_label.fontMetrics().horizontalAdvance(str(unit or "")) + 6)
        self.unit_label.setFixedWidth(unit_width)
        self.setFixedWidth(base_width + max(0, unit_width - UNIT_LABEL_WIDTH))
        self.spin.setFixedWidth(base_width - UNIT_LABEL_WIDTH - 6)
        self.spin.setMinimumHeight(CONTROL_HEIGHT)
        self.spin.setAccelerated(True)
        self.spin.lineEdit().setPlaceholderText(self._base_placeholder)
        root.addWidget(self.spin, 0, Qt.AlignLeft)
        root.addWidget(self.unit_label, 0, Qt.AlignLeft)

        self.spin.valueChanged.connect(self._on_spin_changed)
        self.spin.lineEdit().textChanged.connect(self._on_line_text_changed)

    def _invalid_hint(self) -> str:
        if self._multiple_of is None:
            return ""
        return f"Value must be a multiple of {self._multiple_of}."

    def _valid_multiple(self, raw: str) -> bool:
        if self._multiple_of is None:
            return True
        token = str(raw or "").strip()
        if not token:
            return False
        try:
            value = int(token)
        except ValueError:
            return False
        return int(value) % int(self._multiple_of) == 0

    def _refresh_validity_state(self) -> None:
        text = str(self.spin.lineEdit().text() or "").strip()
        valid = bool(text) and self._valid_multiple(text)
        self.spin.lineEdit().setProperty("invalidMultiple", "false" if valid or not text else "true")
        tooltip_parts = [part for part in [self._base_tooltip.strip(), self._invalid_hint() if text and not valid else ""] if part]
        self.spin.lineEdit().setToolTip("\n\n".join(tooltip_parts))
        self.spin.lineEdit().style().unpolish(self.spin.lineEdit())
        self.spin.lineEdit().style().polish(self.spin.lineEdit())
        self.spin.lineEdit().update()

    def _on_spin_changed(self, _value: int) -> None:
        self._is_set = True
        self._refresh_validity_state()
        self.changed.emit()

    def _on_line_text_changed(self, text: str) -> None:
        if not str(text or "").strip():
            self._is_set = False
        self._refresh_validity_state()
        self.changed.emit()

    def is_set(self) -> bool:
        if not self._is_set:
            return False
        text = str(self.spin.lineEdit().text() or "").strip()
        if not text:
            return False
        return self._valid_multiple(text)

    def clear(self) -> None:
        self._is_set = False
        self.spin.lineEdit().clear()
        self._refresh_validity_state()

    def value(self) -> Optional[int]:
        return int(self.spin.value()) if self.is_set() else None

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            self.clear()
            return
        self._is_set = True
        self.spin.setValue(parsed)
        self._refresh_validity_state()

    def set_locked(self, locked: bool) -> None:
        self.spin.setEnabled(not locked)
        self.unit_label.setEnabled(not locked)

    def set_suggested_text(self, text: str) -> None:
        self.spin.lineEdit().setPlaceholderText(str(text or self._base_placeholder))

    def clear_suggested_text(self) -> None:
        self.spin.lineEdit().setPlaceholderText(self._base_placeholder)

    def set_base_tooltip(self, text: str) -> None:
        self._base_tooltip = str(text or "")
        self._refresh_validity_state()


class NullableVector4Input(QWidget):
    changed = Signal()

    def __init__(
        self,
        *,
        labels: Sequence[str],
        placeholder: str = "",
        unit: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._labels = [str(item).strip() or f"V{index + 1}" for index, item in enumerate(list(labels)[:4])]
        while len(self._labels) < 4:
            self._labels.append(f"V{len(self._labels) + 1}")
        self._base_placeholder = str(placeholder or "")
        self._link_updates = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self.setFixedWidth(INPUT_TOTAL_WIDTH + 120)

        self.link_all = QCheckBox("Link all")
        root.addWidget(self.link_all, 0, Qt.AlignLeft)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(2)
        self._edits: List[QLineEdit] = []
        for index, label_text in enumerate(self._labels):
            label = QLabel(label_text)
            label.setObjectName("InputUnit")
            grid.addWidget(label, 0, index)
            edit = QLineEdit()
            edit.setFixedWidth(58)
            edit.setPlaceholderText(self._base_placeholder)
            regex = QRegularExpression(r"^-?\d*(?:[.,]\d{0,6})?$")
            edit.setValidator(QRegularExpressionValidator(regex, edit))
            edit.textChanged.connect(lambda text, idx=index: self._on_text_changed(idx, text))
            self._edits.append(edit)
            grid.addWidget(edit, 1, index)

        unit_label = QLabel(str(unit or ""))
        unit_label.setObjectName("InputUnit")
        grid.addWidget(unit_label, 1, 4)
        root.addLayout(grid)

    def _parse_token(self, text: str) -> Optional[float]:
        token = str(text or "").strip().replace(",", ".")
        if not token:
            return None
        try:
            return float(token)
        except ValueError:
            return None

    def _on_text_changed(self, index: int, text: str) -> None:
        if self._link_updates:
            self.changed.emit()
            return
        if self.link_all.isChecked():
            normalized = str(text or "")
            self._link_updates = True
            try:
                for idx, edit in enumerate(self._edits):
                    if idx == index:
                        continue
                    edit.setText(normalized)
            finally:
                self._link_updates = False
        self.changed.emit()

    def is_set(self) -> bool:
        tokens = [self._parse_token(edit.text()) for edit in self._edits]
        return all(value is not None for value in tokens)

    def clear(self) -> None:
        for edit in self._edits:
            edit.clear()

    def value(self) -> Optional[List[float]]:
        if not self.is_set():
            return None
        return [float(self._parse_token(edit.text()) or 0.0) for edit in self._edits]

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        values: List[Any]
        if isinstance(value, (list, tuple)):
            values = list(value)[:4]
        else:
            values = [value]
        while len(values) < 4:
            values.append(None)
        for index, edit in enumerate(self._edits):
            token = values[index]
            if token is None:
                edit.clear()
                continue
            try:
                parsed = float(token)
            except (TypeError, ValueError):
                edit.clear()
                continue
            edit.setText(f"{parsed:.6g}")

    def set_locked(self, locked: bool) -> None:
        self.link_all.setEnabled(not locked)
        for edit in self._edits:
            edit.setEnabled(not locked)

    def set_suggested_text(self, text: str) -> None:
        values = [item.strip() for item in str(text or "").split(",")]
        for index, edit in enumerate(self._edits):
            hint = values[index] if index < len(values) and values[index] else self._base_placeholder
            edit.setPlaceholderText(hint)

    def clear_suggested_text(self) -> None:
        for edit in self._edits:
            edit.setPlaceholderText(self._base_placeholder)


class NullableListTableInput(QWidget):
    changed = Signal()

    def __init__(
        self,
        *,
        parse_int: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._parse_int = bool(parse_int)
        self._suggested_tooltip = ""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        self.setFixedWidth(INPUT_TOTAL_WIDTH + 120)

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(4)
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedWidth(28)
        self.remove_btn = QPushButton("-")
        self.remove_btn.setFixedWidth(28)
        buttons.addWidget(self.add_btn)
        buttons.addWidget(self.remove_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.table = QTableWidget(0, 1)
        self.table.setHorizontalHeaderLabels(["Value"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(True)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.table.setFixedHeight(108)
        root.addWidget(self.table)

        self.add_btn.clicked.connect(self._add_row)
        self.remove_btn.clicked.connect(self._remove_row)
        self.table.itemChanged.connect(lambda *_: self.changed.emit())

    def _add_row(self) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(""))
        self.changed.emit()

    def _remove_row(self) -> None:
        row_count = self.table.rowCount()
        if row_count <= 0:
            return
        self.table.removeRow(row_count - 1)
        self.changed.emit()

    def _parse_token(self, raw: str) -> Optional[float | int]:
        token = str(raw or "").strip().replace(",", ".")
        if not token:
            return None
        try:
            if self._parse_int:
                return int(float(token))
            return float(token)
        except ValueError:
            return None

    def _row_text(self, row: int) -> str:
        item = self.table.item(row, 0)
        return "" if item is None else str(item.text() or "")

    def is_set(self) -> bool:
        return any(bool(self._row_text(row).strip()) for row in range(self.table.rowCount()))

    def clear(self) -> None:
        self.table.setRowCount(0)

    def value(self) -> Optional[List[float | int]]:
        if not self.is_set():
            return None
        parsed: List[float | int] = []
        for row in range(self.table.rowCount()):
            raw = self._row_text(row)
            value = self._parse_token(raw)
            if value is None:
                if raw.strip():
                    return None
                value = 0 if self._parse_int else 0.0
            parsed.append(value)
        return parsed

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        values = list(value) if isinstance(value, (list, tuple)) else [value]
        self.table.setRowCount(0)
        for row, item in enumerate(values):
            self.table.insertRow(row)
            text = ""
            if item is not None:
                try:
                    text = str(int(float(item)) if self._parse_int else float(item))
                except (TypeError, ValueError):
                    text = ""
            self.table.setItem(row, 0, QTableWidgetItem(text))

    def set_locked(self, locked: bool) -> None:
        self.add_btn.setEnabled(not locked)
        self.remove_btn.setEnabled(not locked)
        self.table.setEnabled(not locked)

    def set_suggested_text(self, text: str) -> None:
        self._suggested_tooltip = str(text or "")
        self.table.setToolTip(self._suggested_tooltip)

    def clear_suggested_text(self) -> None:
        self._suggested_tooltip = ""
        self.table.setToolTip("")

    def entry_count(self) -> int:
        return int(self.table.rowCount())

    def set_entry_count(self, count: int) -> None:
        target = max(0, int(count))
        current = int(self.table.rowCount())
        if target == current:
            return
        if target < current:
            while self.table.rowCount() > target:
                self.table.removeRow(self.table.rowCount() - 1)
            self.changed.emit()
            return
        while self.table.rowCount() < target:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(""))
        self.changed.emit()


class NullableCodeEditorInput(QWidget):
    changed = Signal()

    def __init__(self, *, placeholder: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_placeholder = str(placeholder or "")
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setFixedWidth(INPUT_TOTAL_WIDTH + 160)

        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(self._base_placeholder)
        self.edit.setFixedHeight(108)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        self.edit.setFont(fixed_font)
        self.edit.textChanged.connect(lambda *_: self.changed.emit())
        root.addWidget(self.edit)

    def is_set(self) -> bool:
        return bool(str(self.edit.toPlainText() or "").strip())

    def clear(self) -> None:
        self.edit.clear()

    def value(self) -> Optional[str]:
        if not self.is_set():
            return None
        return str(self.edit.toPlainText() or "").strip()

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        self.edit.setPlainText(str(value))

    def set_locked(self, locked: bool) -> None:
        self.edit.setEnabled(not locked)

    def set_suggested_text(self, text: str) -> None:
        self.edit.setPlaceholderText(str(text or self._base_placeholder))

    def clear_suggested_text(self) -> None:
        self.edit.setPlaceholderText(self._base_placeholder)


class NullableBoolInput(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        self.segment = SegmentedEnumInput(options=[("off", False), ("on", True)])
        root.addWidget(self.segment, 0, Qt.AlignLeft)
        root.addStretch(1)
        self.segment.changed.connect(lambda *_: self.changed.emit())

    def is_set(self) -> bool:
        return self.segment.is_set()

    def clear(self) -> None:
        self.segment.clear(emit=False)

    def value(self) -> Optional[bool]:
        value = self.segment.value()
        return bool(value) if value is not None else None

    def set_value(self, value: Any) -> None:
        if value is None:
            self.clear()
            return
        self.segment.set_value(bool(value))

    def set_locked(self, locked: bool) -> None:
        self.segment.set_locked(locked)


class SegmentedEnumInput(QWidget):
    changed = Signal()
    blocked_interaction = Signal(object, str, str)

    def __init__(
        self,
        options: List[Tuple[str, Any]],
        parent: QWidget | None = None,
        *,
        fallback_value: Any | None = None,
        enforce_fallback: bool = False,
        fallback_is_unset: bool = False,
    ) -> None:
        super().__init__(parent)
        self._values_by_id: Dict[int, Any] = {}
        self._buttons: List[QPushButton] = []
        self._pressed_checked: Dict[int, bool] = {}
        self._none_option_id: Optional[int] = None
        self._fallback_value = fallback_value
        self._enforce_fallback = enforce_fallback
        self._fallback_is_unset = fallback_is_unset
        self._fallback_option_id: Optional[int] = None
        self._pressed_prev_checked_id: int = -1
        self._blocked_button_meta: Dict[int, Dict[str, Any]] = {}

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.group = QButtonGroup(self)
        self.group.setExclusive(True)

        for index, (label, value) in enumerate(options):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("segment", "true")
            button.setMinimumHeight(CONTROL_HEIGHT)
            button.setMinimumWidth(max(56, int(button.fontMetrics().horizontalAdvance(str(label)) + 16)))
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.group.addButton(button, index)
            self._values_by_id[index] = value
            if value is None:
                self._none_option_id = index
            if value == self._fallback_value:
                self._fallback_option_id = index
            self._buttons.append(button)
            root.addWidget(button)
            button.pressed.connect(lambda idx=index: self._on_pressed(idx))
            button.clicked.connect(lambda checked, idx=index: self._on_clicked(idx, checked))
        root.addStretch(1)

    def _on_pressed(self, button_id: int) -> None:
        button = self.group.button(button_id)
        self._pressed_checked[button_id] = bool(button and button.isChecked())
        self._pressed_prev_checked_id = int(self.group.checkedId())

    def _on_clicked(self, button_id: int, checked: bool) -> None:
        blocked_meta = self._blocked_button_meta.get(int(button_id))
        if blocked_meta is not None:
            self._restore_checked_state_after_blocked_click()
            self.blocked_interaction.emit(
                self._values_by_id.get(int(button_id)),
                str(blocked_meta.get("cause_key", "") or ""),
                str(blocked_meta.get("message", "") or ""),
            )
            return
        if self._pressed_checked.get(button_id, False) and checked:
            if self._enforce_fallback and self._fallback_option_id is not None:
                if button_id == self._fallback_option_id:
                    return
                fallback = self.group.button(self._fallback_option_id)
                if fallback is not None and not fallback.isChecked():
                    fallback.setChecked(True)
                    self.changed.emit()
                return
            self.clear()
            return
        self.changed.emit()

    def _restore_checked_state_after_blocked_click(self) -> None:
        previous = int(self._pressed_prev_checked_id)
        self.group.setExclusive(False)
        for button in self._buttons:
            button.setChecked(False)
        self.group.setExclusive(True)
        if previous >= 0:
            prev_button = self.group.button(previous)
            if prev_button is not None:
                prev_button.setChecked(True)

    def clear(self, *, emit: bool = True, force_empty: bool = False) -> None:
        if self._enforce_fallback and not force_empty and self._fallback_option_id is not None:
            fallback = self.group.button(self._fallback_option_id)
            if fallback is not None:
                changed = not fallback.isChecked()
                fallback.setChecked(True)
                if emit and changed:
                    self.changed.emit()
                return
        self.group.setExclusive(False)
        for button in self._buttons:
            button.setChecked(False)
        self.group.setExclusive(True)
        if emit:
            self.changed.emit()

    def is_set(self) -> bool:
        checked = self.group.checkedId()
        if checked < 0:
            return False
        if self._fallback_is_unset and checked == self._fallback_option_id:
            return False
        return self._values_by_id.get(checked) is not None

    def value(self) -> Any:
        checked = self.group.checkedId()
        if checked < 0:
            return None
        if self._fallback_is_unset and checked == self._fallback_option_id:
            return None
        return self._values_by_id.get(checked)

    def set_value(self, value: Any) -> None:
        if value is None:
            if self._none_option_id is not None:
                button = self.group.button(self._none_option_id)
                if button is not None:
                    button.setChecked(True)
                return
            self.clear(emit=False, force_empty=not self._enforce_fallback)
            return
        for button_id, option_value in self._values_by_id.items():
            if option_value == value:
                button = self.group.button(button_id)
                if button is not None:
                    button.setChecked(True)
                return
        self.clear(emit=False, force_empty=not self._enforce_fallback)

    def set_locked(self, locked: bool) -> None:
        for button in self._buttons:
            button.setEnabled(not locked)

    def set_blocked_option_map(self, blocked_options: Mapping[str, Mapping[str, Any]] | None) -> None:
        raw = dict(blocked_options or {})
        self._blocked_button_meta = {}
        for button_id, value in self._values_by_id.items():
            token = "__none__" if value is None else str(value)
            button = self.group.button(button_id)
            if button is None:
                continue
            meta = raw.get(token)
            if not isinstance(meta, Mapping):
                button.setProperty("compatBlockedOption", "false")
                button.setProperty("compatBlocked", "false")
                button.setToolTip("")
                continue
            message = str(meta.get("message", "") or "").strip()
            self._blocked_button_meta[int(button_id)] = {
                "cause_key": str(meta.get("cause_key", "") or "").strip(),
                "message": message,
            }
            button.setProperty("compatBlockedOption", "true")
            button.setProperty("compatBlocked", "true")
            button.setToolTip(message)
        for button in self._buttons:
            button.style().unpolish(button)
            button.style().polish(button)
            button.update()


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
        self.combo.setMinimumHeight(CONTROL_HEIGHT)
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
        self._state_badge: QLabel
        self._reset_button: QPushButton
        self._locked = False
        self._base_tooltip = str(field.tooltip or "")
        self._policy_suggested_default: Any = None
        self._policy_suggested_source = "policy_minimal"
        self._fixed_editor_width = False

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        self._value_widget = self._build_value_widget()
        key = str(self.field.key).strip()
        self._fixed_editor_width = (
            (self.field.widget_kind in {"float", "int", "expr", "ex"})
            or (key == "Morph.FixedPart")
            or self._is_angle_key(key)
        )
        if self._fixed_editor_width:
            self.setFixedWidth(int(EDITOR_TOTAL_WIDTH))
        root.addWidget(self._value_widget, 0, Qt.AlignLeft | Qt.AlignVCenter)

        self._reset_button = QPushButton("\u27f2")
        self._reset_button.setObjectName("FieldResetButton")
        self._reset_button.setToolTip("Reset override")
        self._reset_button.setProperty("canReset", "false")
        self._reset_button.setFixedSize(RESET_CONTROL_WIDTH, RESET_CONTROL_WIDTH)
        self._reset_button.clicked.connect(self._on_reset_clicked)
        root.addWidget(self._reset_button, 0, Qt.AlignRight)

        # Fixed-width badge avoids layout shifts when state changes.
        self._state_badge = QLabel("")
        self._state_badge.setObjectName("FieldStateBadge")
        self._state_badge.setFixedWidth(STATE_BADGE_WIDTH)
        self._state_badge.setAlignment(Qt.AlignCenter)
        self._state_badge.setProperty("severity", "neutral")
        self._state_badge.setVisible(True)
        root.addWidget(self._state_badge, 0, Qt.AlignRight)

        if self._base_tooltip:
            self.setToolTip(self._base_tooltip)
            self._value_widget.setToolTip(self._base_tooltip)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._wire_signals()

        if field.key == "Throat.Profile":
            self.set_is_set(False)
        elif field.key == "GCurve.Type":
            self.set_value(None)
        elif field.key == "Morph.TargetShape":
            self.set_value(0)
        elif field.key == "Rollback":
            self.set_value(0)
        else:
            self.set_is_set(False)
        self._sync_override_state()
        self._refresh_suggested_default_visuals()

    def _wire_signals(self) -> None:
        if hasattr(self._value_widget, "changed"):
            self._value_widget.changed.connect(self._on_value_widget_changed)  # type: ignore[attr-defined]

    def _on_value_widget_changed(self, *_: Any) -> None:
        self._sync_override_state()
        self._refresh_suggested_default_visuals()
        self.changed.emit()

    def _on_reset_clicked(self) -> None:
        self.set_is_set(False)
        self.changed.emit()

    @staticmethod
    def _is_angle_key(key: str) -> bool:
        token = str(key).strip()
        return token in {
            "Throat.Angle",
            "Throat.Ext.Angle",
            "Coverage.Angle",
            "CircArc.TermAngle",
            "Rot",
            "GCurve.Rot",
            "R-OSSE.a0",
            "R-OSSE.a",
        }

    @staticmethod
    def _angle_bounds_for_key(key: str) -> tuple[float, float]:
        token = str(key).strip()
        if token in {"Rot", "GCurve.Rot"}:
            return (-180.0, 180.0)
        if token in {"R-OSSE.a0", "R-OSSE.a", "Throat.Angle", "Throat.Ext.Angle", "Coverage.Angle"}:
            return (0.0, 90.0)
        return (0.0, 180.0)

    def _build_value_widget(self) -> QWidget:
        key = str(self.field.key).strip()
        if key == "Morph.FixedPart":
            return NullableSliderNumericInput(
                minimum=0.0,
                maximum=1.0,
                decimals=3,
                placeholder=self.field.placeholder or "0..1",
                unit=self.field.unit,
                slider_resolution=1000,
                base_slider_step=10,
            )
        if self._is_angle_key(key):
            angle_min, angle_max = self._angle_bounds_for_key(key)
            return NullableSliderNumericInput(
                minimum=angle_min,
                maximum=angle_max,
                decimals=2,
                placeholder=self.field.placeholder or "0",
                unit=self.field.unit,
                slider_resolution=720,
                base_slider_step=6,
            )
        if key == "Mesh.AngularSegments":
            return NullableIntSpinInput(
                minimum=4,
                maximum=int(self.field.maximum) if self.field.maximum is not None else 4096,
                step=4,
                multiple_of=4,
                placeholder=self.field.placeholder or "multiple of 4",
                unit=self.field.unit,
            )
        if key in {"Mesh.LengthSegments", "Mesh.CornerSegments", "Mesh.ThroatSegments"}:
            return NullableIntSpinInput(
                minimum=1 if self.field.minimum is None else int(self.field.minimum),
                maximum=int(self.field.maximum) if self.field.maximum is not None else 4096,
                step=1,
                placeholder=self.field.placeholder or "0",
                unit=self.field.unit,
            )
        if key in {"Mesh.Enclosure.Spacing", "Mesh.Enclosure.FrontResolution", "Mesh.Enclosure.BackResolution"}:
            labels = ("L", "T", "R", "B") if key == "Mesh.Enclosure.Spacing" else ("Q1", "Q2", "Q3", "Q4")
            return NullableVector4Input(labels=labels, placeholder=self.field.placeholder or "0", unit=self.field.unit)
        if key in {"Mesh.SubdomainSlices", "Mesh.InterfaceOffset", "Mesh.InterfaceDraw"}:
            return NullableListTableInput(parse_int=(key == "Mesh.SubdomainSlices"))
        if key == "Mesh.Enclosure.Plan":
            return NullableCodeEditorInput(placeholder=self.field.placeholder or "Plan script / layout")
        if self.field.key == "Rollback":
            return SegmentedEnumInput(
                options=[("disabled", 0), ("enabled", 1)],
                fallback_value=0,
                enforce_fallback=True,
                fallback_is_unset=True,
            )
        if self.field.widget_kind == "float":
            return NullableNumericInput(
                is_float=True,
                decimals=int(self.field.decimals or 2),
                minimum=self.field.minimum,
                maximum=self.field.maximum,
                unit=self.field.unit,
                placeholder=self.field.placeholder or "0",
            )
        if self.field.widget_kind == "int":
            return NullableNumericInput(
                is_float=False,
                decimals=0,
                minimum=self.field.minimum,
                maximum=self.field.maximum,
                unit=self.field.unit,
                placeholder=self.field.placeholder or "0",
            )
        if self.field.widget_kind == "bool":
            return NullableBoolInput()
        if self.field.widget_kind == "enum":
            options = [(option.label, option.value) for option in list(self.field.enum_options)]
            if self.field.key == "Mesh.Enclosure.EdgeType":
                return NullableEnumComboInput(options=options)
            if 1 < len(options) <= 4:
                if self.field.key == "GCurve.Type":
                    return SegmentedEnumInput(options=options, fallback_value=None, enforce_fallback=True)
                if self.field.key == "Morph.TargetShape":
                    return SegmentedEnumInput(
                        options=options,
                        fallback_value=0,
                        enforce_fallback=True,
                        fallback_is_unset=True,
                    )
                return SegmentedEnumInput(options=options)
            return NullableEnumComboInput(options=options)
        if self.field.widget_kind == "list":
            return NullableTextInput(
                placeholder=self.field.placeholder or "0",
                width=INPUT_TOTAL_WIDTH,
                unit=self.field.unit,
                value_parser=self._parse_list,
            )
        if self.field.widget_kind == "ex":
            return NullableTextInput(
                placeholder=self.field.placeholder or "0",
                width=INPUT_TOTAL_WIDTH,
                unit=self.field.unit,
            )
        return NullableTextInput(placeholder=self.field.placeholder or "0", width=INPUT_TOTAL_WIDTH, unit=self.field.unit)

    def _parse_list(self, text: str) -> List[Any]:
        if not text.strip():
            return []
        values: List[Any] = []
        for token in [item.strip() for item in re.split(r"[,\s;]+", text.strip())]:
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

    def _sync_override_state(self) -> None:
        can_reset = bool(self.is_set() and not self._locked)
        self._reset_button.setEnabled(can_reset)
        self._reset_button.setProperty("canReset", "true" if can_reset else "false")
        self._reset_button.style().unpolish(self._reset_button)
        self._reset_button.style().polish(self._reset_button)
        self._reset_button.update()

    def _default_hint(self) -> tuple[Any, str]:
        if self._policy_suggested_default is not None:
            return (self._policy_suggested_default, str(self._policy_suggested_source or "policy_minimal"))
        if self.field.default is not None:
            return (self.field.default, "catalog")
        return (None, "")

    def _refresh_suggested_default_visuals(self) -> None:
        value, source = self._default_hint()
        text = _format_default_value(value)
        tooltip_parts: List[str] = []
        if self._base_tooltip:
            tooltip_parts.append(self._base_tooltip)
        if (not self.is_set()) and text:
            tooltip_parts.append(f"Default (source={source}): {text}")
            self._apply_suggested_text(text)
        else:
            self._clear_suggested_text()
        tooltip = "\n\n".join(tooltip_parts).strip()
        self.setToolTip(tooltip)
        self._value_widget.setToolTip(tooltip)
        if isinstance(self._value_widget, NullableIntSpinInput):
            self._value_widget.set_base_tooltip(tooltip)

    def _apply_suggested_text(self, text: str) -> None:
        if hasattr(self._value_widget, "set_suggested_text"):
            self._value_widget.set_suggested_text(text)  # type: ignore[attr-defined]
            return
        edit = getattr(self._value_widget, "edit", None)
        if isinstance(edit, (QLineEdit, QPlainTextEdit)):
            edit.setPlaceholderText(str(text))

    def _clear_suggested_text(self) -> None:
        if hasattr(self._value_widget, "clear_suggested_text"):
            self._value_widget.clear_suggested_text()  # type: ignore[attr-defined]
            return

    def set_is_set(self, enabled: bool) -> None:
        if enabled:
            if not self.is_set() and self.field.default is not None:
                self.set_value(self.field.default)
            self._sync_override_state()
            self._refresh_suggested_default_visuals()
            return
        if hasattr(self._value_widget, "clear"):
            self._value_widget.clear()  # type: ignore[attr-defined]
        self._sync_override_state()
        self._refresh_suggested_default_visuals()

    def set_value(self, value: Any) -> None:
        if hasattr(self._value_widget, "set_value"):
            self._value_widget.set_value(value)  # type: ignore[attr-defined]
        self._sync_override_state()
        self._refresh_suggested_default_visuals()

    def set_policy_suggested_default(self, value: Any, *, source: str = "policy_minimal") -> None:
        self._policy_suggested_default = value
        self._policy_suggested_source = str(source or "policy_minimal")
        self._refresh_suggested_default_visuals()

    def clear_policy_suggested_default(self) -> None:
        self._policy_suggested_default = None
        self._refresh_suggested_default_visuals()

    def current_state(self) -> FieldState:
        if not self.is_set():
            return FieldState(is_set=False, value=None)
        if hasattr(self._value_widget, "value"):
            return FieldState(is_set=True, value=self._value_widget.value())  # type: ignore[attr-defined]
        return FieldState(is_set=False, value=None)

    def set_locked(self, locked: bool) -> None:
        self._locked = bool(locked)
        if locked:
            self.setToolTip("Locked by runner mode.")
        if hasattr(self._value_widget, "set_locked"):
            self._value_widget.set_locked(locked)  # type: ignore[attr-defined]
        else:
            self._value_widget.setEnabled(not locked)
        self._sync_override_state()
        if not locked:
            self._refresh_suggested_default_visuals()

    def set_helper_message(self, message: str, severity: str) -> None:
        # Legacy hook retained for compatibility; helper text is now shown in the
        # fixed inspector area to avoid shifting field layout.
        _ = (message, severity)

    def clear_helper_message(self) -> None:
        return

    def set_field_state_visual(self, severity: str) -> None:
        level = str(severity or "neutral").lower()
        symbol = ""
        if level == "warn":
            symbol = "!"
        elif level == "fatal":
            symbol = "x"
        self._state_badge.setText(symbol)
        self._state_badge.setProperty("severity", level)
        self._state_badge.style().unpolish(self._state_badge)
        self._state_badge.style().polish(self._state_badge)
        self._state_badge.update()

class ObjectFieldEditor(QWidget):
    changed = Signal()

    @staticmethod
    def _is_tall_property_editor(editor: ScalarFieldEditor) -> bool:
        value_widget = editor.value_widget()
        return isinstance(value_widget, (NullableVector4Input, NullableListTableInput, NullableCodeEditorInput))

    def __init__(self, field: FieldSpec, *, use_toggle: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.field = field
        self._use_toggle = use_toggle
        self.property_editors: Dict[str, ScalarFieldEditor] = {}
        self._state_badge: QLabel
        self._reset_button: QPushButton
        self._locked = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(8)

        badge_row = QHBoxLayout()
        badge_row.setContentsMargins(0, 0, 0, 0)
        badge_row.setSpacing(0)
        badge_row.addStretch(1)
        self._reset_button = QPushButton("\u27f2")
        self._reset_button.setObjectName("FieldResetButton")
        self._reset_button.setToolTip("Reset override")
        self._reset_button.setProperty("canReset", "false")
        self._reset_button.setFixedSize(RESET_CONTROL_WIDTH, RESET_CONTROL_WIDTH)
        self._reset_button.clicked.connect(self._on_reset_clicked)
        badge_row.addWidget(self._reset_button, 0, Qt.AlignRight)
        self._state_badge = QLabel("")
        self._state_badge.setObjectName("FieldStateBadge")
        self._state_badge.setFixedWidth(STATE_BADGE_WIDTH)
        self._state_badge.setAlignment(Qt.AlignCenter)
        self._state_badge.setProperty("severity", "neutral")
        badge_row.addWidget(self._state_badge, 0, Qt.AlignRight)
        root.addLayout(badge_row)

        self.toggle: Optional[SegmentedEnumInput] = None
        if self._use_toggle:
            self.toggle = SegmentedEnumInput(
                options=[("disabled", 0), ("enabled", 1)],
                fallback_value=0,
                enforce_fallback=True,
            )
            root.addWidget(self.toggle, alignment=Qt.AlignLeft)

        self.props_frame = ContextFrame("Details")
        self.props_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        props_widget = QWidget()
        props_grid = QGridLayout(props_widget)
        use_rosse_three_column = str(field.key).strip() == "R-OSSE"
        compact_grid: Optional[ResponsiveCompactGrid] = None
        if use_rosse_three_column:
            compact_grid = ResponsiveCompactGrid()
            compact_grid._min_three_width = 560
        else:
            configure_two_column_grid(props_grid)

        grid_row = 0
        left_slot = True
        for property_field in field.object_properties:
            editor = ScalarFieldEditor(property_field)
            editor.changed.connect(self._on_child_changed)
            if use_rosse_three_column and compact_grid is not None:
                label = QLabel(property_field.label)
                label.setWordWrap(False)
                label.setToolTip(str(property_field.label or ""))
                label.setFixedWidth(max(122, LABEL_COLUMN_WIDTH - 16))
                compact_grid.add_cell(label, editor)
            else:
                if self._is_tall_property_editor(editor):
                    if not left_slot:
                        grid_row += 1
                        left_slot = True
                    tall_row = QWidget()
                    tall_layout = QVBoxLayout(tall_row)
                    tall_layout.setContentsMargins(0, 0, 0, 0)
                    tall_layout.setSpacing(3)
                    tall_label = QLabel(property_field.label)
                    tall_label.setObjectName("ContextTitle")
                    tall_label.setToolTip(str(property_field.label or ""))
                    tall_layout.addWidget(tall_label, 0, Qt.AlignLeft)
                    tall_layout.addWidget(editor, 0, Qt.AlignLeft)
                    props_grid.addWidget(tall_row, grid_row, 0, 1, 5)
                    grid_row += 1
                    left_slot = True
                else:
                    label = QLabel(property_field.label)
                    label.setWordWrap(False)
                    label.setToolTip(str(property_field.label or ""))
                    label.setFixedWidth(LABEL_COLUMN_WIDTH)
                    slot_index = 0 if left_slot else 1
                    label_col, input_col = _two_column_positions(slot_index)
                    props_grid.addWidget(label, grid_row, label_col)
                    props_grid.addWidget(editor, grid_row, input_col, 1, 1, alignment=Qt.AlignLeft)
                    if left_slot:
                        left_slot = False
                    else:
                        left_slot = True
                        grid_row += 1
            self.property_editors[property_field.key] = editor

        if use_rosse_three_column and compact_grid is not None:
            self.props_frame.content_layout.addWidget(compact_grid)
        else:
            self.props_frame.content_layout.addWidget(props_widget)
        root.addWidget(self.props_frame)

        if field.tooltip:
            self.setToolTip(field.tooltip)
            self.props_frame.setToolTip(field.tooltip)

        if self.toggle is not None:
            self.toggle.changed.connect(self._on_toggle_changed)
            self.toggle.set_value(0)
        self._apply_enabled_state()
        self._sync_override_state()

    def _toggle_enabled(self) -> bool:
        if self.toggle is None:
            return True
        value = self.toggle.value()
        return bool(value == 1)

    def _sync_override_state(self) -> None:
        can_reset = bool(self.is_set() and not self._locked)
        self._reset_button.setEnabled(can_reset)
        self._reset_button.setProperty("canReset", "true" if can_reset else "false")
        self._reset_button.style().unpolish(self._reset_button)
        self._reset_button.style().polish(self._reset_button)
        self._reset_button.update()

    def _on_reset_clicked(self) -> None:
        self.set_is_set(False)
        self.changed.emit()

    def _on_toggle_changed(self) -> None:
        if not self._toggle_enabled():
            for editor in self.property_editors.values():
                editor.set_is_set(False)
        self._apply_enabled_state()
        self._sync_override_state()
        self.changed.emit()

    def _on_child_changed(self) -> None:
        if self.toggle is not None and any(editor.is_set() for editor in self.property_editors.values()):
            if not self._toggle_enabled():
                self.toggle.set_value(1)
        self._sync_override_state()
        self.changed.emit()

    def _apply_enabled_state(self) -> None:
        enabled = self._toggle_enabled()
        self.props_frame.setVisible(enabled if self.toggle is not None else True)
        for editor in self.property_editors.values():
            editor.setEnabled(enabled)

    def is_set(self) -> bool:
        if self.toggle is not None:
            return self._toggle_enabled()
        return any(editor.is_set() for editor in self.property_editors.values())

    def set_is_set(self, enabled: bool) -> None:
        if self.toggle is not None:
            currently_enabled = self._toggle_enabled()
            target_value = 1 if enabled else 0
            if currently_enabled != bool(enabled):
                self.toggle.set_value(target_value)
                self._apply_enabled_state()
            if not enabled:
                has_overrides = any(editor.is_set() for editor in self.property_editors.values())
                if has_overrides:
                    for editor in self.property_editors.values():
                        editor.set_is_set(False)
            self._sync_override_state()
            return
        if not enabled:
            for editor in self.property_editors.values():
                editor.set_is_set(False)
        self._sync_override_state()

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
        self._locked = bool(locked)
        if self.toggle is not None:
            self.toggle.set_locked(locked)
        for editor in self.property_editors.values():
            editor.set_locked(locked)
        if locked:
            self.setToolTip("Locked by runner mode.")
        self._sync_override_state()

    def set_helper_message(self, message: str, severity: str) -> None:
        _ = (message, severity)

    def clear_helper_message(self) -> None:
        return

    def set_field_state_visual(self, severity: str) -> None:
        level = str(severity or "neutral").lower()
        symbol = ""
        if level == "warn":
            symbol = "!"
        elif level == "fatal":
            symbol = "x"
        self._state_badge.setText(symbol)
        self._state_badge.setProperty("severity", level)
        self._state_badge.style().unpolish(self._state_badge)
        self._state_badge.style().polish(self._state_badge)
        self._state_badge.update()


def _two_column_positions(form_column: int) -> Tuple[int, int]:
    if form_column <= 0:
        return (0, 1)
    return (3, 4)


def _group_width_hint() -> int:
    # label + input + spacer + label + input + horizontal margins
    return (2 * LABEL_COLUMN_WIDTH) + (2 * INPUT_TOTAL_WIDTH) + FORM_METRICS.column_gap + 32


def _finalize_group_box(box: QGroupBox) -> None:
    width = _group_width_hint()
    box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
    box.setMinimumWidth(width)
    box.setMaximumWidth(16_777_215)


class ParameterForm(QWidget):
    changed = Signal(dict)
    blocked_interaction = Signal(str, str, str)

    def __init__(self, schema: FormSchema | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.schema = schema or build_project_form_schema()
        self._field_specs = self.schema.by_key()
        self._field_editors: Dict[str, QWidget] = {}
        self._field_labels: Dict[str, QLabel] = {}
        self._mode_widgets: Dict[str, Tuple[QStackedWidget, Dict[Optional[int], int]]] = {}
        self._mode_common_frames: Dict[str, Tuple[ContextFrame, Tuple[str, ...]]] = {}
        self._compat_state: Dict[str, Any] = {"visible_keys": [], "locked_keys": [], "issues": []}
        self._compat_visible_keys: set[str] = set()
        self._field_group_boxes: Dict[str, AccordionGroupBox] = {}
        self._field_column_map: Dict[str, str] = {}
        self._section_key_map: Dict[int, set[str]] = {}
        self._accordion_groups_by_column: Dict[str, List[AccordionGroupBox]] = {"Geometry": [], "Mesh": []}
        self._accordion_sync_active = False
        self._morph_detail_frame: Optional[ContextFrame] = None
        self._rollback_detail_frame: Optional[ContextFrame] = None
        self._morph_detail_keys: Tuple[str, ...] = ()
        self._rollback_detail_keys: Tuple[str, ...] = ("Rollback.Angle", "Rollback.Exp", "Rollback.StartAt")
        self._coverage_angle_key = "Coverage.Angle"
        self._suspend_emit = False
        self._handling_field_change = False
        self._last_changed_key: Optional[str] = None
        self._compat_ui_state: Dict[str, Any] = {}
        self._compat_hidden_keys: set[str] = set()
        self._base_width: Optional[int] = None
        self._risk_widgets: Dict[int, QWidget] = {}
        self._risk_original_tooltips: Dict[int, str] = {}
        self._section_counts_by_box: Dict[int, Dict[str, int]] = {}
        self._risk_hover_installed: Dict[int, QWidget] = {}
        self._geometry_dense_grids: List[ResponsiveCompactGrid] = []
        self._pending_hover_widget: Optional[QWidget] = None
        self._hover_tooltip_timer = QTimer(self)
        self._hover_tooltip_timer.setSingleShot(True)
        self._hover_tooltip_timer.setInterval(90)
        self._hover_tooltip_timer.timeout.connect(self._show_pending_risk_tooltip)
        self._risk_popup = RiskHelperPopup(self)

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(30)
        self._root_layout = root

        self.geometry_scroll = QScrollArea()
        self.geometry_scroll.setObjectName("ProjectGeometryScroll")
        self.geometry_scroll.setWidgetResizable(True)
        self.geometry_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.geometry_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.geometry_scroll.setMinimumWidth(_group_width_hint() + 28)
        self.mesh_scroll = QScrollArea()
        self.mesh_scroll.setObjectName("ProjectMeshScroll")
        self.mesh_scroll.setWidgetResizable(True)
        self.mesh_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.mesh_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.mesh_scroll.setMinimumWidth(_group_width_hint() + 28)
        self.geometry_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.mesh_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root.addWidget(self.geometry_scroll, 2)
        root.addWidget(self.mesh_scroll, 1)

        geometry_container = QWidget()
        self.geometry_scroll.setWidget(geometry_container)
        geometry_layout = QVBoxLayout(geometry_container)
        geometry_layout.setContentsMargins(0, 4, 0, 0)
        geometry_layout.setSpacing(14)
        self.geometry_section = SectionColumn("Geometry")
        geometry_layout.addWidget(self.geometry_section)
        geometry_layout.addStretch(1)

        mesh_container = QWidget()
        self.mesh_scroll.setWidget(mesh_container)
        mesh_layout = QVBoxLayout(mesh_container)
        mesh_layout.setContentsMargins(0, 4, 0, 0)
        mesh_layout.setSpacing(14)
        self.mesh_section = SectionColumn("Mesh")
        mesh_layout.addWidget(self.mesh_section)
        mesh_layout.addStretch(1)

        self._build_sections()
        self._refresh_mode_stacks()
        self._apply_local_disclosure()
        self._apply_responsive_spacing()
        self.changed.emit(self.payload())

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._base_width is None:
            self._base_width = max(int(self.width()), 1)
        self._apply_responsive_spacing()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_responsive_spacing()

    def _apply_responsive_spacing(self) -> None:
        if self._base_width is None:
            self._base_width = max(int(self.width()), 1)
        extra = max(int(self.width()) - int(self._base_width), 0)
        compact = int(self.width()) < 1280
        compact_window = self._is_geometry_compact()
        self._root_layout.setSpacing(24 if compact else 28)

        block_spacing = 9 + min(extra // 260, 8)
        for section in (self.geometry_section, self.mesh_section):
            # Keep symmetric outer spacing against both window sides.
            section.set_horizontal_inset(0)
            section.content_layout.setSpacing(block_spacing)
        for grid in self._geometry_dense_grids:
            grid._min_three_width = 10_000 if compact_window else 560
            grid._relayout()

    def _is_geometry_compact(self) -> bool:
        window = self.window()
        if window is not None:
            return int(window.width()) < 1200
        return int(self.width()) < 1200

    def _build_geometry_dense_grid(self) -> ResponsiveCompactGrid:
        grid = ResponsiveCompactGrid()
        grid._min_three_width = 10_000 if self._is_geometry_compact() else 560
        self._geometry_dense_grids.append(grid)
        return grid

    def _make_field_label(self, text: str, *, compact: bool = False, width: Optional[int] = None) -> QLabel:
        label_width = int(width) if width is not None else (max(122, LABEL_COLUMN_WIDTH - 20) if compact else LABEL_COLUMN_WIDTH)
        label = ElidedFixedLabel(str(text or ""), label_width)
        return label

    def _record_field_metadata(
        self,
        key: str,
        box: AccordionGroupBox,
        column_key: str,
        label: Optional[QLabel] = None,
    ) -> None:
        if label is not None:
            self._field_labels[key] = label
        self._field_group_boxes[key] = box
        self._field_column_map[key] = column_key
        self._section_key_map.setdefault(id(box), set()).add(key)

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

        self._add_group_by_name(self.geometry_section.content_layout, grouped_geometry, "Basics", column_key="Geometry")
        self._add_mode_group(self.geometry_section.content_layout, stacks_by_controller.get("Throat.Profile"), column_key="Geometry")
        self._add_morph_group(self.geometry_section.content_layout, grouped_geometry, column_key="Geometry")
        self._add_mode_group(self.geometry_section.content_layout, stacks_by_controller.get("GCurve.Type"), column_key="Geometry")
        self._add_rollback_group(self.geometry_section.content_layout, grouped_geometry, column_key="Geometry")

        self._add_mesh_core_group(self.mesh_section.content_layout, grouped_mesh, column_key="Mesh")
        self._add_group_by_name(self.mesh_section.content_layout, grouped_mesh, "Enclosure", column_key="Mesh")
        self._initialize_accordion_defaults()

    def _register_group_box(self, box: AccordionGroupBox, *, column_key: str) -> None:
        groups = self._accordion_groups_by_column.setdefault(column_key, [])
        groups.append(box)
        box.toggled.connect(lambda expanded, current=box, column=column_key: self._on_group_toggled(column, current, expanded))

    def _on_group_toggled(self, column_key: str, current: AccordionGroupBox, expanded: bool) -> None:
        if self._accordion_sync_active:
            return
        if not expanded:
            return
        self._accordion_sync_active = True
        try:
            for box in self._accordion_groups_by_column.get(column_key, []):
                if box is current:
                    continue
                box.set_collapsed(True)
        finally:
            self._accordion_sync_active = False

    def _initialize_accordion_defaults(self) -> None:
        for column_key, boxes in self._accordion_groups_by_column.items():
            for index, box in enumerate(boxes):
                box.set_collapsed(index != 0)
        self._refresh_section_headers()

    def _field_state(self, key: str) -> FieldState:
        editor = self._field_editors.get(key)
        if editor is None or not hasattr(editor, "current_state"):
            return FieldState(is_set=False, value=None)
        return editor.current_state()  # type: ignore[return-value]

    def _enum_label(self, key: str, value: Any) -> Optional[str]:
        field = self._field_specs.get(key)
        if field is None:
            return None
        for option in field.enum_options:
            if option.value == value:
                return option.label
        return str(value) if value is not None else None

    def _chips_for_box(self, box: AccordionGroupBox) -> List[str]:
        title = str(box.title()).strip()
        chips: List[str] = []

        if title == "Throat Profile":
            state = self._field_state("Throat.Profile")
            if state.is_set:
                label = self._enum_label("Throat.Profile", state.value)
                if label:
                    chips.append(label)
        elif title == "GCurve":
            state = self._field_state("GCurve.Type")
            label = self._enum_label("GCurve.Type", state.value if state.is_set else None)
            if label:
                chips.append(label)
        elif title == "Morph":
            state = self._field_state("Morph.TargetShape")
            label = self._enum_label("Morph.TargetShape", state.value if state.is_set else 0)
            if label:
                chips.append(label)
        elif title == "Enclosure":
            state = self._field_state("Mesh.Enclosure")
            chips.append("enabled" if state.is_set else "disabled")
        elif title == "Core":
            q_state = self._field_state("Mesh.Quadrants")
            if q_state.is_set:
                chips.append(f"Quadrants={q_state.value}")
            r_state = self._field_state("Mesh.RearShape")
            if r_state.is_set:
                label = self._enum_label("Mesh.RearShape", r_state.value)
                if label:
                    chips.append(f"RearShape={label}")
        elif title == "Basics":
            d_state = self._field_state("Throat.Diameter")
            l_state = self._field_state("Length")
            if d_state.is_set:
                chips.append(f"Throat={d_state.value}")
            if l_state.is_set:
                chips.append(f"Length={l_state.value}")

        return chips

    def _refresh_section_headers(self) -> None:
        for boxes in self._accordion_groups_by_column.values():
            for box in boxes:
                chips = self._chips_for_box(box)
                box.set_summary_chips(chips)
                counts = self._section_counts_by_box.get(id(box), {})
                box.set_status_counts(
                    ok_count=int(counts.get("ok", 0)),
                    warn_count=int(counts.get("warn", 0)),
                    fatal_count=int(counts.get("fatal", 0)),
                    incomplete_count=int(counts.get("incomplete", 0)),
                    active_count=int(counts.get("active", 0)),
                    total_fields=len(self._section_key_map.get(id(box), set())),
                )

    def _fields_by_group(self, fields: Iterable[FieldSpec]) -> Dict[str, List[FieldSpec]]:
        grouped: Dict[str, List[FieldSpec]] = {}
        for field in fields:
            group_name = field.group_path[1] if len(field.group_path) >= 2 else "General"
            grouped.setdefault(group_name, []).append(field)
        return grouped

    @staticmethod
    def _field_sort_tuple(field: FieldSpec) -> tuple[int, int, str]:
        return (field_display_priority(str(field.key)), int(field.order), str(field.key))

    def _ordered_keys(self, keys: Iterable[str]) -> List[str]:
        return sorted(
            [str(item) for item in list(keys or []) if str(item).strip()],
            key=lambda key: (
                field_display_priority(key),
                int(self._field_specs.get(key).order) if self._field_specs.get(key) is not None else 100_000,
                key,
            ),
        )

    def _add_group_by_name(
        self,
        parent_layout: QVBoxLayout,
        grouped_fields: Dict[str, List[FieldSpec]],
        group_name: str,
        *,
        column_key: str,
    ) -> None:
        fields = list(grouped_fields.get(group_name, []))
        if not fields:
            return
        self._add_grouped_fields(parent_layout, fields, forced_group_name=group_name, column_key=column_key)

    def _add_mesh_core_group(
        self,
        parent_layout: QVBoxLayout,
        grouped_fields: Dict[str, List[FieldSpec]],
        *,
        column_key: str,
    ) -> None:
        fields = list(grouped_fields.get("Core", []))
        if not fields:
            return

        selection_priority = {"Mesh.Quadrants": 0, "Mesh.RearShape": 1}
        ordered = sorted(
            fields,
            key=lambda field: (
                selection_priority.get(field.key, 9),
                field_display_priority(str(field.key)),
                int(field.order),
                str(field.key),
            ),
        )

        box = AccordionGroupBox("Core")
        _finalize_group_box(box)
        self._register_group_box(box, column_key=column_key)
        box_layout = box.body_layout()

        selection_grid = QGridLayout()
        configure_single_column_grid(selection_grid)
        form_grid = QGridLayout()
        form_grid.setContentsMargins(
            FORM_METRICS.margin_left,
            FORM_METRICS.margin_top,
            FORM_METRICS.margin_right,
            FORM_METRICS.margin_bottom,
        )
        form_grid.setHorizontalSpacing(0)
        form_grid.setVerticalSpacing(FORM_METRICS.row_gap)
        # Columns: label1, gap1, input1, mid-gap, label2, gap2, input2, tail-stretch
        mesh_core_label_width = max(LABEL_COLUMN_WIDTH + 34, 186)
        form_grid.setColumnMinimumWidth(1, FORM_METRICS.label_to_input_gap + 10)
        form_grid.setColumnMinimumWidth(3, max(FORM_METRICS.column_gap - 2, 24))
        form_grid.setColumnMinimumWidth(5, FORM_METRICS.label_to_input_gap + 10)
        form_grid.setColumnStretch(7, 1)

        selection_keys = {"Mesh.Quadrants", "Mesh.RearShape"}
        selection_fields = [field for field in ordered if field.key in selection_keys]
        other_fields = [field for field in ordered if field.key not in selection_keys]
        core_body_order = [
            "Mesh.ThroatResolution",
            "Mesh.MouthResolution",
            "Mesh.AngularSegments",
            "Mesh.LengthSegments",
            "Mesh.CornerSegments",
            "Mesh.ThroatSegments",
            "Mesh.InterfaceResolution",
            "Mesh.ZMapPoints",
            "Mesh.SubdomainSlices",
            "Mesh.InterfaceOffset",
            "Mesh.InterfaceDraw",
            "Mesh.WallThickness",
            "Mesh.RearResolution",
        ]
        rank = {key: index for index, key in enumerate(core_body_order)}
        other_fields.sort(key=lambda field: rank.get(field.key, 10_000))

        for row, field in enumerate(selection_fields):
            label = self._make_field_label(field.label)
            editor = self._ensure_editor(field)
            selection_grid.addWidget(label, row, 0)
            selection_grid.addWidget(editor, row, 1, 1, 1, alignment=Qt.AlignLeft)
            self._record_field_metadata(field.key, box, column_key, label)

        left_fields = other_fields[:6]
        right_fields = other_fields[6:]

        for row, field in enumerate(left_fields):
            label = self._make_field_label(field.label, width=mesh_core_label_width)
            editor = self._ensure_editor(field)
            form_grid.addWidget(label, row, 0)
            form_grid.addWidget(editor, row, 2, 1, 1, alignment=Qt.AlignLeft)
            self._record_field_metadata(field.key, box, column_key, label)

        for row, field in enumerate(right_fields):
            label = self._make_field_label(field.label, width=mesh_core_label_width)
            editor = self._ensure_editor(field)
            form_grid.addWidget(label, row, 4)
            form_grid.addWidget(editor, row, 6, 1, 1, alignment=Qt.AlignLeft)
            self._record_field_metadata(field.key, box, column_key, label)

        box_layout.addLayout(selection_grid)
        box_layout.addLayout(form_grid)
        parent_layout.addWidget(box)

    def _add_mode_group(
        self,
        parent_layout: QVBoxLayout,
        stack: Optional[ModeStackSpec],
        *,
        column_key: str,
    ) -> None:
        if stack is None:
            return
        self._add_mode_groups(parent_layout, [stack], column_key=column_key)

    def _add_morph_group(
        self,
        parent_layout: QVBoxLayout,
        grouped_fields: Dict[str, List[FieldSpec]],
        *,
        column_key: str,
    ) -> None:
        fields = sorted(grouped_fields.get("Morph", []), key=self._field_sort_tuple)
        if not fields:
            return

        controller = next((field for field in fields if field.key == "Morph.TargetShape"), None)
        if controller is None:
            self._add_grouped_fields(parent_layout, fields, forced_group_name="Morph", column_key=column_key)
            return

        detail_fields = [field for field in fields if field.key != controller.key]
        self._morph_detail_keys = tuple(field.key for field in detail_fields)

        box = AccordionGroupBox("Morph")
        _finalize_group_box(box)
        self._register_group_box(box, column_key=column_key)
        box_layout = box.body_layout()
        box_layout.setAlignment(Qt.AlignTop)

        controller_grid = QGridLayout()
        configure_single_column_grid(controller_grid)
        controller_label = self._make_field_label(controller.label)
        controller_editor = self._ensure_editor(controller)
        controller_grid.addWidget(controller_label, 0, 0)
        controller_grid.addWidget(controller_editor, 0, 1)
        self._record_field_metadata(controller.key, box, column_key, controller_label)
        box_layout.addLayout(controller_grid)

        if detail_fields:
            detail_frame = ContextFrame("Details")
            if column_key == "Geometry":
                detail_grid = self._build_geometry_dense_grid()
                for field in detail_fields:
                    label = self._make_field_label(field.label, compact=True)
                    editor = self._ensure_editor(field)
                    editor_widget = editor
                    if field.key in {"Morph.AllowShrinkage", "Morph.CornerRadius"}:
                        label.setFixedWidth(LABEL_COLUMN_WIDTH)
                        shifted = QWidget()
                        shifted_row = QHBoxLayout(shifted)
                        shifted_row.setContentsMargins(10, 0, 0, 0)
                        shifted_row.setSpacing(0)
                        shifted_row.addWidget(editor, 0, Qt.AlignLeft)
                        shifted_row.addStretch(1)
                        editor_widget = shifted
                    detail_grid.add_cell(label, editor_widget)
                    self._record_field_metadata(field.key, box, column_key, label)
                detail_frame.content_layout.addWidget(detail_grid)
            else:
                detail_widget = QWidget()
                detail_grid = QGridLayout(detail_widget)
                configure_two_column_grid(detail_grid)
                for index, field in enumerate(detail_fields):
                    label = self._make_field_label(field.label)
                    editor = self._ensure_editor(field)
                    row = index // 2
                    label_col, input_col = _two_column_positions(index % 2)
                    detail_grid.addWidget(label, row, label_col)
                    detail_grid.addWidget(editor, row, input_col, 1, 1, alignment=Qt.AlignLeft)
                    self._record_field_metadata(field.key, box, column_key, label)
                detail_frame.content_layout.addWidget(detail_widget)
            self._morph_detail_frame = detail_frame
            box_layout.addWidget(detail_frame)

        parent_layout.addWidget(box)

    def _add_rollback_group(
        self,
        parent_layout: QVBoxLayout,
        grouped_fields: Dict[str, List[FieldSpec]],
        *,
        column_key: str,
    ) -> None:
        fields = sorted(grouped_fields.get("Rollback", []), key=self._field_sort_tuple)
        if not fields:
            return

        controller = next((field for field in fields if field.key == "Rollback"), None)
        if controller is None:
            self._add_grouped_fields(parent_layout, fields, forced_group_name="Rollback", column_key=column_key)
            return

        detail_fields = [field for field in fields if field.key != controller.key]
        self._rollback_detail_keys = tuple(field.key for field in detail_fields)

        box = AccordionGroupBox("Rollback")
        _finalize_group_box(box)
        self._register_group_box(box, column_key=column_key)
        box_layout = box.body_layout()
        box_layout.setAlignment(Qt.AlignTop)

        controller_grid = QGridLayout()
        configure_single_column_grid(controller_grid)
        controller_label = self._make_field_label(controller.label)
        controller_editor = self._ensure_editor(controller)
        controller_grid.addWidget(controller_label, 0, 0)
        controller_grid.addWidget(controller_editor, 0, 1)
        self._record_field_metadata(controller.key, box, column_key, controller_label)
        box_layout.addLayout(controller_grid)

        if detail_fields:
            detail_frame = ContextFrame("Details")
            if column_key == "Geometry":
                detail_grid = self._build_geometry_dense_grid()
                for field in detail_fields:
                    label = self._make_field_label(field.label, compact=True)
                    editor = self._ensure_editor(field)
                    detail_grid.add_cell(label, editor)
                    self._record_field_metadata(field.key, box, column_key, label)
                detail_frame.content_layout.addWidget(detail_grid)
            else:
                detail_widget = QWidget()
                detail_grid = QGridLayout(detail_widget)
                configure_two_column_grid(detail_grid)
                for index, field in enumerate(detail_fields):
                    label = self._make_field_label(field.label)
                    editor = self._ensure_editor(field)
                    row = index // 2
                    label_col, input_col = _two_column_positions(index % 2)
                    detail_grid.addWidget(label, row, label_col)
                    detail_grid.addWidget(editor, row, input_col, 1, 1, alignment=Qt.AlignLeft)
                    self._record_field_metadata(field.key, box, column_key, label)
                detail_frame.content_layout.addWidget(detail_widget)
            self._rollback_detail_frame = detail_frame
            box_layout.addWidget(detail_frame)

        parent_layout.addWidget(box)

    def _add_grouped_fields(
        self,
        parent_layout: QVBoxLayout,
        fields: Iterable[FieldSpec],
        *,
        forced_group_name: Optional[str] = None,
        column_key: str,
    ) -> None:
        grouped: Dict[str, List[FieldSpec]] = {}
        if forced_group_name is not None:
            grouped[forced_group_name] = list(fields)
        else:
            grouped = self._fields_by_group(fields)

        for group_name, group_fields in grouped.items():
            box = AccordionGroupBox(group_name)
            _finalize_group_box(box)
            self._register_group_box(box, column_key=column_key)
            ordered = sorted(group_fields, key=self._field_sort_tuple)
            if column_key == "Geometry":
                dense_grid = self._build_geometry_dense_grid()
                for field in ordered:
                    editor = self._ensure_editor(field)
                    if field.widget_kind == "object":
                        dense_grid.add_full_width_widget(editor)
                        self._record_field_metadata(field.key, box, column_key)
                        continue
                    label = self._make_field_label(field.label, compact=True)
                    dense_grid.add_cell(label, editor)
                    self._record_field_metadata(field.key, box, column_key, label)
                box.body_layout().addWidget(dense_grid)
            else:
                grid_holder = QWidget()
                grid = QGridLayout(grid_holder)
                configure_two_column_grid(grid)
                scalar_index = 0
                object_row = max((len([field for field in ordered if field.widget_kind != "object"]) + 1) // 2, 1)
                for field in ordered:
                    editor = self._ensure_editor(field)
                    if field.widget_kind == "object":
                        grid.addWidget(editor, object_row, 0, 1, 5, alignment=Qt.AlignLeft)
                        self._record_field_metadata(field.key, box, column_key)
                        object_row += 1
                        continue
                    label = self._make_field_label(field.label)
                    row = scalar_index // 2
                    label_col, input_col = _two_column_positions(scalar_index % 2)
                    grid.addWidget(label, row, label_col)
                    grid.addWidget(editor, row, input_col, 1, 1, alignment=Qt.AlignLeft)
                    self._record_field_metadata(field.key, box, column_key, label)
                    scalar_index += 1
                box.body_layout().addWidget(grid_holder)
            parent_layout.addWidget(box)

    def _add_mode_groups(
        self,
        parent_layout: QVBoxLayout,
        stacks: Iterable[ModeStackSpec],
        *,
        column_key: str,
    ) -> None:
        for stack in stacks:
            controller = self._field_specs.get(stack.controller_key)
            if controller is None:
                continue

            box = AccordionGroupBox(stack.label)
            _finalize_group_box(box)
            self._register_group_box(box, column_key=column_key)
            box_layout = box.body_layout()
            box_layout.setAlignment(Qt.AlignTop)

            controller_grid = QGridLayout()
            configure_single_column_grid(controller_grid)
            controller_label = self._make_field_label(controller.label)
            controller_editor = self._ensure_editor(controller)
            controller_grid.addWidget(controller_label, 0, 0)
            controller_grid.addWidget(controller_editor, 0, 1)
            self._record_field_metadata(controller.key, box, column_key, controller_label)
            box_layout.addLayout(controller_grid)

            keyed_pages = [page for page in stack.pages if page.value is not None]
            common_keys: set[str] = set()
            if len(keyed_pages) >= 2:
                common_keys = set(keyed_pages[0].field_keys)
                for page in keyed_pages[1:]:
                    common_keys &= set(page.field_keys)

            if common_keys:
                common_box = ContextFrame("Common")
                if column_key == "Geometry":
                    common_grid = self._build_geometry_dense_grid()
                    for key in self._ordered_keys(common_keys):
                        field = self._field_specs.get(key)
                        if field is None:
                            continue
                        label = self._make_field_label(field.label, compact=True)
                        editor = self._ensure_editor(field)
                        common_grid.add_cell(label, editor)
                        self._record_field_metadata(key, box, column_key, label)
                    common_box.content_layout.addWidget(common_grid)
                else:
                    common_widget = QWidget()
                    common_grid = QGridLayout(common_widget)
                    configure_two_column_grid(common_grid)
                    for index, key in enumerate(self._ordered_keys(common_keys)):
                        field = self._field_specs.get(key)
                        if field is None:
                            continue
                        label = self._make_field_label(field.label)
                        editor = self._ensure_editor(field)
                        row = index // 2
                        label_col, input_col = _two_column_positions(index % 2)
                        common_grid.addWidget(label, row, label_col)
                        common_grid.addWidget(editor, row, input_col, 1, 1, alignment=Qt.AlignLeft)
                        self._record_field_metadata(key, box, column_key, label)
                    common_box.content_layout.addWidget(common_widget)
                box_layout.addWidget(common_box)

            pages = AutoSizingStackedWidget()
            pages.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            index_by_value: Dict[Optional[int], int] = {}
            for page in stack.pages:
                page_fields = self._ordered_keys([key for key in page.field_keys if key not in common_keys])
                page_single_field = self._field_specs.get(page_fields[0]) if len(page_fields) == 1 else None
                single_object_page = bool(
                    page_single_field is not None and page_single_field.widget_kind == "object"
                )

                if page.value is None and not page_fields:
                    page_widget = QWidget()
                    page_layout = QVBoxLayout(page_widget)
                    page_layout.setContentsMargins(0, 0, 0, 0)
                    page_layout.setSpacing(0)
                    page_index = pages.addWidget(page_widget)
                    index_by_value[page.value] = page_index
                    continue

                if single_object_page:
                    page_widget = QWidget()
                    page_layout = QVBoxLayout(page_widget)
                    page_layout.setContentsMargins(0, 0, 0, 0)
                    page_layout.setSpacing(0)
                    field = page_single_field
                    if field is not None:
                        editor = self._ensure_editor(field)
                        page_layout.addWidget(editor)
                        self._record_field_metadata(field.key, box, column_key)
                    page_index = pages.addWidget(page_widget)
                    index_by_value[page.value] = page_index
                    continue

                page_widget = ContextFrame(page.label)
                if column_key == "Geometry":
                    dense_grid = self._build_geometry_dense_grid()
                    for key in page_fields:
                        field = self._field_specs.get(key)
                        if field is None:
                            continue
                        label = self._make_field_label(field.label, compact=True)
                        editor = self._ensure_editor(field)
                        dense_grid.add_cell(label, editor)
                        self._record_field_metadata(key, box, column_key, label)
                    page_widget.content_layout.addWidget(dense_grid)
                else:
                    page_grid_widget = QWidget()
                    page_grid = QGridLayout(page_grid_widget)
                    configure_two_column_grid(page_grid)
                    for index, key in enumerate(page_fields):
                        field = self._field_specs.get(key)
                        if field is None:
                            continue
                        label = self._make_field_label(field.label)
                        editor = self._ensure_editor(field)
                        row = index // 2
                        label_col, input_col = _two_column_positions(index % 2)
                        page_grid.addWidget(label, row, label_col)
                        page_grid.addWidget(editor, row, input_col, 1, 1, alignment=Qt.AlignLeft)
                        self._record_field_metadata(key, box, column_key, label)
                    page_widget.content_layout.addWidget(page_grid_widget)
                page_index = pages.addWidget(page_widget)
                index_by_value[page.value] = page_index

            box_layout.addWidget(pages)
            pages.currentChanged.connect(lambda *_args, pages=pages: pages.updateGeometry())
            pages.currentChanged.connect(lambda *_args, box=box: box.adjustSize())
            self._mode_widgets[stack.controller_key] = (pages, index_by_value)
            if common_keys:
                self._mode_common_frames[stack.controller_key] = (common_box, tuple(self._ordered_keys(common_keys)))
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
            editor.changed.connect(lambda *_args, key=field.key: self._on_any_field_changed(changed_key=key))  # type: ignore[attr-defined]
        self._wire_blocked_interaction_signals(field.key, editor)
        self._field_editors[field.key] = editor
        return editor

    def _segments_for_editor(self, editor: QWidget) -> List[SegmentedEnumInput]:
        segments: List[SegmentedEnumInput] = []
        if isinstance(editor, ScalarFieldEditor):
            value_widget = editor.value_widget()
            if isinstance(value_widget, SegmentedEnumInput):
                segments.append(value_widget)
            maybe_segment = getattr(value_widget, "segment", None)
            if isinstance(maybe_segment, SegmentedEnumInput):
                segments.append(maybe_segment)
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

    def _wire_blocked_interaction_signals(self, field_key: str, editor: QWidget) -> None:
        for segment in self._segments_for_editor(editor):
            if bool(getattr(segment, "_blocked_signal_wired", False)):
                continue
            segment._blocked_signal_wired = True  # type: ignore[attr-defined]
            segment.blocked_interaction.connect(  # type: ignore[attr-defined]
                lambda value, cause_key, message, key=field_key: self._on_segment_blocked_interaction(
                    key,
                    value,
                    str(cause_key or ""),
                    str(message or ""),
                )
            )

    def _on_segment_blocked_interaction(self, target_key: str, _value: Any, cause_key: str, message: str) -> None:
        self.blocked_interaction.emit(str(target_key), str(cause_key), str(message))

    def _apply_blocked_option_state(self) -> None:
        compat_ui = dict(self._compat_ui_state or {})
        blocked_by_key = {
            str(key): dict(value)
            for key, value in dict(compat_ui.get("blocked_options", {}) or {}).items()
            if isinstance(value, Mapping)
        }
        for key, editor in self._field_editors.items():
            blocked_options = blocked_by_key.get(str(key), {})
            for segment in self._segments_for_editor(editor):
                segment.set_blocked_option_map(blocked_options)

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
            stacked.setFixedHeight(max(stacked.sizeHint().height(), 0))
        self._refresh_mode_common_frames()

    def _refresh_mode_common_frames(self) -> None:
        for controller_key, (frame, keys) in self._mode_common_frames.items():
            controller_value = self._controller_value(controller_key)
            if controller_key == "GCurve.Type" and controller_value is None:
                frame.setVisible(False)
                continue
            if self._compat_visible_keys:
                frame.setVisible(
                    any((key in self._compat_visible_keys) and (key not in self._compat_hidden_keys) for key in keys)
                )
            else:
                frame.setVisible(True)

    def _sync_mode_side_effects(self) -> None:
        profile_value = self._controller_value("Throat.Profile")
        rosse_editor = self._field_editors.get("R-OSSE")
        if rosse_editor is None or not hasattr(rosse_editor, "set_is_set") or not hasattr(rosse_editor, "is_set"):
            return
        should_enable = bool(profile_value == 2)
        current_enabled = bool(rosse_editor.is_set())  # type: ignore[attr-defined]
        if should_enable != current_enabled:
            rosse_editor.set_is_set(should_enable)  # type: ignore[attr-defined]

    def _on_any_field_changed(self, *_: Any, changed_key: Optional[str] = None) -> None:
        if self._suspend_emit or self._handling_field_change:
            return
        self._handling_field_change = True
        try:
            if changed_key:
                self._last_changed_key = str(changed_key)
            self._refresh_mode_stacks()
            self._sync_mode_side_effects()
            self._apply_local_disclosure()
            self._refresh_section_headers()
            self.changed.emit(self.payload())
        finally:
            self._handling_field_change = False

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

    def _morph_enabled(self) -> bool:
        value = self._controller_value("Morph.TargetShape")
        if value is None:
            return False
        return int(value) != 0

    def _apply_conditional_visibility(
        self,
        keys: Tuple[str, ...],
        *,
        enabled: bool,
        context_frame: Optional[ContextFrame],
    ) -> bool:
        changed = False
        any_visible = False

        for key in keys:
            editor = self._field_editors.get(key)
            if editor is None:
                continue
            label = self._field_labels.get(key)
            compat_visible = key in self._compat_visible_keys if self._compat_visible_keys else True
            if key in self._compat_hidden_keys:
                compat_visible = False
            should_show = bool(enabled and compat_visible)
            any_visible = any_visible or should_show
            if label is not None:
                label.setVisible(should_show)
            editor.setVisible(should_show)
            if not should_show and hasattr(editor, "set_is_set") and hasattr(editor, "current_state"):
                state = editor.current_state()  # type: ignore[attr-defined]
                if getattr(state, "is_set", False):
                    editor.set_is_set(False)  # type: ignore[attr-defined]
                    changed = True

        if context_frame is not None:
            context_frame.setVisible(any_visible)
        return changed

    def _apply_local_disclosure(self) -> bool:
        changed = False
        gcurve_value = self._controller_value("GCurve.Type")
        coverage_enabled = gcurve_value is None
        changed = self._apply_conditional_visibility(
            (self._coverage_angle_key,),
            enabled=coverage_enabled,
            context_frame=None,
        ) or changed
        changed = self._apply_conditional_visibility(
            self._morph_detail_keys,
            enabled=self._morph_enabled(),
            context_frame=self._morph_detail_frame,
        ) or changed
        changed = self._apply_conditional_visibility(
            self._rollback_detail_keys,
            enabled=self._rollback_enabled(),
            context_frame=self._rollback_detail_frame,
        ) or changed
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

    @staticmethod
    def _risk_rank(value: str) -> int:
        order = {"fatal": 0, "warn": 1, "incomplete": 2, "info": 3, "ok": 4, "neutral": 5}
        return order.get(str(value).lower(), 99)

    @staticmethod
    def _repolish(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()

    @staticmethod
    def _normalize_helper_decimals(text: str) -> str:
        def repl(match: re.Match[str]) -> str:
            token = match.group(0)
            try:
                value = float(token.replace(",", "."))
            except ValueError:
                return token
            return f"{value:.2f}"

        return _HELPER_NUMBER_RE.sub(repl, str(text or ""))

    def _install_risk_hover_filter(self, widget: QWidget) -> None:
        widget_id = id(widget)
        if widget_id in self._risk_hover_installed:
            return
        widget.installEventFilter(self)
        self._risk_hover_installed[widget_id] = widget

    def _popup_side_for_widget(self, widget: QWidget) -> str:
        form_center_x = self.mapToGlobal(self.rect().center()).x()
        widget_center_x = widget.mapToGlobal(widget.rect().center()).x()
        return "right" if widget_center_x < form_center_x else "left"

    def _show_pending_risk_tooltip(self) -> None:
        target = self._pending_hover_widget
        self._pending_hover_widget = None
        if target is None or not target.isVisible():
            return
        text = str(target.property("riskTooltipText") or "").strip()
        severity = str(target.property("riskTooltipSeverity") or "warn").strip().lower()
        if not text or severity not in {"warn", "fatal"}:
            return
        display = self._normalize_helper_decimals(text)
        side = self._popup_side_for_widget(target)
        self._risk_popup.show_for(target, display, severity, side)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if isinstance(watched, QWidget):
            etype = event.type()
            if etype in {QEvent.Enter, QEvent.HoverEnter}:
                text = str(watched.property("riskTooltipText") or "").strip()
                severity = str(watched.property("riskTooltipSeverity") or "").strip().lower()
                if text and severity in {"warn", "fatal"}:
                    self._pending_hover_widget = watched
                    self._hover_tooltip_timer.start()
            elif etype in {QEvent.Leave, QEvent.HoverLeave, QEvent.FocusOut, QEvent.MouseButtonPress}:
                if self._pending_hover_widget is watched:
                    self._pending_hover_widget = None
                    self._hover_tooltip_timer.stop()
                self._risk_popup.hide()
            elif etype == QEvent.ToolTip:
                text = str(watched.property("riskTooltipText") or "").strip()
                severity = str(watched.property("riskTooltipSeverity") or "").strip().lower()
                if text and severity in {"warn", "fatal"}:
                    display = self._normalize_helper_decimals(text)
                    side = self._popup_side_for_widget(watched)
                    self._risk_popup.show_for(watched, display, severity, side)
                    return True
        return super().eventFilter(watched, event)

    def _clear_risk_highlights(self) -> None:
        for widget_id, widget in list(self._risk_widgets.items()):
            if widget is None:
                continue
            widget.setProperty("fieldState", "neutral")
            widget.setProperty("riskLevel", "")
            widget.setProperty("riskTooltipText", "")
            widget.setProperty("riskTooltipSeverity", "")
            if widget_id in self._risk_original_tooltips:
                widget.setToolTip(self._risk_original_tooltips[widget_id])
            self._repolish(widget)
        self._pending_hover_widget = None
        self._hover_tooltip_timer.stop()
        self._risk_popup.hide()
        QToolTip.hideText()
        self._risk_widgets.clear()
        self._risk_original_tooltips.clear()
        self._section_counts_by_box = {}
        for boxes in self._accordion_groups_by_column.values():
            for box in boxes:
                box.setProperty("blockState", "neutral")
                self._repolish(box)
        for editor in self._field_editors.values():
            if hasattr(editor, "set_field_state_visual"):
                editor.set_field_state_visual("neutral")  # type: ignore[attr-defined]
            if hasattr(editor, "clear_helper_message"):
                editor.clear_helper_message()  # type: ignore[attr-defined]
        self._refresh_section_headers()

    def _risk_target_for_key(self, key: str) -> Optional[QWidget]:
        editor = self._field_editors.get(key)
        if editor is None:
            return None
        target: QWidget = editor
        if hasattr(editor, "value_widget"):
            maybe_target = editor.value_widget()  # type: ignore[attr-defined]
            if isinstance(maybe_target, QWidget):
                target = maybe_target
        if hasattr(target, "edit"):
            maybe_edit = getattr(target, "edit")
            if isinstance(maybe_edit, QWidget):
                return maybe_edit
        if hasattr(target, "combo"):
            maybe_combo = getattr(target, "combo")
            if isinstance(maybe_combo, QWidget):
                return maybe_combo
        if hasattr(target, "segment"):
            maybe_segment = getattr(target, "segment")
            if isinstance(maybe_segment, QWidget):
                return maybe_segment
        if hasattr(target, "props_frame"):
            maybe_frame = getattr(target, "props_frame")
            if isinstance(maybe_frame, QWidget):
                return maybe_frame
        return target

    def _field_is_set(self, key: str) -> bool:
        editor = self._field_editors.get(key)
        if editor is None or editor.isHidden():
            return False
        if not hasattr(editor, "current_state"):
            return False
        state = editor.current_state()  # type: ignore[attr-defined]
        return bool(getattr(state, "is_set", False))

    def _risk_tooltip(self, issues: List[Dict[str, Any]]) -> str:
        ranked = sorted(
            [item for item in issues if isinstance(item, dict)],
            key=lambda item: self._risk_rank(str(item.get("severity", "info"))),
        )
        if not ranked:
            return ""
        issue = ranked[0]
        key = str(issue.get("field_key") or issue.get("key") or "").strip()
        message = self._normalize_helper_decimals(str(issue.get("message", "")).strip())
        suggestion = self._normalize_helper_decimals(str(issue.get("suggestion", "")).strip())
        if message and key and not message.lower().startswith(key.lower()):
            message = f"{key}: {message}"
        if message and suggestion:
            return f"{message}\n\n{suggestion}"
        return message or suggestion

    def apply_ui_risks(self, issues: List[Dict[str, Any]]) -> None:
        self._clear_risk_highlights()
        grouped_active: Dict[str, List[Dict[str, Any]]] = {}
        grouped_all: Dict[str, List[Dict[str, Any]]] = {}
        section_counts: Dict[int, Dict[str, int]] = {}
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            severity = str(issue.get("severity", "")).strip().lower()
            if severity not in {"warn", "fatal", "ok", "info", "incomplete"}:
                continue
            key = str(issue.get("field_key") or issue.get("key") or "").strip()
            if not key:
                continue
            if key not in self._field_editors:
                continue
            target = self._risk_target_for_key(key)
            if target is None:
                continue
            grouped_all.setdefault(key, []).append(issue)
            if self._field_is_set(key):
                grouped_active.setdefault(key, []).append(issue)

        active_keys = [key for key in self._field_editors.keys() if self._field_is_set(key)]
        key_status: Dict[str, str] = {key: "ok" for key in active_keys}
        for key in active_keys:
            key_issues = grouped_active.get(key, [])
            target = self._risk_target_for_key(key)
            if target is None:
                continue
            severities = {str(item.get("severity", "info")).lower() for item in key_issues}
            if "fatal" in severities:
                severity = "fatal"
            elif "warn" in severities:
                severity = "warn"
            elif "incomplete" in severities:
                severity = "incomplete"
            else:
                severity = "ok"
            key_status[key] = severity
            box = self._field_group_boxes.get(key)
            if box is not None:
                counts = section_counts.setdefault(id(box), {"ok": 0, "warn": 0, "fatal": 0, "incomplete": 0, "active": 0})
                counts["active"] = int(counts.get("active", 0)) + 1
                if severity in {"ok", "warn", "fatal", "incomplete"}:
                    counts[severity] = int(counts.get(severity, 0)) + 1
            editor = self._field_editors.get(key)
            if editor is not None and hasattr(editor, "set_field_state_visual"):
                editor.set_field_state_visual("ok" if severity == "incomplete" else severity)  # type: ignore[attr-defined]
            target_id = id(target)
            self._install_risk_hover_filter(target)
            self._risk_widgets[target_id] = target
            self._risk_original_tooltips[target_id] = target.toolTip()
            visual_severity = "neutral" if severity == "incomplete" else severity
            target.setProperty("fieldState", visual_severity)
            target.setProperty("riskLevel", visual_severity)
            if severity in {"warn", "fatal"}:
                tooltip = self._risk_tooltip(key_issues)
                if tooltip:
                    base_tooltip = self._risk_original_tooltips.get(target_id, "")
                    target.setToolTip(f"{base_tooltip}\n\n{tooltip}".strip() if base_tooltip else tooltip)
                    target.setProperty("riskTooltipText", tooltip)
                    target.setProperty("riskTooltipSeverity", severity)
            else:
                target.setProperty("riskTooltipText", "")
                target.setProperty("riskTooltipSeverity", "")
            self._repolish(target)

        rank = {"fatal": 0, "warn": 1, "incomplete": 2, "ok": 3, "info": 4}
        for key, key_issues in grouped_all.items():
            if key in key_status:
                continue
            highest = "info"
            for issue in key_issues:
                severity = str(issue.get("severity", "info")).strip().lower()
                if rank.get(severity, 99) < rank.get(highest, 99):
                    highest = severity
            if highest not in {"fatal", "warn", "incomplete"}:
                continue
            box = self._field_group_boxes.get(key)
            if box is None:
                continue
            counts = section_counts.setdefault(id(box), {"ok": 0, "warn": 0, "fatal": 0, "incomplete": 0, "active": 0})
            counts[highest] = int(counts.get(highest, 0)) + 1

        self._section_counts_by_box = section_counts
        for boxes in self._accordion_groups_by_column.values():
            for box in boxes:
                counts = section_counts.get(id(box), {})
                if int(counts.get("fatal", 0)) > 0:
                    level = "fatal"
                elif int(counts.get("warn", 0)) > 0:
                    level = "warn"
                else:
                    level = "neutral"
                box.setProperty("blockState", level)
                self._repolish(box)
        self._refresh_section_headers()

    def apply_compatibility(self, state: Dict[str, Any]) -> None:
        self._compat_state = dict(state)
        self._compat_ui_state = dict(state.get("compat_ui_state", {}) or {})
        self._compat_hidden_keys = {
            str(item)
            for item in list(self._compat_ui_state.get("hidden_keys", []) or [])
            if str(item).strip()
        }
        visible_keys = set(str(item) for item in list(state.get("visible_keys", []) or []))
        locked_keys = set(str(item) for item in list(state.get("locked_keys", []) or []))
        blocked_keys = {
            str(item)
            for item in list(self._compat_ui_state.get("blocked_keys", []) or [])
            if str(item).strip()
        }
        self._compat_visible_keys = set(visible_keys)

        self._suspend_emit = True
        changed_hidden = False
        try:
            for key, editor in self._field_editors.items():
                is_visible = (key in visible_keys) and (key not in self._compat_hidden_keys)
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
                    editor.set_locked((key in locked_keys) or (key in blocked_keys))  # type: ignore[attr-defined]
                target = self._risk_target_for_key(key)
                if isinstance(target, QWidget):
                    is_blocked = key in blocked_keys
                    target.setProperty("compatBlocked", "true" if is_blocked else "false")
                    self._repolish(target)
            changed_hidden = self._apply_local_disclosure() or changed_hidden
            self._apply_blocked_option_state()
        finally:
            self._suspend_emit = False

        self._refresh_mode_stacks()
        self._refresh_section_headers()
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

    def open_first_issue_section(self, issues: Sequence[Dict[str, Any]]) -> bool:
        grouped: Dict[str, str] = {}
        rank = {"fatal": 0, "warn": 1, "incomplete": 2, "ok": 3, "info": 4}
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            key = str(issue.get("field_key") or issue.get("key") or "").strip()
            if not key:
                continue
            severity = str(issue.get("severity", "")).strip().lower()
            if severity not in {"fatal", "warn", "incomplete"}:
                continue
            current = grouped.get(key)
            if current is None or rank.get(severity, 99) < rank.get(current, 99):
                grouped[key] = severity

        for wanted in ("fatal", "warn", "incomplete"):
            for key, severity in grouped.items():
                if severity != wanted:
                    continue
                if self.focus_issue_key(key):
                    return True
        return False

    def field_is_set_map(self) -> Dict[str, bool]:
        return {key: self._field_is_set(key) for key in self._field_editors.keys()}

    def field_label_map(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for key, spec in self._field_specs.items():
            label = self._field_labels.get(key)
            result[key] = str(label.text()).strip() if label is not None else str(spec.label or key)
        return result

    def field_section_map(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for key, box in self._field_group_boxes.items():
            result[key] = str(box.title() or "General")
        return result

    def last_changed_key(self) -> Optional[str]:
        value = str(self._last_changed_key or "").strip()
        return value or None

    def flash_cause_key(self, key: str) -> None:
        target = self._risk_target_for_key(str(key))
        if not isinstance(target, QWidget):
            return
        target.setProperty("compatCauseFlash", "true")
        self._repolish(target)

        def _clear() -> None:
            target.setProperty("compatCauseFlash", "false")
            self._repolish(target)

        QTimer.singleShot(460, _clear)

    def focus_issue_key(self, key: str) -> bool:
        key_s = str(key or "").strip()
        if not key_s:
            return False
        box = self._field_group_boxes.get(key_s)
        if box is None:
            return False
        box.set_collapsed(False)
        column_key = self._field_column_map.get(key_s)
        scroll: Optional[QScrollArea] = None
        if column_key == "Geometry":
            scroll = self.geometry_scroll
        elif column_key == "Mesh":
            scroll = self.mesh_scroll

        editor = self._field_editors.get(key_s)
        target = self._risk_target_for_key(key_s)
        if scroll is not None and target is not None:
            scroll.ensureWidgetVisible(target, 18, 36)
        if isinstance(editor, QWidget):
            editor.setFocus(Qt.OtherFocusReason)
        if isinstance(target, QWidget):
            target.setFocus(Qt.OtherFocusReason)
            target.setProperty("issueFlash", "true")
            self._repolish(target)
            QTimer.singleShot(650, lambda w=target: self._clear_issue_flash(w))
        box.header_row().setFocus()
        return True

    def _clear_issue_flash(self, widget: QWidget) -> None:
        if widget is None:
            return
        widget.setProperty("issueFlash", "false")
        self._repolish(widget)


class FormBuilder:
    """Constructs metadata-driven parameter forms from FieldSpec schema."""

    def __init__(self, schema: FormSchema | None = None) -> None:
        self.schema = schema or build_project_form_schema()

    def build(self, parent: QWidget | None = None) -> ParameterForm:
        return ParameterForm(schema=self.schema, parent=parent)
