"""Qt management UI for project-local SpeakerAssemblies."""

from __future__ import annotations

from typing import Any

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QComboBox,
        QDialog,
        QDoubleSpinBox,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSplitter,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for SpeakerAssembly UI") from exc


class AssemblyEditorDialog(QDialog):
    def __init__(
        self,
        *,
        title: str,
        seed: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        data = dict(seed or {})
        self.setWindowTitle(title)
        self.resize(560, 320)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(str(data.get("name") or ""), self)
        self.name.setObjectName("AssemblyName")
        self.description = QTextEdit(self)
        self.description.setObjectName("AssemblyDescription")
        self.description.setPlainText(str(data.get("description") or ""))
        self.description.setMinimumHeight(110)
        form.addRow("Name *", self.name)
        form.addRow("Description", self.description)
        root.addLayout(form)
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel", self)
        save = QPushButton("Save Assembly", self)
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept_valid)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

    def _accept_valid(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Assembly not saved", "Name is required.")
            self.name.setFocus()
            return
        self.accept()

    def payload(self) -> dict[str, Any]:
        return {
            "name": self.name.text().strip(),
            "description": self.description.toPlainText().strip(),
        }


class AssemblyInstanceEditorDialog(QDialog):
    def __init__(
        self,
        *,
        geometries: list[dict[str, Any]],
        title: str,
        seed: dict[str, Any] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        data = dict(seed or {})
        transform = dict(data.get("transform") or {})
        self.setWindowTitle(title)
        self.resize(620, 610)
        root = QVBoxLayout(self)
        note = QLabel(
            "Coordinates use metres and a right-handed +X right, +Y up, +Z forward frame. "
            "Rotations are fixed-axis X then Y then Z in degrees.",
            self,
        )
        note.setWordWrap(True)
        root.addWidget(note)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        content = QWidget(scroll)
        content_root = QVBoxLayout(content)

        identity = QGroupBox("Geometry instance", content)
        form = QFormLayout(identity)
        self.geometry = QComboBox(identity)
        self.geometry.setObjectName("AssemblyInstanceGeometry")
        for row in geometries:
            self.geometry.addItem(f"{row['name']} [{row['role']}]", row["geometry_id"])
        geometry_index = self.geometry.findData(str(data.get("geometry_id") or ""))
        if geometry_index >= 0:
            self.geometry.setCurrentIndex(geometry_index)
        self.name = QLineEdit(str(data.get("name") or ""), identity)
        self.name.setObjectName("AssemblyInstanceName")
        self.description = QTextEdit(identity)
        self.description.setObjectName("AssemblyInstanceDescription")
        self.description.setPlainText(str(data.get("description") or ""))
        self.description.setMinimumHeight(80)
        self.arrangement = QComboBox(identity)
        self.arrangement.setObjectName("AssemblyInstanceArrangement")
        self.arrangement.addItem("Normal", "normal")
        self.arrangement.addItem("Coaxial", "coaxial")
        arrangement_index = self.arrangement.findData(str(data.get("arrangement") or "normal"))
        self.arrangement.setCurrentIndex(max(arrangement_index, 0))
        form.addRow("Geometry *", self.geometry)
        form.addRow("Instance name *", self.name)
        form.addRow("Description", self.description)
        form.addRow("Arrangement", self.arrangement)
        content_root.addWidget(identity)

        transform_group = QGroupBox("Spatial transform", content)
        transform_form = QFormLayout(transform_group)
        self.transform_inputs: dict[str, QDoubleSpinBox] = {}
        fields = (
            ("translation_x_m", "Translation X", " m", -1000.0, 1000.0, 6),
            ("translation_y_m", "Translation Y", " m", -1000.0, 1000.0, 6),
            ("translation_z_m", "Translation Z", " m", -1000.0, 1000.0, 6),
            ("rotation_x_deg", "Rotation X", " deg", -180.0, 180.0, 4),
            ("rotation_y_deg", "Rotation Y", " deg", -180.0, 180.0, 4),
            ("rotation_z_deg", "Rotation Z", " deg", -180.0, 180.0, 4),
        )
        for key, label, suffix, minimum, maximum, decimals in fields:
            editor = QDoubleSpinBox(transform_group)
            editor.setObjectName(f"AssemblyTransform_{key}")
            editor.setRange(minimum, maximum)
            editor.setDecimals(decimals)
            editor.setSuffix(suffix)
            editor.setKeyboardTracking(False)
            editor.setValue(float(transform.get(key, 0.0) or 0.0))
            transform_form.addRow(label, editor)
            self.transform_inputs[key] = editor
        content_root.addWidget(transform_group)
        content_root.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Cancel", self)
        save = QPushButton("Save Instance", self)
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._accept_valid)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)

    def _accept_valid(self) -> None:
        if not self.geometry.currentData():
            QMessageBox.warning(self, "Instance not saved", "Select a Geometry.")
            return
        if not self.name.text().strip():
            QMessageBox.warning(self, "Instance not saved", "Instance name is required.")
            self.name.setFocus()
            return
        self.accept()

    def payload(self) -> dict[str, Any]:
        return {
            "geometry_id": str(self.geometry.currentData() or ""),
            "name": self.name.text().strip(),
            "description": self.description.toPlainText().strip(),
            "arrangement": str(self.arrangement.currentData() or "normal"),
            "transform": {key: editor.value() for key, editor in self.transform_inputs.items()},
        }


