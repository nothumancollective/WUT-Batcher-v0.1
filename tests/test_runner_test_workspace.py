from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.runner_test_workspace import resolve_runner_test_workspace
from app.safe_cleanup import guarded_delete_file_in_workspace, guarded_delete_tree_in_workspace


class RunnerTestWorkspaceTests(unittest.TestCase):
    def test_resolve_workspace_creates_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "runner_test_workspace"
            workspace = resolve_runner_test_workspace(root)
            self.assertTrue(workspace.root.is_absolute())
            self.assertTrue(workspace.cfg_dir.exists())
            self.assertTrue(workspace.ath_out_dir.exists())
            self.assertTrue(workspace.exports_dir.exists())
            self.assertTrue(workspace.logs_dir.exists())
            self.assertTrue(workspace.db_dir.exists())
            self.assertEqual(workspace.db_path.parent, workspace.db_dir)

    def test_workspace_guard_rejects_relative_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = resolve_runner_test_workspace(Path(tmp_dir) / "runner_test_workspace")
            result = guarded_delete_tree_in_workspace(
                "runner_test_workspace\\ath_out\\V001",
                workspace_root=workspace.root,
            )
            self.assertFalse(result.deleted)
            self.assertEqual(result.reason, "target_not_absolute")

    def test_workspace_guard_deletes_only_inside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = resolve_runner_test_workspace(Path(tmp_dir) / "runner_test_workspace")
            target = workspace.ath_out_dir / "V001"
            target.mkdir(parents=True, exist_ok=True)
            (target / "artifact.txt").write_text("x", encoding="utf-8")

            result = guarded_delete_tree_in_workspace(
                target,
                workspace_root=workspace.root,
                expected_parent_name="ath_out",
                expected_dir_name="V001",
            )
            self.assertTrue(result.deleted)
            self.assertFalse(target.exists())

    def test_workspace_guard_rejects_outside_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = resolve_runner_test_workspace(Path(tmp_dir) / "runner_test_workspace")
            outside = Path(tmp_dir) / "outside" / "V001"
            outside.mkdir(parents=True, exist_ok=True)

            result = guarded_delete_tree_in_workspace(
                outside.resolve(),
                workspace_root=workspace.root,
            )
            self.assertFalse(result.deleted)
            self.assertEqual(result.reason, "outside_workspace_root")

    def test_workspace_guard_rejects_unexpected_parent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = resolve_runner_test_workspace(Path(tmp_dir) / "runner_test_workspace")
            target = workspace.logs_dir / "V001"
            target.mkdir(parents=True, exist_ok=True)

            result = guarded_delete_tree_in_workspace(
                target.resolve(),
                workspace_root=workspace.root,
                expected_parent_name="ath_out",
            )
            self.assertFalse(result.deleted)
            self.assertEqual(result.reason, "unexpected_parent_name")

    def test_workspace_file_guard_deletes_cfg_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = resolve_runner_test_workspace(Path(tmp_dir) / "runner_test_workspace")
            cfg_file = workspace.cfg_dir / "case.cfg"
            cfg_file.write_text("Length = 120\n", encoding="utf-8")

            result = guarded_delete_file_in_workspace(
                cfg_file.resolve(),
                workspace_root=workspace.root,
                expected_parent_name="cfg",
            )
            self.assertTrue(result.deleted)
            self.assertFalse(cfg_file.exists())


if __name__ == "__main__":
    unittest.main()
