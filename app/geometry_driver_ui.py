"""Focused Qt dialogs for geometry context and the central driver library."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any
import uuid

from app.driver_library import DriverDefinition, DriverRevision, TRUST_STATES

try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QDoubleValidator
    from PySide6.QtWidgets import (
        QComboBox, QDialog, QFileDialog, QFormLayout, QGridLayout, QGroupBox,
        QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
        QMessageBox, QPushButton, QScrollArea, QSplitter, QTextEdit, QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for geometry/driver UI") from exc


PARAMETER_GROUPS: tuple[tuple[str, tuple[tuple[str, str, tuple[str, ...]], ...]], ...] = (
    ("Exit / throat", (
        ("exit_diameter", "Exit diameter", ("mm", "m")),
        ("throat_area", "Throat area", ("cm2", "m2")),
    )),
    ("Diaphragm", (
        ("diaphragm_diameter", "Diaphragm diameter", ("mm", "m")),
        ("effective_diaphragm_area", "Effective diaphragm area", ("cm2", "m2")),
        ("moving_mass", "Moving mass", ("g", "kg")),
    )),
    ("T/S, impedance and power", (
        ("resonance_frequency", "Resonance frequency", ("Hz",)),
        ("re", "DC resistance Re", ("ohm",)),
        ("le", "Voice-coil inductance Le", ("mH", "H")),
        ("bl", "Force factor Bl", ("T*m",)),
        ("cms", "Compliance Cms", ("m/N",)),
        ("rms", "Mechanical resistance Rms", ("N*s/m",)),
        ("qms", "Qms", ("1",)),
        ("qes", "Qes", ("1",)),
        ("qts", "Qts", ("1",)),
        ("nominal_impedance", "Nominal impedance", ("ohm",)),
        ("rated_power", "Rated power", ("W",)),
    )),
)


class DriverRevisionEditorDialog(QDialog):
    """Non-technical editor for a definition and one immutable revision."""

    def __init__(self, *, service: Any, title: str, kind: str, definition: dict[str, Any] | None = None, seed: dict[str, Any] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.service = service
        self.kind_value = kind
        self.definition_seed = dict(definition or {})
        self.seed = dict(seed or {})
        self.parameter_inputs: dict[str, tuple[QLineEdit, QComboBox]] = {}
        self.le_source_path: str | None = None
        self.le_expected_sha256: str | None = None
        self.existing_le_hash = self.seed.get("le_network_hash")
        self.existing_le_name = self.seed.get("le_network_name")
        self.setWindowTitle(title)
        self.resize(720, 680)
        root = QVBoxLayout(self)
        note = QLabel("Enter only values you know. Empty fields remain unknown; no defaults are invented. Saving always creates an immutable revision.")
        note.setWordWrap(True)
        root.addWidget(note)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        content_layout = QVBoxLayout(content)

        identity = QGroupBox("Driver identity", content)
        identity_form = QFormLayout(identity)
        self.kind_label = QLabel("Compression driver" if kind == "compression_driver" else "Cone / mid driver")
        self.manufacturer = QLineEdit(str(self.definition_seed.get("manufacturer") or "Custom"), identity)
        self.model = QLineEdit(str(self.definition_seed.get("model") or ""), identity)
        self.variant = QLineEdit(str(self.definition_seed.get("variant") or ""), identity)
        identity_form.addRow("Type", self.kind_label)
        identity_form.addRow("Manufacturer", self.manufacturer)
        identity_form.addRow("Model *", self.model)
        identity_form.addRow("Variant", self.variant)
        if self.definition_seed:
            for widget in (self.manufacturer, self.model, self.variant):
                widget.setReadOnly(True)
        content_layout.addWidget(identity)

        parameters = dict(self.seed.get("parameters") or {})
        validator = QDoubleValidator(self)
        validator.setNotation(QDoubleValidator.StandardNotation)
        for group_title, fields in PARAMETER_GROUPS:
            group = QGroupBox(group_title, content)
            grid = QGridLayout(group)
            grid.addWidget(QLabel("Value"), 0, 1)
            grid.addWidget(QLabel("Unit"), 0, 2)
            for row_index, (key, label, units) in enumerate(fields, start=1):
                value_edit = QLineEdit(group)
                value_edit.setValidator(validator)
                value_edit.setObjectName(f"DriverParameter_{key}")
                unit_combo = QComboBox(group)
                unit_combo.setObjectName(f"DriverUnit_{key}")
                unit_combo.addItems(list(units))
                item = dict(parameters.get(key) or {})
                if item.get("value") is not None:
                    value_edit.setText(str(item["value"]))
                unit_index = unit_combo.findText(str(item.get("unit") or ""))
                if unit_index >= 0:
                    unit_combo.setCurrentIndex(unit_index)
                grid.addWidget(QLabel(label), row_index, 0)
                grid.addWidget(value_edit, row_index, 1)
                grid.addWidget(unit_combo, row_index, 2)
                self.parameter_inputs[key] = (value_edit, unit_combo)
            content_layout.addWidget(group)

        provenance = dict(self.seed.get("provenance") or {})
        provenance_group = QGroupBox("Provenance", content)
        provenance_form = QFormLayout(provenance_group)
        self.source = QLineEdit(str(provenance.get("source") or "user entry"), provenance_group)
        self.source_url = QLineEdit(str(provenance.get("source_url") or provenance.get("url") or ""), provenance_group)
        self.trust = QComboBox(provenance_group)
        self.trust.addItem("User asserted", "user_asserted")
        self.trust.addItem("Unverified", "unverified")
        self.trust.addItem("Verified", "verified")
        trust_index = self.trust.findData(str(provenance.get("trust") or "user_asserted"))
        self.trust.setCurrentIndex(max(trust_index, 0))
        self.licence_note = QLineEdit(str(provenance.get("licence_note") or ""), provenance_group)
        provenance_form.addRow("Source", self.source)
        provenance_form.addRow("Source URL", self.source_url)
        provenance_form.addRow("Trust", self.trust)
        provenance_form.addRow("Licence / usage note", self.licence_note)
        content_layout.addWidget(provenance_group)

        network_group = QGroupBox("AKABAK LE network", content)
        network_layout = QVBoxLayout(network_group)
        self.le_preview = QLabel(network_group)
        self.le_preview.setObjectName("DriverLePreview")
        self.le_preview.setWordWrap(True)
        network_layout.addWidget(self.le_preview)
        network_actions = QHBoxLayout()
        self.choose_le = QPushButton("Choose LE network file...", network_group)
        self.clear_le = QPushButton("Remove from this revision", network_group)
        self.choose_le.clicked.connect(self._choose_le_file)
        self.clear_le.clicked.connect(self._clear_le_file)
        network_actions.addWidget(self.choose_le)
        network_actions.addWidget(self.clear_le)
        network_actions.addStretch(1)
        network_layout.addLayout(network_actions)
        content_layout.addWidget(network_group)

        self.completeness = QLabel(content)
        self.completeness.setObjectName("DriverCompletenessStatus")
        self.completeness.setWordWrap(True)
        content_layout.addWidget(self.completeness)
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        save = QPushButton("Save New Revision")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept_valid)
        row.addWidget(cancel)
        row.addWidget(save)
        root.addLayout(row)
        self.payload: dict[str, Any] | None = None
        self.definition_payload: dict[str, Any] | None = None
        self._refresh_le_status()

    def _choose_le_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Choose AKABAK LE network", "", "LE network text (*.txt *.le *.akabak);;All files (*)")
        if path:
            self.set_le_file(path)

    def set_le_file(self, path: str) -> bool:
        try:
            preview = self.service.preview_driver_le_asset(path)
        except Exception as exc:
            QMessageBox.warning(self, "LE network not accepted", str(exc))
            return False
        self.le_source_path = str(path)
        self.le_expected_sha256 = str(preview["sha256"])
        self.existing_le_hash = None
        self.existing_le_name = None
        self.le_preview.setText(
            f"Selected: {preview['file_name']} | {preview['size_bytes']} bytes | SHA-256 {preview['sha256']}"
        )
        self._refresh_completeness()
        return True

    def _clear_le_file(self) -> None:
        self.le_source_path = None
        self.le_expected_sha256 = None
        self.existing_le_hash = None
        self.existing_le_name = None
        self._refresh_le_status()

    def _refresh_le_status(self) -> None:
        if self.le_source_path and self.le_expected_sha256:
            self.le_preview.setText(f"Selected: {Path(self.le_source_path).name} | SHA-256 {self.le_expected_sha256}")
        elif self.existing_le_hash:
            self.le_preview.setText(f"Retained: {self.existing_le_name or 'LE network'} | SHA-256 {self.existing_le_hash}")
        else:
            self.le_preview.setText("No LE network selected. The revision can be saved, but is not simulation-ready.")
        self._refresh_completeness()

    def _refresh_completeness(self) -> None:
        ready = bool(self.le_expected_sha256 or self.existing_le_hash)
        self.completeness.setText(
            "Simulation-ready: an immutable LE network will be attached."
            if ready else
            "Incomplete: no LE network is attached; the current AKABAK coupling cannot simulate this revision."
        )

    def build_payload(self) -> tuple[dict[str, Any], dict[str, Any]]:
        model = self.model.text().strip()
        if not model:
            raise ValueError("Model is required")
        parameters: dict[str, dict[str, Any]] = {}
        for key, (value_edit, unit_combo) in self.parameter_inputs.items():
            token = value_edit.text().strip()
            if token:
                try:
                    value = float(token.replace(",", "."))
                except ValueError as exc:
                    raise ValueError(f"{key} must be a number") from exc
                parameters[key] = {"value": value, "unit": unit_combo.currentText()}
        provenance = {
            "source": self.source.text().strip(),
            "source_url": self.source_url.text().strip(),
            "trust": str(self.trust.currentData()),
            "licence_note": self.licence_note.text().strip(),
        }
        if provenance["trust"] not in TRUST_STATES:
            raise ValueError("Unsupported trust state")
        definition = {
            "manufacturer": self.manufacturer.text().strip(), "model": model,
            "variant": self.variant.text().strip(), "kind": self.kind_value,
        }
        revision = {
            "parameters": parameters, "provenance": provenance,
            "le_network_hash": self.existing_le_hash,
            "le_network_name": self.existing_le_name,
            "network_description": dict(self.seed.get("network_description") or {}),
            "completeness": "simulation_ready" if (self.le_expected_sha256 or self.existing_le_hash) else "incomplete",
            "extensions": dict(self.seed.get("extensions") or {}),
        }
        if self.le_source_path:
            revision["le_source_path"] = self.le_source_path
            revision["le_expected_sha256"] = self.le_expected_sha256
        return definition, revision

    def _accept_valid(self) -> None:
        try:
            self.definition_payload, self.payload = self.build_payload()
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid revision", str(exc))
            return
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
        for button in (self.add_compression, self.add_cone, self.new_revision, self.duplicate, self.archive):
            actions.addWidget(button)
        actions.addStretch(1)
        root.addLayout(actions)

        advanced = QHBoxLayout()
        advanced.addWidget(QLabel("Advanced"))
        self.import_button = QPushButton("Import JSON")
        self.export_button = QPushButton("Export JSON")
        advanced.addWidget(self.import_button)
        advanced.addWidget(self.export_button)
        advanced.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        advanced.addWidget(close)
        root.addLayout(advanced)

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
            self.new_revision.setEnabled(False)
            self.archive.setEnabled(False)
            self.export_button.setEnabled(False)
            return
        row = next((item for item in self.service.list_drivers(include_archived=True) if item["driver_id"] == driver_id), None)
        revision = dict((row or {}).get("latest_revision") or {})
        ready = revision.get("completeness") == "simulation_ready" and bool(revision.get("le_network_hash"))
        parameters = revision.get("parameters") or {}
        parameter_lines = [f"  {name}: {item.get('value')} {item.get('unit')}" for name, item in parameters.items()]
        self.details.setPlainText("\n".join([
            f"{(row or {}).get('manufacturer', '')} {(row or {}).get('model', '')} {(row or {}).get('variant', '')}".strip(),
            f"Type: {(row or {}).get('kind', '')}",
            f"Origin: {(row or {}).get('origin', '')}",
            f"Revisions: {(row or {}).get('revision_count', 0)}",
            f"Status: {'Simulation-ready' if ready else 'Incomplete - no usable LE network'}",
            f"LE file: {revision.get('le_network_name') or 'none'}",
            f"LE SHA-256: {revision.get('le_network_hash') or 'none'}",
            "Parameters:", *(parameter_lines or ["  No optional parameters recorded."]),
            "", "Advanced JSON export retains all schema fields and immutable revisions.",
        ]))
        read_only = bool((row or {}).get("read_only"))
        self.new_revision.setEnabled(not read_only)
        self.archive.setEnabled(not read_only)
        self.export_button.setEnabled(True)

    def _create_driver(self, kind: str) -> None:
        editor = DriverRevisionEditorDialog(service=self.service, title="Create custom driver", kind=kind, parent=self)
        if editor.exec() != QDialog.Accepted or editor.payload is None or editor.definition_payload is None:
            return
        definition = DriverDefinition(
            driver_id=f"D-{uuid.uuid4()}", origin="user", **editor.definition_payload,
        )
        payload = dict(editor.payload)
        le_source_path = payload.pop("le_source_path", None)
        le_expected_sha256 = payload.pop("le_expected_sha256", None)
        revision = DriverRevision(
            revision_id=f"DR-{uuid.uuid4()}", driver_id=definition.driver_id, revision_number=1,
            parameters=dict(payload.get("parameters") or {}), provenance=dict(payload.get("provenance") or {}),
            le_network_hash=payload.get("le_network_hash"), le_network_name=payload.get("le_network_name"),
            network_description=dict(payload.get("network_description") or {}),
            completeness=str(payload.get("completeness") or "incomplete"),
            extensions=dict(payload.get("extensions") or {}),
        )
        try:
            self.service.create_driver(
                definition=asdict(definition), revision=asdict(revision),
                le_source_path=le_source_path, le_expected_sha256=le_expected_sha256,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Driver not created", str(exc))
            return
        self.refresh()

    def _new_revision(self) -> None:
        driver_id = self.selected_driver_id()
        if not driver_id:
            return
        row = next((item for item in self.service.list_drivers(include_archived=True) if item["driver_id"] == driver_id), None)
        if (row or {}).get("read_only"):
            QMessageBox.information(self, "Built-in driver", "Built-in drivers are read-only. Duplicate it to create an editable custom driver.")
            return
        latest = dict((row or {}).get("latest_revision") or {})
        seed = {key: latest.get(key) for key in (
            "parameters", "provenance", "le_network_hash", "le_network_name",
            "network_description", "completeness", "extensions",
        )}
        editor = DriverRevisionEditorDialog(
            service=self.service, title=f"New revision | {(row or {}).get('model', driver_id)}",
            kind=str((row or {}).get("kind") or "future_unknown"), definition=row, seed=seed, parent=self,
        )
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
        self.default_driver.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.default_driver.setMinimumContentsLength(28)
        self.driver_status = QLabel(self)
        self.driver_status.setObjectName("GeometryDriverStatus")
        self.driver_status.setWordWrap(True)
        driver_row.addRow("Default driver", self.default_driver)
        driver_row.addRow("Simulation status", self.driver_status)
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
        self.default_driver.currentIndexChanged.connect(lambda *_: self._show_driver_status())
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
                    ready = revision.get("completeness") == "simulation_ready" and bool(revision.get("le_network_hash"))
                    status = "ready" if ready else "incomplete / no LE"
                    self.default_driver.addItem(
                        f"{row.get('manufacturer')} | {row.get('model')} | r{revision.get('revision_number')} | {status}",
                        revision_id,
                    )
                    index = self.default_driver.count() - 1
                    self.default_driver.setItemData(
                        index,
                        f"Revision {revision_id}\nLE SHA-256: {revision.get('le_network_hash') or 'none'}",
                        Qt.ToolTipRole,
                    )
        self._sync_driver_selection()

    def _sync_driver_selection(self) -> None:
        geometry_id = self.current_geometry_id()
        row = next((item for item in self.service.list_geometries(self.project_id) if item["geometry_id"] == geometry_id), None)
        revision_id = str((row or {}).get("default_driver_revision_id") or "")
        index = self.default_driver.findData(revision_id)
        self.default_driver.setCurrentIndex(max(index, 0))
        self._show_driver_status()

    def _show_driver_status(self) -> None:
        revision_id = str(self.default_driver.currentData() or "")
        if not revision_id:
            self.driver_status.setText("No default driver. A driver revision must be selected before the current AKABAK coupling can run.")
            return
        revision: dict[str, Any] = {}
        for driver in self.service.list_drivers(include_archived=True):
            revision = next((item for item in driver.get("revisions", []) if item.get("revision_id") == revision_id), {})
            if revision:
                break
        if revision.get("completeness") == "simulation_ready" and revision.get("le_network_hash"):
            self.driver_status.setText(
                f"Simulation-ready. LE network {revision.get('le_network_name') or ''} | SHA-256 {revision['le_network_hash']}"
            )
        else:
            self.driver_status.setText("Incomplete: this revision has no usable LE network and cannot run through the current AKABAK coupling.")

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
