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

    def test_superformula_gap_cell_is_present_in_gcurve_grid(self) -> None:
        page = BatchPage()
        grid = page.parameter_form._group_grids.get("GCurve")
        self.assertIsNotNone(grid)
        assert grid is not None
        gap_items = [item for item in list(grid._items) if str(item[0]) == "gap"]
        self.assertGreaterEqual(len(gap_items), 1)


if __name__ == "__main__":
    unittest.main()

