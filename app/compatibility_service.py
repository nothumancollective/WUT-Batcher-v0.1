"""Compatibility service for rules-driven UI and validation workflows."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.ath_knowledge import AthKnowledgeBundle, load_ath_knowledge
from app.compat_engine import sweepable_params, validity_report, visible_params
from app.compat_schema import normalize_ruleset
from app.constants import DEFAULT_RUNNER_MODE
from app.models import Batch, ParamSelection, ProjectConstraints, ResolutionIssue, SweepSpec
from app.version_resolver import resolve_versions


_KEY_IN_QUOTE_RE = re.compile(r"'([^']+)'")
_KEY_PREFIX_RE = re.compile(r"^([A-Za-z0-9_.-]+)\s+ist\b")
_REPORTED_SEVERITY_ORDER = {"fatal": 0, "warn": 1, "info": 2}


def _sorted_unique(items: Iterable[str]) -> List[str]:
    return sorted({str(item) for item in items if str(item).strip()})


def _as_constraints_payload(constraints: ProjectConstraints | Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(constraints, ProjectConstraints):
        return constraints.to_dict()
    if isinstance(constraints, dict):
        return dict(constraints)
    raise TypeError(f"Unsupported constraints payload: {type(constraints)!r}")


def _normalize_runner_mode(runner_mode: Optional[str], constraints_payload: Dict[str, Any]) -> str:
    if runner_mode and str(runner_mode).strip():
        return str(runner_mode).strip()
    return str(constraints_payload.get("runner_mode") or DEFAULT_RUNNER_MODE)


@dataclass(frozen=True)
class CompatibilityIssue:
    rule_id: str
    severity: str
    category: str
    message: str
    source: str
    scope: str
    evidence_type: str
    field_key: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "source": self.source,
            "scope": self.scope,
            "evidence_type": self.evidence_type,
        }
        if self.field_key:
            payload["field_key"] = self.field_key
        return payload


class CompatibilityService:
    def __init__(self, bundle: AthKnowledgeBundle | None = None) -> None:
        self.bundle = bundle or load_ath_knowledge()
        self.ruleset = normalize_ruleset(self.bundle.ruleset, self.bundle.catalog)
        self.catalog_keys = _sorted_unique(
            item.get("key", "")
            for item in self.bundle.catalog.get("parameters", [])
            if isinstance(item, dict)
        )
        self._rule_evidence_type = self._build_evidence_type_map(self.ruleset)

    def _build_evidence_type_map(self, ruleset: Dict[str, Any]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for rule in ruleset.get("rules", []):
            if not isinstance(rule, dict):
                continue
            rule_id = str(rule.get("id", "")).strip()
            if not rule_id:
                continue
            evidence = rule.get("evidence")
            evidence_type = "hypothesis"
            if isinstance(evidence, dict):
                evidence_type = str(evidence.get("type", "hypothesis"))
            mapping[rule_id] = evidence_type

        restrictions = ruleset.get("runner_restrictions")
        if isinstance(restrictions, dict):
            evidence = restrictions.get("evidence")
            evidence_type = "hypothesis"
            if isinstance(evidence, dict):
                evidence_type = str(evidence.get("type", "hypothesis"))
            mapping["runner_fixed_source_block"] = evidence_type
        return mapping

    def runner_locked_keys(self, runner_mode: str) -> List[str]:
        restrictions = self.ruleset.get("runner_restrictions")
        if not isinstance(restrictions, dict):
            return []
        if str(restrictions.get("runner_mode")) != str(runner_mode):
            return []
        keys = restrictions.get("locked_or_hidden_keys", [])
        if not isinstance(keys, list):
            return []
        return _sorted_unique(keys)

    def _evidence_type(self, rule_id: str) -> str:
        return self._rule_evidence_type.get(rule_id, "hypothesis")

    def _extract_field_key(self, message: str) -> Optional[str]:
        quoted = _KEY_IN_QUOTE_RE.search(message)
        if quoted:
            key = str(quoted.group(1)).strip()
            return key if key else None
        prefixed = _KEY_PREFIX_RE.search(message)
        if prefixed:
            key = str(prefixed.group(1)).strip()
            if key in self.catalog_keys:
                return key
        return None

    def _from_validity_issue(self, issue: Dict[str, Any]) -> CompatibilityIssue:
        rule_id = str(issue.get("rule_id", "unknown_rule"))
        message = str(issue.get("message", ""))
        severity = str(issue.get("severity", "warn")).lower()
        category = str(issue.get("category", "ath"))
        return CompatibilityIssue(
            rule_id=rule_id,
            severity=severity,
            category=category,
            message=message,
            source="compat_engine",
            scope="version",
            evidence_type=self._evidence_type(rule_id),
            field_key=self._extract_field_key(message),
        )

    def _from_resolution_issue(self, issue: ResolutionIssue) -> CompatibilityIssue:
        rule_id = str(issue.rule_id)
        message = str(issue.message)
        severity = str(issue.severity).lower()
        return CompatibilityIssue(
            rule_id=rule_id,
            severity=severity,
            category="resolver",
            message=message,
            source=str(issue.source),
            scope=str(issue.scope),
            evidence_type=self._evidence_type(rule_id),
            field_key=self._extract_field_key(message),
        )

    def _sort_and_dedup_issues(self, issues: Sequence[CompatibilityIssue]) -> List[CompatibilityIssue]:
        dedup: Dict[tuple[str, str, str, str], CompatibilityIssue] = {}
        for issue in issues:
            key = (issue.rule_id, issue.severity, issue.message, issue.scope)
            if key not in dedup:
                dedup[key] = issue
        return sorted(
            dedup.values(),
            key=lambda item: (
                _REPORTED_SEVERITY_ORDER.get(item.severity, 99),
                item.scope,
                item.rule_id,
                item.message,
            ),
        )

    def _build_preview_constraints(
        self,
        constraints_payload: Dict[str, Any],
        selected_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        fixed = dict(constraints_payload.get("fixed_params", {}) or {})
        for key, value in dict(selected_params or {}).items():
            if value is None:
                continue
            fixed[str(key)] = value
        return {
            "fixed_params": fixed,
            "limits": dict(constraints_payload.get("limits", {}) or {}),
            "runner_mode": str(constraints_payload.get("runner_mode") or DEFAULT_RUNNER_MODE),
        }

    def evaluate_project_constraints(
        self,
        constraints: ProjectConstraints | Dict[str, Any],
        *,
        runner_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        constraints_payload = _as_constraints_payload(constraints)
        resolved_runner_mode = _normalize_runner_mode(runner_mode, constraints_payload)
        preview = {
            "fixed_params": dict(constraints_payload.get("fixed_params", {}) or {}),
            "limits": dict(constraints_payload.get("limits", {}) or {}),
            "runner_mode": resolved_runner_mode,
        }
        visible = visible_params(preview, runner_mode=resolved_runner_mode, bundle=self.bundle)
        sweepable = sweepable_params(preview, runner_mode=resolved_runner_mode, bundle=self.bundle)
        locked = self.runner_locked_keys(resolved_runner_mode)
        report = validity_report(preview, runner_mode=resolved_runner_mode, bundle=self.bundle)
        issues = self._sort_and_dedup_issues([self._from_validity_issue(item) for item in report.get("issues", [])])
        return {
            "runner_mode": resolved_runner_mode,
            "visible_keys": visible,
            "sweepable_keys": sweepable,
            "locked_keys": locked,
            "issues": [issue.to_dict() for issue in issues],
            "issue_count": len(issues),
        }

    def _build_draft_batch(
        self,
        *,
        project_id: str,
        runner_mode: str,
        selected_params: Dict[str, Any],
        sweeps: Dict[str, Dict[str, Any]],
        sweep_mode: str,
    ) -> Batch:
        selected = {str(key): ParamSelection(value=value) for key, value in dict(selected_params or {}).items()}
        normalized_sweeps: Dict[str, SweepSpec] = {}
        for key, value in dict(sweeps or {}).items():
            if not isinstance(value, dict):
                continue
            try:
                normalized_sweeps[str(key)] = SweepSpec.from_dict(value, key=str(key))
            except Exception:
                continue
        return Batch(
            batch_id="B_DRAFT",
            project_id=project_id,
            selected_params=selected,
            sweeps=normalized_sweeps,
            sweep_mode=sweep_mode if sweep_mode in {"single", "combined"} else "single",
            runner_mode=runner_mode,
        )

    def evaluate_batch_definition(
        self,
        constraints: ProjectConstraints | Dict[str, Any],
        *,
        selected_params: Dict[str, Any],
        sweeps: Dict[str, Dict[str, Any]],
        sweep_mode: str,
    ) -> Dict[str, Any]:
        constraints_payload = _as_constraints_payload(constraints)
        project_id = str(constraints_payload.get("project_id", "P_DRAFT") or "P_DRAFT")
        runner_mode = _normalize_runner_mode(None, constraints_payload)
        preview_constraints = self._build_preview_constraints(constraints_payload, selected_params)

        visible = visible_params(preview_constraints, runner_mode=runner_mode, bundle=self.bundle)
        sweepable = sweepable_params(preview_constraints, runner_mode=runner_mode, bundle=self.bundle)
        locked = self.runner_locked_keys(runner_mode)

        issues: List[CompatibilityIssue] = []
        report = validity_report(preview_constraints, runner_mode=runner_mode, bundle=self.bundle)
        issues.extend(self._from_validity_issue(item) for item in report.get("issues", []))

        batch = self._build_draft_batch(
            project_id=project_id,
            runner_mode=runner_mode,
            selected_params=selected_params,
            sweeps=sweeps,
            sweep_mode=sweep_mode,
        )
        resolved = resolve_versions(constraints_payload, batch, existing_version_ids=(), strict=False)
        issues.extend(self._from_resolution_issue(item) for item in resolved.issues)

        sorted_issues = self._sort_and_dedup_issues(issues)
        return {
            "runner_mode": runner_mode,
            "visible_keys": visible,
            "sweepable_keys": sweepable,
            "locked_keys": locked,
            "issues": [issue.to_dict() for issue in sorted_issues],
            "issue_count": len(sorted_issues),
            "version_count_preview": len(resolved.versions),
        }
