"""Large-scale PROJECT-page ATH experiment harness (UI-path only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import sqlite3
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import uuid

from app.cfg_renderer import render_cfg_text
from app.constants import DEFAULT_RUNNER_MODE, MANDATORY_SOURCE_BLOCK
from app.projectpage_ath_test import (
    _best_mesh_cmd,
    _detect_export_dir,
    _find_config_file,
    _load_template_text,
    _materialize_case_payload,
    _next_cfg_index,
    _path_dirs_snapshot,
    _resolve_render_inputs,
    _write_runtime_ath_cfg,
    compare_expected,
    parse_key_value_text,
    ProjectPageAthCase,
)
from app.runners import AthRunner, RunnerResult
from app.safe_cleanup import guarded_delete_tree
from app.settings_store import UserSettings


_CFG_BASENAME_RE = re.compile(r"^ProjectPageATHTest(\d+)\.cfg$", re.IGNORECASE)
_ATH_CONFIG_OPTIONAL_MISSING_PREFIXES = ("Mesh.",)


@dataclass(frozen=True)
class ExperimentCase:
    case_index: int
    exploratory: bool
    case: ProjectPageAthCase


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sample_float(rng: random.Random, low: float, high: float, *, exploratory: bool) -> float:
    if exploratory:
        # Bias to boundaries for exploratory runs.
        boundary_pick = rng.choice([0.0, 0.1, 0.9, 1.0, rng.random()])
        return low + (high - low) * float(boundary_pick)
    return low + (high - low) * rng.random()


def _sample_int(rng: random.Random, low: int, high: int, *, exploratory: bool) -> int:
    if exploratory and rng.random() < 0.25:
        return int(rng.choice([low, high]))
    return int(rng.randint(low, high))


def _case_fields(
    rng: random.Random,
    *,
    exploratory: bool,
    max_dim_mm: float,
    hard_cap_mm: float,
) -> List[Tuple[str, Any]]:
    fields: List[Tuple[str, Any]] = []

    throat_profile = int(rng.choice([1, 2, 3]))
    gcurve_type = rng.choices([None, 1, 2], weights=[0.35, 0.35, 0.30], k=1)[0]
    morph_target_shape = int(rng.choices([0, 1, 2], weights=[0.45, 0.35, 0.20], k=1)[0])

    length_high = min(max_dim_mm * 0.9, max(200.0, hard_cap_mm * 0.75))
    if exploratory:
        length_low = 15.0
        length_high = min(hard_cap_mm * 1.05, hard_cap_mm + 250.0)
    else:
        length_low = 90.0
    length = round(_sample_float(rng, length_low, max(length_low + 1.0, length_high), exploratory=exploratory), 3)

    throat_diameter = round(_sample_float(rng, 10.0 if exploratory else 20.0, 140.0 if exploratory else 65.0, exploratory=exploratory), 3)
    throat_angle = round(_sample_float(rng, 0.0 if exploratory else 2.0, 28.0 if exploratory else 9.5, exploratory=exploratory), 3)

    fields.extend(
        [
            ("Throat.Profile", throat_profile),
            ("Throat.Diameter", throat_diameter),
            ("Throat.Angle", throat_angle),
            ("Morph.TargetShape", morph_target_shape),
        ]
    )

    # Length is intentionally omitted for R-OSSE-only branches in a subset of cases.
    if throat_profile != 2 or rng.random() < 0.35:
        fields.append(("Length", length))

    if throat_profile == 1:
        fields.extend(
            [
                ("Term.s", round(_sample_float(rng, 0.50, 1.05 if exploratory else 0.86, exploratory=exploratory), 5)),
                ("Term.q", round(_sample_float(rng, 0.82, 1.0, exploratory=exploratory), 5)),
                ("Term.n", round(_sample_float(rng, 2.0, 8.0 if exploratory else 4.6, exploratory=exploratory), 5)),
                ("OS.k", round(_sample_float(rng, 0.2 if exploratory else 0.75, 1.6 if exploratory else 1.20, exploratory=exploratory), 5)),
            ]
        )
    elif throat_profile == 2:
        fields.extend(
            [
                ("R-OSSE.R", round(_sample_float(rng, 35.0, hard_cap_mm * (0.25 if exploratory else 0.12), exploratory=exploratory), 4)),
                ("R-OSSE.r0", round(_sample_float(rng, 3.0, 48.0 if exploratory else 28.0, exploratory=exploratory), 4)),
                ("R-OSSE.a0", round(_sample_float(rng, 0.0, 18.0 if exploratory else 10.0, exploratory=exploratory), 4)),
                ("R-OSSE.a", round(_sample_float(rng, 8.0, 85.0 if exploratory else 60.0, exploratory=exploratory), 4)),
                ("R-OSSE.k", round(_sample_float(rng, 0.15, 1.9 if exploratory else 1.25, exploratory=exploratory), 5)),
                ("R-OSSE.r", round(_sample_float(rng, 0.15, 1.8 if exploratory else 1.15, exploratory=exploratory), 5)),
                ("R-OSSE.m", round(_sample_float(rng, 1.2, 9.0 if exploratory else 5.5, exploratory=exploratory), 5)),
                ("R-OSSE.b", round(_sample_float(rng, 0.0, 1.2 if exploratory else 0.6, exploratory=exploratory), 5)),
                ("R-OSSE.q", round(_sample_float(rng, 0.75, 1.0, exploratory=exploratory), 5)),
            ]
        )
    elif throat_profile == 3:
        fields.extend(
            [
                ("CircArc.TermAngle", round(_sample_float(rng, 3.0, 72.0 if exploratory else 44.0, exploratory=exploratory), 4)),
                ("CircArc.Radius", round(_sample_float(rng, 35.0, hard_cap_mm * (0.3 if exploratory else 0.18), exploratory=exploratory), 4)),
            ]
        )

    if gcurve_type is None:
        fields.append(("Coverage.Angle", round(_sample_float(rng, 12.0, 130.0 if exploratory else 95.0, exploratory=exploratory), 4)))
    else:
        fields.extend(
            [
                ("GCurve.Type", int(gcurve_type)),
                ("GCurve.Dist", round(_sample_float(rng, 8.0, max_dim_mm * (0.9 if exploratory else 0.35), exploratory=exploratory), 4)),
                ("GCurve.Width", round(_sample_float(rng, 18.0, max_dim_mm * (0.85 if exploratory else 0.32), exploratory=exploratory), 4)),
                ("GCurve.Rot", round(_sample_float(rng, -20.0 if exploratory else -8.0, 20.0 if exploratory else 8.0, exploratory=exploratory), 4)),
                ("GCurve.AspectRatio", round(_sample_float(rng, 0.3 if exploratory else 0.7, 2.6 if exploratory else 1.6, exploratory=exploratory), 4)),
            ]
        )
        if int(gcurve_type) == 1:
            fields.append(("GCurve.SE.n", round(_sample_float(rng, 2.0, 7.0 if exploratory else 4.2, exploratory=exploratory), 4)))
        elif int(gcurve_type) == 2:
            fields.extend(
                [
                    ("GCurve.SF.a", round(_sample_float(rng, 0.3 if exploratory else 0.8, 1.8 if exploratory else 1.25, exploratory=exploratory), 4)),
                    ("GCurve.SF.b", round(_sample_float(rng, 0.3 if exploratory else 0.8, 1.8 if exploratory else 1.25, exploratory=exploratory), 4)),
                    ("GCurve.SF.m1", round(_sample_float(rng, 1.0, 14.0 if exploratory else 8.0, exploratory=exploratory), 4)),
                    ("GCurve.SF.m2", round(_sample_float(rng, 1.0, 14.0 if exploratory else 8.0, exploratory=exploratory), 4)),
                    ("GCurve.SF.n1", round(_sample_float(rng, 0.08, 2.0 if exploratory else 0.75, exploratory=exploratory), 4)),
                    ("GCurve.SF.n2", round(_sample_float(rng, 0.3, 3.0 if exploratory else 1.9, exploratory=exploratory), 4)),
                    ("GCurve.SF.n3", round(_sample_float(rng, 0.3, 3.0 if exploratory else 1.9, exploratory=exploratory), 4)),
                ]
            )

    if morph_target_shape != 0:
        tgt_max = max_dim_mm * (0.95 if exploratory else 0.45)
        fields.extend(
            [
                ("Morph.TargetWidth", round(_sample_float(rng, 45.0, max(60.0, tgt_max), exploratory=exploratory), 4)),
                ("Morph.TargetHeight", round(_sample_float(rng, 45.0, max(60.0, tgt_max), exploratory=exploratory), 4)),
            ]
        )
        if morph_target_shape == 1:
            fields.append(("Morph.CornerRadius", round(_sample_float(rng, 0.0, 60.0 if exploratory else 28.0, exploratory=exploratory), 4)))

    fields.extend(
        [
            ("Mesh.Quadrants", int(rng.choice([1, 12, 14] if exploratory else [1, 12]))),
            ("Mesh.AngularSegments", _sample_int(rng, 24 if exploratory else 44, 160 if exploratory else 96, exploratory=exploratory)),
            ("Mesh.LengthSegments", _sample_int(rng, 8 if exploratory else 12, 58 if exploratory else 30, exploratory=exploratory)),
        ]
    )
    if rng.random() < (0.45 if exploratory else 0.28):
        fields.append(("Mesh.ThroatSegments", _sample_int(rng, 1, 24 if exploratory else 12, exploratory=exploratory)))
    if rng.random() < (0.45 if exploratory else 0.28):
        fields.append(("Mesh.CornerSegments", _sample_int(rng, 1, 14 if exploratory else 8, exploratory=exploratory)))

    return fields


def generate_experiment_cases(
    *,
    cases: int,
    seed: int,
    max_dim_mm: float,
    hard_cap_mm: float,
) -> List[ExperimentCase]:
    rng = random.Random(int(seed))
    generated: List[ExperimentCase] = []
    for case_index in range(1, int(cases) + 1):
        exploratory = rng.random() < 0.30
        case = ProjectPageAthCase(
            test_id=f"PP_ATH_EXP_{case_index:04d}",
            project_name=f"PP_ATH_EXP_{case_index:04d}",
            field_values=_case_fields(rng, exploratory=exploratory, max_dim_mm=max_dim_mm, hard_cap_mm=hard_cap_mm),
        )
        generated.append(
            ExperimentCase(
                case_index=case_index,
                exploratory=exploratory,
                case=case,
            )
        )
    return generated


def _copy_log_text(path: Optional[str], target: Path) -> Optional[str]:
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    text = source.read_text(encoding="utf-8", errors="replace")
    target.write_text(text, encoding="utf-8")
    return str(target)


def _safe_delete_cfg_file(cfg_path: Path, *, cfg_root: Path) -> Dict[str, Any]:
    result = {
        "target": str(cfg_path),
        "deleted": False,
        "reason": "unknown",
    }
    resolved_root = cfg_root.expanduser().resolve()
    resolved_cfg = cfg_path.expanduser().resolve()
    if not resolved_cfg.exists():
        result["reason"] = "target_missing"
        return result
    if not resolved_cfg.is_file():
        result["reason"] = "target_not_file"
        return result
    if not resolved_cfg.is_relative_to(resolved_root):
        result["reason"] = "outside_allowed_root"
        return result
    if _CFG_BASENAME_RE.match(resolved_cfg.name) is None:
        result["reason"] = "unexpected_file_name"
        return result
    resolved_cfg.unlink()
    result["deleted"] = True
    result["reason"] = "deleted"
    return result


def _parse_value_num(value: Any) -> Optional[float]:
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _ensure_db_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_runs(
            run_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            seed INTEGER NOT NULL,
            case_index INTEGER NOT NULL,
            status TEXT NOT NULL,
            ath_exit_code INTEGER,
            ath_error_kind TEXT,
            ath_error_message TEXT,
            ath_warning_count INTEGER NOT NULL DEFAULT 0,
            cfg_path TEXT,
            horns_export_dir TEXT,
            stdout_path TEXT,
            stderr_path TEXT,
            notes TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_params(
            run_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value_text TEXT,
            value_num REAL,
            is_set INTEGER NOT NULL,
            PRIMARY KEY(run_id, key)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_metrics(
            run_id TEXT PRIMARY KEY,
            final_width_mm REAL,
            final_height_mm REAL,
            final_length_mm REAL,
            avg_throat_angle_deg REAL,
            derived_volume_m3 REAL,
            flags_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_compare(
            run_id TEXT PRIMARY KEY,
            config_ok INTEGER NOT NULL DEFAULT 0,
            no_ghosts INTEGER NOT NULL DEFAULT 0,
            missing_keys_required_json TEXT,
            missing_keys_optional_json TEXT,
            extra_keys_defaulted_json TEXT,
            extra_keys_ghost_json TEXT,
            mismatch_json TEXT
        )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_runs_status ON experiment_runs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_runs_case_index ON experiment_runs(case_index)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_runs_error_kind ON experiment_runs(ath_error_kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_params_key ON experiment_params(key)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_params_value_num ON experiment_params(value_num)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_metrics_length_mm ON experiment_metrics(final_length_mm)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_metrics_width_mm ON experiment_metrics(final_width_mm)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_metrics_height_mm ON experiment_metrics(final_height_mm)")


def _persist_experiment_row(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    created_at: str,
    seed: int,
    case_index: int,
    status: str,
    ath_exit_code: Optional[int],
    ath_error_kind: Optional[str],
    ath_error_message: Optional[str],
    ath_warning_count: int,
    cfg_path: Optional[str],
    horns_export_dir: Optional[str],
    stdout_path: Optional[str],
    stderr_path: Optional[str],
    notes: str,
    params_rows: Sequence[Tuple[str, Optional[str], Optional[float], int]],
    config_ok: bool,
    no_ghosts: bool,
    missing_keys_required: Sequence[str],
    missing_keys_optional: Sequence[str],
    extra_keys_defaulted: Sequence[str],
    extra_keys_ghost: Sequence[str],
    mismatches: Sequence[Mapping[str, Any]],
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO experiment_runs(
            run_id, created_at, seed, case_index, status, ath_exit_code, ath_error_kind,
            ath_error_message, ath_warning_count, cfg_path, horns_export_dir, stdout_path, stderr_path, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            created_at,
            int(seed),
            int(case_index),
            status,
            ath_exit_code,
            ath_error_kind,
            ath_error_message,
            int(ath_warning_count),
            cfg_path,
            horns_export_dir,
            stdout_path,
            stderr_path,
            notes,
        ),
    )
    conn.execute("DELETE FROM experiment_params WHERE run_id = ?", (run_id,))
    if params_rows:
        conn.executemany(
            """
            INSERT INTO experiment_params(run_id, key, value_text, value_num, is_set)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(run_id, key, value_text, value_num, int(is_set)) for key, value_text, value_num, is_set in params_rows],
        )

    conn.execute(
        """
        INSERT OR REPLACE INTO experiment_compare(
            run_id, config_ok, no_ghosts, missing_keys_required_json, missing_keys_optional_json,
            extra_keys_defaulted_json, extra_keys_ghost_json, mismatch_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            1 if config_ok else 0,
            1 if no_ghosts else 0,
            json.dumps(list(missing_keys_required), ensure_ascii=False),
            json.dumps(list(missing_keys_optional), ensure_ascii=False),
            json.dumps(list(extra_keys_defaulted), ensure_ascii=False),
            json.dumps(list(extra_keys_ghost), ensure_ascii=False),
            json.dumps(list(mismatches), ensure_ascii=False),
        ),
    )


def _param_rows_from_payload(
    *,
    payload: Mapping[str, Any],
    fallback_fields: Sequence[Tuple[str, Any]],
) -> List[Tuple[str, Optional[str], Optional[float], int]]:
    rows: List[Tuple[str, Optional[str], Optional[float], int]] = []
    seen: set[str] = set()
    for item in list(payload.get("param_states", []) or []):
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("param_name", "")).strip()
        if not key:
            continue
        is_set = 1 if int(item.get("is_set", 0)) == 1 else 0
        value = item.get("value") if is_set else None
        value_text = str(value) if value is not None else None
        rows.append((key, value_text, _parse_value_num(value), is_set))
        seen.add(key)

    if rows:
        return rows

    for key, value in fallback_fields:
        norm_key = str(key).strip()
        if not norm_key or norm_key in seen:
            continue
        rows.append((norm_key, str(value), _parse_value_num(value), 1))
    return rows


def _preflight_skip_reason(
    *,
    compat_state: Mapping[str, Any],
    expected_values: Mapping[str, Any],
    hard_cap_mm: float,
) -> Optional[str]:
    for issue in list(compat_state.get("issues", []) or []):
        if not isinstance(issue, Mapping):
            continue
        if str(issue.get("severity", "")).lower() == "fatal":
            return "compat_fatal"

    check_positive = (
        "Length",
        "Throat.Diameter",
        "GCurve.Dist",
        "GCurve.Width",
        "Morph.TargetWidth",
        "Morph.TargetHeight",
        "R-OSSE.R",
        "R-OSSE.r0",
    )
    for key in check_positive:
        if key not in expected_values:
            continue
        try:
            value = float(str(expected_values[key]).replace(",", "."))
        except Exception:
            continue
        if value <= 0.0:
            return f"non_positive_{key}"
        if value > float(hard_cap_mm):
            return f"input_hard_cap_exceeded_{key}"
    return None


def run_projectpage_ath_experiment(
    *,
    settings: UserSettings,
    cases: int = 500,
    seed: int = 1337,
    ath_exe: Optional[str] = None,
    template_cfg: Optional[str] = None,
    cfg_dir: str | Path = r"C:\Tools\ATH",
    export_root: str | Path = r"C:\Horns",
    reports_root: str | Path = "reports/ath_experiments",
    cleanup_files: bool = True,
    max_dim_mm: float = 2000.0,
    hard_cap_mm: float = 5000.0,
) -> Dict[str, Any]:
    resolved_ath_exe = ath_exe or settings.ath_exe
    if not resolved_ath_exe:
        raise ValueError("ATH executable is not configured. Pass --ath-exe or configure settings.")
    ath_executable = Path(resolved_ath_exe)
    if not ath_executable.exists():
        raise FileNotFoundError(f"ATH executable not found: {ath_executable}")

    cfg_root = Path(cfg_dir)
    export_root_path = Path(export_root)
    reports_root_path = Path(reports_root)
    logs_root = reports_root_path / "logs"
    cases_root = reports_root_path / "cases"
    db_path = reports_root_path / "ath_experiments.sqlite"
    cfg_root.mkdir(parents=True, exist_ok=True)
    export_root_path.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    cases_root.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    template_text = _load_template_text(template_cfg or settings.template_cfg)
    runner = AthRunner(str(ath_executable))
    allowed_global_keys = {str(key) for key, _ in MANDATORY_SOURCE_BLOCK}
    start_cfg_index = _next_cfg_index(cfg_root)

    all_cases = generate_experiment_cases(
        cases=cases,
        seed=seed,
        max_dim_mm=max_dim_mm,
        hard_cap_mm=hard_cap_mm,
    )

    reports: List[Dict[str, Any]] = []
    status_counts = {"ok": 0, "ath_error": 0, "pipeline_error": 0, "skipped": 0}
    with sqlite3.connect(str(db_path)) as conn:
        _ensure_db_schema(conn)
        for offset, experiment_case in enumerate(all_cases):
            cfg_index = start_cfg_index + offset
            cfg_path = cfg_root / f"ProjectPageATHTest{cfg_index}.cfg"
            run_name = f"run_{experiment_case.case_index:04d}"
            run_id = f"ath_exp_{seed}_{experiment_case.case_index:04d}_{uuid.uuid4().hex[:10]}"
            case_dir = cases_root / run_name
            runtime_dir = case_dir / "ath_runtime"
            version_logs_dir = case_dir / "runner_logs"
            case_report_path = case_dir / "report.json"
            case_dir.mkdir(parents=True, exist_ok=True)

            case = experiment_case.case
            started_at = _now_iso()
            payload: Dict[str, Any] = {}
            compat_state: Dict[str, Any] = {}
            missing_editors: List[str] = []
            cfg_written = False
            cfg_error: Optional[str] = None
            ath_result: Optional[RunnerResult] = None
            ath_error: Optional[str] = None
            export_dir: Optional[Path] = None
            config_file: Optional[Path] = None
            status = "pipeline_error"
            notes = ""
            cleanup_result: Dict[str, Any] = {}
            ath_error_kind: Optional[str] = None
            ath_error_message: Optional[str] = None
            ath_warning_count = 0

            try:
                payload, compat_state, missing_editors = _materialize_case_payload(case)
                runner_mode = str(payload.get("runner_mode") or DEFAULT_RUNNER_MODE)
                expected_values = {
                    **dict(payload.get("fixed_params", {}) or {}),
                    **dict(payload.get("limits", {}) or {}),
                }
                skip_reason = _preflight_skip_reason(
                    compat_state=compat_state,
                    expected_values=expected_values,
                    hard_cap_mm=hard_cap_mm,
                )
                if skip_reason:
                    status = "skipped"
                    notes = skip_reason
                else:
                    resolved_parameters, resolved_unset = _resolve_render_inputs(payload, runner_mode=runner_mode)
                    cfg_text = render_cfg_text(
                        template_text=template_text,
                        parameters=resolved_parameters,
                        version_id=case.test_id,
                        runner_mode=runner_mode,
                        omit_keys=resolved_unset,
                    )
                    cfg_path.write_text(cfg_text, encoding="utf-8")
                    cfg_written = True

                    before_dirs = _path_dirs_snapshot(export_root_path)
                    _write_runtime_ath_cfg(
                        runtime_dir,
                        export_root=export_root_path,
                        mesh_cmd=_best_mesh_cmd(ath_executable),
                    )
                    try:
                        ath_result = runner.run_cfg(
                            cfg_path,
                            version_logs_dir=version_logs_dir,
                            workdir=runtime_dir,
                        )
                    except Exception as exc:  # pragma: no cover - integration path
                        ath_error = str(exc)
                    export_dir = _detect_export_dir(export_root_path, before_dirs)
                    config_file = _find_config_file(export_dir) if export_dir else None

                    if ath_result and ath_result.ok:
                        status = "ok"
                    elif ath_result:
                        status = "ath_error"
                        ath_error_kind = "ath_nonzero_exit"
                        ath_error_message = f"ATH exited with code {ath_result.exit_code}"
                    else:
                        status = "pipeline_error"
            except Exception as exc:  # pragma: no cover - integration path
                cfg_error = str(exc)
                expected_values = {}
                runner_mode = DEFAULT_RUNNER_MODE
                status = "pipeline_error"

            cfg_parsed = parse_key_value_text(cfg_path.read_text(encoding="utf-8")) if cfg_written and cfg_path.exists() else {}
            config_parsed = parse_key_value_text(config_file.read_text(encoding="utf-8")) if config_file and config_file.exists() else {}
            cfg_compare = compare_expected(
                expected=expected_values,
                observed=cfg_parsed,
                allowed_global_keys=allowed_global_keys,
            )
            config_compare = compare_expected(
                expected=expected_values,
                observed=config_parsed,
                allowed_global_keys=allowed_global_keys,
                optional_missing_prefixes=_ATH_CONFIG_OPTIONAL_MISSING_PREFIXES,
            )
            cfg_ok = bool(cfg_written and cfg_compare["ok"])
            ath_ok = bool(ath_result and ath_result.ok)
            config_ok = bool(config_file is not None and config_compare["ok"])
            no_ghosts = bool((not cfg_compare["extra_keys_ghost"]) and (not config_compare["extra_keys_ghost"]))

            if status == "ok" and not (cfg_ok and ath_ok and config_ok and no_ghosts):
                status = "pipeline_error" if not ath_ok else "ath_error"
                notes = "compare_failed"

            run_stdout_path = _copy_log_text(
                ath_result.stdout_log if ath_result else None,
                logs_root / f"{run_name}_stdout.txt",
            )
            run_stderr_path = _copy_log_text(
                ath_result.stderr_log if ath_result else None,
                logs_root / f"{run_name}_stderr.txt",
            )

            if cleanup_files:
                cleanup_result["cfg"] = _safe_delete_cfg_file(cfg_path, cfg_root=cfg_root)
                if export_dir is not None:
                    cleanup = guarded_delete_tree(
                        export_dir,
                        allowed_root=export_root_path,
                        expected_dir_name=export_dir.name,
                        perform_delete=True,
                    )
                    cleanup_result["export_dir"] = {
                        "target": cleanup.target,
                        "deleted": cleanup.deleted,
                        "reason": cleanup.reason,
                    }

            report = {
                "run_id": run_id,
                "run_name": run_name,
                "case_index": experiment_case.case_index,
                "case_type": "exploratory" if experiment_case.exploratory else "safe",
                "test_id": case.test_id,
                "project_name": case.project_name,
                "started_at": started_at,
                "finished_at": _now_iso(),
                "status": status,
                "notes": notes,
                "cfg_path": str(cfg_path),
                "horns_export_dir": str(export_dir) if export_dir else None,
                "config_path": str(config_file) if config_file else None,
                "stdout_path": run_stdout_path,
                "stderr_path": run_stderr_path,
                "success_flags": {
                    "cfg_written": cfg_written,
                    "ath_ok": ath_ok,
                    "config_ok": config_ok,
                    "no_ghosts": no_ghosts,
                },
                "ath_result": (
                    {
                        "ok": ath_result.ok,
                        "exit_code": ath_result.exit_code,
                        "timed_out": ath_result.timed_out,
                        "stdout_log": ath_result.stdout_log,
                        "stderr_log": ath_result.stderr_log,
                        "summary_log": ath_result.summary_log,
                    }
                    if ath_result
                    else None
                ),
                "compare": {
                    "expected_values": expected_values,
                    "cfg": cfg_compare,
                    "config": config_compare,
                },
                "input_summary": {
                    "field_values": list(case.field_values),
                    "runner_mode": runner_mode,
                    "compat_issues": list(compat_state.get("issues", []) or []),
                    "missing_editors": missing_editors,
                    "payload_fixed_params": dict(payload.get("fixed_params", {}) or {}),
                    "payload_limits": dict(payload.get("limits", {}) or {}),
                },
                "errors": {
                    "cfg_error": cfg_error,
                    "ath_error": ath_error,
                    "ath_error_kind": ath_error_kind,
                    "ath_error_message": ath_error_message,
                    "ath_warning_count": ath_warning_count,
                },
                "cleanup": cleanup_result,
            }
            case_report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            params_rows = _param_rows_from_payload(payload=payload, fallback_fields=case.field_values)
            _persist_experiment_row(
                conn,
                run_id=run_id,
                created_at=report["started_at"],
                seed=int(seed),
                case_index=experiment_case.case_index,
                status=status,
                ath_exit_code=(ath_result.exit_code if ath_result else None),
                ath_error_kind=ath_error_kind,
                ath_error_message=ath_error_message or ath_error,
                ath_warning_count=ath_warning_count,
                cfg_path=str(cfg_path),
                horns_export_dir=str(export_dir) if export_dir else None,
                stdout_path=run_stdout_path,
                stderr_path=run_stderr_path,
                notes=notes,
                params_rows=params_rows,
                config_ok=config_ok,
                no_ghosts=no_ghosts,
                missing_keys_required=list(config_compare.get("missing_keys_required", []) or []),
                missing_keys_optional=list(config_compare.get("missing_keys_optional", []) or []),
                extra_keys_defaulted=list(config_compare.get("extra_keys_defaulted", []) or []),
                extra_keys_ghost=list(config_compare.get("extra_keys_ghost", []) or []),
                mismatches=list(config_compare.get("value_mismatches", []) or []),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO experiment_metrics(
                    run_id, final_width_mm, final_height_mm, final_length_mm, avg_throat_angle_deg, derived_volume_m3, flags_json
                ) VALUES (?, NULL, NULL, NULL, NULL, NULL, ?)
                """,
                (run_id, json.dumps({}, ensure_ascii=False)),
            )
            conn.commit()

            reports.append(report)
            status_counts[status] = int(status_counts.get(status, 0)) + 1

    summary = {
        "generated_at": _now_iso(),
        "ath_executable": str(ath_executable),
        "template_cfg": template_cfg or settings.template_cfg,
        "cfg_dir": str(cfg_root),
        "export_root": str(export_root_path),
        "reports_root": str(reports_root_path),
        "cases_requested": int(cases),
        "seed": int(seed),
        "cleanup_files": bool(cleanup_files),
        "max_dim_mm": float(max_dim_mm),
        "hard_cap_mm": float(hard_cap_mm),
        "database_path": str(db_path),
        "status_counts": status_counts,
        "reports": reports,
        "report_files": [str(cases_root / f"run_{item['case_index']:04d}" / "report.json") for item in reports],
    }
    summary_path = reports_root_path / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
