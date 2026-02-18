"""Shared layout metrics for PROJECT parameter forms."""

from __future__ import annotations

from dataclasses import dataclass

try:
    from PySide6.QtWidgets import QGridLayout
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for form metrics.") from exc


@dataclass(frozen=True)
class FormMetrics:
    # Shared form geometry for 1920x1080 @ 100% scaling.
    label_width: int = 170
    input_width: int = 180
    editor_total_width: int = 264
    unit_label_width: int = 40
    action_width: int = 44
    control_height: int = 32
    label_to_input_gap: int = 8
    column_gap: int = 20
    row_gap: int = 7
    margin_left: int = 10
    margin_top: int = 8
    margin_right: int = 10
    margin_bottom: int = 8


FORM_METRICS = FormMetrics()


def configure_two_column_grid(grid: QGridLayout, metrics: FormMetrics = FORM_METRICS) -> None:
    grid.setContentsMargins(
        metrics.margin_left,
        metrics.margin_top,
        metrics.margin_right,
        metrics.margin_bottom,
    )
    grid.setHorizontalSpacing(metrics.label_to_input_gap)
    grid.setVerticalSpacing(metrics.row_gap)

    # Columns: label0, input0, spacer, label1, input1
    spacer_width = max(metrics.column_gap - (2 * metrics.label_to_input_gap), 0)
    grid.setColumnMinimumWidth(2, spacer_width)
    grid.setColumnStretch(0, 0)
    grid.setColumnStretch(1, 0)
    grid.setColumnStretch(2, 0)
    grid.setColumnStretch(3, 0)
    grid.setColumnStretch(4, 0)


def configure_single_column_grid(grid: QGridLayout, metrics: FormMetrics = FORM_METRICS) -> None:
    grid.setContentsMargins(
        metrics.margin_left,
        metrics.margin_top,
        metrics.margin_right,
        metrics.margin_bottom,
    )
    grid.setHorizontalSpacing(metrics.label_to_input_gap)
    grid.setVerticalSpacing(metrics.row_gap)
    grid.setColumnStretch(0, 0)
    grid.setColumnStretch(1, 0)
