"""Interactive software-rendered 3D trajectory view (no Qt3D / WebEngine)."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .app_theme import ACCENT, BORDER, MUTED, PANEL_ALT, TEXT

_SLOW = np.array([45, 212, 191], dtype=np.float64)
_MID = np.array([230, 180, 80], dtype=np.float64)
_FAST = np.array([240, 113, 120], dtype=np.float64)


def speed_color(norm: float, alpha: int) -> QColor:
    """0 → teal, 0.5 → amber, 1 → red."""
    n = float(np.clip(norm, 0.0, 1.0))
    if n < 0.5:
        rgb = _SLOW + (_MID - _SLOW) * (n / 0.5)
    else:
        rgb = _MID + (_FAST - _MID) * ((n - 0.5) / 0.5)
    return QColor(int(rgb[0]), int(rgb[1]), int(rgb[2]), alpha)


def _normalized_speeds(speeds: np.ndarray | None, n: int) -> np.ndarray | None:
    if speeds is None or len(speeds) != n or n == 0:
        return None
    peak = float(np.max(speeds))
    if peak < 1e-6:
        return np.zeros(n)
    return speeds / peak


class Trajectory3DView(QWidget):
    """Orbit / pan / zoom a 3D polyline path."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setMouseTracking(True)
        self._path = np.zeros((0, 3), dtype=np.float64)
        self._yaw = 0.65  # rad
        self._pitch = 0.45
        self._zoom = 1.0
        self._auto_fit = True
        self._drag_origin: tuple[float, float] | None = None
        self._hint = "拖拽旋转 · 滚轮缩放 · 双击复位视角"
        self._status = "等待标定…"
        self._tip: np.ndarray | None = None
        self._axes = np.eye(3)
        self._speed_norm: np.ndarray | None = None

    def set_status(self, text: str) -> None:
        self._status = text
        self.update()

    def set_path(
        self,
        path: np.ndarray,
        tip_axes: np.ndarray | None = None,
        speeds: np.ndarray | None = None,
    ) -> None:
        if path is None or len(path) == 0:
            self._path = np.zeros((0, 3), dtype=np.float64)
            self._tip = None
            self._speed_norm = None
        else:
            self._path = np.asarray(path, dtype=np.float64)
            self._tip = self._path[-1]
            self._speed_norm = _normalized_speeds(speeds, len(self._path))
        if tip_axes is not None:
            self._axes = tip_axes
        self.update()

    def clear(self) -> None:
        self._path = np.zeros((0, 3), dtype=np.float64)
        self._tip = None
        self.update()

    def reset_camera(self) -> None:
        self._yaw = 0.65
        self._pitch = 0.45
        self._zoom = 1.0
        self._auto_fit = True
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = (event.position().x(), event.position().y())
            self._auto_fit = False

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_origin is None:
            return
        x, y = event.position().x(), event.position().y()
        dx = x - self._drag_origin[0]
        dy = y - self._drag_origin[1]
        self._drag_origin = (x, y)
        self._yaw += dx * 0.01
        self._pitch = float(np.clip(self._pitch + dy * 0.01, -1.2, 1.2))
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_origin = None

    def mouseDoubleClickEvent(self, _event) -> None:  # noqa: N802
        self.reset_camera()

    def wheelEvent(self, event) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        factor = 1.1 if delta > 0 else 1 / 1.1
        self._zoom = float(np.clip(self._zoom * factor, 0.2, 8.0))
        self._auto_fit = False
        self.update()

    def _project(self, pts: np.ndarray) -> np.ndarray:
        """pts (N,3) → screen (N,2) and depth (N,)."""
        if len(pts) == 0:
            return np.zeros((0, 2)), np.zeros(0)

        cy, sy = math.cos(self._yaw), math.sin(self._yaw)
        cp, sp = math.cos(self._pitch), math.sin(self._pitch)
        # yaw around Z, then pitch around X
        rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
        rx = np.array([[1, 0, 0], [0, cp, -sp], [0, sp, cp]])
        cam = rx @ rz @ pts.T  # 3xN

        w = max(self.width(), 1)
        h = max(self.height(), 1)
        span = 1.0
        if self._auto_fit and len(pts) >= 2:
            span = float(np.max(np.linalg.norm(pts - pts.mean(axis=0), axis=1)))
            span = max(span, 0.05)
        elif len(pts) >= 1:
            span = float(np.max(np.abs(pts))) if np.any(pts) else 0.5
            span = max(span, 0.05)

        scale = min(w, h) * 0.38 * self._zoom / span
        cx, cy_ = w * 0.5, h * 0.52
        # perspective-ish: use -Y as depth into screen after rotation
        depth = cam[1]
        screen = np.column_stack(
            [
                cx + cam[0] * scale,
                cy_ - cam[2] * scale,
            ]
        )
        return screen, depth

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(PANEL_ALT))

        # border
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

        self._draw_grid(p)
        self._draw_world_axes(p)
        self._draw_path(p)
        self._draw_tip(p)

        p.setPen(QColor(MUTED))
        p.setFont(QFont("", 11))
        p.drawText(14, 22, "3D Trajectory")
        p.drawText(14, self.height() - 14, self._hint)
        p.setPen(QColor(ACCENT))
        p.drawText(14, 42, self._status)

    def _draw_grid(self, p: QPainter) -> None:
        # ground plane square in world XY (Z=0)
        size = 1.0
        if len(self._path) >= 2:
            size = max(0.4, float(np.max(np.abs(self._path[:, :2]))) * 1.2)
        xs = np.linspace(-size, size, 7)
        ys = np.linspace(-size, size, 7)
        lines = []
        for x in xs:
            lines.append([[x, -size, 0], [x, size, 0]])
        for y in ys:
            lines.append([[-size, y, 0], [size, y, 0]])
        p.setPen(QPen(QColor(BORDER), 1))
        for a, b in lines:
            s, _ = self._project(np.array([a, b]))
            if len(s) == 2:
                p.drawLine(QPointF(s[0, 0], s[0, 1]), QPointF(s[1, 0], s[1, 1]))

    def _draw_world_axes(self, p: QPainter) -> None:
        origin = np.zeros((1, 3))
        axes = np.array([[0.25, 0, 0], [0, 0.25, 0], [0, 0, 0.25]])
        colors = [QColor("#ff6b6b"), QColor("#4ecdc4"), QColor("#ffe66d")]
        labels = ["X", "Y", "Z"]
        o, _ = self._project(origin)
        for i, color in enumerate(colors):
            s, _ = self._project(axes[i : i + 1])
            if len(o) and len(s):
                p.setPen(QPen(color, 2))
                p.drawLine(QPointF(o[0, 0], o[0, 1]), QPointF(s[0, 0], s[0, 1]))
                p.drawText(QPointF(s[0, 0] + 4, s[0, 1] - 4), labels[i])

    def _draw_path(self, p: QPainter) -> None:
        if len(self._path) < 2:
            return
        screen, _depth = self._project(self._path)
        n = len(screen)
        sn = self._speed_norm
        for i in range(1, n):
            t = i / (n - 1)
            alpha = int(40 + 180 * t)
            if sn is not None:
                color = speed_color(sn[i], alpha)
            else:
                color = QColor(ACCENT)
                color.setAlpha(alpha)
            width = 1.2 + 2.2 * t
            p.setPen(QPen(color, width))
            p.drawLine(
                QPointF(screen[i - 1, 0], screen[i - 1, 1]),
                QPointF(screen[i, 0], screen[i, 1]),
            )

    def _draw_tip(self, p: QPainter) -> None:
        if self._tip is None:
            return
        # local axes at tip for orientation
        scale = 0.12
        if len(self._path) >= 2:
            scale = max(0.08, float(np.max(np.linalg.norm(self._path - self._path.mean(0), axis=1))) * 0.15)
        tip = self._tip.reshape(1, 3)
        colors = [QColor("#ff6b6b"), QColor("#4ecdc4"), QColor("#ffe66d")]
        for i, color in enumerate(colors):
            end = tip + self._axes[:, i].reshape(1, 3) * scale
            s, _ = self._project(np.vstack([tip, end]))
            if len(s) == 2:
                p.setPen(QPen(color, 3))
                p.drawLine(QPointF(s[0, 0], s[0, 1]), QPointF(s[1, 0], s[1, 1]))
        s, _ = self._project(tip)
        if len(s):
            p.setBrush(QColor(TEXT))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(s[0, 0], s[0, 1]), 5, 5)


