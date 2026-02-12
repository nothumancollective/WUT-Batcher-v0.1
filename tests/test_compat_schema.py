from __future__ import annotations

import unittest

from app.ath_knowledge import load_ath_knowledge
from app.compat_schema import normalize_ruleset


class CompatSchemaTests(unittest.TestCase):
    def test_migration_v1_to_v1_1_adds_rule_fields(self) -> None:
        bundle = load_ath_knowledge()
        normalized = normalize_ruleset(bundle.ruleset, bundle.catalog)
        self.assertEqual(normalized["ruleset_version"], "ath-geometry-constraints.v1.1")
        self.assertGreater(len(normalized.get("rules", [])), 0)

        sample = normalized["rules"][0]
        for key in ("kind", "applies_to", "evidence"):
            self.assertIn(key, sample)
        self.assertIsInstance(sample["applies_to"], list)
        self.assertIsInstance(sample["evidence"], dict)

    def test_hypothesis_rules_get_verification_plan(self) -> None:
        bundle = load_ath_knowledge()
        normalized = normalize_ruleset(bundle.ruleset, bundle.catalog)
        hypothesis_rules = [
            rule for rule in normalized.get("rules", []) if rule.get("evidence", {}).get("type") == "hypothesis"
        ]
        self.assertGreater(len(hypothesis_rules), 0)
        self.assertTrue(all(bool(rule.get("verification_plan")) for rule in hypothesis_rules))

    def test_semantic_facts_include_required_entries(self) -> None:
        bundle = load_ath_knowledge()
        normalized = normalize_ruleset(bundle.ruleset, bundle.catalog)
        facts = normalized.get("semantic_facts", [])
        fact_ids = {str(item.get("fact_id")) for item in facts if isinstance(item, dict)}
        for fact_id in (
            "length_is_mandatory",
            "source_items_can_be_omitted",
            "source_contours_override",
            "ath_creates_subdirectory_per_script",
            "output_flags_stl_abecproject",
        ):
            self.assertIn(fact_id, fact_ids)


if __name__ == "__main__":
    unittest.main()

