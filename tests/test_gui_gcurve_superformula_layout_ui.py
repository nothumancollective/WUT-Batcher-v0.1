from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.gui import BatchPage

try:
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None  # type: ignore[assignment]


@unittest.skipIf(QApplication is None, "PySide6 is required")
class GCurveSuperformulaLayoutUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _ancestor_with_name(self, widget, name: str):
        current = widget.parentWidget()
        while current is not None:
            if str(current.objectName() or "") == str(name):
                return current
            current = current.parentWidget()
        return None

    def test_gcurve_uses_common_and_mode_subgroup_frames(self) -> None:
        page = BatchPage()
        grid = page.parameter_form._group_grids.get("GCurve")
        self.assertIsNotNone(grid)
        assert grid is not None
        frame_items = [
            item[1]
            for item in list(grid._items)
            if str(item[0]) == "full" and str(getattr(item[1], "objectName", lambda: "")()) == "BatchSubgroupFrame"
        ]
        self.assertEqual(len(frame_items), 2)

        common_row = page.parameter_form._rows.get("GCurve.Rot")
        mode_row = page.parameter_form._rows.get("GCurve.Type")
        self.assertIsNotNone(common_row)
        self.assertIsNotNone(mode_row)
        assert common_row is not None and mode_row is not None

        common_frame = self._ancestor_with_name(common_row.container, "BatchSubgroupFrame")
        mode_frame = self._ancestor_with_name(mode_row.container, "BatchSubgroupFrame")
        self.assertIsNotNone(common_frame)
        self.assertIsNotNone(mode_frame)
        self.assertIsNot(common_frame, mode_frame)


if __name__ == "__main__":
    unittest.main()
