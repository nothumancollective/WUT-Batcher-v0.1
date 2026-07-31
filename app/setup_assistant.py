"""License-aware discovery and opt-in installation for external WUT tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.settings_store import SettingsStore, UserSettings


ATH_DOWNLOAD_URL = "https://www.at-horns.eu/download.html"
AKABAK_DOWNLOAD_URL = "https://www.randteam.de/AKABAK3/Index.html"
VACS_DOWNLOAD_URL = "https://randteam.de/VACS/Index.html"
RND_LICENSE_URL = "https://randteam.de/Commercial/Licenses.html"
GMSH_DOWNLOAD_URL = "https://gmsh.info/"
GMSH_WINGET_ID = "gmsh.gmsh"


@dataclass(frozen=True)
class SetupToolStatus:
    key: str
    label: str
    found: bool
    path: Optional[str]
    source: str
    install_mode: str
    download_url: str
    license_summary: str
    required: bool = True
    configured_path: Optional[str] = None


@dataclass(frozen=True)
class SetupInspection:
    ready: bool
    tools: Tuple[SetupToolStatus, ...]
    winget_available: bool

    @property
    def missing_keys(self) -> List[str]:
        return [tool.key for tool in self.tools if tool.required and not tool.found]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ready": bool(self.ready),
            "missing_keys": self.missing_keys,
            "winget_available": bool(self.winget_available),
            "tools": [asdict(tool) for tool in self.tools],
        }


def _is_file(path: Optional[str | Path]) -> bool:
    if not path:
        return False
    try:
        candidate = Path(str(path)).expanduser()
        return candidate.exists() and candidate.is_file()
    except OSError:
        return False


def _unique_candidates(items: Iterable[Tuple[str, Optional[str | Path]]]) -> Iterable[Tuple[str, Path]]:
    seen: set[str] = set()
    for source, raw in items:
        if not raw:
            continue
        try:
            candidate = Path(str(raw)).expanduser()
            token = os.path.normcase(str(candidate.absolute()))
        except (OSError, ValueError):
            continue
        if token in seen:
            continue
        seen.add(token)
        yield source, candidate


def _program_dir_candidates(*parts: str) -> List[Path]:
    roots = [
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
        r"C:\Program Files",
        r"C:\Program Files (x86)",
    ]
    return [Path(root).joinpath(*parts) for root in roots if root]


def discover_tool_path(
    key: str,
    *,
    configured_path: Optional[str] = None,
    ath_executable: Optional[str] = None,
) -> Tuple[Optional[str], str]:
    """Return an existing executable and the discovery source.

    Valid explicit configuration always wins. Known locations and PATH are used
    only when the configured path is empty or stale.
    """

    token = str(key or "").strip().lower()
    candidates: List[Tuple[str, Optional[str | Path]]] = [("configured", configured_path)]

    which_names: Sequence[str]
    if token == "ath":
        which_names = ("ath.exe", "ath")
        candidates.extend(
            [("known_location", r"C:\Tools\ATH\ath.exe")]
            + [("known_location", path) for path in _program_dir_candidates("ATH", "ath.exe")]
        )
    elif token == "akabak":
        which_names = ("AKABAK.exe", "akabak")
        candidates.extend(
            [("known_location", path) for path in _program_dir_candidates("RDTeam", "AKABAK", "AKABAK.exe")]
        )
    elif token == "vacs":
        which_names = ("VACSVIEWER_32.exe", "VACS.exe", "vacs")
        candidates.extend(
            [("known_location", path) for path in _program_dir_candidates("RDTeam", "VACSVIEWER_32", "VACSVIEWER_32.exe")]
        )
    elif token == "gmsh":
        which_names = ("gmsh.exe", "gmsh")
        if ath_executable:
            candidates.append(("ath_sibling", Path(str(ath_executable)).expanduser().parent / "gmsh.exe"))
        candidates.extend(
            [("known_location", path) for path in _program_dir_candidates("gmsh", "gmsh.exe")]
        )
    else:
        raise ValueError(f"Unsupported setup tool: {key}")

    for name in which_names:
        candidates.append(("path", shutil.which(name)))

    for source, candidate in _unique_candidates(candidates):
        if _is_file(candidate):
            try:
                return str(candidate.resolve()), source
            except OSError:
                return str(candidate), source
    return None, "missing"


def inspect_setup(settings: UserSettings) -> SetupInspection:
    ath_path, ath_source = discover_tool_path("ath", configured_path=settings.ath_exe)
    akabak_path, akabak_source = discover_tool_path("akabak", configured_path=settings.akabak_exe)
    vacs_path, vacs_source = discover_tool_path("vacs", configured_path=settings.vacs_exe)
    gmsh_path, gmsh_source = discover_tool_path("gmsh", ath_executable=ath_path or settings.ath_exe)

    tools = (
        SetupToolStatus(
            key="ath",
            label="ATH",
            found=bool(ath_path),
            path=ath_path,
            source=ath_source,
            install_mode="manual",
            download_url=ATH_DOWNLOAD_URL,
            license_summary="Freeware for personal, non-commercial use; commercial license on request.",
            configured_path=settings.ath_exe,
        ),
        SetupToolStatus(
            key="akabak",
            label="AKABAK",
            found=bool(akabak_path),
            path=akabak_path,
            source=akabak_source,
            install_mode="manual",
            download_url=AKABAK_DOWNLOAD_URL,
            license_summary="Demo/free use has result-saving limits; commercial product development requires a license.",
            configured_path=settings.akabak_exe,
        ),
        SetupToolStatus(
            key="vacs",
            label="VacsViewer / VACS",
            found=bool(vacs_path),
            path=vacs_path,
            source=vacs_source,
            install_mode="manual",
            download_url=VACS_DOWNLOAD_URL,
            license_summary="VacsViewer cannot save project files; commercial product development requires a license.",
            configured_path=settings.vacs_exe,
        ),
        SetupToolStatus(
            key="gmsh",
            label="Gmsh",
            found=bool(gmsh_path),
            path=gmsh_path,
            source=gmsh_source,
            install_mode="winget_opt_in",
            download_url=GMSH_DOWNLOAD_URL,
            license_summary="Open source under GNU GPL v2 or later (with the documented linking exception).",
        ),
    )
    return SetupInspection(
        ready=all(tool.found for tool in tools if tool.required),
        tools=tools,
        winget_available=bool(shutil.which("winget")),
    )


def autoconfigure_detected_tools(settings_store: SettingsStore) -> Dict[str, Any]:
    """Persist detected proprietary tool paths without replacing valid paths."""

    settings = settings_store.load()
    inspection = inspect_setup(settings)
    updates: Dict[str, str] = {}
    by_key = {tool.key: tool for tool in inspection.tools}
    for key, field_name in (("ath", "ath_exe"), ("akabak", "akabak_exe"), ("vacs", "vacs_exe")):
        current = getattr(settings, field_name)
        detected = by_key[key].path
        if _is_file(current) or not detected:
            continue
        updates[field_name] = detected

    if updates:
        settings_store.save(replace(settings, **updates))
    refreshed = inspect_setup(settings_store.load())
    return {
        "changed": bool(updates),
        "updated_fields": updates,
        "inspection": refreshed.to_dict(),
    }


def install_gmsh_with_winget(*, confirmed: bool, timeout_seconds: int = 600) -> Dict[str, Any]:
    """Install Gmsh only after an explicit caller confirmation.

    WUT never downloads or installs ATH, AKABAK or VACS; their license terms and
    official download workflows require a manual user decision.
    """

    existing, source = discover_tool_path("gmsh")
    if existing:
        return {"status": "already_installed", "path": existing, "source": source}
    if not confirmed:
        return {
            "status": "confirmation_required",
            "message": "Explicit confirmation is required before installing Gmsh.",
        }
    winget = shutil.which("winget")
    if not winget:
        return {
            "status": "winget_unavailable",
            "message": f"Open the official download page: {GMSH_DOWNLOAD_URL}",
        }

    command = [
        winget,
        "install",
        "--id",
        GMSH_WINGET_ID,
        "--exact",
        "--source",
        "winget",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(int(timeout_seconds), 30),
            check=False,
            creationflags=(int(getattr(subprocess, "CREATE_NO_WINDOW", 0)) if os.name == "nt" else 0),
        )
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "message": "Gmsh installation did not finish within the time limit."}

    path, source = discover_tool_path("gmsh")
    return {
        "status": "installed" if result.returncode == 0 and path else "failed",
        "returncode": int(result.returncode),
        "path": path,
        "source": source,
        "stdout": str(result.stdout or "")[-4000:],
        "stderr": str(result.stderr or "")[-4000:],
    }
