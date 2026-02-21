"""Batch export settings panel with compact presets and advanced dialog."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set

try:
    from PySide6.QtCore import QPoint, Qt, Signal
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
        QScrollArea,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for batch export panel.") from exc


def _int_or_default(text: str, default: int) -> int:
    value = str(text or "").strip()
    try:
        return int(value)
    except Exception:
        return int(default)


def _int_or_none(text: str) -> Optional[int]:
    value = str(text or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _float_or_default(text: str, default: float) -> float:
    value = str(text or "").strip().replace(",", ".")
    try:
        return float(value)
    except Exception:
        return float(default)


def _normalize_sweep_mode(value: str) -> str:
    mode = str(value or "single").strip().lower()
    return mode if mode in {"single", "combined"} else "single"


def _normalize_sim_mode(value: str) -> str:
    mode = str(value or "free_standing").strip().lower()
    return mode if mode in {"free_standing", "infinite_baffle"} else "free_standing"


@dataclass
class _SimpleGraphState:
    enabled: bool = False

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "_SimpleGraphState":
        return cls(enabled=bool(payload.get("enabled", False)))

    def to_dict(self) -> Dict[str, Any]:
        return {"enabled": bool(self.enabled)}


@dataclass
class _PolarCardState:
    enabled: bool = False
    polar_name: str = ""
    map_angle_start: int = 0
    map_angle_end: int = 90
    map_angle_steps: int = 19
    distance_m: float = 2.0
    offset: int = 145
    inclination: int = 90
    norm_angle: int = 0

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "_PolarCardState":
        return cls(
            enabled=bool(payload.get("enabled", False)),
            polar_name=str(payload.get("polar_name", "") or "").strip(),
            map_angle_start=int(payload.get("map_angle_start", 0) or 0),
            map_angle_end=int(payload.get("map_angle_end", 90) or 90),
            map_angle_steps=max(1, int(payload.get("map_angle_steps", 19) or 19)),
            distance_m=float(payload.get("distance_m", 2.0) or 2.0),
            offset=int(payload.get("offset", 145) or 145),
            inclination=int(payload.get("inclination", 90) or 90),
            norm_angle=int(payload.get("norm_angle", 0) or 0),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "polar_name": str(self.polar_name or "").strip(),
            "map_angle_start": int(self.map_angle_start),
            "map_angle_end": int(self.map_angle_end),
            "map_angle_steps": max(1, int(self.map_angle_steps)),
            "distance_m": float(self.distance_m),
            "offset": int(self.offset),
            "inclination": int(self.inclination),
            "norm_angle": int(self.norm_angle),
        }


@dataclass
class _AdvancedState:
    spl: _SimpleGraphState
    impedance: _SimpleGraphState
    polars: List[_PolarCardState]

    @classmethod
    def defaults(cls) -> "_AdvancedState":
        return cls(
            spl=_SimpleGraphState(enabled=False),
            impedance=_SimpleGraphState(enabled=False),
            polars=[_PolarCardState(enabled=False) for _ in range(3)],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "spl": self.spl.to_dict(),
            "impedance": self.impedance.to_dict(),
            "polars": [item.to_dict() for item in list(self.polars)],
        }


class _AdvancedDialog(QDialog):
    def __init__(self, state: _AdvancedState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("framelessShell", True)
        self.setModal(True)
        self.setMinimumSize(760, 620)
        self._drag_offset: Optional[QPoint] = None

        self._initial = state.to_dict()
        self._current = _AdvancedState(
            spl=_SimpleGraphState.from_dict(state.spl.to_dict()),
            impedance=_SimpleGraphState.from_dict(state.impedance.to_dict()),
            polars=[_PolarCardState.from_dict(item.to_dict()) for item in list(state.polars)],
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("FramelessShell")
        outer.addWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        title_bar = QWidget()
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel("Advanced Export Settings")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_btn = QPushButton("X")
        close_btn.setObjectName("WindowCloseButton")
        close_btn.setFixedSize(28, 24)
        close_btn.clicked.connect(self.reject)
        title_row.addWidget(close_btn, alignment=Qt.AlignRight)
        root.addWidget(title_bar)
        title_bar.mousePressEvent = self._title_mouse_press  # type: ignore[assignment]
        title_bar.mouseMoveEvent = self._title_mouse_move  # type: ignore[assignment]
        title_bar.mouseReleaseEvent = self._title_mouse_release  # type: ignore[assignment]

        scroll = QScrollArea()
        scroll.setObjectName("BatchAdvancedScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root.addWidget(scroll, 1)
        content = QWidget()
        scroll.setWidget(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        hint = QLabel(
            "ATH guide defaults: ABEC.Polars:SPL_V uses MapAngleRange, Distance, Offset, Inclination, NormAngle."
        )
        hint.setObjectName("SummaryText")
        hint.setWordWrap(True)
        content_layout.addWidget(hint)

        cards_top = QHBoxLayout()
        cards_top.setContentsMargins(0, 0, 0, 0)
        cards_top.setSpacing(10)
        cards_top.addWidget(self._build_simple_card("SPL", self._current.spl, graph_key="spl"), 1)
        cards_top.addWidget(self._build_simple_card("Impedance", self._current.impedance, graph_key="impedance"), 1)
        content_layout.addLayout(cards_top)

        polar_title = QLabel("Polars")
        polar_title.setObjectName("SummaryTitle")
        content_layout.addWidget(polar_title)
        for idx in range(3):
            content_layout.addWidget(self._build_polar_card(index=idx, state=self._current.polars[idx]))
        content_layout.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Cancel")
        apply_btn = QPushButton("Apply")
        apply_btn.setObjectName("PrimaryButton")
        cancel_btn.clicked.connect(self.reject)
        apply_btn.clicked.connect(self.accept)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(apply_btn)
        root.addLayout(buttons)

    def _title_mouse_press(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def _title_mouse_move(self, event) -> None:  # type: ignore[override]
        if self._drag_offset is None:
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        self.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def _title_mouse_release(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        event.accept()

    def _build_simple_card(self, title: str, state: _SimpleGraphState, *, graph_key: str) -> QWidget:
        card = QFrame()
        card.setObjectName("ProjectSummaryPanel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(QLabel(title))
        top.addStretch(1)
        active = QPushButton("Activate")
        active.setCheckable(True)
        active.setProperty("segment", "true")
        active.setFixedHeight(32)
        active.setChecked(bool(state.enabled))
        active.toggled.connect(lambda value, key=graph_key: self._set_simple(key, bool(value)))
        top.addWidget(active)
        layout.addLayout(top)
        fixed = QLabel("Format: txt (fixed)")
        fixed.setObjectName("SummaryMeta")
        layout.addWidget(fixed)
        return card

    def _build_polar_card(self, *, index: int, state: _PolarCardState) -> QWidget:
        card = QFrame()
        card.setObjectName("ProjectSummaryPanel")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(QLabel(f"Polar {index + 1}"))
        top.addStretch(1)
        active = QPushButton("Activate Polar")
        active.setCheckable(True)
        active.setProperty("segment", "true")
        active.setFixedHeight(32)
        active.setChecked(bool(state.enabled))
        top.addWidget(active)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        name_edit = QLineEdit(str(state.polar_name or ""))
        name_edit.setPlaceholderText("Polars Name")
        map_start = QLineEdit(str(int(state.map_angle_start)))
        map_start.setValidator(QIntValidator(-360, 360, map_start))
        map_end = QLineEdit(str(int(state.map_angle_end)))
        map_end.setValidator(QIntValidator(-360, 360, map_end))
        map_steps = QLineEdit(str(max(1, int(state.map_angle_steps))))
        map_steps.setValidator(QIntValidator(1, 999, map_steps))
        distance = QLineEdit(str(float(state.distance_m)))
        distance.setValidator(QDoubleValidator(distance))
        offset = QLineEdit(str(int(state.offset)))
        offset.setValidator(QIntValidator(-9999, 9999, offset))
        inclination = QLineEdit(str(int(state.inclination)))
        inclination.setValidator(QIntValidator(-360, 360, inclination))
        norm_angle = QLineEdit(str(int(state.norm_angle)))
        norm_angle.setValidator(QIntValidator(-360, 360, norm_angle))

        controls: List[QWidget] = [
            name_edit,
            map_start,
            map_end,
            map_steps,
            distance,
            offset,
            inclination,
            norm_angle,
        ]

        def _toggle(enabled: bool) -> None:
            for control in controls:
                control.setEnabled(bool(enabled))

        _toggle(bool(state.enabled))
        active.toggled.connect(_toggle)
        active.toggled.connect(lambda value, idx=index: self._set_polar(idx, "enabled", bool(value)))
        name_edit.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "polar_name", str(value)))
        map_start.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "map_angle_start", _int_or_default(value, 0)))
        map_end.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "map_angle_end", _int_or_default(value, 90)))
        map_steps.textChanged.connect(
            lambda value, idx=index: self._set_polar(idx, "map_angle_steps", max(1, _int_or_default(value, 19)))
        )
        distance.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "distance_m", _float_or_default(value, 2.0)))
        offset.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "offset", _int_or_default(value, 145)))
        inclination.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "inclination", _int_or_default(value, 90)))
        norm_angle.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "norm_angle", _int_or_default(value, 0)))

        row = 0
        grid.addWidget(QLabel("Polars Name"), row, 0)
        grid.addWidget(name_edit, row, 1)
        row += 1
        grid.addWidget(QLabel("MapAngle Start"), row, 0)
        grid.addWidget(map_start, row, 1)
        row += 1
        grid.addWidget(QLabel("MapAngle End"), row, 0)
        grid.addWidget(map_end, row, 1)
        row += 1
        grid.addWidget(QLabel("MapAngle Steps"), row, 0)
        grid.addWidget(map_steps, row, 1)
        row += 1
        grid.addWidget(QLabel("Distance [m]"), row, 0)
        grid.addWidget(distance, row, 1)
        row += 1
        grid.addWidget(QLabel("Offset"), row, 0)
        grid.addWidget(offset, row, 1)
        row += 1
        grid.addWidget(QLabel("Inclination"), row, 0)
        grid.addWidget(inclination, row, 1)
        row += 1
        grid.addWidget(QLabel("Norm Angle"), row, 0)
        grid.addWidget(norm_angle, row, 1)
        layout.addLayout(grid)
        return card

    def _set_simple(self, graph_key: str, enabled: bool) -> None:
        if graph_key == "spl":
            self._current.spl.enabled = bool(enabled)
        else:
            self._current.impedance.enabled = bool(enabled)

    def _set_polar(self, index: int, key: str, value: Any) -> None:
        if index < 0 or index >= len(self._current.polars):
            return
        setattr(self._current.polars[index], str(key), value)

    def state(self) -> _AdvancedState:
        return _AdvancedState(
            spl=_SimpleGraphState.from_dict(self._current.spl.to_dict()),
            impedance=_SimpleGraphState.from_dict(self._current.impedance.to_dict()),
            polars=[_PolarCardState.from_dict(item.to_dict()) for item in list(self._current.polars)],
        )

    def touched_graphs(self) -> Set[str]:
        before = dict(self._initial)
        after = self.state().to_dict()
        touched: Set[str] = set()
        if dict(before.get("spl", {})) != dict(after.get("spl", {})):
            touched.add("spl")
        if dict(before.get("impedance", {})) != dict(after.get("impedance", {})):
            touched.add("impedance")
        if list(before.get("polars", [])) != list(after.get("polars", [])):
            touched.add("polar")
        return touched


class BatchExportPanel(QFrame):
    changed = Signal()
    open_enclosure = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectSummaryPanel")
        self._advanced_state = _AdvancedState.defaults()
        self.setMinimumHeight(240)
        self.setMaximumHeight(260)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("Exports")
        title.setObjectName("SummaryTitle")
        root.addWidget(title)

        settings_grid = QGridLayout()
        settings_grid.setContentsMargins(0, 0, 0, 0)
        settings_grid.setHorizontalSpacing(8)
        settings_grid.setVerticalSpacing(8)

        self.simulation_mode = QComboBox()
        self.simulation_mode.setObjectName("BatchExportCombo")
        self.simulation_mode.addItem("Free Standing", "free_standing")
        self.simulation_mode.addItem("Infinite Baffle", "infinite_baffle")
        self.sweep_mode = QComboBox()
        self.sweep_mode.setObjectName("BatchExportCombo")
        self.sweep_mode.addItems(["single", "combined"])
        self.freq_start = QLineEdit("500")
        self.freq_start.setValidator(QIntValidator(1, 1_000_000, self.freq_start))
        self.freq_end = QLineEdit("15000")
        self.freq_end.setValidator(QIntValidator(1, 1_000_000, self.freq_end))
        self.num_points = QLineEdit("16")
        self.num_points.setValidator(QIntValidator(1, 1_000_000, self.num_points))
        self.mesh_frequency = QLineEdit("")
        self.mesh_frequency.setValidator(QIntValidator(1, 1_000_000, self.mesh_frequency))
        self.mesh_frequency.setPlaceholderText("optional")
        for field in (
            self.simulation_mode,
            self.sweep_mode,
            self.freq_start,
            self.freq_end,
            self.num_points,
            self.mesh_frequency,
        ):
            field.setProperty("batchField", "true")

        settings_grid.addWidget(self._field_stack("Simulation Mode", self.simulation_mode), 0, 0)
        settings_grid.addWidget(self._field_stack("Sweep Mode", self.sweep_mode), 0, 1)
        settings_grid.addWidget(self._field_stack("Mesh Freq [Hz]", self.mesh_frequency), 0, 2)
        settings_grid.addWidget(self._field_stack("Freq Start [Hz]", self.freq_start), 1, 0)
        settings_grid.addWidget(self._field_stack("Freq End [Hz]", self.freq_end), 1, 1)
        settings_grid.addWidget(self._field_stack("Points", self.num_points), 1, 2)
        settings_grid.setColumnStretch(0, 1)
        settings_grid.setColumnStretch(1, 1)
        settings_grid.setColumnStretch(2, 1)
        root.addLayout(settings_grid)

        self.footer_row = QWidget()
        self.footer_row.setObjectName("BatchExportsFooter")
        self.footer_layout = QGridLayout(self.footer_row)
        self.footer_layout.setContentsMargins(0, 0, 0, 0)
        self.footer_layout.setHorizontalSpacing(8)
        self.footer_layout.setVerticalSpacing(6)
        self.footer_layout.setColumnStretch(0, 1)
        self.footer_layout.setColumnStretch(1, 0)

        self.footer_left = QWidget()
        left_layout = QHBoxLayout(self.footer_left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(6)
        self.default_export_hint = QLabel("Default exports:")
        self.default_export_hint.setObjectName("BatchSummaryMeta")
        left_layout.addWidget(self.default_export_hint, 0, Qt.AlignLeft | Qt.AlignVCenter)
        self.default_export_chip = QLabel("Polars (H/V/D)")
        self.default_export_chip.setObjectName("SummaryChip")
        self.default_export_chip.setToolTip("Auto-generated by default: SPL_H, SPL_V, SPL_D txt exports.")
        left_layout.addWidget(self.default_export_chip, 0, Qt.AlignLeft | Qt.AlignVCenter)
        left_layout.addStretch(1)

        self.footer_buttons = QWidget()
        footer_buttons_layout = QHBoxLayout(self.footer_buttons)
        footer_buttons_layout.setContentsMargins(0, 0, 0, 0)
        footer_buttons_layout.setSpacing(8)
        self.enclosure_btn = QPushButton("Simulate Enclosure")
        self.enclosure_btn.setObjectName("BatchPrimaryButton")
        self.enclosure_btn.setFixedHeight(30)
        self.enclosure_btn.setMinimumWidth(148)
        self.advanced_btn = QPushButton("Advanced")
        self.advanced_btn.setObjectName("BatchSecondaryButton")
        self.advanced_btn.setFixedHeight(30)
        self.advanced_btn.setMinimumWidth(112)
        footer_buttons_layout.addWidget(self.enclosure_btn)
        footer_buttons_layout.addWidget(self.advanced_btn)
        root.addWidget(self.footer_row)
        root.addStretch(1)

        self._footer_layout_mode = ""
        self._apply_footer_layout_mode()

        self.sweep_mode.currentTextChanged.connect(lambda _value: self.changed.emit())
        self.simulation_mode.currentIndexChanged.connect(lambda _value: self.changed.emit())
        self.freq_start.textChanged.connect(lambda _value: self.changed.emit())
        self.freq_end.textChanged.connect(lambda _value: self.changed.emit())
        self.num_points.textChanged.connect(lambda _value: self.changed.emit())
        self.mesh_frequency.textChanged.connect(lambda _value: self.changed.emit())
        self.advanced_btn.clicked.connect(self._open_advanced)
        self.enclosure_btn.clicked.connect(self.open_enclosure.emit)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._apply_footer_layout_mode()

    def _apply_footer_layout_mode(self) -> None:
        compact = int(self.width()) < 620
        mode = "compact" if compact else "wide"
        if mode == self._footer_layout_mode:
            return

        while self.footer_layout.count():
            self.footer_layout.takeAt(0)
        if compact:
            self.footer_layout.addWidget(self.footer_left, 0, 0, 1, 2)
            self.footer_layout.addWidget(self.footer_buttons, 1, 0, 1, 2, Qt.AlignRight)
        else:
            self.footer_layout.addWidget(self.footer_left, 0, 0, 1, 1)
            self.footer_layout.addWidget(self.footer_buttons, 0, 1, 1, 1, Qt.AlignRight)
        self._footer_layout_mode = mode

    @staticmethod
    def _field_stack(label: str, widget: QWidget) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        text = QLabel(str(label))
        text.setObjectName("BatchSummaryMeta")
        layout.addWidget(text)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if hasattr(widget, "setFixedHeight"):
            widget.setFixedHeight(32)
        layout.addWidget(widget)
        return box

    def _open_advanced(self) -> None:
        dialog = _AdvancedDialog(self._advanced_state, parent=self.window())
        if dialog.exec() != QDialog.Accepted:
            return
        self._advanced_state = dialog.state()
        self.changed.emit()

    def sweep_mode_value(self) -> str:
        return _normalize_sweep_mode(str(self.sweep_mode.currentText() or "single"))

    def set_sweep_mode(self, value: str) -> None:
        self.sweep_mode.setCurrentText(_normalize_sweep_mode(value))

    def simulation_mode_value(self) -> str:
        data = self.simulation_mode.currentData()
        return _normalize_sim_mode(str(data if data is not None else "free_standing"))

    def set_simulation_mode(self, value: str) -> None:
        target = _normalize_sim_mode(value)
        index = self.simulation_mode.findData(target)
        self.simulation_mode.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _default_polar_specs() -> List[Dict[str, Any]]:
        base_options = {
            "map_angle_range": [0, 90, 19],
            "distance_m": 2.0,
        }
        return [
            {
                "id": "default_polar_spl_h",
                "tool": "vacs",
                "graph_kind": "polar",
                "variant": "main",
                "format": "txt",
                "options": {
                    **base_options,
                    "polar_name": "SPL_H",
                    "offset": 145,
                },
                "output_name_template": "{version_id}_{graph_kind}_{export_id}.{format}",
            },
            {
                "id": "default_polar_spl_v",
                "tool": "vacs",
                "graph_kind": "polar",
                "variant": "main",
                "format": "txt",
                "options": {
                    **base_options,
                    "polar_name": "SPL_V",
                    "offset_from_length_mm": 40,
                    "inclination": 90,
                },
                "output_name_template": "{version_id}_{graph_kind}_{export_id}.{format}",
            },
            {
                "id": "default_polar_spl_d",
                "tool": "vacs",
                "graph_kind": "polar",
                "variant": "main",
                "format": "txt",
                "options": {
                    **base_options,
                    "polar_name": "SPL_D",
                    "offset_from_length_mm": 40,
                    "inclination": 42,
                },
                "output_name_template": "{version_id}_{graph_kind}_{export_id}.{format}",
            },
        ]

    def _advanced_specs(self) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        if self._advanced_state.spl.enabled:
            specs.append(
                {
                    "id": "adv_spl",
                    "tool": "vacs",
                    "graph_kind": "spl",
                    "variant": "main",
                    "format": "txt",
                    "options": {},
                    "output_name_template": "{version_id}_{graph_kind}.{format}",
                }
            )
        if self._advanced_state.impedance.enabled:
            specs.append(
                {
                    "id": "adv_impedance",
                    "tool": "vacs",
                    "graph_kind": "impedance",
                    "variant": "main",
                    "format": "txt",
                    "options": {},
                    "output_name_template": "{version_id}_{graph_kind}.{format}",
                }
            )
        for idx, polar in enumerate(list(self._advanced_state.polars), start=1):
            if not polar.enabled:
                continue
            polar_name = str(polar.polar_name or "").strip() or f"SPL_V_{idx}"
            specs.append(
                {
                    "id": f"adv_polar_{idx}",
                    "tool": "vacs",
                    "graph_kind": "polar",
                    "variant": "main",
                    "format": "txt",
                    "options": {
                        "polar_name": polar_name,
                        "map_angle_range": [
                            int(polar.map_angle_start),
                            int(polar.map_angle_end),
                            int(polar.map_angle_steps),
                        ],
                        "distance_m": float(polar.distance_m),
                        "offset": int(polar.offset),
                        "inclination": int(polar.inclination),
                        "norm_angle": int(polar.norm_angle),
                    },
                    "output_name_template": "{version_id}_{graph_kind}_{export_id}.{format}",
                }
            )
        return specs

    @staticmethod
    def _dedupe_specs_by_graph(specs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ordered: List[Dict[str, Any]] = []
        by_key: Dict[str, int] = {}
        for spec in list(specs):
            graph_kind = str(spec.get("graph_kind", "")).strip().lower()
            spec_id = str(spec.get("id", "")).strip().lower()
            key = spec_id if graph_kind == "polar" else graph_kind
            if key in by_key:
                ordered[by_key[key]] = dict(spec)
            else:
                by_key[key] = len(ordered)
                ordered.append(dict(spec))
        return ordered

    def validation_issues(self) -> List[Dict[str, Any]]:
        issues: List[Dict[str, Any]] = []
        seen: Dict[str, int] = {}
        for idx, polar in enumerate(list(self._advanced_state.polars), start=1):
            if not polar.enabled:
                continue
            token = str(polar.polar_name or "").strip().lower()
            if not token:
                continue
            first_idx = seen.get(token)
            if first_idx is None:
                seen[token] = idx
                continue
            issues.append(
                {
                    "severity": "fatal",
                    "rule_id": "export_duplicate_polar_name",
                    "field_key": "sim_export_params.export_specs",
                    "message": f"Polar name '{polar.polar_name}' is duplicated in Polar {first_idx} and Polar {idx}.",
                }
            )
        return issues

    def sim_export_params_payload(self) -> Dict[str, Any]:
        specs = self._dedupe_specs_by_graph(self._advanced_specs())
        exports: Dict[str, Dict[str, Any]] = {}
        for spec in list(specs):
            graph_kind = str(spec.get("graph_kind", "")).strip().lower()
            if not graph_kind:
                continue
            exports[graph_kind] = {"enabled": True, "params": dict(spec.get("options", {}) or {})}
        mesh_freq = _int_or_none(self.mesh_frequency.text())
        return {
            "freq_start_hz": float(_int_or_default(self.freq_start.text(), 500)),
            "freq_end_hz": float(_int_or_default(self.freq_end.text(), 15000)),
            "num_points": _int_or_default(self.num_points.text(), 16),
            "mesh_frequency": None if mesh_freq is None else float(mesh_freq),
            "simulation_mode": self.simulation_mode_value(),
            "auto_default_polar_exports": True,
            "exports": exports,
            "export_specs": specs,
        }

    def _reset_advanced(self) -> None:
        self._advanced_state = _AdvancedState.defaults()

    def _set_from_specs(self, specs: Sequence[Dict[str, Any]]) -> None:
        self._reset_advanced()

        polar_slot = 0
        for spec in list(specs):
            if not isinstance(spec, dict):
                continue
            graph_kind = str(spec.get("graph_kind", "")).strip().lower()
            spec_id = str(spec.get("id", "")).strip().lower()
            options = dict(spec.get("options", {}) or {})
            if spec_id == "preset_spl" or graph_kind == "spl":
                self._advanced_state.spl.enabled = True
                continue
            if spec_id == "preset_impedance" or graph_kind == "impedance":
                self._advanced_state.impedance.enabled = True
                continue
            if graph_kind == "polar" and polar_slot < len(self._advanced_state.polars):
                map_range = list(options.get("map_angle_range", [0, 90, 19]) or [0, 90, 19])
                while len(map_range) < 3:
                    map_range.append([0, 90, 19][len(map_range)])
                self._advanced_state.polars[polar_slot] = _PolarCardState(
                    enabled=True,
                    polar_name=str(options.get("polar_name", "") or "").strip(),
                    map_angle_start=int(map_range[0] or 0),
                    map_angle_end=int(map_range[1] or 90),
                    map_angle_steps=max(1, int(map_range[2] or 19)),
                    distance_m=float(options.get("distance_m", 2.0) or 2.0),
                    offset=int(options.get("offset", 145) or 145),
                    inclination=int(options.get("inclination", 90) or 90),
                    norm_angle=int(options.get("norm_angle", 0) or 0),
                )
                polar_slot += 1

    def set_from_payload(self, payload: Dict[str, Any]) -> None:
        raw = dict(payload or {})
        self.freq_start.setText(str(int(float(raw.get("freq_start_hz", 500) or 500))))
        self.freq_end.setText(str(int(float(raw.get("freq_end_hz", 15000) or 15000))))
        self.num_points.setText(str(int(raw.get("num_points", 16) or 16)))
        mesh_frequency = raw.get("mesh_frequency")
        self.mesh_frequency.setText("" if mesh_frequency is None else str(int(float(mesh_frequency))))
        if "sweep_mode" in raw:
            self.set_sweep_mode(str(raw.get("sweep_mode", "single") or "single"))
        self.set_simulation_mode(str(raw.get("simulation_mode", "free_standing") or "free_standing"))
        self._set_from_specs([item for item in list(raw.get("export_specs", []) or []) if isinstance(item, dict)])

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
        specs = list(self.sim_export_params_payload().get("export_specs", []) or [])
        if specs:
            return len(specs)
        return len(self._default_polar_specs())
