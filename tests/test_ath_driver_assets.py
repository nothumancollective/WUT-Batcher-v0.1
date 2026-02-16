from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.ath_driver_assets import repair_post_ath_le_binding


class AthDriverAssetsTests(unittest.TestCase):
    def test_repair_post_ath_le_binding_copies_and_patches_abec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_root = root / "ATH"
            driver_dir = ath_root / "lib" / "drivers"
            driver_dir.mkdir(parents=True, exist_ok=True)
            driver_source = driver_dir / "generic25.txt"
            driver_source.write_text("driver\n", encoding="utf-8")
            ath_exe = ath_root / "ath.exe"
            ath_exe.write_text("stub\n", encoding="utf-8")

            abec_dir = root / "export" / "ABEC_FreeStanding"
            abec_dir.mkdir(parents=True, exist_ok=True)
            abec = abec_dir / "Project.abec"
            abec.write_text(
                "[Project]\n"
                "Scriptname_InfoFile=\n"
                "[LEScript]\n"
                "Scriptname_LEScript=\n",
                encoding="utf-8",
            )

            diagnostics = root / "diag"
            result = repair_post_ath_le_binding(
                abec_path=abec,
                ath_executable=ath_exe,
                diagnostics_dir=diagnostics,
            )
            self.assertTrue(result.ok)
            self.assertTrue(Path(result.script_path).exists())
            self.assertEqual(Path(result.script_path).read_text(encoding="utf-8"), "driver\n")
            patched = abec.read_text(encoding="utf-8")
            self.assertIn("[LEScript]", patched)
            self.assertIn("Scriptname_LEScript=generic25.txt", patched)
            self.assertTrue(result.before_snapshot_path and Path(result.before_snapshot_path).exists())
            self.assertTrue(result.after_snapshot_path and Path(result.after_snapshot_path).exists())
            self.assertTrue(result.diagnostics_path and Path(result.diagnostics_path).exists())

    def test_repair_post_ath_le_binding_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_root = root / "ATH"
            driver_dir = ath_root / "lib" / "drivers"
            driver_dir.mkdir(parents=True, exist_ok=True)
            (driver_dir / "generic25.txt").write_text("driver\n", encoding="utf-8")
            ath_exe = ath_root / "ath.exe"
            ath_exe.write_text("stub\n", encoding="utf-8")

            abec_dir = root / "export" / "ABEC_FreeStanding"
            abec_dir.mkdir(parents=True, exist_ok=True)
            abec = abec_dir / "Project.abec"
            abec.write_text(
                "[Project]\n"
                "[LEScript]\n"
                "Scriptname_LEScript=generic25.txt\n",
                encoding="utf-8",
            )

            first = repair_post_ath_le_binding(abec_path=abec, ath_executable=ath_exe)
            second = repair_post_ath_le_binding(abec_path=abec, ath_executable=ath_exe)
            self.assertTrue(first.ok)
            self.assertTrue(second.ok)
            self.assertIn(second.copy.status, {"already_present", "copied"})
            self.assertEqual(second.patch.status, "already_set")

    def test_repair_post_ath_le_binding_driver_drvgroup_profile_patches_driver_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_root = root / "ATH"
            driver_dir = ath_root / "lib" / "drivers"
            driver_dir.mkdir(parents=True, exist_ok=True)
            (driver_dir / "generic25.txt").write_text(
                "System 'S1'\n"
                "  Driver 'D1' Def='Drv1' Node=1=0=10=20\n"
                "  RadImp 'Throat' Node=400 DrvGroup=1001\n",
                encoding="utf-8",
            )
            ath_exe = ath_root / "ath.exe"
            ath_exe.write_text("stub\n", encoding="utf-8")

            abec_dir = root / "export" / "ABEC_FreeStanding"
            abec_dir.mkdir(parents=True, exist_ok=True)
            abec = abec_dir / "Project.abec"
            abec.write_text("[LEScript]\nScriptname_LEScript=\n", encoding="utf-8")

            result = repair_post_ath_le_binding(
                abec_path=abec,
                ath_executable=ath_exe,
                le_patch_profile="driver_drvgroup",
            )
            self.assertTrue(result.ok)
            self.assertIn(result.driver_patch.status, {"patched", "already_conformant"})
            patched_driver = Path(result.script_path).read_text(encoding="utf-8")
            self.assertIn("Driver 'D1' Def='Drv1' Node=1=0=10=20 DrvGroup=1001", patched_driver)

    def test_repair_post_ath_le_binding_driver_drvgroup_defdriving_profile_adds_def_driving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_root = root / "ATH"
            driver_dir = ath_root / "lib" / "drivers"
            driver_dir.mkdir(parents=True, exist_ok=True)
            (driver_dir / "generic25.txt").write_text(
                "Def_Driver 'Drv1'\n"
                "  Re=6.3ohm\n"
                "\n"
                "System 'S1'\n"
                "  Driver 'D1' Def='Drv1' Node=1=0=10=20\n",
                encoding="utf-8",
            )
            ath_exe = ath_root / "ath.exe"
            ath_exe.write_text("stub\n", encoding="utf-8")

            abec_dir = root / "export" / "ABEC_FreeStanding"
            abec_dir.mkdir(parents=True, exist_ok=True)
            abec = abec_dir / "Project.abec"
            abec.write_text("[LEScript]\nScriptname_LEScript=\n", encoding="utf-8")

            result = repair_post_ath_le_binding(
                abec_path=abec,
                ath_executable=ath_exe,
                le_patch_profile="driver_drvgroup_def_driving",
                le_voltage_vrms=2.83,
            )
            self.assertTrue(result.ok)
            patched_driver = Path(result.script_path).read_text(encoding="utf-8")
            self.assertIn('Def_Driving "Voltage source" Value=2.83V IsRms', patched_driver)
            self.assertIn("DrvGroup=1001", patched_driver)

    def test_repair_post_ath_le_binding_doc_example_profile_inserts_resistor_and_node_shift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_root = root / "ATH"
            driver_dir = ath_root / "lib" / "drivers"
            driver_dir.mkdir(parents=True, exist_ok=True)
            (driver_dir / "generic25.txt").write_text(
                "System 'S1'\n"
                "  Driver 'D1' Def='Drv1' Node=1=0=10=20\n",
                encoding="utf-8",
            )
            ath_exe = ath_root / "ath.exe"
            ath_exe.write_text("stub\n", encoding="utf-8")
            abec_dir = root / "export" / "ABEC_FreeStanding"
            abec_dir.mkdir(parents=True, exist_ok=True)
            abec = abec_dir / "Project.abec"
            abec.write_text("[LEScript]\nScriptname_LEScript=\n", encoding="utf-8")

            result = repair_post_ath_le_binding(
                abec_path=abec,
                ath_executable=ath_exe,
                le_patch_profile="driver_drvgroup_def_driving_resistor",
            )
            self.assertTrue(result.ok)
            patched_driver = Path(result.script_path).read_text(encoding="utf-8")
            self.assertIn("Resistor 'Rg' Node=1=2 R=1ohm", patched_driver)
            self.assertIn("Driver 'D1' Def='Drv1' Node=2=0=10=20 DrvGroup=1001", patched_driver)
            self.assertIn('Def_Driving "Voltage source" Value=1V IsRms', patched_driver)

    def test_repair_post_ath_le_binding_mut_electrical_profile_mutates_expected_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_root = root / "ATH"
            driver_dir = ath_root / "lib" / "drivers"
            driver_dir.mkdir(parents=True, exist_ok=True)
            (driver_dir / "generic25.txt").write_text(
                "Def_Driver 'Drv1'\n"
                "  Re=6.3ohm\n"
                "  Le=0.03mH\n"
                "  ExpoRe=1.0\n"
                "  ExpoLe=1.0\n"
                "\n"
                "System 'S1'\n"
                "  Driver 'D1' Def='Drv1' Node=1=0=10=20\n",
                encoding="utf-8",
            )
            ath_exe = ath_root / "ath.exe"
            ath_exe.write_text("stub\n", encoding="utf-8")
            abec_dir = root / "export" / "ABEC_FreeStanding"
            abec_dir.mkdir(parents=True, exist_ok=True)
            abec = abec_dir / "Project.abec"
            abec.write_text("[LEScript]\nScriptname_LEScript=\n", encoding="utf-8")

            result = repair_post_ath_le_binding(
                abec_path=abec,
                ath_executable=ath_exe,
                le_patch_profile="mut_electrical",
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.driver_patch.profile, "mut_electrical")
            self.assertTrue(result.driver_patch.changed)
            patched_driver = Path(result.script_path).read_text(encoding="utf-8")
            self.assertIn("Re=12.0ohm", patched_driver)
            self.assertIn("Le=0.10mH", patched_driver)
            self.assertIn("ExpoRe=1.4", patched_driver)
            self.assertIn("ExpoLe=0.10", patched_driver)

    def test_repair_post_ath_le_binding_mut_motor_profile_mutates_expected_parameters(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ath_root = root / "ATH"
            driver_dir = ath_root / "lib" / "drivers"
            driver_dir.mkdir(parents=True, exist_ok=True)
            (driver_dir / "generic25.txt").write_text(
                "Def_Driver 'Drv1'\n"
                "  Bl=12.5N/A\n"
                "  Mms=60g\n"
                "  Cms=0.20e-3m/N\n"
                "  Rms=1.2Ns/m\n"
                "\n"
                "System 'S1'\n"
                "  Driver 'D1' Def='Drv1' Node=1=0=10=20\n",
                encoding="utf-8",
            )
            ath_exe = ath_root / "ath.exe"
            ath_exe.write_text("stub\n", encoding="utf-8")
            abec_dir = root / "export" / "ABEC_FreeStanding"
            abec_dir.mkdir(parents=True, exist_ok=True)
            abec = abec_dir / "Project.abec"
            abec.write_text("[LEScript]\nScriptname_LEScript=\n", encoding="utf-8")

            result = repair_post_ath_le_binding(
                abec_path=abec,
                ath_executable=ath_exe,
                le_patch_profile="mut_motor",
            )
            self.assertTrue(result.ok)
            self.assertEqual(result.driver_patch.profile, "mut_motor")
            self.assertTrue(result.driver_patch.changed)
            patched_driver = Path(result.script_path).read_text(encoding="utf-8")
            self.assertIn("Bl=8.0N/A", patched_driver)
            self.assertIn("Mms=120.0g", patched_driver)
            self.assertIn("Cms=0.050e-3m/N", patched_driver)
            self.assertIn("Rms=7.0Ns/m", patched_driver)


if __name__ == "__main__":
    unittest.main()
