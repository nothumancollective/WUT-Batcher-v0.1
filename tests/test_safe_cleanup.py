from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from app.safe_cleanup import guarded_delete_tree


class SafeCleanupTests(unittest.TestCase):
    def test_deletes_only_inside_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "versions"
            target = root / "V001" / "ath_work"
            target.mkdir(parents=True, exist_ok=True)
            (target / "temp.txt").write_text("x", encoding="utf-8")

            result = guarded_delete_tree(target, allowed_root=root, deny_paths=(root.parent,))
            self.assertTrue(result.deleted)
            self.assertFalse(target.exists())

    def test_rejects_delete_of_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "versions"
            root.mkdir(parents=True, exist_ok=True)
            result = guarded_delete_tree(root, allowed_root=root)
            self.assertFalse(result.deleted)
            self.assertEqual(result.reason, "target_equals_allowed_root")

    def test_rejects_outside_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "versions"
            root.mkdir(parents=True, exist_ok=True)
            outside = Path(tmp_dir) / "outside" / "ath_work"
            outside.mkdir(parents=True, exist_ok=True)

            result = guarded_delete_tree(outside, allowed_root=root)
            self.assertFalse(result.deleted)
            self.assertEqual(result.reason, "outside_allowed_root")


if __name__ == "__main__":
    unittest.main()
