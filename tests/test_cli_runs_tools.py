from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CliRunsToolsTests(unittest.TestCase):
    @staticmethod
    def _isolated_env(tmp_dir: str) -> dict[str, str]:
        env = dict(os.environ)
        env["USERPROFILE"] = tmp_dir
        env["HOME"] = tmp_dir
        return env

    def test_pin_unpin_and_cleanup_preview(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            library_root = Path(tmp_dir) / "library"
            env = self._isolated_env(tmp_dir)

            run_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "run-sample",
                    "--dry-run",
                    "--library-root",
                    str(library_root),
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(run_result.returncode, 0, msg=run_result.stdout + "\n" + run_result.stderr)
            run_payload = json.loads(run_result.stdout)
            project_id = str(run_payload["project_id"])
            run_id = str(run_payload["runtime_summary"]["run_id"])

            pin_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runs",
                    "pin",
                    run_id,
                    "--project-id",
                    project_id,
                    "--tag",
                    "baseline",
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(pin_result.returncode, 0, msg=pin_result.stdout + "\n" + pin_result.stderr)

            cleanup_preview = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runs",
                    "cleanup-testdata",
                    "--project-id",
                    project_id,
                    "--dry-run",
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(cleanup_preview.returncode, 0, msg=cleanup_preview.stdout + "\n" + cleanup_preview.stderr)
            preview_payload = json.loads(cleanup_preview.stdout)
            self.assertEqual(int(preview_payload["aggregate_counts"]["runs"]), 0)

            unpin_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runs",
                    "unpin",
                    run_id,
                    "--project-id",
                    project_id,
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(unpin_result.returncode, 0, msg=unpin_result.stdout + "\n" + unpin_result.stderr)

            cleanup_preview2 = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app",
                    "runs",
                    "cleanup-testdata",
                    "--project-id",
                    project_id,
                    "--dry-run",
                ],
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(cleanup_preview2.returncode, 0, msg=cleanup_preview2.stdout + "\n" + cleanup_preview2.stderr)
            preview_payload2 = json.loads(cleanup_preview2.stdout)
            self.assertGreaterEqual(int(preview_payload2["aggregate_counts"]["runs"]), 1)


if __name__ == "__main__":
    unittest.main()

