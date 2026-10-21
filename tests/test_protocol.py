"""Unit tests for WitMotion BLE packet parsing (no hardware required)."""

from wit_ble5.protocol import (
    ImuSample,
    RegisterPacket,
    cmd_set_rate,
    parse_packet,
)


def _i16_le(value: int) -> tuple[int, int]:
    value &= 0xFFFF
    return value & 0xFF, (value >> 8) & 0xFF


def test_parse_imu_zero():
    pkt = bytes([0x55, 0x61] + [0] * 18)
    sample = parse_packet(pkt)
    assert isinstance(sample, ImuSample)
    assert sample.accel_g == (0.0, 0.0, 0.0)
    assert sample.gyro_dps == (0.0, 0.0, 0.0)
    assert sample.angle_deg == (0.0, 0.0, 0.0)


def test_parse_imu_scales():
    # accel X = 16384 -> 8g ; gyro Y = 16384 -> 1000 dps ; angle Z = 16384 -> 90 deg
    body = bytearray(18)
    ax_l, ax_h = _i16_le(16384)
    body[0], body[1] = ax_l, ax_h
    wy_l, wy_h = _i16_le(16384)
    body[8], body[9] = wy_l, wy_h
    yaw_l, yaw_h = _i16_le(16384)
    body[16], body[17] = yaw_l, yaw_h
    sample = parse_packet(bytes([0x55, 0x61]) + bytes(body))
    assert isinstance(sample, ImuSample)
    assert abs(sample.accel_g[0] - 8.0) < 1e-6
    assert abs(sample.gyro_dps[1] - 1000.0) < 1e-6
    assert abs(sample.angle_deg[2] - 90.0) < 1e-6


def test_parse_register_magnetic():
    # Example from protocol docs (approx)
    pkt = bytes.fromhex("55713a00680169007a0000000000000000000000")
    reg = parse_packet(pkt)
    assert isinstance(reg, RegisterPacket)
    assert reg.start_reg == 0x3A
    assert reg.values[0] == 0x0168  # 360
    assert reg.values[1] == 0x0069  # 105
    assert reg.values[2] == 0x007A  # 122


def test_cmd_set_rate():
    assert cmd_set_rate("10") == bytes([0xFF, 0xAA, 0x03, 0x06, 0x00])
    assert cmd_set_rate("50Hz") == bytes([0xFF, 0xAA, 0x03, 0x08, 0x00])


def test_unknown_packet():
    assert parse_packet(b"\x00\x00") is None
    assert parse_packet(b"\x55\x61\x00") is None
