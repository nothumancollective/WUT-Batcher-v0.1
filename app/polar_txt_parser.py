from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Dict, List, Optional


NUMBER_RE = re.compile(r"[-+]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][-+]?\d+)?")
NAN_INF_RE = re.compile(r"\b(?:nan|inf|infinity)\b", re.IGNORECASE)

ERROR_MISSING_HEADER = "MISSING_HEADER"
ERROR_BAD_DIMENSIONS = "BAD_DIMENSIONS"
ERROR_UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
ERROR_INVALID_NUMERIC = "INVALID_NUMERIC"


class PolarTxtParseError(ValueError):
    def __init__(
        self,
        *,
        path: Path,
        error_code: str,
        reason: str,
        detail: str = "",
    ) -> None:
        self.path = Path(path)
        self.file_path = str(self.path)
        self.error_code = str(error_code)
        self.reason = reason
        self.detail = str(detail or "")
        message = f"{self.path}: [{self.error_code}] {self.reason}"
        if self.detail:
            message = f"{message} ({self.detail})"
        super().__init__(message)


def _raise_parse(path: Path, *, error_code: str, reason: str, detail: str = "") -> None:
    raise PolarTxtParseError(path=path, error_code=error_code, reason=reason, detail=detail)


@dataclass(frozen=True)
class PolarMatrixRow:
    freq_hz: float
    re_values: List[float]
    im_values: List[float]


@dataclass(frozen=True)
class PolarMatrixData:
    path: Path
    metadata: Dict[str, str]
    format_type: str
    angles_deg: List[float]
    orientation_raw: float
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
            _raise_parse(
                path,
                error_code=ERROR_INVALID_NUMERIC,
                reason="invalid Param_Coord_x2 angle token",
                detail=f"token='{token}'",
            )
        if not math.isfinite(float(parsed)):
            _raise_parse(
                path,
                error_code=ERROR_INVALID_NUMERIC,
                reason="non-finite Param_Coord_x2 angle token",
                detail=f"token='{token}'",
            )
        angles.append(float(parsed))
    if not angles:
        _raise_parse(
            path,
            error_code=ERROR_BAD_DIMENSIONS,
            reason="Param_Coord_x2 does not contain any angle bins",
        )
    return angles


def _read_data_block(
    path: Path,
    lines: List[str],
    *,
    start_token: str,
    end_token: str,
    block_name: str,
) -> List[str]:
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
        _raise_parse(
            path,
            error_code=ERROR_UNSUPPORTED_FORMAT,
            reason=f"missing {block_name} start marker",
            detail=f"start_token='{start_token}'",
        )
    if not rows:
        _raise_parse(
            path,
            error_code=ERROR_BAD_DIMENSIONS,
            reason=f"{block_name} block is empty",
            detail=f"start_token='{start_token}', end_token='{end_token}'",
        )
    return rows


def _parse_numeric_row(path: Path, *, row_label: str, row_index: int, raw_line: str) -> List[float]:
    if NAN_INF_RE.search(str(raw_line or "")):
        _raise_parse(
            path,
            error_code=ERROR_INVALID_NUMERIC,
            reason=f"{row_label} row contains non-finite token",
            detail=f"row_index={row_index + 1}",
        )
    tokens = NUMBER_RE.findall(str(raw_line or ""))
    values: List[float] = []
    for token in tokens:
        parsed = _parse_decimal(token)
        if parsed is None:
            _raise_parse(
                path,
                error_code=ERROR_INVALID_NUMERIC,
                reason=f"{row_label} row has non-numeric token",
                detail=f"row_index={row_index + 1}, token='{token}'",
            )
        numeric = float(parsed)
        if not math.isfinite(numeric):
            _raise_parse(
                path,
                error_code=ERROR_INVALID_NUMERIC,
                reason=f"{row_label} row contains non-finite numeric value",
                detail=f"row_index={row_index + 1}, token='{token}'",
            )
        values.append(numeric)
    if not values:
        _raise_parse(
            path,
            error_code=ERROR_BAD_DIMENSIONS,
            reason=f"{row_label} row has no numeric payload",
            detail=f"row_index={row_index + 1}",
        )
    return values


