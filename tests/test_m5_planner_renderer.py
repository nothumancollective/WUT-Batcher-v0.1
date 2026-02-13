from __future__ import annotations



import unittest



from app.batch_planner import expand_versions

from app.cfg_renderer import render_cfg_text

from app.models import Batch, ParamSelection, SweepSpec





class PlannerRendererTests(unittest.TestCase):

    def test_single_expansion_is_deterministic(self) -> None:

        batch = Batch(

            batch_id="B001",

            project_id="P001",

            selected_params={"Throat.Diameter": ParamSelection(value=25.0)},

            sweeps={

                "Length": SweepSpec(start=80, end=100, steps=3),

                "Coverage.Angle": SweepSpec(start=40, end=50, steps=2),

            },

            sweep_mode="single",

        )

        versions = expand_versions(batch, {"fixed_params": {}, "limits": {}})

        self.assertEqual([v.version_id for v in versions], ["V001", "V002", "V003", "V004", "V005"])

        # Alphabetic key order: Coverage.Angle before Length.

        self.assertEqual(float(versions[0].parameters["Coverage.Angle"]), 40.0)

        self.assertEqual(float(versions[2].parameters["Length"]), 80.0)



    def test_combined_expansion_is_cartesian_and_stable(self) -> None:

        batch = Batch(

            batch_id="B001",

            project_id="P001",

            sweeps={

                "Length": SweepSpec(start=80, end=90, steps=2),

                "Coverage.Angle": SweepSpec(start=40, end=50, steps=2),

            },

            sweep_mode="combined",

        )

        versions = expand_versions(batch, {"fixed_params": {}, "limits": {}})

        self.assertEqual(len(versions), 4)

        self.assertEqual(versions[0].version_id, "V001")

        self.assertEqual(float(versions[0].parameters["Coverage.Angle"]), 40.0)

        self.assertEqual(float(versions[0].parameters["Length"]), 80.0)



    def test_cfg_renderer_enforces_mandatory_source_block(self) -> None:

        template = """ABEC.AkabakMode = 0\nLE = foo\nLE.Voltage = 2.5\nLength = 70\nSource.Shape = 1\n"""

        cfg = render_cfg_text(

            template_text=template,

            parameters={

                "Length": 90,

                "ABEC.AkabakMode": 9,

                "LE": "bar",

                "LE.Voltage": 99,

                "Source.Shape": 2,

            },

            version_id="V001",

        )

        self.assertIn("ABEC.AkabakMode    = 1", cfg)

        self.assertIn("LE          = generic25", cfg)

        self.assertIn("LE.Voltage  = 1.0", cfg)

        self.assertIn("Length           = 90", cfg)

        self.assertNotIn("Source.Shape", cfg)

    def test_cfg_renderer_ignores_runner_locked_overrides(self) -> None:

        template = (
            "ABEC.AkabakMode = 0\n"
            "LE = customdriver\n"
            "LE.Voltage = 7.5\n"
            "Source.Shape = 2\n"
            "Source.Radius = 15\n"
            "Source.Curv = 2\n"
            "Length = 80\n"
        )
        cfg = render_cfg_text(
            template_text=template,
            parameters={
                "Length": 95,
                "ABEC.AkabakMode": 7,
                "LE": "something_else",
                "LE.Voltage": 12,
                "Source.Shape": 9,
                "Source.Radius": 90,
                "Source.Curv": 4,
            },
            version_id="V001",
        )
        self.assertIn("ABEC.AkabakMode    = 1", cfg)
        self.assertIn("LE          = generic25", cfg)
        self.assertIn("LE.Voltage  = 1.0", cfg)
        self.assertNotIn("Source.Shape = 2", cfg)
        self.assertNotIn("Source.Radius = 15", cfg)
        self.assertNotIn("Source.Curv = 2", cfg)
        self.assertNotIn("Source.Shape         = 9", cfg)
        self.assertNotIn("Source.Radius        = 90", cfg)
        self.assertNotIn("Source.Curv          = 4", cfg)

    def test_cfg_renderer_emits_r_osse_as_block(self) -> None:
        cfg = render_cfg_text(
            template_text="Length = 120\n",
            parameters={
                "R-OSSE": {
                    "R": 100.0,
                    "r0": 17.0,
                    "a0": 4.5,
                    "a": 46.0,
                    "k": 1.0,
                    "r": 0.7,
                    "m": 2.8,
                    "b": 0.2,
                    "q": 0.99,
                },
            },
            version_id="V001",
        )
        self.assertIn("R-OSSE = {", cfg)
        self.assertIn("R = 100", cfg)
        self.assertIn("r0 = 17", cfg)
        self.assertIn("a0 = 4.5", cfg)
        self.assertIn("q = 0.99", cfg)
        self.assertIn("}", cfg)





if __name__ == "__main__":

    unittest.main()



