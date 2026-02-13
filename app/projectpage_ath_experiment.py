"""Large-scale PROJECT-page ATH experiment harness (UI-path only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
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
_WIDTH_HEIGHT_RE = re.compile(
    r"(?im)\b(?:device|final)\s+width\s*x\s*height\s*=\s*([-+]?\d+(?:[.,]\d+)?)\s*x\s*([-+]?\d+(?:[.,]\d+)?)\s*(mm|m)\b"
)
_LENGTH_RE = re.compile(
    r"(?im)\b(?:device|final)\s+length\s*=\s*([-+]?\d+(?:[.,]\d+)?)\s*(mm|m)\b"
)
_THROAT_ANGLE_RE = re.compile(
    r"(?im)\b(?:final\s+mesh\s+average\s+throat\s+angle|average\s+mesh\s+throat\s+angle)\s*[:=]\s*([-+]?\d+(?:[.,]\d+)?)\s*(deg|°)?"
)
_ATH_WARN_RE = re.compile(r"(?im)\bwarning\b")
_ATH_ERROR_PATTERNS: Tuple[Tuple[str, re.Pattern[str]], ...] = (
    ("rollback_not_supported", re.compile(r"(?i)rollback feature is no longer supported")),
    ("diameter_over_100m", re.compile(r"(?i)diameter[^\n]{0,160}larger than 100 m")),
    ("numeric_overflow", re.compile(r"(?i)(?:inf|nan|overflow)")),
    ("geometry_invalid", re.compile(r"(?i)(?:invalid geometry|math domain error|cannot generate geometry)")),
)


@dataclass(frozen=True)
class ExperimentCase:
    case_index: int
    exploratory: bool
    case: ProjectPageAthCase


PriorRanges = Dict[str, Tuple[float, float]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


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


def _load_prior_ranges(priors_path: Path) -> PriorRanges:
    if not priors_path.exists():
        return {}
    try:
        payload = json.loads(priors_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    raw_ranges = payload.get("range_suggestions")
    if not isinstance(raw_ranges, Mapping):
        return {}
    parsed: PriorRanges = {}
    for key, value in raw_ranges.items():
        if not isinstance(key, str) or not isinstance(value, Mapping):
            continue
        safe = value.get("suggested_safe_range")
        if not isinstance(safe, Mapping):
            continue
        try:
            low = float(safe.get("min"))
            high = float(safe.get("max"))
        except Exception:
            continue
        if not math.isfinite(low) or not math.isfinite(high):
            continue
        if low > high:
            low, high = high, low
        parsed[key] = (low, high)
    return parsed


def _sample_with_priors(
    rng: random.Random,
    *,
    key: str,
    low: float,
    high: float,
    exploratory: bool,
    prior_ranges: PriorRanges,
    use_safe_prob: float = 0.8,
) -> float:
    if low > high:
        low, high = high, low
    if low == high:
        return low

    prior = prior_ranges.get(str(key))
    if prior is None:
        return _sample_float(rng, low, high, exploratory=exploratory)

    safe_low = max(low, float(prior[0]))
    safe_high = min(high, float(prior[1]))
    safe_valid = safe_high > safe_low
    if safe_valid and rng.random() < float(use_safe_prob):
        return _sample_float(rng, safe_low, safe_high, exploratory=False)

    outside_ranges: List[Tuple[float, float]] = []
    if low < safe_low:
        outside_ranges.append((low, safe_low))
    if safe_high < high:
        outside_ranges.append((safe_high, high))
    if outside_ranges:
        seg_low, seg_high = rng.choice(outside_ranges)
        if seg_high > seg_low:
            return _sample_float(rng, seg_low, seg_high, exploratory=True)
    return _sample_float(rng, low, high, exploratory=exploratory)


def _apply_extreme_downweight(
    *,
    rng: random.Random,
    fields: List[Tuple[str, Any]],
    max_dim_mm: float,
) -> List[Tuple[str, Any]]:
    by_key: Dict[str, Any] = {str(key): value for key, value in fields}
    soft_cap = min(float(max_dim_mm), 1000.0)
    hard_targets = ("Length", "Morph.TargetWidth", "Morph.TargetHeight")
    for key in hard_targets:
        if key not in by_key:
            continue
        value = _parse_value_num(by_key[key])
        if value is None or value <= soft_cap:
            continue
        if rng.random() < 0.80:
            damped = soft_cap * (0.75 + 0.25 * rng.random())
            by_key[key] = round(float(damped), 4)
    gcurve_dist = _parse_value_num(by_key.get("GCurve.Dist"))
    if gcurve_dist is not None and gcurve_dist > soft_cap * 0.9 and rng.random() < 0.75:
        by_key["GCurve.Dist"] = round(soft_cap * (0.55 + 0.25 * rng.random()), 4)
    gcurve_width = _parse_value_num(by_key.get("GCurve.Width"))
    if gcurve_width is not None and gcurve_width > soft_cap * 0.9 and rng.random() < 0.75:
        by_key["GCurve.Width"] = round(soft_cap * (0.55 + 0.25 * rng.random()), 4)
    if "GCurve.Type" in by_key and int(by_key.get("GCurve.Type")) == 2:
        # Superformula branch is more sensitive to giant shapes; keep it tighter.
        sf_n2 = _parse_value_num(by_key.get("GCurve.SF.n2"))
        sf_n3 = _parse_value_num(by_key.get("GCurve.SF.n3"))
        if sf_n2 is not None and sf_n2 > 2.1:
            by_key["GCurve.SF.n2"] = round(2.1 - 0.2 * rng.random(), 4)
        if sf_n3 is not None and sf_n3 > 2.1:
            by_key["GCurve.SF.n3"] = round(2.1 - 0.2 * rng.random(), 4)

    normalized: List[Tuple[str, Any]] = []
    for key, _ in fields:
        norm_key = str(key)
        if norm_key in by_key:
            normalized.append((norm_key, by_key[norm_key]))
    return normalized


def _case_fields(
    rng: random.Random,
    *,
    exploratory: bool,
    max_dim_mm: float,
    hard_cap_mm: float,
    prior_ranges: PriorRanges,
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
    length = round(
        _sample_with_priors(
            rng,
            key="Length",
            low=length_low,
            high=max(length_low + 1.0, length_high),
            exploratory=exploratory,
            prior_ranges=prior_ranges,
        ),
        3,
    )

    throat_diameter = round(
        _sample_with_priors(
            rng,
            key="Throat.Diameter",
            low=10.0 if exploratory else 20.0,
            high=140.0 if exploratory else 65.0,
            exploratory=exploratory,
            prior_ranges=prior_ranges,
        ),
        3,
    )
    throat_angle = round(
        _sample_with_priors(
            rng,
            key="Throat.Angle",
            low=0.0 if exploratory else 2.0,
            high=28.0 if exploratory else 9.5,
            exploratory=exploratory,
            prior_ranges=prior_ranges,
        ),
        3,
    )

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
                (
                    "R-OSSE.r0",
                    round(
                        _sample_with_priors(
                            rng,
                            key="R-OSSE.r0",
                            low=3.0,
                            high=48.0 if exploratory else 28.0,
                            exploratory=exploratory,
                            prior_ranges=prior_ranges,
                        ),
                        4,
                    ),
                ),
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
                (
                    "CircArc.Radius",
                    round(
                        _sample_with_priors(
                            rng,
                            key="CircArc.Radius",
                            low=35.0,
                            high=hard_cap_mm * (0.3 if exploratory else 0.18),
                            exploratory=exploratory,
                            prior_ranges=prior_ranges,
                        ),
                        4,
                    ),
                ),
            ]
        )

    if gcurve_type is None:
        fields.append(("Coverage.Angle", round(_sample_float(rng, 12.0, 130.0 if exploratory else 95.0, exploratory=exploratory), 4)))
    else:
        fields.extend(
            [
                ("GCurve.Type", int(gcurve_type)),
                (
                    "GCurve.Dist",
                    round(
                        _sample_with_priors(
                            rng,
                            key="GCurve.Dist",
                            low=8.0,
                            high=max_dim_mm * (0.9 if exploratory else 0.35),
                            exploratory=exploratory,
                            prior_ranges=prior_ranges,
                        ),
                        4,
                    ),
                ),
                (
                    "GCurve.Width",
                    round(
                        _sample_with_priors(
                            rng,
                            key="GCurve.Width",
                            low=18.0,
                            high=max_dim_mm * (0.85 if exploratory else 0.32),
                            exploratory=exploratory,
                            prior_ranges=prior_ranges,
                        ),
                        4,
                    ),
                ),
                ("GCurve.Rot", round(_sample_float(rng, -20.0 if exploratory else -8.0, 20.0 if exploratory else 8.0, exploratory=exploratory), 4)),
                ("GCurve.AspectRatio", round(_sample_float(rng, 0.3 if exploratory else 0.7, 2.6 if exploratory else 1.6, exploratory=exploratory), 4)),
            ]
        )
        if int(gcurve_type) == 1:
            fields.append(("GCurve.SE.n", round(_sample_float(rng, 2.0, 7.0 if exploratory else 4.2, exploratory=exploratory), 4)))
        elif int(gcurve_type) == 2:
            fields.extend(
                [
                    ("GCurve.SF.a", round(_sample_float(rng, 0.5 if exploratory else 0.7, 1.6 if exploratory else 1.25, exploratory=exploratory), 4)),
                    ("GCurve.SF.b", round(_sample_float(rng, 0.5 if exploratory else 0.7, 1.6 if exploratory else 1.25, exploratory=exploratory), 4)),
                    ("GCurve.SF.m1", round(_sample_float(rng, 1.5 if exploratory else 2.0, 10.0 if exploratory else 7.5, exploratory=exploratory), 4)),
                    ("GCurve.SF.m2", round(_sample_float(rng, 1.5 if exploratory else 2.0, 10.0 if exploratory else 7.5, exploratory=exploratory), 4)),
                    ("GCurve.SF.n1", round(_sample_float(rng, 0.1 if exploratory else 0.2, 1.4 if exploratory else 0.95, exploratory=exploratory), 4)),
                    ("GCurve.SF.n2", round(_sample_float(rng, 0.3 if exploratory else 0.5, 2.4 if exploratory else 1.8, exploratory=exploratory), 4)),
                    ("GCurve.SF.n3", round(_sample_float(rng, 0.3 if exploratory else 0.5, 2.4 if exploratory else 1.8, exploratory=exploratory), 4)),
                ]
            )

    if morph_target_shape != 0:
        tgt_max = max_dim_mm * (0.95 if exploratory else 0.45)
        fields.extend(
            [
                (
                    "Morph.TargetWidth",
                    round(
                        _sample_with_priors(
                            rng,
                            key="Morph.TargetWidth",
                            low=45.0,
                            high=max(60.0, tgt_max),
                            exploratory=exploratory,
                            prior_ranges=prior_ranges,
                        ),
                        4,
                    ),
                ),
                (
                    "Morph.TargetHeight",
                    round(
                        _sample_with_priors(
                            rng,
                            key="Morph.TargetHeight",
                            low=45.0,
                            high=max(60.0, tgt_max),
                            exploratory=exploratory,
                            prior_ranges=prior_ranges,
                        ),
                        4,
                    ),
                ),
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

    return _apply_extreme_downweight(rng=rng, fields=fields, max_dim_mm=max_dim_mm)


def generate_experiment_cases(
    *,
    cases: int,
    seed: int,
    max_dim_mm: float,
    hard_cap_mm: float,
    prior_ranges: PriorRanges,
) -> List[ExperimentCase]:
    rng = random.Random(int(seed))
    generated: List[ExperimentCase] = []
    for case_index in range(1, int(cases) + 1):
        case_seed = int(rng.getrandbits(63)) ^ int(case_index * 7919)
        case_rng = random.Random(case_seed)
        exploratory = case_rng.random() < 0.30
        case = ProjectPageAthCase(
            test_id=f"PP_ATH_EXP_{case_index:04d}",
            project_name=f"PP_ATH_EXP_{case_index:04d}",
            field_values=_case_fields(
                case_rng,
                exploratory=exploratory,
                max_dim_mm=max_dim_mm,
                hard_cap_mm=hard_cap_mm,
                prior_ranges=prior_ranges,
            ),
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


def _cleanup_expected_base(*, kind: str) -> Path:
    if kind not in {"cases", "log"}:
        raise ValueError(f"Unsupported cleanup kind: {kind}")
    return (_repo_root() / "reports" / "ath_experiments" / kind).resolve()


def _validate_cleanup_base(base: Path, *, kind: str) -> bool:
    repo = _repo_root().resolve()
    reports_root = (repo / "reports").resolve()
    exp_root = (reports_root / "ath_experiments").resolve()
    expected = _cleanup_expected_base(kind=kind)
    if base != expected:
        return False
    if base in {repo, reports_root, exp_root}:
        return False
    expected_suffix = ("reports", "ath_experiments", kind)
    if tuple(base.parts[-3:]) != expected_suffix:
        return False
    return True


def _append_cleanup_log(
    *,
    reports_root: Path,
    phase: str,
    payload: Mapping[str, Any],
) -> None:
    log_name = "cleanup_pre_run.log" if phase == "pre" else "cleanup_end.log"
    log_path = reports_root / log_name
    record = {"timestamp": _now_iso(), **dict(payload)}
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _cleanup_report_files_base(
    *,
    kind: str,
    phase: str,
    reports_root: Path,
) -> Dict[str, Any]:
    base = _cleanup_expected_base(kind=kind)
    base_path_verified = _validate_cleanup_base(base, kind=kind)
    deleted_count = 0
    bytes_freed = 0
    file_count_before = 0
    created_missing_base = False

    if not base.exists():
        base.mkdir(parents=True, exist_ok=True)
        created_missing_base = True
    if not base.is_dir():
        result = {
            "phase": phase,
            "kind": kind,
            "base": str(base),
            "base_path_verified": False,
            "file_count_before": 0,
            "deleted_count": 0,
            "bytes_freed": 0,
            "error": "base_not_directory",
        }
        _append_cleanup_log(reports_root=reports_root, phase=phase, payload=result)
        return result

    if base_path_verified:
        files = [path for path in base.rglob("*") if path.is_file()]
        file_count_before = len(files)
        for file_path in files:
            resolved = file_path.resolve()
            if not resolved.is_relative_to(base):
                continue
            try:
                bytes_freed += int(resolved.stat().st_size)
            except Exception:
                pass
            resolved.unlink(missing_ok=True)
            deleted_count += 1
        directories = sorted(
            [path for path in base.rglob("*") if path.is_dir()],
            key=lambda item: len(item.parts),
            reverse=True,
        )
        for dir_path in directories:
            resolved_dir = dir_path.resolve()
            if not resolved_dir.is_relative_to(base):
                continue
            try:
                if not any(resolved_dir.iterdir()):
                    resolved_dir.rmdir()
            except Exception:
                continue

    result = {
        "phase": phase,
        "kind": kind,
        "base": str(base),
        "base_path_verified": bool(base_path_verified),
        "created_missing_base": bool(created_missing_base),
        "file_count_before": int(file_count_before),
        "deleted_count": int(deleted_count),
        "bytes_freed": int(bytes_freed),
    }
    _append_cleanup_log(reports_root=reports_root, phase=phase, payload=result)
    return result


def _cleanup_report_files(
    *,
    reports_root: Path,
    phase: str,
    cleanup_cases: bool,
    cleanup_log: bool,
) -> Dict[str, Any]:
    results: Dict[str, Any] = {"phase": phase, "actions": {}}
    if cleanup_cases:
        results["actions"]["cases"] = _cleanup_report_files_base(kind="cases", phase=phase, reports_root=reports_root)
    if cleanup_log:
        results["actions"]["log"] = _cleanup_report_files_base(kind="log", phase=phase, reports_root=reports_root)

    sqlite_path = (reports_root / "ath_experiments.sqlite").resolve()
    summary_path = (reports_root / "summary.json").resolve()
    summary_md = (reports_root / "summary.md").resolve()
    range_v1 = (reports_root / "range_suggestions.v1.json").resolve()
    range_v11 = (reports_root / "range_suggestions.v1.1.json").resolve()
    results["verify"] = {
        "ath_experiments_sqlite_exists": sqlite_path.exists(),
        "summary_json_exists": summary_path.exists(),
        "summary_md_exists": summary_md.exists(),
        "range_suggestions_v1_exists": range_v1.exists(),
        "range_suggestions_v11_exists": range_v11.exists(),
    }
    return results


def _parse_value_num(value: Any) -> Optional[float]:
    try:
        text = str(value).strip().replace(",", ".")
        if not text:
            return None
        return float(text)
    except Exception:
        return None


def _normalize_mm(value: str, unit: str) -> Optional[float]:
    try:
        parsed = float(str(value).replace(",", "."))
    except Exception:
        return None
    if str(unit).strip().lower() == "m":
        return parsed * 1000.0
    return parsed


def parse_ath_output_metrics(stdout_text: str, stderr_text: str) -> Dict[str, Any]:
    combined = f"{stdout_text}\n{stderr_text}"
    width_mm: Optional[float] = None
    height_mm: Optional[float] = None
    length_mm: Optional[float] = None
    angle_deg: Optional[float] = None

    width_match = _WIDTH_HEIGHT_RE.search(combined)
    if width_match is not None:
        width_mm = _normalize_mm(width_match.group(1), width_match.group(3))
        height_mm = _normalize_mm(width_match.group(2), width_match.group(3))

    length_match = _LENGTH_RE.search(combined)
    if length_match is not None:
        length_mm = _normalize_mm(length_match.group(1), length_match.group(2))

    angle_match = _THROAT_ANGLE_RE.search(combined)
    if angle_match is not None:
        try:
            angle_deg = float(str(angle_match.group(1)).replace(",", "."))
        except Exception:
            angle_deg = None

    volume_m3: Optional[float] = None
    if width_mm is not None and height_mm is not None and length_mm is not None:
        volume_m3 = (width_mm * height_mm * length_mm) / 1_000_000_000.0

    return {
        "final_width_mm": width_mm,
        "final_height_mm": height_mm,
        "final_length_mm": length_mm,
        "avg_throat_angle_deg": angle_deg,
        "derived_volume_m3": volume_m3,
    }


def _first_matching_line(text: str, pattern: re.Pattern[str]) -> Optional[str]:
    for line in text.splitlines():
        if pattern.search(line):
            return line.strip()
    return None


def classify_ath_output(stdout_text: str, stderr_text: str, *, exit_code: Optional[int]) -> Dict[str, Any]:
    combined = f"{stdout_text}\n{stderr_text}"
    warning_count = len(_ATH_WARN_RE.findall(combined))
    if exit_code is None or exit_code == 0:
        return {
            "ath_warning_count": warning_count,
            "ath_error_kind": None,
            "ath_error_message": None,
        }

    for kind, pattern in _ATH_ERROR_PATTERNS:
        if pattern.search(combined):
            line = _first_matching_line(combined, pattern)
            return {
                "ath_warning_count": warning_count,
                "ath_error_kind": kind,
                "ath_error_message": line or kind,
            }

    tail_line = ""
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    if lines:
        tail_line = lines[-1]
    return {
        "ath_warning_count": warning_count,
        "ath_error_kind": "ath_nonzero_exit",
        "ath_error_message": tail_line or f"ATH exited with code {exit_code}",
    }


def _ensure_db_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS experiment_runs(
            run_id TEXT PRIMARY KEY,
            run_group_id TEXT,
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

    columns = {
        str(row[1])
        for row in conn.execute("PRAGMA table_info(experiment_runs)").fetchall()
    }
    if "run_group_id" not in columns:
        conn.execute("ALTER TABLE experiment_runs ADD COLUMN run_group_id TEXT")

    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_runs_status ON experiment_runs(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_runs_case_index ON experiment_runs(case_index)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_runs_error_kind ON experiment_runs(ath_error_kind)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_runs_group ON experiment_runs(run_group_id)")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ux_experiment_runs_group_seed_case
        ON experiment_runs(run_group_id, seed, case_index)
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_params_key ON experiment_params(key)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_params_value_num ON experiment_params(value_num)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_metrics_length_mm ON experiment_metrics(final_length_mm)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_metrics_width_mm ON experiment_metrics(final_width_mm)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_experiment_metrics_height_mm ON experiment_metrics(final_height_mm)")


def _legacy_group_base_name(seed: int) -> str:
    seed_int = int(seed)
    if seed_int == 1337:
        return "legacy_500_seed1337"
    if seed_int == 2026:
        return "legacy_5000_seed2026"
    return f"legacy_seed_{seed_int}"


def _backfill_legacy_null_run_groups(conn: sqlite3.Connection) -> Dict[str, Any]:
    rows = conn.execute(
        """
        SELECT run_id, seed, case_index, created_at
        FROM experiment_runs
        WHERE run_group_id IS NULL
        ORDER BY seed, case_index, created_at, run_id
        """
    ).fetchall()
    if not rows:
        return {
            "applied": True,
            "changed_rows": 0,
            "source_null_rows": 0,
            "groups_created": {},
            "idempotent_noop": True,
        }

    target_seeds = sorted({int(row[1]) for row in rows})
    occupied_rows = conn.execute(
        f"""
        SELECT seed, case_index, run_group_id
        FROM experiment_runs
        WHERE run_group_id IS NOT NULL
          AND seed IN ({", ".join("?" for _ in target_seeds)})
        """,
        tuple(target_seeds),
    ).fetchall()
    occupied: set[Tuple[int, int, str]] = set()
    for seed, case_index, run_group_id in occupied_rows:
        if run_group_id is None:
            continue
        occupied.add((int(seed), int(case_index), str(run_group_id)))

    attempts_per_case: Dict[Tuple[int, int], int] = {}
    updates: List[Tuple[str, str]] = []
    groups_created: Dict[str, int] = {}

    for row in rows:
        run_id = str(row[0])
        seed = int(row[1])
        case_index = int(row[2])
        base = _legacy_group_base_name(seed)
        key = (seed, case_index)
        attempt = int(attempts_per_case.get(key, 0)) + 1
        while True:
            group_name = base if attempt == 1 else f"{base}_retry{attempt}"
            slot = (seed, case_index, group_name)
            if slot not in occupied:
                occupied.add(slot)
                break
            attempt += 1
        attempts_per_case[key] = attempt
        updates.append((group_name, run_id))
        groups_created[group_name] = int(groups_created.get(group_name, 0)) + 1

    conn.executemany(
        "UPDATE experiment_runs SET run_group_id = ? WHERE run_id = ? AND run_group_id IS NULL",
        updates,
    )
    remaining_null = conn.execute("SELECT COUNT(*) FROM experiment_runs WHERE run_group_id IS NULL").fetchone()
    changed = int(len(rows) - int(remaining_null[0] if remaining_null else 0))
    return {
        "applied": True,
        "changed_rows": changed,
        "source_null_rows": len(rows),
        "groups_created": groups_created,
        "idempotent_noop": changed == 0,
    }


def _persist_experiment_row(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    run_group_id: Optional[str],
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
    metrics: Mapping[str, Any],
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO experiment_runs(
            run_id, run_group_id, created_at, seed, case_index, status, ath_exit_code, ath_error_kind,
            ath_error_message, ath_warning_count, cfg_path, horns_export_dir, stdout_path, stderr_path, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            run_group_id,
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
    conn.execute(
        """
        INSERT OR REPLACE INTO experiment_metrics(
            run_id, final_width_mm, final_height_mm, final_length_mm, avg_throat_angle_deg, derived_volume_m3, flags_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            metrics.get("final_width_mm"),
            metrics.get("final_height_mm"),
            metrics.get("final_length_mm"),
            metrics.get("avg_throat_angle_deg"),
            metrics.get("derived_volume_m3"),
            json.dumps(dict(metrics.get("flags", {}) or {}), ensure_ascii=False),
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


def _query_with_run_ids(conn: sqlite3.Connection, base_sql: str, run_ids: Sequence[str]) -> List[sqlite3.Row]:
    if not run_ids:
        return []
    rows: List[sqlite3.Row] = []
    chunk_size = 300
    for start in range(0, len(run_ids), chunk_size):
        chunk = list(run_ids[start : start + chunk_size])
        placeholders = ", ".join("?" for _ in chunk)
        sql = base_sql.format(placeholders=placeholders)
        rows.extend(conn.execute(sql, tuple(chunk)).fetchall())
    return rows


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _compute_range_suggestions(conn: sqlite3.Connection, run_ids: Sequence[str]) -> Dict[str, Any]:
    base_sql = """
        SELECT p.key, p.value_num, r.status, r.seed, COALESCE(r.run_group_id, '')
        FROM experiment_params p
        JOIN experiment_runs r ON r.run_id = p.run_id
        WHERE p.run_id IN ({placeholders})
          AND p.is_set = 1
          AND p.value_num IS NOT NULL
    """
    rows = _query_with_run_ids(conn, base_sql, run_ids)
    grouped: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = str(row[0])
        value = _float_or_none(row[1])
        status = str(row[2] or "")
        seed = int(row[3]) if row[3] is not None else -1
        run_group = str(row[4] or "")
        if value is None:
            continue
        bucket = grouped.setdefault(
            key,
            {
                "success": [],
                "fail": [],
                "by_seed_success": {},
                "by_run_group_success": {},
            },
        )
        if status == "ok":
            bucket["success"].append(value)
            by_seed = dict(bucket["by_seed_success"])
            by_seed.setdefault(seed, []).append(value)
            bucket["by_seed_success"] = by_seed
            by_group = dict(bucket["by_run_group_success"])
            by_group.setdefault(run_group, []).append(value)
            bucket["by_run_group_success"] = by_group
        elif status in {"ath_error", "pipeline_error"}:
            bucket["fail"].append(value)

    suggestions: Dict[str, Any] = {}
    for key in sorted(grouped.keys()):
        success_values = grouped[key]["success"]
        fail_values = grouped[key]["fail"]
        success_min = min(success_values) if success_values else None
        success_max = max(success_values) if success_values else None
        fail_min = min(fail_values) if fail_values else None
        fail_max = max(fail_values) if fail_values else None
        suggestion = None
        if success_min is not None and success_max is not None:
            suggestion = {"min": success_min, "max": success_max}
        recommended = None
        if success_values:
            recommended = {
                "min": _percentile(success_values, 0.05),
                "max": _percentile(success_values, 0.95),
            }
        by_seed_ranges: Dict[str, Any] = {}
        for seed, values in sorted(dict(grouped[key].get("by_seed_success", {})).items()):
            if not values:
                continue
            by_seed_ranges[str(seed)] = {
                "success_min": min(values),
                "success_max": max(values),
                "recommended_min": _percentile(values, 0.05),
                "recommended_max": _percentile(values, 0.95),
                "samples": len(values),
            }
        by_group_ranges: Dict[str, Any] = {}
        for group, values in sorted(dict(grouped[key].get("by_run_group_success", {})).items()):
            if not values or not str(group).strip():
                continue
            by_group_ranges[str(group)] = {
                "success_min": min(values),
                "success_max": max(values),
                "recommended_min": _percentile(values, 0.05),
                "recommended_max": _percentile(values, 0.95),
                "samples": len(values),
            }
        suggestions[key] = {
            "success_min": success_min,
            "success_max": success_max,
            "fail_min": fail_min,
            "fail_max": fail_max,
            "suggested_safe_range": suggestion,
            "recommended_range_p05_p95": recommended,
            "by_seed": by_seed_ranges,
            "by_run_group": by_group_ranges,
        }
    return suggestions


def _top_error_patterns(reports: Sequence[Mapping[str, Any]], *, limit: int = 10) -> List[Dict[str, Any]]:
    counts: Dict[str, Dict[str, Any]] = {}
    for report in reports:
        status = str(report.get("status", ""))
        if status != "ath_error":
            continue
        error_payload = dict(report.get("errors", {}) or {})
        kind = str(error_payload.get("ath_error_kind") or "unknown")
        item = counts.setdefault(kind, {"kind": kind, "count": 0, "example_run_ids": []})
        item["count"] = int(item["count"]) + 1
        run_id = str(report.get("run_id") or "")
        if run_id and len(item["example_run_ids"]) < 5:
            item["example_run_ids"].append(run_id)
    ranked = sorted(counts.values(), key=lambda item: int(item["count"]), reverse=True)
    return ranked[: max(1, int(limit))]


def _dimension_threshold_hits(reports: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    warn_hits = 0
    hard_cap_hits = 0
    for report in reports:
        metrics = dict(report.get("metrics", {}) or {})
        flags = dict(metrics.get("flags", {}) or {})
        if bool(flags.get("max_dim_warn")):
            warn_hits += 1
        if bool(flags.get("hard_cap_exceeded")):
            hard_cap_hits += 1
    return {
        "max_dim_warn_hits": warn_hits,
        "hard_cap_hits": hard_cap_hits,
    }


def _mode_from_report(report: Mapping[str, Any]) -> Dict[str, str]:
    input_summary = dict(report.get("input_summary", {}) or {})
    field_values_raw = list(input_summary.get("field_values", []) or [])
    values: Dict[str, Any] = {}
    for item in field_values_raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            continue
        values[str(item[0])] = item[1]

    throat_profile_map = {1: "OS-SE", 2: "R-OSSE", 3: "Circular Arc"}
    throat_value = values.get("Throat.Profile")
    try:
        throat_mode = throat_profile_map.get(int(throat_value), "Unknown")
    except Exception:
        throat_mode = "Unknown"

    gcurve_value = values.get("GCurve.Type")
    if gcurve_value is None:
        gcurve_mode = "no_gcurve"
    else:
        try:
            gcurve_mode = {1: "superellipse", 2: "superformula"}.get(int(gcurve_value), "other")
        except Exception:
            gcurve_mode = "other"

    morph_value = values.get("Morph.TargetShape")
    morph_mode = "morph_off"
    try:
        if morph_value is not None and int(morph_value) != 0:
            morph_mode = "morph_on"
    except Exception:
        morph_mode = "morph_on" if morph_value is not None else "morph_off"

    enclosure_mode = "enclosure_on" if any(str(key).startswith("Mesh.Enclosure") for key in values.keys()) else "enclosure_off"
    return {
        "gcurve": gcurve_mode,
        "throat_profile": throat_mode,
        "morph": morph_mode,
        "enclosure": enclosure_mode,
    }


def _mode_error_rates(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    dimensions = ("gcurve", "throat_profile", "morph", "enclosure")
    buckets: Dict[str, Dict[str, Dict[str, int]]] = {name: {} for name in dimensions}
    for report in reports:
        status = str(report.get("status", ""))
        modes = _mode_from_report(report)
        for dimension in dimensions:
            mode_name = str(modes.get(dimension, "unknown"))
            entry = buckets[dimension].setdefault(mode_name, {"total": 0, "ath_error": 0, "non_ok": 0})
            entry["total"] += 1
            if status == "ath_error":
                entry["ath_error"] += 1
            if status != "ok":
                entry["non_ok"] += 1
    result: Dict[str, Any] = {}
    for dimension in dimensions:
        result[dimension] = {}
        for mode_name, counts in sorted(buckets[dimension].items()):
            total = max(1, int(counts["total"]))
            result[dimension][mode_name] = {
                "total": int(counts["total"]),
                "ath_error": int(counts["ath_error"]),
                "non_ok": int(counts["non_ok"]),
                "ath_error_rate": float(counts["ath_error"]) / float(total),
                "non_ok_rate": float(counts["non_ok"]) / float(total),
            }
    return result


def _error_class_mode_breakdown(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    classes: Dict[str, Dict[str, Any]] = {}
    for report in reports:
        status = str(report.get("status", ""))
        if status != "ath_error":
            continue
        errors = dict(report.get("errors", {}) or {})
        error_class = str(errors.get("ath_error_kind") or "unknown")
        item = classes.setdefault(
            error_class,
            {
                "count": 0,
                "example_run_ids": [],
                "mode_counts": {
                    "gcurve": {},
                    "throat_profile": {},
                    "morph": {},
                    "enclosure": {},
                },
            },
        )
        item["count"] = int(item["count"]) + 1
        run_id = str(report.get("run_id") or "")
        if run_id and len(item["example_run_ids"]) < 5:
            item["example_run_ids"].append(run_id)
        modes = _mode_from_report(report)
        for key in ("gcurve", "throat_profile", "morph", "enclosure"):
            mode_name = str(modes.get(key, "unknown"))
            counts = dict(item["mode_counts"].get(key, {}))
            counts[mode_name] = int(counts.get(mode_name, 0)) + 1
            item["mode_counts"][key] = counts

    ranked = sorted(classes.items(), key=lambda kv: int(kv[1]["count"]), reverse=True)
    return {key: value for key, value in ranked}


def _build_mode_error_matrix(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    matrix: Dict[str, Dict[str, Dict[str, int]]] = {
        "gcurve": {},
        "throat_profile": {},
        "morph": {},
        "enclosure": {},
    }
    for report in reports:
        status = str(report.get("status", "ok"))
        errors = dict(report.get("errors", {}) or {})
        error_class = "ok" if status == "ok" else str(errors.get("ath_error_kind") or status)
        modes = _mode_from_report(report)
        for axis in ("gcurve", "throat_profile", "morph", "enclosure"):
            mode_name = str(modes.get(axis, "unknown"))
            axis_map = matrix[axis].setdefault(mode_name, {})
            axis_map[error_class] = int(axis_map.get(error_class, 0)) + 1
    return matrix


def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    if not values:
        return None
    sorted_values = sorted(float(value) for value in values)
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    q_clamped = min(1.0, max(0.0, float(q)))
    position = q_clamped * (len(sorted_values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(sorted_values[lower])
    ratio = position - lower
    return float(sorted_values[lower] * (1.0 - ratio) + sorted_values[upper] * ratio)


def _dimension_distribution_stats(reports: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    metrics_keys = ("final_length_mm", "final_width_mm", "final_height_mm")
    values_by_key: Dict[str, List[float]] = {key: [] for key in metrics_keys}
    for report in reports:
        metrics = dict(report.get("metrics", {}) or {})
        for key in metrics_keys:
            value = _parse_value_num(metrics.get(key))
            if value is None:
                continue
            values_by_key[key].append(float(value))
    result: Dict[str, Any] = {}
    for key in metrics_keys:
        values = values_by_key[key]
        result[key] = {
            "count": len(values),
            "p50": _percentile(values, 0.50),
            "p90": _percentile(values, 0.90),
            "p99": _percentile(values, 0.99),
            "min": min(values) if values else None,
            "max": max(values) if values else None,
        }
    return result


def _hard_cap_correlated_keys(
    conn: sqlite3.Connection,
    *,
    run_ids: Sequence[str],
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    metric_sql = """
        SELECT m.run_id, m.flags_json
        FROM experiment_metrics m
        WHERE m.run_id IN ({placeholders})
    """
    metric_rows = _query_with_run_ids(conn, metric_sql, run_ids)
    hard_cap_ids: set[str] = set()
    for row in metric_rows:
        run_id = str(row[0])
        flags_raw = str(row[1] or "{}")
        try:
            flags = json.loads(flags_raw)
        except Exception:
            flags = {}
        if isinstance(flags, Mapping) and bool(flags.get("hard_cap_exceeded")):
            hard_cap_ids.add(run_id)

    ok_sql = """
        SELECT run_id
        FROM experiment_runs
        WHERE run_id IN ({placeholders}) AND status = 'ok'
    """
    ok_rows = _query_with_run_ids(conn, ok_sql, run_ids)
    ok_ids = {str(row[0]) for row in ok_rows}
    if not hard_cap_ids or not ok_ids:
        return []

    param_sql = """
        SELECT run_id, key, value_num
        FROM experiment_params
        WHERE run_id IN ({placeholders}) AND is_set = 1 AND value_num IS NOT NULL
    """
    param_rows = _query_with_run_ids(conn, param_sql, run_ids)
    grouped: Dict[str, Dict[str, List[float]]] = {}
    for row in param_rows:
        run_id = str(row[0])
        key = str(row[1])
        value = _float_or_none(row[2])
        if value is None:
            continue
        bucket = grouped.setdefault(key, {"hard_cap": [], "ok": []})
        if run_id in hard_cap_ids:
            bucket["hard_cap"].append(float(value))
        elif run_id in ok_ids:
            bucket["ok"].append(float(value))

    ranked: List[Dict[str, Any]] = []
    for key, bucket in grouped.items():
        hard_values = bucket["hard_cap"]
        ok_values = bucket["ok"]
        if len(hard_values) < 8 or len(ok_values) < 8:
            continue
        hard_mean = sum(hard_values) / len(hard_values)
        ok_mean = sum(ok_values) / len(ok_values)
        delta = hard_mean - ok_mean
        ratio = delta / (abs(ok_mean) + 1e-9)
        ranked.append(
            {
                "key": key,
                "hard_cap_samples": len(hard_values),
                "ok_samples": len(ok_values),
                "hard_cap_mean": hard_mean,
                "ok_mean": ok_mean,
                "delta": delta,
                "delta_ratio": ratio,
                "score": abs(ratio),
            }
        )
    ranked.sort(key=lambda item: float(item.get("score", 0.0)), reverse=True)
    return [{k: v for k, v in item.items() if k != "score"} for item in ranked[: max(1, int(top_n))]]


def _run_ids_for_groups(conn: sqlite3.Connection, *, run_groups: Sequence[str]) -> List[str]:
    groups = [str(group).strip() for group in run_groups if str(group).strip()]
    if not groups:
        return []
    placeholders = ", ".join("?" for _ in groups)
    rows = conn.execute(
        f"""
        SELECT run_id
        FROM experiment_runs
        WHERE run_group_id IN ({placeholders})
        ORDER BY created_at, run_id
        """,
        tuple(groups),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _reports_from_db(conn: sqlite3.Connection, *, run_ids: Sequence[str]) -> List[Dict[str, Any]]:
    if not run_ids:
        return []
    runs_sql = """
        SELECT run_id, status, ath_error_kind
        FROM experiment_runs
        WHERE run_id IN ({placeholders})
    """
    metrics_sql = """
        SELECT run_id, final_width_mm, final_height_mm, final_length_mm, avg_throat_angle_deg, flags_json
        FROM experiment_metrics
        WHERE run_id IN ({placeholders})
    """
    params_sql = """
        SELECT run_id, key, value_text, value_num
        FROM experiment_params
        WHERE run_id IN ({placeholders})
          AND is_set = 1
          AND (
            key IN ('Throat.Profile', 'GCurve.Type', 'Morph.TargetShape')
            OR key LIKE 'Mesh.Enclosure%'
          )
    """

    run_rows = _query_with_run_ids(conn, runs_sql, run_ids)
    metric_rows = _query_with_run_ids(conn, metrics_sql, run_ids)
    param_rows = _query_with_run_ids(conn, params_sql, run_ids)

    runs_map: Dict[str, Dict[str, Any]] = {}
    for row in run_rows:
        runs_map[str(row[0])] = {
            "status": str(row[1] or "pipeline_error"),
            "ath_error_kind": str(row[2] or "") or None,
        }

    metrics_map: Dict[str, Dict[str, Any]] = {}
    for row in metric_rows:
        raw_flags = str(row[5] or "{}")
        try:
            flags = json.loads(raw_flags)
        except Exception:
            flags = {}
        metrics_map[str(row[0])] = {
            "final_width_mm": _float_or_none(row[1]),
            "final_height_mm": _float_or_none(row[2]),
            "final_length_mm": _float_or_none(row[3]),
            "avg_throat_angle_deg": _float_or_none(row[4]),
            "flags": flags if isinstance(flags, Mapping) else {},
        }

    fields_map: Dict[str, Dict[str, Any]] = {}
    for row in param_rows:
        run_id = str(row[0])
        key = str(row[1])
        value = _float_or_none(row[3])
        if value is None:
            value = row[2]
        bucket = fields_map.setdefault(run_id, {})
        bucket[key] = value

    ordered: List[Dict[str, Any]] = []
    for run_id in run_ids:
        run_payload = runs_map.get(run_id, {"status": "pipeline_error", "ath_error_kind": None})
        metrics = metrics_map.get(run_id, {})
        values = fields_map.get(run_id, {})
        ordered.append(
            {
                "run_id": run_id,
                "status": str(run_payload.get("status", "pipeline_error")),
                "errors": {
                    "ath_error_kind": run_payload.get("ath_error_kind"),
                },
                "metrics": metrics,
                "input_summary": {
                    "field_values": [[key, value] for key, value in sorted(values.items())],
                },
            }
        )
    return ordered


def _largest_safe_range_tightenings(
    *,
    prior_ranges: PriorRanges,
    current_ranges: Mapping[str, Any],
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    tightenings: List[Dict[str, Any]] = []
    for key, prior in prior_ranges.items():
        current = current_ranges.get(key)
        if not isinstance(current, Mapping):
            continue
        suggested = current.get("suggested_safe_range")
        if not isinstance(suggested, Mapping):
            continue
        try:
            new_low = float(suggested.get("min"))
            new_high = float(suggested.get("max"))
        except Exception:
            continue
        old_low, old_high = float(prior[0]), float(prior[1])
        old_width = max(0.0, old_high - old_low)
        new_width = max(0.0, new_high - new_low)
        if old_width <= 0:
            continue
        shrink = old_width - new_width
        if shrink <= 0:
            continue
        tightenings.append(
            {
                "key": key,
                "old_range": {"min": old_low, "max": old_high},
                "new_range": {"min": new_low, "max": new_high},
                "shrink_abs": shrink,
                "shrink_ratio": shrink / old_width,
            }
        )
    tightenings.sort(key=lambda item: float(item.get("shrink_ratio", 0.0)), reverse=True)
    return tightenings[: max(1, int(top_n))]


def _write_summary_markdown(
    *,
    summary_path: Path,
    status_counts: Mapping[str, Any],
    top_errors: Sequence[Mapping[str, Any]],
    threshold_hits: Mapping[str, Any],
    mode_error_rates: Mapping[str, Any],
    dimension_stats: Mapping[str, Any],
    error_class_modes: Mapping[str, Any],
    cases: int,
    seed: int,
) -> Path:
    lines = [
        "# ATH Project Page Experiment Summary",
        "",
        f"- Cases requested: {int(cases)}",
        f"- Seed: {int(seed)}",
        f"- OK: {int(status_counts.get('ok', 0))}",
        f"- ATH errors: {int(status_counts.get('ath_error', 0))}",
        f"- Pipeline errors: {int(status_counts.get('pipeline_error', 0))}",
        f"- Skipped: {int(status_counts.get('skipped', 0))}",
        "",
        "## Top ATH Error Patterns",
    ]
    if top_errors:
        for item in top_errors:
            lines.append(
                f"- {item.get('kind')}: {int(item.get('count', 0))} "
                f"(examples: {', '.join(list(item.get('example_run_ids', []) or []))})"
            )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Dimension Threshold Hits",
            f"- max_dim_warn_hits: {int(threshold_hits.get('max_dim_warn_hits', 0))}",
            f"- hard_cap_hits: {int(threshold_hits.get('hard_cap_hits', 0))}",
            "",
            "## Mode Error Rates",
        ]
    )
    for group_name, group_values in dict(mode_error_rates).items():
        lines.append(f"- {group_name}:")
        for mode_name, payload in dict(group_values or {}).items():
            lines.append(
                f"  - {mode_name}: total={int(payload.get('total', 0))}, "
                f"ath_error_rate={float(payload.get('ath_error_rate', 0.0)):.3f}, "
                f"non_ok_rate={float(payload.get('non_ok_rate', 0.0)):.3f}"
            )
    lines.extend(
        [
            "",
            "## Dimension Distribution",
        ]
    )
    for key, payload in dict(dimension_stats or {}).items():
        lines.append(
            f"- {key}: p50={payload.get('p50')}, p90={payload.get('p90')}, p99={payload.get('p99')}, "
            f"min={payload.get('min')}, max={payload.get('max')}"
        )
    lines.extend(
        [
            "",
            "## Error Classes (Mode View)",
        ]
    )
    for error_class, payload in dict(error_class_modes or {}).items():
        lines.append(f"- {error_class}: count={int(payload.get('count', 0))}")
        mode_counts = dict(payload.get("mode_counts", {}) or {})
        for axis in ("gcurve", "throat_profile", "morph", "enclosure"):
            axis_counts = dict(mode_counts.get(axis, {}) or {})
            if not axis_counts:
                continue
            compact = ", ".join(f"{key}={int(value)}" for key, value in sorted(axis_counts.items()))
            lines.append(f"  - {axis}: {compact}")
    lines.extend(
        [
            "",
            "## Anti-Spurious Guidance",
            "- Interpret correlations as risk indicators, not direct causality.",
            "- Prioritize stable effects across modes/seeds and threshold behaviors.",
            "- Validate top candidates with controlled counterfactual mini-runs.",
        ]
    )
    lines.append("")
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    return summary_path


def _sanitize_history_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return cleaned.strip("_") or "default"


def _write_history_snapshots(
    *,
    reports_root: Path,
    summary_payload: Mapping[str, Any],
    range_payload: Mapping[str, Any],
    run_group_label: str,
) -> Dict[str, str]:
    history_root = reports_root / "history"
    history_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    group_token = _sanitize_history_label(run_group_label)[:80]
    summary_path = history_root / f"summary_{group_token}_{timestamp}.json"
    range_path = history_root / f"range_suggestions_{timestamp}.json"
    summary_path.write_text(json.dumps(dict(summary_payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    range_path.write_text(json.dumps(dict(range_payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {
        "summary_snapshot_path": str(summary_path),
        "range_snapshot_path": str(range_path),
    }


def _table_columns(conn: sqlite3.Connection, *, table_name: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [str(row[1]) for row in rows]


def _group_top_errors(conn: sqlite3.Connection, *, limit: int = 3) -> Dict[str, List[Dict[str, Any]]]:
    rows = conn.execute(
        """
        SELECT COALESCE(run_group_id, '<null>') AS run_group, COALESCE(ath_error_kind, 'unknown') AS error_kind, COUNT(*) AS count
        FROM experiment_runs
        WHERE status = 'ath_error'
        GROUP BY COALESCE(run_group_id, '<null>'), COALESCE(ath_error_kind, 'unknown')
        ORDER BY run_group ASC, count DESC, error_kind ASC
        """
    ).fetchall()
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for run_group, error_kind, count in rows:
        key = str(run_group)
        bucket = grouped.setdefault(key, [])
        if len(bucket) >= max(1, int(limit)):
            continue
        bucket.append({"kind": str(error_kind), "count": int(count)})
    return grouped


def _write_data_inventory_markdown(
    *,
    conn: sqlite3.Connection,
    reports_root: Path,
    backfill_result: Optional[Mapping[str, Any]],
) -> Tuple[Path, Dict[str, Any]]:
    table_rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name LIKE 'experiment_%'
        ORDER BY name
        """
    ).fetchall()
    table_names = [str(row[0]) for row in table_rows]
    table_meta: List[Dict[str, Any]] = []
    for table_name in table_names:
        count_row = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
        table_meta.append(
            {
                "name": table_name,
                "row_count": int(count_row[0] if count_row else 0),
                "columns": _table_columns(conn, table_name=table_name),
            }
        )

    run_group_rows = conn.execute(
        """
        SELECT
            COALESCE(run_group_id, '<null>') AS run_group,
            seed,
            COUNT(*) AS total,
            SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_count,
            SUM(CASE WHEN status='ath_error' THEN 1 ELSE 0 END) AS ath_error_count,
            SUM(CASE WHEN status='pipeline_error' THEN 1 ELSE 0 END) AS pipeline_error_count,
            SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped_count,
            MIN(case_index) AS min_case_index,
            MAX(case_index) AS max_case_index
        FROM experiment_runs
        GROUP BY COALESCE(run_group_id, '<null>'), seed
        ORDER BY run_group, seed
        """
    ).fetchall()
    run_group_counts: List[Dict[str, Any]] = []
    for row in run_group_rows:
        run_group_counts.append(
            {
                "run_group": str(row[0]),
                "seed": int(row[1]) if row[1] is not None else None,
                "total": int(row[2] or 0),
                "ok": int(row[3] or 0),
                "ath_error": int(row[4] or 0),
                "pipeline_error": int(row[5] or 0),
                "skipped": int(row[6] or 0),
                "min_case_index": int(row[7]) if row[7] is not None else None,
                "max_case_index": int(row[8]) if row[8] is not None else None,
            }
        )
    top_errors = _group_top_errors(conn, limit=3)
    null_row = conn.execute("SELECT COUNT(*) FROM experiment_runs WHERE run_group_id IS NULL").fetchone()
    null_count = int(null_row[0] if null_row else 0)

    lines: List[str] = [
        "# ATH Experiment Data Inventory",
        "",
        f"- Generated at: {_now_iso()}",
        f"- Database: `{str((reports_root / 'ath_experiments.sqlite').resolve())}`",
        f"- Remaining NULL run_group rows: {null_count}",
        "",
        "## Relevant Data Model",
        "- `experiment_runs`: outcomes, grouping (`run_group_id`, `seed`, `case_index`), ATH errors/warnings, file refs.",
        "- `experiment_params`: Project-page input snapshot (`key`, `value_text/value_num`, `is_set`).",
        "- `experiment_metrics`: observed dimensions/angles (`final_width_mm`, `final_height_mm`, `final_length_mm`, `avg_throat_angle_deg`).",
        "- `experiment_compare`: compare-quality flags (`config_ok`, `no_ghosts`) and mismatch payloads.",
        "",
        "## Tables and Columns",
    ]
    for item in table_meta:
        lines.append(
            f"- `{item['name']}`: rows={int(item['row_count'])}, columns={', '.join(list(item['columns']))}"
        )

    lines.extend(
        [
            "",
            "## Run Groups (including legacy)",
            "| run_group | seed | total | ok | ath_error | pipeline_error | skipped | min_case | max_case |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for item in run_group_counts:
        lines.append(
            f"| {item['run_group']} | {item['seed']} | {item['total']} | {item['ok']} | {item['ath_error']} | "
            f"{item['pipeline_error']} | {item['skipped']} | {item['min_case_index']} | {item['max_case_index']} |"
        )

    lines.extend(["", "## Top Error Patterns by run_group"])
    for run_group, items in sorted(top_errors.items()):
        compact = ", ".join(f"{entry['kind']}={int(entry['count'])}" for entry in items) if items else "none"
        lines.append(f"- {run_group}: {compact}")

    if backfill_result is not None:
        lines.extend(
            [
                "",
                "## Legacy Backfill Result",
                f"- applied: {bool(backfill_result.get('applied'))}",
                f"- changed_rows: {int(backfill_result.get('changed_rows', 0))}",
                f"- source_null_rows: {int(backfill_result.get('source_null_rows', 0))}",
                f"- idempotent_noop: {bool(backfill_result.get('idempotent_noop'))}",
                f"- groups_created: {json.dumps(dict(backfill_result.get('groups_created', {}) or {}), ensure_ascii=False)}",
            ]
        )

    lines.append("")
    inventory_path = reports_root / "data_inventory.md"
    inventory_path.write_text("\n".join(lines), encoding="utf-8")
    return inventory_path, {
        "tables": table_meta,
        "run_group_counts": run_group_counts,
        "top_errors_by_group": top_errors,
        "null_run_group_rows": null_count,
    }


def _build_range_suggestions_v12(
    *,
    range_suggestions: Mapping[str, Any],
    analysis_run_groups: Sequence[str],
) -> Dict[str, Any]:
    per_key: Dict[str, Any] = {}
    for key in sorted(range_suggestions.keys()):
        payload = dict(range_suggestions.get(key, {}) or {})
        safe = dict(payload.get("suggested_safe_range", {}) or {})
        rec = dict(payload.get("recommended_range_p05_p95", {}) or {})
        by_group = dict(payload.get("by_run_group", {}) or {})
        group_names = sorted(str(name) for name in by_group.keys() if str(name).strip())

        ranges: List[Tuple[float, float]] = []
        for group_name in group_names:
            group_payload = dict(by_group.get(group_name, {}) or {})
            low = _float_or_none(group_payload.get("recommended_min"))
            high = _float_or_none(group_payload.get("recommended_max"))
            if low is None or high is None:
                continue
            if low > high:
                low, high = high, low
            ranges.append((low, high))

        consistency_score = None
        consistent = False
        if ranges:
            lows = [item[0] for item in ranges]
            highs = [item[1] for item in ranges]
            union_width = max(0.0, max(highs) - min(lows))
            intersection_width = max(0.0, min(highs) - max(lows))
            consistency_score = 1.0 if union_width <= 1e-9 else intersection_width / union_width
            consistent = bool(len(ranges) >= 3 and consistency_score >= 0.25)

        notes = "insufficient_group_coverage"
        if consistent:
            notes = "consistent_across_multiple_run_groups"
        elif ranges:
            notes = "group_ranges_partially_overlapping"

        per_key[key] = {
            "safe_min": _float_or_none(safe.get("min")),
            "safe_max": _float_or_none(safe.get("max")),
            "rec_p05": _float_or_none(rec.get("min")),
            "rec_p95": _float_or_none(rec.get("max")),
            "based_on_run_groups": group_names,
            "consistent_across_groups": consistent,
            "consistency_score": consistency_score,
            "notes": notes,
        }

    return {
        "generated_at": _now_iso(),
        "analysis_run_groups": [str(group) for group in analysis_run_groups],
        "analysis_run_group_count": len({str(group) for group in analysis_run_groups}),
        "per_key": per_key,
    }


def _build_precision_outputs(
    *,
    conn: sqlite3.Connection,
    run_ids: Sequence[str],
    analysis_run_groups: Sequence[str],
    reports_root: Path,
    status_counts: Mapping[str, Any],
    top_errors: Sequence[Mapping[str, Any]],
    error_class_modes: Mapping[str, Any],
    threshold_hits: Mapping[str, Any],
    range_suggestions: Mapping[str, Any],
) -> Tuple[Path, Path, Dict[str, Any]]:
    if not run_ids:
        empty_rules = {
            "generated_at": _now_iso(),
            "analysis_run_groups": [str(item) for item in analysis_run_groups],
            "candidates": [],
        }
        candidates_path = reports_root / "compat_rule_candidates.v1.json"
        candidates_path.write_text(json.dumps(empty_rules, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        plan_path = reports_root / "precision_plan.md"
        plan_path.write_text("# ATH Precision Plan\n\nNo analysis run_ids available.\n", encoding="utf-8")
        return plan_path, candidates_path, {"condition_stats": {}, "baseline_rate": 0.0}

    run_sql = """
        SELECT run_id, COALESCE(run_group_id, '<null>'), status, COALESCE(ath_error_kind, '')
        FROM experiment_runs
        WHERE run_id IN ({placeholders})
    """
    param_sql = """
        SELECT run_id, key, value_num
        FROM experiment_params
        WHERE run_id IN ({placeholders})
          AND is_set = 1
          AND key IN (
            'Throat.Profile', 'GCurve.Type', 'Coverage.Angle', 'Length',
            'GCurve.Width', 'GCurve.Dist', 'GCurve.Rot', 'Morph.TargetShape'
          )
    """
    metrics_sql = """
        SELECT run_id, final_width_mm, final_height_mm, final_length_mm, avg_throat_angle_deg
        FROM experiment_metrics
        WHERE run_id IN ({placeholders})
    """
    run_rows = _query_with_run_ids(conn, run_sql, run_ids)
    param_rows = _query_with_run_ids(conn, param_sql, run_ids)
    metric_rows = _query_with_run_ids(conn, metrics_sql, run_ids)

    records: Dict[str, Dict[str, Any]] = {}
    for row in run_rows:
        run_id = str(row[0])
        records[run_id] = {
            "run_group": str(row[1] or "<null>"),
            "status": str(row[2] or "pipeline_error"),
            "ath_error_kind": str(row[3] or ""),
            "params": {},
            "metrics": {},
        }
    for row in param_rows:
        run_id = str(row[0])
        key = str(row[1])
        value = _float_or_none(row[2])
        if run_id in records and value is not None:
            records[run_id]["params"][key] = value
    for row in metric_rows:
        run_id = str(row[0])
        if run_id not in records:
            continue
        records[run_id]["metrics"] = {
            "final_width_mm": _float_or_none(row[1]),
            "final_height_mm": _float_or_none(row[2]),
            "final_length_mm": _float_or_none(row[3]),
            "avg_throat_angle_deg": _float_or_none(row[4]),
        }

    baseline_total = len(records)
    baseline_errors = sum(1 for item in records.values() if str(item.get("status")) == "ath_error")
    baseline_rate = (float(baseline_errors) / float(baseline_total)) if baseline_total else 0.0
    baseline_by_group: Dict[str, float] = {}
    for group in sorted({str(item.get("run_group")) for item in records.values()}):
        group_rows = [item for item in records.values() if str(item.get("run_group")) == group]
        total = len(group_rows)
        err = sum(1 for item in group_rows if str(item.get("status")) == "ath_error")
        baseline_by_group[group] = (float(err) / float(total)) if total else 0.0

    conditions: List[Tuple[str, str, Any]] = [
        (
            "superformula_osse",
            "GCurve=superformula and Throat.Profile=OS-SE",
            lambda row: row["params"].get("GCurve.Type") == 2 and row["params"].get("Throat.Profile") == 1,
        ),
        (
            "coverage_gt_75_osse",
            "Coverage.Angle > 75 and Throat.Profile=OS-SE",
            lambda row: (row["params"].get("Coverage.Angle") or -1.0) > 75.0 and row["params"].get("Throat.Profile") == 1,
        ),
        (
            "length_gt_1000",
            "Length > 1000 mm",
            lambda row: (row["params"].get("Length") or -1.0) > 1000.0,
        ),
        (
            "observed_dim_gt_2000",
            "observed final width/height/length > 2000 mm",
            lambda row: max(
                [
                    value
                    for value in (
                        row["metrics"].get("final_width_mm"),
                        row["metrics"].get("final_height_mm"),
                        row["metrics"].get("final_length_mm"),
                    )
                    if value is not None
                ]
                or [0.0]
            )
            > 2000.0,
        ),
    ]

    condition_stats: Dict[str, Any] = {}
    for condition_id, label, fn in conditions:
        matched = [item for item in records.values() if bool(fn(item))]
        total = len(matched)
        errors = sum(1 for item in matched if str(item.get("status")) == "ath_error")
        sample_run_ids = [
            run_id
            for run_id, row in records.items()
            if bool(fn(row)) and str(row.get("status")) == "ath_error"
        ][:5]
        by_group: Dict[str, Any] = {}
        consistent_hits = 0
        group_total_for_consistency = 0
        for group in sorted({str(item.get("run_group")) for item in matched}):
            group_rows = [item for item in matched if str(item.get("run_group")) == group]
            group_total = len(group_rows)
            group_errors = sum(1 for item in group_rows if str(item.get("status")) == "ath_error")
            group_rate = (float(group_errors) / float(group_total)) if group_total else 0.0
            uplift = group_rate - float(baseline_by_group.get(group, baseline_rate))
            by_group[group] = {
                "total": group_total,
                "ath_error": group_errors,
                "ath_error_rate": group_rate,
                "uplift_vs_group_baseline": uplift,
            }
            if group_total >= 30:
                group_total_for_consistency += 1
                if uplift >= 0.10:
                    consistent_hits += 1
        consistent = bool(group_total_for_consistency >= 3 and consistent_hits >= max(2, int(math.ceil(group_total_for_consistency * 0.6))))
        condition_stats[condition_id] = {
            "label": label,
            "total": total,
            "ath_error": errors,
            "ath_error_rate": (float(errors) / float(total)) if total else 0.0,
            "sample_run_ids": sample_run_ids,
            "by_run_group": by_group,
            "consistent_multi_group": consistent,
        }

    range_v12 = _build_range_suggestions_v12(
        range_suggestions=range_suggestions,
        analysis_run_groups=analysis_run_groups,
    )

    rules_payload = {
        "generated_at": _now_iso(),
        "analysis_run_groups": [str(group) for group in analysis_run_groups],
        "candidates": [
            {
                "id": "warn_large_observed_dimensions",
                "kind": "warn",
                "when": "gt(observed.max_dimension_mm, 2000)",
                "then": "show_warning('Observed dimensions exceed 2000 mm. Risk of hard-cap errors is elevated.')",
                "severity": "medium",
                "evidence": {
                    "type": "experiment",
                    "refs": dict(condition_stats.get("observed_dim_gt_2000", {})),
                },
                "confidence": "high",
                "verification_plan": "Counterfactual mini-run: hold mode fixed, vary Length in 100 mm steps around threshold and observe hard_cap_exceeded rate.",
            },
            {
                "id": "warn_superformula_osse_combo",
                "kind": "warn",
                "when": "and(eq('GCurve.Type', 2), eq('Throat.Profile', 1))",
                "then": "show_warning('Superformula + OS-SE has elevated ATH error risk; use conservative Width/Dist/Coverage.')",
                "severity": "high",
                "evidence": {
                    "type": "experiment",
                    "refs": dict(condition_stats.get("superformula_osse", {})),
                },
                "confidence": "high",
                "verification_plan": "Fix all parameters except GCurve.Type and compare superellipse vs superformula under OS-SE.",
            },
            {
                "id": "warn_coverage_angle_osse_high",
                "kind": "warn",
                "when": "and(eq('Throat.Profile', 1), gt('Coverage.Angle', 75))",
                "then": "show_warning('High coverage angle with OS-SE increases ATH error probability.')",
                "severity": "high",
                "evidence": {
                    "type": "experiment",
                    "refs": dict(condition_stats.get("coverage_gt_75_osse", {})),
                },
                "confidence": "high",
                "verification_plan": "Sweep only Coverage.Angle on fixed OS-SE baseline to identify transition band.",
            },
            {
                "id": "warn_length_over_1000",
                "kind": "warn",
                "when": "gt('Length', 1000)",
                "then": "show_warning('Length above 1000 mm often co-occurs with hard-cap related ATH failures.')",
                "severity": "medium",
                "evidence": {
                    "type": "experiment",
                    "refs": dict(condition_stats.get("length_gt_1000", {})),
                },
                "confidence": "medium",
                "verification_plan": "Counterfactual: fixed mode, vary Length only and monitor final dimensions and hard-cap hits.",
            },
            {
                "id": "fatal_rollback_not_supported",
                "kind": "fatal",
                "when": "isDefined('Rollback')",
                "then": "block('Rollback is not supported in this ATH version. Use R-OSSE profile instead.')",
                "severity": "high",
                "evidence": {
                    "type": "ath_doc_or_known_pattern",
                    "refs": [
                        "ATH fatal pattern: 'rollback feature is no longer supported'",
                    ],
                },
                "confidence": "high",
                "verification_plan": "Keep blocked unless ATH release notes explicitly re-enable rollback.",
            },
            {
                "id": "note_superformula_diameter_over_100m",
                "kind": "note",
                "when": "eq(error_class, 'diameter_over_100m')",
                "then": "log_note('Diameter over 100m errors are concentrated in superformula mode; inspect SF shape parameters first.')",
                "severity": "low",
                "evidence": {
                    "type": "experiment",
                    "refs": dict(error_class_modes.get("diameter_over_100m", {})),
                },
                "confidence": "high",
                "verification_plan": "Run SF-only counterfactuals on m1/m2/n2/n3 with fixed Dist/Width.",
            },
        ],
    }

    plan_lines: List[str] = [
        "# ATH Precision Plan",
        "",
        "## Was wir jetzt sicher wissen",
        f"- Analysierte Runs: {len(run_ids)} across run_groups={', '.join([str(group) for group in analysis_run_groups])}",
        f"- Hard-cap Treffer: {int(threshold_hits.get('hard_cap_hits', 0))}; max_dim_warn Hits: {int(threshold_hits.get('max_dim_warn_hits', 0))}",
        f"- Baseline ATH-Error-Rate: {baseline_rate:.4f}",
        "- Robuste Aussagen basieren auf Fehlerklassen und Modus-/Schwellenmustern, nicht auf Einzelparametern.",
        "",
        "## Was wir vermuten (mit Confidence + Verification Plan)",
    ]
    for condition_id in ("superformula_osse", "coverage_gt_75_osse", "length_gt_1000", "observed_dim_gt_2000"):
        stats = dict(condition_stats.get(condition_id, {}) or {})
        if not stats:
            continue
        confidence = "high" if bool(stats.get("consistent_multi_group")) else "medium"
        plan_lines.append(
            f"- {stats.get('label')}: rate={float(stats.get('ath_error_rate', 0.0)):.4f}, "
            f"consistent_multi_group={bool(stats.get('consistent_multi_group'))}, confidence={confidence}."
        )

    plan_lines.extend(
        [
            "",
            "## Naechste 5 Gegenproben",
            "1. Base: OS-SE + superformula konservativ; vary nur `Coverage.Angle` in 5 deg Schritten (40..95). Expected signal: Fehleranstieg ab Schwelle. Success criterion: monotones Risiko-Delta.",
            "2. Base: OS-SE fixed; vary nur `GCurve.Type` no_gcurve/superellipse/superformula. Expected signal: superformula bleibt riskanter. Success criterion: stabile Rangfolge ueber >=3 seeds.",
            "3. Base: no_gcurve + OS-SE; vary nur `Length` (300..1400). Expected signal: final dimensions + hard_cap steigen mit Length. Success criterion: klarer Threshold-Bereich.",
            "4. Base: superformula + OS-SE fixed; vary nur `GCurve.Width` (200..900). Expected signal: diameter_over_100m Cluster im oberen Bereich. Success criterion: reproduzierbare Fehlerzone.",
            "5. Base: superformula + OS-SE fixed; vary nur `GCurve.Dist` (50..900). Expected signal: Interaktion mit Width, keine Einzelfaktor-Behauptung. Success criterion: 2D-Risikokarte Width x Dist.",
            "",
            "## Neue/zu ergaenzende Regeln",
            "- warn_large_observed_dimensions (warn): observed max dimension > 2000 mm.",
            "- warn_superformula_osse_combo (warn): GCurve superformula + OS-SE.",
            "- warn_coverage_angle_osse_high (warn): Coverage.Angle > 75 bei OS-SE.",
            "- warn_length_over_1000 (warn): Length > 1000 mm als Risikoindikator.",
            "- fatal_rollback_not_supported (fatal): Rollback gesetzt -> blocken (ATH inkompatibel).",
            "",
            "## Anti-Spurious Guardrails",
            "- Aussagen sind klassenbasiert (hard_cap_exceeded, diameter_over_100m, ...).",
            "- Kausale Claims nur nach Gegenprobe mit Ein-Parameter-Variation.",
            "- Interaktionen nur als Kandidaten markieren, bis ueber mehrere Seeds reproduziert.",
        ]
    )
    plan_lines.append("")

    plan_path = reports_root / "precision_plan.md"
    plan_path.write_text("\n".join(plan_lines), encoding="utf-8")

    candidates_path = reports_root / "compat_rule_candidates.v1.json"
    candidates_path.write_text(json.dumps(rules_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return plan_path, candidates_path, {
        "condition_stats": condition_stats,
        "baseline_rate": baseline_rate,
        "range_v12": range_v12,
    }


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
    run_group: Optional[str] = None,
    ath_exe: Optional[str] = None,
    template_cfg: Optional[str] = None,
    cfg_dir: str | Path = r"C:\Tools\ATH",
    export_root: str | Path = r"C:\Horns",
    reports_root: str | Path = "reports/ath_experiments",
    cleanup_files: bool = True,
    max_dim_mm: float = 2000.0,
    hard_cap_mm: float = 5000.0,
    priors_path: Optional[str] = None,
    commit_every: int = 25,
    preclean_files: bool = False,
    cleanup_cases: str = "never",
    cleanup_log: str = "never",
    aggregate_run_groups: Optional[Sequence[str]] = None,
    backfill_legacy_null_run_groups: bool = False,
    write_history_snapshots: bool = True,
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
    logs_root = reports_root_path / "log"
    cases_root = reports_root_path / "cases"
    db_path = reports_root_path / "ath_experiments.sqlite"
    resolved_priors_path = Path(priors_path) if priors_path else (reports_root_path / "range_suggestions.v1.json")
    cfg_root.mkdir(parents=True, exist_ok=True)
    export_root_path.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    cases_root.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    cleanup_cases_mode = str(cleanup_cases or "never").strip().lower()
    cleanup_log_mode = str(cleanup_log or "never").strip().lower()
    if cleanup_cases_mode not in {"end", "always", "never"}:
        raise ValueError(f"Unsupported cleanup-cases mode: {cleanup_cases}")
    if cleanup_log_mode not in {"end", "always", "never"}:
        raise ValueError(f"Unsupported cleanup-log mode: {cleanup_log}")

    preclean_result: Optional[Dict[str, Any]] = None
    if bool(preclean_files):
        preclean_result = _cleanup_report_files(
            reports_root=reports_root_path,
            phase="pre",
            cleanup_cases=True,
            cleanup_log=True,
        )

    template_text = _load_template_text(template_cfg or settings.template_cfg)
    runner = AthRunner(str(ath_executable))
    allowed_global_keys = {str(key) for key, _ in MANDATORY_SOURCE_BLOCK}
    start_cfg_index = _next_cfg_index(cfg_root)
    prior_ranges = _load_prior_ranges(resolved_priors_path)

    all_cases = generate_experiment_cases(
        cases=cases,
        seed=seed,
        max_dim_mm=max_dim_mm,
        hard_cap_mm=hard_cap_mm,
        prior_ranges=prior_ranges,
    )

    reports: List[Dict[str, Any]] = []
    status_counts = {"ok": 0, "ath_error": 0, "pipeline_error": 0, "skipped": 0}
    run_group_id = str(run_group).strip() if run_group else f"pp_ath_exp_seed_{int(seed)}"
    legacy_backfill_result: Optional[Dict[str, Any]] = None
    data_inventory_path: Optional[Path] = None
    data_inventory_payload: Dict[str, Any] = {}
    range_suggestions_v12_path: Optional[Path] = None
    range_suggestions_v12_payload: Dict[str, Any] = {}
    precision_plan_path: Optional[Path] = None
    compat_rule_candidates_path: Optional[Path] = None
    precision_analysis_payload: Dict[str, Any] = {}
    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        _ensure_db_schema(conn)
        if bool(backfill_legacy_null_run_groups):
            legacy_backfill_result = _backfill_legacy_null_run_groups(conn)
        for offset, experiment_case in enumerate(all_cases):
            existing = conn.execute(
                """
                SELECT run_id, status
                FROM experiment_runs
                WHERE run_group_id = ? AND seed = ? AND case_index = ?
                LIMIT 1
                """,
                (run_group_id, int(seed), int(experiment_case.case_index)),
            ).fetchone()
            if existing is not None:
                reports.append(
                    {
                        "run_id": str(existing["run_id"]),
                        "run_name": f"run_{experiment_case.case_index:04d}",
                        "case_index": int(experiment_case.case_index),
                        "status": "skipped",
                        "notes": "resume_existing",
                        "run_group_id": run_group_id,
                    }
                )
                status_counts["skipped"] = int(status_counts.get("skipped", 0)) + 1
                continue

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
            metrics_payload: Dict[str, Any] = {
                "final_width_mm": None,
                "final_height_mm": None,
                "final_length_mm": None,
                "avg_throat_angle_deg": None,
                "derived_volume_m3": None,
                "flags": {},
            }

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
            stdout_text = Path(run_stdout_path).read_text(encoding="utf-8", errors="replace") if run_stdout_path else ""
            stderr_text = Path(run_stderr_path).read_text(encoding="utf-8", errors="replace") if run_stderr_path else ""

            parsed_metrics = parse_ath_output_metrics(stdout_text, stderr_text)
            metrics_payload.update(parsed_metrics)
            observed_dims = [
                value
                for value in (
                    parsed_metrics.get("final_width_mm"),
                    parsed_metrics.get("final_height_mm"),
                    parsed_metrics.get("final_length_mm"),
                )
                if isinstance(value, (int, float))
            ]
            max_observed_dim = max(observed_dims) if observed_dims else None
            flags = {
                "max_dim_warn": bool(max_observed_dim is not None and float(max_observed_dim) > float(max_dim_mm)),
                "hard_cap_exceeded": bool(max_observed_dim is not None and float(max_observed_dim) > float(hard_cap_mm)),
                "throat_angle_missing": parsed_metrics.get("avg_throat_angle_deg") is None,
                "max_observed_dim_mm": max_observed_dim,
            }
            metrics_payload["flags"] = flags

            classified = classify_ath_output(
                stdout_text,
                stderr_text,
                exit_code=(ath_result.exit_code if ath_result else None),
            )
            ath_warning_count = int(classified["ath_warning_count"])
            if classified.get("ath_error_kind"):
                ath_error_kind = str(classified.get("ath_error_kind"))
            if classified.get("ath_error_message"):
                ath_error_message = str(classified.get("ath_error_message"))

            if bool(flags.get("hard_cap_exceeded")):
                status = "ath_error"
                ath_error_kind = "hard_cap_exceeded"
                ath_error_message = f"Observed dimension exceeded hard cap {hard_cap_mm} mm"
                notes = "observed_hard_cap_exceeded"

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
                "run_group_id": run_group_id,
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
                "metrics": metrics_payload,
                "cleanup": cleanup_result,
            }
            case_report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

            params_rows = _param_rows_from_payload(payload=payload, fallback_fields=case.field_values)
            _persist_experiment_row(
                conn,
                run_id=run_id,
                run_group_id=run_group_id,
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
                metrics=metrics_payload,
            )
            if cleanup_cases_mode == "always":
                _cleanup_report_files(
                    reports_root=reports_root_path,
                    phase="end",
                    cleanup_cases=True,
                    cleanup_log=False,
                )
            if cleanup_log_mode == "always":
                _cleanup_report_files(
                    reports_root=reports_root_path,
                    phase="end",
                    cleanup_cases=False,
                    cleanup_log=True,
                )
            if (offset + 1) % max(1, int(commit_every)) == 0:
                conn.commit()

            reports.append(report)
            status_counts[status] = int(status_counts.get(status, 0)) + 1

        conn.commit()

        run_ids = [str(item.get("run_id")) for item in reports if str(item.get("run_id", "")).strip()]
        analysis_groups = [str(group).strip() for group in list(aggregate_run_groups or []) if str(group).strip()]
        analysis_run_ids = run_ids
        analysis_reports = reports
        if analysis_groups:
            candidate_ids = _run_ids_for_groups(conn, run_groups=analysis_groups)
            if candidate_ids:
                analysis_run_ids = candidate_ids
                analysis_reports = _reports_from_db(conn, run_ids=analysis_run_ids)
        analysis_status_counts = {"ok": 0, "ath_error": 0, "pipeline_error": 0, "skipped": 0}
        for item in analysis_reports:
            key = str(item.get("status", "pipeline_error"))
            if key not in analysis_status_counts:
                analysis_status_counts[key] = 0
            analysis_status_counts[key] = int(analysis_status_counts.get(key, 0)) + 1

        range_suggestions = _compute_range_suggestions(conn, analysis_run_ids)
        top_errors = _top_error_patterns(analysis_reports, limit=10)
        threshold_hits = _dimension_threshold_hits(analysis_reports)
        mode_error_rates = _mode_error_rates(analysis_reports)
        dimension_stats = _dimension_distribution_stats(analysis_reports)
        hard_cap_correlations = _hard_cap_correlated_keys(conn, run_ids=analysis_run_ids, top_n=10)
        error_class_modes = _error_class_mode_breakdown(analysis_reports)
        mode_error_matrix = _build_mode_error_matrix(analysis_reports)
        range_tightenings = _largest_safe_range_tightenings(
            prior_ranges=prior_ranges,
            current_ranges=range_suggestions,
            top_n=10,
        )

        range_suggestions_path = reports_root_path / "range_suggestions.v1.json"
        range_suggestions_v11_path = reports_root_path / "range_suggestions.v1.1.json"
        range_suggestions_payload = {
            "generated_at": _now_iso(),
            "cases_requested": int(cases),
            "seed": int(seed),
            "source_priors_path": str(resolved_priors_path),
            "analysis_run_groups": analysis_groups,
            "analysis_run_count": len(analysis_run_ids),
            "range_suggestions": range_suggestions,
        }
        range_suggestions_path.write_text(
            json.dumps(range_suggestions_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        range_suggestions_v11_path.write_text(
            json.dumps(range_suggestions_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        range_suggestions_v12_payload = _build_range_suggestions_v12(
            range_suggestions=range_suggestions,
            analysis_run_groups=analysis_groups,
        )
        range_suggestions_v12_path = reports_root_path / "range_suggestions.v1.2.json"
        range_suggestions_v12_path.write_text(
            json.dumps(range_suggestions_v12_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        summary_md_path = _write_summary_markdown(
            summary_path=reports_root_path / "summary.md",
            status_counts=analysis_status_counts,
            top_errors=top_errors,
            threshold_hits=threshold_hits,
            mode_error_rates=mode_error_rates,
            dimension_stats=dimension_stats,
            error_class_modes=error_class_modes,
            cases=cases,
            seed=seed,
        )
        mode_error_matrix_path = reports_root_path / "mode_error_matrix.json"
        mode_error_matrix_path.write_text(
            json.dumps(mode_error_matrix, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        data_inventory_path, data_inventory_payload = _write_data_inventory_markdown(
            conn=conn,
            reports_root=reports_root_path,
            backfill_result=legacy_backfill_result,
        )
        precision_plan_path, compat_rule_candidates_path, precision_analysis_payload = _build_precision_outputs(
            conn=conn,
            run_ids=analysis_run_ids,
            analysis_run_groups=analysis_groups,
            reports_root=reports_root_path,
            status_counts=analysis_status_counts,
            top_errors=top_errors,
            error_class_modes=error_class_modes,
            threshold_hits=threshold_hits,
            range_suggestions=range_suggestions,
        )

    end_cleanup_result: Optional[Dict[str, Any]] = None
    if cleanup_cases_mode == "end" or cleanup_log_mode == "end":
        end_cleanup_result = _cleanup_report_files(
            reports_root=reports_root_path,
            phase="end",
            cleanup_cases=(cleanup_cases_mode == "end"),
            cleanup_log=(cleanup_log_mode == "end"),
        )

    summary = {
        "generated_at": _now_iso(),
        "ath_executable": str(ath_executable),
        "template_cfg": template_cfg or settings.template_cfg,
        "cfg_dir": str(cfg_root),
        "export_root": str(export_root_path),
        "reports_root": str(reports_root_path),
        "cases_requested": int(cases),
        "seed": int(seed),
        "run_group_id": run_group_id,
        "analysis_run_groups": analysis_groups,
        "analysis_run_count": len(analysis_reports),
        "cleanup_files": bool(cleanup_files),
        "preclean_files": bool(preclean_files),
        "cleanup_cases_mode": cleanup_cases_mode,
        "cleanup_log_mode": cleanup_log_mode,
        "max_dim_mm": float(max_dim_mm),
        "hard_cap_mm": float(hard_cap_mm),
        "priors_path": str(resolved_priors_path),
        "database_path": str(db_path),
        "status_counts": analysis_status_counts,
        "run_status_counts": status_counts,
        "reports_preview": reports[:5],
        "total_runs_persisted": len(reports),
        "top_error_patterns": top_errors,
        "error_class_mode_breakdown": error_class_modes,
        "dimension_threshold_hits": threshold_hits,
        "mode_error_rates": mode_error_rates,
        "mode_error_matrix_path": str(mode_error_matrix_path),
        "dimension_distribution": dimension_stats,
        "hard_cap_key_correlations_top10": hard_cap_correlations,
        "largest_safe_range_tightenings": range_tightenings,
        "range_suggestions_path": str(range_suggestions_path),
        "range_suggestions_v11_path": str(range_suggestions_v11_path),
        "range_suggestions_v12_path": str(range_suggestions_v12_path) if range_suggestions_v12_path else None,
        "summary_markdown_path": str(summary_md_path),
        "data_inventory_path": str(data_inventory_path) if data_inventory_path else None,
        "precision_plan_path": str(precision_plan_path) if precision_plan_path else None,
        "compat_rule_candidates_path": str(compat_rule_candidates_path) if compat_rule_candidates_path else None,
        "legacy_backfill_result": legacy_backfill_result,
        "precision_analysis": precision_analysis_payload,
        "data_inventory": data_inventory_payload,
        "preclean_result": preclean_result,
        "end_cleanup_result": end_cleanup_result,
        "report_files_count": len(reports),
        "report_files_preview": [str(cases_root / f"run_{item['case_index']:04d}" / "report.json") for item in reports[:25]],
    }
    summary_path = reports_root_path / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if bool(write_history_snapshots):
        if analysis_groups:
            history_label = "agg_" + "_".join([_sanitize_history_label(group) for group in analysis_groups])
        else:
            history_label = _sanitize_history_label(run_group_id)
        history_paths = _write_history_snapshots(
            reports_root=reports_root_path,
            summary_payload=summary,
            range_payload=range_suggestions_v12_payload or range_suggestions_payload,
            run_group_label=history_label,
        )
        summary["history_snapshot_paths"] = history_paths
        summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
