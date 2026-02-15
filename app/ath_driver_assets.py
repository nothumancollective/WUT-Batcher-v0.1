"""Helpers for ensuring ATH driver assets exist in generated ABEC project folders."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Dict, Optional


DEFAULT_LE_DRIVER_BASENAME = "generic25"
LE_SCRIPT_SECTION_NAME = "LEScript"
LE_SCRIPT_KEY_NAME = "Scriptname_LEScript"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class DriverScriptEnsureResult:
    status: str
    source_path: Optional[str] = None
    target_path: Optional[str] = None
    sha256: Optional[str] = None
    bytes_size: Optional[int] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in {"copied", "already_present"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "source_path": self.source_path,
            "target_path": self.target_path,
            "sha256": self.sha256,
            "bytes_size": self.bytes_size,
            "error": self.error,
        }


@dataclass(frozen=True)
class AbecLeScriptPatchResult:
    status: str
    abec_path: str
    script_filename: str
    section_present_before: bool
    key_present_before: bool
    value_before: str
    value_after: str
    changed: bool
    sha256_before: Optional[str] = None
    sha256_after: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in {"already_set", "patched", "patched_key_inserted", "patched_section_created"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "abec_path": self.abec_path,
            "script_filename": self.script_filename,
            "section_present_before": self.section_present_before,
            "key_present_before": self.key_present_before,
            "value_before": self.value_before,
            "value_after": self.value_after,
            "changed": self.changed,
            "sha256_before": self.sha256_before,
            "sha256_after": self.sha256_after,
            "error": self.error,
        }


@dataclass(frozen=True)
class PostAthLeRepairResult:
    status: str
    abec_path: str
    abec_dir: str
    expected_script_filename: str
    script_path: str
    script_exists: bool
    binding_non_empty: bool
    binding_matches_expected: bool
    binding_value: str
    copy: DriverScriptEnsureResult
    patch: AbecLeScriptPatchResult
    diagnostics_path: Optional[str] = None
    before_snapshot_path: Optional[str] = None
    after_snapshot_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return (
            self.copy.ok
            and self.patch.ok
            and self.script_exists
            and self.binding_non_empty
            and self.binding_matches_expected
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "abec_path": self.abec_path,
            "abec_dir": self.abec_dir,
            "expected_script_filename": self.expected_script_filename,
            "script_path": self.script_path,
            "script_exists": self.script_exists,
            "binding_non_empty": self.binding_non_empty,
            "binding_matches_expected": self.binding_matches_expected,
            "binding_value": self.binding_value,
            "copy": self.copy.to_dict(),
            "patch": self.patch.to_dict(),
            "diagnostics_path": self.diagnostics_path,
            "before_snapshot_path": self.before_snapshot_path,
            "after_snapshot_path": self.after_snapshot_path,
            "error": self.error,
        }


def _driver_filename(driver_basename: str) -> str:
    name = str(driver_basename).strip()
    if not name:
        raise ValueError("driver_basename must not be empty")
    return name if name.lower().endswith(".txt") else f"{name}.txt"


def resolve_ath_driver_source_path(
    ath_executable: str | Path | None,
    *,
    driver_basename: str = DEFAULT_LE_DRIVER_BASENAME,
) -> Optional[Path]:
    if not ath_executable:
        return None

    exe_path = Path(str(ath_executable)).expanduser()
    try:
        exe_path = exe_path.resolve()
    except Exception:
        exe_path = exe_path.absolute()

    filename = _driver_filename(driver_basename)
    roots = [exe_path.parent, exe_path.parent.parent, Path(r"C:\Tools\ATH")]
    seen: set[str] = set()
    for root in roots:
        key = str(root).lower()
        if key in seen:
            continue
        seen.add(key)
        candidate = root / "lib" / "drivers" / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def ensure_driver_script_in_abec_dir(
    *,
    abec_path: str | Path,
    ath_executable: str | Path | None,
    driver_basename: str = DEFAULT_LE_DRIVER_BASENAME,
) -> DriverScriptEnsureResult:
    abec_file = Path(str(abec_path)).expanduser()
    try:
        abec_file = abec_file.resolve()
    except Exception:
        abec_file = abec_file.absolute()

    if not abec_file.exists() or not abec_file.is_file():
        return DriverScriptEnsureResult(status="abec_missing", target_path=str(abec_file))

    source_path = resolve_ath_driver_source_path(
        ath_executable,
        driver_basename=driver_basename,
    )
    if source_path is None:
        return DriverScriptEnsureResult(
            status="source_missing",
            target_path=str(abec_file.parent / _driver_filename(driver_basename)),
            error="driver source not found under ATH/lib/drivers",
        )

    target_path = abec_file.parent / source_path.name
    try:
        source_hash = _sha256_file(source_path)
        source_bytes = source_path.stat().st_size
        if target_path.exists() and target_path.is_file():
            target_hash = _sha256_file(target_path)
            if target_hash == source_hash:
                return DriverScriptEnsureResult(
                    status="already_present",
                    source_path=str(source_path),
                    target_path=str(target_path),
                    sha256=source_hash,
                    bytes_size=source_bytes,
                )

        shutil.copy2(source_path, target_path)
        copied_hash = _sha256_file(target_path)
        copied_bytes = target_path.stat().st_size
        return DriverScriptEnsureResult(
            status="copied",
            source_path=str(source_path),
            target_path=str(target_path),
            sha256=copied_hash,
            bytes_size=copied_bytes,
        )
    except Exception as exc:
        return DriverScriptEnsureResult(
            status="copy_failed",
            source_path=str(source_path),
            target_path=str(target_path),
            error=str(exc),
        )


def _find_le_script_binding(lines: list[str]) -> Dict[str, Any]:
    section_pattern = re.compile(r"^\s*\[(?P<name>[^\]]+)\]\s*$")
    section_present = False
    key_present = False
    value = ""
    section_start = -1
    section_end = len(lines)
    key_line_index = -1
    current_section = ""

    for index, raw in enumerate(lines):
        match = section_pattern.match(raw)
        if match:
            name = str(match.group("name") or "").strip()
            if current_section.lower() == LE_SCRIPT_SECTION_NAME.lower() and section_end == len(lines):
                section_end = index
            current_section = name
            if name.lower() == LE_SCRIPT_SECTION_NAME.lower():
                section_present = True
                section_start = index
            continue
        if current_section.lower() != LE_SCRIPT_SECTION_NAME.lower():
            continue
        if "=" not in raw:
            continue
        lhs, rhs = raw.split("=", 1)
        if str(lhs).strip().lower() != LE_SCRIPT_KEY_NAME.lower():
            continue
        key_present = True
        key_line_index = index
        value = str(rhs).strip()
        break

    return {
        "section_present": section_present,
        "key_present": key_present,
        "value": value,
        "section_start": section_start,
        "section_end": section_end,
        "key_line_index": key_line_index,
    }


def _patch_le_script_text(content: str, *, script_filename: str) -> Dict[str, Any]:
    newline = "\r\n" if "\r\n" in content else "\n"
    trailing_newline = content.endswith("\n") or content.endswith("\r\n")
    lines = content.splitlines()
    if not lines and content == "":
        lines = []

    binding = _find_le_script_binding(lines)
    changed = False
    status = "already_set"

    if not binding["section_present"]:
        if lines and str(lines[-1]).strip():
            lines.append("")
        lines.append(f"[{LE_SCRIPT_SECTION_NAME}]")
        lines.append(f"{LE_SCRIPT_KEY_NAME}={script_filename}")
        changed = True
        status = "patched_section_created"
    elif not binding["key_present"]:
        insert_at = int(binding["section_end"])
        lines.insert(insert_at, f"{LE_SCRIPT_KEY_NAME}={script_filename}")
        changed = True
        status = "patched_key_inserted"
    else:
        existing_value = str(binding["value"]).strip()
        if existing_value != script_filename:
            key_index = int(binding["key_line_index"])
            lines[key_index] = f"{LE_SCRIPT_KEY_NAME}={script_filename}"
            changed = True
            status = "patched"

    new_content = newline.join(lines)
    if trailing_newline and not new_content.endswith(newline):
        new_content += newline
    if not trailing_newline and new_content.endswith(newline):
        new_content = new_content[: -len(newline)]

    return {
        "status": status,
        "changed": changed,
        "content": new_content,
    }


def _read_le_script_binding(abec_path: Path) -> Dict[str, Any]:
    if not abec_path.exists() or not abec_path.is_file():
        return {"section_present": False, "key_present": False, "value": ""}
    text = abec_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    binding = _find_le_script_binding(lines)
    return {
        "section_present": bool(binding["section_present"]),
        "key_present": bool(binding["key_present"]),
        "value": str(binding["value"] or "").strip(),
    }


def patch_abec_le_script_binding(
    *,
    abec_path: str | Path,
    script_filename: str,
) -> AbecLeScriptPatchResult:
    abec_file = Path(str(abec_path)).expanduser()
    try:
        abec_file = abec_file.resolve()
    except Exception:
        abec_file = abec_file.absolute()
    expected = str(script_filename).strip()
    if not expected:
        return AbecLeScriptPatchResult(
            status="invalid_script_filename",
            abec_path=str(abec_file),
            script_filename=str(script_filename),
            section_present_before=False,
            key_present_before=False,
            value_before="",
            value_after="",
            changed=False,
            error="script filename must not be empty",
        )
    if not abec_file.exists() or not abec_file.is_file():
        return AbecLeScriptPatchResult(
            status="abec_missing",
            abec_path=str(abec_file),
            script_filename=expected,
            section_present_before=False,
            key_present_before=False,
            value_before="",
            value_after="",
            changed=False,
            error="abec file not found",
        )
    try:
        before_text = abec_file.read_text(encoding="utf-8", errors="replace")
        before_hash = _sha256_file(abec_file)
        before_binding = _find_le_script_binding(before_text.splitlines())
        patch = _patch_le_script_text(before_text, script_filename=expected)
        if bool(patch["changed"]):
            abec_file.write_text(str(patch["content"]), encoding="utf-8")
        after_binding = _read_le_script_binding(abec_file)
        after_hash = _sha256_file(abec_file)
        return AbecLeScriptPatchResult(
            status=str(patch["status"]),
            abec_path=str(abec_file),
            script_filename=expected,
            section_present_before=bool(before_binding["section_present"]),
            key_present_before=bool(before_binding["key_present"]),
            value_before=str(before_binding["value"] or "").strip(),
            value_after=str(after_binding["value"] or "").strip(),
            changed=bool(patch["changed"]),
            sha256_before=before_hash,
            sha256_after=after_hash,
        )
    except Exception as exc:
        return AbecLeScriptPatchResult(
            status="patch_failed",
            abec_path=str(abec_file),
            script_filename=expected,
            section_present_before=False,
            key_present_before=False,
            value_before="",
            value_after="",
            changed=False,
            error=str(exc),
        )


def repair_post_ath_le_binding(
    *,
    abec_path: str | Path,
    ath_executable: str | Path | None,
    driver_basename: str = DEFAULT_LE_DRIVER_BASENAME,
    diagnostics_dir: str | Path | None = None,
) -> PostAthLeRepairResult:
    abec_file = Path(str(abec_path)).expanduser()
    try:
        abec_file = abec_file.resolve()
    except Exception:
        abec_file = abec_file.absolute()

    before_text = ""
    if abec_file.exists() and abec_file.is_file():
        before_text = abec_file.read_text(encoding="utf-8", errors="replace")

    copy_result = ensure_driver_script_in_abec_dir(
        abec_path=abec_file,
        ath_executable=ath_executable,
        driver_basename=driver_basename,
    )
    expected_filename = _driver_filename(driver_basename)
    patch_result = patch_abec_le_script_binding(
        abec_path=abec_file,
        script_filename=expected_filename,
    )

    binding = _read_le_script_binding(abec_file)
    script_path = abec_file.parent / expected_filename
    script_exists = bool(script_path.exists() and script_path.is_file())
    binding_value = str(binding.get("value", "") or "").strip()
    binding_non_empty = bool(binding_value)
    binding_matches_expected = binding_value.lower() == expected_filename.lower()

    diagnostics_path = None
    before_snapshot_path = None
    after_snapshot_path = None
    if diagnostics_dir:
        diag_root = Path(str(diagnostics_dir)).expanduser()
        diag_root.mkdir(parents=True, exist_ok=True)
        before_path = diag_root / "Project.abec.before.txt"
        after_path = diag_root / "Project.abec.after.txt"
        summary_path = diag_root / "le_repair_summary.json"
        try:
            before_path.write_text(before_text, encoding="utf-8")
            after_text = ""
            if abec_file.exists() and abec_file.is_file():
                after_text = abec_file.read_text(encoding="utf-8", errors="replace")
            after_path.write_text(after_text, encoding="utf-8")
            summary_payload = {
                "abec_path": str(abec_file),
                "abec_dir": str(abec_file.parent),
                "expected_script_filename": expected_filename,
                "script_path": str(script_path),
                "script_exists": script_exists,
                "binding_non_empty": binding_non_empty,
                "binding_matches_expected": binding_matches_expected,
                "binding_value": binding_value,
                "copy": copy_result.to_dict(),
                "patch": patch_result.to_dict(),
            }
            summary_path.write_text(json.dumps(summary_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            diagnostics_path = str(summary_path)
            before_snapshot_path = str(before_path)
            after_snapshot_path = str(after_path)
        except Exception:
            diagnostics_path = None
            before_snapshot_path = None
            after_snapshot_path = None

    failure = None
    if not copy_result.ok:
        failure = f"copy_failed:{copy_result.status}"
    elif not patch_result.ok:
        failure = f"abec_patch_failed:{patch_result.status}"
    elif not script_exists:
        failure = "script_missing_after_repair"
    elif not binding_non_empty:
        failure = "lescript_binding_empty_after_repair"
    elif not binding_matches_expected:
        failure = "lescript_binding_mismatch_after_repair"

    status = "ok" if failure is None else "failed"
    return PostAthLeRepairResult(
        status=status,
        abec_path=str(abec_file),
        abec_dir=str(abec_file.parent),
        expected_script_filename=expected_filename,
        script_path=str(script_path),
        script_exists=script_exists,
        binding_non_empty=binding_non_empty,
        binding_matches_expected=binding_matches_expected,
        binding_value=binding_value,
        copy=copy_result,
        patch=patch_result,
        diagnostics_path=diagnostics_path,
        before_snapshot_path=before_snapshot_path,
        after_snapshot_path=after_snapshot_path,
        error=failure,
    )
