"""Persistent user settings for GUI orchestration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


def _default_library_root() -> str:
    return str((Path.home() / "Documents" / "WUT-Batches" / "Projects").resolve())


def _default_settings_path() -> Path:
    return Path.home() / ".wut_batcher" / "config.json"


SIMULATION_TIMEOUT_MINUTES_DEFAULT = 10
SIMULATION_TIMEOUT_MINUTES_MIN = 1
SIMULATION_TIMEOUT_MINUTES_MAX = 240
ANALYZER_DISPLAY_SHOW_GOOD_BAND_DEFAULT = True
ANALYZER_DISPLAY_SHOW_WARN_BAND_DEFAULT = False
ANALYZER_DISPLAY_SHOW_BAD_BAND_DEFAULT = False
ANALYZER_DISPLAY_SHOW_WARN_LINE_DEFAULT = True
ANALYZER_DISPLAY_SHOW_BAD_LINE_DEFAULT = False
ANALYZER_DISPLAY_COLOR_GOOD_DEFAULT = "#6E8FA7"
ANALYZER_DISPLAY_COLOR_WARN_DEFAULT = "#7B90A3"
ANALYZER_DISPLAY_COLOR_BAD_DEFAULT = "#8D98A7"
ANALYZER_DISPLAY_HIGH_CONTRAST_PLOTS_DEFAULT = True


_HEX_RGB_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def _as_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _as_int(value: object, *, default: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except Exception:
        return int(default)


def _as_hex_rgb(value: object, *, default: str) -> str:
    text = str(value or "").strip()
    if _HEX_RGB_RE.match(text):
        return text.upper()
    return str(default).upper()


@dataclass
class UserSettings:
    library_root: str = _default_library_root()
    ath_exe: Optional[str] = None
    akabak_exe: Optional[str] = None
    vacs_exe: Optional[str] = None
    template_cfg: Optional[str] = None
    background_automation_mode: bool = True
    simulation_timeout_minutes: int = SIMULATION_TIMEOUT_MINUTES_DEFAULT
    analyzer_data_source: str = "project"
    analyzer_cache_mode: str = "balanced"
    analyzer_cache_limit_mb: int = 240
    analyzer_cache_keep_last_n: int = 5
    analyzer_display_show_good_band: bool = ANALYZER_DISPLAY_SHOW_GOOD_BAND_DEFAULT
    analyzer_display_show_warn_band: bool = ANALYZER_DISPLAY_SHOW_WARN_BAND_DEFAULT
    analyzer_display_show_bad_band: bool = ANALYZER_DISPLAY_SHOW_BAD_BAND_DEFAULT
    analyzer_display_show_warn_line: bool = ANALYZER_DISPLAY_SHOW_WARN_LINE_DEFAULT
    analyzer_display_show_bad_line: bool = ANALYZER_DISPLAY_SHOW_BAD_LINE_DEFAULT
    analyzer_display_color_good: str = ANALYZER_DISPLAY_COLOR_GOOD_DEFAULT
    analyzer_display_color_warn: str = ANALYZER_DISPLAY_COLOR_WARN_DEFAULT
    analyzer_display_color_bad: str = ANALYZER_DISPLAY_COLOR_BAD_DEFAULT
    analyzer_display_high_contrast_plots: bool = ANALYZER_DISPLAY_HIGH_CONTRAST_PLOTS_DEFAULT

    def to_dict(self) -> Dict[str, object]:
        return {
            "library_root": self.library_root,
            "ath_exe": self.ath_exe,
            "akabak_exe": self.akabak_exe,
            "vacs_exe": self.vacs_exe,
            "template_cfg": self.template_cfg,
            "background_automation_mode": bool(self.background_automation_mode),
            "simulation_timeout_minutes": int(self.simulation_timeout_minutes),
            "analyzer_data_source": str(self.analyzer_data_source or "project"),
            "analyzer_cache_mode": str(self.analyzer_cache_mode or "balanced"),
            "analyzer_cache_limit_mb": int(self.analyzer_cache_limit_mb),
            "analyzer_cache_keep_last_n": int(self.analyzer_cache_keep_last_n),
            "analyzer_display_show_good_band": bool(self.analyzer_display_show_good_band),
            "analyzer_display_show_warn_band": bool(self.analyzer_display_show_warn_band),
            "analyzer_display_show_bad_band": bool(self.analyzer_display_show_bad_band),
            "analyzer_display_show_warn_line": bool(self.analyzer_display_show_warn_line),
            "analyzer_display_show_bad_line": bool(self.analyzer_display_show_bad_line),
            "analyzer_display_color_good": _as_hex_rgb(
                self.analyzer_display_color_good,
                default=ANALYZER_DISPLAY_COLOR_GOOD_DEFAULT,
            ),
            "analyzer_display_color_warn": _as_hex_rgb(
                self.analyzer_display_color_warn,
                default=ANALYZER_DISPLAY_COLOR_WARN_DEFAULT,
            ),
            "analyzer_display_color_bad": _as_hex_rgb(
                self.analyzer_display_color_bad,
                default=ANALYZER_DISPLAY_COLOR_BAD_DEFAULT,
            ),
            "analyzer_display_high_contrast_plots": bool(self.analyzer_display_high_contrast_plots),
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "UserSettings":
        mode = str(payload.get("analyzer_cache_mode", "balanced") or "balanced").strip().lower()
        if mode not in {"low", "balanced", "high", "extreme", "custom"}:
            mode = "balanced"
        source = str(payload.get("analyzer_data_source", "project") or "project").strip().lower()
        if source not in {"project", "global"}:
            source = "project"
        limit_mb = max(min(_as_int(payload.get("analyzer_cache_limit_mb"), default=240), 10 * 1024), 0)
        keep_last_n = max(min(_as_int(payload.get("analyzer_cache_keep_last_n"), default=5), 200), 1)
        analyzer_display_show_good_band = _as_bool(
            payload.get("analyzer_display_show_good_band"),
            default=ANALYZER_DISPLAY_SHOW_GOOD_BAND_DEFAULT,
        )
        analyzer_display_show_warn_band = _as_bool(
            payload.get("analyzer_display_show_warn_band"),
            default=ANALYZER_DISPLAY_SHOW_WARN_BAND_DEFAULT,
        )
        analyzer_display_show_bad_band = _as_bool(
            payload.get("analyzer_display_show_bad_band"),
            default=ANALYZER_DISPLAY_SHOW_BAD_BAND_DEFAULT,
        )
        analyzer_display_show_warn_line = _as_bool(
            payload.get("analyzer_display_show_warn_line"),
            default=ANALYZER_DISPLAY_SHOW_WARN_LINE_DEFAULT,
        )
        analyzer_display_show_bad_line = _as_bool(
            payload.get("analyzer_display_show_bad_line"),
            default=ANALYZER_DISPLAY_SHOW_BAD_LINE_DEFAULT,
        )
        analyzer_display_color_good = _as_hex_rgb(
            payload.get("analyzer_display_color_good"),
            default=ANALYZER_DISPLAY_COLOR_GOOD_DEFAULT,
        )
        analyzer_display_color_warn = _as_hex_rgb(
            payload.get("analyzer_display_color_warn"),
            default=ANALYZER_DISPLAY_COLOR_WARN_DEFAULT,
        )
        analyzer_display_color_bad = _as_hex_rgb(
            payload.get("analyzer_display_color_bad"),
            default=ANALYZER_DISPLAY_COLOR_BAD_DEFAULT,
        )
        analyzer_display_high_contrast_plots = _as_bool(
            payload.get("analyzer_display_high_contrast_plots"),
            default=ANALYZER_DISPLAY_HIGH_CONTRAST_PLOTS_DEFAULT,
        )
        simulation_timeout_minutes = max(
            min(
                _as_int(payload.get("simulation_timeout_minutes"), default=SIMULATION_TIMEOUT_MINUTES_DEFAULT),
                SIMULATION_TIMEOUT_MINUTES_MAX,
            ),
            SIMULATION_TIMEOUT_MINUTES_MIN,
        )
        return cls(
            library_root=str(payload.get("library_root", _default_library_root())),
            ath_exe=str(payload["ath_exe"]) if payload.get("ath_exe") else None,
            akabak_exe=str(payload["akabak_exe"]) if payload.get("akabak_exe") else None,
            vacs_exe=str(payload["vacs_exe"]) if payload.get("vacs_exe") else None,
            template_cfg=str(payload["template_cfg"]) if payload.get("template_cfg") else None,
            background_automation_mode=_as_bool(payload.get("background_automation_mode"), default=True),
            simulation_timeout_minutes=simulation_timeout_minutes,
            analyzer_data_source=source,
            analyzer_cache_mode=mode,
            analyzer_cache_limit_mb=limit_mb,
            analyzer_cache_keep_last_n=keep_last_n,
            analyzer_display_show_good_band=analyzer_display_show_good_band,
            analyzer_display_show_warn_band=analyzer_display_show_warn_band,
            analyzer_display_show_bad_band=analyzer_display_show_bad_band,
            analyzer_display_show_warn_line=analyzer_display_show_warn_line,
            analyzer_display_show_bad_line=analyzer_display_show_bad_line,
            analyzer_display_color_good=analyzer_display_color_good,
            analyzer_display_color_warn=analyzer_display_color_warn,
            analyzer_display_color_bad=analyzer_display_color_bad,
            analyzer_display_high_contrast_plots=analyzer_display_high_contrast_plots,
        )


class SettingsStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else _default_settings_path()

    def load(self) -> UserSettings:
        if not self.path.exists():
            return UserSettings()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return UserSettings()
        if not isinstance(payload, dict):
            return UserSettings()
        return UserSettings.from_dict(payload)

    def save(self, settings: UserSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def validate(self, settings: UserSettings) -> Dict[str, str]:
        issues: Dict[str, str] = {}
        library_path = Path(settings.library_root).expanduser()
        if not library_path.exists():
            issues["library_root"] = "Library folder does not exist."
        elif not library_path.is_dir():
            issues["library_root"] = "Library path is not a directory."

        for key in ("ath_exe", "akabak_exe", "vacs_exe", "template_cfg"):
            value = getattr(settings, key)
            if not value:
                continue
            path = Path(value).expanduser()
            if not path.exists():
                issues[key] = f"Configured path not found: {path}"

        if str(settings.analyzer_cache_mode or "").strip().lower() not in {"low", "balanced", "high", "extreme", "custom"}:
            issues["analyzer_cache_mode"] = "Invalid analyzer cache mode."
        if str(settings.analyzer_data_source or "").strip().lower() not in {"project", "global"}:
            issues["analyzer_data_source"] = "Analyzer data source must be project or global."
        if int(settings.analyzer_cache_limit_mb) < 0:
            issues["analyzer_cache_limit_mb"] = "Analyzer cache limit must be >= 0 MB."
        if int(settings.analyzer_cache_limit_mb) > 10 * 1024:
            issues["analyzer_cache_limit_mb"] = "Analyzer cache limit must be <= 10240 MB (10 GB)."
        if int(settings.analyzer_cache_keep_last_n) < 1:
            issues["analyzer_cache_keep_last_n"] = "Analyzer cache keep-last must be >= 1."
        if not _HEX_RGB_RE.match(str(settings.analyzer_display_color_good or "").strip()):
            issues["analyzer_display_color_good"] = "Analyzer good-band color must be #RRGGBB."
        if not _HEX_RGB_RE.match(str(settings.analyzer_display_color_warn or "").strip()):
            issues["analyzer_display_color_warn"] = "Analyzer warn-band color must be #RRGGBB."
        if not _HEX_RGB_RE.match(str(settings.analyzer_display_color_bad or "").strip()):
            issues["analyzer_display_color_bad"] = "Analyzer bad-band color must be #RRGGBB."
        timeout_minutes = int(settings.simulation_timeout_minutes)
        if timeout_minutes < SIMULATION_TIMEOUT_MINUTES_MIN:
            issues["simulation_timeout_minutes"] = (
                f"Simulation timeout must be >= {SIMULATION_TIMEOUT_MINUTES_MIN} minute."
            )
        if timeout_minutes > SIMULATION_TIMEOUT_MINUTES_MAX:
            issues["simulation_timeout_minutes"] = (
                f"Simulation timeout must be <= {SIMULATION_TIMEOUT_MINUTES_MAX} minutes."
            )

        return issues
