"""Parser utilities for VACS TXT graph exports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple


NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][-+]?\d+)?")
RESULT_GRAPH_RE = re.compile(r"(?i)^Result_(?:V\d+)?_?([A-Za-z][A-Za-z0-9_-]*)$")


@dataclass(frozen=True)
class VacsGraph:
    graph_type: str
    x_name: str
    y_name: str
    x_unit: str
    y_unit: str
    points: List[Tuple[float, float]]
    export_meta: Dict[str, Any]


def _strip_quotes(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) >= 2:
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (
            cleaned.startswith("'") and cleaned.endswith("'")
        ):
            return cleaned[1:-1]
    return cleaned


def _parse_decimal(token: str) -> Optional[float]:
    cleaned = token.strip().replace(" ", "")
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _split_header_tokens(line: str) -> List[str]:
    if ";" in line:
        parts = [part.strip() for part in line.split(";")]
    elif "\t" in line:
        parts = [part.strip() for part in line.split("\t")]
    elif "|" in line:
        parts = [part.strip() for part in line.split("|")]
    else:
        parts = [part.strip() for part in re.split(r"\s{2,}", line)]
    return [part for part in parts if part]


def _axis_from_token(token: str) -> Tuple[str, str]:
    match = re.match(r"^\s*(.*?)\s*(?:\[(.*?)\])?\s*$", token)
    if not match:
        cleaned = token.strip()
        return (cleaned or "value", "")
    name = (match.group(1) or "").strip() or "value"
    unit = (match.group(2) or "").strip()
    return name, unit


def _infer_graph_type(path: Path, metadata: Dict[str, str], default_graph_type: Optional[str]) -> str:
    lower_map = {key.lower(): value for key, value in metadata.items()}
    for key in ("graph_type", "graphtype", "data_legend", "curve_type", "curvetype"):
        value = lower_map.get(key)
        if value:
            return str(value)
    match = RESULT_GRAPH_RE.match(path.stem)
    if match:
        return match.group(1).upper()
    if default_graph_type:
        return default_graph_type
    return path.stem


def _pick_meta(metadata: Dict[str, str], keys: List[str]) -> str:
    lower_map = {key.lower(): value for key, value in metadata.items()}
    for key in keys:
        value = lower_map.get(key.lower())
        if value:
            return str(value)
    return ""


def parse_vacs_txt_file(path: str | Path, *, default_graph_type: Optional[str] = None) -> VacsGraph:
    source_path = Path(path)
    lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()

    metadata: Dict[str, str] = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key:
            metadata[key] = _strip_quotes(value)

    start_token = metadata.get("StartString_Data", "Data")
    end_token = metadata.get("EndString_Data", "Data_End")
    has_explicit_data_markers = any(line.strip() == start_token for line in lines)

    data_started = not has_explicit_data_markers
    header_tokens: List[str] = []
    points: List[Tuple[float, float]] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped == start_token:
            data_started = True
            continue
        if data_started and stripped == end_token:
            break
        if not data_started:
            continue
        if stripped.startswith(("#", ";")):
            continue
        if "=" in stripped and NUMBER_RE.search(stripped) is None:
            continue

        numbers = NUMBER_RE.findall(stripped)
        if len(numbers) >= 2:
            x = _parse_decimal(numbers[0])
            y = _parse_decimal(numbers[1])
            if x is not None and y is not None:
                points.append((x, y))
            continue

        if not header_tokens and re.search(r"[A-Za-z]", stripped):
            header_tokens = _split_header_tokens(stripped)

    if not points:
        raise ValueError(f"No numeric graph points found in VACS export: {source_path}")

    x_name = _pick_meta(metadata, ["x_name", "xname", "data_x_name", "data_xname", "data_abscissa_name"]) or "x"
    y_name = _pick_meta(metadata, ["y_name", "yname", "data_y_name", "data_yname", "data_legend"]) or "y"
    x_unit = _pick_meta(metadata, ["x_unit", "xunit", "data_x_unit", "data_xunit"]) or ""
    y_unit = _pick_meta(metadata, ["y_unit", "yunit", "data_baseunit", "data_y_unit", "data_yunit"]) or ""

    if len(header_tokens) >= 2:
        header_x_name, header_x_unit = _axis_from_token(header_tokens[0])
        header_y_name, header_y_unit = _axis_from_token(header_tokens[1])
        if x_name == "x":
            x_name = header_x_name
        if y_name == "y":
            y_name = header_y_name
        if not x_unit:
            x_unit = header_x_unit
        if not y_unit:
            y_unit = header_y_unit

    graph_type = _infer_graph_type(source_path, metadata, default_graph_type)
    export_meta: Dict[str, Any] = {
        "metadata": metadata,
        "point_count": len(points),
        "source_file": str(source_path),
    }

    return VacsGraph(
        graph_type=graph_type,
        x_name=x_name,
        y_name=y_name,
        x_unit=x_unit,
        y_unit=y_unit,
        points=points,
        export_meta=export_meta,
    )
