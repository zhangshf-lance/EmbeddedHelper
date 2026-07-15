from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class BleDevice:
    name: str
    address: str
    rssi: int | None = None
    details: object | None = None


@dataclass(frozen=True)
class GattCharacteristic:
    uuid: str
    description: str
    properties: tuple[str, ...]


class MissingBleak(RuntimeError):
    pass


class BleCentral:
    """Small thread-safe wrapper around bleak for Windows BLE central role."""

    def __init__(
        self,
        on_log: Callable[[str], None],
        on_notification: Callable[[str, bytes], None],
    ) -> None:
        self.on_log = on_log
        self.on_notification = on_notification
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, name="ble-central-loop", daemon=True)
        self._thread.start()
        self._client = None
        self._device_address: str | None = None
        self._devices_by_address: dict[str, object] = {}

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import bleak  # noqa: F401
        except Exception as exc:
            return False, f"未安装 bleak：{exc}"
        return True, "BLE 主设备后端可用"

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    async def scan(self, timeout: float = 5.0) -> list[BleDevice]:
        try:
            from bleak import BleakScanner
        except Exception as exc:
            raise MissingBleak("请先安装 bleak：pip install -r requirements.txt") from exc

        devices = await BleakScanner.discover(timeout=timeout, return_adv=True)
        rows: list[BleDevice] = []
        self._devices_by_address.clear()
        for device, advertisement in devices.values():
            self._devices_by_address[device.address] = device
            rows.append(
                BleDevice(
                    name=device.name or advertisement.local_name or "(unknown)",
                    address=device.address,
                    rssi=getattr(advertisement, "rssi", None),
                    details=device,
                )
            )
        return sorted(rows, key=lambda item: (item.name == "(unknown)", item.name, item.address))

    async def connect(self, address: str) -> list[GattCharacteristic]:
        try:
            from bleak import BleakClient
        except Exception as exc:
            raise MissingBleak("请先安装 bleak：pip install -r requirements.txt") from exc

        await self.disconnect()
        target = self._devices_by_address.get(address, address)
        self._client = BleakClient(target, timeout=30)
        await self._client.connect()
        self._device_address = address
        self.on_log(f"已连接 BLE 设备：{address}")
        return await self.characteristics()

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                if self._client.is_connected:
                    await self._client.disconnect()
            finally:
                self._client = None
                self._device_address = None

    async def characteristics(self) -> list[GattCharacteristic]:
        client = self._require_client()
        services = client.services
        rows: list[GattCharacteristic] = []
        for service in services:
            for char in service.characteristics:
                rows.append(
                    GattCharacteristic(
                        uuid=str(char.uuid),
                        description=getattr(char, "description", "") or str(service.uuid),
                        properties=tuple(char.properties),
                    )
                )
        return rows

    async def read(self, characteristic_uuid: str) -> bytes:
        client = self._require_client()
        return bytes(await client.read_gatt_char(characteristic_uuid))

    async def write(self, characteristic_uuid: str, data: bytes, response: bool = True) -> None:
        client = self._require_client()
        await client.write_gatt_char(characteristic_uuid, data, response=response)

    async def start_notify(self, characteristic_uuid: str) -> None:
        client = self._require_client()

        def callback(sender, data: bytearray) -> None:
            self.on_notification(str(sender), bytes(data))

        await client.start_notify(characteristic_uuid, callback)

    async def stop_notify(self, characteristic_uuid: str) -> None:
        client = self._require_client()
        await client.stop_notify(characteristic_uuid)

    def _require_client(self):
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("BLE 主设备未连接")
        return self._client

    def shutdown(self) -> None:
        try:
            self.submit(self.disconnect()).result(timeout=3)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
