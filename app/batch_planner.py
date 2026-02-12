"""
Reconstructed from recovery artifacts
Confidence Level: HIGH
Sources used:
- C:/Work/Batch-Software/recovered/pyc_recovery/disassembly/app_batch_planner_py.preferred.pydisasm.txt
- C:/Work/Rebuild/RecoveredDocs/WUT_BatchSoftware_Update_Roadmap_Codex.md
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Dict, Iterable, List, Set, Tuple

from app.models import Batch, SweepSpec


SUPPORTED_SPACING = {"linear", "log"}


@dataclass(frozen=True)
class SweepValues:
    key: str
    values: List[float]


@dataclass(frozen=True)
class PlannedVersion:
    version_id: str
    parameters: Dict[str, object]
    sweep_mode: str


def _coerce_sweep_spec(key: str, raw_spec: object) -> SweepSpec:
    if isinstance(raw_spec, SweepSpec):
        return raw_spec
    if isinstance(raw_spec, dict):
        payload = dict(raw_spec)
        payload.setdefault("key", key)
        return SweepSpec.from_dict(payload)

    spec_key = str(getattr(raw_spec, "key", key))
    return SweepSpec(
        key=spec_key,
        start=float(getattr(raw_spec, "start")),
        end=float(getattr(raw_spec, "end")),
        steps=int(getattr(raw_spec, "steps")),
        spacing=str(getattr(raw_spec, "spacing", "linear")),
    )


def _iter_sweep_items(batch: Batch) -> List[Tuple[str, SweepSpec]]:
    raw_sweeps = getattr(batch, "sweeps", {})
    items: List[Tuple[str, SweepSpec]] = []

    if isinstance(raw_sweeps, dict):
        iterable: Iterable[Tuple[object, object]] = raw_sweeps.items()
        for raw_key, raw_spec in iterable:
            key = str(raw_key)
            items.append((key, _coerce_sweep_spec(key, raw_spec)))
    else:
        for raw_spec in raw_sweeps or []:
            if isinstance(raw_spec, dict):
                key = str(raw_spec.get("key", "")).strip()
            else:
                key = str(getattr(raw_spec, "key", "")).strip()
            if not key:
                continue
            items.append((key, _coerce_sweep_spec(key, raw_spec)))

    return sorted(items, key=lambda item: item[0])


def _selection_value(selection: object) -> object:
    if isinstance(selection, dict):
        return selection.get("value")
    if hasattr(selection, "value"):
        return getattr(selection, "value")
    return selection


def constrained_param_keys(constraints: Dict) -> Set[str]:
    """Extract constrained parameter keys from constraints.json payload."""
    keys: Set[str] = set()

    limits = constraints.get("limits")
    if isinstance(limits, dict):
        keys.update(limits.keys())

    fixed = constraints.get("fixed_params")
    if isinstance(fixed, dict):
        keys.update(fixed.keys())

    return keys


def build_sweep_values(spec: SweepSpec) -> List[float]:
    if spec.steps < 1:
        raise ValueError("Sweep steps must be >= 1")
    if spec.spacing not in SUPPORTED_SPACING:
        raise ValueError(f"Unsupported sweep spacing: {spec.spacing}")
    if spec.steps == 1:
        return [spec.start]

    if spec.spacing == "linear":
        if spec.start > spec.end:
            raise ValueError("Sweep start must be <= end for linear spacing")
        step = (spec.end - spec.start) / (spec.steps - 1)
        return [spec.start + (step * idx) for idx in range(spec.steps)]

    if spec.start <= 0 or spec.end <= 0:
        raise ValueError("Log spacing requires start/end > 0")
    if spec.start > spec.end:
        raise ValueError("Sweep start must be <= end for log spacing")

    ratio = (spec.end / spec.start) ** (1 / (spec.steps - 1))
    return [spec.start * (ratio**idx) for idx in range(spec.steps)]


def prepare_sweeps(batch: Batch) -> List[SweepValues]:
    sweeps: List[SweepValues] = []
    for key, spec in _iter_sweep_items(batch):
        values = build_sweep_values(spec)
        sweeps.append(SweepValues(key=key, values=values))
    return sweeps


def base_parameter_map(batch: Batch, constraints: Dict) -> Dict[str, object]:
    params: Dict[str, object] = {}

    fixed = constraints.get("fixed_params")
    if isinstance(fixed, dict):
        for key, value in fixed.items():
            params[str(key)] = value

    for key, selection in batch.selected_params.items():
        value = _selection_value(selection)
        if value is None:
            continue
        params[str(key)] = value

    return params


def _effective_sweep_mode(batch: Batch) -> str:
    if batch.sweep_mode in {"single", "combined"}:
        return batch.sweep_mode
    if batch.mode == "factorial":
        return "combined"
    return "single"


def expand_versions(batch: Batch, constraints: Dict) -> List[PlannedVersion]:
    constrained_keys = constrained_param_keys(constraints)
    sweep_keys = set(key for key, _ in _iter_sweep_items(batch))
    blocked = sorted(constrained_keys.intersection(sweep_keys))
    if blocked:
        raise ValueError("Sweep not allowed for constrained parameters: " + ", ".join(blocked))

    base = base_parameter_map(batch, constraints)
    sweeps = prepare_sweeps(batch)
    if not sweeps:
        return [
            PlannedVersion(
                version_id="V001",
                parameters=dict(base),
                sweep_mode=_effective_sweep_mode(batch),
            )
        ]

    mode = _effective_sweep_mode(batch)
    versions: List[PlannedVersion] = []
    version_idx = 1

    if mode == "single":
        for sweep in sweeps:
            for value in sweep.values:
                params = dict(base)
                params[sweep.key] = value
                versions.append(
                    PlannedVersion(
                        version_id=f"V{version_idx:03d}",
                        parameters=params,
                        sweep_mode=mode,
                    )
                )
                version_idx += 1
        return versions

    keys = [sweep.key for sweep in sweeps]
    value_lists = [sweep.values for sweep in sweeps]
    for values_tuple in product(*value_lists):
        params = dict(base)
        for key, value in zip(keys, values_tuple):
            params[key] = value
        versions.append(
            PlannedVersion(
                version_id=f"V{version_idx:03d}",
                parameters=params,
                sweep_mode=mode,
            )
        )
        version_idx += 1

    return versions


def compute_job_count(batch: Batch, constraints: Dict) -> int:
    """Compute number of jobs for a batch, respecting constraints and mode."""
    return len(expand_versions(batch, constraints))
