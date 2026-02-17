"""Minimal completion search for ATH STL-feasible parameter sets.

This module treats the problem as a constrained black-box optimization:
- decision variables: which parameter keys are set for a scenario
- constraints: scenario selectors + minXY>0 per included UI card
- feasibility oracle: ATH run produces a non-empty STL file
- objective: lexicographic minimization of per-card key counts

The implementation supports two execution modes:
1) DB-observed mode (`verify_with_ath=False`): mine minimal candidates from
   successful runs in `ath_experiments.sqlite`.
2) ATH-verified mode (`verify_with_ath=True`): start from DB seeds and run
   greedy minimization with real ATH STL checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from app.ath_knowledge import load_ath_knowledge
from app.cfg_renderer import render_cfg_text
from app.compat_engine import validity_report
from app.constants import ATH_PREVIEW_CFG_DIR, ATH_PREVIEW_EXPORT_ROOT, DEFAULT_RUNNER_MODE
from app.runners import AthRunner
from app.services import _enforce_output_flag
from app.settings_store import UserSettings
from ui.form_schema import FormSchema, build_project_form_schema


_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?(?:[eE][+-]?\d+)?$")
_CARD_ORDER: Tuple[str, ...] = ("profile", "basics", "mesh", "morph", "gcurve", "enclosure")
_CFG_BASENAME = "minimal_completion_current"

# User-provided known-valid baseline. Used as synthetic fallback seed only.
_REFERENCE_BASELINE: Dict[str, Any] = {
    "Throat.Profile": 1,
    "Throat.Diameter": 25.4,
    "Throat.Angle": 7.0,
    "Coverage.Angle": 45.0,
    "Length": 100.0,
    "Term.s": 0.5,
    "Term.n": 4.0,
    "Term.q": 0.996,
    "Morph.TargetShape": 0,
    "Mesh.AngularSegments": 64,
    "Mesh.LengthSegments": 20,
    "Mesh.ThroatResolution": 4.0,
    "Mesh.InterfaceResolution": 8.0,
    "Mesh.InterfaceOffset": 5.0,
}

_DEFAULTS: Dict[str, Any] = {
    "Throat.Diameter": 25.4,
    "Throat.Angle": 7.0,
    "Coverage.Angle": 45.0,
    "Length": 120.0,
    "Term.s": 0.6,
    "Term.n": 4.0,
    "Term.q": 0.996,
    "OS.k": 1.0,
    "CircArc.TermAngle": 35.0,
    "CircArc.Radius": 160.0,
    "GCurve.Dist": 80.0,
    "GCurve.Width": 0.7,
    "GCurve.AspectRatio": 1.0,
    "GCurve.Rot": 0.0,
    "GCurve.SE.n": 3.0,
    "GCurve.SF.a": 1.0,
    "GCurve.SF.b": 1.0,
    "GCurve.SF.m1": 4.0,
    "GCurve.SF.m2": 4.0,
    "GCurve.SF.n1": 1.0,
    "GCurve.SF.n2": 1.0,
    "GCurve.SF.n3": 1.0,
    "Morph.TargetShape": 0,
    "Morph.TargetWidth": 260.0,
    "Morph.TargetHeight": 200.0,
    "Morph.CornerRadius": 35.0,
    "Morph.FixedPart": 0.0,
    "Morph.Rate": 3.0,
    "Morph.AllowShrinkage": 0,
    "Mesh.AngularSegments": 64,
    "Mesh.LengthSegments": 20,
    "Mesh.ThroatResolution": 4.0,
    "Mesh.MouthResolution": 10.0,
    "Mesh.InterfaceResolution": 8.0,
    "Mesh.InterfaceOffset": 5.0,
    "Mesh.Enclosure": {"Depth": 120.0, "EdgeRadius": 10.0, "EdgeType": 1, "Plan": "rect"},
    "R-OSSE": {"R": 120.0, "r0": 12.7, "a0": 7.0, "a": 45.0, "k": 0.5, "r": 0.5, "m": 4.0, "b": 1.0, "q": 0.996},
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if abs(value - round(value)) <= 1e-9:
            return int(round(value))
        return float(value)
    text = str(value).strip()
    if not text:
        return ""
    if _NUMERIC_RE.match(text):
        try:
            num = float(text.replace(",", "."))
            if abs(num - round(num)) <= 1e-9:
                return int(round(num))
            return float(num)
        except Exception:
            return text
    lowered = text.lower()
    if lowered in {"true", "on", "yes"}:
        return 1
    if lowered in {"false", "off", "no"}:
        return 0
    return text


def _value_eq(left: Any, right: Any) -> bool:
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return json.dumps(dict(left), sort_keys=True, ensure_ascii=False) == json.dumps(
            dict(right), sort_keys=True, ensure_ascii=False
        )
    return _normalize_scalar(left) == _normalize_scalar(right)


def _parse_db_value(value_text: Any, value_num: Any) -> Any:
    if value_text is not None:
        text = str(value_text).strip()
        if not text:
            return None
        if text.startswith("{") or text.startswith("["):
            try:
                return json.loads(text)
            except Exception:
                pass
        return _normalize_scalar(text)
    if value_num is None:
        return None
    try:
        num = float(value_num)
        if abs(num - round(num)) <= 1e-9:
            return int(round(num))
        return num
    except Exception:
        return value_num


def _catalog_map() -> Dict[str, Dict[str, Any]]:
    bundle = load_ath_knowledge()
    result: Dict[str, Dict[str, Any]] = {}
    for item in list(bundle.catalog.get("parameters", []) or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if key:
            result[key] = item
    return result


def _fallback_value_for_key(key: str, catalog_by_key: Mapping[str, Mapping[str, Any]]) -> Any:
    if key in _DEFAULTS:
        value = _DEFAULTS[key]
        if isinstance(value, Mapping):
            return dict(value)
        return value
    item = dict(catalog_by_key.get(key, {}) or {})
    if not item:
        return None
    if "default" in item:
        return item.get("default")
    ath_type = str(item.get("type", "")).strip().lower()
    domain = item.get("domain")
    domain_map = domain if isinstance(domain, Mapping) else {}
    if ath_type == "enum":
        enum_values = list(domain_map.get("enum", []) or [])
        return enum_values[0] if enum_values else None
    if ath_type == "bool":
        return 0
    if ath_type == "int":
        min_value = domain_map.get("min")
        if min_value is None:
            return 1
        return int(float(min_value))
    if ath_type in {"float", "expr"}:
        min_value = domain_map.get("min")
        if min_value is None:
            return 0.0
        return float(min_value)
    return None


@dataclass(frozen=True)
class ScenarioSpec:
    scenario_id: str
    description: str
    included_cards: Tuple[str, ...]
    selectors: Dict[str, Any]
    require_defined: Tuple[str, ...] = ()
    require_undefined: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    status: str
    description: str
    included_cards: Tuple[str, ...]
    selectors: Dict[str, Any]
    objective: Tuple[Any, ...]
    card_counts: Dict[str, int]
    extra_key_count: int
    key_count: int
    source: str
    run_id: Optional[str]
    params: Dict[str, Any]
    ath: Dict[str, Any]
    compat: Dict[str, Any]
    notes: List[str]


@dataclass
class _SeedCandidate:
    run_id: Optional[str]
    params: Dict[str, Any]
    source: str


class _AthOracle:
    def __init__(
        self,
        *,
        enabled: bool,
        settings: UserSettings,
        output_root: Path,
        cfg_dir: Path = Path(ATH_PREVIEW_CFG_DIR),
        export_root: Path = Path(ATH_PREVIEW_EXPORT_ROOT),
    ) -> None:
        self.enabled = bool(enabled)
        self.output_root = output_root
        self.cfg_dir = Path(cfg_dir)
        self.export_root = Path(export_root)
        self.logs_root = self.output_root / "logs"
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self._memory_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_db_path = self.output_root / "oracle_cache.sqlite"
        self._conn = sqlite3.connect(str(self._cache_db_path))
        self._ensure_cache_schema()
        self._ath_exe = Path(str(settings.ath_exe or "").strip()) if str(settings.ath_exe or "").strip() else None
        self._template_text = "; autogenerated minimal completion template\n"
        if str(settings.template_cfg or "").strip():
            path = Path(str(settings.template_cfg)).expanduser()
            if path.exists():
                self._template_text = path.read_text(encoding="utf-8")
        self._runtime_cfg_backup = self.cfg_dir / "ath.min_completion.backup.cfg"
        self._runtime_cfg_path = self.cfg_dir / "ath.cfg"
        self._runtime_cfg_had_existing = False

    def close(self) -> None:
        self._restore_runtime_cfg()
        self._conn.close()

    def _ensure_cache_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS oracle_cache(
                config_hash TEXT PRIMARY KEY,
                feasible INTEGER NOT NULL,
                ath_exit_code INTEGER,
                stl_path TEXT,
                detail_json TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def _canonical_hash(self, params: Mapping[str, Any]) -> str:
        payload = json.dumps(dict(params), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()

    def _restore_runtime_cfg(self) -> None:
        if self._runtime_cfg_had_existing and self._runtime_cfg_backup.exists():
            try:
                shutil.copy2(self._runtime_cfg_backup, self._runtime_cfg_path)
            except Exception:
                pass
        elif (not self._runtime_cfg_had_existing) and self._runtime_cfg_path.exists():
            try:
                self._runtime_cfg_path.unlink()
            except Exception:
                pass
        if self._runtime_cfg_backup.exists():
            try:
                self._runtime_cfg_backup.unlink()
            except Exception:
                pass
        self._runtime_cfg_had_existing = False

    def _prepare_runtime_cfg(self) -> None:
        self.cfg_dir.mkdir(parents=True, exist_ok=True)
        self.export_root.mkdir(parents=True, exist_ok=True)
        had_existing = self._runtime_cfg_path.exists()
        self._runtime_cfg_had_existing = had_existing
        if had_existing:
            try:
                shutil.copy2(self._runtime_cfg_path, self._runtime_cfg_backup)
            except Exception:
                self._runtime_cfg_had_existing = False
        mesh_cmd = ""
        if self._ath_exe is not None and self._ath_exe.exists():
            gmsh_candidate = self._ath_exe.parent / "gmsh.exe"
            if gmsh_candidate.exists():
                mesh_cmd = str(gmsh_candidate)
        export_value = str(self.export_root).replace("\\", "/")
        self._runtime_cfg_path.write_text(
            f'OutputRootDir = "{export_value}"\nMeshCmd = "{mesh_cmd}"\nGnuplotPath = ""\n',
            encoding="utf-8",
        )

    def _load_cached(self, config_hash: str) -> Optional[Dict[str, Any]]:
        if config_hash in self._memory_cache:
            return dict(self._memory_cache[config_hash])
        row = self._conn.execute(
            "SELECT feasible, ath_exit_code, stl_path, detail_json FROM oracle_cache WHERE config_hash = ?",
            (config_hash,),
        ).fetchone()
        if row is None:
            return None
        payload = {
            "feasible": bool(int(row[0])),
            "ath_exit_code": None if row[1] is None else int(row[1]),
            "stl_path": str(row[2] or "") if row[2] is not None else None,
            "cached": True,
            "detail": json.loads(str(row[3])) if row[3] else {},
        }
        self._memory_cache[config_hash] = dict(payload)
        return payload

    def _store_cached(self, config_hash: str, payload: Mapping[str, Any]) -> None:
        entry = dict(payload)
        self._memory_cache[config_hash] = dict(entry)
        detail_json = json.dumps(dict(entry.get("detail", {}) or {}), ensure_ascii=False, sort_keys=True)
        self._conn.execute(
            """
            INSERT OR REPLACE INTO oracle_cache(config_hash, feasible, ath_exit_code, stl_path, detail_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(config_hash),
                1 if bool(entry.get("feasible")) else 0,
                entry.get("ath_exit_code"),
                entry.get("stl_path"),
                detail_json,
                _now_iso(),
            ),
        )
        self._conn.commit()

    def _normalize_for_ath(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        normalized: Dict[str, Any] = {}
        for key, value in dict(params).items():
            key_s = str(key).strip()
            if not key_s or value is None:
                continue
            normalized[key_s] = value
        if str(normalized.get("Throat.Profile", "")).strip() in {"2", "2.0"}:
            normalized.pop("Throat.Profile", None)
            if "R-OSSE" not in normalized:
                normalized["R-OSSE"] = dict(_DEFAULTS["R-OSSE"])
        rosse = normalized.get("R-OSSE")
        if isinstance(rosse, Mapping):
            merged = dict(_DEFAULTS["R-OSSE"])
            merged.update(dict(rosse))
            normalized["R-OSSE"] = merged
        return normalized

    def evaluate(self, params: Mapping[str, Any], *, scenario_id: str) -> Dict[str, Any]:
        config_hash = self._canonical_hash(params)
        cached = self._load_cached(config_hash)
        if cached is not None:
            return dict(cached)
        if not self.enabled:
            payload = {"feasible": False, "ath_exit_code": None, "stl_path": None, "cached": False, "detail": {}}
            self._store_cached(config_hash, payload)
            return payload
        if self._ath_exe is None or not self._ath_exe.exists():
            payload = {
                "feasible": False,
                "ath_exit_code": None,
                "stl_path": None,
                "cached": False,
                "detail": {"error": "ath_executable_missing"},
            }
            self._store_cached(config_hash, payload)
            return payload

        self._prepare_runtime_cfg()
        rendered_params = self._normalize_for_ath(params)
        cfg_text = render_cfg_text(
            template_text=self._template_text,
            parameters=rendered_params,
            version_id="V_MINCOMP",
            runner_mode=DEFAULT_RUNNER_MODE,
            omit_keys=(),
        )
        cfg_text = _enforce_output_flag(cfg_text, key="Output.STL", value=1)
        cfg_text = _enforce_output_flag(cfg_text, key="Output.ABECProject", value=0)

        cfg_path = self.cfg_dir / f"{_CFG_BASENAME}.cfg"
        export_dir = self.export_root / _CFG_BASENAME
        if export_dir.exists():
            shutil.rmtree(export_dir, ignore_errors=True)
        cfg_path.write_text(cfg_text, encoding="utf-8")
        logs_dir = self.logs_root / scenario_id
        logs_dir.mkdir(parents=True, exist_ok=True)
        runner = AthRunner(self._ath_exe)
        result = runner.run_cfg(cfg_path, version_logs_dir=logs_dir, workdir=self.cfg_dir)
        stl_path = None
        if export_dir.exists():
            candidates = [path for path in export_dir.rglob("*.stl") if path.is_file() and path.stat().st_size > 0]
            candidates.sort(key=lambda path: int(path.stat().st_mtime_ns), reverse=True)
            if candidates:
                stl_path = str(candidates[0])
        feasible = bool(result.ok and stl_path)
        error_token = ""
        if not result.ok:
            error_token = f"ath_exit_{int(result.exit_code)}"
        elif not stl_path:
            error_token = "stl_not_found"
        payload = {
            "feasible": feasible,
            "ath_exit_code": int(result.exit_code),
            "stl_path": stl_path,
            "cached": False,
            "detail": {
                "error": error_token,
                "stdout_log": str(result.stdout_log),
                "stderr_log": str(result.stderr_log),
                "summary_log": str(result.summary_log),
            },
        }
        self._store_cached(config_hash, payload)
        return payload


def _enum_options_by_key(schema: FormSchema, key: str) -> List[Any]:
    for field in schema.fields:
        if field.key == key:
            values = [option.value for option in field.enum_options]
            return [value for value in values if value is not None]
    return []


def _card_registry(schema: FormSchema) -> Tuple[Dict[str, set[str]], Dict[str, str]]:
    card_keys: Dict[str, set[str]] = {name: set() for name in _CARD_ORDER}
    key_to_card: Dict[str, str] = {}
    for field in schema.fields:
        key = str(field.key)
        card = ""
        if key == "Throat.Profile":
            card = "profile"
        elif key == "GCurve.Type":
            card = "gcurve"
        elif key == "Morph.TargetShape":
            card = "morph"
        elif tuple(field.group_path) == ("Geometry", "Basics"):
            card = "basics"
        elif tuple(field.group_path) == ("Geometry", "Throat Profile"):
            card = "profile"
        elif tuple(field.group_path) == ("Geometry", "Morph"):
            card = "morph"
        elif tuple(field.group_path) == ("Geometry", "GCurve"):
            card = "gcurve"
        elif tuple(field.group_path) == ("Mesh", "Core"):
            card = "mesh"
        elif tuple(field.group_path) == ("Mesh", "Enclosure"):
            card = "enclosure"
        if not card:
            continue
        card_keys[card].add(key)
        key_to_card[key] = card
    return card_keys, key_to_card


def _build_scenarios(schema: FormSchema, *, include_all_combinations: bool) -> List[ScenarioSpec]:
    profile_modes = [int(v) for v in _enum_options_by_key(schema, "Throat.Profile") if int(v) in {1, 2, 3}]
    morph_modes = [int(v) for v in _enum_options_by_key(schema, "Morph.TargetShape") if int(v) in {0, 1, 2}]
    if not morph_modes:
        morph_modes = [0, 1, 2]
    gcurve_modes = [1, 2]
    scenarios: List[ScenarioSpec] = []

    def add(
        sid: str,
        *,
        cards: Sequence[str],
        selectors: Mapping[str, Any],
        require_defined: Sequence[str] = (),
        require_undefined: Sequence[str] = (),
        description: str,
    ) -> None:
        scenarios.append(
            ScenarioSpec(
                scenario_id=sid,
                description=description,
                included_cards=tuple(cards),
                selectors={str(k): v for k, v in dict(selectors).items()},
                require_defined=tuple(str(item) for item in require_defined),
                require_undefined=tuple(str(item) for item in require_undefined),
            )
        )

    for profile in profile_modes:
        add(
            f"s1_profile{profile}_basic",
            cards=("profile", "basics"),
            selectors={"Throat.Profile": profile},
            require_undefined=("GCurve.Type", "Morph.TargetShape", "Mesh.Enclosure"),
            description="Step1: minProfile + minBasic",
        )
        add(
            f"s2_profile{profile}_basic_mesh",
            cards=("profile", "basics", "mesh"),
            selectors={"Throat.Profile": profile},
            require_undefined=("GCurve.Type", "Morph.TargetShape", "Mesh.Enclosure"),
            description="Step2: minProfile + minBasic + minMesh",
        )
        add(
            f"s5_profile{profile}_basic_mesh_enclosure",
            cards=("profile", "basics", "mesh", "enclosure"),
            selectors={"Throat.Profile": profile},
            require_defined=("Mesh.Enclosure",),
            require_undefined=("GCurve.Type", "Morph.TargetShape"),
            description="Step5: minProfile + minBasic + minMesh + minEnclosure",
        )
        for morph_mode in morph_modes:
            add(
                f"s3_profile{profile}_basic_mesh_morph{morph_mode}",
                cards=("profile", "basics", "mesh", "morph"),
                selectors={"Throat.Profile": profile, "Morph.TargetShape": morph_mode},
                require_undefined=("GCurve.Type", "Mesh.Enclosure"),
                description="Step3: minProfile + minBasic + minMesh + minMorph",
            )
        for gcurve_mode in gcurve_modes:
            add(
                f"s4_profile{profile}_basic_mesh_gcurve{gcurve_mode}",
                cards=("profile", "basics", "mesh", "gcurve"),
                selectors={"Throat.Profile": profile, "GCurve.Type": gcurve_mode},
                require_undefined=("Morph.TargetShape", "Mesh.Enclosure"),
                description="Step4: minProfile + minBasic + minMesh + minGCurve",
            )
        for morph_mode in morph_modes:
            for gcurve_mode in gcurve_modes:
                add(
                    f"s6_profile{profile}_basic_mesh_morph{morph_mode}_gcurve{gcurve_mode}",
                    cards=("profile", "basics", "mesh", "morph", "gcurve"),
                    selectors={
                        "Throat.Profile": profile,
                        "Morph.TargetShape": morph_mode,
                        "GCurve.Type": gcurve_mode,
                    },
                    require_undefined=("Mesh.Enclosure",),
                    description="Step6: minProfile + minBasic + minMesh + minMorph + minGCurve",
                )

    if include_all_combinations:
        optional_cards = ("mesh", "morph", "gcurve", "enclosure")
        from itertools import product

        for profile in profile_modes:
            for include_mesh, include_morph, include_gcurve, include_enclosure in product((0, 1), repeat=4):
                if include_enclosure and not include_mesh:
                    continue
                cards = ["profile", "basics"]
                selectors: Dict[str, Any] = {"Throat.Profile": profile}
                undefined: List[str] = []
                defined: List[str] = []
                if include_mesh:
                    cards.append("mesh")
                if include_morph:
                    cards.append("morph")
                else:
                    undefined.append("Morph.TargetShape")
                if include_gcurve:
                    cards.append("gcurve")
                else:
                    undefined.append("GCurve.Type")
                if include_enclosure:
                    cards.append("enclosure")
                    defined.append("Mesh.Enclosure")
                else:
                    undefined.append("Mesh.Enclosure")
                morph_modes_use = morph_modes if include_morph else [None]
                gcurve_modes_use = gcurve_modes if include_gcurve else [None]
                for morph_mode in morph_modes_use:
                    for gcurve_mode in gcurve_modes_use:
                        local_selectors = dict(selectors)
                        if morph_mode is not None:
                            local_selectors["Morph.TargetShape"] = int(morph_mode)
                        if gcurve_mode is not None:
                            local_selectors["GCurve.Type"] = int(gcurve_mode)
                        sid = (
                            f"s7_profile{profile}_"
                            f"mesh{include_mesh}_morph{morph_mode if morph_mode is not None else 'off'}_"
                            f"gcurve{gcurve_mode if gcurve_mode is not None else 'off'}_"
                            f"enc{include_enclosure}"
                        )
                        add(
                            sid,
                            cards=cards,
                            selectors=local_selectors,
                            require_defined=defined,
                            require_undefined=undefined,
                            description="Step7: full minXY combination matrix",
                        )

    dedup: Dict[str, ScenarioSpec] = {}
    for item in scenarios:
        dedup[item.scenario_id] = item
    return [dedup[key] for key in sorted(dedup.keys())]


def _load_seed_pool(
    *,
    db_path: Path,
    keys_allowlist: Sequence[str],
    max_runs: int,
    run_groups: Sequence[str],
) -> Dict[str, Dict[str, Any]]:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        params: List[Any] = []
        where = ["status='ok'"]
        groups = [str(item).strip() for item in run_groups if str(item).strip() and str(item).strip().lower() != "all"]
        if groups:
            where.append(f"run_group_id IN ({', '.join('?' for _ in groups)})")
            params.extend(groups)
        rows = conn.execute(
            f"""
            SELECT run_id
            FROM experiment_runs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC, run_id DESC
            LIMIT ?
            """,
            tuple([*params, int(max_runs)]),
        ).fetchall()
        run_ids = [str(row["run_id"]) for row in rows]
        if not run_ids:
            return {}
        by_run: Dict[str, Dict[str, Any]] = {run_id: {} for run_id in run_ids}
        allow = [str(key) for key in keys_allowlist if str(key).strip()]
        chunk_size = 500
        for start in range(0, len(run_ids), chunk_size):
            chunk = run_ids[start : start + chunk_size]
            sql_params: List[Any] = [*chunk]
            key_filter = ""
            if allow:
                key_filter = f" AND key IN ({', '.join('?' for _ in allow)})"
                sql_params.extend(allow)
            rows_params = conn.execute(
                f"""
                SELECT run_id, key, value_text, value_num
                FROM experiment_params
                WHERE is_set = 1
                  AND run_id IN ({', '.join('?' for _ in chunk)})
                  {key_filter}
                """,
                tuple(sql_params),
            ).fetchall()
            for row in rows_params:
                run_id = str(row["run_id"])
                key = str(row["key"])
                value = _parse_db_value(row["value_text"], row["value_num"])
                if value is None:
                    continue
                by_run.setdefault(run_id, {})[key] = value
        return by_run
    finally:
        conn.close()


def _matches_selector(params: Mapping[str, Any], key: str, expected: Any) -> bool:
    if expected is None:
        return key not in params
    if key not in params:
        return False
    return _value_eq(params.get(key), expected)


def _card_counts(params: Mapping[str, Any], *, key_to_card: Mapping[str, str], included_cards: Sequence[str]) -> Dict[str, int]:
    included = set(str(card) for card in included_cards)
    counts = {card: 0 for card in _CARD_ORDER if card in included}
    for key in params.keys():
        card = key_to_card.get(str(key))
        if card in counts:
            counts[card] = int(counts[card]) + 1
    return counts


def _objective_tuple(params: Mapping[str, Any], *, key_to_card: Mapping[str, str], included_cards: Sequence[str]) -> Tuple[Any, ...]:
    counts = _card_counts(params, key_to_card=key_to_card, included_cards=included_cards)
    included = set(str(card) for card in included_cards)
    extras = 0
    for key in params.keys():
        card = key_to_card.get(str(key))
        if card is None or card not in included:
            extras += 1
    ordered_counts = [int(counts.get(card, 0)) for card in _CARD_ORDER if card in included]
    return (int(extras), *ordered_counts, int(len(params)))


def _scenario_compliant(params: Mapping[str, Any], scenario: ScenarioSpec, *, key_to_card: Mapping[str, str]) -> bool:
    for key, expected in dict(scenario.selectors).items():
        if not _matches_selector(params, str(key), expected):
            return False
    for key in scenario.require_defined:
        if str(key) not in params:
            return False
    for key in scenario.require_undefined:
        if str(key) in params:
            return False
    counts = _card_counts(params, key_to_card=key_to_card, included_cards=scenario.included_cards)
    for card in scenario.included_cards:
        if int(counts.get(card, 0)) <= 0:
            return False
    return True


def _compat_summary(params: Mapping[str, Any]) -> Dict[str, Any]:
    report = validity_report({"fixed_params": dict(params), "limits": {}}, runner_mode=DEFAULT_RUNNER_MODE)
    fatal = list(report.get("fatal", []) or [])
    warn = list(report.get("warn", []) or [])
    top = [str(item.get("message", "")) for item in (fatal[:2] + warn[:2]) if isinstance(item, Mapping)]
    return {"fatal_count": len(fatal), "warn_count": len(warn), "top_messages": top}


def _profile_mode(scenario: ScenarioSpec) -> Optional[int]:
    raw = scenario.selectors.get("Throat.Profile")
    try:
        return int(float(raw))
    except Exception:
        return None


def _gcurve_mode(scenario: ScenarioSpec) -> Optional[int]:
    raw = scenario.selectors.get("GCurve.Type")
    if raw is None:
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


def _morph_mode(scenario: ScenarioSpec) -> Optional[int]:
    raw = scenario.selectors.get("Morph.TargetShape")
    if raw is None:
        return None
    try:
        return int(float(raw))
    except Exception:
        return None


def _preferred_card_seed_keys(scenario: ScenarioSpec, card: str) -> List[str]:
    if card == "profile":
        mode = _profile_mode(scenario)
        if mode == 1:
            return ["Throat.Profile", "Term.s", "Term.n", "Term.q", "OS.k"]
        if mode == 2:
            return ["Throat.Profile", "R-OSSE"]
        if mode == 3:
            return ["Throat.Profile", "CircArc.TermAngle", "CircArc.Radius"]
        return ["Throat.Profile", "Term.s"]
    if card == "basics":
        return ["Throat.Diameter", "Throat.Angle", "Coverage.Angle", "Length"]
    if card == "mesh":
        return ["Mesh.AngularSegments", "Mesh.LengthSegments", "Mesh.ThroatResolution", "Mesh.InterfaceResolution"]
    if card == "morph":
        mode = _morph_mode(scenario)
        if mode in {1, 2}:
            return ["Morph.TargetShape", "Morph.TargetWidth", "Morph.TargetHeight"]
        return ["Morph.TargetShape"]
    if card == "gcurve":
        mode = _gcurve_mode(scenario)
        if mode == 1:
            return ["GCurve.Type", "GCurve.Dist", "GCurve.Width", "GCurve.SE.n"]
        if mode == 2:
            return ["GCurve.Type", "GCurve.Dist", "GCurve.Width", "GCurve.SF.a", "GCurve.SF.b"]
        return ["GCurve.Type"]
    if card == "enclosure":
        return ["Mesh.Enclosure", "Mesh.InterfaceOffset"]
    return []


def _inject_minimum_card_keys(
    params: Dict[str, Any],
    *,
    scenario: ScenarioSpec,
    card_keys: Mapping[str, set[str]],
    key_to_card: Mapping[str, str],
    catalog_by_key: Mapping[str, Mapping[str, Any]],
) -> Dict[str, Any]:
    included = set(str(card) for card in scenario.included_cards)
    result: Dict[str, Any] = {}
    for key, value in dict(params).items():
        key_s = str(key)
        card = key_to_card.get(key_s)
        if card and card not in included:
            continue
        result[key_s] = value
    for key, value in scenario.selectors.items():
        if value is None:
            result.pop(str(key), None)
            continue
        result[str(key)] = value
    for key in scenario.require_undefined:
        result.pop(str(key), None)
    for key in scenario.require_defined:
        if str(key) not in result:
            result[str(key)] = _fallback_value_for_key(str(key), catalog_by_key)

    counts = _card_counts(result, key_to_card=key_to_card, included_cards=scenario.included_cards)
    for card in scenario.included_cards:
        if int(counts.get(card, 0)) > 0:
            continue
        preferred = _preferred_card_seed_keys(scenario, card)
        chosen_key = ""
        for key in preferred:
            if key in card_keys.get(card, set()) or key in scenario.selectors:
                chosen_key = key
                break
        if not chosen_key:
            candidates = sorted(card_keys.get(card, set()))
            if candidates:
                chosen_key = candidates[0]
        if not chosen_key:
            continue
        if chosen_key in scenario.selectors and scenario.selectors[chosen_key] is not None:
            result[chosen_key] = scenario.selectors[chosen_key]
        else:
            result[chosen_key] = _fallback_value_for_key(chosen_key, catalog_by_key)
    return result


def _seed_candidates_for_scenario(
    *,
    scenario: ScenarioSpec,
    seed_pool: Mapping[str, Mapping[str, Any]],
    card_keys: Mapping[str, set[str]],
    key_to_card: Mapping[str, str],
    catalog_by_key: Mapping[str, Mapping[str, Any]],
    max_candidates: int,
) -> List[_SeedCandidate]:
    candidates: List[_SeedCandidate] = []
    for run_id, raw in seed_pool.items():
        params = {str(key): value for key, value in dict(raw).items() if value is not None}
        if not _scenario_compliant(params, scenario, key_to_card=key_to_card):
            continue
        candidates.append(_SeedCandidate(run_id=str(run_id), params=params, source="ath_experiments"))

    candidates.sort(key=lambda item: _objective_tuple(item.params, key_to_card=key_to_card, included_cards=scenario.included_cards))
    if len(candidates) > max_candidates:
        candidates = candidates[:max_candidates]

    synthetic = dict(_REFERENCE_BASELINE)
    synthetic = _inject_minimum_card_keys(
        synthetic,
        scenario=scenario,
        card_keys=card_keys,
        key_to_card=key_to_card,
        catalog_by_key=catalog_by_key,
    )
    candidates.append(_SeedCandidate(run_id=None, params=synthetic, source="synthetic_baseline"))
    return candidates


def _removal_priority_key(key: str, *, key_to_card: Mapping[str, str], scenario: ScenarioSpec) -> Tuple[int, str]:
    card = key_to_card.get(str(key), "")
    included = list(scenario.included_cards)
    if card not in included:
        return (0, str(key))
    return (1 + included.index(card), str(key))


def _greedy_minimize(
    *,
    seed: _SeedCandidate,
    scenario: ScenarioSpec,
    key_to_card: Mapping[str, str],
    card_keys: Mapping[str, set[str]],
    catalog_by_key: Mapping[str, Mapping[str, Any]],
    oracle: _AthOracle,
    max_eval: int,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any], int]:
    working = _inject_minimum_card_keys(
        {str(k): v for k, v in dict(seed.params).items() if v is not None},
        scenario=scenario,
        card_keys=card_keys,
        key_to_card=key_to_card,
        catalog_by_key=catalog_by_key,
    )
    if not _scenario_compliant(working, scenario, key_to_card=key_to_card):
        return (None, {"feasible": False, "detail": {"error": "seed_not_compliant"}}, 0)

    eval_count = 0
    current_eval = oracle.evaluate(working, scenario_id=scenario.scenario_id)
    eval_count += 1
    if not bool(current_eval.get("feasible")):
        return (None, current_eval, eval_count)

    while eval_count < max_eval:
        improved = False
        keys = sorted(working.keys(), key=lambda key: _removal_priority_key(key, key_to_card=key_to_card, scenario=scenario))
        for key in keys:
            if key in scenario.selectors:
                continue
            if key in scenario.require_defined:
                continue
            card = key_to_card.get(str(key))
            if card in scenario.included_cards:
                counts = _card_counts(working, key_to_card=key_to_card, included_cards=scenario.included_cards)
                if int(counts.get(card, 0)) <= 1:
                    continue
            candidate = dict(working)
            candidate.pop(str(key), None)
            if not _scenario_compliant(candidate, scenario, key_to_card=key_to_card):
                continue
            candidate_eval = oracle.evaluate(candidate, scenario_id=scenario.scenario_id)
            eval_count += 1
            if not bool(candidate_eval.get("feasible")):
                if eval_count >= max_eval:
                    break
                continue
            if _objective_tuple(candidate, key_to_card=key_to_card, included_cards=scenario.included_cards) < _objective_tuple(
                working, key_to_card=key_to_card, included_cards=scenario.included_cards
            ):
                working = candidate
                current_eval = candidate_eval
                improved = True
                break
            if eval_count >= max_eval:
                break
        if not improved:
            break
    return (working, current_eval, eval_count)


