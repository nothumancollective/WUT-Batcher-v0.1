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
LE_PATCH_PROFILE_BASELINE = "baseline"
LE_PATCH_PROFILE_DRIVER_DRVGROUP = "driver_drvgroup"
LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING = "driver_drvgroup_def_driving"
LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR = "driver_drvgroup_def_driving_resistor"
LE_PATCH_PROFILE_MUT_ELECTRICAL = "mut_electrical"
LE_PATCH_PROFILE_MUT_MOTOR = "mut_motor"


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
    driver_patch: "LeDriverScriptPatchResult"
    patch: AbecLeScriptPatchResult
    diagnostics_path: Optional[str] = None
    before_snapshot_path: Optional[str] = None
    after_snapshot_path: Optional[str] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return (
            self.copy.ok
            and self.driver_patch.ok
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
            "driver_patch": self.driver_patch.to_dict(),
            "patch": self.patch.to_dict(),
            "diagnostics_path": self.diagnostics_path,
            "before_snapshot_path": self.before_snapshot_path,
            "after_snapshot_path": self.after_snapshot_path,
            "error": self.error,
        }


@dataclass(frozen=True)
class LeDriverScriptPatchResult:
    status: str
    profile: str
    target_path: Optional[str] = None
    changed: bool = False
    driver_line_changed: bool = False
    def_driving_changed: bool = False
    driver_drvgroup_value: Optional[str] = None
    def_driving_value: Optional[str] = None
    sha256_before: Optional[str] = None
    sha256_after: Optional[str] = None
    mutated_parameters: Optional[list[str]] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status in {
            "not_requested",
            "already_conformant",
            "patched",
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "profile": self.profile,
            "target_path": self.target_path,
            "changed": self.changed,
            "driver_line_changed": self.driver_line_changed,
            "def_driving_changed": self.def_driving_changed,
            "driver_drvgroup_value": self.driver_drvgroup_value,
            "def_driving_value": self.def_driving_value,
            "sha256_before": self.sha256_before,
            "sha256_after": self.sha256_after,
            "mutated_parameters": list(self.mutated_parameters or []),
            "error": self.error,
        }


def _driver_filename(driver_basename: str) -> str:
    name = str(driver_basename).strip()
    if not name:
        raise ValueError("driver_basename must not be empty")
    return name if name.lower().endswith(".txt") else f"{name}.txt"


def _normalize_le_patch_profile(profile: Optional[str]) -> str:
    value = str(profile or "").strip().lower()
    if not value:
        return LE_PATCH_PROFILE_BASELINE
    aliases = {
        "none": LE_PATCH_PROFILE_BASELINE,
        "baseline": LE_PATCH_PROFILE_BASELINE,
        "drvgroup": LE_PATCH_PROFILE_DRIVER_DRVGROUP,
        "driver_drvgroup": LE_PATCH_PROFILE_DRIVER_DRVGROUP,
        "drvgroup+def_driving": LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING,
        "driver_drvgroup_def_driving": LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING,
        "driver_drvgroup+def_driving": LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING,
        "driver_drvgroup_def_driving_resistor": LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR,
        "doc_example": LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR,
        "mut_electrical": LE_PATCH_PROFILE_MUT_ELECTRICAL,
        "mut_motor": LE_PATCH_PROFILE_MUT_MOTOR,
    }
    return aliases.get(value, value)


def _format_voltage_vrms(value: float) -> str:
    rendered = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return rendered or "0"


def _split_line_comment(raw: str) -> tuple[str, str]:
    body, marker, comment = raw.partition("//")
    if not marker:
        return raw, ""
    return body.rstrip(), f" {marker}{comment}"