class SpeakerAssemblyManagerDialog(QDialog):
    """Single service-backed management surface for SpeakerAssemblies."""

    def __init__(
        self,
        service: Any,
        project_id: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = str(project_id)
        self.setWindowTitle("Speaker Assemblies")
        self.resize(980, 680)
        self.setMinimumSize(680, 500)
        root = QVBoxLayout(self)
        note = QLabel(
            "Arrange immutable snapshots of existing project Geometries. "
            "This foundation does not run a coupled simulation.",
            self,
        )
        note.setWordWrap(True)
        root.addWidget(note)
        splitter = QSplitter(Qt.Horizontal, self)

        assembly_panel = QWidget(splitter)
        assembly_root = QVBoxLayout(assembly_panel)
        assembly_root.addWidget(QLabel("Assemblies", assembly_panel))
        self.assembly_list = QListWidget(assembly_panel)
        self.assembly_list.setObjectName("SpeakerAssemblyList")
        assembly_root.addWidget(self.assembly_list, 1)
        assembly_actions = QGridLayout()
        self.new_assembly_button = QPushButton("New Assembly", assembly_panel)
        self.edit_assembly_button = QPushButton("Edit Details", assembly_panel)
        self.archive_assembly_button = QPushButton("Archive", assembly_panel)
        assembly_actions.addWidget(self.new_assembly_button, 0, 0)
        assembly_actions.addWidget(self.edit_assembly_button, 0, 1)
        assembly_actions.addWidget(self.archive_assembly_button, 1, 0, 1, 2)
        assembly_root.addLayout(assembly_actions)

        instance_panel = QWidget(splitter)
        instance_root = QVBoxLayout(instance_panel)
        self.assembly_details = QLabel(instance_panel)
        self.assembly_details.setObjectName("SpeakerAssemblyDetails")
        self.assembly_details.setWordWrap(True)
        instance_root.addWidget(self.assembly_details)
        self.instance_list = QListWidget(instance_panel)
        self.instance_list.setObjectName("SpeakerAssemblyInstanceList")
        instance_root.addWidget(self.instance_list, 1)
        instance_actions = QGridLayout()
        self.add_instance_button = QPushButton("Add Instance", instance_panel)
        self.edit_instance_button = QPushButton("Edit Instance", instance_panel)
        self.move_up_button = QPushButton("Move Up", instance_panel)
        self.move_down_button = QPushButton("Move Down", instance_panel)
        self.remove_instance_button = QPushButton("Remove Instance", instance_panel)
        instance_actions.addWidget(self.add_instance_button, 0, 0)
        instance_actions.addWidget(self.edit_instance_button, 0, 1)
        instance_actions.addWidget(self.move_up_button, 1, 0)
        instance_actions.addWidget(self.move_down_button, 1, 1)
        instance_actions.addWidget(self.remove_instance_button, 2, 0, 1, 2)
        instance_root.addLayout(instance_actions)
        splitter.addWidget(assembly_panel)
        splitter.addWidget(instance_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_row.addWidget(close_button)
        root.addLayout(close_row)

        self.new_assembly_button.clicked.connect(self._new_assembly)
        self.edit_assembly_button.clicked.connect(self._edit_assembly)
        self.archive_assembly_button.clicked.connect(self._archive_assembly)
        self.add_instance_button.clicked.connect(self._add_instance)
        self.edit_instance_button.clicked.connect(self._edit_instance)
        self.move_up_button.clicked.connect(lambda: self._move_instance(-1))
        self.move_down_button.clicked.connect(lambda: self._move_instance(1))
        self.remove_instance_button.clicked.connect(self._remove_instance)
        self.assembly_list.currentItemChanged.connect(lambda *_: self._refresh_instances())
        self.instance_list.currentItemChanged.connect(lambda *_: self._refresh_action_state())
        self.refresh()

    def current_assembly_id(self) -> str | None:
        item = self.assembly_list.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def current_instance_id(self) -> str | None:
        item = self.instance_list.currentItem()
        return str(item.data(Qt.UserRole)) if item is not None else None

    def _current_assembly(self) -> dict[str, Any] | None:
        assembly_id = self.current_assembly_id()
        if not assembly_id:
            return None
        return self.service.get_speaker_assembly(self.project_id, assembly_id)

    def refresh(self, *, preferred_assembly_id: str | None = None) -> None:
        selected = preferred_assembly_id or self.current_assembly_id()
        self.assembly_list.clear()
        for row in self.service.list_speaker_assemblies(self.project_id):
            item = QListWidgetItem(f"{row['name']} · {len(row.get('instances') or [])} instances")
            item.setData(Qt.UserRole, row["assembly_id"])
            item.setToolTip(str(row.get("description") or row["assembly_id"]))
            self.assembly_list.addItem(item)
            if row["assembly_id"] == selected:
                self.assembly_list.setCurrentItem(item)
        if self.assembly_list.currentItem() is None and self.assembly_list.count():
            self.assembly_list.setCurrentRow(0)
        self._refresh_instances()

    def _refresh_instances(self, *, preferred_instance_id: str | None = None) -> None:
        self.instance_list.clear()
        assembly = self._current_assembly()
        if not assembly:
            self.assembly_details.setText("No Assembly selected. Create one to arrange Geometry snapshots.")
            self._refresh_action_state()
            return
        description = str(assembly.get("description") or "No description")
        self.assembly_details.setText(
            f"{assembly['name']} · {assembly['assembly_id']}\n{description}\n"
            "Snapshot transforms only; coupled simulation is not implemented."
        )
        for row in list(assembly.get("instances") or []):
            transform = dict(row.get("transform") or {})
            item = QListWidgetItem(
                f"{int(row['order_index']) + 1}. {row['name']} · {row['arrangement']} · "
                f"{row['geometry_id']} · T=({transform.get('translation_x_m', 0):g}, "
                f"{transform.get('translation_y_m', 0):g}, {transform.get('translation_z_m', 0):g}) m · "
                f"R=({transform.get('rotation_x_deg', 0):g}, {transform.get('rotation_y_deg', 0):g}, "
                f"{transform.get('rotation_z_deg', 0):g}) deg"
            )
            item.setData(Qt.UserRole, row["instance_id"])
            item.setToolTip(f"Geometry snapshot SHA-256: {row['geometry_snapshot_hash']}")
            self.instance_list.addItem(item)
            if row["instance_id"] == preferred_instance_id:
                self.instance_list.setCurrentItem(item)
        if self.instance_list.currentItem() is None and self.instance_list.count():
            self.instance_list.setCurrentRow(0)
        self._refresh_action_state()

    def _refresh_action_state(self) -> None:
        has_assembly = bool(self.current_assembly_id())
        has_instance = bool(self.current_instance_id())
        for button in (self.edit_assembly_button, self.archive_assembly_button, self.add_instance_button):
            button.setEnabled(has_assembly)
        for button in (self.edit_instance_button, self.move_up_button, self.move_down_button, self.remove_instance_button):
            button.setEnabled(has_instance)
        row = self.instance_list.currentRow()
        self.move_up_button.setEnabled(has_instance and row > 0)
        self.move_down_button.setEnabled(has_instance and row >= 0 and row < self.instance_list.count() - 1)

    def create_assembly(self, payload: dict[str, Any]) -> dict[str, Any]:
        row = self.service.create_speaker_assembly(self.project_id, **payload)
        self.refresh(preferred_assembly_id=row["assembly_id"])
        return row

    def update_assembly(self, payload: dict[str, Any]) -> dict[str, Any]:
        assembly_id = self.current_assembly_id()
        if not assembly_id:
            raise ValueError("No SpeakerAssembly selected")
        row = self.service.update_speaker_assembly(self.project_id, assembly_id, **payload)
        self.refresh(preferred_assembly_id=assembly_id)
        return row

    def add_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        assembly_id = self.current_assembly_id()
        if not assembly_id:
            raise ValueError("No SpeakerAssembly selected")
        row = self.service.add_speaker_assembly_instance(self.project_id, assembly_id, **payload)
        instance_id = row["instances"][-1]["instance_id"]
        self.refresh(preferred_assembly_id=assembly_id)
        self._refresh_instances(preferred_instance_id=instance_id)
        return row

    def update_instance(self, payload: dict[str, Any]) -> dict[str, Any]:
        assembly_id = self.current_assembly_id()
        instance_id = self.current_instance_id()
        if not assembly_id or not instance_id:
            raise ValueError("No Geometry instance selected")
        row = self.service.update_speaker_assembly_instance(
            self.project_id,
            assembly_id,
            instance_id,
            **payload,
        )
        self.refresh(preferred_assembly_id=assembly_id)
        self._refresh_instances(preferred_instance_id=instance_id)
        return row

    def move_instance(self, delta: int) -> dict[str, Any]:
        assembly_id = self.current_assembly_id()
        instance_id = self.current_instance_id()
        if not assembly_id or not instance_id:
            raise ValueError("No Geometry instance selected")
        row = self.service.move_speaker_assembly_instance(
            self.project_id,
            assembly_id,
            instance_id,
            self.instance_list.currentRow() + int(delta),
        )
        self.refresh(preferred_assembly_id=assembly_id)
        self._refresh_instances(preferred_instance_id=instance_id)
        return row

    def remove_instance(self) -> dict[str, Any]:
        assembly_id = self.current_assembly_id()
        instance_id = self.current_instance_id()
        if not assembly_id or not instance_id:
            raise ValueError("No Geometry instance selected")
        row = self.service.remove_speaker_assembly_instance(self.project_id, assembly_id, instance_id)
        self.refresh(preferred_assembly_id=assembly_id)
        return row

    def _new_assembly(self) -> None:
        dialog = AssemblyEditorDialog(title="New SpeakerAssembly", parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.create_assembly(dialog.payload())

    def _edit_assembly(self) -> None:
        assembly = self._current_assembly()
        if not assembly:
            return
        dialog = AssemblyEditorDialog(title="Edit SpeakerAssembly", seed=assembly, parent=self)
        if dialog.exec() == QDialog.Accepted:
            self.update_assembly(dialog.payload())

    def _archive_assembly(self) -> None:
        assembly_id = self.current_assembly_id()
        if not assembly_id:
            return
        if QMessageBox.question(
            self,
            "Archive SpeakerAssembly",
            "Archive this Assembly? Its manifest and snapshots remain readable.",
        ) != QMessageBox.Yes:
            return
        self.service.archive_speaker_assembly(self.project_id, assembly_id)
        self.refresh()

    def _geometries(self) -> list[dict[str, Any]]:
        return [row for row in self.service.list_geometries(self.project_id) if not row.get("archived_at")]

    def _add_instance(self) -> None:
        dialog = AssemblyInstanceEditorDialog(
            geometries=self._geometries(),
            title="Add Geometry Instance",
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.add_instance(dialog.payload())

    def _edit_instance(self) -> None:
        assembly = self._current_assembly()
        instance_id = self.current_instance_id()
        if not assembly or not instance_id:
            return
        seed = next(item for item in assembly["instances"] if item["instance_id"] == instance_id)
        dialog = AssemblyInstanceEditorDialog(
            geometries=self._geometries(),
            title="Edit Geometry Instance",
            seed=seed,
            parent=self,
        )
        if dialog.exec() == QDialog.Accepted:
            self.update_instance(dialog.payload())

    def _move_instance(self, delta: int) -> None:
        if self.current_instance_id():
            self.move_instance(delta)

    def _remove_instance(self) -> None:
        if not self.current_instance_id():
            return
        if QMessageBox.question(
            self,
            "Remove Geometry Instance",
            "Remove this instance from the Assembly? The source Geometry is not changed.",
        ) == QMessageBox.Yes:
            self.remove_instance()
