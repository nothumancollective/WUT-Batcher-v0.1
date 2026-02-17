"""Context-stratified safe-range analysis for ATH experiment DB."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class _ContextRow:
    key: str
    profile_mode: str
    gcurve_mode: str
    morph_mode: str
    enclosure_mode: str
    value: float


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _percentile(sorted_values: Sequence[float], q: float) -> Optional[float]:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    qn = max(0.0, min(1.0, float(q)))
    rank = qn * float(len(sorted_values) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    if lo == hi:
        return float(sorted_values[lo])
    return float(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac)


def _group_token(profile: str, gcurve: str, morph: str, enclosure: str) -> str:
    return f"profile={profile}|gcurve={gcurve}|morph={morph}|enclosure={enclosure}"


def _iter_grouped_rows(
    conn: sqlite3.Connection,
    *,
    run_groups: Sequence[str],
) -> Iterator[_ContextRow]:
    run_group_filter = [str(item).strip() for item in list(run_groups or []) if str(item).strip() and str(item).strip().lower() != "all"]
    where_group = ""
    params: List[Any] = []
    if run_group_filter:
        placeholders = ",".join("?" for _ in run_group_filter)
        where_group = f" AND r.run_group_id IN ({placeholders})"
        params.extend(run_group_filter)

    query = f"""
        WITH run_ctx AS (
            SELECT
                ep.run_id AS run_id,
                MAX(CASE WHEN ep.key = 'Throat.Profile' AND ep.is_set = 1 THEN CAST(ep.value_num AS INTEGER) END) AS throat_profile,
                MAX(CASE WHEN ep.key = 'GCurve.Type' AND ep.is_set = 1 THEN CAST(ep.value_num AS INTEGER) END) AS gcurve_type,
                MAX(CASE WHEN ep.key = 'Morph.TargetShape' AND ep.is_set = 1 THEN CAST(ep.value_num AS INTEGER) END) AS morph_shape,
                MAX(CASE WHEN ep.key = 'Mesh.Enclosure' AND ep.is_set = 1 THEN 1 ELSE 0 END) AS enclosure_on,
                MAX(CASE WHEN ep.key = 'R-OSSE' AND ep.is_set = 1 THEN 1 ELSE 0 END) AS rosse_on
            FROM experiment_params ep
            GROUP BY ep.run_id
        ),
        filtered_runs AS (
            SELECT
                r.run_id AS run_id,
                COALESCE(rc.throat_profile, 1) AS throat_profile,
                rc.gcurve_type AS gcurve_type,
                rc.morph_shape AS morph_shape,
                COALESCE(rc.enclosure_on, 0) AS enclosure_on,
                COALESCE(rc.rosse_on, 0) AS rosse_on
            FROM experiment_runs r
            JOIN run_ctx rc ON rc.run_id = r.run_id
            LEFT JOIN experiment_compare ec ON ec.run_id = r.run_id
            WHERE r.status = 'ok'
              AND COALESCE(ec.config_ok, 1) = 1
              {where_group}
        )
        SELECT
            ep.key AS key,
            CASE
                WHEN fr.rosse_on = 1 OR fr.throat_profile = 2 THEN 'rosse'
                WHEN fr.throat_profile = 3 THEN 'circarc'
                ELSE 'osse'
            END AS profile_mode,
            CASE
                WHEN fr.gcurve_type = 1 THEN 'se'
                WHEN fr.gcurve_type = 2 THEN 'sf'
                ELSE 'none'
            END AS gcurve_mode,
            CASE
                WHEN fr.morph_shape = 1 THEN 'shape1'
                WHEN fr.morph_shape = 2 THEN 'shape2'
                ELSE 'off'
            END AS morph_mode,
            CASE WHEN fr.enclosure_on = 1 THEN 'on' ELSE 'off' END AS enclosure_mode,
            ep.value_num AS value_num
        FROM experiment_params ep
        JOIN filtered_runs fr ON fr.run_id = ep.run_id
        WHERE ep.is_set = 1
          AND ep.value_num IS NOT NULL
        ORDER BY
            ep.key,
            profile_mode,
            gcurve_mode,
            morph_mode,
            enclosure_mode,
            ep.value_num
    """
    for row in conn.execute(query, tuple(params)):
        key, profile, gcurve, morph, enclosure, value_num = row
        try:
            value = float(value_num)
        except Exception:
            continue
        yield _ContextRow(
            key=str(key),
            profile_mode=str(profile),
            gcurve_mode=str(gcurve),
            morph_mode=str(morph),
            enclosure_mode=str(enclosure),
            value=value,
        )


def _iter_key_rows(
    conn: sqlite3.Connection,
    *,
    run_groups: Sequence[str],
) -> Iterator[Tuple[str, float]]:
    run_group_filter = [str(item).strip() for item in list(run_groups or []) if str(item).strip() and str(item).strip().lower() != "all"]
    where_group = ""
    params: List[Any] = []
    if run_group_filter:
        placeholders = ",".join("?" for _ in run_group_filter)
        where_group = f" AND r.run_group_id IN ({placeholders})"
        params.extend(run_group_filter)
    query = f"""
        SELECT ep.key AS key, ep.value_num AS value_num
        FROM experiment_params ep
        JOIN experiment_runs r ON r.run_id = ep.run_id
        LEFT JOIN experiment_compare ec ON ec.run_id = ep.run_id
        WHERE ep.is_set = 1
          AND ep.value_num IS NOT NULL
          AND r.status = 'ok'
          AND COALESCE(ec.config_ok, 1) = 1
          {where_group}
        ORDER BY ep.key, ep.value_num
    """
    for row in conn.execute(query, tuple(params)):
        key, value_num = row
        try:
            value = float(value_num)
        except Exception:
            continue
        yield (str(key), value)


def _stats_payload(sorted_values: Sequence[float]) -> Dict[str, Any]:
    return {
        "count": int(len(sorted_values)),
        "safe_min": _percentile(sorted_values, 0.01),
        "safe_max": _percentile(sorted_values, 0.99),
        "rec_p05": _percentile(sorted_values, 0.05),
        "rec_p95": _percentile(sorted_values, 0.95),
    }


def _accumulate_contextual_stats(
    conn: sqlite3.Connection,
    *,
    run_groups: Sequence[str],
    min_count: int,
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    output: Dict[str, Dict[str, Dict[str, Any]]] = {}
    current_group: Optional[Tuple[str, str, str, str, str]] = None
    values: List[float] = []

    def flush() -> None:
        nonlocal current_group, values
        if current_group is None:
            return
        key, profile, gcurve, morph, enclosure = current_group
        if len(values) >= int(min_count):
            key_bucket = output.setdefault(key, {})
            token = _group_token(profile, gcurve, morph, enclosure)
            key_bucket[token] = {
                "profile_mode": profile,
                "gcurve_mode": gcurve,
                "morph_mode": morph,
                "enclosure_mode": enclosure,
                **_stats_payload(values),
            }
        current_group = None
        values = []

    for row in _iter_grouped_rows(conn, run_groups=run_groups):
        group = (row.key, row.profile_mode, row.gcurve_mode, row.morph_mode, row.enclosure_mode)
        if current_group is None:
            current_group = group
        elif group != current_group:
            flush()
            current_group = group
        values.append(float(row.value))
    flush()
    return output


def _accumulate_global_stats(
    conn: sqlite3.Connection,
    *,
    run_groups: Sequence[str],
    min_count: int,
) -> Dict[str, Dict[str, Any]]:
    output: Dict[str, Dict[str, Any]] = {}
    current_key: Optional[str] = None
    values: List[float] = []

    def flush() -> None:
        nonlocal current_key, values
        if current_key is None:
            return
        if len(values) >= int(min_count):
            output[current_key] = _stats_payload(values)
        current_key = None
        values = []

    for key, value in _iter_key_rows(conn, run_groups=run_groups):
        if current_key is None:
            current_key = key
        elif key != current_key:
            flush()
            current_key = key
        values.append(float(value))
    flush()
    return output


def _summary_markdown(
    payload: Mapping[str, Any],
    *,
    max_contexts_per_key: int,
) -> str:
    lines: List[str] = []
    lines.append("# Contextual Range Suggestions")
    lines.append("")
    lines.append(f"- generated_at: `{payload.get('generated_at')}`")
    lines.append(f"- source_db: `{payload.get('source_db')}`")
    lines.append(f"- run_groups: `{', '.join(payload.get('run_groups', []) or ['all'])}`")
    lines.append(f"- min_count: `{payload.get('min_count')}`")
    lines.append("")
    lines.append("## Keys")
    lines.append("")
    global_per_key = dict(payload.get("global_per_key", {}) or {})
    by_key_context = dict(payload.get("contextual_per_key", {}) or {})
    lines.append("| key | global_count | safe_min | safe_max | rec_p05 | rec_p95 | contextual_groups |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for key in sorted(global_per_key.keys()):
        global_row = dict(global_per_key.get(key, {}) or {})
        group_count = len(dict(by_key_context.get(key, {}) or {}))
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} | {} |".format(
                key,
                int(global_row.get("count", 0) or 0),
                global_row.get("safe_min"),
                global_row.get("safe_max"),
                global_row.get("rec_p05"),
                global_row.get("rec_p95"),
                int(group_count),
            )
        )
    lines.append("")
    lines.append("## Context Samples")
    lines.append("")
    for key in sorted(by_key_context.keys()):
        groups = dict(by_key_context.get(key, {}) or {})
        if not groups:
            continue
        lines.append(f"### {key}")
        lines.append("")
        lines.append("| context | count | safe_min | safe_max | rec_p05 | rec_p95 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        rows = sorted(groups.items(), key=lambda item: int(dict(item[1]).get("count", 0)), reverse=True)
        for token, raw in rows[: max(1, int(max_contexts_per_key))]:
            row = dict(raw or {})
            lines.append(
                "| `{}` | {} | {} | {} | {} | {} |".format(
                    token,
                    int(row.get("count", 0) or 0),
                    row.get("safe_min"),
                    row.get("safe_max"),
                    row.get("rec_p05"),
                    row.get("rec_p95"),
                )
            )
        lines.append("")
    return "\n".join(lines) + "\n"


def run_contextual_range_analysis(
    *,
    reports_root: str | Path = "reports/ath_experiments",
    run_group: str = "all",
    min_count: int = 80,
    output_json_name: str = "range_suggestions.contextual.v1.json",
    output_md_name: str = "range_suggestions.contextual.v1.md",
    max_contexts_per_key: int = 8,
) -> Dict[str, Any]:
    reports_root_path = Path(reports_root)
    db_path = reports_root_path / "ath_experiments.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"ATH experiments DB not found: {db_path}")
    run_groups = [item.strip() for item in str(run_group or "all").split(",") if item.strip()] or ["all"]

    with closing(sqlite3.connect(str(db_path))) as conn:
        global_per_key = _accumulate_global_stats(conn, run_groups=run_groups, min_count=min_count)
        contextual = _accumulate_contextual_stats(conn, run_groups=run_groups, min_count=min_count)

    payload: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "source_db": str(db_path),
        "run_groups": run_groups,
        "method": (
            "successful(config_ok) numeric values stratified by profile/gcurve/morph/enclosure context; "
            "safe bounds=p01/p99, recommended=p05/p95"
        ),
        "min_count": int(min_count),
        "global_per_key": global_per_key,
        "contextual_per_key": contextual,
    }

    reports_root_path.mkdir(parents=True, exist_ok=True)
    json_path = reports_root_path / str(output_json_name)
    md_path = reports_root_path / str(output_md_name)
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(_summary_markdown(payload, max_contexts_per_key=max_contexts_per_key), encoding="utf-8")

    return {
        "ok": True,
        "generated_at": payload["generated_at"],
        "db_path": str(db_path),
        "json_path": str(json_path),
        "md_path": str(md_path),
        "run_groups": run_groups,
        "global_key_count": len(global_per_key),
        "contextual_key_count": len(contextual),
    }
