"""Batch export settings panel with preset buttons and structured graph cards."""

from __future__ import annotations

from typing import Any, Dict, Optional

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QDoubleValidator, QIntValidator
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
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


def _float_or_none(text: str) -> Optional[float]:
    value = str(text or "").strip().replace(",", ".")
    if not value:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _int_or_default(text: str, default: int) -> int:
    value = str(text or "").strip()
    try:
        return int(value)
    except Exception:
        return int(default)


class _GuideDialog(QDialog):
    def __init__(self, *, title: str, body_lines: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.setModal(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)
        for line in list(body_lines):
            label = QLabel(str(line))
            label.setWordWrap(True)
            root.addWidget(label)
        root.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        root.addWidget(close_btn, 0, Qt.AlignRight)


class BatchExportPanel(QFrame):
    changed = Signal()

    _GRAPH_GUIDE: Dict[str, list[str]] = {
        "spl": [
            "Graph: SPL",
            "Export format: text",
            "Delimiter: tab",
            "Decimal separator: .",
            "Export of graph view: ON",
            "Export of parameters: OFF",
            "Metadata: Graph_Type, Graph_Caption, Data_LevelType, Data_Legend",
        ],
        "impedance": [
            "Graph: Impedance",
            "Export format: text",
            "Delimiter: tab",
            "Decimal separator: .",
            "Export of graph view: ON",
            "Export of parameters: OFF",
            "Metadata: Graph_Type, Graph_Caption, Data_LevelType=Impedance10, Data_Legend",
        ],
        "polar": [
            "Graph: Polar",
            "UI preset only (catalog mapping pending).",
            "No active recipe/catalog entry in current repository state.",
        ],
    }

    _GRAPH_DEFS: Dict[str, Dict[str, Any]] = {
        "spl": {
            "id": "preset_spl",
            "tool": "vacs",
            "graph_kind": "spl",
            "variant_default": "main",
            "format_default": "txt",
            "mapped": True,
        },
        "impedance": {
            "id": "preset_impedance",
            "tool": "vacs",
            "graph_kind": "impedance",
            "variant_default": "main",
            "format_default": "txt",
            "mapped": True,
        },
        "polar": {
            "id": "preset_polar",
            "tool": "vacs",
            "graph_kind": "polar",
            "variant_default": "main",
            "format_default": "txt",
            "mapped": False,
        },
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectSummaryPanel")
        self._graph_controls: Dict[str, Dict[str, QWidget]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        title = QLabel("Exports")
        title.setObjectName("SummaryTitle")
        root.addWidget(title)

        settings_grid = QGridLayout()
        settings_grid.setHorizontalSpacing(8)
        settings_grid.setVerticalSpacing(6)

        self.sweep_mode = QComboBox()
        self.sweep_mode.addItems(["single", "combined"])
        self.sweep_mode.setMaximumWidth(140)

        self.freq_start = QLineEdit("500")
        self.freq_start.setValidator(QDoubleValidator(self.freq_start))
        self.freq_end = QLineEdit("15000")
        self.freq_end.setValidator(QDoubleValidator(self.freq_end))
        self.num_points = QLineEdit("16")
        self.num_points.setValidator(QIntValidator(1, 1_000_000, self.num_points))
        self.mesh_frequency = QLineEdit("")
        self.mesh_frequency.setValidator(QDoubleValidator(self.mesh_frequency))
        self.mesh_frequency.setPlaceholderText("optional")

        settings_grid.addWidget(QLabel("Sweep mode"), 0, 0)
        settings_grid.addWidget(self.sweep_mode, 0, 1)
        settings_grid.addWidget(QLabel("f_start [Hz]"), 0, 2)
        settings_grid.addWidget(self.freq_start, 0, 3)
        settings_grid.addWidget(QLabel("f_end [Hz]"), 1, 0)
        settings_grid.addWidget(self.freq_end, 1, 1)
        settings_grid.addWidget(QLabel("points"), 1, 2)
        settings_grid.addWidget(self.num_points, 1, 3)
        settings_grid.addWidget(QLabel("mesh frequency"), 2, 0)
        settings_grid.addWidget(self.mesh_frequency, 2, 1)
        root.addLayout(settings_grid)

        preset_box = QGroupBox("Presets")
        preset_layout = QHBoxLayout(preset_box)
        preset_layout.setContentsMargins(8, 8, 8, 8)
        preset_layout.setSpacing(8)
        self.preset_spl = self._make_preset_button("SPL")
        self.preset_impedance = self._make_preset_button("Impedance")
        self.preset_polar = self._make_preset_button("Polar")
        self.preset_polar.setEnabled(False)
        self.preset_polar.setToolTip("Coming soon: no active graph catalog mapping for polar exports.")
        preset_layout.addWidget(self.preset_spl)
        preset_layout.addWidget(self.preset_impedance)
        preset_layout.addWidget(self.preset_polar)
        preset_layout.addStretch(1)
        root.addWidget(preset_box)

        advanced_box = QGroupBox("Advanced")
        advanced_layout = QVBoxLayout(advanced_box)
        advanced_layout.setContentsMargins(8, 8, 8, 8)
        advanced_layout.setSpacing(8)
        advanced_layout.addWidget(self._make_graph_card("spl", "SPL"))
        advanced_layout.addWidget(self._make_graph_card("impedance", "Impedance"))
        advanced_layout.addWidget(self._make_graph_card("polar", "Polar"))
        root.addWidget(advanced_box, 1)

        self.sweep_mode.currentTextChanged.connect(lambda _value: self.changed.emit())
        self.freq_start.textChanged.connect(lambda _value: self.changed.emit())
        self.freq_end.textChanged.connect(lambda _value: self.changed.emit())
        self.num_points.textChanged.connect(lambda _value: self.changed.emit())
        self.mesh_frequency.textChanged.connect(lambda _value: self.changed.emit())
        self.preset_spl.toggled.connect(lambda checked: self._on_preset_toggled("spl", checked))
        self.preset_impedance.toggled.connect(lambda checked: self._on_preset_toggled("impedance", checked))
        self.preset_polar.toggled.connect(lambda checked: self._on_preset_toggled("polar", checked))

    @staticmethod
    def _make_preset_button(label: str) -> QPushButton:
        button = QPushButton(str(label))
        button.setCheckable(True)
        button.setProperty("segment", "true")
        button.setMinimumHeight(28)
        return button

    def _make_graph_card(self, key: str, title: str) -> QWidget:
        meta = self._GRAPH_DEFS[key]
        mapped = bool(meta.get("mapped", False))

        card = QFrame()
        card.setObjectName("ProjectSummaryPanel")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(8, 8, 8, 8)
        card_layout.setSpacing(6)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(8)
        title_label = QLabel(str(title))
        title_label.setObjectName("SummaryMeta")
        header.addWidget(title_label)
        header.addStretch(1)
        status = QLabel("mapped" if mapped else "coming soon")
        status.setObjectName("SummaryText")
        header.addWidget(status)
        guide_btn = QPushButton("Guide")
        guide_btn.setProperty("segment", "true")
        guide_btn.setMinimumHeight(24)
        guide_btn.clicked.connect(lambda _checked=False, graph_key=key, graph_title=title: self._open_guide(graph_key, graph_title))
        header.addWidget(guide_btn)
        card_layout.addLayout(header)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        variant = QComboBox()
        variant.addItems(["main", "default"])
        fmt = QComboBox()
        fmt.addItems(["txt"])
        if not mapped:
            variant.setEnabled(False)
            fmt.setEnabled(False)
        form.addWidget(QLabel("Variant"), 0, 0)
        form.addWidget(variant, 0, 1)
        form.addWidget(QLabel("Format"), 0, 2)
        form.addWidget(fmt, 0, 3)
        card_layout.addLayout(form)

        variant.currentTextChanged.connect(lambda _value: self.changed.emit())
        fmt.currentTextChanged.connect(lambda _value: self.changed.emit())
        self._graph_controls[key] = {"variant": variant, "format": fmt, "status": status}
        return card

    def _open_guide(self, graph_key: str, graph_title: str) -> None:
        lines = list(self._GRAPH_GUIDE.get(str(graph_key), [])) or ["No guide available."]
        dialog = _GuideDialog(title=f"{graph_title} Guide", body_lines=lines, parent=self.window())
        dialog.exec()

    def _preset_button(self, key: str) -> QPushButton:
        if key == "spl":
            return self.preset_spl
        if key == "impedance":
            return self.preset_impedance
        return self.preset_polar

    def _on_preset_toggled(self, key: str, checked: bool) -> None:
        meta = self._GRAPH_DEFS.get(str(key), {})
        if checked and not bool(meta.get("mapped", False)):
            button = self._preset_button(str(key))
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)
            return
        self.changed.emit()

    def sweep_mode_value(self) -> str:
        value = str(self.sweep_mode.currentText() or "single").strip().lower()
        return value if value in {"single", "combined"} else "single"

    def set_sweep_mode(self, value: str) -> None:
        mode = str(value or "single").strip().lower()
        self.sweep_mode.setCurrentText(mode if mode in {"single", "combined"} else "single")

    def _spec_from_graph(self, graph_key: str) -> Optional[Dict[str, Any]]:
        meta = self._GRAPH_DEFS.get(str(graph_key))
        if not isinstance(meta, dict) or not bool(meta.get("mapped", False)):
            return None
        controls = self._graph_controls.get(str(graph_key), {})
        variant_combo = controls.get("variant")
        format_combo = controls.get("format")
        variant = str(variant_combo.currentText()).strip() if isinstance(variant_combo, QComboBox) else str(meta.get("variant_default", "main"))
        fmt = str(format_combo.currentText()).strip().lower() if isinstance(format_combo, QComboBox) else str(meta.get("format_default", "txt"))
        return {
            "id": str(meta.get("id", "")),
            "tool": str(meta.get("tool", "vacs")),
            "graph_kind": str(meta.get("graph_kind", "")),
            "variant": variant or None,
            "format": fmt or "txt",
            "options": {},
            "output_name_template": "{version_id}_{graph_kind}.{format}",
        }

    def sim_export_params_payload(self) -> Dict[str, Any]:
        specs: list[Dict[str, Any]] = []
        if self.preset_spl.isChecked():
            spec = self._spec_from_graph("spl")
            if isinstance(spec, dict):
                specs.append(spec)
        if self.preset_impedance.isChecked():
            spec = self._spec_from_graph("impedance")
            if isinstance(spec, dict):
                specs.append(spec)
        if self.preset_polar.isChecked():
            spec = self._spec_from_graph("polar")
            if isinstance(spec, dict):
                specs.append(spec)

        exports: Dict[str, Dict[str, Any]] = {}
        for spec in list(specs):
            key = str(spec.get("graph_kind", "")).strip()
            if key:
                exports[key] = {"enabled": True, "params": {}}

        return {
            "freq_start_hz": _float_or_default(self.freq_start.text(), 500.0),
            "freq_end_hz": _float_or_default(self.freq_end.text(), 15000.0),
            "num_points": _int_or_default(self.num_points.text(), 16),
            "mesh_frequency": _float_or_none(self.mesh_frequency.text()),
            "exports": exports,
            "export_specs": specs,
        }

    def _set_presets_from_specs(self, specs: list[Dict[str, Any]]) -> None:
        graph_ids = {str(spec.get("id", "")).strip() for spec in list(specs) if isinstance(spec, dict)}
        graph_kinds = {str(spec.get("graph_kind", "")).strip().lower() for spec in list(specs) if isinstance(spec, dict)}

        self.preset_spl.blockSignals(True)
        self.preset_impedance.blockSignals(True)
        self.preset_polar.blockSignals(True)
        self.preset_spl.setChecked("preset_spl" in graph_ids or "spl" in graph_kinds)
        self.preset_impedance.setChecked("preset_impedance" in graph_ids or "impedance" in graph_kinds)
        # Keep polar disabled until mapping is available.
        self.preset_polar.setChecked(False)
        self.preset_spl.blockSignals(False)
        self.preset_impedance.blockSignals(False)
        self.preset_polar.blockSignals(False)

        for spec in list(specs):
            if not isinstance(spec, dict):
                continue
            graph_key = str(spec.get("graph_kind", "")).strip().lower()
            controls = self._graph_controls.get(graph_key)
            if not isinstance(controls, dict):
                continue
            variant_combo = controls.get("variant")
            fmt_combo = controls.get("format")
            if isinstance(variant_combo, QComboBox):
                variant_combo.setCurrentText(str(spec.get("variant", "main") or "main"))
            if isinstance(fmt_combo, QComboBox):
                fmt_combo.setCurrentText(str(spec.get("format", "txt") or "txt").lower())

    def set_from_payload(self, payload: Dict[str, Any]) -> None:
        raw = dict(payload or {})
        self.freq_start.setText(str(raw.get("freq_start_hz", 500.0)))
        self.freq_end.setText(str(raw.get("freq_end_hz", 15000.0)))
        self.num_points.setText(str(raw.get("num_points", 16)))
        mesh_frequency = raw.get("mesh_frequency")
        self.mesh_frequency.setText("" if mesh_frequency is None else str(mesh_frequency))
        self._set_presets_from_specs([spec for spec in list(raw.get("export_specs", []) or []) if isinstance(spec, dict)])

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
