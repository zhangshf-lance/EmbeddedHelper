from __future__ import annotations

import winreg
from dataclasses import dataclass
from typing import Iterator


BLUETOOTH_CLASS_GUID = "{e0cbf06c-cd8b-4647-bb8a-263b43f0f974}"


@dataclass(frozen=True)
class Device:
    _instance_id: str


def devices(class_guid: str) -> Iterator[Device]:
    """Minimal pysetupdi-compatible device iterator for bless on Windows.

    The bless WinRT backend only needs objects with an ``_instance_id`` field
    and filters Bluetooth adapters whose id starts with ``USB``. This shim
    reads that information from the Windows Enum registry tree.
    """
    if class_guid.lower() != BLUETOOTH_CLASS_GUID:
        return
    root_path = r"SYSTEM\CurrentControlSet\Enum\USB"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root_path) as root:
            index = 0
            while True:
                try:
                    hardware_id = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                yield from _instances_for_hardware(root_path, hardware_id)
    except OSError:
        return


def _instances_for_hardware(root_path: str, hardware_id: str) -> Iterator[Device]:
    hardware_path = f"{root_path}\\{hardware_id}"
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, hardware_path) as hardware_key:
            index = 0
            while True:
                try:
                    instance_id = winreg.EnumKey(hardware_key, index)
                except OSError:
                    break
                index += 1
                if _is_bluetooth_instance(f"{hardware_path}\\{instance_id}"):
                    yield Device(f"USB\\{hardware_id}\\{instance_id}")
    except OSError:
        return


def _is_bluetooth_instance(instance_path: str) -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, instance_path) as instance_key:
            class_guid, _ = winreg.QueryValueEx(instance_key, "ClassGUID")
    except OSError:
        return False
    return str(class_guid).lower() == BLUETOOTH_CLASS_GUID
