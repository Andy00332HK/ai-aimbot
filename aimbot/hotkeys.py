"""全域熱鍵（pynput）：鍵盤任意鍵 + 滑鼠全部按鍵。

- HOLD 模式：按住啟動鍵（config.hold_key，格式 kb:<鍵名> / mouse:<按鍵名>）
- TOGGLE 模式：toggle_key 切換
- aim_switch_key 切換頭/胸、quit_key 離開

啟動鍵比對：
- 單字元（如 a）：比對 KeyCode.char
- 修飾鍵（shift/ctrl/alt）：左右任一都算
- 其他（f5、space…）：比對 Key.name
"""
from __future__ import annotations

import threading
from typing import Callable

from pynput import keyboard, mouse

from .config import ConfigManager, normalize_hold_key

# 修飾鍵的家族集合（左/右任一按下都算）
_MOD_SETS = {
    "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
    "ctrl": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "alt": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r},
}


def kb_key_matches(name: str, key) -> bool:
    """kb:<name> 與 pynput 事件的比對。"""
    if len(name) == 1:  # 單字元鍵（a-z 0-9 等）
        ch = getattr(key, "char", None)
        return ch is not None and ch.lower() == name
    if getattr(key, "name", None) == name:
        return True
    mod = _MOD_SETS.get(name)
    return mod is not None and key in mod


class HotkeyManager:
    def __init__(self, cm: ConfigManager, on_quit: Callable[[], None]):
        """
        on_quit：由 Tk 主執行緒處理（經 dispatcher）。
        其餘事件直接呼叫 engine（執行緒安全：只用 Event 與原子設定）。
        """
        self.cm = cm
        self.engine = None  # main.py 注入
        self.on_quit = on_quit
        self._kb_listener: keyboard.Listener | None = None
        self._mouse_listener: mouse.Listener | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            self._kb_listener = keyboard.Listener(
                on_press=self._on_key_press, on_release=self._on_key_release)
            self._kb_listener.daemon = True
            self._kb_listener.start()
            self._mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
            self._mouse_listener.daemon = True
            self._mouse_listener.start()

    def stop(self) -> None:
        with self._lock:
            for l in (self._kb_listener, self._mouse_listener):
                if l is not None:
                    try:
                        l.stop()
                    except Exception:
                        pass
            self._kb_listener = None
            self._mouse_listener = None

    # ── 鍵盤 ──
    def _on_key_press(self, key) -> None:
        if self.engine is None:
            return
        cfg = self.cm.get()
        try:
            if key == _fn_key(cfg.quit_key):
                self.on_quit()
                return
            if key == _fn_key(cfg.toggle_key):
                self.engine.toggle_active()
                return
            if key == _fn_key(cfg.aim_switch_key):
                self.engine.switch_aim_point()
                return
            if key == _fn_key(cfg.diag_key):
                self.engine.request_diagnostic()
                return
        except Exception:
            pass
        hold = normalize_hold_key(cfg.hold_key)
        if hold.startswith("kb:") and kb_key_matches(hold[3:], key):
            self.engine.set_hold_pressed(True)

    def _on_key_release(self, key) -> None:
        if self.engine is None:
            return
        cfg = self.cm.get()
        hold = normalize_hold_key(cfg.hold_key)
        if hold.startswith("kb:") and kb_key_matches(hold[3:], key):
            self.engine.set_hold_pressed(False)

    # ── 滑鼠（左/右/中/側鍵皆可作啟動鍵） ──
    def _on_mouse_click(self, x, y, button, pressed) -> None:
        if self.engine is None:
            return
        cfg = self.cm.get()
        hold = normalize_hold_key(cfg.hold_key)
        if hold.startswith("mouse:") and button.name == hold[6:]:
            self.engine.set_hold_pressed(pressed)


def _fn_key(name: str):
    """'f6' → keyboard.Key.f6；非 F 鍵回 None。"""
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        return None
