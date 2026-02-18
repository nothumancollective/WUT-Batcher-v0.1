"""Minimal STL preview widget with Qt3D rendering and fallback mode."""

from __future__ import annotations

from array import array
import math
from pathlib import Path
import re
import struct
from typing import Any, List, Mapping, Optional, Sequence, Tuple

try:
    from PySide6.QtCore import QByteArray, QPoint, QPointF, Qt
    from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPen, QPolygonF, QVector3D, QWheelEvent
    from PySide6.QtWidgets import QVBoxLayout, QWidget
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


def _as_float_list(raw: Any) -> List[float]:
    if raw is None:
        return []
    if isinstance(raw, (int, float)):
        return [float(raw)]
    if isinstance(raw, str):
        values: List[float] = []
        for token in re.split(r"[,\s;]+", raw.strip()):
            if not token:
                continue
            try:
                values.append(float(token.replace(",", ".")))
            except Exception:
                continue
        return values
    if isinstance(raw, (list, tuple)):
        values = []
        for item in list(raw):
            try:
                values.append(float(item))
            except Exception:
                continue
        return values
    return []


def _expand4(values: List[float], *, fallback: float) -> List[float]:
    if not values:
        return [float(fallback)] * 4
    out = [float(item) for item in values[:4]]
    while len(out) < 4:
        out.append(float(out[-1]))
    return out


