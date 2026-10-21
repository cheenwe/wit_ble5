# wit_ble5

跨平台（**macOS / Linux**）维特智能 BLE 5.0 姿态传感器客户端，支持实时连接并读取加速度 / 角速度 / 欧拉角。

适配型号示例：`WT9011DCL-BT50`、`WT901BLE*`、`BWT901BLE5.0` 等使用同一套 BLE 5.0 协议的模块。

## 依赖

- Python **3.10+**
- 系统蓝牙已开启
- [bleak](https://github.com/hbldh/bleak)（底层：macOS CoreBluetooth / Linux BlueZ）

### Linux 额外要求

```bash
# Debian/Ubuntu
sudo apt install bluez bluetooth
# 当前用户需能访问蓝牙（或用 sudo 跑一次验证）
```

### macOS 注意

- **不要**指望在「系统设置 → 蓝牙」里配对成功；本程序通过 BLE GATT 直连。
- 首次运行若系统弹权限，请允许「蓝牙」。
- 官方 Windows 上位机在此不适用。

## 安装

```bash
cd wit_ble5
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## 图形界面（推荐）

实时连接 / 断开，**3D + 俯视空间轨迹**（空中画 8 字看轮廓），并附带原始 IMU 波形：

```bash
wit-ble5 gui
# 或
wit-ble5-gui
```

流程：Scan → Connect → **静置约 1 秒标定** → **重置轨迹** → 在空中慢速画「8」→ 看「空间轨迹」页的 3D / 俯视图。  
可拖拽旋转 3D；「平面模式」打开时更易看出 8 字。纯 IMU 会漂移，画完一个就看，变形了再重置。

## 使用

### 1. 扫描设备

长按传感器开机（蓝灯快闪），然后：

```bash
wit-ble5 scan
# 或
python -m wit_ble5 scan
```

设备名通常类似 `WT901BLExxxx`。记下 ADDRESS（macOS 上多为 UUID 形式）。

### 2. 实时连接读数

```bash
# 自动选第一台维特设备
wit-ble5 connect

# 指定地址
wit-ble5 connect <ADDRESS>

# 设回传频率 20Hz，并读一次电量
wit-ble5 connect <ADDRESS> --rate 20 --battery

# JSON Lines（方便管道/落盘）
wit-ble5 connect <ADDRESS> --json --duration 10
```

成功后传感器蓝灯变为慢闪，终端持续输出类似：

```text
[     1     0.12s] acc(g)=[+0.012,-0.003,+0.998]  gyro(°/s)=[  +0.12,  -0.05,  +0.01]  angle(°)=[ +0.15, -1.20,+12.30]
```

`Ctrl+C` 结束。

## 作为库调用

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

## 协议要点

| 项目 | 值 |
|------|-----|
| Service | `0000ffe5-0000-1000-8000-00805f9a34fb` |
| Notify | `0000ffe4-0000-1000-8000-00805f9a34fb` |
| Write | `0000ffe9-0000-1000-8000-00805f9a34fb` |
| 默认帧 | `55 61` + 18 字节（加计 / 陀螺 / 角度） |

官方协议：https://wit-motion.gitbook.io/witmotion-sdk/ble-5.0-protocol

## 测试（无需硬件）

```bash
pip install -e ".[dev]"
pytest
```

## 排障

| 现象 | 处理 |
|------|------|
| `scan` 为空 | 确认已开机快闪；靠近电脑；关掉手机 App 占用；Linux 检查 `bluetoothctl power on` |
| 连接超时 | 换近一点再试；重启传感器；macOS 系统设置里删掉残留蓝牙条目 |
| Linux 权限错误 | 把用户加入 `bluetooth`/`lp` 组，或检查 BlueZ 服务 |
| 有连接无数据 | 确认型号是 BLE5.0 系列；用 `--rate 10` 强制设频率 |

## 许可

MIT
