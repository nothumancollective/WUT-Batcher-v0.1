"""Central resolver for Project constraints + Batch definition -> VersionSpec list."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import prod
import re
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from app.batch_planner import build_sweep_values
from app.compat_engine import sweepable_params, validity_report, visible_params
from app.constants import MAX_BATCH_VERSIONS, MAX_PREVIEW_VALIDATED_VERSIONS
from app.models import (
    Batch,
    ParamSelection,
    Project,
    ProjectConstraints,
    ResolveVersionsResult,
    ResolutionIssue,
    VersionSpec,
)


_VERSION_ID_RE = re.compile(r"^V(\d+)$", re.IGNORECASE)


class VersionResolutionError(ValueError):
    def __init__(self, issues: Sequence[ResolutionIssue]) -> None:
        self.issues = list(issues)
        super().__init__(self._build_message())

    def _build_message(self) -> str:
        if not self.issues:
            return "Version resolution failed."
        issues_text = "; ".join(f"{issue.rule_id}: {issue.message}" for issue in self.issues[:5])
        if len(self.issues) > 5:
            issues_text += f" (+{len(self.issues) - 5} more)"
        return f"Version resolution blocked by fatal issues: {issues_text}"


@dataclass(frozen=True)
class CompatibilityRule:
    rule_id: str
    description: str
    scope: str
    condition: str
    action: List[str]
    severity: str
    evidence: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "description": self.description,
            "scope": self.scope,
            "condition": self.condition,
            "action": list(self.action),
            "severity": self.severity,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class VersionPlanPreview:
    """Bounded compatibility result for an exact batch-size estimate."""

    version_count: int
    estimated_version_count: int
    issues: List[ResolutionIssue]
    fully_validated: bool


def _as_constraints_payload(project_or_constraints: Project | ProjectConstraints | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(project_or_constraints, Project):
        return project_or_constraints.constraints.to_dict()
    if isinstance(project_or_constraints, ProjectConstraints):
        return project_or_constraints.to_dict()
    if isinstance(project_or_constraints, dict):
        return dict(project_or_constraints)
    raise TypeError(f"Unsupported constraints type: {type(project_or_constraints)!r}")


def _effective_runner_mode(batch: Batch, constraints_payload: Dict[str, Any]) -> str:
    runner_mode = str(getattr(batch, "runner_mode", "")).strip()
    if runner_mode:
        return runner_mode
    return str(constraints_payload.get("runner_mode", "AkabakImportFixedSource"))


def _effective_sweep_mode(batch: Batch) -> str:
    if batch.sweep_mode in {"single", "combined"}:
        return batch.sweep_mode
    if batch.mode == "factorial":
        return "combined"
    return "single"


def _extract_constrained_params(constraints_payload: Dict[str, Any]) -> Dict[str, Any]:
    constrained: Dict[str, Any] = {}
    fixed = constraints_payload.get("fixed_params")
    if isinstance(fixed, dict):
        constrained.update({str(key): value for key, value in fixed.items()})
    # PROJECT form currently stores Mesh.* concrete values under "limits".
    limits = constraints_payload.get("limits")
    if isinstance(limits, dict):
        constrained.update({str(key): value for key, value in limits.items()})
    return constrained


def _preview_constraints_with_batch_context(constraints_payload: Dict[str, Any], batch: Batch) -> Dict[str, Any]:
    fixed = dict(constraints_payload.get("fixed_params", {}) or {})
    limits = dict(constraints_payload.get("limits", {}) or {})
    param_states = [
        item
        for item in list(constraints_payload.get("param_states", []) or [])
        if isinstance(item, dict)
    ]
    for key, value in _iter_batch_selected(batch):
        if value is None:
            continue
        fixed[str(key)] = value
        param_states.append({"param_name": str(key), "is_set": 1, "value": value})
    for key, spec in dict(getattr(batch, "sweeps", {}) or {}).items():
        sweep_key = str(key)
        start_value = getattr(spec, "start", None)
        if start_value is None and isinstance(spec, dict):
            start_value = spec.get("start")
        if start_value is None:
            continue
        fixed[sweep_key] = start_value
        param_states.append({"param_name": sweep_key, "is_set": 1, "value": start_value})
    return {
        "fixed_params": fixed,
        "limits": limits,
        "param_states": param_states,
        "runner_mode": str(constraints_payload.get("runner_mode", "")),
    }


def _selection_value(selection: Any) -> Any:
    if isinstance(selection, ParamSelection):
        return selection.value
    if isinstance(selection, dict):
        return selection.get("value")
    if hasattr(selection, "value"):
        return getattr(selection, "value")
    return selection


def _iter_batch_selected(batch: Batch) -> List[Tuple[str, Any]]:
    items: List[Tuple[str, Any]] = []
    for key, selection in batch.selected_params.items():
        items.append((str(key), _selection_value(selection)))
    return sorted(items, key=lambda item: item[0])


def _iter_sweeps(batch: Batch) -> List[Tuple[str, List[float]]]:
    sweeps: List[Tuple[str, List[float]]] = []
    for key, spec in sorted(batch.sweeps.items(), key=lambda item: str(item[0])):
        sweep_key = str(key)
        sweeps.append((sweep_key, build_sweep_values(spec)))
    return sweeps


def compatibility_rules_from_constraints(constraints_payload: Dict[str, Any]) -> List[CompatibilityRule]:
    rules_raw = constraints_payload.get("rules")
    if not isinstance(rules_raw, list):
        return []

    normalized: List[CompatibilityRule] = []
    for rule in rules_raw:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id", "")).strip()
        if not rule_id:
            continue
        normalized.append(
            CompatibilityRule(
                rule_id=rule_id,
                description=str(rule.get("rationale", "")),
                scope=str(rule.get("scope", "version")),
                condition=str(rule.get("when", "true")),
                action=[str(value) for value in list(rule.get("then", []) or [])],
                severity=str(rule.get("severity", "warn")),
                evidence="source" if bool(rule.get("rationale")) else "hypothesis",
            )
        )
    return normalized


def allocate_version_ids(count: int, existing_version_ids: Iterable[str]) -> List[str]:
    if count < 0:
        raise ValueError("count must be >= 0")
    max_number = 0
    for raw_id in existing_version_ids:
        match = _VERSION_ID_RE.match(str(raw_id).strip())
        if not match:
            continue
        max_number = max(max_number, int(match.group(1)))

    start = max_number + 1
    end = max_number + count
    width = max(3, len(str(end)))
    return [f"V{index:0{width}d}" for index in range(start, end + 1)]


def _compatibility_precheck(
    batch: Batch,
    constraints_payload: Dict[str, Any],
    runner_mode: str,
) -> List[ResolutionIssue]:
    issues: List[ResolutionIssue] = []
    preview_constraints = _preview_constraints_with_batch_context(constraints_payload, batch)
    report = validity_report(preview_constraints, runner_mode=runner_mode)
    for fatal in report.get("fatal", []):
        issues.append(
            ResolutionIssue(
                rule_id=str(fatal.get("rule_id", "unknown_rule")),
                severity="fatal",
                message=str(fatal.get("message", "Invalid project constraints.")),
                scope="project",
                source="compat_engine",
            )
        )

    visible = set(visible_params(preview_constraints, runner_mode=runner_mode))
    sweepable = set(sweepable_params(preview_constraints, runner_mode=runner_mode))

    for key, _ in _iter_batch_selected(batch):
        if key not in visible:
            issues.append(
                ResolutionIssue(
                    rule_id="batch_param_not_visible",
                    severity="fatal",
                    message=f"Batch parameter '{key}' is not visible for current project constraints.",
                    scope="batch",
                    source="resolver",
                )
            )

    fixed_keys = set(_extract_constrained_params(constraints_payload).keys())
    for key, _ in _iter_sweeps(batch):
        if key in fixed_keys:
            issues.append(
                ResolutionIssue(
                    rule_id="sweep_fixed_param_blocked",
                    severity="fatal",
                    message=f"Sweep is not allowed for constrained parameter '{key}'.",
                    scope="batch",
                    source="resolver",
                )
            )
        elif key not in sweepable:
            issues.append(
                ResolutionIssue(
                    rule_id="sweep_not_allowed",
                    severity="fatal",
                    message=f"Sweep parameter '{key}' is not sweepable under current constraints.",
                    scope="batch",
                    source="resolver",
                )
            )
    return issues


def _candidate_sweeps(mode: str, sweeps: List[Tuple[str, List[float]]]) -> List[Dict[str, float]]:
    if not sweeps:
        return [{}]
    if mode == "single":
        candidates: List[Dict[str, float]] = []
        for key, values in sweeps:
            for value in values:
                candidates.append({key: value})
        return candidates

    keys = [key for key, _ in sweeps]
    value_lists = [values for _, values in sweeps]
    candidates = []
    for values in product(*value_lists):
        candidates.append({key: value for key, value in zip(keys, values)})
    return candidates


def _candidate_sweep_count(mode: str, sweeps: List[Tuple[str, List[float]]]) -> int:
    if not sweeps:
        return 1
    counts = [len(values) for _key, values in sweeps]
    if mode == "single":
        return sum(counts)
    return prod(counts)


def version_count_for_batch(batch: Batch) -> int:
    """Return the exact candidate count without materializing combinations."""

    return _candidate_sweep_count(_effective_sweep_mode(batch), _iter_sweeps(batch))


def preview_version_plan(
    project_or_constraints: Project | ProjectConstraints | Dict[str, Any],
    batch: Batch,
    *,
    validation_limit: int = MAX_PREVIEW_VALIDATED_VERSIONS,
    max_versions: int = MAX_BATCH_VERSIONS,
) -> VersionPlanPreview:
    """Validate small plans fully and keep large-plan UI checks bounded."""

    constraints_payload = _as_constraints_payload(project_or_constraints)
    runner_mode = _effective_runner_mode(batch, constraints_payload)
    issues = _compatibility_precheck(batch, constraints_payload, runner_mode)
    estimated_count = version_count_for_batch(batch)
    if any(issue.severity == "fatal" for issue in issues):
        return VersionPlanPreview(
            version_count=0,
            estimated_version_count=estimated_count,
            issues=issues,
            fully_validated=False,
        )

    if estimated_count > max_versions:
        issues.append(
            ResolutionIssue(
                rule_id="batch_version_limit_exceeded",
                severity="fatal",
                message=(
                    f"Combined sweeps describe {estimated_count:,} versions; "
                    f"the safety limit is {max_versions:,}. Reduce sweep steps or use single mode."
                ),
                scope="batch",
                source="resolver",
            )
        )
        return VersionPlanPreview(
            version_count=0,
            estimated_version_count=estimated_count,
            issues=issues,
            fully_validated=False,
        )

    if estimated_count > validation_limit:
        issues.append(
            ResolutionIssue(
                rule_id="batch_version_validation_deferred",
                severity="warn",
                message=(
                    f"The {estimated_count:,}-version plan is too large for live per-version validation. "
                    "It will be fully validated when the batch is created."
                ),
                scope="batch",
                source="resolver",
            )
        )
        return VersionPlanPreview(
            version_count=estimated_count,
            estimated_version_count=estimated_count,
            issues=issues,
            fully_validated=False,
        )

    resolved = resolve_versions(
        constraints_payload,
        batch,
        existing_version_ids=(),
        strict=False,
        max_versions=max_versions,
    )
    return VersionPlanPreview(
        version_count=len(resolved.versions),
        estimated_version_count=estimated_count,
        issues=list(resolved.issues),
        fully_validated=True,
    )


def _version_validity_issues(
    resolved_params: Dict[str, Any],
    constraints_payload: Dict[str, Any],
    runner_mode: str,
    *,
    version_index: int,
) -> List[ResolutionIssue]:
    report = validity_report(
        {
            "fixed_params": resolved_params,
            "limits": constraints_payload.get("limits", {}),
        },
        runner_mode=runner_mode,
    )
    issues: List[ResolutionIssue] = []
    for fatal in report.get("fatal", []):
        issues.append(
            ResolutionIssue(
                rule_id=str(fatal.get("rule_id", "unknown_rule")),
                severity="fatal",
                message=str(fatal.get("message", "Version parameters violate compatibility rules.")),
                scope="version",
                source="compat_engine",
                version_index=version_index,
            )
        )
    return issues


def resolve_versions(
    project_or_constraints: Project | ProjectConstraints | Dict[str, Any],
    batch: Batch,
    *,
    existing_version_ids: Iterable[str] = (),
    strict: bool = True,
    max_versions: int = MAX_BATCH_VERSIONS,
) -> ResolveVersionsResult:
    constraints_payload = _as_constraints_payload(project_or_constraints)
    mode = _effective_sweep_mode(batch)
    runner_mode = _effective_runner_mode(batch, constraints_payload)
    fixed_params = _extract_constrained_params(constraints_payload)

    issues = _compatibility_precheck(batch, constraints_payload, runner_mode)
    if strict and any(issue.severity == "fatal" for issue in issues):
        raise VersionResolutionError([issue for issue in issues if issue.severity == "fatal"])
    if any(issue.severity == "fatal" for issue in issues):
        return ResolveVersionsResult(versions=[], issues=issues)

    selected_items = _iter_batch_selected(batch)
    base_variable_params: Dict[str, Any] = {}
    variable_keys = {key for key, _ in selected_items}
    for key, value in selected_items:
        if value is None:
            continue
        base_variable_params[key] = value

    sweep_defs = _iter_sweeps(batch)
    sweep_keys = [key for key, _ in sweep_defs]
    variable_keys.update(sweep_keys)

    candidate_count = _candidate_sweep_count(mode, sweep_defs)
    if candidate_count > max_versions:
        limit_issue = ResolutionIssue(
            rule_id="batch_version_limit_exceeded",
            severity="fatal",
            message=(
                f"Combined sweeps describe {candidate_count:,} versions; "
                f"the safety limit is {max_versions:,}. Reduce sweep steps or use single mode."
            ),
            scope="batch",
            source="resolver",
        )
        issues.append(limit_issue)
        if strict:
            raise VersionResolutionError([limit_issue])
        return ResolveVersionsResult(versions=[], issues=issues)

    candidates = _candidate_sweeps(mode, sweep_defs)
    valid_payloads: List[Tuple[int, Dict[str, Any], Dict[str, float], List[str]]] = []
    for index, sweep_values in enumerate(candidates, start=1):
        variable_map = dict(base_variable_params)
        variable_map.update(sweep_values)
        unset_keys = sorted(key for key in variable_keys if key not in variable_map)
        resolved_params = dict(fixed_params)
        resolved_params.update(variable_map)

        version_issues = _version_validity_issues(
            resolved_params,
            constraints_payload,
            runner_mode,
            version_index=index,
        )
        if version_issues:
            issues.extend(version_issues)
            continue

        valid_payloads.append((index, resolved_params, dict(sweep_values), unset_keys))

    fatal_issues = [issue for issue in issues if issue.severity == "fatal"]
    if strict and fatal_issues:
        raise VersionResolutionError(fatal_issues)

    version_ids = allocate_version_ids(len(valid_payloads), existing_version_ids)
    versions: List[VersionSpec] = []
    for local_index, (sequence_index, resolved_params, sweep_values, unset_keys) in enumerate(valid_payloads):
        variable_params = dict(resolved_params)
        for fixed_key in fixed_params.keys():
            variable_params.pop(fixed_key, None)

        versions.append(
            VersionSpec(
                project_id=batch.project_id,
                batch_id=batch.batch_id,
                version_id=version_ids[local_index],
                sweep_mode=mode,
                sequence_index=sequence_index,
                parameters=resolved_params,
                variable_parameters=variable_params,
                unset_parameters=unset_keys,
                sweep_parameters=sweep_values,
                sim_export_settings=batch.sim_export_settings.to_dict(),
            )
        )

    return ResolveVersionsResult(versions=versions, issues=issues)
