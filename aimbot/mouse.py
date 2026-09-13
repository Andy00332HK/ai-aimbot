"""滑鼠控制：Windows SendInput API 相對移動（純 ctypes，無額外依賴）。

相對移動（MOUSEEVENTF_MOVE）多數遊戲可直接接收。
實際位移會受 Windows「加強指標精準度」與遊戲內靈敏度影響，
因此提供 sensitivity 倍率供使用者校正。
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


class MouseController:
    def __init__(self, sensitivity: float = 1.0):
        self.sensitivity = float(sensitivity)

    def move_relative(self, dx: float, dy: float) -> None:
        """相對移動滑鼠（以整數 mickey 為單位）。"""
        idx = int(round(dx * self.sensitivity))
        idy = int(round(dy * self.sensitivity))
        if idx == 0 and idy == 0:
            return
        inp = _INPUT(type=INPUT_MOUSE)
        inp.mi = _MOUSEINPUT(
            dx=idx,
            dy=idy,
            mouseData=0,
            dwFlags=MOUSEEVENTF_MOVE,
            time=0,
            dwExtraInfo=None,
        )
        _USER32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
