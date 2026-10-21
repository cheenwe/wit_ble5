"""BLE I/O on a dedicated asyncio thread; emits Qt-safe signals."""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

from wit_ble5.client import WitBleClient, scan_devices
from wit_ble5.protocol import ImuSample, RegisterPacket


class BleWorker(QObject):
    devices_found = Signal(list)  # list[dict]
    connected = Signal(str)  # address
    disconnected = Signal()
    sample = Signal(object)  # ImuSample
    battery = Signal(int, int)  # raw, percent
    status = Signal(str)
    error = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: WitBleClient | None = None
        self._stop_scan = asyncio.Event()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="wit-ble-worker", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        loop = self._loop
        if loop is None:
            return
        fut = asyncio.run_coroutine_threadsafe(self._async_shutdown(), loop)
        try:
            fut.result(timeout=5)
        except Exception:
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread:
            self._thread.join(timeout=3)

    def scan(self, timeout: float = 6.0) -> None:
        self._submit(self._async_scan(timeout))

    def connect_device(self, address: str, rate: str | None = "10") -> None:
        self._submit(self._async_connect(address, rate))

    def disconnect_device(self) -> None:
        self._submit(self._async_disconnect())

    def set_rate(self, rate: str) -> None:
        self._submit(self._async_set_rate(rate))

    def request_battery(self) -> None:
        self._submit(self._async_battery())

    def _submit(self, coro: Any) -> None:
        loop = self._loop
        if loop is None or not loop.is_running():
            self.error.emit("BLE worker not ready")
            return
        asyncio.run_coroutine_threadsafe(coro, loop)

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        loop.run_forever()
        pending = asyncio.all_tasks(loop)
        for t in pending:
            t.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()
        self._loop = None

    async def _async_shutdown(self) -> None:
        await self._async_disconnect()

    async def _async_scan(self, timeout: float) -> None:
        self.status.emit(f"Scanning {timeout:.0f}s…")
        try:
            devices = await scan_devices(timeout=timeout, wit_only=True)
            rows = [
                {
                    "name": d.name or adv.local_name or "Unknown",
                    "address": d.address,
                    "rssi": adv.rssi,
                }
                for d, adv in devices
            ]
            self.devices_found.emit(rows)
            self.status.emit(f"Found {len(rows)} device(s)" if rows else "No devices found")
        except Exception as exc:
            self.error.emit(str(exc))
            self.status.emit("Scan failed")

    async def _async_connect(self, address: str, rate: str | None) -> None:
        await self._async_disconnect()
        self.status.emit(f"Connecting {address}…")

        def on_sample(sample: ImuSample | RegisterPacket, _raw: bytes) -> None:
            if isinstance(sample, ImuSample):
                self.sample.emit(sample)
            elif isinstance(sample, RegisterPacket) and sample.start_reg == 0x64 and sample.values:
                raw = sample.values[0]
                self.battery.emit(raw, _battery_percent(raw))

        try:
            client = WitBleClient(address, on_sample=on_sample, timeout=20.0)
            await client.connect()
            self._client = client
            self.connected.emit(address)
            self.status.emit("Connected")
            if rate:
                await client.set_rate(rate)
            await client.read_register(0x64)
        except Exception as exc:
            self._client = None
            self.error.emit(str(exc))
            self.status.emit("Connect failed")
            self.disconnected.emit()

    async def _async_disconnect(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            await client.disconnect()
        except Exception:
            pass
        self.disconnected.emit()
        self.status.emit("Disconnected")

    async def _async_set_rate(self, rate: str) -> None:
        if not self._client or not self._client.is_connected:
            return
        try:
            await self._client.set_rate(rate)
            self.status.emit(f"Rate → {rate} Hz")
        except Exception as exc:
            self.error.emit(str(exc))

    async def _async_battery(self) -> None:
        if not self._client or not self._client.is_connected:
            return
        try:
            await self._client.read_register(0x64)
        except Exception as exc:
            self.error.emit(str(exc))


def _battery_percent(raw: int) -> int:
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
