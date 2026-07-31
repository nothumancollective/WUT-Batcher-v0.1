"""Automated verification harness for compatibility semantic facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, List, Optional, Sequence

from app.ath_knowledge import load_ath_knowledge
from app.compat_schema import normalize_ruleset
from app.runners import run_process_with_tree_timeout
from app.tidy_dataset import TidyDatasetWriter


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class CompatVerificationCase:
    fact_id: str
    case_id: str
    description: str
    cfg_lines: List[str]
    expected: Dict[str, Any]


def _base_cfg_lines() -> List[str]:
    return [
        "Length = 100",
        "Throat.Diameter = 25",
        "Throat.Angle = 7",
        "Mesh.LengthSegments = 8",
        "Mesh.AngularSegments = 4",
    ]


def build_default_cases() -> List[CompatVerificationCase]:
    return [
        CompatVerificationCase(
            fact_id="output_flags_stl_abecproject",
            case_id="output_flags_both",
            description="Verify that Output.STL and Output.ABECProject request artifacts.",
            cfg_lines=[*_base_cfg_lines(), "Output.STL = 1", "Output.ABECProject = 1"],
            expected={"require_success": True, "require_stl": True, "require_abec": True},
        ),
        CompatVerificationCase(
            fact_id="output_flags_stl_abecproject",
            case_id="output_flags_stl_only",
            description="Verify that Output.STL can be requested independently.",
            cfg_lines=[*_base_cfg_lines(), "Output.STL = 1", "Output.ABECProject = 0"],
            expected={"require_success": True, "require_stl": True, "require_no_abec": True},
        ),
        CompatVerificationCase(
            fact_id="output_flags_stl_abecproject",
            case_id="output_flags_abec_only",
            description="Verify that Output.ABECProject can be requested independently.",
            cfg_lines=[*_base_cfg_lines(), "Output.STL = 0", "Output.ABECProject = 1"],
            expected={"require_success": True, "require_abec": True, "require_no_stl": True},
        ),
        CompatVerificationCase(
            fact_id="ath_creates_subdirectory_per_script",
            case_id="project_subdir_default",
            description="Verify automatic per-script output subdirectory creation.",
            cfg_lines=[*_base_cfg_lines(), "Output.STL = 0", "Output.ABECProject = 0"],
            expected={"require_success": True, "require_project_subdir": True},
        ),
        CompatVerificationCase(
            fact_id="source_items_can_be_omitted",
            case_id="source_defaults_omitted",
            description="Verify ATH accepts omitted Source.* and still runs with defaults.",
            cfg_lines=[*_base_cfg_lines(), "Output.STL = 0", "Output.ABECProject = 0"],
            expected={"require_success": True, "require_source_keys_absent": True},
        ),
        CompatVerificationCase(
            fact_id="source_contours_override",
            case_id="source_contours_present",
            description="Verify Source.Contours is accepted when explicit source keys are present.",
            cfg_lines=[
                *_base_cfg_lines(),
                "Source.Contours = ::esp section1",
                "Source.Shape = 3",
                "Source.Radius = 18",
                "Output.STL = 0",
                "Output.ABECProject = 0",
            ],
            expected={"require_success": True, "require_source_keys_present": True},
        ),
        CompatVerificationCase(
            fact_id="output_flags_stl_abecproject",
            case_id="output_flags_disabled",
            description="Verify no STL/ABEC artifact appears when both flags are disabled.",
            cfg_lines=[*_base_cfg_lines(), "Output.STL = 0", "Output.ABECProject = 0"],
            expected={"require_success": True, "require_no_stl": True, "require_no_abec": True},
        ),
        CompatVerificationCase(
            fact_id="source_items_can_be_omitted",
            case_id="source_defaults_explicit",
            description="Verify ATH still succeeds with explicit Source defaults.",
            cfg_lines=[
                *_base_cfg_lines(),
                "Source.Shape = 1",
                "Source.Radius = -1",
                "Source.Curv = 0",
                "Source.Velocity = 1",
                "Output.STL = 0",
                "Output.ABECProject = 0",
            ],
            expected={"require_success": True, "require_source_keys_present": True},
        ),
    ]


def build_cases(mode: str = "quick") -> List[CompatVerificationCase]:
    all_cases = build_default_cases()
    normalized_mode = str(mode).strip().lower()
    if normalized_mode == "full":
        return all_cases
    # Quick mode keeps the run deterministic and fast (6 cases).
    quick_ids = {
        "output_flags_both",
        "output_flags_stl_only",
        "output_flags_abec_only",
        "project_subdir_default",
        "source_defaults_omitted",
        "source_contours_present",
    }
    quick_cases = [case for case in all_cases if case.case_id in quick_ids]
    if quick_cases:
        return quick_cases
    return all_cases[:6]


def _write_runtime_ath_cfg(path: Path, *, output_root: Path, mesh_cmd: str) -> None:
    text = (
        f'OutputRootDir = "{output_root}"\n'
        f'MeshCmd = "{mesh_cmd}"\n'
        'GnuplotPath = ""\n'
    )
    path.write_text(text, encoding="utf-8")


def _case_output_root(case_dir: Path) -> Path:
    return case_dir / "ath_output"


def _project_subdir(output_root: Path, cfg_path: Path) -> Path:
    return output_root / cfg_path.stem


def _run_case(
    case: CompatVerificationCase,
    *,
    case_root: Path,
    ath_executable: str,
    ath_base_args: Sequence[str],
    timeout_s: int,
    gmsh_path: Optional[str],
) -> Dict[str, Any]:
    case_dir = case_root / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = case_dir / f"{case.case_id}.cfg"
    cfg_text = "\n".join(case.cfg_lines) + "\n"
    cfg_path.write_text(cfg_text, encoding="utf-8")

    runtime_dir = case_dir / "ath_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    output_root = _case_output_root(case_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    # Bare gmsh.exe opens the GUI without a file and can leave a responsive but
    # permanently blocking child behind. ATH replaces %f with its generated GEO.
    _write_runtime_ath_cfg(runtime_dir / "ath.cfg", output_root=output_root, mesh_cmd="gmsh.exe %f -")

    command = [ath_executable, *list(ath_base_args), str(cfg_path)]
    env = dict(os.environ)
    if gmsh_path:
        env["PATH"] = f"{gmsh_path};{env.get('PATH', '')}"

    started_at = _now_iso()
    timed_out = False
    return_code = -1
    stdout = ""
    stderr = ""
    try:
        proc = run_process_with_tree_timeout(
            command,
            cwd=str(runtime_dir),
            timeout=max(1, int(timeout_s)),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=env,
        )
        return_code = int(proc.returncode)
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "")

    project_subdir = _project_subdir(output_root, cfg_path)
    stl_files = list(project_subdir.rglob("*.stl")) if project_subdir.exists() else []
    abec_files = list(project_subdir.rglob("*.abec")) if project_subdir.exists() else []

    observed = {
        "return_code": return_code,
        "timed_out": timed_out,
        "stdout_head": "\n".join(stdout.splitlines()[:10]),
        "stderr_head": "\n".join(stderr.splitlines()[:10]),
        "output_root_exists": output_root.exists(),
        "project_subdir_exists": project_subdir.exists(),
        "stl_count": len(stl_files),
        "abec_count": len(abec_files),
        "source_keys_present_in_cfg": any(
            line.strip().startswith("Source.") for line in cfg_text.splitlines() if line.strip()
        ),
    }

    expected = dict(case.expected)
    checks = {
        "require_success": (return_code == 0 and not timed_out),
        "require_project_subdir": bool(observed["project_subdir_exists"]),
        "require_stl": int(observed["stl_count"]) > 0,
        "require_abec": int(observed["abec_count"]) > 0,
        "require_no_stl": int(observed["stl_count"]) == 0,
        "require_no_abec": int(observed["abec_count"]) == 0,
        "require_source_keys_absent": not bool(observed["source_keys_present_in_cfg"]),
        "require_source_keys_present": bool(observed["source_keys_present_in_cfg"]),
    }
    passed = all(checks[key] for key, enabled in expected.items() if enabled)

    return {
        "fact_id": case.fact_id,
        "case_id": case.case_id,
        "status": "pass" if passed else "fail",
        "expected": expected,
        "observed": observed,
        "details": {
            "description": case.description,
            "command": command,
            "started_at": started_at,
            "finished_at": _now_iso(),
            "checks": checks,
            "cfg_path": str(cfg_path),
            "runtime_dir": str(runtime_dir),
            "output_root": str(output_root),
            "project_subdir": str(project_subdir),
        },
    }


def run_compat_verification(
    *,
    project_root: str | Path,
    project_id: str,
    ath_executable: Optional[str],
    ath_base_args: Sequence[str] = (),
    timeout_s: int = 120,
    gmsh_path: Optional[str] = None,
    persist_sql: bool = True,
    only_hypothesis: bool = True,
    mode: str = "quick",
) -> Dict[str, Any]:
    project_root_path = Path(project_root)
    project_root_path.mkdir(parents=True, exist_ok=True)
    writer: Optional[TidyDatasetWriter] = None
    if persist_sql:
        library_root = (
            project_root_path.parent.parent
            if project_root_path.parent.name.lower() == "projects"
            else project_root_path.parent
        )
        writer = TidyDatasetWriter(project_root_path, library_root=library_root)

    bundle = load_ath_knowledge()
    normalized = normalize_ruleset(bundle.ruleset, bundle.catalog)
    facts = normalized.get("semantic_facts", [])
    evidence_by_fact = {
        str(item.get("fact_id")): item.get("evidence", {})
        for item in facts
        if isinstance(item, dict) and isinstance(item.get("fact_id"), str)
    }

    cases = build_cases(mode=mode)
    results: List[Dict[str, Any]] = []
    case_root = project_root_path / "_compat_tmp"
    case_root.mkdir(parents=True, exist_ok=True)
    for case in cases:
        evidence = evidence_by_fact.get(case.fact_id, {})
        if only_hypothesis and isinstance(evidence, dict) and evidence.get("type") == "ath_doc":
            results.append(
                {
                    "fact_id": case.fact_id,
                    "case_id": case.case_id,
                    "status": "skipped",
                    "expected": dict(case.expected),
                    "observed": {"reason": "ath_doc_evidence_present", "evidence_type": "ath_doc"},
                    "details": {"description": case.description},
                }
            )
            continue
        if not ath_executable:
            results.append(
                {
                    "fact_id": case.fact_id,
                    "case_id": case.case_id,
                    "status": "skipped",
                    "expected": dict(case.expected),
                    "observed": {"reason": "ath_executable_missing"},
                    "details": {"description": case.description},
                }
            )
            continue
        results.append(
            _run_case(
                case,
                case_root=case_root,
                ath_executable=ath_executable,
                ath_base_args=ath_base_args,
                timeout_s=timeout_s,
                gmsh_path=gmsh_path,
            )
        )

    report_dir = project_root_path / "_logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "compat_verification_report.json"
    report_payload = {
        "project_id": project_id,
        "generated_at": _now_iso(),
        "result_count": len(results),
        "results": results,
    }
    report_path.write_text(json.dumps(report_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    sql_result: Dict[str, Any] = {}
    if persist_sql:
        assert writer is not None
        sql_rows = [
            {
                "project_id": project_id,
                "fact_id": row["fact_id"],
                "case_id": row["case_id"],
                "status": row["status"],
                "expected": row["expected"],
                "observed": row["observed"],
                "details": row["details"],
            }
            for row in results
        ]
        sql_result = writer.write_compat_verification_results(sql_rows)

    status_counts = {"pass": 0, "fail": 0, "skipped": 0}
    for row in results:
        key = str(row.get("status", "skipped"))
        status_counts[key] = int(status_counts.get(key, 0)) + 1

    return {
        "project_id": project_id,
        "mode": mode,
        "project_root": str(project_root_path),
        "report_path": str(report_path),
        "case_count": len(cases),
        "status_counts": status_counts,
        "results": results,
        "sql_result": sql_result,
    }
