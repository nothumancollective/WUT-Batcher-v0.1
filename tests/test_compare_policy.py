from __future__ import annotations

import unittest

from app.compare_policy import (
    alias_allowed_keys_for_expected,
    canonicalize_cfg_value,
    canonicalize_config_value,
    compare_semantics,
    policy_tracked_keys,
    policy_values_equal,
)


class ComparePolicyTests(unittest.TestCase):
    def test_policy_tracks_five_high_mismatch_keys(self) -> None:
        keys = policy_tracked_keys()
        self.assertEqual(
            keys,
            [
                "GCurve.SF",
                "Mesh.InterfaceDraw",
                "Mesh.SubdomainSlices",
                "Mesh.ZMapPoints",
                "Morph.AllowShrinkage",
            ],
        )

    def test_bool_canonicalization_morph_allow_shrinkage(self) -> None:
        self.assertEqual(canonicalize_cfg_value("Morph.AllowShrinkage", True), 1)
        self.assertEqual(canonicalize_cfg_value("Morph.AllowShrinkage", False), 0)
        self.assertIs(canonicalize_config_value("Morph.AllowShrinkage", "1.0"), True)
        self.assertIs(canonicalize_config_value("Morph.AllowShrinkage", "0"), False)

    def test_gcurve_sf_alias_from_subkeys(self) -> None:
        observed = {
            "GCurve.SF.a": "1",
            "GCurve.SF.b": "1",
            "GCurve.SF.m1": "5",
            "GCurve.SF.m2": "5",
            "GCurve.SF.n1": "0.3",
            "GCurve.SF.n2": "1.1",
            "GCurve.SF.n3": "1.1",
        }
        rhs = canonicalize_config_value("GCurve.SF", "", observed_map=observed)
        self.assertEqual(rhs, [1.0, 1.0, 5.0, 0.3, 1.1, 1.1])
        self.assertTrue(
            policy_values_equal(
                "GCurve.SF",
                [1.0, 1.0, 5.0, 0.3, 1.1, 1.1],
                "",
                target="ath_config",
                observed_map=observed,
            )
        )

    def test_alias_allowlist_for_expected_parent(self) -> None:
        alias = alias_allowed_keys_for_expected(["GCurve.SF", "Length"])
        self.assertIn("GCurve.SF.a", alias)
        self.assertIn("GCurve.SF.m2", alias)
        self.assertIn("GCurve.SF.n3", alias)

    def test_mesh_empty_list_equivalence_in_ath_config(self) -> None:
        eq = policy_values_equal(
            "Mesh.SubdomainSlices",
            [12, 14, 18],
            "",
            target="ath_config",
            observed_map={},
        )
        self.assertIs(eq, True)
        self.assertIsNotNone(compare_semantics("Mesh.SubdomainSlices"))


if __name__ == "__main__":
    unittest.main()

