"""Raw Input 探針：驗證滑鼠注入後端到達遊戲時的身分（遊戲視角端到端測試）。

以與遊戲相同的方式註冊 RawInput（RIDEV_INPUTSINK），分別用 SendInput 與
Interception 送出 +400 滑格脈衝，觀察每個 WM_INPUT 事件的 hDevice：
  - SendInput → hDevice=NULL（會被過濾合成輸入的遊戲引擎丟棄）
  - Interception → hDevice=真實裝置句柄（遊戲視為硬體輸入）
同時量測光標淨位移並歸位。執行期間請勿移動滑鼠。
"""
import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                  wintypes.WPARAM, wintypes.LPARAM]
user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                   wintypes.LPVOID, ctypes.POINTER(wintypes.UINT),
                                   wintypes.UINT]
user32.GetRawInputData.restype = wintypes.UINT

WM_INPUT = 0x00FF
RIDEV_INPUTSINK = 0x00000100
RID_INPUT = 0x10000003

events = []


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


class RAWMOUSE(ctypes.Structure):
    class _U(ctypes.Union):
        class _S(ctypes.Structure):
            _fields_ = [("usButtonFlags", wintypes.USHORT),
                        ("usButtonData", wintypes.USHORT)]
        _fields_ = [("ulButtons", wintypes.ULONG), ("btn", _S)]
    _anonymous_ = ("u",)
    _fields_ = [("usFlags", wintypes.USHORT), ("u", _U),
                ("ulRawButtons", wintypes.ULONG),
                ("lLastX", wintypes.LONG), ("lLastY", wintypes.LONG),
                ("ulExtraInformation", wintypes.ULONG)]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("mouse", RAWMOUSE)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


def wnd_proc(hwnd, msg, wparam, lparam):
    if msg == WM_INPUT:
        size = wintypes.UINT(0)
        user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size),
                               ctypes.sizeof(RAWINPUTHEADER))
        buf = ctypes.create_string_buffer(size.value)
        got = user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size),
                                     ctypes.sizeof(RAWINPUTHEADER))
        if got not in (0, 0xFFFFFFFF):
            ri = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
            if ri.header.dwType == 0:
                events.append((time.perf_counter(), ri.header.hDevice,
                               ri.mouse.lLastX, ri.mouse.lLastY))
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


proc = WNDPROC(wnd_proc)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", ctypes.c_void_p), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


wc = WNDCLASSW(0, proc, 0, 0, kernel32.GetModuleHandleW(None),
               None, None, None, None, "rawprobe2")
assert user32.RegisterClassW(ctypes.byref(wc))
hwnd = user32.CreateWindowExW(0, "rawprobe2", "probe", 0, 0, 0, 0, 0,
                              wintypes.HWND(-3), None, None, None)
assert hwnd
rid = RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, hwnd)
assert user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE))

from aimbot.mouse import SendInputMouse, InterceptionMouse
si = SendInputMouse()
it = InterceptionMouse()

start = time.perf_counter()
result = {}


def phase(name, fn):
    result[name] = fn()


def burst_send():
    for _ in range(20):
        si.move_relative(20, 0)
        time.sleep(0.025)


def burst_int():
    for _ in range(20):
        it.move_relative(20, 0)
        time.sleep(0.025)


def restore_send():
    for _ in range(20):
        si.move_relative(-20, 0)
        time.sleep(0.02)


def restore_int():
    for _ in range(20):
        it.move_relative(-20, 0)
        time.sleep(0.02)


def cursor_delta(fn):
    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    x0, y0 = pt.x, pt.y
    fn()
    time.sleep(0.1)
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x - x0, pt.y - y0


def run():
    time.sleep(0.4)                       # t≈0.4 安靜期（控制組：不注入）
    result["idle_cursor"] = cursor_delta(lambda: time.sleep(0.6))
    result["t_send"] = time.perf_counter()
    result["send_cursor"] = cursor_delta(burst_send)   # t≈1.0-1.6
    restore_send()                        # 光標歸位，避免測完停在 +400px
    time.sleep(0.5)
    result["t_int"] = time.perf_counter()
    result["int_cursor"] = cursor_delta(burst_int)     # t≈2.1-2.7
    restore_int()
    time.sleep(0.4)


threading.Thread(target=run, daemon=True).start()

msg = wintypes.MSG()
while threading.active_count() > 1 or time.perf_counter() - start < 3.6:
    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))
    time.sleep(0.001)
time.sleep(0.2)

t_send = result["t_send"] - start
t_int = result["t_int"] - start
print(f"光標淨位移: 靜止對照 {result['idle_cursor']}, "
      f"SendInput +400 {result['send_cursor']}, Interception +400 {result['int_cursor']}")
print(f"注入時刻: SendInput t={t_send:.2f}s, Interception t={t_int:.2f}s\n")

w1 = [e for e in events if t_send <= (e[0] - start) <= t_send + 0.8]
w2 = [e for e in events if t_int <= (e[0] - start) <= t_int + 0.8]
other = [e for e in events if e not in w1 and e not in w2]
for label, win in (("SendInput", w1), ("Interception", w2)):
    n_null = sum(1 for e in win if not e[1])
    print(f"{label:12s} 窗口: {len(win):3d} 事件, dx 總和 {sum(e[2] for e in win):+5d}, "
          f"hDevice=NULL {n_null}, 帶句柄 {len(win) - n_null}")
print(f"其他時段: {len(other)} 事件（物理滑鼠）")
if other:
    hd = other[len(other) // 2][1]
    print(f"物理滑鼠事件 hDevice 範例: 0x{hd:X}" if hd else "物理事件 hDevice=NULL?!")
