"""Runner test workspace layout helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass(frozen=True)
class RunnerTestWorkspace:
    root: Path
    cfg_dir: Path
    ath_out_dir: Path
    exports_dir: Path
    logs_dir: Path
    db_dir: Path
    db_path: Path

    def to_dict(self) -> Dict[str, str]:
        return {
            "root": str(self.root),
            "cfg_dir": str(self.cfg_dir),
            "ath_out_dir": str(self.ath_out_dir),
            "exports_dir": str(self.exports_dir),
            "logs_dir": str(self.logs_dir),
            "db_dir": str(self.db_dir),
            "db_path": str(self.db_path),
        }


def resolve_runner_test_workspace(root: str | Path = "runner_test_workspace") -> RunnerTestWorkspace:
    root_path = Path(root).expanduser()
    if not root_path.is_absolute():
        root_path = (Path.cwd() / root_path).resolve()
    else:
        root_path = root_path.resolve()

    cfg_dir = root_path / "cfg"
    ath_out_dir = root_path / "ath_out"
    exports_dir = root_path / "exports"
    logs_dir = root_path / "logs"
    db_dir = root_path / "db"
    db_path = db_dir / "runner_test.sqlite"

    for path in (root_path, cfg_dir, ath_out_dir, exports_dir, logs_dir, db_dir):
        path.mkdir(parents=True, exist_ok=True)

    return RunnerTestWorkspace(
        root=root_path,
        cfg_dir=cfg_dir,
        ath_out_dir=ath_out_dir,
        exports_dir=exports_dir,
        logs_dir=logs_dir,
        db_dir=db_dir,
        db_path=db_path,
    )
