from __future__ import annotations

import ctypes
import threading
import time
import winreg
from ctypes import wintypes
from dataclasses import dataclass
from typing import Callable, Iterable


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value

NOPARITY = 0
ODDPARITY = 1
EVENPARITY = 2
MARKPARITY = 3
SPACEPARITY = 4

ONESTOPBIT = 0
ONE5STOPBITS = 1
TWOSTOPBITS = 2


class DCB(ctypes.Structure):
    _fields_ = [
        ("DCBlength", wintypes.DWORD),
        ("BaudRate", wintypes.DWORD),
        ("fBitFields", wintypes.DWORD),
        ("wReserved", wintypes.WORD),
        ("XonLim", wintypes.WORD),
        ("XoffLim", wintypes.WORD),
        ("ByteSize", ctypes.c_ubyte),
        ("Parity", ctypes.c_ubyte),
        ("StopBits", ctypes.c_ubyte),
        ("XonChar", ctypes.c_char),
        ("XoffChar", ctypes.c_char),
        ("ErrorChar", ctypes.c_char),
        ("EofChar", ctypes.c_char),
        ("EvtChar", ctypes.c_char),
        ("wReserved1", wintypes.WORD),
    ]


class COMMTIMEOUTS(ctypes.Structure):
    _fields_ = [
        ("ReadIntervalTimeout", wintypes.DWORD),
        ("ReadTotalTimeoutMultiplier", wintypes.DWORD),
        ("ReadTotalTimeoutConstant", wintypes.DWORD),
        ("WriteTotalTimeoutMultiplier", wintypes.DWORD),
        ("WriteTotalTimeoutConstant", wintypes.DWORD),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.GetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
kernel32.GetCommState.restype = wintypes.BOOL
kernel32.SetCommState.argtypes = [wintypes.HANDLE, ctypes.POINTER(DCB)]
kernel32.SetCommState.restype = wintypes.BOOL
kernel32.SetCommTimeouts.argtypes = [wintypes.HANDLE, ctypes.POINTER(COMMTIMEOUTS)]
kernel32.SetCommTimeouts.restype = wintypes.BOOL
kernel32.PurgeComm.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.PurgeComm.restype = wintypes.BOOL
kernel32.ReadFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
kernel32.ReadFile.restype = wintypes.BOOL
kernel32.WriteFile.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    wintypes.LPVOID,
]
kernel32.WriteFile.restype = wintypes.BOOL


@dataclass(frozen=True)
class SerialDevice:
    port: str
    description: str


def _last_error(prefix: str) -> OSError:
    return ctypes.WinError(ctypes.get_last_error(), prefix)


def list_serial_ports() -> list[SerialDevice]:
    """Return COM ports registered by Windows, including Bluetooth SPP ports."""
    devices: list[SerialDevice] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DEVICEMAP\SERIALCOMM") as key:
            index = 0
            while True:
                try:
                    name, port, _ = winreg.EnumValue(key, index)
                except OSError:
                    break
                devices.append(SerialDevice(str(port), name))
                index += 1
    except OSError:
        return []
    return sorted(devices, key=lambda item: _port_sort_key(item.port))


def _port_sort_key(port: str) -> tuple[int, str]:
    prefix = "COM"
    if port.upper().startswith(prefix) and port[len(prefix) :].isdigit():
        return (int(port[len(prefix) :]), port)
    return (9999, port)


def encode_payload(text: str, hex_mode: bool = False, line_ending: str = "") -> bytes:
    payload = text.strip() if hex_mode else text
    if hex_mode:
        payload = payload.replace(" ", "").replace(",", "")
        if len(payload) % 2:
            raise ValueError("HEX 数据长度必须是偶数")
        data = bytes.fromhex(payload)
    else:
        data = payload.encode("utf-8")
    endings = {"none": b"", "cr": b"\r", "lf": b"\n", "crlf": b"\r\n"}
    return data + endings.get(line_ending, b"")


def format_payload(data: bytes, hex_mode: bool = False) -> str:
    if hex_mode:
        return " ".join(f"{byte:02X}" for byte in data)
    return data.decode("utf-8", errors="replace")


