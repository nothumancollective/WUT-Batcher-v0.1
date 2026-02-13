"""Persistent user settings for GUI orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


def _default_library_root() -> str:
    return str((Path.home() / "Documents" / "WUT-Batches" / "Projects").resolve())


def _default_settings_path() -> Path:
    return Path.home() / ".wut_batcher" / "config.json"


@dataclass
class UserSettings:
    library_root: str = _default_library_root()
    ath_exe: Optional[str] = None
    akabak_exe: Optional[str] = None
    vacs_exe: Optional[str] = None
    template_cfg: Optional[str] = None

    def to_dict(self) -> Dict[str, object]:
        return {
            "library_root": self.library_root,
            "ath_exe": self.ath_exe,
            "akabak_exe": self.akabak_exe,
            "vacs_exe": self.vacs_exe,
            "template_cfg": self.template_cfg,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, object]) -> "UserSettings":
        return cls(
            library_root=str(payload.get("library_root", _default_library_root())),
            ath_exe=str(payload["ath_exe"]) if payload.get("ath_exe") else None,
            akabak_exe=str(payload["akabak_exe"]) if payload.get("akabak_exe") else None,
            vacs_exe=str(payload["vacs_exe"]) if payload.get("vacs_exe") else None,
            template_cfg=str(payload["template_cfg"]) if payload.get("template_cfg") else None,
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

        return issues