def _ensure_driver_drvgroup(
    content: str,
    *,
    driver_tag: str,
    drvgroup_value: str,
) -> tuple[str, bool, bool]:
    lines = content.splitlines()
    driver_regex = re.compile(
        r"^\s*Driver\s+'{}'(?=\s|$)".format(re.escape(driver_tag)),
        flags=re.IGNORECASE,
    )
    drvgroup_regex = re.compile(r"\bDrvGroup\s*=", flags=re.IGNORECASE)
    drvgroup_value_regex = re.compile(
        r"\bDrvGroup\s*=\s*([0-9,\s]+)",
        flags=re.IGNORECASE,
    )
    changed = False
    found = False

    for index, line in enumerate(lines):
        if not driver_regex.search(line):
            continue
        found = True
        body, comment = _split_line_comment(line)
        if drvgroup_regex.search(body):
            match = drvgroup_value_regex.search(body)
            if match and str(drvgroup_value) in str(match.group(1)):
                break
            body = drvgroup_value_regex.sub(f"DrvGroup={drvgroup_value}", body, count=1)
        else:
            body = f"{body.rstrip()} DrvGroup={drvgroup_value}".rstrip()
        updated = f"{body}{comment}".rstrip()
        if updated != line.rstrip():
            lines[index] = updated
            changed = True
        break

    return "\n".join(lines), changed, found


def _ensure_def_driving(
    content: str,
    *,
    voltage_vrms: float,
) -> tuple[str, bool]:
    lines = content.splitlines()
    if any(re.search(r"^\s*Def_Driving\b", line, flags=re.IGNORECASE) for line in lines):
        return "\n".join(lines), False

    insert_at = 0
    for index, line in enumerate(lines):
        if re.search(r"^\s*System\b", line, flags=re.IGNORECASE):
            insert_at = index
            break
    driving_line = f'Def_Driving "Voltage source" Value={_format_voltage_vrms(voltage_vrms)}V IsRms'
    lines.insert(insert_at, driving_line)
    if insert_at + 1 < len(lines) and str(lines[insert_at + 1]).strip():
        lines.insert(insert_at + 1, "")
    return "\n".join(lines), True


def _ensure_system_resistor_and_driver_node(
    content: str,
    *,
    driver_tag: str,
) -> tuple[str, bool]:
    lines = content.splitlines()
    changed = False
    system_index = -1
    for index, line in enumerate(lines):
        if re.search(r"^\s*System\b", line, flags=re.IGNORECASE):
            system_index = index
            break
    if system_index >= 0:
        has_resistor = False
        for line in lines[system_index + 1 :]:
            if re.search(r"^\s*System\b", line, flags=re.IGNORECASE):
                break
            if re.search(r"^\s*Resistor\s+'Rg'\b", line, flags=re.IGNORECASE):
                has_resistor = True
                break
        if not has_resistor:
            insert_at = system_index + 1
            lines.insert(insert_at, "  Resistor 'Rg' Node=1=2 R=1ohm")
            changed = True

    driver_regex = re.compile(
        r"^\s*Driver\s+'{}'(?=\s|$)".format(re.escape(driver_tag)),
        flags=re.IGNORECASE,
    )
    for index, line in enumerate(lines):
        if not driver_regex.search(line):
            continue
        updated = re.sub(r"Node\s*=\s*1\s*=\s*0\s*=", "Node=2=0=", line, count=1, flags=re.IGNORECASE)
        if updated != line:
            lines[index] = updated
            changed = True
        break
    return "\n".join(lines), changed


def _replace_first_param_value(
    content: str,
    *,
    param: str,
    value_token: str,
    force_unit: Optional[str] = None,
) -> tuple[str, bool]:
    pattern = re.compile(
        r"(\b"
        + re.escape(param)
        + r"\s*=\s*)([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)([ \t]*[A-Za-z/%]+)?",
        flags=re.IGNORECASE,
    )

    changed = False

    def _repl(match: re.Match[str]) -> str:
        nonlocal changed
        prefix = str(match.group(1) or "")
        old_value = str(match.group(2) or "").strip()
        unit = str(match.group(3) or "").strip()
        if force_unit is not None:
            unit = str(force_unit).strip()
        replacement = f"{prefix}{value_token}{unit}"
        previous = f"{prefix}{old_value}{str(match.group(3) or '')}".strip()
        if replacement.strip() != previous.strip():
            changed = True
        return replacement

    patched, count = pattern.subn(_repl, content, count=1)
    return patched, bool(changed and count > 0)


