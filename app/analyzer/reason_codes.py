"""Shared analyzer KPI reason-code catalog and severity helpers."""

from __future__ import annotations

from typing import Dict, List, Sequence

_REASON_CATALOG: Dict[str, Dict[str, str]] = {
    "MISSING_KPI_ROWS": {
        "severity": "error",
        "summary": "KPI cache rows are missing for this run/version.",
        "impact": "Score and KPI metrics are unavailable until KPIs are computed.",
        "action": "Run Compute KPIs for the current batch.",
    },
    "MISSING_PLANE": {
        "severity": "warn",
        "summary": "At least one expected plane (H/V/D) is missing in imported polar data.",
        "impact": "Aggregate KPI weighting is reduced to available planes.",
        "action": "Re-export/import missing polar planes if full-plane analysis is required.",
    },
    "INSUFFICIENT_ANGLE_COVERAGE": {
        "severity": "warn",
        "summary": "Angular coverage is limited for reliable full-space assessment.",
        "impact": "Beamwidth/coverage metrics may rely on half-space assumptions.",
        "action": "Export a wider angle set (ideally symmetric around 0 deg) for stronger confidence.",
    },
    "EMPTY_BAND_INTERSECTION": {
        "severity": "error",
        "summary": "Requested analysis band has no overlap with available polar frequencies.",
        "impact": "KPIs are unscorable for this band.",
        "action": "Adjust KPI band limits to overlap imported frequency range.",
    },
    "NO_POINTS": {
        "severity": "error",
        "summary": "No polar points were available for KPI computation.",
        "impact": "KPIs cannot be computed.",
        "action": "Verify imported polar files and re-import the run.",
    },
}


def reason_item(code: str) -> Dict[str, str]:
    token = str(code or "").strip().upper()
    base = dict(_REASON_CATALOG.get(token) or {})
    if not base:
        base = {
            "severity": "warn",
            "summary": "Analyzer reported a reason code without catalog metadata.",
            "impact": "Review raw KPI payload for detailed diagnostics.",
            "action": "Inspect run details and source polar files.",
        }
    return {
        "code": token,
        "severity": str(base.get("severity") or "warn").strip().lower(),
        "summary": str(base.get("summary") or ""),
        "impact": str(base.get("impact") or ""),
        "action": str(base.get("action") or ""),
    }


def reason_items_for_codes(codes: Sequence[str]) -> List[Dict[str, str]]:
    ordered: List[Dict[str, str]] = []
    seen: set[str] = set()
    for raw in list(codes or []):
        token = str(raw or "").strip().upper()
        if not token or token in seen:
            continue
        seen.add(token)
        ordered.append(reason_item(token))
    return ordered
