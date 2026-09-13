"""置中透明覆蓋層：直接把網格與偵測框畫在螢幕中央的 ROI 上。

- Tkinter 無邊框視窗 + 透明色
- Win32 WS_EX_TRANSPARENT | WS_EX_NOACTIVATE → 點擊穿透（不影響遊戲操作）
- 永遠置頂（定期重新斷言，防止被全螢幕遊戲蓋掉）
- 重繪由 Tk mainloop 的 after 排程驅動（Tk 非執行緒安全）
"""
from __future__ import annotations

import ctypes
import tkinter as tk

TRANSPARENT = "#010101"  # 幾乎不會出現在真實畫面的顏色作為透明鍵

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

COLOR_GRID = "#3a3f4b"
COLOR_DET = "#2ecc71"       # 綠：一般偵測
COLOR_LOCK = "#ff3b30"      # 紅：鎖定目標
COLOR_CROSS = "#ff3b30"
COLOR_STATUS = "#e8e8e8"
COLOR_OFF = "#888888"


def _make_clickthrough(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
    )


def _assert_topmost(hwnd: int) -> None:
    ctypes.windll.user32.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
    )


class Overlay:
    """engine.state + config → 螢幕置中 ROI 視覺化。"""

    def __init__(self, root: tk.Tk, get_config, get_state, get_roi_origin):
        self.get_config = get_config
        self.get_state = get_state
        self.get_roi_origin = get_roi_origin  # () -> (left, top) ROI 在螢幕上的原點
        self.win = tk.Toplevel(root)
        self.win.title("AI Aimbot Overlay")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-transparentcolor", TRANSPARENT)
        self.win.configure(bg=TRANSPARENT)
        self.canvas = tk.Canvas(self.win, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._hwnd = 0
        self._frame_i = 0
        self.win.after(60, self._apply_win32)  # 視窗映射後套用穿透樣式
        self.win.after(16, self._tick)

    def _apply_win32(self) -> None:
        try:
            self.win.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.win.winfo_id())
            if not hwnd:
                hwnd = self.win.winfo_id()
            self._hwnd = hwnd
            _make_clickthrough(hwnd)
            _assert_topmost(hwnd)
        except Exception:
            pass

    # ── 幾何 ──
    def _place(self) -> None:
        cfg = self.get_config()
        size = cfg.roi_size
        left, top = self.get_roi_origin()
        self.win.geometry(f"{size}x{size}+{left}+{top}")

    # ── 每幀重繪 ──
    def _tick(self) -> None:
        try:
            cfg = self.get_config()
            st = self.get_state()
            if cfg.show_overlay:
                if self.win.state() == "withdrawn":
                    self.win.deiconify()
                self._place()
                self._draw(cfg, st)
            else:
                if self.win.state() != "withdrawn":
                    self.win.withdraw()
            self._frame_i += 1
            if self._frame_i % 120 == 0 and self._hwnd:
                _assert_topmost(self._hwnd)  # 防止被遊戲蓋掉
        except Exception:
            pass
        self.win.after(16, self._tick)  # ~60 FPS 重繪

    def _draw(self, cfg, st) -> None:
        c = self.canvas
        c.delete("all")
        size = cfg.roi_size
        if size < 50:
            return
        # 網格
        if cfg.show_grid:
            n = max(2, cfg.grid_cells)
            step = size / n
            for i in range(1, n):
                p = i * step
                c.create_line(p, 0, p, size, fill=COLOR_GRID)
                c.create_line(0, p, size, p, fill=COLOR_GRID)
        # 邊界
        border = COLOR_DET if st.active else COLOR_OFF
        c.create_rectangle(0, 0, size - 1, size - 1, outline=border, width=2)
        # 準心十字（ROI 中心）
        cx = cy = size / 2
        g = 7
        c.create_line(cx - g, cy, cx + g, cy, fill=COLOR_CROSS, width=2)
        c.create_line(cx, cy - g, cx, cy + g, fill=COLOR_CROSS, width=2)
        # 偵測框
        if cfg.show_detections:
            for d in st.detections:
                locked = st.lock_box is not None and \
                    (d.x1, d.y1, d.x2, d.y2) == st.lock_box
                color = COLOR_LOCK if locked else COLOR_DET
                width = 3 if locked else 2
                c.create_rectangle(d.x1, d.y1, d.x2, d.y2, outline=color, width=width)
                label = f"{d.conf:.2f}"
                c.create_text(d.x1 + 2, max(0, d.y1 - 9), text=label,
                              fill=color, anchor="w", font=("Segoe UI", 9, "bold"))
            # 瞄準點標記
            if st.lock_pt is not None:
                tx, ty = st.lock_pt
                c.create_oval(tx - 3, ty - 3, tx + 3, ty + 3,
                              outline=COLOR_LOCK, width=2)
        # 狀態列
        status = (f"FPS {st.fps:.0f}  |  {'ON' if st.active else 'OFF'}  |  "
                  f"AIM {'HEAD' if cfg.aim_point == 'head' else 'BODY'}")
        c.create_text(8, 6, text=status, anchor="nw", fill=COLOR_STATUS,
                      font=("Segoe UI", 10, "bold"))

    def destroy(self) -> None:
        try:
            self.win.destroy()
        except Exception:
            pass
