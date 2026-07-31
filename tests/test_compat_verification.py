from __future__ import annotations

from contextlib import closing
import csv
import io
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from app.compat_verification import run_compat_verification


class CompatVerificationHarnessTests(unittest.TestCase):
    def test_default_mode_skips_doc_backed_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P_COMPAT"
            summary = run_compat_verification(
                project_root=project_root,
                project_id="P_COMPAT",
                ath_executable=None,
                persist_sql=False,
                only_hypothesis=True,
                mode="quick",
            )
            self.assertEqual(summary["status_counts"]["fail"], 0)
            self.assertGreaterEqual(summary["status_counts"]["skipped"], 1)
            self.assertFalse((project_root.parent / "library.sqlite").exists())

    def test_all_cases_can_run_with_stubbed_ath_and_write_sql(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            project_root = Path(tmp_dir) / "projects" / "P_COMPAT"
            stub_path = Path(tmp_dir) / "fake_ath.py"
            stub_path.write_text(
                textwrap.dedent(
                    """
                    import re
                    import sys
                    from pathlib import Path

                    cfg = Path(sys.argv[-1])
                    text = cfg.read_text(encoding="utf-8")
                    ath_cfg = Path.cwd() / "ath.cfg"
                    ath_text = ath_cfg.read_text(encoding="utf-8")
                    match = re.search(r'OutputRootDir\\s*=\\s*"([^"]+)"', ath_text)
                    out_root = Path(match.group(1)) if match else (Path.cwd() / "out")
                    sub = out_root / cfg.stem
                    sub.mkdir(parents=True, exist_ok=True)
                    if re.search(r'Output\\.STL\\s*=\\s*1\\b', text):
                        (sub / "mesh.stl").write_text("stub", encoding="utf-8")
                    if re.search(r'Output\\.ABECProject\\s*=\\s*1\\b', text):
                        (sub / "Project.abec").write_text("stub", encoding="utf-8")
                    print("Final length = 100.0 mm")
                    """
                ),
                encoding="utf-8",
            )
            summary = run_compat_verification(
                project_root=project_root,
                project_id="P_COMPAT",
                ath_executable=sys.executable,
                ath_base_args=[str(stub_path)],
                persist_sql=True,
                only_hypothesis=False,
                mode="quick",
            )
            self.assertEqual(summary["status_counts"]["fail"], 0)
            self.assertGreaterEqual(summary["status_counts"]["pass"], 5)

            db_path = Path(str(summary["sql_result"]["project_db_path"]))
            self.assertEqual(Path(str(summary["sql_result"]["global_db_path"])), Path(tmp_dir) / "library.sqlite")
            self.assertFalse((project_root.parent / "library.sqlite").exists())
            with closing(sqlite3.connect(str(db_path))) as conn:
                count = conn.execute("SELECT COUNT(*) FROM compat_verification_results").fetchone()[0]
            self.assertEqual(int(count), int(summary["status_counts"]["pass"]))

    @unittest.skipUnless(sys.platform.startswith("win"), "Windows-only process-tree timeout test")
    def test_timeout_kills_ath_children_and_still_writes_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            project_root = root / "projects" / "P_COMPAT"
            pid_log = root / "child_pids.txt"
            stub_path = root / "hanging_ath.py"
            stub_path.write_text(
                textwrap.dedent(
                    """
                    import subprocess
                    import sys
                    import time
                    from pathlib import Path

                    pid_log = Path(sys.argv[1])
                    child = subprocess.Popen(
                        [sys.executable, "-c", "import time; time.sleep(60)"]
                    )
                    with pid_log.open("a", encoding="utf-8") as handle:
                        handle.write(f"{child.pid}\\n")
                    time.sleep(60)
                    """
                ),
                encoding="utf-8",
            )

            started = time.monotonic()
            summary = run_compat_verification(
                project_root=project_root,
                project_id="P_COMPAT",
                ath_executable=sys.executable,
                ath_base_args=[str(stub_path), str(pid_log)],
                timeout_s=1,
                persist_sql=False,
                only_hypothesis=False,
                mode="quick",
            )
            elapsed = time.monotonic() - started

            self.assertLess(elapsed, 20.0)
            self.assertEqual(summary["case_count"], 6)
            self.assertEqual(summary["status_counts"]["fail"], 6)
            self.assertTrue(Path(summary["report_path"]).is_file())
            child_pids = [int(value) for value in pid_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(child_pids), 6)
            self.assertTrue(all(not _windows_pid_exists(pid) for pid in child_pids))


def _windows_pid_exists(pid: int) -> bool:
    result = subprocess.run(
        ["tasklist", "/FI", f"PID eq {int(pid)}", "/FO", "CSV", "/NH"],
        capture_output=True,
        text=True,
        check=False,
    )
    for row in csv.reader(io.StringIO(str(result.stdout or ""))):
        if len(row) < 2:
            continue
        raw_pid = str(row[1] or "").strip().strip('"')
        if raw_pid.isdigit() and int(raw_pid) == int(pid):
            return True
    return False


if __name__ == "__main__":
    unittest.main()

