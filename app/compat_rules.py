"""Machine-readable compatibility rule export for project/batch/version validation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List

from app.ath_knowledge import AthKnowledgeBundle, load_ath_knowledge


@dataclass(frozen=True)
class CompatibilityRuleRecord:
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


def _scope_for_rule(rule_scope: str) -> str:
    if rule_scope == "visibility":
        return "project"
    if rule_scope == "sweepability":
        return "batch"
    return "version"


def load_compatibility_rules(bundle: AthKnowledgeBundle | None = None) -> List[CompatibilityRuleRecord]:
    bundle = bundle or load_ath_knowledge()
    rules_raw = bundle.ruleset.get("rules", [])
    records: List[CompatibilityRuleRecord] = []
    for rule in rules_raw:
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id", "")).strip()
        if not rule_id:
            continue
        rule_scope = str(rule.get("scope", "validity"))
        description = str(rule.get("rationale", "")).strip()
        records.append(
            CompatibilityRuleRecord(
                rule_id=rule_id,
                description=description,
                scope=_scope_for_rule(rule_scope),
                condition=str(rule.get("when", "true")),
                action=[str(item) for item in list(rule.get("then", []) or [])],
                severity=str(rule.get("severity", "warn")),
                evidence="source" if description else "hypothesis",
            )
        )

    restrictions = bundle.ruleset.get("runner_restrictions", {})
    if isinstance(restrictions, dict):
        runner_mode = str(restrictions.get("runner_mode", "")).strip()
        locked = restrictions.get("locked_or_hidden_keys", [])
        if runner_mode and isinstance(locked, list) and locked:
            records.append(
                CompatibilityRuleRecord(
                    rule_id="runner_fixed_source_block",
                    description="Locks source-related keys for the fixed AKABAK import runner mode.",
                    scope="project",
                    condition=f"runner_mode == '{runner_mode}'",
                    action=[f"lock({str(key)})" for key in locked],
                    severity="fatal",
                    evidence="source",
                )
            )
    return records


def dump_compatibility_rules(path: str | Path, bundle: AthKnowledgeBundle | None = None) -> None:
    records = load_compatibility_rules(bundle=bundle)
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "1.0",
        "rule_count": len(records),
        "rules": [record.to_dict() for record in records],
    }
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
