"""WitMotion BLE 5.0 packet parsing.

Default stream frame (20 bytes):
  0x55 0x61 | ax ay az | wx wy wz | roll pitch yaw
Each axis is signed int16 little-endian.

Scale factors from official BLE 5.0 protocol:
  accel: raw / 32768 * 16  (g)
  gyro:  raw / 32768 * 2000 (°/s)
  angle: raw / 32768 * 180 (°)
"""

from __future__ import annotations

import struct
from dataclasses import asdict, dataclass
from typing import Any

HEADER = 0x55
FLAG_IMU = 0x61
FLAG_REG = 0x71

PACKET_LEN = 20

# GATT UUIDs used by WitMotion BLE 5.0 modules
SERVICE_UUID = "0000ffe5-0000-1000-8000-00805f9a34fb"
NOTIFY_UUID = "0000ffe4-0000-1000-8000-00805f9a34fb"
WRITE_UUID = "0000ffe9-0000-1000-8000-00805f9a34fb"

# Return rate register values (FF AA 03 RATE 00)
RATE_CODES: dict[str, int] = {
    "0.1": 0x01,
    "0.5": 0x02,
    "1": 0x03,
    "2": 0x04,
    "5": 0x05,
    "10": 0x06,
    "20": 0x07,
    "50": 0x08,
    "100": 0x09,
    "200": 0x0A,
}

DEVICE_NAME_PREFIXES = (
    "WT901",
    "WT9011",
    "WT901BLE",
    "BWT901",
    "WitMotion",
)


@dataclass(slots=True)
class ImuSample:
    """One IMU sample from a 0x61 frame."""

    accel_g: tuple[float, float, float]
    gyro_dps: tuple[float, float, float]
    angle_deg: tuple[float, float, float]  # roll, pitch, yaw

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["accel_g"] = list(self.accel_g)
        d["gyro_dps"] = list(self.gyro_dps)
        d["angle_deg"] = list(self.angle_deg)
        return d

    def format_line(self) -> str:
        ax, ay, az = self.accel_g
        wx, wy, wz = self.gyro_dps
        roll, pitch, yaw = self.angle_deg
        return (
            f"acc(g)=[{ax:+7.3f},{ay:+7.3f},{az:+7.3f}]  "
            f"gyro(°/s)=[{wx:+8.2f},{wy:+8.2f},{wz:+8.2f}]  "
            f"angle(°)=[{roll:+7.2f},{pitch:+7.2f},{yaw:+7.2f}]"
        )


@dataclass(slots=True)
class RegisterPacket:
    """One 0x71 register read response."""

    start_reg: int
    values: tuple[int, ...]  # up to 8 signed int16

    def to_dict(self) -> dict[str, Any]:
        return {"start_reg": self.start_reg, "values": list(self.values)}


def _i16(lo: int, hi: int) -> int:
    return struct.unpack("<h", bytes((lo, hi)))[0]


def _scale_triplet(raw: bytes, scale: float) -> tuple[float, float, float]:
    x = _i16(raw[0], raw[1]) / 32768.0 * scale
    y = _i16(raw[2], raw[3]) / 32768.0 * scale
    z = _i16(raw[4], raw[5]) / 32768.0 * scale
    return (x, y, z)


def parse_packet(data: bytes | bytearray) -> ImuSample | RegisterPacket | None:
    """Parse one BLE notify payload. Returns None if unrecognized/short."""
    if len(data) < 2 or data[0] != HEADER:
        return None

    flag = data[1]
    if flag == FLAG_IMU and len(data) >= PACKET_LEN:
        body = bytes(data[2:20])
        return ImuSample(
            accel_g=_scale_triplet(body[0:6], 16.0),
            gyro_dps=_scale_triplet(body[6:12], 2000.0),
            angle_deg=_scale_triplet(body[12:18], 180.0),
        )

    if flag == FLAG_REG and len(data) >= 4:
        start = data[2] | (data[3] << 8)
        values: list[int] = []
        for i in range(4, min(len(data), 20), 2):
            if i + 1 >= len(data):
                break
            values.append(_i16(data[i], data[i + 1]))
        return RegisterPacket(start_reg=start, values=tuple(values))

    return None


def cmd_set_rate(rate_hz: str) -> bytes:
    """Build FF AA 03 RATE 00 for a known rate label."""
    key = rate_hz.strip().lower().replace("hz", "")
    if key not in RATE_CODES:
        raise ValueError(
            f"unsupported rate {rate_hz!r}; choose one of: {', '.join(RATE_CODES)}"
        )
    return bytes((0xFF, 0xAA, 0x03, RATE_CODES[key], 0x00))


def cmd_read_register(reg: int) -> bytes:
    """Build FF AA 27 XX 00."""
    return bytes((0xFF, 0xAA, 0x27, reg & 0xFF, 0x00))


def cmd_save(restore_default: bool = False) -> bytes:
    return bytes((0xFF, 0xAA, 0x00, 0x01 if restore_default else 0x00, 0x00))


def looks_like_wit_device(name: str | None) -> bool:
    if not name:
        return False
    upper = name.upper()
    return any(upper.startswith(p.upper()) for p in DEVICE_NAME_PREFIXES)
