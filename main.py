"""AI Aimbot — 進入點。

組裝：設定 → 引擎（背景執行緒）→ 覆蓋層 → 控制面板 → 全域熱鍵。

⚠ 僅供單機／離線遊戲使用。請勿用於任何連線／多人遊戲。
"""
from __future__ import annotations

import ctypes
import sys
import tkinter as tk


def _enable_dpi_awareness() -> None:
    """讓 Tk 座標 = 實體像素，覆蓋層才能與 mss 擷取區對齊。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> int:
    if sys.platform != "win32":
        print("此工具目前僅支援 Windows。")
        return 1

    _enable_dpi_awareness()

    from aimbot.config import ConfigManager
    from aimbot.engine import AimEngine
    from aimbot.overlay import Overlay
    from aimbot.hotkeys import HotkeyManager
    from gui.panel import ControlPanel, UiDispatcher

    cm = ConfigManager()
    dispatcher = UiDispatcher()
    engine = AimEngine(cm)

    root = tk.Tk()  # root 本身就是控制面板（ControlPanel 會設定標題與內容）

    def get_roi_origin() -> tuple[int, int]:
        if engine.capture is not None:
            return engine.capture.roi_origin
        # 引擎尚未就緒：以主螢幕幾何估算
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        roi = cm.get().roi_size
        return (sw - roi) // 2, (sh - roi) // 2

    overlay = Overlay(root, cm.get, lambda: engine.state, get_roi_origin)

    def on_quit():
        def _do_quit():
            try:
                engine.stop()
            except Exception:
                pass
            try:
                hotkeys.stop()
            except Exception:
                pass
            overlay.destroy()
            try:
                root.destroy()
            except Exception:
                pass
        # 可能從熱鍵執行緒觸發 → 一律送回主執行緒
        dispatcher.post(_do_quit)

    hotkeys = HotkeyManager(cm, on_quit=on_quit)
    hotkeys.engine = engine

    panel = ControlPanel(root, cm, engine, dispatcher, on_quit=on_quit)

    engine.start()
    hotkeys.start()

    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
