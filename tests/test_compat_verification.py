from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import textwrap
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
            )
            self.assertEqual(summary["status_counts"]["fail"], 0)
            self.assertGreaterEqual(summary["status_counts"]["skipped"], 1)

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
            )
            self.assertEqual(summary["status_counts"]["fail"], 0)
            self.assertEqual(summary["status_counts"]["pass"], 3)

            db_path = project_root / "dataset" / "project.sqlite"
            with closing(sqlite3.connect(str(db_path))) as conn:
                count = conn.execute("SELECT COUNT(*) FROM compat_verification_results").fetchone()[0]
            self.assertEqual(int(count), 3)


if __name__ == "__main__":
    unittest.main()

