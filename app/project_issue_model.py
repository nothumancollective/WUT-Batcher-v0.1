"""UI-only issue normalization for Project page presentation."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class UiProjectIssue:
    key: str
    severity: str  # error | warn | incomplete
    message: str
    section: str
    field_label: str
    source: str
    rule_id: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _is_required_missing_issue(raw_issue: Mapping[str, Any], *, field_is_set: bool) -> bool:
    if field_is_set:
        return False
    severity = str(raw_issue.get("severity", "")).strip().lower()
    if severity != "fatal":
        return False
    rule_id = str(raw_issue.get("rule_id", "")).strip().lower()
    message = str(raw_issue.get("message", "")).strip().lower()
    if "required" in rule_id or "required" in message or "erforderlich" in message:
        return True
    if "missing" in rule_id and ("field" in message or "value" in message):
        return True
    return False


def classify_ui_severity(raw_issue: Mapping[str, Any], *, field_is_set: bool) -> Optional[str]:
    severity = str(raw_issue.get("severity", "")).strip().lower()
    if severity in {"warn", "warning"}:
        return "warn"
    if severity in {"fatal", "error"}:
        if _is_required_missing_issue(raw_issue, field_is_set=field_is_set):
            return "incomplete"
        return "error"
    return None


def normalize_project_issues(
    raw_issues: Sequence[Mapping[str, Any]],
    *,
    field_is_set: Mapping[str, bool],
    field_labels: Mapping[str, str],
    field_sections: Mapping[str, str],
) -> List[UiProjectIssue]:
    dedup: Dict[Tuple[str, str, str], UiProjectIssue] = {}
    for raw in raw_issues:
        key = str(raw.get("field_key") or raw.get("key") or "").strip()
        if not key:
            continue
        severity = classify_ui_severity(raw, field_is_set=bool(field_is_set.get(key, False)))
        if severity is None:
            continue
        message = str(raw.get("message", "")).strip()
        if not message:
            continue
        item = UiProjectIssue(
            key=key,
            severity=severity,
            message=message,
            section=str(field_sections.get(key, "General")),
            field_label=str(field_labels.get(key, key)),
            source=str(raw.get("source", "")).strip().lower(),
            rule_id=str(raw.get("rule_id", "")).strip(),
        )
        dedup[(item.key, item.severity, item.message)] = item

    severity_rank = {"error": 0, "warn": 1, "incomplete": 2}
    ordered = sorted(
        dedup.values(),
        key=lambda item: (
            severity_rank.get(item.severity, 99),
            item.section.lower(),
            item.field_label.lower(),
            item.key.lower(),
            item.message.lower(),
        ),
    )
    return ordered


def issue_counts(issues: Iterable[UiProjectIssue]) -> Dict[str, int]:
    counts = {"error": 0, "warn": 0, "incomplete": 0}
    for issue in issues:
        if issue.severity in counts:
            counts[issue.severity] += 1
    return counts

