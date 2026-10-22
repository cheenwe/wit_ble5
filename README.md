# wit-ble5

[![CI](https://github.com/OWNER/wit_ble5/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/wit_ble5/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Cross-platform (**macOS / Linux**) client for [WitMotion](https://www.wit-motion.com/) BLE 5.0 IMU sensors — realtime accel / gyro / Euler angles, CLI streaming, and a Qt GUI with 3D trajectory.

Compatible modules (same BLE 5.0 GATT / frame format): `WT9011DCL-BT50`, `WT901BLE*`, `BWT901BLE5.0`, …

> Unofficial community project — not affiliated with WitMotion.

---

跨平台维特智能 BLE 5.0 姿态传感器客户端：实时连接、CLI、图形界面（3D / 俯视轨迹、速度显示）。

## Features

- BLE scan / connect / disconnect via [bleak](https://github.com/hbldh/bleak) (CoreBluetooth / BlueZ)
- CLI: `scan`, `connect`, `gui`
- GUI: IMU plots, hybrid / tip / translate trajectory modes, speed coloring
- Unit-tested protocol + tracker (no hardware required for CI)

## Requirements

- Python **3.10+**
- Bluetooth enabled
- Linux: BlueZ (`sudo apt install bluez bluetooth`)
- macOS: allow Bluetooth permission; **do not** rely on System Settings pairing — this app uses GATT directly

## Install

```bash
git clone https://github.com/OWNER/wit_ble5.git
cd wit_ble5
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"   # or: pip install -e .
```

## Quick start

```bash
# GUI (recommended)
wit-ble5 gui

# CLI
wit-ble5 scan
wit-ble5 connect              # auto-pick first WitMotion device
wit-ble5 connect <ADDRESS> --rate 20 --battery
```

GUI tip: Scan → Connect → hold still ~1s → **Reset path** → draw in the air. Prefer **手臂混合 (hybrid)** mode; raise **幅度×** if the stroke looks too small. Pure IMU drifts — reset between gestures.

## Library usage

```python
import asyncio
from wit_ble5 import WitBleClient
from wit_ble5.client import scan_devices
from wit_ble5.protocol import ImuSample

async def main():
    devices = await scan_devices(timeout=6)
    if not devices:
        raise SystemExit("no device")
    addr = devices[0][0].address

    def on_sample(sample, _raw):
        if isinstance(sample, ImuSample):
            print(sample.format_line())

    async with WitBleClient(addr, on_sample=on_sample) as client:
        await client.set_rate("10")
        await asyncio.sleep(30)

asyncio.run(main())
```

## Protocol

| Item | Value |
|------|--------|
| Service | `0000ffe5-0000-1000-8000-00805f9a34fb` |
| Notify | `0000ffe4-0000-1000-8000-00805f9a34fb` |
| Write | `0000ffe9-0000-1000-8000-00805f9a34fb` |
| Default frame | `55 61` + 18 bytes (accel / gyro / angle) |

Official protocol reference: [WitMotion BLE 5.0 docs](https://wit-motion.gitbook.io/witmotion-sdk/ble-5.0-protocol)

## Development / CI

```bash
make install-dev
make ci          # ruff + pytest
make build       # sdist + wheel
```

GitHub Actions runs the same checks on Ubuntu & macOS (Python 3.10–3.13).  
Tag `vX.Y.Z` to cut a GitHub Release (see [docs/publishing.md](docs/publishing.md)).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).  
Security reports: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE)
