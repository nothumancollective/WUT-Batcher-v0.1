"""Discovery helpers for AKABAK/VACS UI Automation maps."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict

from app.ui_automation.session import UiaSession, UiaSessionError


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def inspect_tool_ui(
    *,
    tool_name: str,
    executable: str | Path,
    output_root: str | Path = "ui_maps",
    startup_timeout_s: int = 20,
    dry_run: bool = False,
) -> Dict[str, Any]:
    tool_slug = str(tool_name).strip().lower()
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = _now_stamp()
    summary_path = output_dir / f"{tool_slug}_inspect_{stamp}.json"
    tree_txt_path = output_dir / f"{tool_slug}_uia_tree_{stamp}.txt"
    tree_json_path = output_dir / f"{tool_slug}_uia_tree_{stamp}.json"

    if dry_run:
        payload = {
            "tool": tool_slug,
            "dry_run": True,
            "executable": str(executable),
            "output_root": str(output_dir),
            "summary_path": str(summary_path),
            "tree_txt_path": str(tree_txt_path),
            "tree_json_path": str(tree_json_path),
        }
        summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return payload

    session = UiaSession(
        executable=executable,
        app_name=tool_slug,
        startup_timeout_s=startup_timeout_s,
        allow_fallback=True,
    )
    try:
        session.connect_or_start()
        windows = [item.to_dict() for item in session.list_top_windows()]
        tree_dump = session.dump_tree(
            output_txt=tree_txt_path,
            output_json=tree_json_path,
            max_depth=4,
        )
        payload = {
            "tool": tool_slug,
            "dry_run": False,
            "backend": session.backend,
            "executable": str(executable),
            "process_id": session.process_id,
            "window_count": len(windows),
            "windows": windows,
            "tree_dump": tree_dump,
            "summary_path": str(summary_path),
        }
    except UiaSessionError as exc:
        payload = {
            "tool": tool_slug,
            "dry_run": False,
            "error": str(exc),
            "executable": str(executable),
            "summary_path": str(summary_path),
        }
    finally:
        session.close()

    summary_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload
