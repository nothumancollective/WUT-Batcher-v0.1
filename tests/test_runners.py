from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

from app.runners import AthRunner, parse_ath_dimensions


class RunnerTests(unittest.TestCase):
    def test_ath_runner_logs_and_dimension_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            logs_dir = Path(tmp_dir) / "logs"
            cfg_path = Path(tmp_dir) / "input.cfg"
            cfg_path.write_text("; cfg\n", encoding="utf-8")

            runner = AthRunner(
                executable=sys.executable,
                base_args=["-c", "print('Length=320.5 Width=280.1 Height=140.0')"],
            )
            result = runner.run_cfg(cfg_path, version_logs_dir=logs_dir)
            self.assertTrue(result.ok)
            self.assertTrue(Path(result.stdout_log).exists())
            self.assertTrue(Path(result.stderr_log).exists())

            stdout_text = Path(result.stdout_log).read_text(encoding="utf-8")
            parsed = parse_ath_dimensions(stdout_text)
            self.assertEqual(parsed.horn_length_mm, 320.5)
            self.assertEqual(parsed.horn_width_mm, 280.1)
            self.assertEqual(parsed.horn_height_mm, 140.0)
            self.assertIn("Length=320.5", parsed.raw_line)


if __name__ == "__main__":
    unittest.main()
