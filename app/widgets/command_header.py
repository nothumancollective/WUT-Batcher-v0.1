"""Reusable command header with responsive command bar and wrapped status chips."""

from __future__ import annotations

from typing import Sequence

from app.widgets.flow_layout import FlowLayout
from ui.text_utils import safe_text

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtWidgets import (
        QFrame,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QStackedLayout,
        QVBoxLayout,
        QWidget,
        QWidgetAction,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for CommandHeaderWidget.") from exc


def _clamp(min_value: int, value: int, max_value: int) -> int:
    return max(int(min_value), min(int(value), int(max_value)))


class CommandHeaderWidget(QFrame):
    """Shared command header for pages with command actions + status chips."""

    _WIDE_BREAKPOINT = 900
    _WIDE_TO_NARROW = 880
    _NARROW_TO_WIDE = 920

    def __init__(self, *, context_label: str = "Batch", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandHeaderWidget")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self._layout_mode = ""
        self._estimate_chips: list[str] = []
        self._issue_messages: list[str] = []
        self._fatal_count = 0
        self._warn_count = 0
        self._incomplete_count = 0
        self._issues_menu: QMenu | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        self._name_group = QWidget(self)
        name_layout = QHBoxLayout(self._name_group)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.setSpacing(6)
        self.name_label = QLabel(str(context_label).strip() or "Batch")
        self.name_label.setObjectName("BatchCommandLabel")
        self.batch_name_edit = QLineEdit(self)
        self.batch_name_edit.setPlaceholderText("Batch Name")
        self.batch_name_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        name_layout.addWidget(self.name_label, 0, Qt.AlignLeft | Qt.AlignVCenter)
        name_layout.addWidget(self.batch_name_edit, 1, Qt.AlignVCenter)

        self._actions_group = QWidget(self)
        actions_layout = QHBoxLayout(self._actions_group)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(8)
        self.save_button = QPushButton("Save Batch", self)
        self.save_button.setObjectName("BatchSecondaryButton")
        self.run_button = QPushButton("Run Batch", self)
        self.run_button.setObjectName("BatchRunButton")
        self.save_button.setToolTip("Save current batch configuration")
        self.run_button.setToolTip("Run simulation batch with current configuration")
        self.save_button.setMinimumWidth(120)
        self.run_button.setMinimumWidth(120)
        actions_layout.addWidget(self.save_button, 0, Qt.AlignRight | Qt.AlignVCenter)
        actions_layout.addWidget(self.run_button, 0, Qt.AlignRight | Qt.AlignVCenter)

        command_wrap = QWidget(self)
        self._command_stack = QStackedLayout(command_wrap)
        self._command_stack.setContentsMargins(0, 0, 0, 0)
        self._command_stack.setSpacing(0)

        self._wide_page = QWidget(self)
        self._wide_layout = QHBoxLayout(self._wide_page)
        self._wide_layout.setContentsMargins(0, 0, 0, 0)
        self._wide_layout.setSpacing(8)

        self._narrow_page = QWidget(self)
        self._narrow_layout = QVBoxLayout(self._narrow_page)
        self._narrow_layout.setContentsMargins(0, 0, 0, 0)
        self._narrow_layout.setSpacing(6)
        self._narrow_actions_row = QWidget(self._narrow_page)
        self._narrow_actions_layout = QHBoxLayout(self._narrow_actions_row)
        self._narrow_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._narrow_actions_layout.setSpacing(0)

        self._command_stack.addWidget(self._wide_page)
        self._command_stack.addWidget(self._narrow_page)
        root.addWidget(command_wrap)

        status_wrap = QWidget(self)
        status_wrap.setObjectName("CommandStatusDeck")
        status_layout = QHBoxLayout(status_wrap)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(0)
        self._chips_wrap = QWidget(status_wrap)
        self._chips_flow = FlowLayout(self._chips_wrap, margin=0, hspacing=6, vspacing=6)
        self._chips_wrap.setLayout(self._chips_flow)
        status_layout.addWidget(self._chips_wrap, 1)
        root.addWidget(status_wrap)

        self.issues_chip = QPushButton("No issues", self)
        self.issues_chip.setObjectName("CommandIssuesChip")
        self.issues_chip.setToolTip("No validation issues.")
        self.issues_chip.setCursor(Qt.PointingHandCursor)
        self.issues_chip.clicked.connect(self._show_issue_popover)

        self.apply_responsive_layout(self._WIDE_BREAKPOINT)
        self._rebuild_status_chips()

    def current_layout_mode(self) -> str:
        return str(self._layout_mode or "wide")

    def apply_responsive_layout(self, available_width: int) -> None:
        width = max(int(available_width), 1)
        next_mode = self._layout_mode
        if not next_mode:
            next_mode = "narrow" if width < self._WIDE_BREAKPOINT else "wide"
        elif self._layout_mode == "wide":
            next_mode = "narrow" if width < self._WIDE_TO_NARROW else "wide"
        else:
            next_mode = "wide" if width > self._NARROW_TO_WIDE else "narrow"
        if next_mode != self._layout_mode:
            self._mount_command_groups(next_mode)
        max_width = _clamp(320, int(width * 0.45), 720)
        self.batch_name_edit.setMinimumWidth(240)
        self.batch_name_edit.setMaximumWidth(max_width)

    def set_estimate_chips(self, chips: Sequence[str]) -> None:
        cleaned = [safe_text(item).strip() for item in list(chips or []) if safe_text(item).strip()]
        self._estimate_chips = cleaned
        self._rebuild_status_chips()

    def set_issue_state(
        self,
        *,
        messages: Sequence[str],
        fatal_count: int,
        warn_count: int,
        incomplete_count: int,
    ) -> None:
        self._issue_messages = [safe_text(item).strip() for item in list(messages or []) if safe_text(item).strip()]
        self._fatal_count = max(int(fatal_count), 0)
        self._warn_count = max(int(warn_count), 0)
        self._incomplete_count = max(int(incomplete_count), 0)
        self._rebuild_status_chips()

    def _mount_command_groups(self, mode: str) -> None:
        target_mode = "narrow" if str(mode) == "narrow" else "wide"
        self._detach_from_parent_layout(self._name_group)
        self._detach_from_parent_layout(self._actions_group)
        self._clear_layout(self._wide_layout)
        self._clear_layout(self._narrow_layout)
        if target_mode == "wide":
            self._wide_layout.addWidget(self._name_group, 0, Qt.AlignLeft | Qt.AlignVCenter)
            self._wide_layout.addStretch(1)
            self._wide_layout.addWidget(self._actions_group, 0, Qt.AlignRight | Qt.AlignVCenter)
            self._command_stack.setCurrentWidget(self._wide_page)
        else:
            self._narrow_layout.addWidget(self._name_group, 0, Qt.AlignLeft | Qt.AlignVCenter)
            self._clear_layout(self._narrow_actions_layout)
            self._narrow_actions_layout.addStretch(1)
            self._narrow_actions_layout.addWidget(self._actions_group, 0, Qt.AlignRight | Qt.AlignVCenter)
            self._narrow_layout.addWidget(self._narrow_actions_row)
            self._command_stack.setCurrentWidget(self._narrow_page)
        self._layout_mode = target_mode

    @staticmethod
    def _detach_from_parent_layout(widget: QWidget) -> None:
        parent = widget.parentWidget()
        if parent is not None and parent.layout() is not None:
            parent.layout().removeWidget(widget)
        widget.setParent(None)

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            widget.setParent(None)

    def _rebuild_status_chips(self) -> None:
        self._clear_status_chip_widgets()
        for text in self._estimate_chips:
            chip = QLabel(safe_text(text))
            chip.setObjectName("SummaryChip")
            chip.setWordWrap(False)
            self._chips_flow.addWidget(chip)

        issue_text = "No issues"
        severity = "ok"
        if self._fatal_count > 0:
            issue_text = f"Errors: {self._fatal_count}"
            severity = "fatal"
        elif self._warn_count > 0:
            issue_text = f"Warnings: {self._warn_count}"
            severity = "warn"
        elif self._incomplete_count > 0:
            issue_text = f"Incomplete: {self._incomplete_count}"
            severity = "incomplete"

        self.issues_chip.setText(issue_text)
        self.issues_chip.setProperty("severity", severity)
        if self._issue_messages:
            self.issues_chip.setToolTip("\n".join(self._issue_messages[:10]))
        elif self._incomplete_count > 0:
            self.issues_chip.setToolTip("Define required values to run this batch.")
        else:
            self.issues_chip.setToolTip("No validation issues.")
        self.issues_chip.style().unpolish(self.issues_chip)
        self.issues_chip.style().polish(self.issues_chip)
        self.issues_chip.update()
        self._chips_flow.addWidget(self.issues_chip)
        self.updateGeometry()

    def _clear_status_chip_widgets(self) -> None:
        while self._chips_flow.count():
            item = self._chips_flow.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is None:
                continue
            if widget is self.issues_chip:
                widget.setParent(self)
                continue
            widget.deleteLater()

    def _show_issue_popover(self) -> None:
        menu = QMenu(self)
        menu.setObjectName("CommandIssuesPopover")
        window_width = int(self.window().width()) if self.window() is not None else int(self.width())
        content_width = _clamp(280, int(window_width * 0.42), 520)
        content = QWidget(menu)
        content.setMinimumWidth(content_width)
        content.setMaximumWidth(content_width)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 8, 10, 10)
        content_layout.setSpacing(6)

        title = QLabel("Validation issues")
        title.setObjectName("IssuesPanelGroupTitle")
        content_layout.addWidget(title)

        scroll = QScrollArea(content)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMinimumWidth(max(content_width - 20, 220))
        scroll.setMaximumHeight(320)

        body = QWidget(scroll)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(4)
        if self._issue_messages:
            for index, message in enumerate(self._issue_messages, start=1):
                line = QLabel(f"{index}. {message}")
                line.setWordWrap(True)
                line.setObjectName("SummaryMeta")
                body_layout.addWidget(line)
        elif self._incomplete_count > 0:
            line = QLabel("Define required values to run this batch.")
            line.setWordWrap(True)
            line.setObjectName("SummaryMeta")
            body_layout.addWidget(line)
        else:
            line = QLabel("No validation issues.")
            line.setWordWrap(True)
            line.setObjectName("SummaryMeta")
            body_layout.addWidget(line)
        body_layout.addStretch(1)
        scroll.setWidget(body)
        content_layout.addWidget(scroll)

        action = QWidgetAction(menu)
        action.setDefaultWidget(content)
        menu.addAction(action)

        anchor = self.issues_chip.mapToGlobal(QPoint(0, self.issues_chip.height() + 4))
        self._issues_menu = menu
        menu.popup(anchor)
