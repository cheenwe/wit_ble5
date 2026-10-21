import math

import numpy as np

from wit_ble5.gui.tracker import TrajectoryTracker, rotation_body_to_world
from wit_ble5.protocol import ImuSample


def test_identity_rotation_level():
    R = rotation_body_to_world(0, 0, 0)
    assert np.allclose(R, np.eye(3), atol=1e-9)


def test_yaw_90():
    R = rotation_body_to_world(0, 0, 90)
    v = R @ np.array([1.0, 0.0, 0.0])
    assert abs(v[1] - 1.0) < 1e-6


def _calib(tr: TrajectoryTracker, dt: float = 0.05) -> float:
    still = ImuSample(accel_g=(0.0, 0.0, 1.0), gyro_dps=(0.0, 0.0, 0.0), angle_deg=(0.0, 0.0, 0.0))
    t = 0.0
    for _ in range(25):
        t += dt
        tr.update(t, still)
    assert tr.calibrated
    return t


def test_tip_mode_figure8_at_20hz():
    tr = TrajectoryTracker(mode="tip", calib_seconds=0.3, integrate_z=False, scale=1.0)
    t = _calib(tr, dt=0.05)
    tr.reset_path(keep_calibration=True)

    for i in range(100):
        t += 0.05
        u = 2 * math.pi * i / 50
        roll = 35 * math.sin(u)
        pitch = 35 * math.sin(u) * math.cos(u)
        tr.update(
            t,
            ImuSample(
                accel_g=(0.0, 0.0, 1.0),
                gyro_dps=(20.0, 20.0, 0.0),
                angle_deg=(roll, pitch, 0.0),
            ),
        )

    path = tr.path_array
    assert len(path) > 50
    assert float(np.ptp(path[:, 0])) > 0.08
    assert float(np.ptp(path[:, 1])) > 0.05


def test_hybrid_responds_to_translation():
    """Hybrid must move when the sensor translates with little orientation change."""
    tr = TrajectoryTracker(
        mode="hybrid",
        calib_seconds=0.3,
        integrate_z=False,
        scale=1.0,
        tip_weight=0.5,
        translate_weight=4.0,
        noise_gate_mps2=0.1,
    )
    t = _calib(tr, dt=0.05)
    tr.reset_path(keep_calibration=True)

    # Lateral accel pulses forming a rough figure-8 in XY while nearly upright
    for i in range(120):
        t += 0.05
        u = 2 * math.pi * i / 60
        ax = 0.6 * math.sin(u)
        ay = 0.6 * math.sin(u) * math.cos(u)
        tr.update(
            t,
            ImuSample(
                accel_g=(ax, ay, 1.0),
                gyro_dps=(5.0, 5.0, 5.0),
                angle_deg=(2.0, -1.0, 0.0),
            ),
        )

    path = tr.path_array
    assert len(path) > 50
    assert tr.path_extent_m > 0.05
    assert float(np.ptp(path[:, 0])) > 0.03
    assert float(np.ptp(path[:, 1])) > 0.02


def test_translate_mode_moves_on_accel():
    tr = TrajectoryTracker(mode="translate", calib_seconds=0.3, integrate_z=False, noise_gate_mps2=0.1, scale=1.0)
    t = _calib(tr, dt=0.05)
    tr.reset_path(keep_calibration=True)

    moving = ImuSample(accel_g=(0.8, 0.0, 1.0), gyro_dps=(0.0, 0.0, 40.0), angle_deg=(0.0, 0.0, 0.0))
    for _ in range(30):
        t += 0.05
        tr.update(t, moving)

    path = tr.path_array
    assert len(path) > 5
    assert abs(path[-1, 0]) > 1e-3
    tr.reset_path()
    assert tr.speed_mps == 0 and len(tr.speeds) == 0
