from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError
import threading
from dataclasses import dataclass
from typing import Callable


DEFAULT_SERVICE_UUID = "6E400001-B5A3-F393-E0A9-E50E24DCCA9E"
DEFAULT_RX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
DEFAULT_TX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"


@dataclass(frozen=True)
class PeripheralStatus:
    running: bool
    message: str


class BlePeripheral:
    """Thread-safe facade for a BLE GATT server using bless when available."""

    def __init__(self, on_log: Callable[[str], None], on_rx: Callable[[bytes], None]) -> None:
        self.on_log = on_log
        self.on_rx = on_rx
        self.running = False
        self._service_uuid = DEFAULT_SERVICE_UUID
        self._rx_uuid = DEFAULT_RX_UUID
        self._tx_uuid = DEFAULT_TX_UUID
        self._device_name = "BLE Debug Slave"
        self._server = None
        self._name_status = ""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="ble-peripheral-loop", daemon=True
        )
        self._thread.start()

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import bless  # noqa: F401
        except Exception as exc:
            return False, f"未安装 BLE GATT Server 依赖 bless：{exc}"
        return True, "BLE 从设备后端可用"

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def start(
        self,
        device_name: str,
        service_uuid: str,
        rx_uuid: str,
        tx_uuid: str,
    ) -> PeripheralStatus:
        self._device_name = device_name
        self._service_uuid = service_uuid
        self._rx_uuid = rx_uuid
        self._tx_uuid = tx_uuid
        try:
            return self._submit(
                self._start_async(device_name, service_uuid, rx_uuid, tx_uuid)
            ).result(timeout=15)
        except TimeoutError:
            if self._is_advertising():
                self.running = True
                return PeripheralStatus(
                    True,
                    f"BLE 从设备已广播 Service UUID：{service_uuid}；外部可能显示为电脑蓝牙名或无名称",
                )
            self.running = False
            return PeripheralStatus(False, "BLE 从设备启动超时，且未检测到 GATT 广播")
        except Exception as exc:
            self.running = False
            return PeripheralStatus(False, f"BLE 从设备启动失败：{exc}")

    def stop(self) -> PeripheralStatus:
        try:
            return self._submit(self._stop_async()).result(timeout=10)
        except Exception as exc:
            self.running = False
            self._server = None
            return PeripheralStatus(False, f"BLE 从设备停止失败：{exc}")

    def notify(self, data: bytes) -> PeripheralStatus:
        if not self.running:
            return PeripheralStatus(False, "BLE 从设备未运行，无法发送通知")
        try:
            return self._submit(self._notify_async(data)).result(timeout=10)
        except Exception as exc:
            return PeripheralStatus(False, f"BLE 从设备通知失败：{exc}")

    async def _start_async(
        self,
        device_name: str,
        service_uuid: str,
        rx_uuid: str,
        tx_uuid: str,
    ) -> PeripheralStatus:
        try:
            from bless import (
                BlessServer,
                GATTAttributePermissions,
                GATTCharacteristicProperties,
            )
        except Exception as exc:
            return PeripheralStatus(False, f"请先安装依赖：pip install -r requirements.txt ({exc})")

        await self._stop_async()
        server = await self._create_server(
            BlessServer,
            GATTAttributePermissions,
            GATTCharacteristicProperties,
            device_name,
            service_uuid,
            rx_uuid,
            tx_uuid,
            overwrite_name=True,
        )
        self._server = server
        try:
            await self._start_server(server, use_parameters=False)
        except Exception as exc:
            if getattr(server, "_name_overwrite", False):
                self.on_log(f"BLE 适配器名称覆盖失败，回退普通模式：{exc}")
                await self._stop_async()
                server = await self._create_server(
                    BlessServer,
                    GATTAttributePermissions,
                    GATTCharacteristicProperties,
                    device_name,
                    service_uuid,
                    rx_uuid,
                    tx_uuid,
                    overwrite_name=False,
                )
                self._server = server
                await self._start_server(server, use_parameters=False)
            else:
                raise
        self.running = True
        name_hint = self._name_status or "未覆盖系统蓝牙名称"
        return PeripheralStatus(
            True,
            f"BLE 从设备已广播 Service UUID：{service_uuid}；{name_hint}",
        )

    async def _create_server(
        self,
        server_class,
        permissions_class,
        properties_class,
        device_name: str,
        service_uuid: str,
        rx_uuid: str,
        tx_uuid: str,
        overwrite_name: bool,
    ):
        self._name_status = ""
        server = server_class(name=device_name, name_overwrite=overwrite_name)
        server.read_request_func = self._read_request
        server.write_request_func = self._write_request

        await server.add_new_service(service_uuid)
        await server.add_new_characteristic(
            service_uuid,
            rx_uuid,
            properties_class.write,
            bytearray(),
            permissions_class.writeable,
        )
        await server.add_new_characteristic(
            service_uuid,
            tx_uuid,
            properties_class.read | properties_class.notify,
            bytearray(),
            permissions_class.readable,
        )
        self._attach_status_loggers(server)
        return server

    async def _stop_async(self) -> PeripheralStatus:
        if self._server is not None:
            await self._server.stop()
        self._server = None
        self.running = False
        return PeripheralStatus(False, "BLE 从设备已停止")

    async def _notify_async(self, data: bytes) -> PeripheralStatus:
        if self._server is None:
            return PeripheralStatus(False, "BLE 从设备未运行")

        characteristic = None
        if hasattr(self._server, "get_characteristic"):
            characteristic = self._server.get_characteristic(self._tx_uuid)
        if characteristic is not None:
            characteristic.value = bytearray(data)
        updated = self._server.update_value(self._service_uuid, self._tx_uuid)
        if not updated:
            return PeripheralStatus(False, "BLE 从设备通知失败：未找到 TX 特征")
        self.on_log(f"BLE 从设备通知 {len(data)} 字节")
        return PeripheralStatus(True, "通知已发送")

    async def _start_server(self, server, use_parameters: bool) -> None:
        from winrt.windows.devices.bluetooth.genericattributeprofile import (
            GattServiceProviderAdvertisingParameters,
        )

        parameters = GattServiceProviderAdvertisingParameters()
        parameters.is_discoverable = True
        parameters.is_connectable = True

        await self._start_advertising_attempt(
            server,
            lambda service_provider: self._start_provider(service_provider, parameters),
        )
        if getattr(server, "_name_overwrite", False):
            self._name_status = f"已尝试将系统蓝牙名称覆盖为：{self._device_name}"
        if self._is_advertising():
            return

        statuses = self._advertisement_statuses(server)
        raise RuntimeError(f"BLE GATT 广播未启动，状态：{self._format_statuses(statuses)}")

    def _start_provider(self, service_provider, parameters) -> None:
        if hasattr(service_provider, "start_advertising_with_parameters"):
            service_provider.start_advertising_with_parameters(parameters)
            return
        try:
            service_provider.start_advertising(parameters)
        except TypeError as exc:
            if "Invalid parameter count" not in str(exc):
                raise
            service_provider.start_advertising()

    async def _start_advertising_attempt(self, server, start_provider: Callable[[object], None]) -> None:
        for service in server.services.values():
            service_provider = getattr(service, "service_provider", None)
            if service_provider is None:
                raise RuntimeError("BLE GATT 服务尚未初始化")
            start_provider(service_provider)

        if hasattr(server, "_advertising"):
            server._advertising = True

        last_statuses: list[int | None] = []
        for _ in range(25):
            last_statuses = self._advertisement_statuses(server)
            if any(status in (2, 4) for status in last_statuses):
                self.on_log(f"BLE GATT 广播状态：{self._format_statuses(last_statuses)}")
                return
            await asyncio.sleep(0.2)
        self.on_log(f"BLE GATT 广播状态：{self._format_statuses(last_statuses)}")

    def _attach_status_loggers(self, server) -> None:
        for service in server.services.values():
            service_provider = getattr(service, "service_provider", None)
            if service_provider is None:
                continue
            try:
                service_provider.add_advertisement_status_changed(
                    lambda _sender, args: self.on_log(
                        "BLE GATT 广播事件："
                        f"状态={self._format_status(getattr(args, 'status', None))}，"
                        f"错误={getattr(args, 'error', None)}"
                    )
                )
            except Exception as exc:
                self.on_log(f"BLE GATT 广播事件监听失败：{exc}")

    def _is_advertising(self) -> bool:
        server = self._server
        if server is None:
            return False
        return any(status in (2, 4) for status in self._advertisement_statuses(server))

    def _advertisement_statuses(self, server) -> list[int | None]:
        statuses: list[int | None] = []
        for service in server.services.values():
            service_provider = getattr(service, "service_provider", None)
            status = getattr(service_provider, "advertisement_status", None)
            if hasattr(status, "value"):
                status = status.value
            statuses.append(status)
        return statuses

    def _format_statuses(self, statuses: list[int | None]) -> str:
        return ", ".join(self._format_status(status) for status in statuses)

    def _format_status(self, status) -> str:
        if hasattr(status, "value"):
            status = status.value
        names = {
            0: "CREATED(0)",
            1: "STOPPED(1)",
            2: "STARTED(2)",
            3: "ABORTED(3)",
            4: "STARTED_WITHOUT_ALL_ADVERTISEMENT_DATA(4)",
        }
        return names.get(status, str(status))

    def _read_request(self, characteristic, **_kwargs):
        value = getattr(characteristic, "value", bytearray())
        return value if value is not None else bytearray()

    def _write_request(self, characteristic, value, **_kwargs):
        characteristic.value = value
        try:
            uuid = str(getattr(characteristic, "uuid", ""))
            if uuid.lower() == self._rx_uuid.lower():
                self.on_rx(bytes(value))
        except Exception as exc:
            self.on_log(f"BLE 从设备写入回调失败：{exc}")

    def shutdown(self) -> None:
        self.stop()
        self._loop.call_soon_threadsafe(self._loop.stop)
