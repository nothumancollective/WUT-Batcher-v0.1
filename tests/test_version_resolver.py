from __future__ import annotations

import unittest

from app.models import Batch, ParamSelection, SweepSpec
from app.version_resolver import (
    VersionResolutionError,
    allocate_version_ids,
    preview_version_plan,
    resolve_versions,
    version_count_for_batch,
)


class VersionResolverTests(unittest.TestCase):
    def test_single_mode_sets_only_active_sweep_without_base(self) -> None:
        constraints = {"fixed_params": {"Length": 90}, "limits": {}}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            selected_params={},
            sweeps={
                "Coverage.Angle": SweepSpec(start=40, end=50, steps=2),
                "Throat.Diameter": SweepSpec(start=20, end=30, steps=3),
            },
            sweep_mode="single",
            runner_mode="AthGuidePreview",
        )

        result = resolve_versions(constraints, batch, strict=True)
        self.assertEqual(len(result.versions), 5)
        self.assertEqual(result.versions[0].version_id, "V001")

        # In single mode without base values, exactly one sweep key is set per version.
        for version in result.versions:
            sweep_keys_set = [key for key in ("Coverage.Angle", "Throat.Diameter") if key in version.parameters]
            self.assertEqual(len(sweep_keys_set), 1)
            self.assertEqual(len(version.unset_parameters), 1)

    def test_combined_mode_sets_all_sweeps(self) -> None:
        constraints = {"fixed_params": {"Length": 90}, "limits": {}}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            selected_params={"Coverage.Angle": ParamSelection(value=45.0)},
            sweeps={
                "Coverage.Angle": SweepSpec(start=40, end=50, steps=2),
                "Throat.Diameter": SweepSpec(start=20, end=30, steps=2),
            },
            sweep_mode="combined",
            runner_mode="AthGuidePreview",
        )

        result = resolve_versions(constraints, batch, strict=True)
        self.assertEqual(len(result.versions), 4)
        for version in result.versions:
            self.assertIn("Coverage.Angle", version.parameters)
            self.assertIn("Throat.Diameter", version.parameters)
            self.assertEqual(version.unset_parameters, [])

    def test_combined_count_is_exact_without_materializing_versions(self) -> None:
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            sweeps={
                "Coverage.Angle": SweepSpec(start=20, end=80, steps=101),
                "Throat.Diameter": SweepSpec(start=20, end=80, steps=101),
            },
            sweep_mode="combined",
            runner_mode="AthGuidePreview",
        )
        self.assertEqual(version_count_for_batch(batch), 10_201)

    def test_resolver_blocks_cartesian_product_above_safety_limit(self) -> None:
        constraints = {"fixed_params": {"Length": 90}, "limits": {}}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            sweeps={
                "Coverage.Angle": SweepSpec(start=20, end=80, steps=101),
                "Throat.Diameter": SweepSpec(start=20, end=80, steps=101),
            },
            sweep_mode="combined",
            runner_mode="AthGuidePreview",
        )
        with self.assertRaises(VersionResolutionError) as raised:
            resolve_versions(constraints, batch, strict=True)
        self.assertIn("batch_version_limit_exceeded", {item.rule_id for item in raised.exception.issues})

    def test_preview_defers_per_version_validation_for_large_safe_plan(self) -> None:
        constraints = {"fixed_params": {"Length": 90}, "limits": {}}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            sweeps={
                "Coverage.Angle": SweepSpec(start=20, end=80, steps=17),
                "Throat.Diameter": SweepSpec(start=20, end=80, steps=17),
            },
            sweep_mode="combined",
            runner_mode="AthGuidePreview",
        )
        preview = preview_version_plan(constraints, batch)
        self.assertEqual(preview.version_count, 289)
        self.assertEqual(preview.estimated_version_count, 289)
        self.assertFalse(preview.fully_validated)
        self.assertIn("batch_version_validation_deferred", {item.rule_id for item in preview.issues})

    def test_resolution_blocks_sweep_for_fixed_constraint(self) -> None:
        constraints = {"fixed_params": {"Length": 90}, "limits": {}}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            sweeps={"Length": SweepSpec(start=80, end=100, steps=3)},
            sweep_mode="single",
            runner_mode="AthGuidePreview",
        )
        with self.assertRaises(VersionResolutionError):
            resolve_versions(constraints, batch, strict=True)

    def test_allocate_version_ids_respects_existing(self) -> None:
        allocated = allocate_version_ids(3, ["V001", "V009"])
        self.assertEqual(allocated, ["V010", "V011", "V012"])

    def test_mesh_limits_are_included_in_resolved_parameters(self) -> None:
        constraints = {
            "fixed_params": {"Length": 90},
            "limits": {"Mesh.Quadrants": 1, "Mesh.AngularSegments": 64},
        }
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            selected_params={},
            sweeps={},
            sweep_mode="single",
            runner_mode="AthGuidePreview",
        )
        result = resolve_versions(constraints, batch, strict=True)
        self.assertEqual(len(result.versions), 1)
        version = result.versions[0]
        self.assertEqual(version.parameters["Mesh.Quadrants"], 1)
        self.assertEqual(version.parameters["Mesh.AngularSegments"], 64)

    def test_unset_mesh_key_is_omitted_from_limits_payload(self) -> None:
        constraints = {
            "fixed_params": {"Length": 90},
            "limits": {"Mesh.Quadrants": 1},
            "param_states": [
                {"param_name": "Mesh.Quadrants", "is_set": 1, "value": 1},
                {"param_name": "Mesh.LengthSegments", "is_set": 0, "value": 20},
            ],
        }
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            selected_params={},
            sweeps={},
            sweep_mode="single",
            runner_mode="AthGuidePreview",
        )
        result = resolve_versions(constraints, batch, strict=True)
        self.assertEqual(len(result.versions), 1)
        version = result.versions[0]
        self.assertIn("Mesh.Quadrants", version.parameters)
        self.assertNotIn("Mesh.LengthSegments", version.parameters)

    def test_selected_param_visibility_uses_batch_context(self) -> None:
        constraints = {"fixed_params": {"Length": 120}, "limits": {}, "runner_mode": "AthGuidePreview"}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            selected_params={
                "GCurve.Type": ParamSelection(value=1),
                "GCurve.Dist": ParamSelection(value=60.0),
                "GCurve.Width": ParamSelection(value=120.0),
            },
            sweeps={},
            sweep_mode="single",
            runner_mode="AthGuidePreview",
        )
        result = resolve_versions(constraints, batch, strict=False)
        rule_ids = {issue.rule_id for issue in result.issues}
        self.assertNotIn("batch_param_not_visible", rule_ids)
        self.assertEqual(len(result.versions), 1)

    def test_sweepability_uses_batch_context(self) -> None:
        constraints = {"fixed_params": {"Length": 120}, "limits": {}, "runner_mode": "AthGuidePreview"}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            selected_params={
                "GCurve.Type": ParamSelection(value=1),
                "GCurve.Dist": ParamSelection(value=60.0),
            },
            sweeps={"GCurve.Width": SweepSpec(start=80.0, end=100.0, steps=2)},
            sweep_mode="single",
            runner_mode="AthGuidePreview",
        )
        result = resolve_versions(constraints, batch, strict=False)
        rule_ids = {issue.rule_id for issue in result.issues}
        self.assertNotIn("sweep_not_allowed", rule_ids)
        self.assertNotIn("batch_param_not_visible", rule_ids)
        self.assertEqual(len(result.versions), 2)

    def test_length_required_is_satisfied_by_batch_selection(self) -> None:
        constraints = {"fixed_params": {}, "limits": {}, "runner_mode": "AthGuidePreview"}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            selected_params={"Length": ParamSelection(value=220.0)},
            sweeps={},
            sweep_mode="single",
            runner_mode="AthGuidePreview",
        )
        result = resolve_versions(constraints, batch, strict=False)
        rule_ids = {issue.rule_id for issue in result.issues}
        self.assertNotIn("validity_length_required", rule_ids)
        self.assertEqual(len(result.versions), 1)

    def test_length_required_is_satisfied_by_batch_sweep(self) -> None:
        constraints = {"fixed_params": {}, "limits": {}, "runner_mode": "AthGuidePreview"}
        batch = Batch(
            batch_id="B001",
            project_id="P001",
            selected_params={},
            sweeps={"Length": SweepSpec(start=180.0, end=220.0, steps=2)},
            sweep_mode="single",
            runner_mode="AthGuidePreview",
        )
        result = resolve_versions(constraints, batch, strict=False)
        rule_ids = {issue.rule_id for issue in result.issues}
        self.assertNotIn("validity_length_required", rule_ids)
        self.assertEqual(len(result.versions), 2)


if __name__ == "__main__":
    unittest.main()
