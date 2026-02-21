from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Dict, List, Optional


NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][-+]?\d+)?")


class PolarTxtParseError(ValueError):
    def __init__(self, *, path: Path, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


@dataclass(frozen=True)
class PolarMatrixRow:
    freq_hz: float
    re_values: List[float]
    im_values: List[float]


@dataclass(frozen=True)
class PolarMatrixData:
    path: Path
    metadata: Dict[str, str]
    angles_deg: List[float]
    orientation_raw: Optional[float]
    rows: List[PolarMatrixRow]
    warnings: List[str]

    @property
    def freq_values(self) -> List[float]:
        return [row.freq_hz for row in self.rows]


def _strip_quotes(value: str) -> str:
    cleaned = str(value or "").strip()
    if len(cleaned) >= 2:
        if (cleaned.startswith('"') and cleaned.endswith('"')) or (
            cleaned.startswith("'") and cleaned.endswith("'")
        ):
            return cleaned[1:-1]
    return cleaned


def _parse_decimal(token: str) -> Optional[float]:
    cleaned = str(token or "").strip().replace(" ", "")
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


def _parse_metadata(lines: List[str]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for line in lines:
        stripped = str(line or "").strip()
        if not stripped or stripped.startswith(("#", ";")):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key:
            metadata[key] = _strip_quotes(value)
    return metadata


def _parse_angle_list(path: Path, value: str) -> List[float]:
    tokens = [item.strip() for item in str(value or "").split(",")]
    angles: List[float] = []
    for token in tokens:
        if not token:
            continue
        parsed = _parse_decimal(token)
        if parsed is None:
            raise PolarTxtParseError(path=path, reason=f"invalid Param_Coord_x2 angle token '{token}'")
        angles.append(float(parsed))
    if not angles:
        raise PolarTxtParseError(path=path, reason="Param_Coord_x2 does not contain any angle bins")
    return angles


def _read_data_block(path: Path, lines: List[str], *, start_token: str, end_token: str) -> List[str]:
    started = False
    rows: List[str] = []
    for line in lines:
        stripped = str(line or "").strip()
        if not started:
            if stripped == start_token:
                started = True
            continue
        if stripped == end_token:
            break
        if not stripped or stripped.startswith(("#", ";")):
            continue
        rows.append(line)
    if not started:
        raise PolarTxtParseError(path=path, reason=f"missing data start marker '{start_token}'")
    if not rows:
        raise PolarTxtParseError(path=path, reason="data block is empty")
    return rows


def parse_polar_legacy_complex_txt(path: str | Path) -> PolarMatrixData:
    source_path = Path(path)
    lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    metadata = _parse_metadata(lines)
    data_format = str(metadata.get("Data_Format", "") or "").strip().lower()
    if data_format and data_format != "complex":
        raise PolarTxtParseError(path=source_path, reason=f"unsupported Data_Format '{metadata.get('Data_Format')}'")

    angles_raw = metadata.get("Param_Coord_x2")
    if not angles_raw:
        raise PolarTxtParseError(path=source_path, reason="missing Param_Coord_x2 header")
    angles_deg = _parse_angle_list(source_path, angles_raw)
    angle_count = len(angles_deg)
    if angle_count < 1:
        raise PolarTxtParseError(path=source_path, reason="angle_count must be >= 1")

    orientation_raw: Optional[float] = None
    if "Param_Coord_x3" in metadata:
        orientation_raw = _parse_decimal(metadata.get("Param_Coord_x3", ""))
        if orientation_raw is None:
            raise PolarTxtParseError(path=source_path, reason="Param_Coord_x3 is not numeric")

    start_token = metadata.get("StartString_Data", "Data")
    end_token = metadata.get("EndString_Data", "Data_End")
    data_rows = _read_data_block(source_path, lines, start_token=start_token, end_token=end_token)

    expected_width = 1 + (2 * angle_count)
    rows: List[PolarMatrixRow] = []
    warnings: List[str] = []
    prev_freq: Optional[float] = None
    for idx, raw_line in enumerate(data_rows):
        tokens = NUMBER_RE.findall(str(raw_line or ""))
        values: List[float] = []
        for token in tokens:
            parsed = _parse_decimal(token)
            if parsed is None:
                raise PolarTxtParseError(
                    path=source_path,
                    reason=f"line {idx + 1} in data block has non-numeric token '{token}'",
                )
            values.append(float(parsed))
        if len(values) != expected_width:
            raise PolarTxtParseError(
                path=source_path,
                reason=(
                    f"line {idx + 1} has width {len(values)}; expected {expected_width} "
                    f"(1 + 2*angle_count)"
                ),
            )
        freq = float(values[0])
        if prev_freq is not None and freq < prev_freq:
            warnings.append(
                f"frequency decreased at row {idx + 1}: prev={prev_freq:g}, current={freq:g}"
            )
        prev_freq = freq
        complex_values = values[1:]
        rows.append(
            PolarMatrixRow(
                freq_hz=freq,
                re_values=[float(item) for item in complex_values[0::2]],
                im_values=[float(item) for item in complex_values[1::2]],
            )
        )

    if not rows:
        raise PolarTxtParseError(path=source_path, reason="freq_count must be >= 1")

    return PolarMatrixData(
        path=source_path,
        metadata=metadata,
        angles_deg=angles_deg,
        orientation_raw=orientation_raw,
        rows=rows,
        warnings=warnings,
    )


def normalize_orientation_marker(value: Optional[float]) -> str:
    if value is None:
        return "X3_UNKNOWN"

    numeric = float(value)
    if abs(numeric - 0.0) <= 1e-6:
        return "H"
    if abs(numeric - 90.0) <= 1e-6:
        return "V"
    if abs(numeric - 42.0) <= 1e-6:
        return "D"
    if abs(numeric - round(numeric)) <= 1e-6:
        return f"X3_{int(round(numeric))}"
    token = f"{numeric:.6f}".rstrip("0").rstrip(".")
    return f"X3_{token}"
