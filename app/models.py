"""Core data models used by CLI/GUI/planner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.constants import DEFAULT_RUNNER_MODE
from app.export_specs import dump_export_specs, parse_export_specs


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_path(value: str | Path) -> Path:
    return value if isinstance(value, Path) else Path(value)


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in: {path}")
    return payload


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


@dataclass
class AppConfig:
    app_name: str = "Batch-Software"
    projects_root: str = str(Path("~/Documents/WUT-Batches/Projects"))
    templates_dir: Optional[str] = None
    template_cfg: Optional[str] = None
    ath_exe: Optional[str] = None
    ath_export_root: Optional[str] = None
    batch_results_root: Optional[str] = None
    akabak_dir: Optional[str] = None
    vacs_dir: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def projects_root_path(self) -> Path:
        root = Path(self.projects_root).expanduser()
        if not root.is_absolute():
            root = Path.home() / root
        return root

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        known = {
            "app_name",
            "projects_root",
            "templates_dir",
            "template_cfg",
            "ath_exe",
            "ath_export_root",
            "batch_results_root",
            "akabak_dir",
            "vacs_dir",
        }
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(
            app_name=str(data.get("app_name", "Batch-Software")),
            projects_root=str(data.get("projects_root", cls.projects_root)),
            templates_dir=data.get("templates_dir"),
            template_cfg=data.get("template_cfg"),
            ath_exe=data.get("ath_exe"),
            ath_export_root=data.get("ath_export_root"),
            batch_results_root=data.get("batch_results_root"),
            akabak_dir=data.get("akabak_dir"),
            vacs_dir=data.get("vacs_dir"),
            extra=extra,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "app_name": self.app_name,
            "projects_root": self.projects_root,
        }
        optional = (
            "templates_dir",
            "template_cfg",
            "ath_exe",
            "ath_export_root",
            "batch_results_root",
            "akabak_dir",
            "vacs_dir",
        )
        for key in optional:
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        payload.update(self.extra)
        return payload

    @classmethod
    def load(cls, path: str | Path = "app_config.json") -> "AppConfig":
        json_path = _as_path(path)
        if not json_path.exists():
            return cls()
        return cls.from_dict(_read_json(json_path))

    def dump(self, path: str | Path = "app_config.json") -> None:
        _write_json(_as_path(path), self.to_dict())


@dataclass
class ProjectConstraints:
    schema_version: str = "1.1"
    project_id: str = ""
    template_family: str = "ath_geometry_v1"
    runner_mode: str = DEFAULT_RUNNER_MODE
    notes: Optional[str] = None
    fixed_params: Dict[str, Any] = field(default_factory=dict)
    limits: Dict[str, Any] = field(default_factory=dict)
    param_states: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectConstraints":
        return cls(
            schema_version=str(data.get("schema_version", "1.1")),
            project_id=str(data.get("project_id", "")),
            template_family=str(data.get("template_family", "ath_geometry_v1")),
            runner_mode=str(data.get("runner_mode", DEFAULT_RUNNER_MODE)),
            notes=data.get("notes"),
            fixed_params=dict(data.get("fixed_params", {}) or {}),
            limits=dict(data.get("limits", {}) or {}),
            param_states=[
                item for item in list(data.get("param_states", []) or []) if isinstance(item, dict)
            ],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "template_family": self.template_family,
            "runner_mode": self.runner_mode,
            "notes": self.notes,
            "fixed_params": dict(self.fixed_params),
            "limits": dict(self.limits),
            "param_states": [dict(item) for item in self.param_states if isinstance(item, dict)],
        }


@dataclass
class Project:
    project_id: str
    name: str
    root_path: str
    schema_version: str = "1.1"
    constraints: ProjectConstraints = field(default_factory=ProjectConstraints)
    created_at: str = field(default_factory=_now_iso)
    created_by: str = ""
    display_number: str = ""
    project_uid: str = ""
    library_uid: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Project":
        constraints_raw = data.get("constraints", {}) or {}
        project_id = str(data.get("project_id", ""))
        project_uid = str(data.get("project_uid", data.get("uid", "")) or "").strip()
        display_number = str(data.get("display_number", data.get("display_id", "")) or "").strip()
        if not project_uid and "__" in project_id:
            parts = project_id.split("__", 1)
            if len(parts) == 2:
                display_number = display_number or str(parts[0]).strip()
                project_uid = str(parts[1]).strip()
        return cls(
            schema_version=str(data.get("schema_version", "1.1")),
            project_id=project_id,
            name=str(data.get("name", "")),
            root_path=str(data.get("root_path", "")),
            constraints=ProjectConstraints.from_dict(dict(constraints_raw)),
            created_at=str(data.get("created_at", _now_iso())),
            created_by=str(data.get("created_by", "")),
            display_number=display_number,
            project_uid=project_uid,
            library_uid=str(data.get("library_uid", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "name": self.name,
            "root_path": self.root_path,
            "constraints": self.constraints.to_dict(),
            "created_at": self.created_at,
            "created_by": self.created_by,
            "display_number": self.display_number,
            "project_uid": self.project_uid,
            "library_uid": self.library_uid,
        }


@dataclass
class SweepSpec:
    start: float
    end: float
    steps: int
    spacing: str = "linear"
    key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], key: Optional[str] = None) -> "SweepSpec":
        return cls(
            key=str(data.get("key", key)) if (data.get("key") is not None or key is not None) else None,
            start=float(data.get("start", 0.0)),
            end=float(data.get("end", 0.0)),
            steps=int(data.get("steps", 1)),
            spacing=str(data.get("spacing", "linear")),
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "start": self.start,
            "end": self.end,
            "steps": self.steps,
            "spacing": self.spacing,
        }
        if self.key:
            payload["key"] = self.key
        return payload


@dataclass
class ParamSelection:
    value: Any = None
    sweep: Optional[SweepSpec] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any], key: Optional[str] = None) -> "ParamSelection":
        if "sweep" in data and isinstance(data["sweep"], dict):
            return cls(value=None, sweep=SweepSpec.from_dict(data["sweep"], key=key))
        value = data.get("value")
        if value is None:
            return cls(value=None, sweep=None)
        if isinstance(value, (dict, list, bool, int, float)):
            return cls(value=value, sweep=None)
        try:
            return cls(value=float(value), sweep=None)
        except Exception:
            return cls(value=value, sweep=None)

    def to_dict(self) -> Dict[str, Any]:
        if self.sweep is not None:
            return {"sweep": self.sweep.to_dict()}
        return {"value": self.value}


@dataclass
class ExportOption:
    enabled: bool = False
    params: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExportOption":
        return cls(enabled=bool(data.get("enabled", False)), params=dict(data.get("params", {}) or {}))

    def to_dict(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "params": dict(self.params)}


@dataclass
class SimExportSettings:
    freq_start_hz: float = 500.0
    freq_end_hz: float = 15000.0
    num_points: int = 16
    mesh_frequency: Optional[float] = None
    simulation_mode: str = "free_standing"
    auto_default_polar_exports: bool = False
    exports: Dict[str, ExportOption] = field(default_factory=dict)
    export_specs: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimExportSettings":
        exports: Dict[str, ExportOption] = {}
        for key, value in dict(data.get("exports", {}) or {}).items():
            if isinstance(value, dict):
                exports[str(key)] = ExportOption.from_dict(value)
        specs = dump_export_specs(parse_export_specs(data))
        return cls(
            freq_start_hz=float(data.get("freq_start_hz", 500.0)),
            freq_end_hz=float(data.get("freq_end_hz", 15000.0)),
            num_points=int(data.get("num_points", 16)),
            mesh_frequency=(
                None if data.get("mesh_frequency") is None else float(data.get("mesh_frequency"))
            ),
            simulation_mode=(
                str(data.get("simulation_mode", "free_standing")).strip().lower()
                if str(data.get("simulation_mode", "free_standing")).strip().lower() in {"free_standing", "infinite_baffle"}
                else "free_standing"
            ),
            auto_default_polar_exports=bool(data.get("auto_default_polar_exports", False)),
            exports=exports,
            export_specs=specs,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "freq_start_hz": self.freq_start_hz,
            "freq_end_hz": self.freq_end_hz,
            "num_points": self.num_points,
            "mesh_frequency": self.mesh_frequency,
            "simulation_mode": self.simulation_mode,
            "auto_default_polar_exports": bool(self.auto_default_polar_exports),
            "exports": {k: v.to_dict() for k, v in self.exports.items()},
            "export_specs": list(self.export_specs),
        }


@dataclass
class Batch:
    batch_id: str
    project_id: str = ""
    schema_version: str = "1.1"
    selected_params: Dict[str, ParamSelection] = field(default_factory=dict)
    sweeps: Dict[str, SweepSpec] = field(default_factory=dict)
    sweep_mode: str = "single"
    sim_export_settings: SimExportSettings = field(default_factory=SimExportSettings)
    runner_mode: str = DEFAULT_RUNNER_MODE
    geometry_id: str = ""
    driver_selection_mode: str = "geometry_default"
    driver_override_revision_id: str = ""
    # Legacy compatibility fields. New batches keep selection references above;
    # immutable snapshots are resolved and persisted per run.
    driver_revision_id: str = ""
    driver_snapshot: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def mode(self) -> str:
        return "factorial" if self.sweep_mode == "combined" else "oat"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Batch":
        selected_params: Dict[str, ParamSelection] = {}
        for key, value in dict(data.get("selected_params", {}) or {}).items():
            if isinstance(value, dict):
                selected_params[str(key)] = ParamSelection.from_dict(value, key=str(key))
            else:
                selected_params[str(key)] = ParamSelection(value=float(value))

        sweeps: Dict[str, SweepSpec] = {}
        raw_sweeps = data.get("sweeps", {}) or {}
        if isinstance(raw_sweeps, list):
            for item in raw_sweeps:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key", "")).strip()
                if not key:
                    continue
                sweeps[key] = SweepSpec.from_dict(item, key=key)
        elif isinstance(raw_sweeps, dict):
            for key, value in raw_sweeps.items():
                if isinstance(value, dict):
                    sweeps[str(key)] = SweepSpec.from_dict(value, key=str(key))

        sweep_mode = str(data.get("sweep_mode", "")).strip()
        if sweep_mode not in {"single", "combined"}:
            legacy_mode = str(data.get("mode", "oat")).lower()
            sweep_mode = "combined" if legacy_mode in {"factorial", "both"} else "single"

        sim_export_raw = data.get("sim_export_settings", {})
        if isinstance(sim_export_raw, dict):
            sim_export_settings = SimExportSettings.from_dict(sim_export_raw)
        else:
            sim_export_settings = SimExportSettings()

        known = {
            "batch_id",
            "project_id",
            "schema_version",
            "selected_params",
            "sweeps",
            "sweep_mode",
            "mode",
            "sim_export_settings",
            "runner_mode",
            "geometry_id",
            "driver_selection_mode",
            "driver_override_revision_id",
            "driver_revision_id",
            "driver_snapshot",
        }
        extra = {k: v for k, v in data.items() if k not in known}

        selection_mode = str(data.get("driver_selection_mode", "geometry_default") or "geometry_default")
        if selection_mode not in {"geometry_default", "explicit_override"}:
            selection_mode = "geometry_default"
        return cls(
            schema_version=str(data.get("schema_version", "1.1")),
            batch_id=str(data.get("batch_id", data.get("id", ""))),
            project_id=str(data.get("project_id", "")),
            selected_params=selected_params,
            sweeps=sweeps,
            sweep_mode=sweep_mode,
            sim_export_settings=sim_export_settings,
            runner_mode=str(data.get("runner_mode", DEFAULT_RUNNER_MODE)),
            geometry_id=str(data.get("geometry_id", "") or ""),
            driver_selection_mode=selection_mode,
            driver_override_revision_id=str(data.get("driver_override_revision_id", "") or ""),
            driver_revision_id=str(data.get("driver_revision_id", "") or ""),
            driver_snapshot=dict(data.get("driver_snapshot", {}) or {}),
            extra=extra,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "project_id": self.project_id,
            "selected_params": {k: v.to_dict() for k, v in self.selected_params.items()},
            "sweeps": {k: v.to_dict() for k, v in self.sweeps.items()},
            "sweep_mode": self.sweep_mode,
            "mode": self.mode,
            "sim_export_settings": self.sim_export_settings.to_dict(),
            "runner_mode": self.runner_mode,
            "geometry_id": self.geometry_id,
            "driver_selection_mode": self.driver_selection_mode,
            "driver_override_revision_id": self.driver_override_revision_id,
            "driver_revision_id": self.driver_revision_id,
            "driver_snapshot": dict(self.driver_snapshot),
        }
        payload.update(self.extra)
        return payload

    @classmethod
    def load(cls, path: str | Path) -> "Batch":
        return cls.from_dict(_read_json(_as_path(path)))

    def dump(self, path: str | Path) -> None:
        _write_json(_as_path(path), self.to_dict())


@dataclass
class DatasetManifest:
    schema_version: str = "1.0"
    project_id: str = ""
    created_at: str = field(default_factory=_now_iso)
    batch_ids: List[str] = field(default_factory=list)
    import_index: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatasetManifest":
        return cls(
            schema_version=str(data.get("schema_version", "1.0")),
            project_id=str(data.get("project_id", "")),
            created_at=str(data.get("created_at", _now_iso())),
            batch_ids=[str(v) for v in list(data.get("batch_ids", []) or [])],
            import_index=[entry for entry in list(data.get("import_index", []) or []) if isinstance(entry, dict)],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "created_at": self.created_at,
            "batch_ids": list(self.batch_ids),
            "import_index": list(self.import_index),
        }

    @classmethod
    def load(cls, path: str | Path) -> "DatasetManifest":
        json_path = _as_path(path)
        if not json_path.exists():
            return cls()
        return cls.from_dict(_read_json(json_path))

    def dump(self, path: str | Path) -> None:
        _write_json(_as_path(path), self.to_dict())


@dataclass
class ResolutionIssue:
    rule_id: str
    severity: str
    message: str
    scope: str = "version"
    source: str = "resolver"
    version_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "message": self.message,
            "scope": self.scope,
            "source": self.source,
        }
        if self.version_index is not None:
            payload["version_index"] = self.version_index
        return payload


@dataclass
class VersionSpec:
    project_id: str
    batch_id: str
    version_id: str
    sweep_mode: str
    sequence_index: int
    parameters: Dict[str, Any] = field(default_factory=dict)
    variable_parameters: Dict[str, Any] = field(default_factory=dict)
    unset_parameters: List[str] = field(default_factory=list)
    sweep_parameters: Dict[str, Any] = field(default_factory=dict)
    sim_export_settings: Dict[str, Any] = field(default_factory=dict)
    paths: Dict[str, str] = field(default_factory=dict)
    status: str = "planned"
    created_at: str = field(default_factory=_now_iso)
    geometry_id: str = ""
    driver_snapshot: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VersionSpec":
        return cls(
            project_id=str(data.get("project_id", "")),
            batch_id=str(data.get("batch_id", "")),
            version_id=str(data.get("version_id", "")),
            sweep_mode=str(data.get("sweep_mode", "single")),
            sequence_index=int(data.get("sequence_index", 0) or 0),
            parameters=dict(data.get("parameters", {}) or {}),
            variable_parameters=dict(data.get("variable_parameters", {}) or {}),
            unset_parameters=[str(item) for item in list(data.get("unset_parameters", []) or [])],
            sweep_parameters=dict(data.get("sweep_parameters", {}) or {}),
            sim_export_settings=dict(data.get("sim_export_settings", {}) or {}),
            paths={str(key): str(value) for key, value in dict(data.get("paths", {}) or {}).items()},
            status=str(data.get("status", "planned") or "planned"),
            created_at=str(data.get("created_at", "") or _now_iso()),
            geometry_id=str(data.get("geometry_id", "") or ""),
            driver_snapshot=dict(data.get("driver_snapshot", {}) or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "batch_id": self.batch_id,
            "version_id": self.version_id,
            "sweep_mode": self.sweep_mode,
            "sequence_index": self.sequence_index,
            "parameters": dict(self.parameters),
            "variable_parameters": dict(self.variable_parameters),
            "unset_parameters": list(self.unset_parameters),
            "sweep_parameters": dict(self.sweep_parameters),
            "sim_export_settings": dict(self.sim_export_settings),
            "paths": dict(self.paths),
            "status": self.status,
            "created_at": self.created_at,
            "geometry_id": self.geometry_id,
            "driver_snapshot": dict(self.driver_snapshot),
        }


@dataclass
class ResolveVersionsResult:
    versions: List[VersionSpec] = field(default_factory=list)
    issues: List[ResolutionIssue] = field(default_factory=list)

    @property
    def blocking_issues(self) -> List[ResolutionIssue]:
        return [issue for issue in self.issues if issue.severity == "fatal"]
