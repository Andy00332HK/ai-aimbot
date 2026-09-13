"""滑鼠控制:雙後端注入工廠(仿 capture.py 的後端模式)。

  - SendInput（Windows API）：標準注入，多數遊戲可直接接收，零額外依賴
  - Interception（驅動級）：以偵測到的真實滑鼠裝置身分送出位移，
    給「過濾軟體注入輸入」的遊戲引擎用（RawInput 只認 hDevice != NULL）。
    需先安裝 Interception 驅動（官方 release 的 install.bat + 重新開機），
    並 pip install interception-python pywin32。

兩種後端都只在 engine 執行緒中使用。
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

_USER32 = ctypes.WinDLL("user32", use_last_error=True)

# ── SendInput 結構定義 ──
MOUSEEVENTF_MOVE = 0x0001
INPUT_MOUSE = 0

_LONG = ctypes.c_long
_ULONG = ctypes.c_ulong


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", _LONG),
        ("dy", _LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def _sendinput_move(dx: int, dy: int) -> None:
    inp = _INPUT(type=INPUT_MOUSE)
    inp.mi = _MOUSEINPUT(
        dx=dx,
        dy=dy,
        mouseData=0,
        dwFlags=MOUSEEVENTF_MOVE,
        time=0,
        dwExtraInfo=None,
    )
    _USER32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))


class _MouseBase:
    """統一介面：move_relative() 以整數滑格（mickey）相對移動。"""

    backend_name = "base"

    def move_relative(self, dx: float, dy: float) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SendInputMouse(_MouseBase):
    """Windows SendInput 相對移動（標準注入／相容備援）。

    實際位移會受 Windows「加強指標精準度」與遊戲內靈敏度影響，
    由面板的 sensitivity 倍率校正。
    """

    backend_name = "SendInput"

    def move_relative(self, dx: float, dy: float) -> None:
        idx = int(round(dx))
        idy = int(round(dy))
        if idx == 0 and idy == 0:
            return
        _sendinput_move(idx, idy)


class InterceptionMouse(_MouseBase):
    """Interception 驅動級注入：以真實硬體裝置身分送出相對位移。

    繞過兩類阻擋：
      - UIPI：遊戲以管理員執行時，低權限程序的 SendInput 會被 Windows 靜默丟棄
      - 引擎過濾：部分引擎的 RawInput 只收 hDevice != NULL 的硬體事件
    """

    backend_name = "Interception"

    def __init__(self) -> None:
        from interception import Interception, MouseFlag, MouseStroke

        self._stroke = MouseStroke
        self._flag = MouseFlag.MOUSE_MOVE_RELATIVE
        self._ctx = Interception()
        if not self._ctx.valid:
            raise RuntimeError("Interception 驅動未安裝（安裝後需重新開機）")
        dev = next((n for n in range(10, 20)
                    if self._ctx.devices[n].get_HWID() is not None), None)
        if dev is None:
            raise RuntimeError("Interception 找不到已連接的滑鼠裝置")
        self._dev = dev
        self._ctx.mouse = dev

    def move_relative(self, dx: float, dy: float) -> None:
        idx = int(round(dx))
        idy = int(round(dy))
        if idx == 0 and idy == 0:
            return
        self._ctx.send(self._dev, self._stroke(self._flag, 0, 0, idx, idy))

    def close(self) -> None:
        try:
            self._ctx.destroy()
        except Exception:
            pass


def create_mouse(preferred: str = "auto") -> _MouseBase:
    """依設定建立注入器；Interception 不可用時自動退回 SendInput。"""
    if preferred in ("auto", "interception"):
        try:
            return InterceptionMouse()
        except Exception:
            if preferred == "interception":
                m = SendInputMouse()
                m.backend_name = "SendInput（Interception 不可用）"
                return m
    return SendInputMouse()
