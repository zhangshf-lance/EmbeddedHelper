from __future__ import annotations

import datetime as _dt
import json
import sys
import tkinter.font as tkfont
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
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
from .wifi_win import WifiManager, WifiNetwork


def _resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath(*parts)


class BleAssistantApp(tk.Tk):
    BG = "#eef3f8"
    SURFACE = "#ffffff"
    SURFACE_ALT = "#f7fafc"
    TEXT_BG = "#fbfdff"
    HEADER_BG = "#0b1220"
    HEADER_SUB = "#b7c4d7"
    ACCENT = "#0891b2"
    ACCENT_DARK = "#0e7490"
    ACCENT_SOFT = "#dff7fb"
    TEXT = "#162033"
    MUTED = "#64748b"
    BORDER = "#d5e0ea"
    DANGER = "#dc2626"

    def __init__(self) -> None:
        super().__init__()
        self.title("嵌入式调试助手")
        self.geometry("1280x860")
        self.minsize(1120, 740)
        self.configure(background=self.BG)
        self._set_app_icon()

        self.central = BleCentral(self.log, self._on_ble_notification)
        self.peripheral = BlePeripheral(self.log, self._on_peripheral_rx)
        self.wifi = WifiManager()
        self.serial_port: WindowsSerialPort | None = None
        self.ble_devices: list[BleDevice] = []
        self.ble_characteristics: list[GattCharacteristic] = []
        self.wifi_networks: list[WifiNetwork] = []
        self.serial_commands: list[dict[str, object]] = []
        self.serial_sequence_after_id: str | None = None
        self.serial_sequence_index = 0
        self.serial_sequence_items: list[dict[str, object]] = []
        self._loop_send_after_ids: dict[str, str | None] = {
            "ble": None,
            "peripheral": None,
            "serial": None,
        }
        self.worker_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ui-worker")

        self._build_style()
        self._build()
        self._refresh_serial_ports()
        self._show_backend_status()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_app_icon(self) -> None:
        icon_path = _resource_path("assets", "app_icon.ico")
        png_path = _resource_path("assets", "app_icon.png")
        try:
            if icon_path.exists():
                self.iconbitmap(default=str(icon_path))
            if png_path.exists():
                self._icon_photo = tk.PhotoImage(file=str(png_path))
                self.iconphoto(True, self._icon_photo)
        except tk.TclError:
            pass

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
        style.configure("Panel.TFrame", background=self.SURFACE)
        style.configure("Header.TFrame", background=self.HEADER_BG)
        style.configure("HeaderIcon.TLabel", background=self.HEADER_BG)
        style.configure(
            "HeaderBadge.TLabel",
            background="#122033",
            foreground="#a7f3d0",
            font=("Microsoft YaHei UI", 9, "bold"),
            padding=(10, 4),
        )
        style.configure(
            "HeaderTitle.TLabel",
            background=self.HEADER_BG,
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 17, "bold"),
        )
        style.configure(
            "HeaderSub.TLabel",
            background=self.HEADER_BG,
            foreground=self.HEADER_SUB,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure("TLabel", background=self.BG, foreground=self.TEXT)
        style.configure("Status.TLabel", background=self.BG, foreground=self.MUTED)
        style.configure(
            "TLabelframe",
            background=self.SURFACE,
            bordercolor=self.BORDER,
            relief="solid",
            borderwidth=1,
        )
        style.configure(
            "TLabelframe.Label",
            background=self.SURFACE,
            foreground=self.TEXT,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.configure("TNotebook", background=self.BG, borderwidth=0, tabmargins=(0, 0, 0, 0))
        style.configure(
            "TNotebook.Tab",
            padding=(20, 10),
            background="#dfe8f2",
            foreground="#334155",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", self.SURFACE), ("active", self.ACCENT_SOFT)],
            foreground=[("selected", self.ACCENT)],
        )
        style.configure("TButton", padding=(12, 7), font=("Microsoft YaHei UI", 9))
        style.configure("Accent.TButton", background=self.ACCENT, foreground="#ffffff")
        style.map(
            "Accent.TButton",
            background=[("active", self.ACCENT_DARK), ("disabled", "#9bd6e4")],
            foreground=[("disabled", "#eff6ff")],
        )
        style.configure("Danger.TButton", foreground=self.DANGER)
        style.configure(
            "TEntry",
            fieldbackground="#ffffff",
            bordercolor=self.BORDER,
            lightcolor=self.BORDER,
            darkcolor=self.BORDER,
            padding=5,
        )
        style.configure(
            "TCombobox",
            fieldbackground="#ffffff",
            bordercolor=self.BORDER,
            lightcolor=self.BORDER,
            darkcolor=self.BORDER,
            padding=4,
        )
        style.configure("TCheckbutton", background=self.BG, foreground=self.TEXT)
        style.configure(
            "Treeview",
            background=self.TEXT_BG,
            fieldbackground=self.TEXT_BG,
            foreground=self.TEXT,
            rowheight=26,
            bordercolor=self.BORDER,
            borderwidth=0,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#e6eef6",
            foreground="#334155",
            padding=(6, 5),
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", self.ACCENT)],
            foreground=[("selected", "#ffffff")],
        )

    def _build(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Header.TFrame")
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)
        if hasattr(self, "_icon_photo"):
            self._header_logo = self._icon_photo.subsample(5, 5)
            ttk.Label(header, image=self._header_logo, style="HeaderIcon.TLabel").grid(
                row=0, column=0, rowspan=2, sticky="w", padx=(20, 14), pady=14
            )
        ttk.Label(header, text="嵌入式调试助手", style="HeaderTitle.TLabel").grid(
            row=0, column=1, sticky="w", padx=(0, 18), pady=(16, 2)
        )
        ttk.Label(
            header,
            text="BLE 主设备、BLE GATT 从设备、串口、WiFi HOSTAP/STATION 一体化调试",
            style="HeaderSub.TLabel",
        ).grid(row=1, column=1, sticky="w", padx=(0, 18), pady=(0, 16))
        ttk.Label(header, text="BLE / Serial / WiFi", style="HeaderBadge.TLabel").grid(
            row=0, column=2, rowspan=2, sticky="e", padx=(0, 20), pady=18
        )

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=18, pady=18)

        self.ble_tab = ttk.Frame(notebook)
        self.peripheral_tab = ttk.Frame(notebook)
        self.serial_tab = ttk.Frame(notebook)
        self.wifi_tab = ttk.Frame(notebook)
        self.log_tab = ttk.Frame(notebook)

        notebook.add(self.ble_tab, text="BLE 主设备")
        notebook.add(self.peripheral_tab, text="BLE 从设备")
        notebook.add(self.serial_tab, text="串口通信")
        notebook.add(self.wifi_tab, text="WiFi 调试")
        notebook.add(self.log_tab, text="运行日志")

        self._build_ble_tab()
        self._build_peripheral_tab()
        self._build_serial_tab()
        self._build_wifi_tab()
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
        ttk.Button(char_frame, text="刷新特征", command=self._ble_refresh_characteristics).grid(
            row=0, column=2, padx=(0, 8), pady=8
        )

        options = ttk.Frame(right)
        options.grid(row=1, column=0, sticky="ew", pady=8)
        self.ble_send_hex = tk.BooleanVar(value=False)
        self.ble_recv_hex = tk.BooleanVar(value=False)
        self.ble_write_response = tk.BooleanVar(value=True)
        ttk.Checkbutton(options, text="发送HEX", variable=self.ble_send_hex).pack(side="left")
        ttk.Checkbutton(options, text="接收HEX", variable=self.ble_recv_hex).pack(side="left", padx=(8, 12))
        ttk.Checkbutton(options, text="响应写", variable=self.ble_write_response).pack(
            side="left", padx=(0, 12)
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
        ttk.Button(
            send_frame, text="清除发送", command=lambda: self._clear_entry(self.ble_send_text)
        ).grid(row=0, column=1, padx=(0, 8), pady=8)
        self.ble_loop_interval = tk.StringVar(value="1000")
        ble_loop = ttk.Frame(send_frame)
        ble_loop.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(ble_loop, text="循环间隔(ms)").pack(side="left")
        ttk.Entry(ble_loop, width=8, textvariable=self.ble_loop_interval).pack(
            side="left", padx=(6, 8)
        )
        ttk.Button(ble_loop, text="开始循环", command=lambda: self._start_loop_send("ble")).pack(
            side="left"
        )
        ttk.Button(ble_loop, text="停止循环", command=lambda: self._stop_loop_send("ble")).pack(
            side="left", padx=6
        )

        recv_frame = ttk.LabelFrame(right, text="接收 / 读取")
        recv_frame.grid(row=3, column=0, sticky="nsew", pady=(8, 0))
        recv_frame.columnconfigure(0, weight=1)
        recv_frame.rowconfigure(0, weight=1)
        self.ble_recv = ScrolledText(recv_frame, height=16, wrap="word")
        self.ble_recv.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        ttk.Button(
            recv_frame, text="清除接收", command=lambda: self._clear_text(self.ble_recv)
        ).grid(row=1, column=0, sticky="e", padx=8, pady=(0, 8))

    def _build_peripheral_tab(self) -> None:
        tab = self.peripheral_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        form = ttk.LabelFrame(tab, text="BLE GATT 从设备")
        form.grid(row=0, column=0, sticky="ew")
        form.columnconfigure(1, weight=1)
        self.peripheral_name = tk.StringVar(value="BLE_ZHANGSHF")
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
        self.peripheral_disconnect_button = ttk.Button(
            buttons, text="断开连接", command=self._peripheral_disconnect
        )
        self.peripheral_disconnect_button.pack(side="left", padx=6)
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
        ttk.Button(
            send, text="清除发送", command=lambda: self._clear_entry(self.peripheral_send_text)
        ).grid(row=0, column=2, padx=(0, 8), pady=8)
        self.peripheral_loop_interval = tk.StringVar(value="1000")
        peripheral_loop = ttk.Frame(send)
        peripheral_loop.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(peripheral_loop, text="循环间隔(ms)").pack(side="left")
        ttk.Entry(peripheral_loop, width=8, textvariable=self.peripheral_loop_interval).pack(
            side="left", padx=(6, 8)
        )
        ttk.Button(
            peripheral_loop, text="开始循环", command=lambda: self._start_loop_send("peripheral")
        ).pack(side="left")
        ttk.Button(
            peripheral_loop, text="停止循环", command=lambda: self._stop_loop_send("peripheral")
        ).pack(side="left", padx=6)
        recv = ttk.LabelFrame(io, text="主设备写入")
        recv.columnconfigure(0, weight=1)
        recv.rowconfigure(0, weight=1)
        self.peripheral_recv = ScrolledText(recv, height=12, wrap="word")
        self.peripheral_recv.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        ttk.Button(
            recv, text="清除接收", command=lambda: self._clear_text(self.peripheral_recv)
        ).grid(row=1, column=0, sticky="e", padx=8, pady=(0, 8))
        io.add(send, weight=0)
        io.add(recv, weight=1)

    def _build_serial_tab(self) -> None:
        tab = self.serial_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=2)
        tab.rowconfigure(4, weight=1)

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
        self.serial_send_hex = tk.BooleanVar(value=False)
        self.serial_recv_hex = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="发送HEX", variable=self.serial_send_hex).pack(side="left")
        ttk.Checkbutton(options, text="接收HEX", variable=self.serial_recv_hex).pack(side="left", padx=(8, 12))
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
        ttk.Button(
            terminal, text="清除接收", command=lambda: self._clear_text(self.serial_recv)
        ).grid(row=1, column=0, sticky="e", padx=8, pady=(0, 8))

        send = ttk.LabelFrame(tab, text="发送数据")
        send.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        send.columnconfigure(0, weight=1)
        self.serial_send_text = ttk.Entry(send)
        self.serial_send_text.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        self.serial_send_text.bind("<Return>", lambda _event: self._serial_send())
        ttk.Button(send, text="发送", command=self._serial_send).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(
            send, text="清除发送", command=lambda: self._clear_entry(self.serial_send_text)
        ).grid(row=0, column=2, padx=(0, 8), pady=8)
        self.serial_loop_interval = tk.StringVar(value="1000")
        serial_loop = ttk.Frame(send)
        serial_loop.grid(row=1, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 8))
        ttk.Label(serial_loop, text="循环间隔(ms)").pack(side="left")
        ttk.Entry(serial_loop, width=8, textvariable=self.serial_loop_interval).pack(
            side="left", padx=(6, 8)
        )
        ttk.Button(
            serial_loop, text="开始循环", command=lambda: self._start_loop_send("serial")
        ).pack(side="left")
        ttk.Button(
            serial_loop, text="停止循环", command=lambda: self._stop_loop_send("serial")
        ).pack(side="left", padx=6)

        multi = ttk.LabelFrame(tab, text="多条字符串顺序发送")
        multi.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        multi.columnconfigure(0, weight=1)
        multi.rowconfigure(0, weight=1)

        columns = ("enabled", "order", "command", "comment", "delay")
        self.serial_command_tree = ttk.Treeview(
            multi,
            columns=columns,
            show="headings",
            height=8,
            selectmode="browse",
        )
        headings = {
            "enabled": "启用",
            "order": "顺序",
            "command": "字符串",
            "comment": "注释",
            "delay": "延时(ms)",
        }
        widths = {
            "enabled": 54,
            "order": 54,
            "command": 420,
            "comment": 220,
            "delay": 80,
        }
        for column in columns:
            self.serial_command_tree.heading(column, text=headings[column])
            self.serial_command_tree.column(
                column,
                width=widths[column],
                minwidth=48,
                stretch=column in {"command", "comment"},
                anchor="w" if column in {"command", "comment"} else "center",
            )
        self.serial_command_tree.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.serial_command_tree.tag_configure("odd", background="#ffffff")
        self.serial_command_tree.tag_configure("even", background=self.SURFACE_ALT)
        self.serial_command_tree.bind("<<TreeviewSelect>>", self._serial_command_selected)
        self.serial_command_tree.bind("<Double-Button-1>", lambda _event: self._serial_send_selected_command())
        self.serial_command_tree.bind("<space>", lambda _event: self._serial_toggle_selected_command())
        scrollbar = ttk.Scrollbar(multi, orient="vertical", command=self.serial_command_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns", pady=8)
        self.serial_command_tree.configure(yscrollcommand=scrollbar.set)

        editor = ttk.Frame(multi)
        editor.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        editor.columnconfigure(2, weight=3)
        editor.columnconfigure(4, weight=2)
        self.serial_cmd_enabled = tk.BooleanVar(value=True)
        self.serial_cmd_text = tk.StringVar()
        self.serial_cmd_comment = tk.StringVar()
        self.serial_cmd_delay = tk.StringVar(value="1000")
        ttk.Checkbutton(editor, text="启用", variable=self.serial_cmd_enabled).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Label(editor, text="字符串").grid(row=0, column=1, sticky="w")
        ttk.Entry(editor, textvariable=self.serial_cmd_text).grid(
            row=0, column=2, sticky="ew", padx=(6, 10)
        )
        ttk.Label(editor, text="注释").grid(row=0, column=3, sticky="w")
        ttk.Entry(editor, textvariable=self.serial_cmd_comment).grid(
            row=0, column=4, sticky="ew", padx=(6, 10)
        )
        ttk.Label(editor, text="延时").grid(row=0, column=5, sticky="w")
        ttk.Entry(editor, width=8, textvariable=self.serial_cmd_delay).grid(
            row=0, column=6, padx=(6, 10)
        )

        buttons = ttk.Frame(multi)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=(0, 8))
        ttk.Button(buttons, text="添加", command=self._serial_add_command).pack(side="left")
        ttk.Button(buttons, text="更新", command=self._serial_update_command).pack(side="left", padx=6)
        ttk.Button(buttons, text="删除", command=self._serial_delete_command).pack(side="left")
        ttk.Button(buttons, text="上移", command=lambda: self._serial_move_command(-1)).pack(
            side="left", padx=(12, 6)
        )
        ttk.Button(buttons, text="下移", command=lambda: self._serial_move_command(1)).pack(side="left")
        ttk.Button(buttons, text="发送选中", command=self._serial_send_selected_command).pack(
            side="left", padx=(12, 6)
        )
        self.serial_sequence_start_button = ttk.Button(
            buttons,
            text="顺序发送",
            command=self._serial_start_sequence,
            style="Accent.TButton",
        )
        self.serial_sequence_start_button.pack(side="left")
        self.serial_sequence_stop_button = ttk.Button(
            buttons, text="停止顺序", command=self._serial_stop_sequence
        )
        self.serial_sequence_stop_button.pack(side="left", padx=6)
        ttk.Button(buttons, text="保存", command=self._save_serial_commands).pack(
            side="right", padx=(6, 0)
        )
        ttk.Button(buttons, text="载入", command=self._load_serial_commands).pack(side="right")

        self._load_serial_commands(show_log=False)

    def _build_wifi_tab(self) -> None:
        tab = self.wifi_tab
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        top = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        top.grid(row=0, column=0, sticky="ew")

        hostap = ttk.LabelFrame(top, text="HOSTAP")
        hostap.columnconfigure(1, weight=1)
        self.hostap_ssid = tk.StringVar(value="EmbeddedDebugAP")
        self.hostap_password = tk.StringVar(value="12345678")
        ttk.Label(hostap, text="SSID").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(hostap, textvariable=self.hostap_ssid).grid(
            row=0, column=1, sticky="ew", padx=(0, 8), pady=6
        )
        ttk.Label(hostap, text="密码").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(hostap, textvariable=self.hostap_password, show="*").grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=6
        )
        hostap_buttons = ttk.Frame(hostap)
        hostap_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        self.hostap_start_button = ttk.Button(
            hostap_buttons,
            text="启动 HOSTAP",
            command=self._wifi_hostap_start,
            style="Accent.TButton",
        )
        self.hostap_start_button.pack(side="left")
        self.hostap_stop_button = ttk.Button(
            hostap_buttons, text="停止", command=self._wifi_hostap_stop
        )
        self.hostap_stop_button.pack(side="left", padx=6)
        self.hostap_status_button = ttk.Button(
            hostap_buttons, text="状态", command=self._wifi_hostap_status
        )
        self.hostap_status_button.pack(side="left")
        self.hostap_status = ttk.Label(hostap_buttons, text="未启动", style="Status.TLabel")
        self.hostap_status.pack(side="left", padx=12)

        station = ttk.LabelFrame(top, text="STATION")
        station.columnconfigure(1, weight=1)
        self.station_ssid = tk.StringVar()
        self.station_password = tk.StringVar()
        ttk.Label(station, text="SSID").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(station, textvariable=self.station_ssid).grid(
            row=0, column=1, sticky="ew", padx=(0, 8), pady=6
        )
        ttk.Label(station, text="密码").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(station, textvariable=self.station_password, show="*").grid(
            row=1, column=1, sticky="ew", padx=(0, 8), pady=6
        )
        station_buttons = ttk.Frame(station)
        station_buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        self.station_scan_button = ttk.Button(
            station_buttons, text="扫描", command=self._wifi_station_scan, style="Accent.TButton"
        )
        self.station_scan_button.pack(side="left")
        self.station_connect_button = ttk.Button(
            station_buttons, text="连接", command=self._wifi_station_connect, style="Accent.TButton"
        )
        self.station_connect_button.pack(side="left", padx=6)
        self.station_disconnect_button = ttk.Button(
            station_buttons, text="断开", command=self._wifi_station_disconnect
        )
        self.station_disconnect_button.pack(side="left")
        self.station_status_button = ttk.Button(
            station_buttons, text="状态", command=self._wifi_station_status
        )
        self.station_status_button.pack(side="left", padx=6)
        self.station_status = ttk.Label(station_buttons, text="未连接", style="Status.TLabel")
        self.station_status.pack(side="left", padx=12)

        top.add(hostap, weight=1)
        top.add(station, weight=1)

        lower = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        lower.grid(row=1, column=0, sticky="nsew", pady=(8, 0))

        networks = ttk.LabelFrame(lower, text="STATION 扫描结果")
        networks.rowconfigure(0, weight=1)
        networks.columnconfigure(0, weight=1)
        self.wifi_network_list = tk.Listbox(
            networks,
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
        self.wifi_network_list.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.wifi_network_list.bind("<<ListboxSelect>>", self._wifi_show_selected_network)
        self.wifi_network_list.bind("<Double-Button-1>", lambda _event: self._wifi_use_network())
        ttk.Button(networks, text="使用选中 SSID", command=self._wifi_use_network).grid(
            row=1, column=0, sticky="e", padx=8, pady=(0, 8)
        )

        output = ttk.LabelFrame(lower, text="WiFi 输出")
        output.rowconfigure(0, weight=1)
        output.columnconfigure(0, weight=1)
        self.wifi_output = ScrolledText(output, height=16, wrap="word")
        self.wifi_output.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        ttk.Button(output, text="清除输出", command=lambda: self._clear_text(self.wifi_output)).grid(
            row=1, column=0, sticky="e", padx=8, pady=(0, 8)
        )

        lower.add(networks, weight=1)
        lower.add(output, weight=2)

    def _build_log_tab(self) -> None:
        self.log_tab.columnconfigure(0, weight=1)
        self.log_tab.rowconfigure(1, weight=1)
        toolbar = ttk.Frame(self.log_tab)
        toolbar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        ttk.Button(toolbar, text="清除日志", command=lambda: self._clear_text(self.log_text)).pack(
            side="right"
        )
        self.log_text = ScrolledText(self.log_tab, wrap="word")
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)

    def _style_text_widgets(self) -> None:
        for widget in (
            self.ble_recv,
            self.peripheral_recv,
            self.serial_recv,
            self.wifi_output,
            self.log_text,
        ):
            widget.configure(
                background=self.TEXT_BG,
                foreground=self.TEXT,
                insertbackground=self.ACCENT_DARK,
                borderwidth=1,
                relief="solid",
                highlightthickness=1,
                highlightbackground=self.BORDER,
                highlightcolor=self.ACCENT,
                padx=12,
                pady=10,
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

    def _clear_text(self, widget: ScrolledText) -> None:
        widget.delete("1.0", "end")

    def _clear_entry(self, widget) -> None:
        widget.delete(0, "end")

    def _loop_interval(self, channel: str) -> int | None:
        variables = {
            "ble": self.ble_loop_interval,
            "peripheral": self.peripheral_loop_interval,
            "serial": self.serial_loop_interval,
        }
        try:
            interval = int(variables[channel].get())
        except ValueError:
            self._show_error("循环发送间隔错误", ValueError("请输入整数毫秒数"))
            return None
        if interval < 50:
            self._show_error("循环发送间隔错误", ValueError("间隔不能小于 50 ms"))
            return None
        return interval

    def _start_loop_send(self, channel: str) -> None:
        if self._loop_send_after_ids.get(channel) is not None:
            self.log(f"{self._loop_send_name(channel)}循环发送已在运行")
            return
        interval = self._loop_interval(channel)
        if interval is None:
            return
        self.log(f"{self._loop_send_name(channel)}开始循环发送，间隔 {interval} ms")
        self._run_loop_send(channel)

    def _stop_loop_send(self, channel: str, log_message: bool = True) -> None:
        after_id = self._loop_send_after_ids.get(channel)
        if after_id is not None:
            self.after_cancel(after_id)
            self._loop_send_after_ids[channel] = None
            if log_message:
                self.log(f"{self._loop_send_name(channel)}已停止循环发送")

    def _run_loop_send(self, channel: str) -> None:
        if not self._send_once(channel, quiet=True):
            self._loop_send_after_ids[channel] = None
            self.log(f"{self._loop_send_name(channel)}循环发送已停止")
            return
        interval = self._loop_interval(channel)
        if interval is None:
            self._loop_send_after_ids[channel] = None
            return
        self._loop_send_after_ids[channel] = self.after(
            interval, lambda: self._run_loop_send(channel)
        )

    def _send_once(self, channel: str, quiet: bool = False) -> bool:
        if channel == "ble":
            return self._ble_write_once(quiet)
        if channel == "peripheral":
            return self._peripheral_notify_once(quiet)
        if channel == "serial":
            return self._serial_send_once(quiet)
        return False

    def _loop_send_name(self, channel: str) -> str:
        return {
            "ble": "BLE 主设备",
            "peripheral": "BLE 从设备",
            "serial": "串口",
        }.get(channel, channel)

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
            f"{char.uuid} | {','.join(char.properties)} | Service {char.service_uuid}"
            for char in characteristics
        ]
        self.ble_char_combo.config(values=values)
        if values:
            self.ble_char_combo.current(0)
        self.ble_status.config(text=f"已连接，{len(values)} 个特征")

    def _ble_refresh_characteristics(self) -> None:
        self._stop_loop_send("ble", False)
        self.ble_status.config(text="正在刷新 GATT 特征...")
        future = self.central.submit(self.central.refresh_characteristics())
        self._future_result(future, self._ble_connected, "BLE 刷新特征失败")

    def _ble_disconnect(self) -> None:
        self._stop_loop_send("ble", False)
        future = self.central.submit(self.central.disconnect())
        self._future_result(future, lambda _result: self.ble_status.config(text="已断开"), "BLE 断开失败")

    def _selected_char_uuid(self, quiet: bool = False) -> str | None:
        index = self.ble_char_combo.current()
        if index < 0 or index >= len(self.ble_characteristics):
            if quiet:
                self.log("BLE 主设备循环发送停止：请先选择 GATT 特征")
                return None
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
            data = encode_payload(self.ble_send_text.get(), self.ble_send_hex.get(), "none")
        except ValueError as exc:
            self._show_error("BLE 数据格式错误", exc)
            return
        future = self.central.submit(
            self.central.write(char_uuid, data, response=self.ble_write_response.get())
        )
        self._future_result(future, lambda _result: self.log(f"BLE 写入 {len(data)} 字节"), "BLE 写入失败")

    def _ble_write_once(self, quiet: bool = False) -> bool:
        char_uuid = self._selected_char_uuid(quiet)
        if not char_uuid:
            return False
        try:
            data = encode_payload(self.ble_send_text.get(), self.ble_send_hex.get(), "none")
        except ValueError as exc:
            if quiet:
                self.log(f"BLE 主设备循环发送停止：数据格式错误，{exc}")
            else:
                self._show_error("BLE 数据格式错误", exc)
            return False
        future = self.central.submit(
            self.central.write(char_uuid, data, response=self.ble_write_response.get())
        )
        self._future_result(future, lambda _result: self.log(f"BLE 写入 {len(data)} 字节"), "BLE 写入失败")
        return True

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
        body = format_payload(data, self.ble_recv_hex.get())
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
        self._stop_loop_send("peripheral", False)
        self._run_peripheral_task(
            "正在停止从设备...",
            self.peripheral.stop,
            self._apply_peripheral_status,
        )

    def _peripheral_disconnect(self) -> None:
        self._run_peripheral_task(
            "正在断开连接...",
            self.peripheral.disconnect,
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

    def _peripheral_notify_once(self, quiet: bool = False) -> bool:
        if self.peripheral_notify_button.cget("state") == "disabled":
            return True
        try:
            data = encode_payload(self.peripheral_send_text.get(), self.peripheral_send_hex.get(), "none")
        except ValueError as exc:
            if quiet:
                self.log(f"BLE 从设备循环发送停止：数据格式错误，{exc}")
            else:
                self._show_error("从设备数据格式错误", exc)
            return False
        self._run_peripheral_task(
            "正在发送通知...",
            lambda: self.peripheral.notify(data),
            self._apply_peripheral_status,
        )
        return True

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
            self.peripheral_disconnect_button,
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

    def _wifi_hostap_start(self) -> None:
        ssid = self.hostap_ssid.get()
        password = self.hostap_password.get()
        self._run_wifi_task(
            "HOSTAP 启动中...",
            lambda: self.wifi.hostap_start(ssid, password),
            lambda output: self._wifi_task_success("HOSTAP 已启动", output),
        )

    def _wifi_hostap_stop(self) -> None:
        self._run_wifi_task(
            "HOSTAP 停止中...",
            self.wifi.hostap_stop,
            lambda output: self._wifi_task_success("HOSTAP 已停止", output),
        )

    def _wifi_hostap_status(self) -> None:
        self._run_wifi_task(
            "HOSTAP 状态查询中...",
            self.wifi.hostap_status,
            lambda output: self._wifi_task_success("HOSTAP 状态已更新", output),
        )

    def _wifi_station_scan(self) -> None:
        self._run_wifi_task(
            "STATION 扫描中...",
            self.wifi.station_scan,
            self._wifi_station_scan_done,
        )

    def _wifi_station_connect(self) -> None:
        ssid = self.station_ssid.get()
        password = self.station_password.get()
        self._run_wifi_task(
            "STATION 连接中...",
            lambda: self.wifi.station_connect(ssid, password),
            lambda output: self._wifi_task_success("STATION 已发起连接", output),
        )

    def _wifi_station_disconnect(self) -> None:
        self._run_wifi_task(
            "STATION 断开中...",
            self.wifi.station_disconnect,
            lambda output: self._wifi_task_success("STATION 已断开", output),
        )

    def _wifi_station_status(self) -> None:
        self._run_wifi_task(
            "STATION 状态查询中...",
            self.wifi.station_status,
            lambda output: self._wifi_task_success("STATION 状态已更新", output),
        )

    def _wifi_use_network(self) -> None:
        network = self._selected_wifi_network()
        if network is None:
            messagebox.showinfo("选择 WiFi", "请先选择一个 WiFi 网络")
            return
        self.station_ssid.set(network.ssid)
        self._show_wifi_network_details(network)

    def _wifi_show_selected_network(self, _event=None) -> None:
        network = self._selected_wifi_network()
        if network is not None:
            self._show_wifi_network_details(network)

    def _selected_wifi_network(self) -> WifiNetwork | None:
        selection = self.wifi_network_list.curselection()
        if not selection:
            return None
        index = selection[0]
        if index < 0 or index >= len(self.wifi_networks):
            return None
        return self.wifi_networks[index]

    def _run_wifi_task(self, busy_text: str, action, callback) -> None:
        self._set_wifi_busy(True, busy_text)
        future = self.worker_pool.submit(action)
        future.add_done_callback(
            lambda done_future: self.after(0, lambda: self._wifi_task_done(done_future, callback))
        )

    def _wifi_task_done(self, future: Future, callback) -> None:
        self._set_wifi_busy(False)
        try:
            result = future.result()
        except Exception as exc:
            self._show_error("WiFi 操作失败", exc)
            return
        callback(result)

    def _wifi_station_scan_done(self, result) -> None:
        networks, _output = result
        self.wifi_networks = networks
        self.wifi_network_list.delete(0, "end")
        for network in networks:
            meta = " | ".join(
                item
                for item in (
                    network.signal,
                    network.authentication,
                    network.encryption,
                    f"BSSID {network.bssid_count}" if network.bssid_count else "",
                )
                if item
            )
            suffix = f" | {meta}" if meta else ""
            self.wifi_network_list.insert("end", f"{network.ssid}{suffix}")
        self.station_status.config(text=f"发现 {len(networks)} 个网络")
        self._clear_text(self.wifi_output)
        if networks:
            self.wifi_network_list.selection_set(0)
            self.wifi_network_list.activate(0)
            self._show_wifi_network_details(networks[0])
        self.log(f"WiFi STATION 扫描完成：{len(networks)} 个网络")

    def _wifi_task_success(self, status: str, output: str) -> None:
        if status.startswith("HOSTAP"):
            self.hostap_status.config(text=status)
        elif status.startswith("STATION"):
            self.station_status.config(text=status)
        if output:
            first_line = output.splitlines()[0] if output.splitlines() else output
            self.log(f"{status}: {first_line}")
        self.log(status)

    def _show_wifi_network_details(self, network: WifiNetwork) -> None:
        self._clear_text(self.wifi_output)
        self._append_text(self.wifi_output, self.wifi.format_network_details(network) + "\n")

    def _set_wifi_busy(self, busy: bool, text: str | None = None) -> None:
        state = "disabled" if busy else "normal"
        for button in (
            self.hostap_start_button,
            self.hostap_stop_button,
            self.hostap_status_button,
            self.station_scan_button,
            self.station_connect_button,
            self.station_disconnect_button,
            self.station_status_button,
        ):
            button.config(state=state)
        if text:
            if text.startswith("HOSTAP"):
                self.hostap_status.config(text=text)
            elif text.startswith("STATION"):
                self.station_status.config(text=text)

    def _serial_command_config_path(self) -> Path:
        folder = Path.home() / "AppData" / "Roaming" / "EmbeddedDebugAssistant"
        return folder / "serial_commands.json"

    def _refresh_serial_command_tree(self, select_index: int | None = None) -> None:
        for item in self.serial_command_tree.get_children():
            self.serial_command_tree.delete(item)
        for index, command in enumerate(self.serial_commands, start=1):
            self.serial_command_tree.insert(
                "",
                "end",
                values=(
                    "√" if command.get("enabled", True) else "",
                    index,
                    str(command.get("command", "")),
                    str(command.get("comment", "")),
                    int(command.get("delay_ms", 1000)),
                ),
                tags=("even" if index % 2 == 0 else "odd",),
            )
        if select_index is not None and self.serial_commands:
            select_index = max(0, min(select_index, len(self.serial_commands) - 1))
            item = self.serial_command_tree.get_children()[select_index]
            self.serial_command_tree.selection_set(item)
            self.serial_command_tree.focus(item)
            self.serial_command_tree.see(item)

    def _selected_serial_command_index(self) -> int | None:
        selection = self.serial_command_tree.selection()
        if not selection:
            return None
        children = self.serial_command_tree.get_children()
        try:
            return children.index(selection[0])
        except ValueError:
            return None

    def _serial_command_selected(self, _event=None) -> None:
        index = self._selected_serial_command_index()
        if index is None:
            return
        command = self.serial_commands[index]
        self.serial_cmd_enabled.set(bool(command.get("enabled", True)))
        self.serial_cmd_text.set(str(command.get("command", "")))
        self.serial_cmd_comment.set(str(command.get("comment", "")))
        self.serial_cmd_delay.set(str(int(command.get("delay_ms", 1000))))

    def _serial_command_from_editor(self) -> dict[str, object] | None:
        text = self.serial_cmd_text.get()
        if not text:
            self._show_error("串口多条发送", ValueError("字符串不能为空"))
            return None
        try:
            delay_ms = int(self.serial_cmd_delay.get())
        except ValueError:
            self._show_error("串口多条发送", ValueError("延时必须是整数毫秒"))
            return None
        if delay_ms < 0:
            self._show_error("串口多条发送", ValueError("延时不能小于 0 ms"))
            return None
        return {
            "enabled": self.serial_cmd_enabled.get(),
            "command": text,
            "comment": self.serial_cmd_comment.get(),
            "delay_ms": delay_ms,
        }

    def _serial_add_command(self) -> None:
        command = self._serial_command_from_editor()
        if command is None:
            return
        self.serial_commands.append(command)
        self._refresh_serial_command_tree(len(self.serial_commands) - 1)
        self._save_serial_commands(show_log=False)

    def _serial_update_command(self) -> None:
        index = self._selected_serial_command_index()
        if index is None:
            messagebox.showinfo("串口多条发送", "请先选择一条记录")
            return
        command = self._serial_command_from_editor()
        if command is None:
            return
        self.serial_commands[index] = command
        self._refresh_serial_command_tree(index)
        self._save_serial_commands(show_log=False)

    def _serial_delete_command(self) -> None:
        index = self._selected_serial_command_index()
        if index is None:
            messagebox.showinfo("串口多条发送", "请先选择一条记录")
            return
        del self.serial_commands[index]
        self._refresh_serial_command_tree(index)
        self._save_serial_commands(show_log=False)

    def _serial_move_command(self, offset: int) -> None:
        index = self._selected_serial_command_index()
        if index is None:
            messagebox.showinfo("串口多条发送", "请先选择一条记录")
            return
        target = index + offset
        if target < 0 or target >= len(self.serial_commands):
            return
        self.serial_commands[index], self.serial_commands[target] = (
            self.serial_commands[target],
            self.serial_commands[index],
        )
        self._refresh_serial_command_tree(target)
        self._save_serial_commands(show_log=False)

    def _serial_toggle_selected_command(self) -> str:
        index = self._selected_serial_command_index()
        if index is None:
            return "break"
        self.serial_commands[index]["enabled"] = not bool(
            self.serial_commands[index].get("enabled", True)
        )
        self._refresh_serial_command_tree(index)
        self._save_serial_commands(show_log=False)
        return "break"

    def _save_serial_commands(self, show_log: bool = True) -> None:
        path = self._serial_command_config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.serial_commands, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if show_log:
            self.log(f"串口多条发送配置已保存：{path}")

    def _load_serial_commands(self, show_log: bool = True) -> None:
        path = self._serial_command_config_path()
        if not path.exists():
            self.serial_commands = []
            self._refresh_serial_command_tree()
            return
        try:
            raw_commands = json.loads(path.read_text(encoding="utf-8"))
            self.serial_commands = [
                {
                    "enabled": bool(item.get("enabled", True)),
                    "command": str(item.get("command", "")),
                    "comment": str(item.get("comment", "")),
                    "delay_ms": max(0, int(item.get("delay_ms", 1000))),
                }
                for item in raw_commands
                if isinstance(item, dict)
            ]
        except Exception as exc:
            if hasattr(self, "log_text"):
                self._show_error("串口多条发送载入失败", exc)
            else:
                messagebox.showerror("串口多条发送载入失败", str(exc))
            self.serial_commands = []
        self._refresh_serial_command_tree(0 if self.serial_commands else None)
        if show_log:
            self.log(f"串口多条发送配置已载入：{path}")

    def _serial_send_selected_command(self) -> None:
        index = self._selected_serial_command_index()
        if index is None:
            messagebox.showinfo("串口多条发送", "请先选择一条记录")
            return
        self._serial_send_command_entry(self.serial_commands[index])

    def _serial_send_command_entry(self, command: dict[str, object]) -> bool:
        if not self.serial_port:
            messagebox.showinfo("串口未打开", "请先打开串口")
            return False
        text = str(command.get("command", ""))
        try:
            data = encode_payload(text, False, self.serial_line_ending.get())
            count = self.serial_port.write(data)
        except Exception as exc:
            self._show_error("串口多条发送失败", exc)
            return False
        comment = str(command.get("comment", "")).strip()
        suffix = f"（{comment}）" if comment else ""
        self.log(f"串口多条发送：{text}{suffix}，{count} 字节")
        return True

    def _serial_start_sequence(self) -> None:
        if self.serial_sequence_after_id is not None:
            self.log("串口顺序发送已在运行")
            return
        if not self.serial_port:
            messagebox.showinfo("串口未打开", "请先打开串口")
            return
        self.serial_sequence_items = [
            command
            for command in self.serial_commands
            if command.get("enabled", True) and str(command.get("command", ""))
        ]
        if not self.serial_sequence_items:
            messagebox.showinfo("串口多条发送", "没有启用的字符串")
            return
        self.serial_sequence_index = 0
        self.serial_sequence_start_button.config(state="disabled")
        self.log(f"串口顺序发送开始：{len(self.serial_sequence_items)} 条")
        self._serial_sequence_next()

    def _serial_sequence_next(self) -> None:
        if self.serial_sequence_index >= len(self.serial_sequence_items):
            self.serial_sequence_after_id = None
            self.serial_sequence_start_button.config(state="normal")
            self.log("串口顺序发送完成")
            return
        command = self.serial_sequence_items[self.serial_sequence_index]
        if not self._serial_send_command_entry(command):
            self._serial_stop_sequence("串口顺序发送已停止")
            return
        self.serial_sequence_index += 1
        if self.serial_sequence_index >= len(self.serial_sequence_items):
            self.serial_sequence_after_id = self.after(1, self._serial_sequence_next)
            return
        delay_ms = int(command.get("delay_ms", 1000))
        self.serial_sequence_after_id = self.after(delay_ms, self._serial_sequence_next)

    def _serial_stop_sequence(self, message: str = "串口顺序发送已停止") -> None:
        was_running = self.serial_sequence_after_id is not None or bool(self.serial_sequence_items)
        if self.serial_sequence_after_id is not None:
            self.after_cancel(self.serial_sequence_after_id)
            self.serial_sequence_after_id = None
        self.serial_sequence_start_button.config(state="normal")
        self.serial_sequence_items = []
        self.serial_sequence_index = 0
        if was_running:
            self.log(message)

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
        self._stop_loop_send("serial", False)
        self._serial_stop_sequence("串口顺序发送已停止")
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
                self.serial_send_hex.get(),
                self.serial_line_ending.get(),
            )
            count = self.serial_port.write(data)
        except Exception as exc:
            self._show_error("串口发送失败", exc)
            return
        self.log(f"串口发送 {count} 字节")

    def _serial_send_once(self, quiet: bool = False) -> bool:
        if not self.serial_port:
            if quiet:
                self.log("串口循环发送停止：请先打开串口")
            else:
                messagebox.showinfo("串口未打开", "请先打开串口")
            return False
        try:
            data = encode_payload(
                self.serial_send_text.get(),
                self.serial_send_hex.get(),
                self.serial_line_ending.get(),
            )
            count = self.serial_port.write(data)
        except Exception as exc:
            if quiet:
                self.log(f"串口循环发送停止：发送失败，{exc}")
            else:
                self._show_error("串口发送失败", exc)
            return False
        self.log(f"串口发送 {count} 字节")
        return True

    def _on_serial_data(self, data: bytes) -> None:
        body = format_payload(data, self.serial_recv_hex.get())
        self.after(0, lambda: self._append_text(self.serial_recv, body))

    def _on_serial_error(self, exc: Exception) -> None:
        self.after(0, lambda: self._show_error("串口读取失败", exc))

    def _on_close(self) -> None:
        for channel in tuple(self._loop_send_after_ids):
            self._stop_loop_send(channel, False)
        self._serial_close()
        self.peripheral.shutdown()
        self.central.shutdown()
        self.worker_pool.shutdown(wait=False, cancel_futures=True)
        self.destroy()


def main() -> None:
    app = BleAssistantApp()
    app.mainloop()
