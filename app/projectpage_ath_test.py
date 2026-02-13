"""Project-page focused ATH end-to-end verification harness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from app.cfg_renderer import render_cfg_text
from app.compatibility_service import CompatibilityService
from app.constants import DEFAULT_RUNNER_MODE, MANDATORY_SOURCE_BLOCK
from app.models import Batch, ProjectConstraints
from app.runners import AthRunner, RunnerResult
from app.settings_store import UserSettings
from app.version_resolver import resolve_versions
from ui.form_builder import ParameterForm
from ui.form_schema import build_project_form_schema


try:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
except Exception:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


_CFG_BASENAME_RE = re.compile(r"^ProjectPageATHTest(\d+)\.cfg$", re.IGNORECASE)
_ASSIGN_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s*=\s*(.*?)\s*$")
_SPACE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)\s+(.+?)\s*$")
_NUMERIC_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")


@dataclass(frozen=True)
class ProjectPageAthCase:
    test_id: str
    project_name: str
    field_values: Sequence[Tuple[str, Any]]


@dataclass(frozen=True)
class CaseArtifacts:
    cfg_path: Path
    runtime_dir: Path
    logs_dir: Path
    report_path: Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _ensure_qt_app() -> None:
    if QApplication is None:
        raise RuntimeError("PySide6 is required for projectpage-ath-test. Install with `pip install PySide6`.")
    _ = QApplication.instance() or QApplication([])


def _collapse_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _normalize_expression(value: Any) -> str:
    text = _collapse_ws(str(value))
    text = re.sub(r"(?<=\d),(?=\d)", ".", text)
    return text.replace(" ", "")


def _parse_numeric(value: Any) -> Optional[float]:
    text = str(value).strip()
    if not _NUMERIC_RE.match(text):
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _values_equal(expected: Any, actual: Any, *, tol: float = 1e-6) -> bool:
    exp_num = _parse_numeric(expected)
    act_num = _parse_numeric(actual)
    if exp_num is not None and act_num is not None:
        return abs(exp_num - act_num) <= tol
    return _normalize_expression(expected) == _normalize_expression(actual)


def _strip_inline_comment(line: str) -> str:
    in_quotes = False
    escaped = False
    for idx, char in enumerate(line):
        if char == "\\" and not escaped:
            escaped = True
            continue
        if char == '"' and not escaped:
            in_quotes = not in_quotes
        if not in_quotes and char in {";", "#"}:
            return line[:idx]
        escaped = False
    return line


def _flatten_values(prefix: str, value: Any) -> Dict[str, Any]:
    if isinstance(value, Mapping):
        flattened: Dict[str, Any] = {}
        for sub_key, sub_value in value.items():
            child_key = f"{prefix}.{sub_key}"
            if isinstance(sub_value, Mapping):
                flattened.update(_flatten_values(child_key, sub_value))
            else:
                flattened[child_key] = sub_value
        return flattened
    return {prefix: value}


def parse_key_value_text(text: str) -> Dict[str, Any]:
    parsed: Dict[str, Any] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        stripped = _strip_inline_comment(lines[index]).strip()
        if not stripped:
            index += 1
            continue

        assign = _ASSIGN_RE.match(stripped)
        if assign is None:
            spaced = _SPACE_ASSIGN_RE.match(stripped)
            if spaced is not None and "=" not in stripped and not stripped.endswith("{"):
                parsed[spaced.group(1).strip()] = _collapse_ws(spaced.group(2))
            index += 1
            continue

        key = assign.group(1).strip()
        raw_value = assign.group(2).strip()
        if raw_value == "{":
            index += 1
            while index < len(lines):
                block_line = _strip_inline_comment(lines[index]).strip()
                if not block_line:
                    index += 1
                    continue
                if block_line.startswith("}"):
                    break
                sub_assign = _ASSIGN_RE.match(block_line)
                if sub_assign is not None:
                    sub_key = sub_assign.group(1).strip()
                    parsed[f"{key}.{sub_key}"] = _collapse_ws(sub_assign.group(2))
                index += 1
            index += 1
            continue

        if raw_value.startswith("{") and raw_value.endswith("}") and '"' in raw_value:
            try:
                obj_value = json.loads(raw_value)
            except Exception:
                parsed[key] = _collapse_ws(raw_value)
            else:
                if isinstance(obj_value, Mapping):
                    parsed.update(_flatten_values(key, obj_value))
                else:
                    parsed[key] = obj_value
            index += 1
            continue

        parsed[key] = _collapse_ws(raw_value)
        index += 1
    return parsed


def compare_expected(
    *,
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    allowed_global_keys: Iterable[str],
) -> Dict[str, Any]:
    expected_flat: Dict[str, Any] = {}
    for key, value in expected.items():
        expected_flat.update(_flatten_values(str(key), value))

    observed_map = {str(key): value for key, value in observed.items()}
    allowed = set(str(key) for key in allowed_global_keys)
    allowed_keys = set(expected_flat.keys()) | allowed

    missing = sorted(key for key in expected_flat.keys() if key not in observed_map)
    extra = sorted(key for key in observed_map.keys() if key not in allowed_keys)
    mismatches: List[Dict[str, Any]] = []
    for key, expected_value in sorted(expected_flat.items()):
        if key not in observed_map:
            continue
        actual_value = observed_map[key]
        if not _values_equal(expected_value, actual_value):
            mismatches.append(
                {
                    "key": key,
                    "expected": expected_value,
                    "actual": actual_value,
                }
            )

    return {
        "missing_keys": missing,
        "extra_keys": extra,
        "value_mismatches": mismatches,
        "ok": not missing and not extra and not mismatches,
    }


def _next_cfg_index(cfg_dir: Path) -> int:
    max_index = 0
    if cfg_dir.exists():
        for entry in cfg_dir.iterdir():
            if not entry.is_file():
                continue
            match = _CFG_BASENAME_RE.match(entry.name)
            if match:
                max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def _path_dirs_snapshot(root: Path) -> Dict[str, int]:
    if not root.exists():
        return {}
    snapshot: Dict[str, int] = {}
    for entry in root.iterdir():
        if entry.is_dir():
            snapshot[entry.name] = entry.stat().st_mtime_ns
    return snapshot


def _detect_export_dir(export_root: Path, before: Mapping[str, int]) -> Optional[Path]:
    if not export_root.exists():
        return None
    after = _path_dirs_snapshot(export_root)
    new_entries = [name for name in after.keys() if name not in before]
    if new_entries:
        new_entries.sort(key=lambda name: after[name], reverse=True)
        return export_root / new_entries[0]
    changed_entries = [name for name, mtime_ns in after.items() if mtime_ns > int(before.get(name, -1))]
    if changed_entries:
        changed_entries.sort(key=lambda name: after[name], reverse=True)
        return export_root / changed_entries[0]
    return None


def _best_mesh_cmd(ath_executable: Path) -> str:
    gmsh_candidate = ath_executable.parent / "gmsh.exe"
    if gmsh_candidate.exists():
        return str(gmsh_candidate)
    return ""


def _write_runtime_ath_cfg(runtime_dir: Path, *, export_root: Path, mesh_cmd: str) -> Path:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    export_value = str(export_root).replace("\\", "/")
    text = (
        f'OutputRootDir = "{export_value}"\n'
        f'MeshCmd = "{mesh_cmd}"\n'
        'GnuplotPath = ""\n'
    )
    path = runtime_dir / "ath.cfg"
    path.write_text(text, encoding="utf-8")
    return path


def _find_config_file(export_dir: Path) -> Optional[Path]:
    direct_candidates = [export_dir / "config", export_dir / "config.txt"]
    for candidate in direct_candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    fallback = sorted(
        [path for path in export_dir.rglob("config*") if path.is_file()],
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    return fallback[0] if fallback else None


def _materialize_case_payload(
    case: ProjectPageAthCase,
    *,
    runner_mode: str = DEFAULT_RUNNER_MODE,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    _ensure_qt_app()
    service = CompatibilityService()
    form = ParameterForm(build_project_form_schema())

    def refresh_compat() -> None:
        draft = form.payload()
        state = service.evaluate_project_constraints({**draft, "runner_mode": runner_mode})
        form.apply_compatibility(state)

    refresh_compat()
    missing_editors: List[str] = []
    for key, value in case.field_values:
        editor = form.editor_for_key(str(key))
        if editor is None and "." in str(key):
            parent_key = str(key).rsplit(".", 1)[0]
            parent_editor = form.editor_for_key(parent_key)
            if (
                parent_editor is not None
                and hasattr(parent_editor, "property_editors")
                and isinstance(getattr(parent_editor, "property_editors"), dict)
            ):
                editor = getattr(parent_editor, "property_editors").get(str(key))
                if editor is not None and hasattr(parent_editor, "set_is_set"):
                    parent_editor.set_is_set(True)  # type: ignore[attr-defined]
        if editor is None:
            missing_editors.append(str(key))
            continue
        if value is None and hasattr(editor, "set_is_set"):
            editor.set_is_set(False)  # type: ignore[attr-defined]
            refresh_compat()
            continue
        if hasattr(editor, "set_is_set"):
            editor.set_is_set(True)  # type: ignore[attr-defined]
        if hasattr(editor, "set_value"):
            editor.set_value(value)  # type: ignore[attr-defined]
        if hasattr(form, "_on_any_field_changed"):
            form._on_any_field_changed()  # type: ignore[attr-defined]
        refresh_compat()

    payload = form.payload()
    payload["runner_mode"] = runner_mode
    ui_set_keys = sorted(
        str(item.get("param_name"))
        for item in payload.get("param_states", [])
        if isinstance(item, dict) and int(item.get("is_set", 0)) == 1
    )
    return payload, service.evaluate_project_constraints(payload), sorted(set(missing_editors))


def _resolve_render_inputs(constraints_payload: Mapping[str, Any], *, runner_mode: str) -> Tuple[Dict[str, Any], List[str]]:
    constraints = ProjectConstraints.from_dict(dict(constraints_payload))
    batch = Batch(
        batch_id="B_ATH_TEST",
        project_id="P_ATH_TEST",
        selected_params={},
        sweeps={},
        sweep_mode="single",
        runner_mode=runner_mode,
    )
    resolved = resolve_versions(constraints, batch, strict=True)
    if len(resolved.versions) != 1:
        raise RuntimeError(f"Expected exactly one resolved version, got {len(resolved.versions)}.")
    version = resolved.versions[0]
    return dict(version.parameters), list(version.unset_parameters)


def default_projectpage_ath_cases() -> List[ProjectPageAthCase]:
    return [
        ProjectPageAthCase(
            test_id="PP_ATH_TEST_01",
            project_name="PP_ATH_TEST_01",
            field_values=[
                ("Length", 130.0),
                ("Throat.Diameter", 36.0),
                ("Throat.Angle", 4.2),
                ("Throat.Profile", 1),
                ("Term.s", 0.7),
                ("Term.q", 0.995),
                ("Term.n", 3.7),
                ("OS.k", 1.0),
                ("Coverage.Angle", 48.5),
                ("Morph.TargetShape", 0),
                ("Rollback", 0),
                ("Mesh.Quadrants", 1),
                ("Mesh.AngularSegments", 64),
                ("Mesh.LengthSegments", 18),
            ],
        ),
        ProjectPageAthCase(
            test_id="PP_ATH_TEST_02",
            project_name="PP_ATH_TEST_02",
            field_values=[
                ("Throat.Diameter", 34.0),
                ("Throat.Angle", 5.0),
                ("Throat.Profile", 2),
                ("R-OSSE.R", 100.0),
                ("R-OSSE.r0", 17.0),
                ("R-OSSE.a0", 4.5),
                ("R-OSSE.a", 46.0),
                ("R-OSSE.k", 1.0),
                ("R-OSSE.r", 0.7),
                ("R-OSSE.m", 2.8),
                ("R-OSSE.b", 0.2),
                ("R-OSSE.q", 0.995),
                ("Coverage.Angle", 52.0),
                ("Morph.TargetShape", 0),
                ("Rollback", 0),
                ("Mesh.Quadrants", 1),
                ("Mesh.AngularSegments", 72),
                ("Mesh.LengthSegments", 20),
            ],
        ),
        ProjectPageAthCase(
            test_id="PP_ATH_TEST_03",
            project_name="PP_ATH_TEST_03",
            field_values=[
                ("Length", 145.0),
                ("Throat.Diameter", 35.0),
                ("Throat.Angle", 5.8),
                ("Throat.Profile", 3),
                ("CircArc.TermAngle", 40.0),
                ("CircArc.Radius", 220.0),
                ("GCurve.Type", 1),
                ("GCurve.Dist", 65.0),
                ("GCurve.Width", 150.0),
                ("GCurve.AspectRatio", 1.25),
                ("GCurve.SE.n", 2.6),
                ("Morph.TargetShape", 1),
                ("Morph.TargetWidth", 320.0),
                ("Morph.TargetHeight", 240.0),
                ("Morph.CornerRadius", 18.0),
                ("Rollback", 1),
                ("Rollback.StartAt", 0.56),
                ("Rollback.Angle", 170.0),
                ("Rollback.Exp", 1.4),
                ("Mesh.Quadrants", 1),
                ("Mesh.AngularSegments", 68),
                ("Mesh.LengthSegments", 22),
            ],
        ),
        ProjectPageAthCase(
            test_id="PP_ATH_TEST_04",
            project_name="PP_ATH_TEST_04",
            field_values=[
                ("Length", 138.0),
                ("Throat.Diameter", 34.0),
                ("Throat.Angle", 4.0),
                ("Throat.Profile", 1),
                ("Term.s", 0.78),
                ("Term.q", 0.996),
                ("Term.n", 3.4),
                ("OS.k", 0.95),
                ("GCurve.Type", 2),
                ("GCurve.Dist", 62.0),
                ("GCurve.Width", 142.0),
                ("GCurve.SF.a", 1.0),
                ("GCurve.SF.b", 1.0),
                ("GCurve.SF.m1", 3.0),
                ("GCurve.SF.m2", 4.0),
                ("GCurve.SF.n1", 0.2),
                ("GCurve.SF.n2", 1.6),
                ("GCurve.SF.n3", 1.7),
                ("Morph.TargetShape", 0),
                ("Rollback", 0),
                ("Mesh.Quadrants", 1),
                ("Mesh.AngularSegments", 64),
                ("Mesh.LengthSegments", 18),
            ],
        ),
        ProjectPageAthCase(
            test_id="PP_ATH_TEST_05",
            project_name="PP_ATH_TEST_05",
            field_values=[
                ("Length", 125.0),
                ("Throat.Diameter", 32.0),
                ("Throat.Angle", 3.8),
                ("Throat.Profile", 1),
                ("Term.s", 0.8),
                ("Term.q", 0.994),
                ("Term.n", 3.2),
                ("OS.k", 0.9),
                ("Coverage.Angle", 46.0),
                ("Morph.TargetShape", 2),
                ("Morph.TargetWidth", 260.0),
                ("Morph.TargetHeight", 260.0),
                ("Rollback", 1),
                ("Rollback.StartAt", 0.52),
                ("Rollback.Angle", 165.0),
                ("Rollback.Exp", 1.5),
                ("Mesh.Quadrants", 1),
                ("Mesh.AngularSegments", 60),
                ("Mesh.LengthSegments", 16),
            ],
        ),
        ProjectPageAthCase(
            test_id="PP_ATH_TEST_06",
            project_name="PP_ATH_TEST_06",
            field_values=[
                ("Length", 132.0),
                ("Throat.Diameter", 33.0),
                ("Throat.Angle", 4.4),
                ("Throat.Profile", 3),
                ("CircArc.TermAngle", 38.0),
                ("CircArc.Radius", 180.0),
                ("GCurve.Type", 1),
                ("GCurve.Dist", 58.0),
                ("GCurve.Width", 135.0),
                ("GCurve.SE.n", 2.1),
                ("Morph.TargetShape", 1),
                ("Morph.TargetWidth", 280.0),
                ("Morph.TargetHeight", 210.0),
                ("Rollback", 0),
                ("Mesh.Quadrants", 1),
                ("Mesh.AngularSegments", 64),
                ("Mesh.LengthSegments", 18),
            ],
        ),
        ProjectPageAthCase(
            test_id="PP_ATH_TEST_07",
            project_name="PP_ATH_TEST_07",
            field_values=[
                ("Length", 140.0),
                ("Throat.Diameter", 35.0),
                ("Throat.Angle", 5.2),
                ("Throat.Profile", 1),
                ("Term.s", 0.72),
                ("Term.q", 0.995),
                ("Term.n", 3.6),
                ("OS.k", 1.05),
                ("Coverage.Angle", 50.0),
                ("Morph.TargetShape", 0),
                ("Rollback", 1),
                ("Rollback.StartAt", 0.5),
                ("Rollback.Angle", 172.0),
                ("Rollback.Exp", 1.35),
                ("Mesh.Quadrants", 1),
                ("Mesh.AngularSegments", 72),
                ("Mesh.LengthSegments", 20),
            ],
        ),
        ProjectPageAthCase(
            test_id="PP_ATH_TEST_08",
            project_name="PP_ATH_TEST_08",
            field_values=[
                ("Length", 136.0),
                ("Throat.Diameter", 34.5),
                ("Throat.Angle", 4.6),
                ("Throat.Profile", 3),
                ("CircArc.TermAngle", 36.0),
                ("CircArc.Radius", 200.0),
                ("GCurve.Type", 2),
                ("GCurve.Dist", 60.0),
                ("GCurve.Width", 140.0),
                ("GCurve.SF.a", 1.0),
                ("GCurve.SF.b", 1.0),
                ("GCurve.SF.m1", 5.0),
                ("GCurve.SF.m2", 5.0),
                ("GCurve.SF.n1", 0.3),
                ("GCurve.SF.n2", 1.1),
                ("GCurve.SF.n3", 1.1),
                ("Morph.TargetShape", 2),
                ("Morph.TargetWidth", 255.0),
                ("Morph.TargetHeight", 255.0),
                ("Rollback", 0),
                ("Mesh.Quadrants", 1),
                ("Mesh.AngularSegments", 64),
                ("Mesh.LengthSegments", 18),
            ],
        ),
    ]


def _case_artifacts(root: Path, *, index: int, cfg_path: Path) -> CaseArtifacts:
    run_root = root / f"run_{index:02d}"
    return CaseArtifacts(
        cfg_path=cfg_path,
        runtime_dir=run_root / "ath_runtime",
        logs_dir=run_root / "logs",
        report_path=run_root / f"report_{index:02d}.json",
    )


def _load_template_text(template_cfg: Optional[str]) -> str:
    if not template_cfg:
        return "; autogenerated cfg template\n"
    return Path(template_cfg).read_text(encoding="utf-8")


def run_projectpage_ath_test_suite(
    *,
    settings: UserSettings,
    ath_exe: Optional[str] = None,
    template_cfg: Optional[str] = None,
    cfg_dir: str | Path = r"C:\Tools\ATH",
    export_root: str | Path = r"C:\Horns",
    reports_root: str | Path = "reports/projectpage_ath_test",
    case_limit: Optional[int] = None,
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
    cfg_root.mkdir(parents=True, exist_ok=True)
    export_root_path.mkdir(parents=True, exist_ok=True)
    reports_root_path.mkdir(parents=True, exist_ok=True)

    template_text = _load_template_text(template_cfg or settings.template_cfg)
    cases = default_projectpage_ath_cases()
    if case_limit is not None:
        cases = cases[: max(0, int(case_limit))]

    runner = AthRunner(str(ath_executable))
    allowed_global_keys = {str(key) for key, _ in MANDATORY_SOURCE_BLOCK}
    start_cfg_index = _next_cfg_index(cfg_root)
    reports: List[Dict[str, Any]] = []

    for offset, case in enumerate(cases):
        cfg_index = start_cfg_index + offset
        cfg_path = cfg_root / f"ProjectPageATHTest{cfg_index}.cfg"
        artifacts = _case_artifacts(reports_root_path, index=offset + 1, cfg_path=cfg_path)
        artifacts.report_path.parent.mkdir(parents=True, exist_ok=True)

        case_started_at = _now_iso()
        payload, compat_state, missing_editors = _materialize_case_payload(case)
        runner_mode = str(payload.get("runner_mode") or DEFAULT_RUNNER_MODE)
        expected_values = {
            **dict(payload.get("fixed_params", {}) or {}),
            **dict(payload.get("limits", {}) or {}),
        }
        try:
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
            cfg_error: Optional[str] = None
        except Exception as exc:  # pragma: no cover - exercised in real integration run
            cfg_written = False
            cfg_error = str(exc)

        before_dirs = _path_dirs_snapshot(export_root_path)
        ath_result: Optional[RunnerResult] = None
        ath_error: Optional[str] = None
        if cfg_written:
            _write_runtime_ath_cfg(
                artifacts.runtime_dir,
                export_root=export_root_path,
                mesh_cmd=_best_mesh_cmd(ath_executable),
            )
            try:
                ath_result = runner.run_cfg(
                    cfg_path,
                    version_logs_dir=artifacts.logs_dir,
                    workdir=artifacts.runtime_dir,
                )
            except Exception as exc:  # pragma: no cover - exercised in real integration run
                ath_error = str(exc)

        export_dir = _detect_export_dir(export_root_path, before_dirs) if cfg_written else None
        config_file = _find_config_file(export_dir) if export_dir is not None else None

        cfg_parsed = parse_key_value_text(cfg_path.read_text(encoding="utf-8")) if cfg_written else {}
        config_parsed = parse_key_value_text(config_file.read_text(encoding="utf-8")) if config_file else {}
        cfg_compare = compare_expected(
            expected=expected_values,
            observed=cfg_parsed,
            allowed_global_keys=allowed_global_keys,
        )
        config_compare = compare_expected(
            expected=expected_values,
            observed=config_parsed,
            allowed_global_keys=allowed_global_keys,
        )
        ath_ok = bool(ath_result and ath_result.ok)
        config_ok = config_file is not None and config_compare["ok"]
        no_ghosts = (not cfg_compare["extra_keys"]) and (not config_compare["extra_keys"])

        report = {
            "test_id": case.test_id,
            "project_name": case.project_name,
            "started_at": case_started_at,
            "finished_at": _now_iso(),
            "input_summary": {
                "field_values": list(case.field_values),
                "ui_set_keys": sorted(
                    str(item.get("param_name"))
                    for item in payload.get("param_states", [])
                    if isinstance(item, dict) and int(item.get("is_set", 0)) == 1
                ),
                "payload_fixed_params": dict(payload.get("fixed_params", {}) or {}),
                "payload_limits": dict(payload.get("limits", {}) or {}),
                "runner_mode": runner_mode,
                "compat_issues": list(compat_state.get("issues", []) or []),
                "missing_editors": missing_editors,
            },
            "cfg_path": str(cfg_path),
            "horns_export_dir": str(export_dir) if export_dir else None,
            "config_path": str(config_file) if config_file else None,
            "report_path": str(artifacts.report_path),
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
                else {
                    "ok": False,
                    "exit_code": None,
                    "timed_out": None,
                    "stdout_log": None,
                    "stderr_log": None,
                    "summary_log": None,
                    "error": ath_error,
                }
            ),
            "compare": {
                "expected_values": expected_values,
                "allowed_global_keys": sorted(allowed_global_keys),
                "cfg": cfg_compare,
                "config": config_compare,
            },
            "errors": {
                "cfg_error": cfg_error,
                "ath_error": ath_error,
            },
        }
        artifacts.report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        reports.append(report)

    status_counts = {"ok": 0, "failed": 0}
    for item in reports:
        flags = dict(item.get("success_flags", {}) or {})
        case_ok = bool(flags.get("cfg_written")) and bool(flags.get("ath_ok")) and bool(flags.get("config_ok")) and bool(
            flags.get("no_ghosts")
        )
        if case_ok:
            status_counts["ok"] += 1
        else:
            status_counts["failed"] += 1

    summary = {
        "generated_at": _now_iso(),
        "reports_root": str(reports_root_path),
        "cfg_dir": str(cfg_root),
        "export_root": str(export_root_path),
        "ath_executable": str(ath_executable),
        "template_cfg": template_cfg or settings.template_cfg,
        "total_cases": len(reports),
        "status_counts": status_counts,
        "report_files": [str(item.get("report_path")) for item in reports],
        "reports": reports,
    }
    summary_path = reports_root_path / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary["summary_path"] = str(summary_path)
    return summary