class WindowsSerialPort:
    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: str = "1",
    ) -> None:
        self.port = port
        self.baudrate = baudrate
        self.bytesize = bytesize
        self.parity = parity.upper()
        self.stopbits = stopbits
        self._handle: wintypes.HANDLE | None = None
        self._reader: threading.Thread | None = None
        self._reader_stop = threading.Event()

    @property
    def is_open(self) -> bool:
        return self._handle is not None

    def open(self) -> None:
        if self.is_open:
            return
        path = self.port if self.port.startswith(r"\\.") else rf"\\.\{self.port}"
        handle = kernel32.CreateFileW(
            path,
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if handle == INVALID_HANDLE_VALUE:
            raise _last_error(f"无法打开串口 {self.port}")
        self._handle = handle
        try:
            self._configure()
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        self.stop_reader()
        if self._handle is not None:
            kernel32.CloseHandle(self._handle)
            self._handle = None

    def _configure(self) -> None:
        if self._handle is None:
            raise RuntimeError("串口未打开")
        dcb = DCB()
        dcb.DCBlength = ctypes.sizeof(DCB)
        if not kernel32.GetCommState(self._handle, ctypes.byref(dcb)):
            raise _last_error("读取串口配置失败")
        dcb.BaudRate = int(self.baudrate)
        dcb.ByteSize = int(self.bytesize)
        dcb.Parity = {
            "N": NOPARITY,
            "O": ODDPARITY,
            "E": EVENPARITY,
            "M": MARKPARITY,
            "S": SPACEPARITY,
        }.get(self.parity, NOPARITY)
        dcb.StopBits = {"1": ONESTOPBIT, "1.5": ONE5STOPBITS, "2": TWOSTOPBITS}.get(
            self.stopbits, ONESTOPBIT
        )
        dcb.fBitFields = 1
        if not kernel32.SetCommState(self._handle, ctypes.byref(dcb)):
            raise _last_error("设置串口参数失败")

        timeouts = COMMTIMEOUTS()
        timeouts.ReadIntervalTimeout = 50
        timeouts.ReadTotalTimeoutMultiplier = 10
        timeouts.ReadTotalTimeoutConstant = 50
        timeouts.WriteTotalTimeoutMultiplier = 10
        timeouts.WriteTotalTimeoutConstant = 500
        if not kernel32.SetCommTimeouts(self._handle, ctypes.byref(timeouts)):
            raise _last_error("设置串口超时失败")
        kernel32.PurgeComm(self._handle, 0x0004 | 0x0008)

    def write(self, data: bytes) -> int:
        if self._handle is None:
            raise RuntimeError("串口未打开")
        written = wintypes.DWORD(0)
        buffer = ctypes.create_string_buffer(data)
        ok = kernel32.WriteFile(self._handle, buffer, len(data), ctypes.byref(written), None)
        if not ok:
            raise _last_error("串口写入失败")
        return int(written.value)

    def read(self, size: int = 4096) -> bytes:
        if self._handle is None:
            raise RuntimeError("串口未打开")
        buffer = ctypes.create_string_buffer(size)
        received = wintypes.DWORD(0)
        ok = kernel32.ReadFile(self._handle, buffer, size, ctypes.byref(received), None)
        if not ok:
            raise _last_error("串口读取失败")
        return bytes(buffer.raw[: received.value])

    def start_reader(
        self,
        on_data: Callable[[bytes], None],
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if self._reader and self._reader.is_alive():
            return
        self._reader_stop.clear()

        def loop() -> None:
            while not self._reader_stop.is_set():
                try:
                    chunk = self.read()
                except Exception as exc:  # pragma: no cover - depends on device removal timing.
                    if on_error:
                        on_error(exc)
                    break
                if chunk:
                    on_data(chunk)
                else:
                    time.sleep(0.02)

        self._reader = threading.Thread(target=loop, name=f"serial-reader-{self.port}", daemon=True)
        self._reader.start()

    def stop_reader(self) -> None:
        self._reader_stop.set()
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=1.0)
        self._reader = None


def common_baudrates() -> Iterable[int]:
    return (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
