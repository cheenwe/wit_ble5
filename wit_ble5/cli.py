"""CLI: scan / connect / stream WitMotion BLE 5.0 sensors."""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
import time
from typing import Any

from . import __version__
from .client import WitBleClient, scan_devices
from .protocol import ImuSample, RegisterPacket, RATE_CODES


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wit-ble5",
        description="Connect to WitMotion BLE 5.0 IMU (WT9011DCL-BT50 / WT901BLE) on macOS & Linux",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("gui", help="Launch realtime IMU dashboard (connect / disconnect / plots)")

    scan = sub.add_parser("scan", help="Scan nearby WitMotion BLE devices")
    scan.add_argument("--timeout", type=float, default=8.0, help="Scan seconds (default 8)")
    scan.add_argument(
        "--all",
        action="store_true",
        help="Show all BLE devices, not only WitMotion-looking names",
    )
    scan.add_argument("--json", action="store_true", help="JSON output")

    conn = sub.add_parser("connect", help="Connect and print realtime IMU data")
    conn.add_argument(
        "address",
        nargs="?",
        default=None,
        help="BLE address / UUID (omit to auto-pick first WitMotion device)",
    )
    conn.add_argument("--timeout", type=float, default=20.0, help="Connect timeout")
    conn.add_argument("--scan-timeout", type=float, default=8.0, help="Scan timeout when auto-picking")
    conn.add_argument(
        "--rate",
        default=None,
        choices=sorted(RATE_CODES.keys(), key=lambda x: float(x)),
        help="Set return rate in Hz after connect",
    )
    conn.add_argument("--json", action="store_true", help="One JSON object per line")
    conn.add_argument(
        "--duration",
        type=float,
        default=0,
        help="Stop after N seconds (0 = run until Ctrl+C)",
    )
    conn.add_argument(
        "--battery",
        action="store_true",
        help="Also request battery register once after connect",
    )
    return p


async def _cmd_scan(args: argparse.Namespace) -> int:
    print(f"Scanning {args.timeout:.0f}s ...", file=sys.stderr)
    devices = await scan_devices(timeout=args.timeout, wit_only=not args.all)
    if args.json:
        rows = [
            {
                "address": d.address,
                "name": d.name or adv.local_name,
                "rssi": adv.rssi,
            }
            for d, adv in devices
        ]
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        if not devices:
            print("No devices found. Check power / distance / Bluetooth permission.")
            return 1
        print(f"{'NAME':<24} {'ADDRESS':<40} RSSI")
        print("-" * 72)
        for d, adv in devices:
            name = d.name or adv.local_name or "-"
            rssi = adv.rssi if adv.rssi is not None else "-"
            print(f"{name:<24} {d.address:<40} {rssi}")
        print(file=sys.stderr)
        print("Connect with: wit-ble5 connect <ADDRESS>", file=sys.stderr)
    return 0


async def _resolve_address(address: str | None, scan_timeout: float) -> str:
    if address:
        return address
    print(f"No address given; scanning {scan_timeout:.0f}s for WitMotion ...", file=sys.stderr)
    devices = await scan_devices(timeout=scan_timeout, wit_only=True)
    if not devices:
        raise SystemExit("No WitMotion device found. Power on the sensor and retry `wit-ble5 scan`.")
    d, adv = devices[0]
    name = d.name or adv.local_name or "?"
    print(f"Auto-selected: {name}  {d.address}", file=sys.stderr)
    return d.address


def _battery_percent(raw: int) -> int:
    # Protocol docs use register raw as millivolt-ish scale; map like official table.
    table = [
        (396, 100),
        (393, 90),
        (387, 75),
        (382, 60),
        (379, 50),
        (377, 40),
        (373, 30),
        (370, 20),
        (368, 15),
        (350, 10),
        (340, 5),
    ]
    for threshold, pct in table:
        if raw >= threshold:
            return pct
    return 0


async def _cmd_connect(args: argparse.Namespace) -> int:
    address = await _resolve_address(args.address, args.scan_timeout)
    stop = asyncio.Event()
    count = 0
    t0 = time.monotonic()

    def _on_sample(sample: ImuSample | RegisterPacket, raw: bytes) -> None:
        nonlocal count
        if isinstance(sample, RegisterPacket):
            if sample.start_reg == 0x64 and sample.values:
                pct = _battery_percent(sample.values[0])
                msg = {"type": "battery", "raw": sample.values[0], "percent": pct}
                if args.json:
                    print(json.dumps(msg, ensure_ascii=False), flush=True)
                else:
                    print(f"[battery] raw={sample.values[0]} ~{pct}%", flush=True)
            elif not args.json:
                print(f"[reg 0x{sample.start_reg:02X}] {sample.values}", flush=True)
            return

        count += 1
        if args.json:
            payload: dict[str, Any] = {
                "type": "imu",
                "t": time.time(),
                "n": count,
                **sample.to_dict(),
            }
            print(json.dumps(payload, ensure_ascii=False), flush=True)
        else:
            elapsed = time.monotonic() - t0
            print(f"[{count:6d}  {elapsed:7.2f}s] {sample.format_line()}", flush=True)

    print(f"Connecting to {address} ...", file=sys.stderr)
    async with WitBleClient(address, on_sample=_on_sample, timeout=args.timeout) as client:
        print("Connected. Streaming IMU (Ctrl+C to stop) ...", file=sys.stderr)
        if args.rate:
            await client.set_rate(args.rate)
            print(f"Return rate set to {args.rate} Hz", file=sys.stderr)
        if args.battery:
            await client.read_register(0x64)

        loop = asyncio.get_running_loop()

        def _request_stop(*_: Any) -> None:
            stop.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_stop)
            except NotImplementedError:
                # Windows / some environments
                signal.signal(sig, lambda *_: _request_stop())

        if args.duration and args.duration > 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=args.duration)
            except asyncio.TimeoutError:
                pass
        else:
            await stop.wait()

    print(f"Stopped. frames={count}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.cmd == "gui":
        from .gui.app import run_gui

        run_gui()
        return
    try:
        if args.cmd == "scan":
            code = asyncio.run(_cmd_scan(args))
        elif args.cmd == "connect":
            code = asyncio.run(_cmd_connect(args))
        else:
            code = 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        code = 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
