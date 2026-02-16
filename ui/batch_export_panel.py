"""Batch export settings panel with presets and advanced list editing."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QDoubleValidator, QIntValidator
    from PySide6.QtWidgets import (
        QCheckBox,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for batch export panel.") from exc


def _float_or_default(text: str, default: float) -> float:
    value = str(text or "").strip().replace(",", ".")
    try:
        return float(value)
    except Exception:
        return float(default)


def _int_or_default(text: str, default: int) -> int:
    value = str(text or "").strip()
    try:
        return int(value)
    except Exception:
        return int(default)


class BatchExportPanel(QFrame):
    changed = Signal()

    _PRESET_SPECS: Dict[str, Dict[str, Any]] = {
        "spl": {
            "id": "preset_spl",
            "tool": "vacs",
            "graph_kind": "spl",
            "variant": "main",
            "format": "txt",
            "output_name_template": "{version_id}_{graph_kind}.{format}",
        },
        "impedance": {
            "id": "preset_impedance",
            "tool": "vacs",
            "graph_kind": "impedance",
            "variant": "main",
            "format": "txt",
            "output_name_template": "{version_id}_{graph_kind}.{format}",
        },
        "polar": {
            "id": "preset_polar",
            "tool": "vacs",
            "graph_kind": "polar",
            "variant": "main",
            "format": "txt",
            "output_name_template": "{version_id}_{graph_kind}.{format}",
        },
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectSummaryPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("Exports")
        title.setObjectName("SummaryTitle")
        root.addWidget(title)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        self.freq_start = QLineEdit("500")
        self.freq_start.setValidator(QDoubleValidator(self.freq_start))
        self.freq_end = QLineEdit("15000")
        self.freq_end.setValidator(QDoubleValidator(self.freq_end))
        self.num_points = QLineEdit("16")
        self.num_points.setValidator(QIntValidator(1, 1_000_000, self.num_points))
        form.addWidget(QLabel("f_start [Hz]"), 0, 0)
        form.addWidget(self.freq_start, 0, 1)
        form.addWidget(QLabel("f_end [Hz]"), 0, 2)
        form.addWidget(self.freq_end, 0, 3)
        form.addWidget(QLabel("points"), 0, 4)
        form.addWidget(self.num_points, 0, 5)
        root.addLayout(form)

        preset_box = QGroupBox("Presets")
        preset_layout = QHBoxLayout(preset_box)
        preset_layout.setContentsMargins(8, 8, 8, 8)
        preset_layout.setSpacing(10)
        self.preset_spl = QCheckBox("SPL")
        self.preset_impedance = QCheckBox("Impedance")
        self.preset_polar = QCheckBox("Polar")
        preset_layout.addWidget(self.preset_spl)
        preset_layout.addWidget(self.preset_impedance)
        preset_layout.addWidget(self.preset_polar)
        preset_layout.addStretch(1)
        root.addWidget(preset_box)

        adv_box = QGroupBox("Advanced")
        adv_layout = QVBoxLayout(adv_box)
        adv_layout.setContentsMargins(8, 8, 8, 8)
        adv_layout.setSpacing(8)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "graph_kind", "variant", "format", "output template"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        adv_layout.addWidget(self.table, 1)

        button_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.remove_btn = QPushButton("Remove")
        button_row.addWidget(self.add_btn)
        button_row.addWidget(self.remove_btn)
        button_row.addStretch(1)
        adv_layout.addLayout(button_row)
        root.addWidget(adv_box, 1)

        self.freq_start.textChanged.connect(lambda _text: self.changed.emit())
        self.freq_end.textChanged.connect(lambda _text: self.changed.emit())
        self.num_points.textChanged.connect(lambda _text: self.changed.emit())
        self.table.itemChanged.connect(lambda _item: self._on_table_changed())
        self.preset_spl.toggled.connect(lambda enabled: self._on_preset_toggled("spl", enabled))
        self.preset_impedance.toggled.connect(lambda enabled: self._on_preset_toggled("impedance", enabled))
        self.preset_polar.toggled.connect(lambda enabled: self._on_preset_toggled("polar", enabled))
        self.add_btn.clicked.connect(self._add_empty_row)
        self.remove_btn.clicked.connect(self._remove_selected_row)

    def _make_item(self, value: Any) -> QTableWidgetItem:
        return QTableWidgetItem(str("" if value is None else value))

    def _row_spec(self, row_index: int) -> Dict[str, Any]:
        def text(col: int) -> str:
            item = self.table.item(row_index, col)
            return "" if item is None else str(item.text() or "").strip()

        return {
            "id": text(0),
            "tool": "vacs",
            "graph_kind": text(1),
            "variant": text(2) or None,
            "format": (text(3) or "txt").lower(),
            "options": {},
            "output_name_template": text(4) or "{version_id}_{graph_kind}.{format}",
        }

    def _append_spec_row(self, spec: Dict[str, Any]) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, self._make_item(spec.get("id", "")))
        self.table.setItem(row, 1, self._make_item(spec.get("graph_kind", "")))
        self.table.setItem(row, 2, self._make_item(spec.get("variant", "main")))
        self.table.setItem(row, 3, self._make_item(spec.get("format", "txt")))
        self.table.setItem(
            row,
            4,
            self._make_item(spec.get("output_name_template", "{version_id}_{graph_kind}.{format}")),
        )

    def _has_spec_id(self, spec_id: str) -> bool:
        wanted = str(spec_id).strip()
        if not wanted:
            return False
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and str(item.text()).strip() == wanted:
                return True
        return False

    def _remove_spec_id(self, spec_id: str) -> None:
        wanted = str(spec_id).strip()
        if not wanted:
            return
        for row in range(self.table.rowCount() - 1, -1, -1):
            item = self.table.item(row, 0)
            if item is not None and str(item.text()).strip() == wanted:
                self.table.removeRow(row)

    def _sync_presets_from_rows(self) -> None:
        ids = {self.table.item(row, 0).text().strip() for row in range(self.table.rowCount()) if self.table.item(row, 0)}
        self.preset_spl.blockSignals(True)
        self.preset_impedance.blockSignals(True)
        self.preset_polar.blockSignals(True)
        self.preset_spl.setChecked("preset_spl" in ids)
        self.preset_impedance.setChecked("preset_impedance" in ids)
        self.preset_polar.setChecked("preset_polar" in ids)
        self.preset_spl.blockSignals(False)
        self.preset_impedance.blockSignals(False)
        self.preset_polar.blockSignals(False)

    def _on_preset_toggled(self, preset_key: str, enabled: bool) -> None:
        spec = dict(self._PRESET_SPECS[preset_key])
        spec_id = str(spec.get("id", "")).strip()
        if enabled and not self._has_spec_id(spec_id):
            self._append_spec_row(spec)
        if not enabled:
            self._remove_spec_id(spec_id)
        self.changed.emit()

    def _add_empty_row(self) -> None:
        index = self.table.rowCount() + 1
        self._append_spec_row(
            {
                "id": f"user_{index}",
                "graph_kind": "",
                "variant": "main",
                "format": "txt",
                "output_name_template": "{version_id}_{graph_kind}.{format}",
            }
        )
        self.changed.emit()

    def _remove_selected_row(self) -> None:
        index = self.table.currentRow()
        if index < 0:
            return
        self.table.removeRow(index)
        self._sync_presets_from_rows()
        self.changed.emit()

    def _on_table_changed(self) -> None:
        self._sync_presets_from_rows()
        self.changed.emit()

    def sim_export_params_payload(self) -> Dict[str, Any]:
        specs: List[Dict[str, Any]] = []
        for row in range(self.table.rowCount()):
            spec = self._row_spec(row)
            if not str(spec.get("id", "")).strip():
                continue
            if not str(spec.get("graph_kind", "")).strip():
                continue
            specs.append(spec)

        exports: Dict[str, Dict[str, Any]] = {}
        for spec in specs:
            key = str(spec.get("graph_kind", "")).strip()
            if not key:
                continue
            exports[key] = {"enabled": True, "params": {}}

        return {
            "freq_start_hz": _float_or_default(self.freq_start.text(), 500.0),
            "freq_end_hz": _float_or_default(self.freq_end.text(), 15000.0),
            "num_points": _int_or_default(self.num_points.text(), 16),
            "exports": exports,
            "export_specs": specs,
        }

    def set_from_payload(self, payload: Dict[str, Any]) -> None:
        raw = dict(payload or {})
        self.freq_start.setText(str(raw.get("freq_start_hz", 500.0)))
        self.freq_end.setText(str(raw.get("freq_end_hz", 15000.0)))
        self.num_points.setText(str(raw.get("num_points", 16)))
        self.table.setRowCount(0)
        for spec in list(raw.get("export_specs", []) or []):
            if not isinstance(spec, dict):
                continue
            self._append_spec_row(spec)
        self._sync_presets_from_rows()

    def set_from_batch(self, batch: Any) -> None:
        settings = getattr(batch, "sim_export_settings", None)
        if settings is None:
            self.set_from_payload({})
            return
        if isinstance(settings, dict):
            self.set_from_payload(settings)
            return
        to_dict = getattr(settings, "to_dict", None)
        if callable(to_dict):
            self.set_from_payload(dict(to_dict() or {}))
            return
        self.set_from_payload({})

    def export_spec_count(self) -> int:
        return len(list(self.sim_export_params_payload().get("export_specs", []) or []))
