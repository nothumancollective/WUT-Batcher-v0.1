"""Ruleset schema normalization and migration helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Sequence


V1 = "ath-geometry-constraints.v1"
V1_1 = "ath-geometry-constraints.v1.1"

KIND_BY_SCOPE = {
    "validity": "validity",
    "visibility": "visibility",
    "sweepability": "sweepability",
}

APPLIES_TO_BY_SCOPE = {
    "validity": ["version"],
    "visibility": ["project", "batch"],
    "sweepability": ["batch"],
}


def _catalog_sources(catalog: Dict[str, Any], key: str) -> List[Dict[str, str]]:
    for item in catalog.get("parameters", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("key")) != key:
            continue
        refs: List[Dict[str, str]] = []
        for source in item.get("sources", []):
            if not isinstance(source, dict):
                continue
            refs.append(
                {
                    "source": str(source.get("source", "")),
                    "section": str(source.get("section", "")),
                    "quote_hint": str(source.get("quote-hint", "")),
                }
            )
        return refs
    return []


def _source_evidence(refs: Sequence[Dict[str, str]], notes: str) -> Dict[str, Any]:
    return {
        "type": "source",
        "refs": list(refs),
        "confidence": 0.95,
        "notes": notes,
    }


def _hypothesis_evidence(notes: str, confidence: float = 0.4) -> Dict[str, Any]:
    return {
        "type": "hypothesis",
        "refs": [],
        "confidence": float(confidence),
        "notes": notes,
    }


def _default_verification_plan(rule_id: str) -> str:
    return (
        f"Create a focused fixture for '{rule_id}', execute rule evaluator and cross-check with ATH run logs "
        "to confirm behavior before promoting confidence."
    )


def _normalize_evidence(raw: Any, *, rule_id: str, fallback_note: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return _hypothesis_evidence(fallback_note)

    evidence_type = str(raw.get("type", "hypothesis"))
    refs_raw = raw.get("refs", [])
    refs: List[Dict[str, str]] = []
    if isinstance(refs_raw, list):
        for entry in refs_raw:
            if not isinstance(entry, dict):
                continue
            refs.append(
                {
                    "source": str(entry.get("source", "")),
                    "section": str(entry.get("section", "")),
                    "quote_hint": str(entry.get("quote_hint", entry.get("quote-hint", ""))),
                }
            )
    confidence = raw.get("confidence", 0.4 if evidence_type == "hypothesis" else 0.95)
    try:
        confidence_value = float(confidence)
    except (TypeError, ValueError):
        confidence_value = 0.4 if evidence_type == "hypothesis" else 0.95
    notes = str(raw.get("notes", fallback_note))
    normalized = {
        "type": evidence_type,
        "refs": refs,
        "confidence": confidence_value,
        "notes": notes,
    }
    if normalized["type"] == "hypothesis" and normalized["confidence"] > 0.5:
        normalized["confidence"] = 0.5
    return normalized


def _rule_evidence(rule_id: str, catalog: Dict[str, Any]) -> Dict[str, Any]:
    if rule_id == "validity_length_required":
        refs = _catalog_sources(catalog, "Length")
        if refs:
            return _source_evidence(refs, "Length mandatory requirement in explicit parametrization.")
    if rule_id == "visibility_source_contours_override":
        refs = _catalog_sources(catalog, "Source.Contours")
        if refs:
            return _source_evidence(refs, "Source.Contours overrides Source.* except Source.Velocity.")
    return _hypothesis_evidence(
        "Rule behavior is currently derived from legacy implementation and requires explicit document verification."
    )


def _fact_records(catalog: Dict[str, Any]) -> List[Dict[str, Any]]:
    length_refs = _catalog_sources(catalog, "Length")
    contours_refs = _catalog_sources(catalog, "Source.Contours")

    facts: List[Dict[str, Any]] = []
    facts.append(
        {
            "fact_id": "length_is_mandatory",
            "statement": "Length is a mandatory item in explicit horn parametrization.",
            "evidence": (
                _source_evidence(length_refs, "Directly documented for Length.")
                if length_refs
                else _hypothesis_evidence("Length mandatory reference missing in knowledge bundle.")
            ),
        }
    )
    facts.append(
        {
            "fact_id": "source_items_can_be_omitted",
            "statement": "Source.* items can be omitted and ATH will use defaults.",
            "evidence": _hypothesis_evidence(
                "Knowledge bundle currently lacks explicit omission/default statement for all Source.* items."
            ),
            "verification_plan": (
                "Add doc citation for default omission behavior or run ATH fixtures with omitted Source.* fields and "
                "record resulting defaults."
            ),
        }
    )
    facts.append(
        {
            "fact_id": "source_contours_override",
            "statement": "If Source.Contours is present, Source.Shape/Radius/Curv are ignored; Source.Velocity remains relevant.",
            "evidence": (
                _source_evidence(contours_refs, "Documented Source.Contours override semantics.")
                if contours_refs
                else _hypothesis_evidence("Source.Contours override reference missing in knowledge bundle.")
            ),
        }
    )
    facts.append(
        {
            "fact_id": "ath_creates_subdirectory_per_script",
            "statement": "ATH auto-creates a subdirectory per script under output root.",
            "evidence": _hypothesis_evidence(
                "No explicit source entry for output-root subdirectory behavior exists in current knowledge bundle."
            ),
            "verification_plan": "Capture exact User Guide section and validate via controlled ATH run in temp output root.",
        }
    )
    facts.append(
        {
            "fact_id": "output_flags_stl_abecproject",
            "statement": "ATH supports output flags Output.STL and Output.ABECProject.",
            "evidence": _hypothesis_evidence(
                "No explicit Output.STL/Output.ABECProject entries currently exist in the local knowledge bundle."
            ),
            "verification_plan": "Add direct User Guide references for Output flags and validate with ATH export fixtures.",
        }
    )
    return facts


def migrate_ruleset_v1_to_v1_1(ruleset: Dict[str, Any], catalog: Dict[str, Any]) -> Dict[str, Any]:
    migrated = deepcopy(ruleset)
    source_version = str(migrated.get("ruleset_version", ""))
    if source_version == V1:
        migrated["ruleset_version"] = V1_1

    normalized_rules: List[Dict[str, Any]] = []
    for raw_rule in migrated.get("rules", []):
        if not isinstance(raw_rule, dict):
            continue
        rule = dict(raw_rule)
        rule_id = str(rule.get("id", "unknown_rule"))
        scope = str(rule.get("scope", "validity"))
        rule["kind"] = str(rule.get("kind") or KIND_BY_SCOPE.get(scope, "validity"))

        applies_to = rule.get("applies_to")
        if not isinstance(applies_to, list) or not applies_to:
            applies_to = list(APPLIES_TO_BY_SCOPE.get(scope, ["version"]))
        rule["applies_to"] = [str(item) for item in applies_to]

        fallback = _rule_evidence(rule_id, catalog)
        rule["evidence"] = _normalize_evidence(
            rule.get("evidence"),
            rule_id=rule_id,
            fallback_note=str(fallback.get("notes", "")),
        )
        if not isinstance(rule.get("evidence"), dict):
            rule["evidence"] = fallback
        if (
            isinstance(rule.get("evidence"), dict)
            and rule["evidence"].get("type") == "hypothesis"
            and not rule.get("verification_plan")
        ):
            rule["verification_plan"] = _default_verification_plan(rule_id)
        normalized_rules.append(rule)
    migrated["rules"] = normalized_rules

    restrictions = migrated.get("runner_restrictions", {})
    if isinstance(restrictions, dict):
        normalized_restrictions = dict(restrictions)
        normalized_restrictions["kind"] = str(restrictions.get("kind") or "runner")
        applies_to = restrictions.get("applies_to")
        if not isinstance(applies_to, list) or not applies_to:
            applies_to = ["project"]
        normalized_restrictions["applies_to"] = [str(item) for item in applies_to]

        fallback = _hypothesis_evidence(
            "Runner restrictions are implementation-level constraints and need explicit ATH/AKABAK mode references."
        )
        evidence = _normalize_evidence(
            restrictions.get("evidence"),
            rule_id="runner_fixed_source_block",
            fallback_note=str(fallback.get("notes", "")),
        )
        if not isinstance(evidence, dict):
            evidence = fallback
        normalized_restrictions["evidence"] = evidence
        if evidence.get("type") == "hypothesis" and not restrictions.get("verification_plan"):
            normalized_restrictions["verification_plan"] = _default_verification_plan("runner_fixed_source_block")
        migrated["runner_restrictions"] = normalized_restrictions

    migrated["semantic_facts"] = _fact_records(catalog)
    return migrated


def normalize_ruleset(ruleset: Dict[str, Any], catalog: Dict[str, Any]) -> Dict[str, Any]:
    return migrate_ruleset_v1_to_v1_1(ruleset, catalog)

