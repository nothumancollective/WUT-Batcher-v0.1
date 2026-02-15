from __future__ import annotations

import unittest

from app.runner_test_profiles import apply_runner_test_profile, get_runner_test_profile


class RunnerTestProfilesTests(unittest.TestCase):
    def test_fast_profile_exists(self) -> None:
        profile = get_runner_test_profile("fast")
        self.assertEqual(profile.profile_id, "fast")
        self.assertGreaterEqual(len(profile.parameter_overrides), 1)

    def test_apply_fast_profile_overrides_parameters_and_sim_settings(self) -> None:
        parameters = {"Length": 120, "Mesh.AngularSegments": 100}
        sim_settings = {"freq_start_hz": 500.0, "freq_end_hz": 15000.0, "num_points": 16}
        merged_params, merged_sim, metadata = apply_runner_test_profile(
            profile_id="fast",
            parameters=parameters,
            sim_export_settings=sim_settings,
        )
        self.assertEqual(merged_params["Length"], 120)
        self.assertEqual(merged_params["Mesh.AngularSegments"], 24)
        self.assertEqual(merged_sim["num_points"], 6)
        self.assertEqual(metadata["profile"]["profile_id"], "fast")
        self.assertIn("Mesh.AngularSegments", metadata["applied_parameter_overrides"])


if __name__ == "__main__":
    unittest.main()