def _write_reports(*, output_root: Path, summary: Mapping[str, Any]) -> Dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = output_root / f"minimal_completion_summary_{stamp}.json"
    md_path = output_root / f"minimal_completion_summary_{stamp}.md"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    lines: List[str] = []
    lines.append("# Minimal Completion Search")
    lines.append("")
    lines.append(f"- generated_at: `{summary.get('generated_at')}`")
    lines.append(f"- optimization_problem: `{summary.get('optimization_problem')}`")
    lines.append(f"- verify_with_ath: `{summary.get('verify_with_ath')}`")
    lines.append(f"- scenarios: `{summary.get('scenario_count')}`")
    lines.append("")
    lines.append("| scenario | status | source | objective | cards | key_count | notes |")
    lines.append("|---|---|---|---|---|---:|---|")
    for row in list(summary.get("results", []) or []):
        if not isinstance(row, Mapping):
            continue
        notes = ", ".join(str(item) for item in list(row.get("notes", []) or []))
        objective = json.dumps(row.get("objective", []), ensure_ascii=False)
        cards = ",".join(str(item) for item in list(row.get("included_cards", []) or []))
        lines.append(
            f"| `{row.get('scenario_id')}` | `{row.get('status')}` | `{row.get('source')}` | `{objective}` | "
            f"`{cards}` | {int(row.get('key_count', 0) or 0)} | {notes} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def run_minimal_completion_search(
    *,
    settings: UserSettings,
    reports_root: str | Path = "reports/ath_experiments",
    output_root: str | Path = "reports/minimal_completion",
    run_group: str = "all",
    include_all_combinations: bool = False,
    verify_with_ath: bool = False,
    seed_run_limit: int = 20000,
    max_seed_candidates: int = 12,
    max_eval_per_scenario: int = 250,
    scenario_filter: str = "",
) -> Dict[str, Any]:
    schema = build_project_form_schema()
    card_keys, key_to_card = _card_registry(schema)
    catalog_by_key = _catalog_map()
    scenarios = _build_scenarios(schema, include_all_combinations=bool(include_all_combinations))
    filter_token = str(scenario_filter or "").strip()
    if filter_token:
        scenarios = [item for item in scenarios if filter_token in item.scenario_id]

    db_path = Path(reports_root) / "ath_experiments.sqlite"
    run_groups = [item.strip() for item in str(run_group or "all").split(",") if item.strip()]
    seed_pool = _load_seed_pool(
        db_path=db_path,
        keys_allowlist=sorted(catalog_by_key.keys()),
        max_runs=max(1, int(seed_run_limit)),
        run_groups=run_groups,
    )
    output_root_path = Path(output_root)
    oracle = _AthOracle(
        enabled=bool(verify_with_ath),
        settings=settings,
        output_root=output_root_path,
    )

    results: List[Dict[str, Any]] = []
    total_eval = 0
    try:
        for scenario in scenarios:
            seed_candidates = _seed_candidates_for_scenario(
                scenario=scenario,
                seed_pool=seed_pool,
                card_keys=card_keys,
                key_to_card=key_to_card,
                catalog_by_key=catalog_by_key,
                max_candidates=max(1, int(max_seed_candidates)),
            )
            best: Optional[ScenarioResult] = None
            notes: List[str] = []
            attempt_errors: List[str] = []
            for seed in seed_candidates:
                if not verify_with_ath:
                    params = _inject_minimum_card_keys(
                        dict(seed.params),
                        scenario=scenario,
                        card_keys=card_keys,
                        key_to_card=key_to_card,
                        catalog_by_key=catalog_by_key,
                    )
                    if not _scenario_compliant(params, scenario, key_to_card=key_to_card):
                        continue
                    objective = _objective_tuple(params, key_to_card=key_to_card, included_cards=scenario.included_cards)
                    candidate_result = ScenarioResult(
                        scenario_id=scenario.scenario_id,
                        status="observed_only",
                        description=scenario.description,
                        included_cards=scenario.included_cards,
                        selectors=dict(scenario.selectors),
                        objective=objective,
                        card_counts=_card_counts(params, key_to_card=key_to_card, included_cards=scenario.included_cards),
                        extra_key_count=int(objective[0]),
                        key_count=len(params),
                        source=seed.source,
                        run_id=seed.run_id,
                        params=dict(params),
                        ath={"feasible": None, "ath_exit_code": None, "stl_path": None},
                        compat=_compat_summary(params),
                        notes=["db_observed_candidate"],
                    )
                else:
                    params, ath_eval, eval_count = _greedy_minimize(
                        seed=seed,
                        scenario=scenario,
                        key_to_card=key_to_card,
                        card_keys=card_keys,
                        catalog_by_key=catalog_by_key,
                        oracle=oracle,
                        max_eval=max(1, int(max_eval_per_scenario)),
                    )
                    total_eval += int(eval_count)
                    if params is None:
                        detail = dict(ath_eval.get("detail", {}) or {})
                        error_token = str(detail.get("error", "")).strip()
                        if error_token:
                            attempt_errors.append(f"{seed.source}:{error_token}")
                        elif ath_eval.get("ath_exit_code") is not None:
                            attempt_errors.append(f"{seed.source}:exit_{ath_eval.get('ath_exit_code')}")
                        if seed.source == "synthetic_baseline":
                            notes.append("synthetic_seed_infeasible")
                        continue
                    objective = _objective_tuple(params, key_to_card=key_to_card, included_cards=scenario.included_cards)
                    candidate_result = ScenarioResult(
                        scenario_id=scenario.scenario_id,
                        status="feasible",
                        description=scenario.description,
                        included_cards=scenario.included_cards,
                        selectors=dict(scenario.selectors),
                        objective=objective,
                        card_counts=_card_counts(params, key_to_card=key_to_card, included_cards=scenario.included_cards),
                        extra_key_count=int(objective[0]),
                        key_count=len(params),
                        source=seed.source,
                        run_id=seed.run_id,
                        params=dict(params),
                        ath={
                            "feasible": bool(ath_eval.get("feasible")),
                            "ath_exit_code": ath_eval.get("ath_exit_code"),
                            "stl_path": ath_eval.get("stl_path"),
                            "cached": bool(ath_eval.get("cached", False)),
                        },
                        compat=_compat_summary(params),
                        notes=["ath_verified"],
                    )

                if best is None:
                    best = candidate_result
                    continue
                if tuple(candidate_result.objective) < tuple(best.objective):
                    best = candidate_result

            if best is None:
                failed_result = ScenarioResult(
                    scenario_id=scenario.scenario_id,
                    status="no_feasible_candidate" if verify_with_ath else "no_observed_candidate",
                    description=scenario.description,
                    included_cards=scenario.included_cards,
                    selectors=dict(scenario.selectors),
                    objective=(999_999,),
                    card_counts={card: 0 for card in scenario.included_cards},
                    extra_key_count=0,
                    key_count=0,
                    source="none",
                    run_id=None,
                    params={},
                    ath={"feasible": False, "ath_exit_code": None, "stl_path": None},
                    compat={"fatal_count": 0, "warn_count": 0, "top_messages": []},
                    notes=notes or ["no_matching_seed_found"],
                )
                if attempt_errors:
                    failed_result.notes.extend(sorted(set(attempt_errors))[:3])
                results.append(
                    {
                        **failed_result.__dict__,
                        "objective": list(failed_result.objective),
                    }
                )
                continue

            row = {
                **best.__dict__,
                "objective": list(best.objective),
            }
            if notes:
                row["notes"] = [*list(row.get("notes", []) or []), *notes]
            results.append(row)
    finally:
        oracle.close()

    summary: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "optimization_problem": (
            "black_box_constrained_lexicographic_cardinality_minimization "
            "(feasibility via ATH STL oracle, minXY>0 per included card)"
        ),
        "verify_with_ath": bool(verify_with_ath),
        "db_path": str(db_path),
        "seed_run_limit": int(seed_run_limit),
        "seed_pool_size": int(len(seed_pool)),
        "scenario_count": int(len(scenarios)),
        "max_seed_candidates": int(max_seed_candidates),
        "max_eval_per_scenario": int(max_eval_per_scenario),
        "ath_eval_calls": int(total_eval),
        "scenario_filter": filter_token,
        "results": results,
    }
    files = _write_reports(output_root=output_root_path, summary=summary)
    summary["report_json"] = files["json"]
    summary["report_md"] = files["md"]
    return summary