class _SoftwareStlCanvas(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self._triangles: List[tuple[Vec3, Vec3, Vec3, Vec3]] = []
        self._enclosure_edges: List[tuple[Vec3, Vec3]] = []
        self._rot_x = -12.0
        self._rot_y = 24.0
        self._zoom = 1.0
        self._last_pos = QPoint()
        self._dragging = False

    def clear_mesh(self) -> None:
        self._triangles = []
        self._enclosure_edges = []
        self.update()

    def set_mesh(self, vertices: array, normals: array, bounds: Sequence[float]) -> None:
        if len(bounds) < 6:
            self.clear_mesh()
            return
        min_x, min_y, min_z, max_x, max_y, max_z = [float(v) for v in list(bounds[:6])]
        center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)
        span = max(max_x - min_x, max_y - min_y, max_z - min_z, 1e-6)

        tris: List[tuple[Vec3, Vec3, Vec3, Vec3]] = []
        tri_count = len(vertices) // 9
        for index in range(tri_count):
            base = index * 9
            try:
                v1 = (
                    (float(vertices[base + 0]) - center[0]) / span,
                    (float(vertices[base + 1]) - center[1]) / span,
                    (float(vertices[base + 2]) - center[2]) / span,
                )
                v2 = (
                    (float(vertices[base + 3]) - center[0]) / span,
                    (float(vertices[base + 4]) - center[1]) / span,
                    (float(vertices[base + 5]) - center[2]) / span,
                )
                v3 = (
                    (float(vertices[base + 6]) - center[0]) / span,
                    (float(vertices[base + 7]) - center[1]) / span,
                    (float(vertices[base + 8]) - center[2]) / span,
                )
            except Exception:
                continue

            nbase = index * 9
            normal: Vec3
            if nbase + 2 < len(normals):
                normal = _normalize(
                    (
                        float(normals[nbase + 0]),
                        float(normals[nbase + 1]),
                        float(normals[nbase + 2]),
                    )
                )
            else:
                normal = _normalize(_cross(_sub(v2, v1), _sub(v3, v1)))

            tris.append((v1, v2, v3, normal))

        self._triangles = tris
        self.update()

    def clear_enclosure_overlay(self) -> None:
        self._enclosure_edges = []
        self.update()

    def set_enclosure_overlay_bounds(self, bounds: Sequence[float]) -> None:
        if len(bounds) < 6:
            self.clear_enclosure_overlay()
            return
        min_x, min_y, min_z, max_x, max_y, max_z = [float(v) for v in list(bounds[:6])]
        points = [
            (min_x, min_y, min_z),
            (max_x, min_y, min_z),
            (max_x, max_y, min_z),
            (min_x, max_y, min_z),
            (min_x, min_y, max_z),
            (max_x, min_y, max_z),
            (max_x, max_y, max_z),
            (min_x, max_y, max_z),
        ]
        edges_idx = (
            (0, 1),
            (1, 2),
            (2, 3),
            (3, 0),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 4),
            (0, 4),
            (1, 5),
            (2, 6),
            (3, 7),
        )
        self._enclosure_edges = [(points[a], points[b]) for a, b in edges_idx]
        self.update()

    def triangle_count(self) -> int:
        return int(len(self._triangles))

    def _rotate(self, v: Vec3) -> Vec3:
        ry = math.radians(self._rot_y)
        rx = math.radians(self._rot_x)
        cosy = math.cos(ry)
        siny = math.sin(ry)
        cosx = math.cos(rx)
        sinx = math.sin(rx)

        x1 = (v[0] * cosy) + (v[2] * siny)
        z1 = (-v[0] * siny) + (v[2] * cosy)
        y2 = (v[1] * cosx) - (z1 * sinx)
        z2 = (v[1] * sinx) + (z1 * cosx)
        return (x1, y2, z2)

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))

        if not self._triangles:
            return

        width = max(1, int(self.width()))
        height = max(1, int(self.height()))
        cx = width * 0.5
        cy = height * 0.5
        px_scale = min(width, height) * 0.68
        cam_dist = 3.2

        light = _normalize((0.35, -0.4, 1.0))
        max_draw = 22000
        stride = max(1, len(self._triangles) // max_draw)
        draw_items: List[tuple[float, QPolygonF, QColor]] = []

        for tri_index in range(0, len(self._triangles), stride):
            v1, v2, v3, normal = self._triangles[tri_index]
            rv1 = self._rotate(v1)
            rv2 = self._rotate(v2)
            rv3 = self._rotate(v3)
            rn = _normalize(self._rotate(normal))

            def _project(v: Vec3) -> tuple[float, float, float]:
                denom = max(0.18, cam_dist - v[2])
                f = (self._zoom / denom) * px_scale
                return (cx + (v[0] * f), cy - (v[1] * f), v[2])

            p1 = _project(rv1)
            p2 = _project(rv2)
            p3 = _project(rv3)
            z_avg = (p1[2] + p2[2] + p3[2]) / 3.0

            intensity = max(0.18, min(1.0, (rn[0] * light[0]) + (rn[1] * light[1]) + (rn[2] * light[2])))
            base = 182
            shade = min(255, max(0, int(base + (73.0 * intensity))))
            fill = QColor(shade, shade, shade, 238)
            poly = QPolygonF([QPointF(p1[0], p1[1]), QPointF(p2[0], p2[1]), QPointF(p3[0], p3[1])])
            draw_items.append((z_avg, poly, fill))

        draw_items.sort(key=lambda item: float(item[0]))
        pen = QPen(QColor(248, 248, 250, 40))
        pen.setWidth(1)
        painter.setPen(pen)
        for _z, polygon, color in draw_items:
            painter.setBrush(color)
            painter.drawPolygon(polygon)

        if self._enclosure_edges:
            cam_dist = 3.2

            def _project(v: Vec3) -> QPointF:
                rv = self._rotate(v)
                denom = max(0.18, cam_dist - rv[2])
                f = (self._zoom / denom) * px_scale
                return QPointF(cx + (rv[0] * f), cy - (rv[1] * f))

            enclosure_pen = QPen(QColor(124, 164, 220, 210))
            enclosure_pen.setWidth(2)
            painter.setPen(enclosure_pen)
            painter.setBrush(Qt.NoBrush)
            for start, end in self._enclosure_edges:
                painter.drawLine(_project(start), _project(end))

    def mousePressEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._last_pos = event.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if self._dragging:
            delta = event.pos() - self._last_pos
            self._last_pos = event.pos()
            self._rot_y += float(delta.x()) * 0.6
            self._rot_x += float(delta.y()) * 0.6
            self._rot_x = max(-89.0, min(89.0, self._rot_x))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # type: ignore[override]
        delta = float(event.angleDelta().y())
        if abs(delta) <= 1e-9:
            return
        factor = 1.11 if delta > 0 else 0.90
        self._zoom = max(0.36, min(4.0, self._zoom * factor))
        self.update()
        event.accept()


class StlPreviewWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._software_canvas: Optional[_SoftwareStlCanvas] = None
        self._container: Optional[QWidget] = None
        self._root_entity = None
        self._mesh_entity = None
        self._camera = None
        self._last_mesh_bounds: Optional[List[float]] = None

        if not _QT3D_AVAILABLE:
            self._software_canvas = _SoftwareStlCanvas(self)
            root.addWidget(self._software_canvas, 1)
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
        self._camera.setPosition(QVector3D(0.0, 0.0, 80.0))
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
        self._last_mesh_bounds = None
        if self._software_canvas is not None:
            self._software_canvas.clear_mesh()
        if self._mesh_entity is not None:
            self._mesh_entity.setParent(None)
            self._mesh_entity.deleteLater()
            self._mesh_entity = None

    def load_stl(self, path: str | Path) -> None:
        stl_path = Path(path)
        if not stl_path.exists() or not stl_path.is_file():
            raise FileNotFoundError(f"STL not found: {stl_path}")

        vertices, normals, bounds = _load_stl_geometry(stl_path)
        self._last_mesh_bounds = [float(item) for item in list(bounds[:6])]

        if not _QT3D_AVAILABLE:
            if self._software_canvas is None:
                raise RuntimeError("STL software renderer is unavailable.")
            self.clear_mesh()
            self._last_mesh_bounds = [float(item) for item in list(bounds[:6])]
            self._software_canvas.set_mesh(vertices, normals, bounds)
            return

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

    def set_enclosure_overlay(self, enclosure: Optional[Mapping[str, Any]]) -> None:
        if self._software_canvas is None:
            return
        bounds = self._last_mesh_bounds
        if bounds is None or enclosure is None or not isinstance(enclosure, Mapping):
            self._software_canvas.clear_enclosure_overlay()
            return

        min_x, min_y, min_z, max_x, max_y, max_z = [float(v) for v in list(bounds[:6])]
        span = max(max_x - min_x, max_y - min_y, max_z - min_z, 1e-6)
        center = ((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, (min_z + max_z) * 0.5)

        spacing = _expand4(_as_float_list(enclosure.get("Spacing")), fallback=0.0)
        depth_raw = enclosure.get("Depth")
        depth = float(_as_float_list(depth_raw)[0]) if _as_float_list(depth_raw) else 0.0
        if depth <= 0.0 and str(enclosure.get("Plan", "") or "").strip():
            depth = float(max_z - min_z)
        if depth <= 0.0:
            self._software_canvas.clear_enclosure_overlay()
            return

        raw_bounds = [
            float(min_x - spacing[0]),
            float(min_y - spacing[3]),
            float(min_z),
            float(max_x + spacing[2]),
            float(max_y + spacing[1]),
            float(max_z + depth),
        ]
        norm_bounds = [
            (raw_bounds[0] - center[0]) / span,
            (raw_bounds[1] - center[1]) / span,
            (raw_bounds[2] - center[2]) / span,
            (raw_bounds[3] - center[0]) / span,
            (raw_bounds[4] - center[1]) / span,
            (raw_bounds[5] - center[2]) / span,
        ]
        self._software_canvas.set_enclosure_overlay_bounds(norm_bounds)

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
        distance = max(26.0, radius * 1.125)

        self._camera.setViewCenter(center)
        self._camera.setPosition(QVector3D(center.x(), center.y(), center.z() + distance))
