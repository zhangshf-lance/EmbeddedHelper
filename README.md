# Windows 蓝牙调试助手

这是一个 Windows 桌面调试工具，包含三个工作区：

- **BLE 主设备**：扫描 BLE 设备、连接、枚举 GATT 特征、读/写特征、订阅 Notify。
- **BLE 从设备**：创建 Nordic UART 风格的 GATT Server，支持 RX 写入和 TX Notify，可分别选择发送/接收为字符串或 HEX。
- **串口通信**：打开 COM 口、收发文本或 HEX 数据，支持普通串口和系统映射出来的蓝牙 SPP 虚拟串口。

## 运行

```bat
run.bat
```

如果希望外部扫描列表里的名称也匹配界面填写的“系统蓝牙名称”，请使用管理员方式启动：

```bat
run_admin.bat
```

已打包版本位于：

```text
dist\BLEAssistant.exe
```

打包后的 EXE 需要管理员方式启动时可运行：

```bat
run_exe_admin.bat
```

需要安装带 Tcl/Tk 的 Windows Python 3.11+。如果 `run.bat` 无法启动，请先修复系统 Python 或直接使用完整路径运行：

```bat
python -m pip install -r requirements.txt
python app.py
```

> 串口功能不需要第三方库。BLE 主设备需要 `bleak`。BLE 从设备使用 `bless`。当前 requirements 显式固定了 Windows 可用组合，并使用 `--no-deps` 避免 `bless` 的依赖声明把 BLE 包降级。电脑蓝牙适配器仍必须支持 BLE 广播/GATT Server。

## 使用建议

1. 先打开“串口通信”，点“刷新”查看 COM 口。蓝牙经典 SPP 配对后通常会出现在这里。
2. 打开“BLE 主设备”，点“扫描”，选择设备后“连接”，再选择特征进行读写或订阅通知。
3. “BLE 从设备”使用默认 Nordic UART UUID：
   - Service：`6E400001-B5A3-F393-E0A9-E50E24DCCA9E`
   - RX 写入：`6E400002-B5A3-F393-E0A9-E50E24DCCA9E`
   - TX 通知：`6E400003-B5A3-F393-E0A9-E50E24DCCA9E`
4. 从设备页里的“发送HEX”和“接收HEX”是独立开关。发送 HEX 时可输入 `01 02 FF` 或 `0102FF`；不勾选时按 UTF-8 字符串发送。接收 HEX 只影响显示格式。

## 目录

```text
app.py                         程序入口
run.bat                        Windows 启动脚本
requirements.txt               BLE 依赖
ble_assistant/ui.py            Tkinter 桌面界面
ble_assistant/ble_central.py   BLE 主设备后端
ble_assistant/ble_peripheral.py BLE 从设备后端入口
ble_assistant/serial_win.py    Windows 串口后端
pysetupdi.py                   bless 在 Windows 下需要的蓝牙适配器枚举兼容层
```

## 注意

Windows 上 BLE “从设备/GATT Server”比 BLE 主设备更受系统版本、蓝牙驱动和 Python BLE 库影响。如果目标是调试蓝牙串口模块，优先使用系统配对后生成的 SPP COM 口；如果目标是调试 BLE 外设，优先使用“BLE 主设备”页。

外部设备扫描从设备时，建议在扫描工具里开启“显示无名称设备”，并按 Service UUID `6E400001-B5A3-F393-E0A9-E50E24DCCA9E` 过滤。Windows GATT Server 通常使用系统蓝牙适配器名称；工具会尝试把系统蓝牙名称改成界面填写的名称，但这通常需要管理员权限，并可能短暂重启蓝牙适配器。
