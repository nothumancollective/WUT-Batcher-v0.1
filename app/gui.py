"""PySide6 GUI orchestrator for WUT Batcher."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import subprocess
from typing import Dict, List, Optional

from app.doctor_service import run_doctor_checks
from app.gui_theme import build_stylesheet
from app.models import AppConfig, Batch, Project
from app.services import OrchestratorService
from app.settings_store import UserSettings

try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QAction, QFont, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
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


class DashboardPage(QWidget):
    request_new_batch = Signal()
    request_edit_batch = Signal(str)
    request_clone_batch = Signal(str)
    request_export = Signal(str, str, bool, bool)
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
        self.export_batch_id = QLineEdit()
        self.export_batch_id.setPlaceholderText("Batch ID")
        self.export_version_id = QLineEdit()
        self.export_version_id.setPlaceholderText("Version ID")
        self.export_stl = QCheckBox("STL")
        self.export_abec = QCheckBox("ABEC")
        self.export_btn = QPushButton("Export")
        export_grid.addWidget(QLabel("Batch"), 0, 0)
        export_grid.addWidget(self.export_batch_id, 0, 1)
        export_grid.addWidget(QLabel("Version"), 1, 0)
        export_grid.addWidget(self.export_version_id, 1, 1)
        export_grid.addWidget(self.export_stl, 2, 0)
        export_grid.addWidget(self.export_abec, 2, 1)
        export_grid.addWidget(self.export_btn, 3, 0, 1, 2)
        root.addWidget(export_box)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.settings_btn = QPushButton("Settings")
        footer.addWidget(self.settings_btn)
        root.addLayout(footer)

        self.new_batch_btn.clicked.connect(self.request_new_batch.emit)
        self.edit_batch_btn.clicked.connect(self._emit_edit)
        self.clone_batch_btn.clicked.connect(self._emit_clone)
        self.export_btn.clicked.connect(self._emit_export)
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

    def _emit_export(self) -> None:
        batch_id = self.export_batch_id.text().strip()
        version_id = self.export_version_id.text().strip()
        if not batch_id or not version_id:
            return
        self.request_export.emit(batch_id, version_id, self.export_stl.isChecked(), self.export_abec.isChecked())


class ProjectPage(QWidget):
    submit_project = Signal(str, dict)
    back_to_dashboard = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        title = QLabel("PROJECT")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.project_name = QLineEdit()
        self.project_name.setPlaceholderText("Project Name")
        root.addWidget(self.project_name)

        groups = QHBoxLayout()
        self.geometry_constraints = QTextEdit()
        self.geometry_constraints.setPlaceholderText('Geometry constraints JSON, e.g. {"Length": 120}')
        self.mesh_constraints = QTextEdit()
        self.mesh_constraints.setPlaceholderText('Mesh limits JSON, e.g. {"Mesh.MaxElem": 120000}')

        geo_box = QGroupBox("Geometry")
        geo_layout = QVBoxLayout(geo_box)
        geo_layout.addWidget(self.geometry_constraints)

        mesh_box = QGroupBox("Mesh")
        mesh_layout = QVBoxLayout(mesh_box)
        mesh_layout.addWidget(self.mesh_constraints)

        groups.addWidget(geo_box, 1)
        groups.addWidget(mesh_box, 1)
        root.addLayout(groups, 1)

        buttons = QHBoxLayout()
        create_btn = QPushButton("Projekt erstellen")
        create_btn.setObjectName("PrimaryButton")
        back_btn = QPushButton("Back to Dashboard")
        buttons.addWidget(create_btn)
        buttons.addWidget(back_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        create_btn.clicked.connect(self._submit)
        back_btn.clicked.connect(self.back_to_dashboard.emit)

    def _submit(self) -> None:
        geometry_payload: Dict[str, object] = {}
        mesh_payload: Dict[str, object] = {}
        try:
            raw = self.geometry_constraints.toPlainText().strip()
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    geometry_payload = parsed
        except json.JSONDecodeError:
            pass
        try:
            raw = self.mesh_constraints.toPlainText().strip()
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    mesh_payload = parsed
        except json.JSONDecodeError:
            pass
        payload = {
            "fixed_params": geometry_payload,
            "limits": mesh_payload,
        }
        self.submit_project.emit(self.project_name.text().strip(), payload)


class BatchPage(QWidget):
    save_batch = Signal(dict)
    run_batch = Signal(dict)
    back_to_dashboard = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        title = QLabel("BATCH")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        grid = QGridLayout()
        self.batch_name = QLineEdit()
        self.batch_name.setPlaceholderText("Batch Name")
        self.sweep_mode = QLineEdit()
        self.sweep_mode.setPlaceholderText("single | combined")
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

    def _payload(self) -> Dict[str, object]:
        def parse_dict(text: str) -> Dict[str, object]:
            raw = text.strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}

        return {
            "batch_name": self.batch_name.text().strip(),
            "sweep_mode": self.sweep_mode.text().strip() or "single",
            "selected_params": parse_dict(self.selected_json.toPlainText()),
            "sweeps": parse_dict(self.sweeps_json.toPlainText()),
            "sim_export_params": parse_dict(self.sim_export_json.toPlainText()),
        }


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
        self.eta_label = QLabel("ETA: --")
        root.addWidget(self.version_label)
        root.addWidget(self.eta_label)
        root.addStretch(1)


class ProjectManagerWindow(QMainWindow):
    open_project = Signal(str)
    create_project = Signal()

    def __init__(self, service: OrchestratorService) -> None:
        super().__init__()
        self.service = service
        self.setWindowTitle("WUT Batcher - Project Manager")
        self.resize(1200, 800)

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        title = QLabel("Project Manager")
        title.setObjectName("PageTitle")
        root.addWidget(title)

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


class MainWindow(QMainWindow):
    def __init__(self, service: OrchestratorService) -> None:
        super().__init__()
        self.service = service
        self.current_project: Optional[Project] = None
        self.last_status_detail = ""

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
        self.setStatusBar(bar)

        self.status_message = ClickableLabel("Ready.")
        self.status_message.clicked.connect(self._show_status_detail)
        bar.addWidget(self.status_message, 1)

        self.brand = ClickableLabel("WUT BATCHER")
        self.brand.clicked.connect(self._show_about)
        bar.addPermanentWidget(self.brand)

    def _connect_page_signals(self) -> None:
        self.dashboard_page.request_new_batch.connect(self.show_batch)
        self.dashboard_page.request_edit_batch.connect(self._edit_batch)
        self.dashboard_page.request_clone_batch.connect(self._clone_batch)
        self.dashboard_page.request_export.connect(self._export_version)
        self.dashboard_page.request_settings.connect(self._open_settings)

        self.project_page.submit_project.connect(self._create_project)
        self.project_page.back_to_dashboard.connect(self.show_dashboard)

        self.batch_page.save_batch.connect(self._save_batch)
        self.batch_page.run_batch.connect(self._run_batch)
        self.batch_page.back_to_dashboard.connect(self.show_dashboard)

    def set_status(self, text: str, detail: Optional[str] = None) -> None:
        self.status_message.setText(text)
        self.last_status_detail = detail or text

    def _show_status_detail(self) -> None:
        QMessageBox.information(self, "Status Detail", self.last_status_detail or "No details.")

    def _show_about(self) -> None:
        AboutDialog(self).exec()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.service, self)
        dialog.settings_saved.connect(lambda _: self.set_status("Settings saved."))
        dialog.exec()

    def load_project(self, project: Project) -> None:
        self.current_project = project
        self.refresh_dashboard()
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
        self.stack.setCurrentWidget(self.project_page)

    def show_batch(self) -> None:
        self.stack.setCurrentWidget(self.batch_page)

    def show_run(self) -> None:
        self.stack.setCurrentWidget(self.run_page)

    def _create_project(self, project_name: str, constraints: Dict[str, object]) -> None:
        project = self.service.create_project(project_name, constraints)
        self.load_project(project)
        self.set_status(f"Project created: {project.project_id}")

    def _save_batch(self, payload: Dict[str, object]) -> Optional[str]:
        if self.current_project is None:
            self.set_status("No project loaded.")
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
        summary = self.service.run_batch(self.current_project.project_id, batch_id, continue_on_error=True)
        self.run_page.progress.setValue(100)
        self.run_page.version_label.setText(f"Version {len(summary.versions)}/{len(summary.versions)}")
        self.run_page.eta_label.setText("ETA: done")
        self.set_status(
            f"Run finished for {batch_id}",
            detail=json.dumps(asdict(summary), indent=2, ensure_ascii=False),
        )
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
        result = self.service.export_version(
            project_id=self.current_project.project_id,
            batch_id=batch_id,
            version_id=version_id,
            export_stl=export_stl,
            export_abec=export_abec,
        )
        self.set_status(
            f"Export finished for {version_id}",
            detail=json.dumps(result, indent=2, ensure_ascii=False),
        )


class GuiController:
    def __init__(self, service: OrchestratorService) -> None:
        self.service = service
        self.project_manager = ProjectManagerWindow(service)
        self.main_window = MainWindow(service)
        self.project_manager.open_project.connect(self._open_project)
        self.project_manager.create_project.connect(self._new_project)

    def show_project_manager(self) -> None:
        self.project_manager.refresh()
        self.project_manager.show()

    def _open_project(self, project_id: str) -> None:
        project = self.service.repo.load_project(project_id)
        self.main_window.load_project(project)
        self.main_window.show()
        self.project_manager.hide()

    def _new_project(self) -> None:
        self.main_window.current_project = None
        self.main_window.show()
        self.main_window.show_project()
        self.project_manager.hide()


def _make_splash(app: QApplication) -> QSplashScreen:
    pixmap = QPixmap(640, 300)
    pixmap.fill(Qt.black)
    splash = QSplashScreen(pixmap)
    splash.showMessage("WUT Batcher\nLoading...", alignment=Qt.AlignCenter, color=Qt.white)
    splash.show()
    app.processEvents()
    return splash


def _run_doctor_for_splash(service: OrchestratorService) -> Dict[str, object]:
    settings = service.settings
    config = AppConfig(projects_root=settings.library_root)
    report = run_doctor_checks(config, config_path=None, fix=False, kill_zombies=False, report_path=None)
    tool_versions: Dict[str, str] = {}
    for key, exe_path in {
        "ath": settings.ath_exe,
        "akabak": settings.akabak_exe,
        "vacs": settings.vacs_exe,
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


def _apply_font(app: QApplication) -> None:
    preferred = QFont("Condor", 10)
    if preferred.family().lower() == "condor":
        app.setFont(preferred)
    else:
        app.setFont(QFont("Segoe UI", 10))


def launch_gui() -> int:
    app = QApplication.instance() or QApplication([])
    _apply_font(app)
    app.setStyleSheet(build_stylesheet())

    service = OrchestratorService()
    splash = _make_splash(app)
    doctor_payload = _run_doctor_for_splash(service)
    splash.showMessage(
        f"Doctor status: {doctor_payload['overall_status']}\nOpening Project Manager...",
        alignment=Qt.AlignCenter,
        color=Qt.white,
    )
    app.processEvents()

    controller = GuiController(service)
    controller.main_window.set_status(
        f"Doctor: {doctor_payload['overall_status']}",
        detail=json.dumps(doctor_payload, indent=2, ensure_ascii=False),
    )
    splash.finish(controller.project_manager)
    controller.show_project_manager()
    return app.exec()


def main() -> int:
    return int(launch_gui())