def _validate_required_headers(path: Path, metadata: Dict[str, str]) -> tuple[List[float], float]:
    data_format_raw = str(metadata.get("Data_Format", "") or "").strip()
    if not data_format_raw:
        _raise_parse(
            path,
            error_code=ERROR_MISSING_HEADER,
            reason="missing Data_Format header",
            detail="Enable complex export output in VACS.",
        )
    if data_format_raw.lower() != "complex":
        _raise_parse(
            path,
            error_code=ERROR_UNSUPPORTED_FORMAT,
            reason="unsupported Data_Format",
            detail=f"expected='Complex', actual='{data_format_raw}'",
        )

    domain_raw = str(metadata.get("Data_Domain", "") or "").strip()
    if not domain_raw:
        _raise_parse(
            path,
            error_code=ERROR_MISSING_HEADER,
            reason="missing Data_Domain header",
            detail="Enable frequency-domain export in VACS.",
        )
    if "frequency" not in domain_raw.lower():
        _raise_parse(
            path,
            error_code=ERROR_UNSUPPORTED_FORMAT,
            reason="unsupported Data_Domain",
            detail=f"expected contains 'Frequency', actual='{domain_raw}'",
        )

    angles_raw = metadata.get("Param_Coord_x2")
    if not angles_raw:
        _raise_parse(
            path,
            error_code=ERROR_MISSING_HEADER,
            reason="missing Param_Coord_x2 header",
            detail="Enable 'Export of parameters' in VACS Data Export.",
        )
    angles_deg = _parse_angle_list(path, angles_raw)
    if len(angles_deg) < 1:
        _raise_parse(path, error_code=ERROR_BAD_DIMENSIONS, reason="angle_count must be >= 1")

    orientation_text = str(metadata.get("Param_Coord_x3", "") or "").strip()
    if not orientation_text:
        _raise_parse(
            path,
            error_code=ERROR_MISSING_HEADER,
            reason="missing Param_Coord_x3 header",
            detail="Enable 'Export of parameters' in VACS Data Export.",
        )
    orientation_raw = _parse_decimal(orientation_text)
    if orientation_raw is None or not math.isfinite(float(orientation_raw)):
        _raise_parse(
            path,
            error_code=ERROR_INVALID_NUMERIC,
            reason="Param_Coord_x3 is not numeric",
            detail=f"value='{orientation_text}'",
        )
    return angles_deg, float(orientation_raw)


def parse_polar_legacy_complex_txt(path: str | Path) -> PolarMatrixData:
    source_path = Path(path)
    lines = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    metadata = _parse_metadata(lines)
    angles_deg, orientation_raw = _validate_required_headers(source_path, metadata)
    angle_count = len(angles_deg)

    format_type = "legacy_with_frequency"
    absc_start = str(metadata.get("StartString_Absc", "") or "").strip()
    absc_end = str(metadata.get("EndString_Absc", "") or "").strip()
    has_abscissa_markers = bool(absc_start and absc_end)
    if has_abscissa_markers:
        format_type = "abscissa_data"

    start_token = str(metadata.get("StartString_Data", "Data") or "Data").strip()
    end_token = str(metadata.get("EndString_Data", "Data_End") or "Data_End").strip()
    data_rows = _read_data_block(
        source_path,
        lines,
        start_token=start_token,
        end_token=end_token,
        block_name="data",
    )

    rows: List[PolarMatrixRow] = []
    warnings: List[str] = []
    prev_freq: Optional[float] = None

    if format_type == "abscissa_data":
        absc_rows = _read_data_block(
            source_path,
            lines,
            start_token=absc_start,
            end_token=absc_end,
            block_name="abscissa",
        )
        freqs: List[float] = []
        for idx, raw_line in enumerate(absc_rows):
            values = _parse_numeric_row(source_path, row_label="abscissa", row_index=idx, raw_line=raw_line)
            if len(values) != 1:
                _raise_parse(
                    source_path,
                    error_code=ERROR_BAD_DIMENSIONS,
                    reason="abscissa row width mismatch",
                    detail=f"row_index={idx + 1}, expected=1, actual={len(values)}",
                )
            freq = float(values[0])
            if prev_freq is not None and freq < prev_freq:
                warnings.append(
                    f"frequency decreased at abscissa row {idx + 1}: prev={prev_freq:g}, current={freq:g}"
                )
            prev_freq = freq
            freqs.append(freq)

        if len(freqs) < 1:
            _raise_parse(source_path, error_code=ERROR_BAD_DIMENSIONS, reason="freq_count must be >= 1")
        if len(data_rows) != len(freqs):
            _raise_parse(
                source_path,
                error_code=ERROR_BAD_DIMENSIONS,
                reason="abscissa/data row count mismatch",
                detail=f"abscissa_rows={len(freqs)}, data_rows={len(data_rows)}",
            )

        expected_width = 2 * angle_count
        for idx, raw_line in enumerate(data_rows):
            values = _parse_numeric_row(source_path, row_label="data", row_index=idx, raw_line=raw_line)
            if len(values) != expected_width:
                _raise_parse(
                    source_path,
                    error_code=ERROR_BAD_DIMENSIONS,
                    reason="data row width mismatch for abscissa+data format",
                    detail=(
                        f"row_index={idx + 1}, expected={expected_width}, actual={len(values)} "
                        f"(2*angle_count)"
                    ),
                )
            rows.append(
                PolarMatrixRow(
                    freq_hz=float(freqs[idx]),
                    re_values=[float(item) for item in values[0::2]],
                    im_values=[float(item) for item in values[1::2]],
                )
            )
    else:
        expected_width = 1 + (2 * angle_count)
        for idx, raw_line in enumerate(data_rows):
            values = _parse_numeric_row(source_path, row_label="data", row_index=idx, raw_line=raw_line)
            if len(values) != expected_width:
                _raise_parse(
                    source_path,
                    error_code=ERROR_BAD_DIMENSIONS,
                    reason="data row width mismatch for legacy format",
                    detail=(
                        f"row_index={idx + 1}, expected={expected_width}, actual={len(values)} "
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
        _raise_parse(source_path, error_code=ERROR_BAD_DIMENSIONS, reason="freq_count must be >= 1")

    return PolarMatrixData(
        path=source_path,
        metadata=metadata,
        format_type=format_type,
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
