"""Minimal STL preview widget with Qt3D rendering and fallback mode."""

from __future__ import annotations

from array import array
import math
from pathlib import Path
import struct
from typing import List, Optional, Sequence, Tuple

try:
    from PySide6.QtCore import QByteArray, Qt
    from PySide6.QtGui import QColor, QVector3D
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("PySide6 is required for STL preview widget.") from exc

try:  # pragma: no cover - availability depends on PySide6 build
    from PySide6.Qt3DCore import QEntity
    from PySide6.Qt3DExtras import QOrbitCameraController, QPhongMaterial, Qt3DWindow
    from PySide6.Qt3DRender import QAttribute, QBuffer, QGeometry, QGeometryRenderer

    _QT3D_AVAILABLE = True
except Exception:  # pragma: no cover
    _QT3D_AVAILABLE = False


Vec3 = Tuple[float, float, float]


def _normalize(v: Vec3) -> Vec3:
    length = math.sqrt((v[0] * v[0]) + (v[1] * v[1]) + (v[2] * v[2]))
    if length <= 1e-12:
        return (0.0, 0.0, 1.0)
    return (v[0] / length, v[1] / length, v[2] / length)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        (a[1] * b[2]) - (a[2] * b[1]),
        (a[2] * b[0]) - (a[0] * b[2]),
        (a[0] * b[1]) - (a[1] * b[0]),
    )


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _update_bounds(bounds: List[float], v: Vec3) -> None:
    bounds[0] = min(bounds[0], v[0])
    bounds[1] = min(bounds[1], v[1])
    bounds[2] = min(bounds[2], v[2])
    bounds[3] = max(bounds[3], v[0])
    bounds[4] = max(bounds[4], v[1])
    bounds[5] = max(bounds[5], v[2])


def _looks_like_binary(data: bytes) -> bool:
    if len(data) < 84:
        return False
    tri_count = int.from_bytes(data[80:84], "little", signed=False)
    expected = 84 + (tri_count * 50)
    if expected == len(data):
        return True
    if expected < len(data) and not data[:5].lower().startswith(b"solid"):
        return True
    return False


def _parse_binary_stl(data: bytes) -> tuple[array, array, list[float]]:
    vertices = array("f")
    normals = array("f")
    bounds = [float("inf"), float("inf"), float("inf"), float("-inf"), float("-inf"), float("-inf")]

    if len(data) < 84:
        return vertices, normals, bounds

    tri_count = int.from_bytes(data[80:84], "little", signed=False)
    offset = 84
    for _ in range(tri_count):
        if offset + 50 > len(data):
            break
        nx, ny, nz = struct.unpack_from("<fff", data, offset)
        v1 = struct.unpack_from("<fff", data, offset + 12)
        v2 = struct.unpack_from("<fff", data, offset + 24)
        v3 = struct.unpack_from("<fff", data, offset + 36)
        offset += 50

        normal = _normalize((float(nx), float(ny), float(nz)))
        if abs(normal[0]) < 1e-9 and abs(normal[1]) < 1e-9 and abs(normal[2] - 1.0) < 1e-9:
            edge1 = _sub(v2, v1)
            edge2 = _sub(v3, v1)
            normal = _normalize(_cross(edge1, edge2))

        for v in (v1, v2, v3):
            vf = (float(v[0]), float(v[1]), float(v[2]))
            vertices.extend(vf)
            normals.extend(normal)
            _update_bounds(bounds, vf)

    return vertices, normals, bounds


def _parse_ascii_stl(data: bytes) -> tuple[array, array, list[float]]:
    text = data.decode("utf-8", errors="replace")
    vertices = array("f")
    normals = array("f")
    bounds = [float("inf"), float("inf"), float("inf"), float("-inf"), float("-inf"), float("-inf")]

    current_normal: Optional[Vec3] = None
    current_vertices: List[Vec3] = []

    for raw_line in text.splitlines():
        parts = raw_line.strip().split()
        if not parts:
            continue
        token = parts[0].lower()

        if token == "facet" and len(parts) >= 5 and parts[1].lower() == "normal":
            try:
                current_normal = (float(parts[2]), float(parts[3]), float(parts[4]))
            except Exception:
                current_normal = (0.0, 0.0, 1.0)
            current_vertices = []
            continue

        if token == "vertex" and len(parts) >= 4:
            try:
                current_vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            except Exception:
                continue
            continue

        if token == "endfacet" and len(current_vertices) >= 3:
            v1, v2, v3 = current_vertices[0], current_vertices[1], current_vertices[2]
            normal = _normalize(current_normal or (0.0, 0.0, 0.0))
            if abs(normal[0]) < 1e-9 and abs(normal[1]) < 1e-9 and abs(normal[2]) < 1e-9:
                normal = _normalize(_cross(_sub(v2, v1), _sub(v3, v1)))

            for v in (v1, v2, v3):
                vertices.extend(v)
                normals.extend(normal)
                _update_bounds(bounds, v)
            current_vertices = []
            continue

    return vertices, normals, bounds


def _load_stl_geometry(path: Path) -> tuple[array, array, list[float]]:
    data = path.read_bytes()
    if _looks_like_binary(data):
        vertices, normals, bounds = _parse_binary_stl(data)
    else:
        vertices, normals, bounds = _parse_ascii_stl(data)

    if len(vertices) == 0:
        raise ValueError(f"No triangles found in STL: {path}")
    return vertices, normals, bounds


class StlPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._fallback_label: Optional[QLabel] = None
        self._container: Optional[QWidget] = None
        self._root_entity = None
        self._mesh_entity = None
        self._camera = None

        if not _QT3D_AVAILABLE:
            self._fallback_label = QLabel("Qt3D renderer unavailable on this system.")
            self._fallback_label.setObjectName("SummaryText")
            self._fallback_label.setAlignment(Qt.AlignCenter)
            self._fallback_label.setWordWrap(True)
            root.addWidget(self._fallback_label, 1)
            return

        self._view = Qt3DWindow()
        self._view.defaultFrameGraph().setClearColor(QColor(0, 0, 0, 0))
        self._container = QWidget.createWindowContainer(self._view, self)
        self._container.setAttribute(Qt.WA_TranslucentBackground, True)
        self._container.setFocusPolicy(Qt.StrongFocus)
        self._container.setStyleSheet("background: transparent;")
        root.addWidget(self._container, 1)

        self._root_entity = QEntity()
        self._view.setRootEntity(self._root_entity)

        self._camera = self._view.camera()
        self._camera.lens().setPerspectiveProjection(45.0, 16.0 / 9.0, 0.01, 10000.0)
        self._camera.setPosition(QVector3D(0.0, 0.0, 220.0))
        self._camera.setViewCenter(QVector3D(0.0, 0.0, 0.0))

        self._orbit = QOrbitCameraController(self._root_entity)
        self._orbit.setLinearSpeed(120.0)
        self._orbit.setLookSpeed(220.0)
        self._orbit.setCamera(self._camera)

        self._material = QPhongMaterial(self._root_entity)
        self._material.setDiffuse(QColor(232, 232, 236))
        self._material.setAmbient(QColor(190, 190, 196))
        self._material.setSpecular(QColor(255, 255, 255))
        self._material.setShininess(64.0)

    def clear_mesh(self) -> None:
        if self._mesh_entity is not None:
            self._mesh_entity.setParent(None)
            self._mesh_entity.deleteLater()
            self._mesh_entity = None

    def load_stl(self, path: str | Path) -> None:
        stl_path = Path(path)
        if not stl_path.exists() or not stl_path.is_file():
            raise FileNotFoundError(f"STL not found: {stl_path}")

        if not _QT3D_AVAILABLE:
            if self._fallback_label is not None:
                self._fallback_label.setText(f"STL loaded: {stl_path.name} (viewer fallback)")
            return

        vertices, normals, bounds = _load_stl_geometry(stl_path)
        self.clear_mesh()

        geometry = QGeometry(self._root_entity)

        vertex_buffer = QBuffer(QBuffer.VertexBuffer, geometry)
        vertex_buffer.setData(QByteArray(vertices.tobytes()))
        normal_buffer = QBuffer(QBuffer.VertexBuffer, geometry)
        normal_buffer.setData(QByteArray(normals.tobytes()))

        vertex_count = len(vertices) // 3

        position_attr = QAttribute(geometry)
        position_attr.setName(QAttribute.defaultPositionAttributeName())
        position_attr.setVertexBaseType(QAttribute.Float)
        position_attr.setVertexSize(3)
        position_attr.setAttributeType(QAttribute.VertexAttribute)
        position_attr.setBuffer(vertex_buffer)
        position_attr.setByteStride(12)
        position_attr.setCount(vertex_count)

        normal_attr = QAttribute(geometry)
        normal_attr.setName(QAttribute.defaultNormalAttributeName())
        normal_attr.setVertexBaseType(QAttribute.Float)
        normal_attr.setVertexSize(3)
        normal_attr.setAttributeType(QAttribute.VertexAttribute)
        normal_attr.setBuffer(normal_buffer)
        normal_attr.setByteStride(12)
        normal_attr.setCount(vertex_count)

        geometry.addAttribute(position_attr)
        geometry.addAttribute(normal_attr)

        renderer = QGeometryRenderer()
        renderer.setPrimitiveType(QGeometryRenderer.Triangles)
        renderer.setGeometry(geometry)
        renderer.setVertexCount(vertex_count)

        self._mesh_entity = QEntity(self._root_entity)
        self._mesh_entity.addComponent(renderer)
        self._mesh_entity.addComponent(self._material)

        self._frame_camera(bounds)

    def _frame_camera(self, bounds: Sequence[float]) -> None:
        if self._camera is None or len(bounds) < 6:
            return

        min_x, min_y, min_z, max_x, max_y, max_z = [float(v) for v in list(bounds[:6])]
        center = QVector3D(
            (min_x + max_x) * 0.5,
            (min_y + max_y) * 0.5,
            (min_z + max_z) * 0.5,
        )
        size_x = max(0.001, max_x - min_x)
        size_y = max(0.001, max_y - min_y)
        size_z = max(0.001, max_z - min_z)
        radius = max(size_x, size_y, size_z) * 0.75
        distance = max(80.0, radius * 3.2)

        self._camera.setViewCenter(center)
        self._camera.setPosition(QVector3D(center.x(), center.y(), center.z() + distance))
