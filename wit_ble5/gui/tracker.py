"""IMU trajectory for air-drawn gestures (figure-8 etc.).

Modes:
  - hybrid:    attitude tip + high-pass translation (default, matches hand drawing)
  - tip:       virtual pen from attitude only
  - translate: accel double-integration only

Why tip-only often looks like a small circle:
  waving the arm mainly *translates* the sensor; orientation may just orbit,
  so a short virtual tip traces a circle and ignores the real 8-shaped path.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass

import numpy as np

from wit_ble5.protocol import ImuSample

G = 9.80665
MAX_PATH = 8000
TIP_LENGTH = 0.70  # ~forearm — larger stroke than 0.35
MODES = ("hybrid", "tip", "translate")


def rotation_body_to_world(roll_deg: float, pitch_deg: float, yaw_deg: float) -> np.ndarray:
    """WitMotion Z-Y-X (yaw-pitch-roll) body → world (Z up)."""
    r, p, y = np.radians([roll_deg, pitch_deg, yaw_deg])
    cr, sr = math.cos(r), math.sin(r)
    cp, sp = math.cos(p), math.sin(p)
    cy, sy = math.cos(y), math.sin(y)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return rz @ ry @ rx


@dataclass
class TrackerState:
    position_m: np.ndarray
    velocity_mps: np.ndarray
    linear_acc: np.ndarray
    stationary: bool
    mode: str


class TrajectoryTracker:
    def __init__(
        self,
        *,
        mode: str = "hybrid",
        calib_seconds: float = 1.0,
        integrate_z: bool = False,
        scale: float = 4.0,
        tip_length: float = TIP_LENGTH,
        tip_weight: float = 1.2,
        translate_weight: float = 3.5,
        # translate tuning — favour short air gestures @ 20 Hz
        accel_lpf: float = 0.90,
        vel_damping: float = 0.25,
        noise_gate_mps2: float = 0.18,
        pos_hp_tau: float = 2.2,  # seconds; keeps ~2–4s figure-8, kills slow drift
        zupt_acc_g: float = 0.12,
        zupt_gyro_dps: float = 18.0,
        zupt_hold: int = 12,
    ) -> None:
        self.mode = mode if mode in MODES else "hybrid"
        self.calib_seconds = calib_seconds
        self.integrate_z = integrate_z
        self.scale = scale
        self.tip_length = tip_length
        self.tip_weight = tip_weight
        self.translate_weight = translate_weight
        self.accel_lpf = accel_lpf
        self.vel_damping = vel_damping
        self.noise_gate_mps2 = noise_gate_mps2
        self.pos_hp_tau = pos_hp_tau
        self.zupt_acc_g = zupt_acc_g
        self.zupt_gyro_dps = zupt_gyro_dps
        self.zupt_hold = zupt_hold

        self.path: deque[np.ndarray] = deque(maxlen=MAX_PATH)
        self.speeds: deque[float] = deque(maxlen=MAX_PATH)
        self.speed_mps = 0.0
        self.peak_speed_mps = 0.0
        self.angular_speed_dps = 0.0

        self.pos = np.zeros(3, dtype=np.float64)
        self.vel = np.zeros(3, dtype=np.float64)
        self._tip_pos = np.zeros(3, dtype=np.float64)
        self._trans_raw = np.zeros(3, dtype=np.float64)
        self._trans_lp = np.zeros(3, dtype=np.float64)
        self._trans_hp = np.zeros(3, dtype=np.float64)
        self._trans_vel = np.zeros(3, dtype=np.float64)
        self._a_lp = np.zeros(3, dtype=np.float64)
        self._tip0: np.ndarray | None = None
        self._R0: np.ndarray | None = None

        self._calib: list[np.ndarray] = []
        self._t0: float | None = None
        self._last_t: float | None = None
        self._calibrated = False
        self._still_count = 0
        self.last_linear_acc = np.zeros(3, dtype=np.float64)
        self.last_stationary = False
        self.path_extent_m = 0.0

    @property
    def calibrated(self) -> bool:
        return self._calibrated

    @property
    def path_array(self) -> np.ndarray:
        if not self.path:
            return np.zeros((0, 3), dtype=np.float64)
        return np.asarray(self.path, dtype=np.float64)

    @property
    def speeds_array(self) -> np.ndarray:
        return np.asarray(self.speeds, dtype=np.float64)

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(mode)
        self.mode = mode
        self.reset_path(keep_calibration=True)

    def set_scale(self, scale: float) -> None:
        self.scale = max(0.1, float(scale))

    def reset_path(self, keep_calibration: bool = True) -> None:
        self.path.clear()
        self.speeds.clear()
        self.speed_mps = 0.0
        self.peak_speed_mps = 0.0
        self.pos[:] = 0
        self.vel[:] = 0
        self._tip_pos[:] = 0
        self._trans_raw[:] = 0
        self._trans_lp[:] = 0
        self._trans_hp[:] = 0
        self._trans_vel[:] = 0
        self._a_lp[:] = 0
        self._tip0 = None
        self._last_t = None
        self._still_count = 0
        self.path_extent_m = 0.0
        if not keep_calibration:
            self._calibrated = False
            self._calib.clear()
            self._t0 = None
            self._R0 = None

    def update(self, t: float, sample: ImuSample) -> TrackerState:
        roll, pitch, yaw = sample.angle_deg
        R = rotation_body_to_world(roll, pitch, yaw)
        a_body = np.asarray(sample.accel_g, dtype=np.float64)
        a_world = R @ a_body
        a_lin = (a_world - np.array([0.0, 0.0, 1.0])) * G
        self.last_linear_acc = a_lin

        gyro = np.asarray(sample.gyro_dps, dtype=np.float64)
        self.angular_speed_dps = float(np.linalg.norm(gyro))
        stationary = (
            abs(float(np.linalg.norm(a_body)) - 1.0) < self.zupt_acc_g
            and float(np.linalg.norm(gyro)) < self.zupt_gyro_dps
        )
        self.last_stationary = stationary
        self._still_count = self._still_count + 1 if stationary else 0

        if self._t0 is None:
            self._t0 = t

        if not self._calibrated:
            self._calib.append(a_lin.copy())
            if (t - self._t0) >= self.calib_seconds and len(self._calib) >= 6:
                self._a_lp = np.mean(np.stack(self._calib), axis=0)
                self._R0 = R.copy()
                self._calibrated = True
                self._last_t = t
                self._tip0 = np.array([0.0, 0.0, self.tip_length])
                self.pos[:] = 0.0
                self._append_point(0.0)
            return TrackerState(self.pos.copy(), self.vel.copy(), a_lin, stationary, self.mode)

        if self._last_t is None:
            self._last_t = t
            return TrackerState(self.pos.copy(), self.vel.copy(), a_lin, stationary, self.mode)

        dt = t - self._last_t
        self._last_t = t
        if dt <= 1e-4 or dt > 0.35:
            return TrackerState(self.pos.copy(), self.vel.copy(), a_lin, stationary, self.mode)

        tip = self._compute_tip(R)
        trans, trans_vel = self._compute_translate(a_lin, dt)

        if self.mode == "tip":
            new_pos = tip
            self.vel = (tip - self._tip_pos) / dt if dt > 0 else self.vel
        elif self.mode == "translate":
            new_pos = trans
            self.vel = trans_vel
        else:  # hybrid — translation dominates, tip adds orientation stroke
            new_pos = self.tip_weight * tip + self.translate_weight * trans
            self.vel = trans_vel + (tip - self._tip_pos) / dt if dt > 0 else trans_vel

        self._tip_pos = tip
        if not self.integrate_z:
            new_pos = np.array([new_pos[0], new_pos[1], 0.0])

        self.pos = new_pos
        speed = float(np.linalg.norm(self.vel))
        self.speed_mps = speed
        self.peak_speed_mps = max(self.peak_speed_mps, speed)
        self._append_point(speed)
        self._refresh_extent()
        return TrackerState(self.pos.copy(), self.vel.copy(), a_lin, stationary, self.mode)

    def _compute_tip(self, R: np.ndarray) -> np.ndarray:
        if self._R0 is None:
            self._R0 = R.copy()
        R_rel = R @ self._R0.T
        tip_local = np.array([0.0, 0.0, self.tip_length])
        tip = R_rel @ tip_local
        if self._tip0 is None:
            self._tip0 = tip_local.copy()
        return tip - self._tip0

    def _compute_translate(self, a_lin: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray]:
        self._a_lp = self.accel_lpf * self._a_lp + (1.0 - self.accel_lpf) * a_lin
        a_dyn = a_lin - self._a_lp
        if not self.integrate_z:
            a_dyn = a_dyn.copy()
            a_dyn[2] = 0.0

        if float(np.linalg.norm(a_dyn)) < self.noise_gate_mps2:
            a_dyn = np.zeros(3)

        vel = self._trans_vel + a_dyn * dt
        vel *= math.exp(-self.vel_damping * dt)

        if self._still_count >= self.zupt_hold:
            vel *= 0.4
            if float(np.linalg.norm(vel)) < 0.04:
                vel[:] = 0.0

        speed = float(np.linalg.norm(vel))
        if speed > 5.0:
            vel *= 5.0 / speed

        self._trans_vel = vel
        self._trans_raw = self._trans_raw + vel * dt

        # High-pass position: remove slow drift, keep gesture (figure-8 over ~2–4s)
        alpha = math.exp(-dt / max(self.pos_hp_tau, 0.2))
        self._trans_lp = alpha * self._trans_lp + (1.0 - alpha) * self._trans_raw
        self._trans_hp = self._trans_raw - self._trans_lp
        return self._trans_hp.copy(), vel.copy()

    def _append_point(self, speed: float) -> None:
        self.path.append((self.pos * self.scale).copy())
        self.speeds.append(speed)

    def _refresh_extent(self) -> None:
        if len(self.path) < 2:
            self.path_extent_m = 0.0
            return
        arr = np.asarray(self.path)
        self.path_extent_m = float(np.max(np.linalg.norm(arr - arr.mean(axis=0), axis=1)))
