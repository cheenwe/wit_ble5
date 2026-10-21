"""WitMotion BLE 5.0 realtime dashboard with 3D air-drawn trajectory."""

from __future__ import annotations

import sys
import time
from collections import deque

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from wit_ble5.protocol import RATE_CODES, ImuSample

from .app_theme import (
    ACCENT,
    ACCENT_DIM,
    AXIS_COLORS,
    BG,
    BORDER,
    DANGER,
    MUTED,
    OK,
    PANEL,
    PANEL_ALT,
    TEXT,
    WARN,
)
from .ble_worker import BleWorker
from .tracker import TrajectoryTracker, rotation_body_to_world
from .view3d import TopDownPathView, Trajectory3DView

WINDOW_SEC = 15.0
MAX_POINTS = 3000


class StatusDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(MUTED)
        self.setFixedSize(14, 14)

    def set_state(self, state: str) -> None:
        colors = {
            "idle": MUTED,
            "scanning": WARN,
            "connected": OK,
            "error": DANGER,
        }
        self._color = QColor(colors.get(state, MUTED))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(self._color)
        p.setPen(QPen(self._color.darker(130), 1))
        p.drawEllipse(2, 2, 10, 10)


class MetricCard(QFrame):
    def __init__(self, title: str, unit: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        head = QLabel(title)
        head.setObjectName("metricTitle")
        layout.addWidget(head)

        self.values = QLabel("—  —  —")
        self.values.setObjectName("metricValues")
        self.values.setWordWrap(True)
        layout.addWidget(self.values)

        foot = QLabel(unit)
        foot.setObjectName("metricUnit")
        layout.addWidget(foot)

    def set_xyz(self, x: float, y: float, z: float, fmt: str = "+.3f") -> None:
        self.values.setText(
            f'<span style="color:{AXIS_COLORS["x"]}">X {x:{fmt}}</span>   '
            f'<span style="color:{AXIS_COLORS["y"]}">Y {y:{fmt}}</span>   '
            f'<span style="color:{AXIS_COLORS["z"]}">Z {z:{fmt}}</span>'
        )

    def set_html(self, html: str) -> None:
        self.values.setText(html)


class ImuPlot(pg.PlotWidget):
    def __init__(self, title: str, ylabel: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackground(PANEL_ALT)
        self.showGrid(x=True, y=True, alpha=0.18)
        self.setLabel("left", ylabel, color=MUTED)
        self.setLabel("bottom", "t (s)", color=MUTED)
        self.setTitle(title, color=TEXT, size="11pt")
        self.getAxis("left").setPen(pg.mkPen(BORDER))
        self.getAxis("bottom").setPen(pg.mkPen(BORDER))
        self.getAxis("left").setTextPen(pg.mkPen(MUTED))
        self.getAxis("bottom").setTextPen(pg.mkPen(MUTED))
        self.addLegend(offset=(8, 8), labelTextColor=MUTED, brush=pg.mkBrush(0, 0, 0, 80))
        self.setMinimumHeight(160)
        self.setXRange(-WINDOW_SEC, 0, padding=0)

        self.curves = {
            "x": self.plot(pen=pg.mkPen(AXIS_COLORS["x"], width=2), name="X"),
            "y": self.plot(pen=pg.mkPen(AXIS_COLORS["y"], width=2), name="Y"),
            "z": self.plot(pen=pg.mkPen(AXIS_COLORS["z"], width=2), name="Z"),
        }
        self._t: deque[float] = deque(maxlen=MAX_POINTS)
        self._x: deque[float] = deque(maxlen=MAX_POINTS)
        self._y: deque[float] = deque(maxlen=MAX_POINTS)
        self._z: deque[float] = deque(maxlen=MAX_POINTS)
        self._t0: float | None = None

    def clear_data(self) -> None:
        self._t.clear()
        self._x.clear()
        self._y.clear()
        self._z.clear()
        self._t0 = None
        for c in self.curves.values():
            c.setData([], [])

    def push(self, now: float, x: float, y: float, z: float) -> None:
        if self._t0 is None:
            self._t0 = now
        self._t.append(now - self._t0)
        self._x.append(x)
        self._y.append(y)
        self._z.append(z)

    def redraw(self) -> None:
        if not self._t:
            return
        t = np.asarray(self._t, dtype=np.float64)
        t_rel = t - t[-1]
        mask = t_rel >= -WINDOW_SEC
        t_rel = t_rel[mask]
        self.curves["x"].setData(t_rel, np.asarray(self._x, dtype=np.float64)[mask])
        self.curves["y"].setData(t_rel, np.asarray(self._y, dtype=np.float64)[mask])
        self.curves["z"].setData(t_rel, np.asarray(self._z, dtype=np.float64)[mask])
        self.setXRange(-WINDOW_SEC, 0, padding=0.02)


class SpeedPlot(pg.PlotWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setBackground(PANEL_ALT)
        self.showGrid(x=True, y=True, alpha=0.18)
        self.setLabel("left", "cm/s", color=MUTED)
        self.setLabel("bottom", "t (s)", color=MUTED)
        self.setTitle("移动速度（推算）", color=TEXT, size="10pt")
        for ax in ("left", "bottom"):
            self.getAxis(ax).setPen(pg.mkPen(BORDER))
            self.getAxis(ax).setTextPen(pg.mkPen(MUTED))
        self.setMinimumHeight(150)
        self.setMaximumHeight(200)
        self.setXRange(-WINDOW_SEC, 0, padding=0)
        self.curve = self.plot(
            pen=pg.mkPen(WARN, width=2),
            fillLevel=0,
            brush=pg.mkBrush(230, 180, 80, 50),
        )
        self._t: deque[float] = deque(maxlen=MAX_POINTS)
        self._v: deque[float] = deque(maxlen=MAX_POINTS)

    def clear_data(self) -> None:
        self._t.clear()
        self._v.clear()
        self.curve.setData([], [])

    def push(self, now: float, speed_cm_s: float) -> None:
        self._t.append(now)
        self._v.append(speed_cm_s)

    def redraw(self) -> None:
        if not self._t:
            return
        t = np.asarray(self._t, dtype=np.float64)
        t_rel = t - t[-1]
        mask = t_rel >= -WINDOW_SEC
        self.curve.setData(t_rel[mask], np.asarray(self._v, dtype=np.float64)[mask])
        self.setXRange(-WINDOW_SEC, 0, padding=0.02)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Wit BLE5 · 空间轨迹")
        self.resize(1280, 860)
        self.setMinimumSize(1024, 700)

        self.worker = BleWorker()
        self.worker.start()
        self.tracker = TrajectoryTracker(mode="hybrid", integrate_z=False, scale=4.0)
        self._connected = False
        self._frame_count = 0
        self._pending: deque[tuple[float, ImuSample]] = deque(maxlen=2000)
        self._devices: list[dict] = []

        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 16, 18, 16)
        outer.setSpacing(12)

        outer.addWidget(self._build_header())
        outer.addWidget(self._build_toolbar())
        outer.addWidget(self._build_metrics())
        outer.addWidget(self._build_tabs(), stretch=1)
        outer.addWidget(self._build_footer())

        self._wire()
        self._apply_style()

        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(33)
        self._plot_timer.timeout.connect(self._flush_plots)
        self._plot_timer.start()

    def _build_header(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("header")
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 14, 16, 14)

        brand = QVBoxLayout()
        title = QLabel("WIT BLE5")
        title.setObjectName("brand")
        sub = QLabel("空中画轨迹 · 默认「手臂混合」跟随手的平移画 8 字")
        sub.setObjectName("subtitle")
        brand.addWidget(title)
        brand.addWidget(sub)
        row.addLayout(brand)
        row.addStretch()

        self.dot = StatusDot()
        self.state_label = QLabel("Idle")
        self.state_label.setObjectName("stateLabel")
        state_box = QHBoxLayout()
        state_box.setSpacing(8)
        state_box.addWidget(self.dot)
        state_box.addWidget(self.state_label)
        row.addLayout(state_box)
        return bar

    def _build_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("toolbar")
        col = QVBoxLayout(bar)
        col.setContentsMargins(14, 12, 14, 12)
        col.setSpacing(10)

        row1 = QHBoxLayout()
        row1.setSpacing(10)
        self.btn_scan = QPushButton("Scan")
        self.btn_scan.setObjectName("btnSecondary")
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.setObjectName("btnPrimary")
        self.btn_disconnect = QPushButton("Disconnect")
        self.btn_disconnect.setObjectName("btnDanger")
        self.btn_disconnect.setEnabled(False)

        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(300)
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.device_combo.setPlaceholderText("Scan to list devices…")

        self.rate_combo = QComboBox()
        for r in sorted(RATE_CODES.keys(), key=lambda x: float(x)):
            self.rate_combo.addItem(f"{r} Hz", r)
        # 20–50 Hz is enough for tip mode; 50+ better for translate
        self.rate_combo.setCurrentText("20 Hz")

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("手臂混合（推荐）", "hybrid")
        self.mode_combo.addItem("姿态笔尖", "tip")
        self.mode_combo.addItem("位移推算", "translate")

        for w in (
            self.btn_scan,
            self.device_combo,
            QLabel("Rate"),
            self.rate_combo,
            QLabel("模式"),
            self.mode_combo,
            self.btn_connect,
            self.btn_disconnect,
        ):
            if isinstance(w, QLabel):
                w.setObjectName("fieldLabel")
            row1.addWidget(w)
        col.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setSpacing(10)
        self.btn_reset_path = QPushButton("重置轨迹")
        self.btn_reset_path.setObjectName("btnPrimary")
        self.btn_recalib = QPushButton("重新标定")
        self.btn_recalib.setObjectName("btnSecondary")
        self.btn_clear_imu = QPushButton("清空波形")
        self.btn_clear_imu.setObjectName("btnGhost")

        self.chk_flat = QCheckBox("平面投影（更易看出 8 字）")
        self.chk_flat.setChecked(True)
        self.chk_record = QCheckBox("记录轨迹")
        self.chk_record.setChecked(True)

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.5, 50.0)
        self.scale_spin.setSingleStep(0.5)
        self.scale_spin.setValue(4.0)
        self.scale_spin.setPrefix("幅度× ")
        self.scale_spin.setDecimals(1)

        for w in (
            self.btn_reset_path,
            self.btn_recalib,
            self.btn_clear_imu,
            self.chk_flat,
            self.chk_record,
            self.scale_spin,
        ):
            row2.addWidget(w)
        row2.addStretch()
        col.addLayout(row2)
        return bar

    def _build_metrics(self) -> QWidget:
        wrap = QWidget()
        grid = QGridLayout(wrap)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)

        self.card_acc = MetricCard("Acceleration", "unit: g")
        self.card_gyro = MetricCard("Angular velocity", "unit: °/s")
        self.card_angle = MetricCard("Attitude", "roll / pitch / yaw °")
        self.card_pos = MetricCard("Position", "推算坐标 m（相对）")
        self.card_speed = MetricCard("Speed", "移动速度（推算）· 角速度（实测）")
        self.card_speed.setObjectName("speedCard")
        self.card_meta = MetricCard("Session", "frames · battery")

        grid.addWidget(self.card_acc, 0, 0)
        grid.addWidget(self.card_gyro, 0, 1)
        grid.addWidget(self.card_angle, 0, 2)
        grid.addWidget(self.card_pos, 0, 3)
        grid.addWidget(self.card_speed, 0, 4)
        grid.addWidget(self.card_meta, 0, 5)
        for i in range(6):
            grid.setColumnStretch(i, 1)
        grid.setColumnStretch(4, 2)
        return wrap

    def _build_tabs(self) -> QWidget:
        self.tabs = QTabWidget()
        self.tabs.setObjectName("tabs")

        # --- Trajectory tab (primary) ---
        traj = QWidget()
        traj_layout = QHBoxLayout(traj)
        traj_layout.setContentsMargins(0, 8, 0, 0)
        traj_layout.setSpacing(10)

        left = QFrame()
        left.setObjectName("plotPanel")
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(10, 10, 10, 10)
        self.view3d = Trajectory3DView()
        left_l.addWidget(self.view3d)
        tip = QLabel(
            "用法：静置标定 →「重置轨迹」→ 用手在空中真正画出「8」字轨迹"
            "（混合模式会跟手的平移；幅度不够就调大「幅度×」）。"
        )
        tip.setObjectName("footerText")
        tip.setWordWrap(True)
        left_l.addWidget(tip)
        traj_layout.addWidget(left, stretch=3)

        right = QFrame()
        right.setObjectName("plotPanel")
        right_l = QVBoxLayout(right)
        right_l.setContentsMargins(10, 10, 10, 10)
        self.view_top = TopDownPathView()
        right_l.addWidget(self.view_top, stretch=1)
        self.plot_speed = SpeedPlot()
        right_l.addWidget(self.plot_speed)
        note = QLabel(
            "手臂混合=姿态+位移，更接近你实际画的形状。"
            "若仍像小圆：调大幅度×、重置后再画，动作稍大稍快；纯笔尖模式只看倾斜容易变成圆。"
        )
        note.setObjectName("footerText")
        note.setWordWrap(True)
        right_l.addWidget(note)
        traj_layout.addWidget(right, stretch=2)

        self.tabs.addTab(traj, "空间轨迹")

        # --- Raw IMU tab ---
        imu = QFrame()
        imu.setObjectName("plotPanel")
        imu_l = QVBoxLayout(imu)
        imu_l.setContentsMargins(10, 10, 10, 10)
        imu_l.setSpacing(8)
        pg.setConfigOptions(antialias=True)
        self.plot_acc = ImuPlot("Acceleration", "g")
        self.plot_gyro = ImuPlot("Gyroscope", "°/s")
        self.plot_angle = ImuPlot("Angle", "°")
        imu_l.addWidget(self.plot_acc)
        imu_l.addWidget(self.plot_gyro)
        imu_l.addWidget(self.plot_angle)
        self.tabs.addTab(imu, "原始 IMU")

        return self.tabs

    def _build_footer(self) -> QWidget:
        foot = QFrame()
        foot.setObjectName("footer")
        row = QHBoxLayout(foot)
        row.setContentsMargins(8, 4, 8, 4)
        self.footer_status = QLabel("Ready")
        self.footer_status.setObjectName("footerText")
        row.addWidget(self.footer_status)
        row.addStretch()
        hint = QLabel("macOS / Linux · bleak")
        hint.setObjectName("footerText")
        row.addWidget(hint)
        return foot

    def _wire(self) -> None:
        self.btn_scan.clicked.connect(self._on_scan)
        self.btn_connect.clicked.connect(self._on_connect)
        self.btn_disconnect.clicked.connect(self._on_disconnect)
        self.btn_clear_imu.clicked.connect(self._on_clear_imu)
        self.btn_reset_path.clicked.connect(self._on_reset_path)
        self.btn_recalib.clicked.connect(self._on_recalib)
        self.chk_flat.toggled.connect(self._on_flat_toggled)
        self.scale_spin.valueChanged.connect(self._on_scale)
        self.rate_combo.currentIndexChanged.connect(self._on_rate_changed)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self.worker.devices_found.connect(self._on_devices)
        self.worker.connected.connect(self._on_connected)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.sample.connect(self._on_sample)
        self.worker.battery.connect(self._on_battery)
        self.worker.status.connect(self._on_status)
        self.worker.error.connect(self._on_error)

    def _on_scan(self) -> None:
        self.btn_scan.setEnabled(False)
        self.dot.set_state("scanning")
        self.state_label.setText("Scanning")
        self.worker.scan(6.0)
        QTimer.singleShot(6500, lambda: self.btn_scan.setEnabled(not self._connected))

    def _on_connect(self) -> None:
        addr = self.device_combo.currentData()
        if not addr:
            text = self.device_combo.currentText().strip()
            if "·" in text:
                addr = text.split("·", 1)[1].strip().split()[0]
            else:
                addr = text
        if not addr:
            self._on_status("请先 Scan 并选择设备")
            return
        rate = self.rate_combo.currentData()
        self.btn_connect.setEnabled(False)
        self.btn_scan.setEnabled(False)
        self.tracker = TrajectoryTracker(
            mode=self.mode_combo.currentData() or "hybrid",
            integrate_z=not self.chk_flat.isChecked(),
            scale=self.scale_spin.value(),
        )
        self.view3d.clear()
        self.view_top.clear()
        self.plot_speed.clear_data()
        self.view3d.set_status("连接中…静置设备等待标定")
        self.worker.connect_device(addr, rate=rate)

    def _on_disconnect(self) -> None:
        self.worker.disconnect_device()

    def _on_clear_imu(self) -> None:
        self.plot_acc.clear_data()
        self.plot_gyro.clear_data()
        self.plot_angle.clear_data()
        self._frame_count = 0
        self._update_meta()

    def _on_reset_path(self) -> None:
        self.tracker.reset_path(keep_calibration=True)
        self.view3d.clear()
        self.view_top.clear()
        self.plot_speed.clear_data()
        self.view3d.set_status("轨迹已重置 — 开始画 8 字")
        self._on_status("轨迹已重置")

    def _on_recalib(self) -> None:
        self.tracker.reset_path(keep_calibration=False)
        self.view3d.clear()
        self.view_top.clear()
        self.plot_speed.clear_data()
        self.view3d.set_status("重新标定中…请静置约 1 秒")
        self._on_status("重新标定中，请保持静止")

    def _on_flat_toggled(self, checked: bool) -> None:
        self.tracker.integrate_z = not checked
        self._on_reset_path()

    def _on_mode_changed(self) -> None:
        mode = self.mode_combo.currentData() or "hybrid"
        self.tracker.set_mode(mode)
        self.view3d.clear()
        self.view_top.clear()
        self.plot_speed.clear_data()
        labels = {"hybrid": "手臂混合", "tip": "姿态笔尖", "translate": "位移推算"}
        label = labels.get(mode, mode)
        self.view3d.set_status(f"已切换到{label} — 请重置后重画")
        self._on_status(f"轨迹模式 → {label}")

    def _on_scale(self, value: float) -> None:
        self.tracker.set_scale(value)

    def _on_rate_changed(self) -> None:
        if not self._connected:
            return
        rate = self.rate_combo.currentData()
        if rate:
            self.worker.set_rate(rate)

    def _on_devices(self, rows: list) -> None:
        self._devices = rows
        self.device_combo.clear()
        for d in rows:
            rssi = d.get("rssi")
            rssi_s = f"  {rssi} dBm" if rssi is not None else ""
            label = f"{d['name']}  ·  {d['address']}{rssi_s}"
            self.device_combo.addItem(label, d["address"])
        self.btn_scan.setEnabled(not self._connected)
        if rows and not self._connected:
            self.btn_connect.setEnabled(True)

    def _on_connected(self, address: str) -> None:
        self._connected = True
        self.dot.set_state("connected")
        self.state_label.setText("Connected")
        self.btn_connect.setEnabled(False)
        self.btn_disconnect.setEnabled(True)
        self.btn_scan.setEnabled(False)
        self.device_combo.setEnabled(False)
        self._device_addr = address
        self._battery_pct: int | None = None
        self.tabs.setCurrentIndex(0)
        self._update_meta()

    def _on_disconnected(self) -> None:
        self._connected = False
        self.dot.set_state("idle")
        self.state_label.setText("Disconnected")
        self.btn_connect.setEnabled(True)
        self.btn_disconnect.setEnabled(False)
        self.btn_scan.setEnabled(True)
        self.device_combo.setEnabled(True)
        self.view3d.set_status("已断开")

    def _on_sample(self, sample: ImuSample) -> None:
        self._pending.append((time.monotonic(), sample))
        self._frame_count += 1

    def _on_battery(self, _raw: int, percent: int) -> None:
        self._battery_pct = percent
        self._update_meta()

    def _on_status(self, text: str) -> None:
        self.footer_status.setText(text)

    def _on_error(self, text: str) -> None:
        self.dot.set_state("error")
        self.footer_status.setText(f"Error: {text}")
        if not self._connected:
            self.btn_connect.setEnabled(True)
            self.btn_scan.setEnabled(True)

    def _flush_plots(self) -> None:
        if not self._pending:
            return
        batch = list(self._pending)
        self._pending.clear()

        state = None
        recording = self.chk_record.isChecked()
        for now, s in batch:
            self.plot_acc.push(now, *s.accel_g)
            self.plot_gyro.push(now, *s.gyro_dps)
            self.plot_angle.push(now, *s.angle_deg)
            if recording:
                state = self.tracker.update(now, s) or state
                if self.tracker.calibrated:
                    self.plot_speed.push(now, self.tracker.speed_mps * 100.0)

        now, sample = batch[-1]
        ax, ay, az = sample.accel_g
        wx, wy, wz = sample.gyro_dps
        roll, pitch, yaw = sample.angle_deg

        if self.tabs.currentIndex() == 1:
            self.plot_acc.redraw()
            self.plot_gyro.redraw()
            self.plot_angle.redraw()

        self.card_acc.set_xyz(ax, ay, az, "+.3f")
        self.card_gyro.set_xyz(wx, wy, wz, "+.2f")
        self.card_angle.set_xyz(roll, pitch, yaw, "+.2f")
        self._update_speed_card()

        if state is not None:
            px, py, pz = state.position_m
            self.card_pos.set_xyz(px, py, pz, "+.3f")
            tags = {"hybrid": "混合", "tip": "笔尖", "translate": "位移"}
            mode_tag = tags.get(self.tracker.mode, self.tracker.mode)
            if not self.tracker.calibrated:
                self.view3d.set_status("标定中…请保持静止")
            elif state.stationary and self.tracker._still_count >= self.tracker.zupt_hold:
                self.view3d.set_status(
                    f"[{mode_tag}] 静止 · 幅度 {self.tracker.path_extent_m * 100:.0f} cm · "
                    f"{len(self.tracker.path)} 点"
                )
            else:
                self.view3d.set_status(
                    f"[{mode_tag}] {self.tracker.speed_mps * 100:.1f} cm/s · "
                    f"幅度 {self.tracker.path_extent_m * 100:.0f} cm · {len(self.tracker.path)} 点"
                )
            path = self.tracker.path_array
            speeds = self.tracker.speeds_array
            R = rotation_body_to_world(roll, pitch, yaw)
            self.view3d.set_path(path, tip_axes=R, speeds=speeds)
            self.view_top.set_path(path, speeds=speeds)
            self.plot_speed.redraw()

        self._update_meta()

    def _update_speed_card(self) -> None:
        tr = self.tracker
        v = tr.speed_mps * 100.0
        peak = tr.peak_speed_mps * 100.0
        self.card_speed.set_html(
            f'<span style="color:{WARN}; font-size:20px">{v:5.1f}</span> cm/s'
            f'  <span style="color:{MUTED}">峰值 {peak:.1f}</span><br>'
            f'<span style="color:{ACCENT}">ω {tr.angular_speed_dps:6.1f} °/s</span>'
        )

    def _update_meta(self) -> None:
        batt = f"{self._battery_pct}%" if getattr(self, "_battery_pct", None) is not None else "—"
        cal = "已标定" if self.tracker.calibrated else "标定中"
        self.card_meta.set_html(
            f"{self._frame_count} frames<br>"
            f'<span style="color:{ACCENT}">BAT {batt}</span> · {cal}'
        )

    def closeEvent(self, event) -> None:  # noqa: N802
        self._plot_timer.stop()
        self.worker.shutdown()
        super().closeEvent(event)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"""
            QMainWindow, QWidget {{
                background: {BG};
                color: {TEXT};
                font-family: "Helvetica Neue", "PingFang SC", "Noto Sans CJK SC", sans-serif;
                font-size: 13px;
            }}
            #header, #toolbar, #plotPanel, #footer, #metricCard, #speedCard {{
                background: {PANEL};
                border: 1px solid {BORDER};
                border-radius: 12px;
            }}
            #tabs::pane {{
                border: none;
                background: transparent;
                top: 8px;
            }}
            QTabBar::tab {{
                background: {PANEL_ALT};
                color: {MUTED};
                padding: 8px 18px;
                margin-right: 4px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border: 1px solid {BORDER};
            }}
            QTabBar::tab:selected {{
                background: {PANEL};
                color: {TEXT};
                border-bottom-color: {PANEL};
            }}
            #brand {{
                font-size: 22px;
                font-weight: 700;
                letter-spacing: 1px;
                color: {TEXT};
            }}
            #subtitle {{ color: {MUTED}; font-size: 12px; }}
            #stateLabel {{ font-weight: 600; color: {TEXT}; }}
            #metricTitle {{
                color: {MUTED};
                font-size: 11px;
                letter-spacing: 0.6px;
            }}
            #metricValues {{
                font-size: 13px;
                font-weight: 600;
                font-family: Menlo, Monaco, Consolas, monospace;
            }}
            #metricUnit, #fieldLabel, #footerText {{ color: {MUTED}; font-size: 11px; }}
            QComboBox, QDoubleSpinBox {{
                background: {PANEL_ALT};
                border: 1px solid {BORDER};
                border-radius: 8px;
                padding: 7px 10px;
                min-height: 20px;
            }}
            QComboBox::drop-down {{ border: none; width: 24px; }}
            QComboBox QAbstractItemView {{
                background: {PANEL};
                border: 1px solid {BORDER};
                selection-background-color: {ACCENT_DIM};
            }}
            QCheckBox {{ color: {TEXT}; spacing: 6px; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border-radius: 4px;
                border: 1px solid {BORDER};
                background: {PANEL_ALT};
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT};
                border-color: {ACCENT};
            }}
            QPushButton {{
                border: none;
                border-radius: 8px;
                padding: 9px 16px;
                font-weight: 600;
            }}
            #btnPrimary {{ background: {ACCENT}; color: #042f2e; }}
            #btnPrimary:hover {{ background: #5eead4; }}
            #btnPrimary:disabled {{ background: #2a4a48; color: #6b8f8c; }}
            #btnSecondary {{
                background: {PANEL_ALT};
                border: 1px solid {BORDER};
                color: {TEXT};
            }}
            #btnSecondary:hover {{ border-color: {ACCENT}; }}
            #btnDanger {{
                background: #3a2226;
                color: {DANGER};
                border: 1px solid #5a3036;
            }}
            #btnDanger:hover {{ background: #4a2a30; }}
            #btnDanger:disabled {{ color: #6a4548; border-color: #3a2a2c; }}
            #btnGhost {{
                background: transparent;
                border: 1px solid {BORDER};
                color: {MUTED};
            }}
            #btnGhost:hover {{ color: {TEXT}; border-color: {MUTED}; }}
            """
        )


def run_gui() -> None:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Wit BLE5")
    font = QFont()
    font.setPointSize(13)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


def main() -> None:
    run_gui()


if __name__ == "__main__":
    main()
