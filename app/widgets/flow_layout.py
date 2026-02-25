"""Simple wrap layout for compact chip rows."""

from __future__ import annotations

from typing import Optional

try:
    from PySide6.QtCore import QPoint, QRect, QSize, Qt
    from PySide6.QtWidgets import QLayout, QSizePolicy, QWidgetItem
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for FlowLayout.") from exc


class FlowLayout(QLayout):
    """A lightweight flow layout for wrapping tag/chip widgets."""

    def __init__(
        self,
        parent=None,
        *,
        margin: int = 0,
        hspacing: int = 6,
        vspacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[QWidgetItem] = []
        self._hspacing = int(hspacing)
        self._vspacing = int(vspacing)
        self.setContentsMargins(int(margin), int(margin), int(margin), int(margin))

    def __del__(self) -> None:  # pragma: no cover
        while self.count():
            self.takeAt(0)

    def addItem(self, item) -> None:  # type: ignore[override]
        self._items.append(item)

    def count(self) -> int:  # type: ignore[override]
        return len(self._items)

    def itemAt(self, index: int):  # type: ignore[override]
        if 0 <= int(index) < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):  # type: ignore[override]
        if 0 <= int(index) < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):  # type: ignore[override]
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # type: ignore[override]
        return True

    def heightForWidth(self, width: int) -> int:  # type: ignore[override]
        return self._do_layout(QRect(0, 0, int(width), 0), test_only=True)

    def setGeometry(self, rect) -> None:  # type: ignore[override]
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self):  # type: ignore[override]
        return self.minimumSize()

    def minimumSize(self):  # type: ignore[override]
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins = self.contentsMargins()
        size += QSize(int(margins.left()) + int(margins.right()), int(margins.top()) + int(margins.bottom()))
        return size

    def clear(self) -> None:
        while self.count():
            item = self.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _effective_spacing(self, widget) -> tuple[int, int]:
        hspace = int(self._hspacing)
        vspace = int(self._vspacing)
        if widget is not None and hspace < 0:
            hspace = widget.style().layoutSpacing(QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Horizontal)
        if widget is not None and vspace < 0:
            vspace = widget.style().layoutSpacing(QSizePolicy.PushButton, QSizePolicy.PushButton, Qt.Vertical)
        return (hspace, vspace)

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(
            int(margins.left()),
            int(margins.top()),
            -int(margins.right()),
            -int(margins.bottom()),
        )
        x = effective.x()
        y = effective.y()
        line_height = 0

        for item in self._items:
            widget = item.widget()
            hspace, vspace = self._effective_spacing(widget)
            item_size = item.sizeHint()
            next_x = x + item_size.width() + hspace
            if (next_x - hspace) > effective.right() and line_height > 0:
                x = effective.x()
                y = y + line_height + vspace
                next_x = x + item_size.width() + hspace
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x
            line_height = max(line_height, item_size.height())

        return int(y + line_height - rect.y() + int(margins.bottom()))