class TopDownPathView(QWidget):
    """XY (ground) projection — easiest to recognize a figure-8."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)
        self._path = np.zeros((0, 3), dtype=np.float64)
        self._speed_norm: np.ndarray | None = None
        self._title = "Top-down (X–Y) · 颜色=速度"

    def set_path(self, path: np.ndarray, speeds: np.ndarray | None = None) -> None:
        self._path = np.asarray(path, dtype=np.float64) if path is not None else np.zeros((0, 3))
        self._speed_norm = _normalized_speeds(speeds, len(self._path))
        self.update()

    def clear(self) -> None:
        self._path = np.zeros((0, 3), dtype=np.float64)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(PANEL_ALT))
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 10, 10)

        p.setPen(QColor(MUTED))
        p.drawText(14, 22, self._title)

        if len(self._path) < 2:
            p.setPen(QColor(MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "画 8 字时，俯视轮廓会出现在这里")
            return

        xy = self._path[:, :2]
        center = xy.mean(axis=0)
        span = np.max(np.linalg.norm(xy - center, axis=1))
        span = max(float(span), 0.05)
        w, h = self.width(), self.height()
        margin = 28
        scale = min(w - 2 * margin, h - 2 * margin) * 0.45 / span
        cx, cy = w * 0.5, h * 0.55

        def to_screen(pt: np.ndarray) -> QPointF:
            return QPointF(cx + (pt[0] - center[0]) * scale, cy - (pt[1] - center[1]) * scale)

        # axes
        p.setPen(QPen(QColor(BORDER), 1, Qt.PenStyle.DashLine))
        p.drawLine(QPointF(margin, cy), QPointF(w - margin, cy))
        p.drawLine(QPointF(cx, margin + 10), QPointF(cx, h - margin))

        n = len(xy)
        sn = self._speed_norm
        for i in range(1, n):
            t = i / (n - 1)
            alpha = int(50 + 200 * t)
            if sn is not None:
                color = speed_color(sn[i], alpha)
            else:
                color = QColor(ACCENT)
                color.setAlpha(alpha)
            p.setPen(QPen(color, 1.5 + 2.5 * t))
            p.drawLine(to_screen(xy[i - 1]), to_screen(xy[i]))

        tip = to_screen(xy[-1])
        p.setBrush(QColor(TEXT))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(tip, 5, 5)
