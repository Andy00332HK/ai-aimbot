"""全域熱鍵（pynput）：鍵盤 + 滑鼠側鍵。

- HOLD 模式：按住 hold_key（鍵盤鍵或滑鼠側鍵）時啟動
- TOGGLE 模式：toggle_key 切換
- aim_switch_key 切換頭/胸、quit_key 離開

所有 UI 影響的回呼都透過 dispatcher（佇列）送到 Tk 主執行緒。
"""
from __future__ import annotations

import threading
from typing import Callable

from pynput import keyboard, mouse

from .config import ConfigManager

# 鍵盤按住鍵 → pynput Key 名稱
_HOLD_KEY_MAP = {
    "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
    "ctrl": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "alt": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r},
    "caps_lock": {keyboard.Key.caps_lock},
}


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
        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press, on_release=self._on_key_release)
        self._kb_listener.daemon = True
        self._kb_listener.start()
        self._mouse_listener = mouse.Listener(on_click=self._on_mouse_click)
        self._mouse_listener.daemon = True
        self._mouse_listener.start()

    def stop(self) -> None:
        for l in (self._kb_listener, self._mouse_listener):
            if l is not None:
                try:
                    l.stop()
                except Exception:
                    pass

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
        except Exception:
            pass
        hold_set = _HOLD_KEY_MAP.get(cfg.hold_key)
        if hold_set and key in hold_set:
            self.engine.set_hold_pressed(True)

    def _on_key_release(self, key) -> None:
        if self.engine is None:
            return
        cfg = self.cm.get()
        hold_set = _HOLD_KEY_MAP.get(cfg.hold_key)
        if hold_set and key in hold_set:
            self.engine.set_hold_pressed(False)

    # ── 滑鼠側鍵 ──
    def _on_mouse_click(self, x, y, button, pressed) -> None:
        if self.engine is None:
            return
        cfg = self.cm.get()
        is_x1 = button == mouse.Button.x1
        is_x2 = button == mouse.Button.x2
        if (cfg.hold_key == "mouse_x1" and is_x1) or (cfg.hold_key == "mouse_x2" and is_x2):
            self.engine.set_hold_pressed(pressed)


def _fn_key(name: str):
    """'f6' → keyboard.Key.f6；非 F 鍵回 None。"""
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        return None
