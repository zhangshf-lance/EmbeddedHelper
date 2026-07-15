from __future__ import annotations

import datetime as _dt
import tkinter.font as tkfont
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .ble_central import BleCentral, BleDevice, GattCharacteristic
from .ble_peripheral import (
    DEFAULT_RX_UUID,
    DEFAULT_SERVICE_UUID,
    DEFAULT_TX_UUID,
    BlePeripheral,
)
from .serial_win import (
    WindowsSerialPort,
    common_baudrates,
    encode_payload,
    format_payload,
    list_serial_ports,
)


class BleAssistantApp(tk.Tk):
    BG = "#f4f7fb"
    TEXT_BG = "#f8fafc"
    ACCENT = "#2563eb"
    TEXT = "#1f2937"
    MUTED = "#64748b"
    BORDER = "#dbe3ee"

    def __init__(self) -> None:
        super().__init__()
        self.title("Windows 蓝牙调试助手")
        self.geometry("1180x800")
        self.minsize(1040, 700)
        self.configure(background=self.BG)

        self.central = BleCentral(self.log, self._on_ble_notification)
        self.peripheral = BlePeripheral(self.log, self._on_peripheral_rx)
        self.serial_port: WindowsSerialPort | None = None
        self.ble_devices: list[BleDevice] = []
        self.ble_characteristics: list[GattCharacteristic] = []
        self.worker_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ui-worker")

        self._build_style()
        self._build()
        self._refresh_serial_ports()
        self._show_backend_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        self.option_add("*Font", "{Microsoft YaHei UI} 9")
        self.option_add("*TCombobox*Listbox.font", "{Microsoft YaHei UI} 9")
        tkfont.nametofont("TkDefaultFont").configure(family="Microsoft YaHei UI", size=9)
        tkfont.nametofont("TkTextFont").configure(family="Consolas", size=10)

        style.configure(".", background=self.BG, foreground=self.TEXT)
        style.configure("TFrame", background=self.BG)
        style.configure("Header.TFrame", background="#0f172a")
        style.configure(
            "HeaderTitle.TLabel",
            background="#0f172a",
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 15, "bold"),
        )
        style.configure(
            "HeaderSub.TLabel",
            background="#0f172a",
            foreground="#cbd5e1",
            font=("Microsoft YaHei UI", 9),
        )
        style.configure("TLabel", background=self.BG, foreground=self.TEXT)
        style.configure("Status.TLabel", background=self.BG, foreground=self.MUTED)
        style.configure("TLabelframe", background=self.BG, bordercolor=self.BORDER)
        style.configure(
            "TLabelframe.Label",
            background=self.BG,
            foreground=self.TEXT,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.configure("TNotebook", background=self.BG, borderwidth=0)
        style.configure(
            "TNotebook.Tab",
            padding=(18, 9),
            background="#e8eef7",
            foreground="#334155",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#ffffff"), ("active", "#eef4ff")],
            foreground=[("selected", self.ACCENT)],
        )
        style.configure("TButton", padding=(12, 6))
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#ffffff")
        style.map(
            "Accent.TButton",
            background=[("active", "#1d4ed8"), ("disabled", "#93c5fd")],
            foreground=[("disabled", "#eff6ff")],
        )
        style.configure("Danger.TButton", foreground="#b91c1c")
        style.configure("TEntry", fieldbackground="#ffffff", bordercolor=self.BORDER, padding=4)
        style.configure("TCombobox", fieldbackground="#ffffff", bordercolor=self.BORDER, padding=3)
        style.configure("TCheckbutton", background=self.BG, foreground=self.TEXT)

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Windows 蓝牙调试助手", style="HeaderTitle.TLabel").grid(
            row=0, column=0, sticky="w", padx=18, pady=(14, 2)
        )
        ttk.Label(
            header,
            text="BLE 主设备、BLE GATT 从设备、串口通信一体化调试",
            style="HeaderSub.TLabel",
        ).grid(row=1, column=0, sticky="w", padx=18, pady=(0, 14))

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=14, pady=14)

        self.ble_tab = ttk.Frame(notebook)
        self.peripheral_tab = ttk.Frame(notebook)
        self.serial_tab = ttk.Frame(notebook)
        self.log_tab = ttk.Frame(notebook)

        notebook.add(self.ble_tab, text="BLE 主设备")
        notebook.add(self.peripheral_tab, text="BLE 从设备")
        notebook.add(self.serial_tab, text="串口通信")
        notebook.add(self.log_tab, text="运行日志")

        self._build_ble_tab()
        self._build_peripheral_tab()
        self._build_serial_tab()
        self._build_log_tab()
        self._style_text_widgets()

    def _build_ble_tab(self) -> None:
        tab = self.ble_tab
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=2)
        tab.rowconfigure(1, weight=1)

        toolbar = ttk.Frame(tab)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        ttk.Label(toolbar, text="扫描秒数").pack(side="left")
        self.scan_timeout = tk.StringVar(value="5")
        ttk.Entry(toolbar, width=6, textvariable=self.scan_timeout).pack(side="left", padx=(6, 12))
        ttk.Button(toolbar, text="扫描", command=self._ble_scan, style="Accent.TButton").pack(side="left")
        ttk.Button(toolbar, text="连接", command=self._ble_connect, style="Accent.TButton").pack(side="left", padx=6)
        ttk.Button(toolbar, text="断开", command=self._ble_disconnect).pack(side="left")
        self.ble_status = ttk.Label(toolbar, text="未连接", style="Status.TLabel")
        self.ble_status.pack(side="left", padx=16)

        left = ttk.LabelFrame(tab, text="发现的设备")
        left.grid(row=1, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.ble_device_list = tk.Listbox(
            left,
            activestyle="dotbox",
            exportselection=False,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=self.BORDER,
            selectbackground=self.ACCENT,
            selectforeground="#ffffff",
            background=self.TEXT_BG,
            foreground=self.TEXT,
            font=("Microsoft YaHei UI", 9),
        )
        self.ble_device_list.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.ble_device_list.bind("<Double-Button-1>", lambda _event: self._ble_connect())

        right = ttk.Frame(tab)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        char_frame = ttk.LabelFrame(right, text="GATT 特征")
        char_frame.grid(row=0, column=0, sticky="ew")
        char_frame.columnconfigure(1, weight=1)
        ttk.Label(char_frame, text="特征").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.ble_char_var = tk.StringVar()
        self.ble_char_combo = ttk.Combobox(char_frame, textvariable=self.ble_char_var, state="readonly")
        self.ble_char_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=8)

        options = ttk.Frame(right)
        options.grid(row=1, column=0, sticky="ew", pady=8)
        self.ble_hex = tk.BooleanVar(value=False)
        self.ble_write_response = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="HEX", variable=self.ble_hex).pack(side="left")
        ttk.Checkbutton(options, text="响应写", variable=self.ble_write_response).pack(
            side="left", padx=12
        )
        ttk.Button(options, text="读", command=self._ble_read).pack(side="left")
        ttk.Button(options, text="写", command=self._ble_write).pack(side="left", padx=6)
        ttk.Button(options, text="订阅通知", command=self._ble_notify).pack(side="left")
        ttk.Button(options, text="停止通知", command=self._ble_stop_notify).pack(side="left", padx=6)

        send_frame = ttk.LabelFrame(right, text="发送数据")
        send_frame.grid(row=2, column=0, sticky="ew")
        send_frame.columnconfigure(0, weight=1)
        self.ble_send_text = ttk.Entry(send_frame)
        self.ble_send_text.grid(row=0, column=0, sticky="ew", padx=8, pady=8)

        recv_frame = ttk.LabelFrame(right, text="接收 / 读取")
        recv_frame.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        recv_frame.columnconfigure(0, weight=1)
        recv_frame.rowconfigure(0, weight=1)
        self.ble_recv = ScrolledText(recv_frame, height=16, wrap="word")
        self.ble_recv.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _build_peripheral_tab(self) -> None:
        tab = self.peripheral_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        form = ttk.LabelFrame(tab, text="BLE GATT 从设备")
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        self.peripheral_name = tk.StringVar(value="BLE Debug Slave")
        self.peripheral_service = tk.StringVar(value=DEFAULT_SERVICE_UUID)
        self.peripheral_rx = tk.StringVar(value=DEFAULT_RX_UUID)
        self.peripheral_tx = tk.StringVar(value=DEFAULT_TX_UUID)
        rows = [
            ("系统蓝牙名称", self.peripheral_name),
            ("Service UUID", self.peripheral_service),
            ("RX UUID 写入", self.peripheral_rx),
            ("TX UUID 通知", self.peripheral_tx),
        ]
        for row, (label, variable) in enumerate(rows):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
            ttk.Entry(form, textvariable=variable).grid(
                row=row, column=1, sticky="ew", padx=(0, 8), pady=6
            )

        buttons = ttk.Frame(tab)
        buttons.grid(row=1, column=0, sticky="ew", pady=8)
        self.peripheral_start_button = ttk.Button(
            buttons, text="启动从设备", command=self._peripheral_start, style="Accent.TButton"
        )
        self.peripheral_start_button.pack(side="left")
        self.peripheral_stop_button = ttk.Button(
            buttons, text="停止", command=self._peripheral_stop
        )
        self.peripheral_stop_button.pack(side="left", padx=6)
        self.peripheral_send_hex = tk.BooleanVar(value=False)
        self.peripheral_recv_hex = tk.BooleanVar(value=False)
        ttk.Checkbutton(buttons, text="发送HEX", variable=self.peripheral_send_hex).pack(
            side="left", padx=(12, 6)
        )
        ttk.Checkbutton(buttons, text="接收HEX", variable=self.peripheral_recv_hex).pack(
            side="left", padx=6
        )
        self.peripheral_status = ttk.Label(buttons, text="未启动", style="Status.TLabel")
        self.peripheral_status.pack(side="left", padx=12)

        io = ttk.PanedWindow(tab, orient=tk.VERTICAL)
        io.grid(row=2, column=0, sticky="nsew")
        send = ttk.LabelFrame(io, text="通知发送")
        send.columnconfigure(0, weight=1)
        self.peripheral_send_text = ttk.Entry(send)
        self.peripheral_send_text.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.peripheral_send_text.bind("<Return>", lambda _event: self._peripheral_notify())
        self.peripheral_notify_button = ttk.Button(send, text="Notify", command=self._peripheral_notify)
        self.peripheral_notify_button.grid(
            row=0, column=1, padx=(0, 8), pady=8
        )
        recv = ttk.LabelFrame(io, text="主设备写入")
        recv.columnconfigure(0, weight=1)
        recv.rowconfigure(0, weight=1)
        self.peripheral_recv = ScrolledText(recv, height=12, wrap="word")
        self.peripheral_recv.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        io.add(send, weight=0)
        io.add(recv, weight=1)

    def _build_serial_tab(self) -> None:
        tab = self.serial_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(tab)
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(toolbar, text="端口").pack(side="left")
        self.serial_port_var = tk.StringVar()
        self.serial_combo = ttk.Combobox(toolbar, textvariable=self.serial_port_var, width=18)
        self.serial_combo.pack(side="left", padx=(6, 12))
        ttk.Button(toolbar, text="刷新", command=self._refresh_serial_ports).pack(side="left")
        ttk.Label(toolbar, text="波特率").pack(side="left", padx=(12, 0))
        self.serial_baud = tk.StringVar(value="115200")
        ttk.Combobox(
            toolbar,
            textvariable=self.serial_baud,
            values=[str(item) for item in common_baudrates()],
            width=10,
        ).pack(side="left", padx=6)
        ttk.Button(toolbar, text="打开", command=self._serial_open, style="Accent.TButton").pack(side="left", padx=(12, 6))
        ttk.Button(toolbar, text="关闭", command=self._serial_close).pack(side="left")
        self.serial_status = ttk.Label(toolbar, text="未打开", style="Status.TLabel")
        self.serial_status.pack(side="left", padx=16)

        options = ttk.Frame(tab)
        options.grid(row=1, column=0, sticky="ew", pady=8)
        self.serial_hex = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="HEX", variable=self.serial_hex).pack(side="left")
        ttk.Label(options, text="行尾").pack(side="left", padx=(12, 0))
        self.serial_line_ending = tk.StringVar(value="none")
        ttk.Combobox(
            options,
            textvariable=self.serial_line_ending,
            values=("none", "cr", "lf", "crlf"),
            width=8,
            state="readonly",
        ).pack(side="left", padx=6)

        terminal = ttk.LabelFrame(tab, text="接收窗口")
        terminal.grid(row=2, column=0, sticky="nsew")
        terminal.columnconfigure(0, weight=1)
        terminal.rowconfigure(0, weight=1)
        self.serial_recv = ScrolledText(terminal, height=18, wrap="word")
        self.serial_recv.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        send = ttk.LabelFrame(tab, text="发送数据")
        send.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        send.columnconfigure(0, weight=1)
        self.serial_send_text = ttk.Entry(send)
        self.serial_send_text.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.serial_send_text.bind("<Return>", lambda _event: self._serial_send())
        ttk.Button(send, text="发送", command=self._serial_send).grid(row=0, column=1, padx=(0, 8))

    def _build_log_tab(self) -> None:
        self.log_tab.columnconfigure(0, weight=1)
        self.log_tab.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(self.log_tab, wrap="word")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _style_text_widgets(self) -> None:
        for widget in (self.ble_recv, self.peripheral_recv, self.serial_recv, self.log_text):
            widget.configure(
                background=self.TEXT_BG,
                foreground=self.TEXT,
                insertbackground=self.ACCENT,
                borderwidth=0,
                relief="flat",
                padx=10,
                pady=8,
                font=("Consolas", 10),
            )

    def _show_backend_status(self) -> None:
        for title, status in (
            ("BLE 主设备", BleCentral.available()),
            ("BLE 从设备", BlePeripheral.available()),
        ):
            ok, message = status
            self.log(f"{title}: {'OK' if ok else '不可用'} - {message}")

    def log(self, message: str) -> None:
        timestamp = _dt.datetime.now().strftime("%H:%M:%S")
        self.after(0, lambda: self._append_text(self.log_text, f"[{timestamp}] {message}\n"))

    def _append_text(self, widget: ScrolledText, text: str) -> None:
        widget.insert("end", text)
        widget.see("end")

    def _future_result(self, future: Future, callback, error_prefix: str) -> None:
        def done(done_future: Future) -> None:
            try:
                result = done_future.result()
            except Exception as exc:
                self.after(0, lambda caught=exc: self._show_error(error_prefix, caught))
                return
            self.after(0, lambda: callback(result))

        future.add_done_callback(done)

    def _show_error(self, prefix: str, exc: Exception) -> None:
        self.log(f"{prefix}: {exc}")
        messagebox.showerror(prefix, str(exc))

    def _ble_scan(self) -> None:
        try:
            timeout = max(1.0, float(self.scan_timeout.get()))
        except ValueError:
            timeout = 5.0
        self.ble_characteristics = []
        self.ble_char_combo.config(values=[])
        self.ble_char_var.set("")
        self.ble_status.config(text="扫描中...")
        self.log(f"开始扫描 BLE 设备，{timeout:g} 秒")
        future = self.central.submit(self.central.scan(timeout))
        self._future_result(future, self._ble_scan_done, "BLE 扫描失败")

    def _ble_scan_done(self, devices: list[BleDevice]) -> None:
        self.ble_devices = devices
        self.ble_device_list.delete(0, "end")
        for device in devices:
            rssi = "" if device.rssi is None else f" RSSI {device.rssi}"
            self.ble_device_list.insert("end", f"{device.name} | {device.address}{rssi}")
        self.ble_status.config(text=f"发现 {len(devices)} 个设备")

    def _selected_ble_device(self) -> BleDevice | None:
        selection = self.ble_device_list.curselection()
        if not selection:
            messagebox.showinfo("选择设备", "请先选择一个 BLE 设备")
            return None
        return self.ble_devices[selection[0]]

    def _ble_connect(self) -> None:
        device = self._selected_ble_device()
        if not device:
            return
        self.ble_characteristics = []
        self.ble_char_combo.config(values=[])
        self.ble_char_var.set("")
        self.ble_status.config(text=f"连接 {device.address}...")
        self.log(f"开始连接 BLE 设备：{device.name} | {device.address}")
        future = self.central.submit(self.central.connect(device.address))
        self._future_result(future, self._ble_connected, "BLE 连接失败")

    def _ble_connected(self, characteristics: list[GattCharacteristic]) -> None:
        self.ble_characteristics = characteristics
        values = [
            f"{char.uuid} | {','.join(char.properties)} | {char.description}"
            for char in characteristics
        ]
        self.ble_char_combo.config(values=values)
        if values:
            self.ble_char_combo.current(0)
        self.ble_status.config(text=f"已连接，{len(values)} 个特征")

    def _ble_disconnect(self) -> None:
        future = self.central.submit(self.central.disconnect())
        self._future_result(future, lambda _result: self.ble_status.config(text="已断开"), "BLE 断开失败")

    def _selected_char_uuid(self) -> str | None:
        index = self.ble_char_combo.current()
        if index < 0 or index >= len(self.ble_characteristics):
            messagebox.showinfo("选择特征", "请先选择一个 GATT 特征")
            return None
        return self.ble_characteristics[index].uuid

    def _ble_read(self) -> None:
        char_uuid = self._selected_char_uuid()
        if not char_uuid:
            return
        future = self.central.submit(self.central.read(char_uuid))
        self._future_result(future, lambda data: self._append_ble_rx("READ", char_uuid, data), "BLE 读取失败")

    def _ble_write(self) -> None:
        char_uuid = self._selected_char_uuid()
        if not char_uuid:
            return
        try:
            data = encode_payload(self.ble_send_text.get(), self.ble_hex.get(), "none")
        except ValueError as exc:
            self._show_error("BLE 数据格式错误", exc)
            return
        future = self.central.submit(
            self.central.write(char_uuid, data, response=self.ble_write_response.get())
        )
        self._future_result(future, lambda _result: self.log(f"BLE 写入 {len(data)} 字节"), "BLE 写入失败")

    def _ble_notify(self) -> None:
        char_uuid = self._selected_char_uuid()
        if not char_uuid:
            return
        future = self.central.submit(self.central.start_notify(char_uuid))
        self._future_result(future, lambda _result: self.log(f"已订阅 {char_uuid}"), "BLE 订阅失败")

    def _ble_stop_notify(self) -> None:
        char_uuid = self._selected_char_uuid()
        if not char_uuid:
            return
        future = self.central.submit(self.central.stop_notify(char_uuid))
        self._future_result(future, lambda _result: self.log(f"已停止订阅 {char_uuid}"), "BLE 停止通知失败")

    def _on_ble_notification(self, sender: str, data: bytes) -> None:
        self.after(0, lambda: self._append_ble_rx("NOTIFY", sender, data))

    def _append_ble_rx(self, label: str, source: str, data: bytes) -> None:
        body = format_payload(data, self.ble_hex.get())
        self._append_text(self.ble_recv, f"{label} {source}: {body}\n")

    def _peripheral_start(self) -> None:
        name = self.peripheral_name.get()
        service_uuid = self.peripheral_service.get()
        rx_uuid = self.peripheral_rx.get()
        tx_uuid = self.peripheral_tx.get()
        self._run_peripheral_task(
            "正在启动从设备...",
            lambda: self.peripheral.start(name, service_uuid, rx_uuid, tx_uuid),
            self._apply_peripheral_status,
        )

    def _peripheral_stop(self) -> None:
        self._run_peripheral_task(
            "正在停止从设备...",
            self.peripheral.stop,
            self._apply_peripheral_status,
        )

    def _peripheral_notify(self) -> None:
        try:
            data = encode_payload(self.peripheral_send_text.get(), self.peripheral_send_hex.get(), "none")
        except ValueError as exc:
            self._show_error("从设备数据格式错误", exc)
            return
        self._run_peripheral_task(
            "正在发送通知...",
            lambda: self.peripheral.notify(data),
            self._apply_peripheral_status,
        )

    def _run_peripheral_task(self, busy_text: str, action, callback) -> None:
        self._set_peripheral_busy(True, busy_text)
        future = self.worker_pool.submit(action)
        future.add_done_callback(
            lambda done_future: self.after(0, lambda: self._peripheral_task_done(done_future, callback))
        )

    def _peripheral_task_done(self, future: Future, callback) -> None:
        self._set_peripheral_busy(False)
        try:
            result = future.result()
        except Exception as exc:
            self._show_error("BLE 从设备操作失败", exc)
            return
        callback(result)

    def _set_peripheral_busy(self, busy: bool, text: str | None = None) -> None:
        state = "disabled" if busy else "normal"
        for button in (
            self.peripheral_start_button,
            self.peripheral_stop_button,
            self.peripheral_notify_button,
        ):
            button.config(state=state)
        if text:
            self.peripheral_status.config(text=text)

    def _apply_peripheral_status(self, status) -> None:
        self.peripheral_status.config(text=status.message)
        self.log(status.message)

    def _on_peripheral_rx(self, data: bytes) -> None:
        body = format_payload(data, self.peripheral_recv_hex.get())
        self.after(0, lambda: self._append_text(self.peripheral_recv, f"RX: {body}\n"))

    def _refresh_serial_ports(self) -> None:
        ports = list_serial_ports()
        values = [f"{item.port} | {item.description}" for item in ports]
        self.serial_combo.config(values=values)
        if values and not self.serial_port_var.get():
            self.serial_combo.current(0)
        self.log(f"刷新串口：{len(values)} 个")

    def _serial_selected_port(self) -> str:
        value = self.serial_port_var.get().strip()
        if "|" in value:
            value = value.split("|", 1)[0].strip()
        return value

    def _serial_open(self) -> None:
        if self.serial_port:
            self._serial_close()
        port = self._serial_selected_port()
        if not port:
            messagebox.showinfo("选择串口", "请先选择或输入 COM 口")
            return
        try:
            baud = int(self.serial_baud.get())
            self.serial_port = WindowsSerialPort(port, baudrate=baud)
            self.serial_port.open()
            self.serial_port.start_reader(self._on_serial_data, self._on_serial_error)
        except Exception as exc:
            self.serial_port = None
            self._show_error("串口打开失败", exc)
            return
        self.serial_status.config(text=f"{port} 已打开")
        self.log(f"串口已打开：{port} @ {baud}")

    def _serial_close(self) -> None:
        if self.serial_port:
            port = self.serial_port.port
            self.serial_port.close()
            self.serial_port = None
            self.log(f"串口已关闭：{port}")
        self.serial_status.config(text="未打开")

    def _serial_send(self) -> None:
        if not self.serial_port:
            messagebox.showinfo("串口未打开", "请先打开串口")
            return
        try:
            data = encode_payload(
                self.serial_send_text.get(),
                self.serial_hex.get(),
                self.serial_line_ending.get(),
            )
            count = self.serial_port.write(data)
        except Exception as exc:
            self._show_error("串口发送失败", exc)
            return
        self.log(f"串口发送 {count} 字节")

    def _on_serial_data(self, data: bytes) -> None:
        body = format_payload(data, self.serial_hex.get())
        self.after(0, lambda: self._append_text(self.serial_recv, body))

    def _on_serial_error(self, exc: Exception) -> None:
        self.after(0, lambda: self._show_error("串口读取失败", exc))

    def _on_close(self) -> None:
        self._serial_close()
        self.peripheral.shutdown()
        self.central.shutdown()
        self.worker_pool.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main() -> None:
    app = BleAssistantApp()
    app.mainloop()
