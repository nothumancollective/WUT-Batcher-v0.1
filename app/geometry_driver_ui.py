"""Focused Qt dialogs for geometry context and the central driver library."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any
import uuid

from app.driver_library import DriverDefinition, DriverRevision

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog,
        QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
        QSplitter, QTextEdit, QVBoxLayout, QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for geometry/driver UI") from exc


class DriverRevisionEditorDialog(QDialog):
    def __init__(self, *, title: str, seed: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(650, 520)
        root = QVBoxLayout(self)
        note = QLabel("Enter explicit parameters and provenance. Missing values stay null; units are mandatory for each parameter.")
        note.setWordWrap(True)
        root.addWidget(note)
        self.editor = QTextEdit(self)
        self.editor.setObjectName("DriverRevisionJsonEditor")
        payload = seed or {
            "parameters": {},
            "provenance": {"source": "user", "trust": "user_asserted", "licence_note": ""},
            "network_description": {},
            "completeness": "incomplete",
            "extensions": {},
        }
        self.editor.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))
        root.addWidget(self.editor, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        save = QPushButton("Save New Revision")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept_valid)
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)
        self.payload: dict[str, Any] | None = None

    def _accept_valid(self) -> None:
        try:
            payload = json.loads(self.editor.toPlainText())
            if not isinstance(payload, dict):
                raise ValueError("Revision JSON must be an object")
            if not isinstance(payload.get("parameters", {}), dict):
                raise ValueError("parameters must be an object")
            if not isinstance(payload.get("provenance", {}), dict):
                raise ValueError("provenance must be an object")
        except (ValueError, json.JSONDecodeError) as exc:
            QMessageBox.warning(self, "Invalid revision", str(exc))
            return
        self.payload = payload
        self.accept()


class DriverLibraryDialog(QDialog):
    def __init__(self, service: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.setWindowTitle("Driver Library")
        self.resize(980, 650)
        root = QVBoxLayout(self)

        filters = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Search manufacturer, model or variant")
        self.kind = QComboBox(self)
        self.kind.addItem("All driver types", "")
        self.kind.addItem("Compression drivers", "compression_driver")
        self.kind.addItem("Cone / mid drivers", "cone_driver")
        self.kind.addItem("Generic / test", "generic_test")
        self.kind.addItem("Future / unknown", "future_unknown")
        filters.addWidget(self.search, 1)
        filters.addWidget(self.kind)
        root.addLayout(filters)

        splitter = QSplitter(Qt.Horizontal, self)
        self.list = QListWidget(splitter)
        self.list.setObjectName("DriverLibraryList")
        self.details = QTextEdit(splitter)
        self.details.setObjectName("DriverLibraryDetails")
        self.details.setReadOnly(True)
        self.details.setLineWrapMode(QTextEdit.WidgetWidth)
        splitter.addWidget(self.list)
        splitter.addWidget(self.details)
        splitter.setSizes([360, 620])
        root.addWidget(splitter, 1)

        actions = QHBoxLayout()
        self.add_compression = QPushButton("New Compression Driver")
        self.add_cone = QPushButton("New Cone Driver")
        self.new_revision = QPushButton("New Revision")
        self.duplicate = QPushButton("Duplicate")
        self.archive = QPushButton("Archive")
        self.import_button = QPushButton("Import JSON")
        self.export_button = QPushButton("Export JSON")
        for button in (
            self.add_compression, self.add_cone, self.new_revision, self.duplicate,
            self.archive, self.import_button, self.export_button,
        ):
            actions.addWidget(button)
        actions.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        actions.addWidget(close)
        root.addLayout(actions)

        self.search.textChanged.connect(lambda *_: self.refresh())
        self.kind.currentIndexChanged.connect(lambda *_: self.refresh())
        self.list.currentItemChanged.connect(lambda *_: self._show_details())
        self.add_compression.clicked.connect(lambda: self._create_driver("compression_driver"))
        self.add_cone.clicked.connect(lambda: self._create_driver("cone_driver"))
        self.new_revision.clicked.connect(self._new_revision)
        self.duplicate.clicked.connect(self._duplicate)
        self.archive.clicked.connect(self._archive)
        self.import_button.clicked.connect(self._import_json)
        self.export_button.clicked.connect(self._export_json)
        self.refresh()

    def selected_driver_id(self) -> str | None:
        item = self.list.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def refresh(self) -> None:
        selected = self.selected_driver_id()
        rows = self.service.list_drivers(query=self.search.text(), kind=str(self.kind.currentData() or ""))
        self.list.clear()
        for row in rows:
            revision = row.get("latest_revision") or {}
            state = "ready" if revision.get("completeness") == "simulation_ready" else "incomplete"
            builtin = " · built-in/read-only" if row.get("read_only") else ""
            item = QListWidgetItem(f"{row.get('manufacturer') or 'Custom'} · {row.get('model')} [{row.get('kind')}] · {state}{builtin}")
            item.setData(Qt.UserRole, row["driver_id"])
            item.setToolTip(str(row.get("variant") or row.get("model") or ""))
            self.list.addItem(item)
            if row["driver_id"] == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._show_details()

    def _show_details(self) -> None:
        driver_id = self.selected_driver_id()
        if not driver_id:
            self.details.setPlainText("No driver selected.")
            return
        row = next((item for item in self.service.list_drivers(include_archived=True) if item["driver_id"] == driver_id), None)
        self.details.setPlainText(json.dumps(row or {}, indent=2, ensure_ascii=False))

    def _create_driver(self, kind: str) -> None:
        manufacturer, ok = QInputDialog.getText(self, "Manufacturer", "Manufacturer (may be Custom):", text="Custom")
        if not ok:
            return
        model, ok = QInputDialog.getText(self, "Model", "Model name:")
        if not ok or not model.strip():
            return
        definition = DriverDefinition(
            driver_id=f"D-{uuid.uuid4()}", manufacturer=manufacturer.strip(), model=model.strip(), kind=kind,
        )
        editor = DriverRevisionEditorDialog(title=f"Initial revision · {model}", parent=self)
        if editor.exec() != QDialog.Accepted or editor.payload is None:
            return
        payload = editor.payload
        revision = DriverRevision(
            revision_id=f"DR-{uuid.uuid4()}", driver_id=definition.driver_id, revision_number=1,
            parameters=dict(payload.get("parameters") or {}), provenance=dict(payload.get("provenance") or {}),
            network_description=dict(payload.get("network_description") or {}),
            completeness=str(payload.get("completeness") or "incomplete"),
            extensions=dict(payload.get("extensions") or {}),
        )
        try:
            self.service.create_driver(definition=asdict(definition), revision=asdict(revision))
        except Exception as exc:
            QMessageBox.warning(self, "Driver not created", str(exc))
            return
        self.refresh()

    def _new_revision(self) -> None:
        driver_id = self.selected_driver_id()
        if not driver_id:
            return
        row = next((item for item in self.service.list_drivers(include_archived=True) if item["driver_id"] == driver_id), None)
        latest = dict((row or {}).get("latest_revision") or {})
        seed = {key: latest.get(key) for key in ("parameters", "provenance", "network_description", "completeness", "extensions")}
        editor = DriverRevisionEditorDialog(title=f"New revision · {(row or {}).get('model', driver_id)}", seed=seed, parent=self)
        if editor.exec() != QDialog.Accepted or editor.payload is None:
            return
        try:
            self.service.create_driver_revision(driver_id, **editor.payload)
        except Exception as exc:
            QMessageBox.warning(self, "Revision not created", str(exc))
            return
        self.refresh()

    def _duplicate(self) -> None:
        driver_id = self.selected_driver_id()
        if not driver_id:
            return
        model, ok = QInputDialog.getText(self, "Duplicate driver", "Model name for copy:")
        if ok and model.strip():
            self.service.duplicate_driver(driver_id, model=model.strip())
            self.refresh()

    def _archive(self) -> None:
        driver_id = self.selected_driver_id()
        if not driver_id:
            return
        try:
            self.service.archive_driver(driver_id)
        except Exception as exc:
            QMessageBox.warning(self, "Driver not archived", str(exc))
            return
        self.refresh()

    def _import_json(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import driver", "", "WUT Driver JSON (*.json)")
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            report = self.service.import_driver_json(payload)
            if not report.get("ok"):
                raise ValueError("; ".join(report.get("errors") or ["Import failed"]))
        except Exception as exc:
            QMessageBox.warning(self, "Driver import failed", str(exc))
            return
        self.refresh()

    def _export_json(self) -> None:
        driver_id = self.selected_driver_id()
        if not driver_id:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export driver", f"{driver_id}.json", "WUT Driver JSON (*.json)")
        if path:
            Path(path).write_text(json.dumps(self.service.export_driver_json(driver_id), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


class GeometryManagerDialog(QDialog):
    def __init__(self, service: Any, project_id: str, *, active_geometry_id: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.selected_geometry_id = active_geometry_id
        self.setWindowTitle("Project Geometries")
        self.resize(860, 560)
        root = QVBoxLayout(self)
        self.list = QListWidget(self)
        self.list.setObjectName("GeometryManagerList")
        root.addWidget(self.list, 1)
        driver_row = QFormLayout()
        self.default_driver = QComboBox(self)
        self.default_driver.setObjectName("GeometryDefaultDriverCombo")
        driver_row.addRow("Default driver", self.default_driver)
        root.addLayout(driver_row)
        actions = QHBoxLayout()
        self.create_button = QPushButton("New Geometry")
        self.rename_button = QPushButton("Rename")
        self.duplicate_button = QPushButton("Duplicate")
        self.archive_button = QPushButton("Archive")
        self.driver_library_button = QPushButton("Driver Library")
        self.set_driver_button = QPushButton("Set Default Driver")
        self.open_button = QPushButton("Open Geometry")
        for button in (self.create_button, self.rename_button, self.duplicate_button, self.archive_button, self.driver_library_button, self.set_driver_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.open_button)
        root.addLayout(actions)
        self.create_button.clicked.connect(self._create)
        self.rename_button.clicked.connect(self._rename)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.archive_button.clicked.connect(self._archive)
        self.driver_library_button.clicked.connect(self._drivers)
        self.set_driver_button.clicked.connect(self._set_default_driver)
        self.open_button.clicked.connect(self._open)
        self.list.currentItemChanged.connect(lambda *_: self._sync_driver_selection())
        self.refresh()

    def current_geometry_id(self) -> str | None:
        item = self.list.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def refresh(self, *, preferred_geometry_id: str | None = None) -> None:
        selected = preferred_geometry_id or self.current_geometry_id() or self.selected_geometry_id
        self.list.clear()
        for row in self.service.list_geometries(self.project_id):
            legacy = " · legacy" if row.get("legacy") else ""
            driver = row.get("default_driver_revision_id") or "no default driver"
            item = QListWidgetItem(f"{row['name']} [{row['role']}] · {driver}{legacy}")
            item.setData(Qt.UserRole, row["geometry_id"])
            item.setToolTip(str(row.get("description") or row["name"]))
            self.list.addItem(item)
            if row["geometry_id"] == selected:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self._reload_drivers()

    def _reload_drivers(self) -> None:
        self.default_driver.clear()
        self.default_driver.addItem("No default driver", "")
        for row in self.service.list_drivers():
            for revision in row.get("revisions", []):
                revision_id = revision.get("revision_id")
                if revision_id:
                    self.default_driver.addItem(
                        f"{row.get('manufacturer')} · {row.get('model')} · r{revision.get('revision_number')}",
                        revision_id,
                    )
        self._sync_driver_selection()

    def _sync_driver_selection(self) -> None:
        geometry_id = self.current_geometry_id()
        row = next((item for item in self.service.list_geometries(self.project_id) if item["geometry_id"] == geometry_id), None)
        revision_id = str((row or {}).get("default_driver_revision_id") or "")
        index = self.default_driver.findData(revision_id)
        self.default_driver.setCurrentIndex(max(index, 0))

    def _create(self) -> None:
        name, ok = QInputDialog.getText(self, "New geometry", "Geometry name:")
        if not ok or not name.strip():
            return
        role, ok = QInputDialog.getItem(self, "Geometry role", "Role:", ["hf_horn", "mid_horn", "waveguide"], 0, False)
        if ok:
            row = self.service.create_geometry(self.project_id, name=name.strip(), role=str(role))
            self.selected_geometry_id = row["geometry_id"]
            self.refresh(preferred_geometry_id=row["geometry_id"])

    def _rename(self) -> None:
        geometry_id = self.current_geometry_id()
        if not geometry_id:
            return
        name, ok = QInputDialog.getText(self, "Rename geometry", "New name:")
        if ok and name.strip():
            self.service.update_geometry(self.project_id, geometry_id, name=name.strip())
            self.refresh()

    def _duplicate(self) -> None:
        geometry_id = self.current_geometry_id()
        if geometry_id:
            row = self.service.duplicate_geometry(self.project_id, geometry_id)
            self.selected_geometry_id = row["geometry_id"]
            self.refresh(preferred_geometry_id=row["geometry_id"])

    def _archive(self) -> None:
        geometry_id = self.current_geometry_id()
        if not geometry_id:
            return
        try:
            self.service.archive_geometry(self.project_id, geometry_id)
        except Exception as exc:
            QMessageBox.warning(self, "Geometry not archived", str(exc))
            return
        if self.selected_geometry_id == geometry_id:
            self.selected_geometry_id = None
        self.refresh()

    def _drivers(self) -> None:
        DriverLibraryDialog(self.service, self).exec()
        self._reload_drivers()

    def _set_default_driver(self) -> None:
        geometry_id = self.current_geometry_id()
        if geometry_id:
            try:
                self.service.set_geometry_default_driver(self.project_id, geometry_id, str(self.default_driver.currentData() or "") or None)
            except Exception as exc:
                QMessageBox.warning(self, "Default driver not changed", str(exc))
            self.refresh()

    def _open(self) -> None:
        self.selected_geometry_id = self.current_geometry_id()
        if self.selected_geometry_id:
            self.accept()