def _apply_mutation_profile(content: str, *, profile: str) -> tuple[str, bool, list[str]]:
    mutated: list[str] = []
    patched = content
    if profile == LE_PATCH_PROFILE_MUT_ELECTRICAL:
        mutations = [
            ("Re", "12.0", "ohm"),
            ("Le", "0.10", "mH"),
            ("ExpoRe", "1.4", ""),
            ("ExpoLe", "0.10", ""),
        ]
    elif profile == LE_PATCH_PROFILE_MUT_MOTOR:
        mutations = [
            ("Bl", "8.0", "N/A"),
            ("Mms", "120.0", "g"),
            ("Cms", "0.050e-3", "m/N"),
            ("Rms", "7.0", "Ns/m"),
        ]
    else:
        return patched, False, mutated

    changed_any = False
    for key, value, unit in mutations:
        patched_next, changed = _replace_first_param_value(
            patched,
            param=key,
            value_token=value,
            force_unit=unit,
        )
        if changed:
            mutated.append(key)
            changed_any = True
        patched = patched_next
    return patched, changed_any, mutated


def patch_driver_script_for_le_profile(
    *,
    script_path: str | Path,
    profile: Optional[str],
    driver_tag: str = "D1",
    drvgroup_value: str = "1001",
    voltage_vrms: float = 1.0,
) -> LeDriverScriptPatchResult:
    canonical = _normalize_le_patch_profile(profile)
    target = Path(str(script_path)).expanduser()
    try:
        target = target.resolve()
    except Exception:
        target = target.absolute()
    if not target.exists() or not target.is_file():
        return LeDriverScriptPatchResult(
            status="target_missing",
            profile=canonical,
            target_path=str(target),
            error="driver script target missing",
        )

    if canonical == LE_PATCH_PROFILE_BASELINE:
        return LeDriverScriptPatchResult(
            status="not_requested",
            profile=canonical,
            target_path=str(target),
            changed=False,
            driver_drvgroup_value=str(drvgroup_value),
            def_driving_value=f"{_format_voltage_vrms(voltage_vrms)}V",
            sha256_before=_sha256_file(target),
            sha256_after=_sha256_file(target),
        )

    if canonical not in {
        LE_PATCH_PROFILE_DRIVER_DRVGROUP,
        LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING,
        LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR,
        LE_PATCH_PROFILE_MUT_ELECTRICAL,
        LE_PATCH_PROFILE_MUT_MOTOR,
    }:
        return LeDriverScriptPatchResult(
            status="invalid_profile",
            profile=canonical,
            target_path=str(target),
            error=f"unsupported le patch profile: {canonical}",
        )

    newline = "\r\n"
    try:
        original = target.read_text(encoding="utf-8", errors="replace")
        before_hash = _sha256_file(target)
        newline = "\r\n" if "\r\n" in original else "\n"
        trailing_newline = original.endswith("\n") or original.endswith("\r\n")

        driver_changed = False
        def_driving_changed = False
        mutated_parameters: list[str] = []
        patched = original

        if canonical in {
            LE_PATCH_PROFILE_DRIVER_DRVGROUP,
            LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING,
            LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR,
            LE_PATCH_PROFILE_MUT_ELECTRICAL,
            LE_PATCH_PROFILE_MUT_MOTOR,
        }:
            patched, driver_changed, driver_found = _ensure_driver_drvgroup(
                patched,
                driver_tag=driver_tag,
                drvgroup_value=str(drvgroup_value),
            )
            if not driver_found:
                return LeDriverScriptPatchResult(
                    status="driver_not_found",
                    profile=canonical,
                    target_path=str(target),
                    driver_drvgroup_value=str(drvgroup_value),
                    def_driving_value=f"{_format_voltage_vrms(voltage_vrms)}V",
                    sha256_before=before_hash,
                    sha256_after=before_hash,
                    error=f"driver section '{driver_tag}' not found",
                )

        if canonical in {
            LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING,
            LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR,
            LE_PATCH_PROFILE_MUT_ELECTRICAL,
            LE_PATCH_PROFILE_MUT_MOTOR,
        }:
            patched, def_driving_changed = _ensure_def_driving(
                patched,
                voltage_vrms=float(voltage_vrms),
            )
        if canonical in {
            LE_PATCH_PROFILE_DRIVER_DRVGROUP_DEF_DRIVING_RESISTOR,
            LE_PATCH_PROFILE_MUT_ELECTRICAL,
            LE_PATCH_PROFILE_MUT_MOTOR,
        }:
            patched, system_changed = _ensure_system_resistor_and_driver_node(
                patched,
                driver_tag=driver_tag,
            )
            driver_changed = driver_changed or system_changed

        if canonical in {LE_PATCH_PROFILE_MUT_ELECTRICAL, LE_PATCH_PROFILE_MUT_MOTOR}:
            patched, mutation_changed, mutated_parameters = _apply_mutation_profile(
                patched,
                profile=canonical,
            )
            driver_changed = driver_changed or mutation_changed

        if newline == "\r\n":
            patched = patched.replace("\n", "\r\n")
        if trailing_newline and not patched.endswith(newline):
            patched += newline
        if not trailing_newline and patched.endswith(newline):
            patched = patched[: -len(newline)]

        changed = driver_changed or def_driving_changed
        if changed:
            target.write_text(patched, encoding="utf-8")
        after_hash = _sha256_file(target)
        return LeDriverScriptPatchResult(
            status="patched" if changed else "already_conformant",
            profile=canonical,
            target_path=str(target),
            changed=changed,
            driver_line_changed=driver_changed,
            def_driving_changed=def_driving_changed,
            driver_drvgroup_value=str(drvgroup_value),
            def_driving_value=f"{_format_voltage_vrms(voltage_vrms)}V",
            sha256_before=before_hash,
            sha256_after=after_hash,
            mutated_parameters=mutated_parameters,
        )
    except Exception as exc:
        return LeDriverScriptPatchResult(
            status="patch_failed",
            profile=canonical,
            target_path=str(target),
            error=str(exc),
        )


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
    source_override: str | Path | None = None,
) -> DriverScriptEnsureResult:
    abec_file = Path(str(abec_path)).expanduser()
    try:
        abec_file = abec_file.resolve()
    except Exception:
        abec_file = abec_file.absolute()

    if not abec_file.exists() or not abec_file.is_file():
        return DriverScriptEnsureResult(status="abec_missing", target_path=str(abec_file))

    source_path = Path(source_override).expanduser().resolve() if source_override else resolve_ath_driver_source_path(
        ath_executable, driver_basename=driver_basename,
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
    le_patch_profile: Optional[str] = None,
    le_driver_tag: str = "D1",
    le_drvgroup_value: str = "1001",
    le_voltage_vrms: float = 1.0,
    diagnostics_dir: str | Path | None = None,
    driver_source_override: str | Path | None = None,
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
        source_override=driver_source_override,
    )
    driver_patch_result = LeDriverScriptPatchResult(
        status="target_missing",
        profile=_normalize_le_patch_profile(le_patch_profile),
        target_path=None,
        error="driver script path unavailable",
    )
    if copy_result.target_path:
        driver_patch_result = patch_driver_script_for_le_profile(
            script_path=copy_result.target_path,
            profile=le_patch_profile,
            driver_tag=str(le_driver_tag or "D1"),
            drvgroup_value=str(le_drvgroup_value or "1001"),
            voltage_vrms=float(le_voltage_vrms),
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
                "driver_patch": driver_patch_result.to_dict(),
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
    elif not driver_patch_result.ok:
        failure = f"driver_patch_failed:{driver_patch_result.status}"
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
        driver_patch=driver_patch_result,
        patch=patch_result,
        diagnostics_path=diagnostics_path,
        before_snapshot_path=before_snapshot_path,
        after_snapshot_path=after_snapshot_path,
        error=failure,
    )
