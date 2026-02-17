"""Batch export settings panel with presets and structured advanced cards."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set

try:
    from PySide6.QtCore import Qt, Signal
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
    variant: str = "main"
    fmt: str = "txt"

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "_SimpleGraphState":
        return cls(
            enabled=bool(payload.get("enabled", False)),
            variant=str(payload.get("variant", "main") or "main").strip() or "main",
            fmt=str(payload.get("fmt", "txt") or "txt").strip().lower() or "txt",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "variant": str(self.variant or "main").strip() or "main",
            "fmt": str(self.fmt or "txt").strip().lower() or "txt",
        }


@dataclass
class _PolarCardState:
    enabled: bool = False
    polar_name: str = ""
    variant: str = "main"
    fmt: str = "txt"
    map_angle_start: int = 0
    map_angle_end: int = 90
    map_angle_steps: int = 19
    distance_m: float = 2.0
    offset: int = 145
    inclination: int = 90

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "_PolarCardState":
        return cls(
            enabled=bool(payload.get("enabled", False)),
            polar_name=str(payload.get("polar_name", "") or "").strip(),
            variant=str(payload.get("variant", "main") or "main").strip() or "main",
            fmt=str(payload.get("fmt", "txt") or "txt").strip().lower() or "txt",
            map_angle_start=int(payload.get("map_angle_start", 0) or 0),
            map_angle_end=int(payload.get("map_angle_end", 90) or 90),
            map_angle_steps=max(1, int(payload.get("map_angle_steps", 19) or 19)),
            distance_m=float(payload.get("distance_m", 2.0) or 2.0),
            offset=int(payload.get("offset", 145) or 145),
            inclination=int(payload.get("inclination", 90) or 90),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "polar_name": str(self.polar_name or "").strip(),
            "variant": str(self.variant or "main").strip() or "main",
            "fmt": str(self.fmt or "txt").strip().lower() or "txt",
            "map_angle_start": int(self.map_angle_start),
            "map_angle_end": int(self.map_angle_end),
            "map_angle_steps": max(1, int(self.map_angle_steps)),
            "distance_m": float(self.distance_m),
            "offset": int(self.offset),
            "inclination": int(self.inclination),
        }


@dataclass
class _AdvancedState:
    spl: _SimpleGraphState
    impedance: _SimpleGraphState
    polars: List[_PolarCardState]

    @classmethod
    def defaults(cls) -> "_AdvancedState":
        return cls(
            spl=_SimpleGraphState(enabled=False, variant="main", fmt="txt"),
            impedance=_SimpleGraphState(enabled=False, variant="main", fmt="txt"),
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
        self.setWindowTitle("Advanced Export Settings")
        self.setModal(True)
        self.setMinimumWidth(760)

        self._initial = state.to_dict()
        self._current = _AdvancedState(
            spl=_SimpleGraphState.from_dict(state.spl.to_dict()),
            impedance=_SimpleGraphState.from_dict(state.impedance.to_dict()),
            polars=[_PolarCardState.from_dict(item.to_dict()) for item in list(state.polars)],
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        hint = QLabel(
            "ATH guide defaults: Polar -> ABEC.Polars:SPL_V with MapAngleRange, Distance, Offset, Inclination."
        )
        hint.setObjectName("SummaryText")
        hint.setWordWrap(True)
        root.addWidget(hint)

        top_cards = QHBoxLayout()
        top_cards.setContentsMargins(0, 0, 0, 0)
        top_cards.setSpacing(10)
        top_cards.addWidget(self._build_simple_card("SPL", self._current.spl, graph_key="spl"), 1)
        top_cards.addWidget(self._build_simple_card("Impedance", self._current.impedance, graph_key="impedance"), 1)
        root.addLayout(top_cards)

        polar_title = QLabel("Polar (up to 3)")
        polar_title.setObjectName("SummaryTitle")
        root.addWidget(polar_title)

        for index in range(3):
            root.addWidget(self._build_polar_card(index=index, state=self._current.polars[index]))

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
        active.setChecked(bool(state.enabled))
        top.addWidget(active)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        variant = QComboBox()
        variant.addItems(["main", "default"])
        variant.setCurrentText(str(state.variant))
        fmt = QComboBox()
        fmt.addItems(["txt"])
        fmt.setCurrentText(str(state.fmt))
        controls: List[QWidget] = [variant, fmt]

        def _toggle(enabled: bool) -> None:
            for control in controls:
                control.setEnabled(bool(enabled))

        _toggle(bool(state.enabled))
        active.toggled.connect(_toggle)
        active.toggled.connect(lambda value, key=graph_key: self._set_simple(key, "enabled", bool(value)))
        variant.currentTextChanged.connect(lambda value, key=graph_key: self._set_simple(key, "variant", str(value)))
        fmt.currentTextChanged.connect(lambda value, key=graph_key: self._set_simple(key, "fmt", str(value).lower()))

        grid.addWidget(QLabel("Variant"), 0, 0)
        grid.addWidget(variant, 0, 1)
        grid.addWidget(QLabel("Format"), 1, 0)
        grid.addWidget(fmt, 1, 1)
        layout.addLayout(grid)
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
        active.setChecked(bool(state.enabled))
        top.addWidget(active)
        layout.addLayout(top)

        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)

        name_edit = QLineEdit(str(state.polar_name or ""))
        name_edit.setPlaceholderText("Polars Name")
        variant = QComboBox()
        variant.addItems(["main", "default"])
        variant.setCurrentText(str(state.variant))
        fmt = QComboBox()
        fmt.addItems(["txt"])
        fmt.setCurrentText(str(state.fmt))
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

        controls: List[QWidget] = [
            name_edit,
            variant,
            fmt,
            map_start,
            map_end,
            map_steps,
            distance,
            offset,
            inclination,
        ]

        def _toggle(enabled: bool) -> None:
            for control in controls:
                control.setEnabled(bool(enabled))

        _toggle(bool(state.enabled))
        active.toggled.connect(_toggle)
        active.toggled.connect(lambda value, idx=index: self._set_polar(idx, "enabled", bool(value)))
        name_edit.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "polar_name", str(value)))
        variant.currentTextChanged.connect(lambda value, idx=index: self._set_polar(idx, "variant", str(value)))
        fmt.currentTextChanged.connect(lambda value, idx=index: self._set_polar(idx, "fmt", str(value).lower()))
        map_start.textChanged.connect(
            lambda value, idx=index: self._set_polar(idx, "map_angle_start", _int_or_default(value, 0))
        )
        map_end.textChanged.connect(
            lambda value, idx=index: self._set_polar(idx, "map_angle_end", _int_or_default(value, 90))
        )
        map_steps.textChanged.connect(
            lambda value, idx=index: self._set_polar(idx, "map_angle_steps", max(1, _int_or_default(value, 19)))
        )
        distance.textChanged.connect(
            lambda value, idx=index: self._set_polar(idx, "distance_m", _float_or_default(value, 2.0))
        )
        offset.textChanged.connect(lambda value, idx=index: self._set_polar(idx, "offset", _int_or_default(value, 145)))
        inclination.textChanged.connect(
            lambda value, idx=index: self._set_polar(idx, "inclination", _int_or_default(value, 90))
        )

        row = 0
        grid.addWidget(QLabel("Polars Name"), row, 0)
        grid.addWidget(name_edit, row, 1)
        row += 1
        grid.addWidget(QLabel("Variant"), row, 0)
        grid.addWidget(variant, row, 1)
        row += 1
        grid.addWidget(QLabel("Format"), row, 0)
        grid.addWidget(fmt, row, 1)
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
        layout.addLayout(grid)
        return card

    def _set_simple(self, graph_key: str, key: str, value: Any) -> None:
        state = self._current.spl if graph_key == "spl" else self._current.impedance
        setattr(state, str(key), value)

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

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectSummaryPanel")
        self._advanced_state = _AdvancedState.defaults()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel("Exports")
        title.setObjectName("SummaryTitle")
        root.addWidget(title)

        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(8)
        self.simulation_mode = QComboBox()
        self.simulation_mode.addItem("Free Standing", "free_standing")
        self.simulation_mode.addItem("Infinite Baffle", "infinite_baffle")
        self.simulation_mode.setMinimumWidth(152)
        self.simulation_mode.setMaximumWidth(180)
        self.sweep_mode = QComboBox()
        self.sweep_mode.addItems(["single", "combined"])
        self.sweep_mode.setMinimumWidth(112)
        self.sweep_mode.setMaximumWidth(132)
        mode_row.addWidget(QLabel("Simulation Mode"))
        mode_row.addWidget(self.simulation_mode, 0, Qt.AlignLeft)
        mode_row.addSpacing(10)
        mode_row.addWidget(QLabel("Sweep Mode"))
        mode_row.addWidget(self.sweep_mode, 0, Qt.AlignLeft)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        freq_row = QHBoxLayout()
        freq_row.setContentsMargins(0, 0, 0, 0)
        freq_row.setSpacing(8)
        self.freq_start = QLineEdit("500")
        self.freq_start.setValidator(QIntValidator(1, 1_000_000, self.freq_start))
        self.freq_start.setFixedWidth(112)
        self.freq_start.setFixedHeight(28)
        self.freq_end = QLineEdit("15000")
        self.freq_end.setValidator(QIntValidator(1, 1_000_000, self.freq_end))
        self.freq_end.setFixedWidth(112)
        self.freq_end.setFixedHeight(28)
        self.num_points = QLineEdit("16")
        self.num_points.setValidator(QIntValidator(1, 1_000_000, self.num_points))
        self.num_points.setFixedWidth(112)
        self.num_points.setFixedHeight(28)
        freq_row.addWidget(QLabel("Freq Start [Hz]"))
        freq_row.addWidget(self.freq_start, 0, Qt.AlignLeft)
        freq_row.addWidget(QLabel("Freq End [Hz]"))
        freq_row.addWidget(self.freq_end, 0, Qt.AlignLeft)
        freq_row.addWidget(QLabel("Points"))
        freq_row.addWidget(self.num_points, 0, Qt.AlignLeft)
        freq_row.addStretch(1)
        root.addLayout(freq_row)

        mesh_row = QHBoxLayout()
        mesh_row.setContentsMargins(0, 0, 0, 0)
        mesh_row.setSpacing(8)
        self.mesh_frequency = QLineEdit("")
        self.mesh_frequency.setValidator(QIntValidator(1, 1_000_000, self.mesh_frequency))
        self.mesh_frequency.setPlaceholderText("optional")
        self.mesh_frequency.setFixedWidth(112)
        self.mesh_frequency.setFixedHeight(28)
        mesh_row.addWidget(QLabel("Mesh Freq [Hz]"))
        mesh_row.addWidget(self.mesh_frequency, 0, Qt.AlignLeft)
        mesh_row.addStretch(1)
        root.addLayout(mesh_row)

        presets_row = QHBoxLayout()
        presets_row.setContentsMargins(0, 0, 0, 0)
        presets_row.setSpacing(8)
        self.preset_spl = self._make_preset_button("SPL")
        self.preset_impedance = self._make_preset_button("Impedance")
        self.preset_polar = self._make_preset_button("Polar")
        presets_row.addWidget(self.preset_spl)
        presets_row.addWidget(self.preset_impedance)
        presets_row.addWidget(self.preset_polar)
        presets_row.addStretch(1)
        self.advanced_btn = QPushButton("Advanced")
        self.advanced_btn.setProperty("segment", "true")
        self.advanced_btn.setFixedHeight(24)
        self.advanced_btn.setMinimumWidth(84)
        self.advanced_btn.setMaximumWidth(96)
        presets_row.addWidget(self.advanced_btn, 0, Qt.AlignRight)
        root.addLayout(presets_row)
        root.addStretch(1)

        self.sweep_mode.currentTextChanged.connect(lambda _value: self.changed.emit())
        self.simulation_mode.currentIndexChanged.connect(lambda _value: self.changed.emit())
        self.freq_start.textChanged.connect(lambda _value: self.changed.emit())
        self.freq_end.textChanged.connect(lambda _value: self.changed.emit())
        self.num_points.textChanged.connect(lambda _value: self.changed.emit())
        self.mesh_frequency.textChanged.connect(lambda _value: self.changed.emit())
        self.preset_spl.toggled.connect(lambda _checked: self.changed.emit())
        self.preset_impedance.toggled.connect(lambda _checked: self.changed.emit())
        self.preset_polar.toggled.connect(lambda _checked: self.changed.emit())
        self.advanced_btn.clicked.connect(self._open_advanced)

    @staticmethod
    def _make_preset_button(label: str) -> QPushButton:
        button = QPushButton(str(label))
        button.setCheckable(True)
        button.setProperty("segment", "true")
        button.setFixedHeight(28)
        return button

    def _open_advanced(self) -> None:
        dialog = _AdvancedDialog(self._advanced_state, parent=self.window())
        if dialog.exec() != QDialog.Accepted:
            return
        touched = dialog.touched_graphs()
        self._advanced_state = dialog.state()
        if "spl" in touched:
            self.preset_spl.setChecked(False)
        if "impedance" in touched:
            self.preset_impedance.setChecked(False)
        if "polar" in touched:
            self.preset_polar.setChecked(False)
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

    def _preset_specs(self) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        if self.preset_spl.isChecked():
            specs.append(
                {
                    "id": "preset_spl",
                    "tool": "vacs",
                    "graph_kind": "spl",
                    "variant": "main",
                    "format": "txt",
                    "options": {},
                    "output_name_template": "{version_id}_{graph_kind}.{format}",
                }
            )
        if self.preset_impedance.isChecked():
            specs.append(
                {
                    "id": "preset_impedance",
                    "tool": "vacs",
                    "graph_kind": "impedance",
                    "variant": "main",
                    "format": "txt",
                    "options": {},
                    "output_name_template": "{version_id}_{graph_kind}.{format}",
                }
            )
        if self.preset_polar.isChecked():
            specs.append(
                {
                    "id": "preset_polar",
                    "tool": "vacs",
                    "graph_kind": "polar",
                    "variant": "main",
                    "format": "txt",
                    "options": {
                        "polar_name": "SPL_V",
                        "map_angle_range": [0, 90, 19],
                        "distance_m": 2.0,
                        "offset": 145,
                        "inclination": 90,
                    },
                    "output_name_template": "{version_id}_{graph_kind}.{format}",
                }
            )
        return specs

    def _advanced_specs(self) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        if self._advanced_state.spl.enabled:
            specs.append(
                {
                    "id": "adv_spl",
                    "tool": "vacs",
                    "graph_kind": "spl",
                    "variant": self._advanced_state.spl.variant,
                    "format": self._advanced_state.spl.fmt,
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
                    "variant": self._advanced_state.impedance.variant,
                    "format": self._advanced_state.impedance.fmt,
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
                    "variant": polar.variant,
                    "format": polar.fmt,
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
        specs = self._dedupe_specs_by_graph([*self._preset_specs(), *self._advanced_specs()])
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
            "exports": exports,
            "export_specs": specs,
        }

    def _reset_advanced(self) -> None:
        self._advanced_state = _AdvancedState.defaults()

    def _set_from_specs(self, specs: Sequence[Dict[str, Any]]) -> None:
        self.preset_spl.blockSignals(True)
        self.preset_impedance.blockSignals(True)
        self.preset_polar.blockSignals(True)
        self.preset_spl.setChecked(False)
        self.preset_impedance.setChecked(False)
        self.preset_polar.setChecked(False)
        self.preset_spl.blockSignals(False)
        self.preset_impedance.blockSignals(False)
        self.preset_polar.blockSignals(False)
        self._reset_advanced()

        polar_slot = 0
        for spec in list(specs):
            if not isinstance(spec, dict):
                continue
            graph_kind = str(spec.get("graph_kind", "")).strip().lower()
            spec_id = str(spec.get("id", "")).strip().lower()
            variant = str(spec.get("variant", "main") or "main")
            fmt = str(spec.get("format", "txt") or "txt").lower()
            options = dict(spec.get("options", {}) or {})

            if spec_id == "preset_spl":
                self.preset_spl.setChecked(True)
                continue
            if spec_id == "preset_impedance":
                self.preset_impedance.setChecked(True)
                continue
            if spec_id == "preset_polar":
                self.preset_polar.setChecked(True)
                continue

            if graph_kind == "spl":
                self._advanced_state.spl = _SimpleGraphState(enabled=True, variant=variant, fmt=fmt)
                continue
            if graph_kind == "impedance":
                self._advanced_state.impedance = _SimpleGraphState(enabled=True, variant=variant, fmt=fmt)
                continue
            if graph_kind == "polar" and polar_slot < len(self._advanced_state.polars):
                map_range = list(options.get("map_angle_range", [0, 90, 19]) or [0, 90, 19])
                while len(map_range) < 3:
                    map_range.append([0, 90, 19][len(map_range)])
                self._advanced_state.polars[polar_slot] = _PolarCardState(
                    enabled=True,
                    polar_name=str(options.get("polar_name", "") or "").strip(),
                    variant=variant,
                    fmt=fmt,
                    map_angle_start=int(map_range[0] or 0),
                    map_angle_end=int(map_range[1] or 90),
                    map_angle_steps=max(1, int(map_range[2] or 19)),
                    distance_m=float(options.get("distance_m", 2.0) or 2.0),
                    offset=int(options.get("offset", 145) or 145),
                    inclination=int(options.get("inclination", 90) or 90),
                )
                polar_slot += 1

    def set_from_payload(self, payload: Dict[str, Any]) -> None:
        raw = dict(payload or {})
        self.freq_start.setText(str(int(float(raw.get("freq_start_hz", 500) or 500))))
        self.freq_end.setText(str(int(float(raw.get("freq_end_hz", 15000) or 15000))))
        self.num_points.setText(str(int(raw.get("num_points", 16) or 16)))
        mesh_frequency = raw.get("mesh_frequency")
        if mesh_frequency is None:
            self.mesh_frequency.setText("")
        else:
            self.mesh_frequency.setText(str(int(float(mesh_frequency))))
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
        return len(list(self.sim_export_params_payload().get("export_specs", []) or []))
