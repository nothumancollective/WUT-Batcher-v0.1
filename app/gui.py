"""PySide6 GUI orchestrator for WUT Batcher."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Dict, List, Optional

from app.doctor_service import run_doctor_checks
from app.constants import DEFAULT_RUNNER_MODE
from app.models import AppConfig, Batch, Project
from app.services import OrchestratorService
from app.settings_store import UserSettings
from app.ui_validation import UiValidationEngine
from ui.form_builder import ParameterForm
from ui.form_metrics import FORM_METRICS
from ui.form_schema import build_project_form_schema
from ui.theme import apply_theme, apply_windows_dark_titlebar, configure_windows_qt_darkmode_env

try:
    from PySide6.QtCore import QPoint, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPixmap
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QComboBox,
        QCheckBox,
        QDialog,
        QFormLayout,
        QFrame,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QInputDialog,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QSplashScreen,
        QStackedWidget,
        QStatusBar,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for GUI mode. Install it with 'pip install PySide6'.") from exc


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        super().mousePressEvent(event)
        if event.button() == Qt.LeftButton:
            self.clicked.emit()


def _parse_json_object(text: str) -> Dict[str, Any]:
    raw = text.strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _severity_rank(value: str) -> int:
    order = {"fatal": 0, "warn": 1, "info": 2}
    return order.get(str(value).lower(), 99)


def _highest_issue_severity(issues: List[Dict[str, Any]]) -> str:
    if not issues:
        return ""
    ranked = sorted((str(item.get("severity", "info")).lower() for item in issues), key=_severity_rank)
    return ranked[0] if ranked else ""


def _status_entries(detail: str) -> List[Dict[str, str]]:
    def _humanize_rule_id(value: str) -> str:
        token = str(value or "").strip()
        if not token:
            return "Issue"
        return token.replace("_", " ").replace(".", " ").strip().title()

    raw = str(detail or "").strip()
    if not raw:
        return [{"severity": "info", "title": "Status", "text": "No details available."}]

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return [{"severity": "info", "title": "Status", "text": raw}]

    entries: List[Dict[str, str]] = []
    if isinstance(payload, dict):
        overall = str(payload.get("overall_status", "")).strip().lower()
        if overall:
            overall_map = {"ok": "ok", "warn": "warn", "fail": "fatal"}
            entries.append(
                {
                    "severity": overall_map.get(overall, "info"),
                    "title": "Doctor Overall",
                    "text": f"Overall status: {overall.upper()}",
                }
            )
        checks = payload.get("checks")
        if isinstance(checks, list):
            for item in checks:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status", "")).strip().lower()
                severity_map = {"ok": "ok", "warn": "warn", "fail": "fatal"}
                entries.append(
                    {
                        "severity": severity_map.get(status, "info"),
                        "title": str(item.get("label", "Check")).strip() or "Check",
                        "text": str(item.get("detail", "")).strip() or "No detail.",
                    }
                )
        issues = payload.get("issues")
        if isinstance(issues, list):
            for item in issues:
                if not isinstance(item, dict):
                    continue
                entries.append(
                    {
                        "severity": str(item.get("severity", "info")).strip().lower(),
                        "title": _humanize_rule_id(str(item.get("rule_id", "Issue"))),
                        "text": str(item.get("message", "")).strip() or "No detail.",
                    }
                )
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                entries.append(
                    {
                        "severity": str(item.get("severity", "info")).strip().lower(),
                        "title": _humanize_rule_id(str(item.get("rule_id", "Issue"))),
                        "text": str(item.get("message", "")).strip() or str(item),
                    }
                )
            else:
                entries.append({"severity": "info", "title": "Status", "text": str(item)})

    if not entries:
        entries.append({"severity": "info", "title": "Status", "text": raw})
    return entries


def _win32_force_foreground(window: QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        hwnd = int(window.winId())
        SW_MAXIMIZE = 3
        SW_SHOWNORMAL = 1
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        HWND_TOPMOST = -1
        HWND_NOTOPMOST = -2
        is_maximized = bool(window.windowState() & Qt.WindowMaximized)
        user32.ShowWindow(hwnd, SW_MAXIMIZE if is_maximized else SW_SHOWNORMAL)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        return


def _ensure_maximized_foreground(window: QWidget) -> None:
    if window is None:
        return
    state = window.windowState()
    state = (state | Qt.WindowMaximized) & ~Qt.WindowFullScreen & ~Qt.WindowMinimized
    window.setWindowState(state)
    window.showMaximized()
    window.raise_()
    window.activateWindow()
    app = QApplication.instance()
    if app is not None:
        app.setActiveWindow(window)
    _win32_force_foreground(window)


def _ensure_normal_foreground(window: QWidget) -> None:
    if window is None:
        return
    state = window.windowState()
    state = state & ~Qt.WindowFullScreen & ~Qt.WindowMinimized & ~Qt.WindowMaximized
    window.setWindowState(state)
    window.showNormal()
    window.raise_()
    window.activateWindow()
    app = QApplication.instance()
    if app is not None:
        app.setActiveWindow(window)
    _win32_force_foreground(window)


def _center_window(window: QWidget) -> None:
    app = QApplication.instance()
    if app is None:
        return
    screen = window.screen() or app.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    frame = window.frameGeometry()
    frame.moveCenter(area.center())
    window.move(frame.topLeft())


class CompatibilityPanel(QGroupBox):
    request_show_details = Signal()

    def __init__(self, title: str = "Compatibility") -> None:
        super().__init__(title)
        root = QVBoxLayout(self)

        counts = QHBoxLayout()
        self.visible_count = QLabel("Visible fields: 0")
        self.locked_count = QLabel("Locked fields: 0")
        self.sweepable_count = QLabel("Sweepable fields: 0")
        counts.addWidget(self.visible_count)
        counts.addWidget(self.locked_count)
        counts.addWidget(self.sweepable_count)
        counts.addStretch(1)
        root.addLayout(counts)

        lists = QHBoxLayout()
        self.visible_list = QListWidget()
        self.visible_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.locked_list = QListWidget()
        self.locked_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.locked_list.setEnabled(False)
        self.locked_list.setToolTip("Locked by runner mode")
        lists.addWidget(self._wrap_list("Visible", self.visible_list), 2)
        lists.addWidget(self._wrap_list("Locked by runner mode", self.locked_list), 1)
        root.addLayout(lists)

        self.summary = QLabel("No issues.")
        self.summary.setWordWrap(True)
        self.summary.setObjectName("IssueHint")
        root.addWidget(self.summary)

        self.show_details_btn = QPushButton("Show details")
        self.show_details_btn.clicked.connect(self.request_show_details.emit)
        root.addWidget(self.show_details_btn, alignment=Qt.AlignLeft)

        self._issues: List[Dict[str, Any]] = []
        self._update_lists([], [], [])

    def _wrap_list(self, label: str, widget: QListWidget) -> QWidget:
        box = QGroupBox(label)
        layout = QVBoxLayout(box)
        layout.addWidget(widget)
        return box

    def _update_lists(self, visible: List[str], locked: List[str], sweepable: List[str]) -> None:
        self.visible_list.clear()
        self.locked_list.clear()
        for key in visible:
            self.visible_list.addItem(QListWidgetItem(key))
        for key in locked:
            item = QListWidgetItem(key)
            item.setToolTip("Locked by runner mode")
            self.locked_list.addItem(item)
        self.visible_count.setText(f"Visible fields: {len(visible)}")
        self.locked_count.setText(f"Locked fields: {len(locked)}")
        self.sweepable_count.setText(f"Sweepable fields: {len(sweepable)}")

    def update_state(self, state: Dict[str, Any]) -> None:
        visible = sorted(str(item) for item in list(state.get("visible_keys", []) or []))
        locked = sorted(str(item) for item in list(state.get("locked_keys", []) or []))
        sweepable = sorted(str(item) for item in list(state.get("sweepable_keys", []) or []))
        issues = [item for item in list(state.get("issues", []) or []) if isinstance(item, dict)]
        self._issues = issues
        self._update_lists(visible, locked, sweepable)

        top = issues[:5]
        if not top:
            self.summary.setText("No validation issues.")
            self.summary.setProperty("severity", "")
            self.show_details_btn.setEnabled(False)
        else:
            lines = []
            for issue in top:
                severity = str(issue.get("severity", "info")).upper()
                rule_id = str(issue.get("rule_id", "unknown_rule"))
                evidence_type = str(issue.get("evidence_type", "hypothesis"))
                message = str(issue.get("message", ""))
                lines.append(f"[{severity}] {rule_id} ({evidence_type}) - {message}")
            self.summary.setText("\n".join(lines))
            self.summary.setProperty("severity", _highest_issue_severity(issues))
            self.show_details_btn.setEnabled(True)
        self.style().unpolish(self.summary)
        self.style().polish(self.summary)

    def issues(self) -> List[Dict[str, Any]]:
        return list(self._issues)


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About WUT Batcher")
        self.setModal(True)
        self.resize(360, 220)

        layout = QVBoxLayout(self)
        logo = QLabel("[ LOGO ]")
        logo.setAlignment(Qt.AlignCenter)
        logo.setObjectName("SectionTitle")
        layout.addWidget(logo)

        version = QLabel("Version: 0.1-rebuild")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)

        author = QLabel("Entwickelt von Maximilian Heinze")
        author.setAlignment(Qt.AlignCenter)
        layout.addWidget(author)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class StatusDetailDialog(QDialog):
    def __init__(self, detail_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setWindowTitle("Status")
        self.resize(760, 520)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("framelessShell", True)
        self._drag_offset: Optional[QPoint] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("FramelessShell")
        outer.addWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title_bar = QWidget()
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        icon = QLabel("●")
        icon.setObjectName("StatusSymbol")
        title_row.addWidget(icon)
        title = QLabel("Status Details")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_btn = QPushButton("X")
        close_btn.setObjectName("WindowCloseButton")
        close_btn.setFixedSize(28, 24)
        close_btn.clicked.connect(self.accept)
        title_row.addWidget(close_btn, alignment=Qt.AlignRight)
        root.addWidget(title_bar)
        title_bar.mousePressEvent = self._title_mouse_press  # type: ignore[assignment]
        title_bar.mouseMoveEvent = self._title_mouse_move  # type: ignore[assignment]
        title_bar.mouseReleaseEvent = self._title_mouse_release  # type: ignore[assignment]

        scroll = QListWidget()
        scroll.setSelectionMode(QAbstractItemView.NoSelection)
        entries = _status_entries(detail_text)
        for entry in entries:
            sev = str(entry.get("severity", "info")).lower()
            title_text = str(entry.get("title", "Status"))
            body_text = str(entry.get("text", ""))
            item = QListWidgetItem()
            row_widget = QWidget()
            row_layout = QVBoxLayout(row_widget)
            row_layout.setContentsMargins(10, 8, 10, 8)
            row_layout.setSpacing(4)

            title_label = QLabel(title_text)
            title_label.setObjectName("SectionTitle")
            body_label = QLabel(body_text)
            body_label.setWordWrap(True)
            body_label.setObjectName("IssueHint")
            body_label.setProperty("severity", sev if sev in {"fatal", "warn", "ok"} else "")
            row_layout.addWidget(title_label)
            row_layout.addWidget(body_label)

            item.setSizeHint(row_widget.sizeHint())
            scroll.addItem(item)
            scroll.setItemWidget(item, row_widget)
        root.addWidget(scroll, 1)

    def _title_mouse_press(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def _title_mouse_move(self, event) -> None:  # type: ignore[override]
        if self._drag_offset is None:
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        self.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def _title_mouse_release(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        event.accept()


class SettingsDialog(QDialog):
    settings_saved = Signal(dict)

    def __init__(self, service: OrchestratorService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.resize(560, 260)

        self.library_root = QLineEdit()
        self.ath_exe = QLineEdit()
        self.akabak_exe = QLineEdit()
        self.vacs_exe = QLineEdit()
        self.template_cfg = QLineEdit()

        form = QFormLayout()
        form.addRow("Library Folder", self.library_root)
        form.addRow("ATH", self.ath_exe)
        form.addRow("AKABAK", self.akabak_exe)
        form.addRow("VACS", self.vacs_exe)
        form.addRow("Template CFG", self.template_cfg)

        save_btn = QPushButton("Save")
        save_btn.setObjectName("PrimaryButton")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(save_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(buttons)

        self._load()

    def _load(self) -> None:
        settings = self.service.settings
        self.library_root.setText(settings.library_root)
        self.ath_exe.setText(settings.ath_exe or "")
        self.akabak_exe.setText(settings.akabak_exe or "")
        self.vacs_exe.setText(settings.vacs_exe or "")
        self.template_cfg.setText(settings.template_cfg or "")

    def _save(self) -> None:
        settings = UserSettings(
            library_root=self.library_root.text().strip(),
            ath_exe=self.ath_exe.text().strip() or None,
            akabak_exe=self.akabak_exe.text().strip() or None,
            vacs_exe=self.vacs_exe.text().strip() or None,
            template_cfg=self.template_cfg.text().strip() or None,
        )
        result = self.service.save_settings(settings)
        issues = result.get("validation", {})
        self.settings_saved.emit(result)
        if issues:
            detail = "\n".join(f"- {key}: {value}" for key, value in issues.items())
            QMessageBox.warning(self, "Settings saved with warnings", detail)
        self.accept()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class ExportDialog(QDialog):
    def __init__(self, versions_by_batch: Dict[str, List[str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.versions_by_batch = versions_by_batch
        self.setWindowTitle("Export Version")
        self.setModal(True)
        self.resize(420, 220)

        self.batch_combo = QComboBox()
        self.version_combo = QComboBox()
        self.export_stl = QCheckBox("STL")
        self.export_abec = QCheckBox("ABEC")
        self.export_abec.setChecked(True)

        for batch_id in sorted(self.versions_by_batch.keys()):
            self.batch_combo.addItem(batch_id)

        form = QFormLayout()
        form.addRow("Batch", self.batch_combo)
        form.addRow("Version", self.version_combo)
        form.addRow("Export STL", self.export_stl)
        form.addRow("Export ABEC", self.export_abec)

        self.batch_combo.currentTextChanged.connect(self._reload_versions)
        self._reload_versions(self.batch_combo.currentText())

        export_btn = QPushButton("Export")
        export_btn.setObjectName("PrimaryButton")
        export_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(export_btn)

        root = QVBoxLayout(self)
        root.addLayout(form)
        root.addLayout(buttons)

    def _reload_versions(self, batch_id: str) -> None:
        self.version_combo.clear()
        for version_id in self.versions_by_batch.get(batch_id, []):
            self.version_combo.addItem(version_id)

    def payload(self) -> Dict[str, object]:
        return {
            "batch_id": self.batch_combo.currentText().strip(),
            "version_id": self.version_combo.currentText().strip(),
            "export_stl": self.export_stl.isChecked(),
            "export_abec": self.export_abec.isChecked(),
        }

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class RunManagerDialog(QDialog):
    def __init__(self, service: OrchestratorService, project_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.setWindowTitle("Runs verwalten")
        self.setModal(True)
        self.resize(760, 420)

        self.batch_filter = QComboBox()
        self.run_list = QListWidget()
        self.run_list.setSelectionMode(QAbstractItemView.SingleSelection)

        refresh_btn = QPushButton("Refresh")
        pin_btn = QPushButton("Pin")
        pin_btn.setToolTip("Markiert einen Run als Ergebnis, das behalten werden soll.")
        unpin_btn = QPushButton("Unpin")
        close_btn = QPushButton("Close")

        top = QFormLayout()
        top.addRow("Batch Filter", self.batch_filter)

        actions = QHBoxLayout()
        actions.addWidget(refresh_btn)
        actions.addWidget(pin_btn)
        actions.addWidget(unpin_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self.run_list, 1)
        root.addLayout(actions)

        refresh_btn.clicked.connect(self._reload_runs)
        pin_btn.clicked.connect(self._pin_selected)
        unpin_btn.clicked.connect(self._unpin_selected)
        close_btn.clicked.connect(self.accept)
        self.batch_filter.currentTextChanged.connect(lambda _: self._reload_runs())

        self._reload_batches()
        self._reload_runs()

    def _reload_batches(self) -> None:
        self.batch_filter.clear()
        self.batch_filter.addItem("(all)")
        for batch in self.service.repo.list_batches(self.project_id):
            self.batch_filter.addItem(batch.batch_id)

    def _selected_run_id(self) -> Optional[str]:
        item = self.run_list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return str(value) if value else None

    def _reload_runs(self) -> None:
        self.run_list.clear()
        batch_text = self.batch_filter.currentText().strip()
        batch_id = None if batch_text in {"", "(all)"} else batch_text
        rows = self.service.list_runs(project_id=self.project_id, batch_id=batch_id)
        for row in rows:
            status = str(row.get("status", ""))
            pinned = bool(row.get("pinned", False))
            tag = str(row.get("tag") or "")
            pin_flag = "PINNED" if pinned else "unpinned"
            tag_text = f" [{tag}]" if tag else ""
            label = f"{row['run_id']} | {row['batch_id']} | {status} | {pin_flag}{tag_text}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, str(row["run_id"]))
            self.run_list.addItem(item)

    def _pin_selected(self) -> None:
        run_id = self._selected_run_id()
        if not run_id:
            return
        tag, ok = QInputDialog.getText(self, "Run pinnen", "Tag (optional):")
        if not ok:
            return
        self.service.pin_run(project_id=self.project_id, run_id=run_id, tag=tag.strip() or None)
        self._reload_runs()

    def _unpin_selected(self) -> None:
        run_id = self._selected_run_id()
        if not run_id:
            return
        self.service.unpin_run(project_id=self.project_id, run_id=run_id)
        self._reload_runs()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class CleanupTestDataDialog(QDialog):
    def __init__(self, service: OrchestratorService, project_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.setWindowTitle("Testdaten aufraeumen")
        self.setModal(True)
        self.resize(760, 500)
        self._last_preview: Dict[str, Any] = {}

        info = QLabel("Behalten: angeheftete Runs. Loeschen: alle anderen Runs (Testdaten).")
        info.setWordWrap(True)

        self.delete_exports = QCheckBox("Exportdateien ebenfalls loeschen (empfohlen)")
        self.delete_exports.setChecked(True)

        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)

        self.confirm_input = QLineEdit()
        self.confirm_input.setPlaceholderText("Type DELETE to confirm")

        preview_btn = QPushButton("Preview")
        cleanup_btn = QPushButton("Cleanup")
        cleanup_btn.setObjectName("PrimaryButton")
        cancel_btn = QPushButton("Cancel")

        actions = QHBoxLayout()
        actions.addWidget(preview_btn)
        actions.addWidget(cleanup_btn)
        actions.addStretch(1)
        actions.addWidget(cancel_btn)

        root = QVBoxLayout(self)
        root.addWidget(info)
        root.addWidget(self.delete_exports)
        root.addWidget(self.preview_text, 1)
        root.addWidget(QLabel("Confirmation"))
        root.addWidget(self.confirm_input)
        root.addLayout(actions)

        preview_btn.clicked.connect(self._preview)
        cleanup_btn.clicked.connect(self._cleanup)
        cancel_btn.clicked.connect(self.reject)
        self._preview()

    def _preview(self) -> None:
        result = self.service.cleanup_test_data(
            project_id=self.project_id,
            delete_exports=self.delete_exports.isChecked(),
            dry_run=True,
        )
        self._last_preview = result
        run_ids = list(result.get("run_ids", []))
        counts = dict(result.get("counts", {}) or {})
        lines = [
            f"Project: {self.project_id}",
            f"Runs to delete: {len(run_ids)}",
            f"Counts: {json.dumps(counts, ensure_ascii=False)}",
            "",
            "Run IDs:",
            *[f"- {run_id}" for run_id in run_ids],
        ]
        self.preview_text.setPlainText("\n".join(lines))

    def _cleanup(self) -> None:
        if self.confirm_input.text().strip() != "DELETE":
            QMessageBox.warning(self, "Confirmation required", 'Type "DELETE" to continue.')
            return
        result = self.service.cleanup_test_data(
            project_id=self.project_id,
            delete_exports=self.delete_exports.isChecked(),
            dry_run=False,
        )
        self._last_preview = result
        QMessageBox.information(
            self,
            "Cleanup finished",
            f"Deleted runs: {len(list(result.get('run_ids', [])))}\nAudit: {result.get('audit_log')}",
        )
        self.accept()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        apply_windows_dark_titlebar(self)


class DashboardPage(QWidget):
    request_new_batch = Signal()
    request_edit_batch = Signal(str)
    request_clone_batch = Signal(str)
    request_open_export_dialog = Signal()
    request_manage_runs = Signal()
    request_cleanup_testdata = Signal()
    request_settings = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)

        title = QLabel("DASHBOARD")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.constraints_summary = QTextEdit()
        self.constraints_summary.setReadOnly(True)
        self.constraints_summary.setPlaceholderText("Constraints summary")
        root.addWidget(self.constraints_summary)

        self.batch_list = QListWidget()
        root.addWidget(self.batch_list, 1)

        actions = QHBoxLayout()
        self.new_batch_btn = QPushButton("New Batch")
        self.edit_batch_btn = QPushButton("Edit Batch")
        self.clone_batch_btn = QPushButton("Clone Batch")
        actions.addWidget(self.new_batch_btn)
        actions.addWidget(self.edit_batch_btn)
        actions.addWidget(self.clone_batch_btn)
        actions.addStretch(1)
        root.addLayout(actions)

        export_box = QGroupBox("Export")
        export_grid = QGridLayout(export_box)
        self.export_btn = QPushButton("Open Export Dialog")
        self.manage_runs_btn = QPushButton("Runs verwalten...")
        self.cleanup_testdata_btn = QPushButton("Testdaten aufraeumen...")
        export_grid.addWidget(self.export_btn, 0, 0)
        export_grid.addWidget(self.manage_runs_btn, 0, 1)
        export_grid.addWidget(self.cleanup_testdata_btn, 0, 2)
        root.addWidget(export_box)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.settings_btn = QPushButton("Settings")
        footer.addWidget(self.settings_btn)
        root.addLayout(footer)

        self.new_batch_btn.clicked.connect(self.request_new_batch.emit)
        self.edit_batch_btn.clicked.connect(self._emit_edit)
        self.clone_batch_btn.clicked.connect(self._emit_clone)
        self.export_btn.clicked.connect(self.request_open_export_dialog.emit)
        self.manage_runs_btn.clicked.connect(self.request_manage_runs.emit)
        self.cleanup_testdata_btn.clicked.connect(self.request_cleanup_testdata.emit)
        self.settings_btn.clicked.connect(self.request_settings.emit)

    def _selected_batch_id(self) -> Optional[str]:
        item = self.batch_list.currentItem()
        if item is None:
            return None
        data = item.data(Qt.UserRole)
        return str(data) if data else None

    def _emit_edit(self) -> None:
        batch_id = self._selected_batch_id()
        if batch_id:
            self.request_edit_batch.emit(batch_id)

    def _emit_clone(self) -> None:
        batch_id = self._selected_batch_id()
        if batch_id:
            self.request_clone_batch.emit(batch_id)

class ProjectPage(QWidget):
    submit_project = Signal(str, dict)
    draft_changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 12, 24, 16)
        root.setSpacing(12)
        title = QLabel("PROJECT")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        form_column_width = (2 * FORM_METRICS.label_width) + (2 * FORM_METRICS.input_width) + FORM_METRICS.column_gap + 32
        self._form_column_width = form_column_width

        name_row = QHBoxLayout()
        name_row.setContentsMargins(0, 0, 0, 0)
        name_row.setSpacing(10)
        name_row.addStretch(1)
        left_col = QWidget()
        left_col.setFixedWidth(form_column_width)
        left_col_layout = QVBoxLayout(left_col)
        left_col_layout.setContentsMargins(0, 0, 0, 0)
        left_col_layout.setSpacing(6)
        name_label = QLabel("Project Name")
        name_label.setObjectName("InputCaption")
        left_col_layout.addWidget(name_label)
        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("Project Name")
        self.project_name.setFixedWidth(form_column_width)
        left_col_layout.addWidget(self.project_name, 0, Qt.AlignLeft)
        name_row.addWidget(left_col, 0, Qt.AlignTop)
        right_col_spacer = QWidget()
        right_col_spacer.setFixedWidth(form_column_width)
        name_row.addWidget(right_col_spacer, 0, Qt.AlignTop)
        name_row.addStretch(1)
        root.addLayout(name_row)

        self.summary_panel = QFrame()
        self.summary_panel.setObjectName("ProjectSummaryPanel")
        summary_layout = QVBoxLayout(self.summary_panel)
        summary_layout.setContentsMargins(12, 10, 12, 10)
        summary_layout.setSpacing(4)
        summary_title = QLabel("Project constraints (locked after creation)")
        summary_title.setObjectName("SummaryTitle")
        summary_layout.addWidget(summary_title)
        self.summary_line_1 = QLabel(
            "Everything you set here becomes fixed for the project and cannot be changed in Batch runs."
        )
        self.summary_line_1.setObjectName("SummaryText")
        self.summary_line_1.setWordWrap(True)
        summary_layout.addWidget(self.summary_line_1)
        self.summary_line_2 = QLabel("Batch runs can only vary parameters that are not locked here.")
        self.summary_line_2.setObjectName("SummaryText")
        self.summary_line_2.setWordWrap(True)
        summary_layout.addWidget(self.summary_line_2)
        self.summary_counts = QLabel("Errors: 0 • Warnings: 0")
        self.summary_counts.setObjectName("SummaryMeta")
        summary_layout.addWidget(self.summary_counts)
        self.summary_chips_wrap = QWidget()
        self.summary_chips_layout = QHBoxLayout(self.summary_chips_wrap)
        self.summary_chips_layout.setContentsMargins(0, 2, 0, 0)
        self.summary_chips_layout.setSpacing(6)
        summary_layout.addWidget(self.summary_chips_wrap)
        root.addWidget(self.summary_panel)
        root.addSpacing(6)

        self.constraints_form = ParameterForm(build_project_form_schema())
        root.addWidget(self.constraints_form, 1)

        self.action_bar = QFrame()
        self.action_bar.setObjectName("ProjectActionBar")
        self.action_bar.setFixedHeight(60)
        action_layout = QHBoxLayout(self.action_bar)
        action_layout.setContentsMargins(12, 8, 12, 8)
        action_layout.setSpacing(10)

        left_action = QHBoxLayout()
        left_action.setContentsMargins(0, 0, 0, 0)
        left_action.setSpacing(8)
        self.action_status_pill = QLabel("Ready to create")
        self.action_status_pill.setObjectName("ProjectStatusPill")
        self.action_status_pill.setProperty("severity", "ok")
        left_action.addWidget(self.action_status_pill)
        self.action_status_hint = QLabel("")
        self.action_status_hint.setObjectName("ProjectStatusHint")
        left_action.addWidget(self.action_status_hint)
        self.view_issues_btn = QPushButton("View issues")
        self.view_issues_btn.setObjectName("ProjectViewIssuesButton")
        self.view_issues_btn.setVisible(False)
        left_action.addWidget(self.view_issues_btn)
        left_wrap = QWidget()
        left_wrap.setLayout(left_action)
        action_layout.addWidget(left_wrap, 1)

        self.create_btn = QPushButton("Create Project")
        self.create_btn.setObjectName("PrimaryButton")
        action_layout.addWidget(self.create_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        root.addWidget(self.action_bar)

        self.create_btn.clicked.connect(self._submit)
        self.view_issues_btn.clicked.connect(self._focus_first_issue)
        self.constraints_form.changed.connect(self._emit_draft_changed)

        self._compat_state: Dict[str, Any] = {"visible_keys": [], "locked_keys": [], "sweepable_keys": [], "issues": []}
        self._latest_field_issues: List[Dict[str, Any]] = []
        self._validation_phase = "idle"
        self._creating_project = False
        self._constraints_locked = False
        self._update_action_state()
        self._update_summary_panel()

    def _emit_draft_changed(self, payload: Dict[str, Any] | None = None) -> None:
        self.draft_changed.emit(payload or self._raw_constraints_payload())

    def _raw_constraints_payload(self) -> Dict[str, Any]:
        return self.constraints_form.payload()

    def apply_compatibility(self, state: Dict[str, Any]) -> None:
        self._compat_state = dict(state)
        self.constraints_form.apply_compatibility(state)

    def apply_ui_risks(self, issues: List[Dict[str, Any]]) -> None:
        self._latest_field_issues = [item for item in issues if isinstance(item, dict)]
        self.constraints_form.apply_ui_risks(issues)
        if self._validation_phase == "validating":
            self._validation_phase = "idle"
        self._update_action_state()
        self._update_summary_panel()

    def set_validation_phase(self, phase: str) -> None:
        self._validation_phase = str(phase or "idle").strip().lower()
        self._update_action_state()

    def set_creating(self, creating: bool) -> None:
        self._creating_project = bool(creating)
        if creating:
            self._constraints_locked = False
        self._update_action_state()

    def set_constraints_locked(self, locked: bool) -> None:
        self._constraints_locked = bool(locked)
        if locked:
            self._creating_project = False
            self._validation_phase = "idle"
        self._update_action_state()
        self._update_summary_panel()

    def _issue_counts(self) -> Dict[str, int]:
        rank = {"fatal": 0, "warn": 1, "ok": 2, "info": 3}
        per_key: Dict[str, str] = {}
        for issue in self._latest_field_issues:
            key = str(issue.get("field_key") or issue.get("key") or "").strip()
            if not key:
                continue
            severity = str(issue.get("severity", "")).strip().lower()
            if severity not in {"fatal", "warn"}:
                continue
            current = per_key.get(key)
            if current is None or rank.get(severity, 99) < rank.get(current, 99):
                per_key[key] = severity
        fatal = sum(1 for value in per_key.values() if value == "fatal")
        warn = sum(1 for value in per_key.values() if value == "warn")
        return {"fatal": fatal, "warn": warn}

    @staticmethod
    def _mode_label(mapping: Dict[int, str], value: Any, *, fallback: str) -> str:
        try:
            key = int(value)
        except Exception:
            return fallback
        return mapping.get(key, fallback)

    def _mode_chips(self, payload: Dict[str, Any]) -> List[str]:
        state_by_key: Dict[str, Dict[str, Any]] = {}
        for row in list(payload.get("param_states", []) or []):
            if not isinstance(row, dict):
                continue
            key = str(row.get("param_name", "")).strip()
            if not key:
                continue
            state_by_key[key] = {"is_set": bool(row.get("is_set")), "value": row.get("value")}

        def get_value(key: str) -> Any:
            row = state_by_key.get(key, {})
            if bool(row.get("is_set")):
                return row.get("value")
            return None

        throat_value = get_value("Throat.Profile")
        gcurve_value = get_value("GCurve.Type")
        morph_value = get_value("Morph.TargetShape")
        enclosure_enabled = bool(state_by_key.get("Mesh.Enclosure", {}).get("is_set", False))
        chips = [
            f"Throat: {self._mode_label({1: 'OS-SE', 2: 'R-OSSE', 3: 'Circular Arc'}, throat_value, fallback='unset')}",
            f"Morph: {self._mode_label({0: 'no morph', 1: 'rectangle', 2: 'circle'}, morph_value if morph_value is not None else 0, fallback='no morph')}",
            f"GCurve: {self._mode_label({0: 'no GCurve', 1: 'Superellipse', 2: 'Superformula'}, gcurve_value if gcurve_value is not None else 0, fallback='no GCurve')}",
            f"Enclosure: {'enabled' if enclosure_enabled else 'disabled'}",
        ]
        return chips

    def _set_summary_chips(self, chips: List[str]) -> None:
        while self.summary_chips_layout.count():
            item = self.summary_chips_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for chip_text in chips[:4]:
            chip = QLabel(chip_text)
            chip.setObjectName("SummaryChip")
            self.summary_chips_layout.addWidget(chip, 0, Qt.AlignVCenter)
        self.summary_chips_layout.addStretch(1)

    def _update_summary_panel(self) -> None:
        payload = self._raw_constraints_payload()
        counts = self._issue_counts()
        self.summary_counts.setText(f"Errors: {counts['fatal']} • Warnings: {counts['warn']}")
        self._set_summary_chips(self._mode_chips(payload))

    def _update_action_state(self) -> None:
        counts = self._issue_counts()
        fatal = int(counts.get("fatal", 0))
        warn = int(counts.get("warn", 0))

        if self._creating_project:
            text = "Creating project..."
            severity = "progress"
            hint = ""
        elif self._constraints_locked:
            text = "Constraints locked for this project"
            severity = "ok"
            hint = ""
        elif self._validation_phase == "validating":
            text = "Checking constraints..."
            severity = "progress"
            hint = ""
        elif fatal > 0:
            text = f"Fix errors: {fatal}"
            severity = "fatal"
            hint = "Resolve errors to proceed."
        elif warn > 0:
            text = f"Warnings: {warn}"
            severity = "warn"
            hint = "You can continue, but results may be unstable."
        else:
            text = "Ready to create"
            severity = "ok"
            hint = ""

        self.action_status_pill.setText(text)
        self.action_status_pill.setProperty("severity", severity)
        self.action_status_pill.style().unpolish(self.action_status_pill)
        self.action_status_pill.style().polish(self.action_status_pill)
        self.action_status_hint.setText(hint)
        self.action_status_hint.setVisible(bool(hint))

        has_issues = fatal > 0 or warn > 0
        self.view_issues_btn.setVisible(has_issues)

        enabled = (fatal == 0) and (not self._creating_project)
        self.create_btn.setEnabled(enabled)
        if not enabled and fatal > 0:
            self.create_btn.setToolTip("Resolve errors before creating the project.")
        else:
            self.create_btn.setToolTip("")

    def _focus_first_issue(self) -> None:
        self.constraints_form.open_first_issue_section(self._latest_field_issues)

    def _submit(self) -> None:
        if not self.create_btn.isEnabled():
            return
        payload = self._raw_constraints_payload()
        self.submit_project.emit(self.project_name.text().strip(), payload)


class BatchPage(QWidget):
    save_batch = Signal(dict)
    run_batch = Signal(dict)
    back_to_dashboard = Signal()
    draft_changed = Signal(dict)

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        title = QLabel("BATCH")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        grid = QGridLayout()
        self.batch_name = QLineEdit()
        self.batch_name.setPlaceholderText("Batch Name")
        self.sweep_mode = QComboBox()
        self.sweep_mode.addItems(["single", "combined"])
        self.selected_json = QTextEdit()
        self.selected_json.setPlaceholderText('Variable params JSON, e.g. {"Throat.Diameter": 25}')
        self.sweeps_json = QTextEdit()
        self.sweeps_json.setPlaceholderText('Sweeps JSON, e.g. {"Length":{"start":80,"end":120,"steps":3}}')
        self.sim_export_json = QTextEdit()
        self.sim_export_json.setPlaceholderText('Sim/export params JSON')

        grid.addWidget(QLabel("Batch Name"), 0, 0)
        grid.addWidget(self.batch_name, 0, 1)
        grid.addWidget(QLabel("Sweep mode"), 1, 0)
        grid.addWidget(self.sweep_mode, 1, 1)
        grid.addWidget(QLabel("Variable Parameters"), 2, 0)
        grid.addWidget(self.selected_json, 2, 1)
        grid.addWidget(QLabel("Sweep Definitions"), 3, 0)
        grid.addWidget(self.sweeps_json, 3, 1)
        grid.addWidget(QLabel("Sim/Export Params"), 4, 0)
        grid.addWidget(self.sim_export_json, 4, 1)
        root.addLayout(grid, 1)
        self.compat_panel = CompatibilityPanel("Batch Compatibility")
        root.addWidget(self.compat_panel)

        buttons = QHBoxLayout()
        save_btn = QPushButton("Save Batch")
        save_btn.setObjectName("PrimaryButton")
        run_btn = QPushButton("Run Batch")
        back_btn = QPushButton("Back to Dashboard")
        buttons.addWidget(save_btn)
        buttons.addWidget(run_btn)
        buttons.addWidget(back_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        save_btn.clicked.connect(lambda: self.save_batch.emit(self._payload()))
        run_btn.clicked.connect(lambda: self.run_batch.emit(self._payload()))
        back_btn.clicked.connect(self.back_to_dashboard.emit)

        self.selected_json.textChanged.connect(self._emit_draft_changed)
        self.sweeps_json.textChanged.connect(self._emit_draft_changed)
        self.sim_export_json.textChanged.connect(self._emit_draft_changed)
        self.sweep_mode.currentTextChanged.connect(lambda _: self._emit_draft_changed())

        self._compat_state: Dict[str, Any] = {"visible_keys": [], "locked_keys": [], "sweepable_keys": [], "issues": []}

    def _emit_draft_changed(self) -> None:
        self.draft_changed.emit(self._payload(include_name=False))

    def apply_compatibility(self, state: Dict[str, Any]) -> None:
        self._compat_state = dict(state)
        self.compat_panel.update_state(state)
        severity = _highest_issue_severity(self.compat_panel.issues())
        for widget in (self.selected_json, self.sweeps_json):
            widget.setProperty("severity", severity)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    def _payload(self, *, include_name: bool = True) -> Dict[str, object]:
        selected = _parse_json_object(self.selected_json.toPlainText())
        sweeps = _parse_json_object(self.sweeps_json.toPlainText())

        visible = set(str(item) for item in list(self._compat_state.get("visible_keys", []) or []))
        locked = set(str(item) for item in list(self._compat_state.get("locked_keys", []) or []))
        sweepable = set(str(item) for item in list(self._compat_state.get("sweepable_keys", []) or []))
        if visible:
            selected = {
                key: value
                for key, value in selected.items()
                if str(key) in visible and str(key) not in locked
            }
        if sweepable:
            sweeps = {
                key: value
                for key, value in sweeps.items()
                if str(key) in sweepable and str(key) not in locked
            }

        payload: Dict[str, object] = {
            "sweep_mode": self.sweep_mode.currentText().strip() or "single",
            "selected_params": selected,
            "sweeps": sweeps,
            "sim_export_params": _parse_json_object(self.sim_export_json.toPlainText()),
        }
        if include_name:
            payload["batch_name"] = self.batch_name.text().strip()
        return payload


class RunPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        title = QLabel("RUN")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        hint = QLabel(
            "AKABAK/VACS are driven via UI automation. Do not close this window while a run is active."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        root.addWidget(self.progress)

        self.version_label = QLabel("Version 0/0")
        self.mode_label = QLabel("Mode: --")
        self.eta_label = QLabel("ETA: --")
        root.addWidget(self.version_label)
        root.addWidget(self.mode_label)
        root.addWidget(self.eta_label)
        root.addStretch(1)


class ProjectManagerWindow(QMainWindow):
    open_project = Signal(str)
    create_project = Signal()

    def __init__(self, service: OrchestratorService) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle("WUT Batcher - Project Manager")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setProperty("framelessShell", True)
        self.setMinimumSize(760, 520)
        self.resize(920, 620)
        self._drag_offset: Optional[QPoint] = None

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(0)
        shell = QFrame()
        shell.setObjectName("FramelessShell")
        outer.addWidget(shell)
        root = QVBoxLayout(shell)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        title_bar = QWidget()
        title_row = QHBoxLayout(title_bar)
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.setSpacing(8)
        title = QLabel("Project Manager")
        title.setObjectName("SectionTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        close_btn = QPushButton("X")
        close_btn.setObjectName("WindowCloseButton")
        close_btn.setFixedSize(28, 24)
        close_btn.clicked.connect(self.close)
        title_row.addWidget(close_btn, alignment=Qt.AlignRight)
        root.addWidget(title_bar)
        title_bar.mousePressEvent = self._title_mouse_press  # type: ignore[assignment]
        title_bar.mouseMoveEvent = self._title_mouse_move  # type: ignore[assignment]
        title_bar.mouseReleaseEvent = self._title_mouse_release  # type: ignore[assignment]

        self.project_list = QListWidget()
        root.addWidget(self.project_list, 1)

        buttons = QHBoxLayout()
        open_btn = QPushButton("Open Project")
        new_btn = QPushButton("New Project")
        refresh_btn = QPushButton("Refresh")
        buttons.addWidget(open_btn)
        buttons.addWidget(new_btn)
        buttons.addWidget(refresh_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        open_btn.clicked.connect(self._emit_open)
        new_btn.clicked.connect(self.create_project.emit)
        refresh_btn.clicked.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.project_list.clear()
        for project in self.service.list_projects():
            label = f"{project.project_id} | {project.name}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, project.project_id)
            self.project_list.addItem(item)

    def _emit_open(self) -> None:
        item = self.project_list.currentItem()
        if item is None:
            return
        project_id = item.data(Qt.UserRole)
        if project_id:
            self.open_project.emit(str(project_id))

    def _title_mouse_press(self, event) -> None:  # type: ignore[override]
        if event.button() != Qt.LeftButton:
            return
        self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def _title_mouse_move(self, event) -> None:  # type: ignore[override]
        if self._drag_offset is None:
            return
        if not (event.buttons() & Qt.LeftButton):
            return
        self.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def _title_mouse_release(self, event) -> None:  # type: ignore[override]
        self._drag_offset = None
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self, service: OrchestratorService) -> None:
        super().__init__()
        self.service = service
        self.current_project: Optional[Project] = None
        self.last_status_detail = ""
        self.ui_validation = UiValidationEngine()
        self._project_validation_debounce_ms = 200
        self._pending_project_payload: Optional[Dict[str, object]] = None
        self._project_validation_timer = QTimer(self)
        self._project_validation_timer.setSingleShot(True)
        self._project_validation_timer.setInterval(self._project_validation_debounce_ms)
        self._project_validation_timer.timeout.connect(self._flush_project_draft_validation)

        self.setWindowTitle("WUT Batcher")
        self.resize(1280, 860)

        self.stack = QStackedWidget()
        self.dashboard_page = DashboardPage()
        self.project_page = ProjectPage()
        self.batch_page = BatchPage()
        self.run_page = RunPage()

        self.stack.addWidget(self.dashboard_page)
        self.stack.addWidget(self.project_page)
        self.stack.addWidget(self.batch_page)
        self.stack.addWidget(self.run_page)
        self.setCentralWidget(self.stack)

        self._build_statusbar()
        self._connect_page_signals()
        self.show_dashboard()

    def _build_statusbar(self) -> None:
        bar = QStatusBar()
        bar.setSizeGripEnabled(False)
        self.setStatusBar(bar)

        self.status_message = ClickableLabel("Ready.")
        self.status_message.clicked.connect(self._show_status_detail)
        bar.addWidget(self.status_message, 1)

        self.brand = ClickableLabel("WUT BATCHER")
        self.brand.setObjectName("StatusBrand")
        self.brand.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.brand.clicked.connect(self._show_about)
        bar.addPermanentWidget(self.brand)

    def _connect_page_signals(self) -> None:
        self.dashboard_page.request_new_batch.connect(self.show_batch)
        self.dashboard_page.request_edit_batch.connect(self._edit_batch)
        self.dashboard_page.request_clone_batch.connect(self._clone_batch)
        self.dashboard_page.request_open_export_dialog.connect(self._open_export_dialog)
        self.dashboard_page.request_manage_runs.connect(self._open_run_manager)
        self.dashboard_page.request_cleanup_testdata.connect(self._open_cleanup_dialog)
        self.dashboard_page.request_settings.connect(self._open_settings)

        self.project_page.submit_project.connect(self._create_project)
        self.project_page.draft_changed.connect(self._queue_project_draft_changed)

        self.batch_page.save_batch.connect(self._save_batch)
        self.batch_page.run_batch.connect(self._run_batch)
        self.batch_page.back_to_dashboard.connect(self.show_dashboard)
        self.batch_page.draft_changed.connect(self._on_batch_draft_changed)
        self.batch_page.compat_panel.request_show_details.connect(
            lambda: self._show_validation_details(self.batch_page.compat_panel.issues(), "Batch Validation Details")
        )

    def set_status(self, text: str, detail: Optional[str] = None) -> None:
        self.status_message.setText(text)
        self.last_status_detail = detail or text

    def _show_status_detail(self) -> None:
        StatusDetailDialog(self.last_status_detail or "No details.", self).exec()

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def _show_validation_details(self, issues: List[Dict[str, Any]], title: str) -> None:
        if not issues:
            QMessageBox.information(self, title, "No validation issues.")
            return
        lines = []
        for issue in issues:
            severity = str(issue.get("severity", "info")).upper()
            rule_id = str(issue.get("rule_id", "unknown_rule"))
            evidence_type = str(issue.get("evidence_type", "hypothesis"))
            message = str(issue.get("message", ""))
            lines.append(f"[{severity}] {rule_id} ({evidence_type})\n{message}")
        QMessageBox.information(self, title, "\n\n".join(lines))

    def _present_validation_summary(
        self,
        *,
        title: str,
        issues: List[Dict[str, Any]],
        block_on_fatal: bool,
    ) -> bool:
        if not issues:
            return True
        fatal_count = sum(1 for issue in issues if str(issue.get("severity", "")).lower() == "fatal")
        top = issues[:5]
        lines = []
        for issue in top:
            severity = str(issue.get("severity", "info")).upper()
            rule_id = str(issue.get("rule_id", "unknown_rule"))
            evidence_type = str(issue.get("evidence_type", "hypothesis"))
            message = str(issue.get("message", ""))
            lines.append(f"[{severity}] {rule_id} ({evidence_type}) - {message}")
        detail_lines = [
            {
                "severity": issue.get("severity"),
                "rule_id": issue.get("rule_id"),
                "evidence_type": issue.get("evidence_type"),
                "message": issue.get("message"),
                "scope": issue.get("scope"),
            }
            for issue in issues
        ]
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setIcon(QMessageBox.Warning if fatal_count == 0 else QMessageBox.Critical)
        dialog.setText(f"Validation Summary ({len(issues)} issues)")
        dialog.setInformativeText("\n".join(lines) + "\n\nShow details for full list.")
        dialog.setDetailedText(json.dumps(detail_lines, indent=2, ensure_ascii=False))
        if fatal_count > 0 and block_on_fatal:
            dialog.setStandardButtons(QMessageBox.Ok)
            dialog.exec()
            return False
        dialog.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
        return dialog.exec() == QMessageBox.Ok

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.service, self)
        dialog.settings_saved.connect(lambda _: self.set_status("Settings saved."))
        dialog.exec()

    def load_project(self, project: Project) -> None:
        self.current_project = project
        self.project_page.set_constraints_locked(True)
        self.refresh_dashboard()
        self._on_project_draft_changed(self.project_page._raw_constraints_payload())
        self._on_batch_draft_changed(self.batch_page._payload(include_name=False))
        self.show_dashboard()

    def refresh_dashboard(self) -> None:
        if self.current_project is None:
            self.dashboard_page.constraints_summary.setPlainText("No project loaded.")
            self.dashboard_page.batch_list.clear()
            return

        constraints_json = json.dumps(self.current_project.constraints.to_dict(), indent=2, ensure_ascii=False)
        self.dashboard_page.constraints_summary.setPlainText(constraints_json)
        self.dashboard_page.batch_list.clear()
        for batch in self.service.repo.list_batches(self.current_project.project_id):
            label = f"{batch.batch_id} | {batch.extra.get('batch_name', batch.batch_id)}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, batch.batch_id)
            self.dashboard_page.batch_list.addItem(item)

    def show_dashboard(self) -> None:
        self.stack.setCurrentWidget(self.dashboard_page)

    def show_project(self) -> None:
        self._on_project_draft_changed(self.project_page._raw_constraints_payload())
        self.stack.setCurrentWidget(self.project_page)

    def show_batch(self) -> None:
        self._on_batch_draft_changed(self.batch_page._payload(include_name=False))
        self.stack.setCurrentWidget(self.batch_page)

    def show_run(self) -> None:
        self.stack.setCurrentWidget(self.run_page)

    def _create_project(self, project_name: str, constraints: Dict[str, object]) -> None:
        self.project_page.set_creating(True)
        try:
            validation = self.service.evaluate_project_constraints(dict(constraints))
            issues = [item for item in list(validation.get("issues", []) or []) if isinstance(item, dict)]
            project = self.service.create_project(project_name, constraints)
            self.load_project(project)
            self.project_page.set_constraints_locked(True)
            if issues:
                self.set_status(
                    f"Project created: {project.project_id} (draft issues: {len(issues)})",
                    detail=json.dumps(issues, indent=2, ensure_ascii=False),
                )
            else:
                self.set_status(f"Project created: {project.project_id}")
        finally:
            self.project_page.set_creating(False)

    def _save_batch(self, payload: Dict[str, object]) -> Optional[str]:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return None
        validation = self.service.evaluate_batch_definition(
            project_id=self.current_project.project_id,
            selected_params=dict(payload.get("selected_params", {}) or {}),
            sweeps=dict(payload.get("sweeps", {}) or {}),
            sweep_mode=str(payload.get("sweep_mode", "single")),
        )
        issues = [item for item in list(validation.get("issues", []) or []) if isinstance(item, dict)]
        if not self._present_validation_summary(
            title="Batch Validation Summary",
            issues=issues,
            block_on_fatal=True,
        ):
            self.set_status("Batch save blocked by validation.")
            return None
        summary = self.service.create_batch(
            project_id=self.current_project.project_id,
            batch_name=str(payload.get("batch_name", "")),
            selected_params=dict(payload.get("selected_params", {}) or {}),
            sweeps=dict(payload.get("sweeps", {}) or {}),
            sweep_mode=str(payload.get("sweep_mode", "single")),
            sim_export_params=dict(payload.get("sim_export_params", {}) or {}),
        )
        self.set_status(
            f"Batch saved: {summary.batch_id}, versions={summary.version_count}",
            detail=json.dumps(asdict(summary), indent=2, ensure_ascii=False),
        )
        self.refresh_dashboard()
        self.show_dashboard()
        return summary.batch_id

    def _run_batch(self, payload: Dict[str, object]) -> None:
        batch_id = self._save_batch(payload)
        if self.current_project is None or not batch_id:
            return
        self.show_run()
        self.run_page.version_label.setText("Version 0/0")
        self.run_page.mode_label.setText("Mode: running...")
        summary = self.service.run_batch(self.current_project.project_id, batch_id, continue_on_error=True)
        self.run_page.progress.setValue(100)
        self.run_page.version_label.setText(f"Version {len(summary.versions)}/{len(summary.versions)}")
        self.run_page.mode_label.setText("Mode: dry-run" if summary.dry_run else "Mode: real")
        self.run_page.eta_label.setText("ETA: done")
        self.set_status(
            f"Run finished for {batch_id}",
            detail=json.dumps(asdict(summary), indent=2, ensure_ascii=False),
        )
        self.refresh_dashboard()

    def _open_export_dialog(self) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        rows = self.service.list_versions(self.current_project.project_id)
        versions_by_batch: Dict[str, List[str]] = {}
        for row in rows:
            batch_id = str(row["batch_id"])
            versions_by_batch.setdefault(batch_id, []).append(str(row["version_id"]))
        if not versions_by_batch:
            self.set_status("No versions available for export.")
            return
        dialog = ExportDialog(versions_by_batch, self)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        self._export_version(
            str(payload["batch_id"]),
            str(payload["version_id"]),
            bool(payload["export_stl"]),
            bool(payload["export_abec"]),
        )

    def _open_run_manager(self) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        RunManagerDialog(self.service, self.current_project.project_id, self).exec()
        self.refresh_dashboard()

    def _open_cleanup_dialog(self) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        dialog = CleanupTestDataDialog(self.service, self.current_project.project_id, self)
        if dialog.exec() == QDialog.Accepted:
            self.set_status("Cleanup finished.")
            self.refresh_dashboard()

    def _edit_batch(self, batch_id: str) -> None:
        self.set_status(f"Edit Batch requested: {batch_id} (placeholder).")
        self.show_batch()

    def _clone_batch(self, batch_id: str) -> None:
        self.set_status(f"Clone Batch requested: {batch_id} (placeholder).")
        self.show_batch()

    def _export_version(self, batch_id: str, version_id: str, export_stl: bool, export_abec: bool) -> None:
        if self.current_project is None:
            self.set_status("No project loaded.")
            return
        try:
            result = self.service.export_version(
                project_id=self.current_project.project_id,
                batch_id=batch_id,
                version_id=version_id,
                export_stl=export_stl,
                export_abec=export_abec,
            )
        except Exception as exc:
            self.set_status(f"Export failed for {version_id}", detail=str(exc))
            return
        self.set_status(f"Export finished for {version_id}", detail=json.dumps(result, indent=2, ensure_ascii=False))

    def _queue_project_draft_changed(self, payload: Dict[str, object]) -> None:
        self._pending_project_payload = dict(payload)
        self.project_page.set_validation_phase("validating")
        self._project_validation_timer.start()

    def _flush_project_draft_validation(self) -> None:
        payload = self._pending_project_payload
        self._pending_project_payload = None
        if payload is None:
            payload = self.project_page._raw_constraints_payload()
        self._on_project_draft_changed(payload)

    def _on_project_draft_changed(self, payload: Dict[str, object]) -> None:
        runner_mode = DEFAULT_RUNNER_MODE
        if self.current_project is not None:
            runner_mode = self.current_project.constraints.runner_mode
        constraints_payload = {
            "fixed_params": dict(payload.get("fixed_params", {}) or {}),
            "limits": dict(payload.get("limits", {}) or {}),
            "param_states": [item for item in list(payload.get("param_states", []) or []) if isinstance(item, dict)],
            "runner_mode": runner_mode,
        }
        state = self.service.evaluate_project_constraints(constraints_payload)
        self.project_page.apply_compatibility(state)
        visible_keys = set(str(item) for item in list(state.get("visible_keys", []) or []))
        issues = [item for item in list(state.get("issues", []) or []) if isinstance(item, dict)]
        field_issues = self.ui_validation.evaluate(
            draft_payload=constraints_payload,
            validation_state=state,
            visible_keys=visible_keys,
        )
        self.project_page.apply_ui_risks(field_issues)
        _ = issues

    def _on_batch_draft_changed(self, payload: Dict[str, object]) -> None:
        if self.current_project is None:
            self.batch_page.apply_compatibility(
                {
                    "visible_keys": [],
                    "locked_keys": [],
                    "sweepable_keys": [],
                    "issues": [],
                }
            )
            return
        state = self.service.evaluate_batch_definition(
            project_id=self.current_project.project_id,
            selected_params=dict(payload.get("selected_params", {}) or {}),
            sweeps=dict(payload.get("sweeps", {}) or {}),
            sweep_mode=str(payload.get("sweep_mode", "single")),
        )
        self.batch_page.apply_compatibility(state)


class GuiController:
    def __init__(self, service: OrchestratorService) -> None:
        self.service = service
        self.project_manager = ProjectManagerWindow(service)
        self.main_window = MainWindow(service)
        self.project_manager.open_project.connect(self._open_project)
        self.project_manager.create_project.connect(self._new_project)

    def show_project_manager(self) -> None:
        self.project_manager.refresh()
        self._show_window_normal_foreground(self.project_manager)

    def _show_main_window_maximized(self) -> None:
        self._show_window_maximized_foreground(self.main_window)

    @staticmethod
    def _show_window_normal_foreground(window: QMainWindow) -> None:
        _center_window(window)
        window.show()
        apply_windows_dark_titlebar(window)
        _ensure_normal_foreground(window)

    @staticmethod
    def _show_window_maximized_foreground(window: QMainWindow) -> None:
        window.show()
        apply_windows_dark_titlebar(window)
        _ensure_maximized_foreground(window)

    def _open_project(self, project_id: str) -> None:
        project = self.service.repo.load_project(project_id)
        self.main_window.load_project(project)
        self._show_main_window_maximized()
        self.project_manager.hide()

    def _new_project(self) -> None:
        self.main_window.current_project = None
        self.main_window.project_page.set_constraints_locked(False)
        self._show_main_window_maximized()
        self.main_window.show_project()
        self.project_manager.hide()


def _make_splash(app: QApplication) -> QSplashScreen:
    width, height = 760, 360
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, float(width), float(height), 18.0, 18.0)
    painter.fillPath(path, QColor("#101010"))
    painter.setPen(QColor("#F1F1F1"))
    font = QFont("Condor", 58)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, "WUT BATCHER")
    painter.end()
    splash = QSplashScreen(pixmap, Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
    splash.setAttribute(Qt.WA_TranslucentBackground, True)
    splash.show()
    app.processEvents()
    return splash


def _run_doctor_for_splash(service: OrchestratorService) -> Dict[str, object]:
    settings = service.settings
    config = AppConfig(projects_root=settings.library_root)
    report = run_doctor_checks(
        config,
        config_path=None,
        fix=False,
        kill_zombies=False,
        report_path=None,
        tool_paths={
            "ath_exe": settings.ath_exe,
            "akabak_exe": settings.akabak_exe,
            "vacs_exe": settings.vacs_exe,
        },
    )
    tool_versions: Dict[str, str] = {}
    for key, exe_path in {
        "ath": settings.ath_exe,
    }.items():
        if not exe_path:
            continue
        try:
            result = subprocess.run(
                [exe_path, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=4,
                check=False,
            )
            text = (result.stdout or result.stderr or "").strip().splitlines()
            if text:
                tool_versions[key] = text[0]
        except Exception:
            continue
    return {
        "overall_status": report.overall_status,
        "checks": [check.__dict__ for check in report.checks],
        "tool_versions": tool_versions,
    }


def launch_gui() -> int:
    configure_windows_qt_darkmode_env()
    app = QApplication.instance() or QApplication([])
    apply_theme(app)

    service = OrchestratorService()
    splash = _make_splash(app)
    apply_windows_dark_titlebar(splash)
    doctor_payload = _run_doctor_for_splash(service)
    controller = GuiController(service)
    doctor_status = str(doctor_payload["overall_status"]).lower()
    if doctor_status in {"fail", "warn"}:
        controller.main_window.set_status(
            f"Doctor {doctor_status}: click for details",
            detail=json.dumps(doctor_payload, indent=2, ensure_ascii=False),
        )
    else:
        controller.main_window.set_status(
            "Doctor ok.",
            detail=json.dumps(doctor_payload, indent=2, ensure_ascii=False),
        )
    apply_windows_dark_titlebar(controller.main_window)
    apply_windows_dark_titlebar(controller.project_manager)
    splash.finish(controller.project_manager)
    controller.show_project_manager()
    return app.exec()


def main() -> int:
    return int(launch_gui())
