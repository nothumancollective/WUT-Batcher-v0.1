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


if __name__ == "__main__":
    unittest.main()
