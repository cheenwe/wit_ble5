"""Async BLE client for WitMotion BLE 5.0 sensors (macOS / Linux via bleak)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

from .protocol import (
    NOTIFY_UUID,
    SERVICE_UUID,
    WRITE_UUID,
    ImuSample,
    RegisterPacket,
    cmd_read_register,
    cmd_set_rate,
    looks_like_wit_device,
    parse_packet,
)

SampleCallback = Callable[[ImuSample | RegisterPacket, bytes], None | Awaitable[None]]


async def scan_devices(
    timeout: float = 8.0,
    *,
    wit_only: bool = True,
) -> list[tuple[BLEDevice, AdvertisementData]]:
    """Scan for nearby BLE devices. By default keep WitMotion-looking names."""
    found: dict[str, tuple[BLEDevice, AdvertisementData]] = {}

    def _on_detect(device: BLEDevice, adv: AdvertisementData) -> None:
        name = device.name or adv.local_name
        if wit_only and not looks_like_wit_device(name):
            uuids = {u.lower() for u in (adv.service_uuids or [])}
            if SERVICE_UUID.lower() not in uuids:
                return
        found[device.address] = (device, adv)

    async with BleakScanner(detection_callback=_on_detect):
        await asyncio.sleep(timeout)

    return sorted(found.values(), key=lambda x: (x[0].name or "", x[0].address))


class WitBleClient:
    """Connect, subscribe to IMU notifications, optionally send commands."""

    def __init__(
        self,
        address: str,
        *,
        on_sample: SampleCallback | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.address = address
        self.on_sample = on_sample
        self.timeout = timeout
        self._client: BleakClient | None = None
        self._write_uuid = WRITE_UUID
        self._notify_uuid = NOTIFY_UUID
        self._latest: ImuSample | None = None
        self._lock = asyncio.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected)

    @property
    def latest(self) -> ImuSample | None:
        return self._latest

    async def connect(self) -> None:
        if self.is_connected:
            return
        self._loop = asyncio.get_running_loop()
        client = BleakClient(self.address, timeout=self.timeout)
        await client.connect()
        self._client = client
        self._resolve_characteristics()
        await client.start_notify(self._notify_uuid, self._handle_notify)

    async def disconnect(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            if client.is_connected:
                try:
                    await client.stop_notify(self._notify_uuid)
                except Exception:
                    pass
                await client.disconnect()
        except Exception:
            pass

    async def __aenter__(self) -> WitBleClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.disconnect()

    async def set_rate(self, rate_hz: str) -> None:
        await self.write(cmd_set_rate(rate_hz))

    async def read_register(self, reg: int) -> None:
        """Request a register block; response arrives via notify as RegisterPacket."""
        await self.write(cmd_read_register(reg))

    async def write(self, payload: bytes) -> None:
        client = self._require_client()
        async with self._lock:
            await client.write_gatt_char(self._write_uuid, payload, response=False)

    def _require_client(self) -> BleakClient:
        if not self._client or not self._client.is_connected:
            raise RuntimeError("not connected")
        return self._client

    def _resolve_characteristics(self) -> None:
        """Prefer known UUIDs; fall back to discovery within the WitMotion service."""
        client = self._require_client()
        notify = None
        write = None

        for service in client.services:
            if service.uuid.lower() != SERVICE_UUID.lower():
                continue
            for char in service.characteristics:
                props = set(char.properties)
                if "notify" in props:
                    notify = char.uuid
                if "write" in props or "write-without-response" in props:
                    write = char.uuid

        # Absolute UUID match wins if present anywhere
        for service in client.services:
            for char in service.characteristics:
                cu = char.uuid.lower()
                if cu == NOTIFY_UUID.lower():
                    notify = char.uuid
                if cu == WRITE_UUID.lower():
                    write = char.uuid

        if notify:
            self._notify_uuid = notify
        if write:
            self._write_uuid = write

    def _handle_notify(self, _handle: int, data: bytearray) -> None:
        parsed = parse_packet(data)
        if parsed is None:
            return
        if isinstance(parsed, ImuSample):
            self._latest = parsed
        cb = self.on_sample
        if cb is None:
            return
        result = cb(parsed, bytes(data))
        if asyncio.iscoroutine(result) and self._loop is not None:
            self._loop.create_task(result)
