from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliRunSampleTests(unittest.TestCase):
    @staticmethod
    def _isolated_env(tmp_dir: str) -> dict[str, str]:
        env = dict(os.environ)
        env["USERPROFILE"] = tmp_dir
        env["HOME"] = tmp_dir
        return env

    def test_run_sample_dry_run_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "library"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "run-sample",
                    "--dry-run",
                    "--library-root",
                    str(library_root),
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["mode"], "dry-run")

    def test_run_sample_real_fails_when_tools_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "library"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "run-sample",
                    "--real",
                    "--library-root",
                    str(library_root),
                ],
                env=self._isolated_env(tmp_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(result.returncode, 2, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error"], "real_run_requested_but_tools_unavailable")


if __name__ == "__main__":
    unittest.main()
