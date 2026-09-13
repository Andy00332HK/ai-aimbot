"""設定管理：預設值、載入、儲存、範圍驗證（執行緒安全）。"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, fields, replace

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.json")

MODEL_SIZES = ("n", "s")
IMGSZ_CHOICES = (320, 416, 640)
MOUSE_BUTTONS = ("left", "right", "middle", "x1", "x2")

# 舊版 hold_key 值 → 新格式（kb:鍵名 / mouse:按鍵名）
_LEGACY_HOLD = {
    "shift": "kb:shift",
    "ctrl": "kb:ctrl",
    "alt": "kb:alt",
    "caps_lock": "kb:caps_lock",
    "mouse_x1": "mouse:x1",
    "mouse_x2": "mouse:x2",
}

_KB_LABELS = {
    "shift": "Shift", "ctrl": "Ctrl", "alt": "Alt", "space": "空白鍵",
    "caps_lock": "Caps Lock", "tab": "Tab", "enter": "Enter",
    "backspace": "Backspace", "delete": "Delete", "insert": "Insert",
    "home": "Home", "end": "End", "page_up": "Page Up", "page_down": "Page Down",
    "up": "↑", "down": "↓", "left": "←", "right": "→",
}
_MOUSE_LABELS = {
    "left": "滑鼠左鍵", "right": "滑鼠右鍵", "middle": "滑鼠中鍵",
    "x1": "滑鼠側鍵 X1", "x2": "滑鼠側鍵 X2",
}


def normalize_hold_key(k) -> str:
    """把任意輸入正規化為合法 hold_key（kb:<name> / mouse:<button>）。"""
    if not isinstance(k, str):
        return "kb:shift"
    k = k.strip().lower()
    if k in _LEGACY_HOLD:
        return _LEGACY_HOLD[k]
    if k.startswith("kb:"):
        name = k[3:]
        ok = name and all(c.isalnum() or c == "_" for c in name)
        return k if ok else "kb:shift"
    if k.startswith("mouse:") and k[6:] in MOUSE_BUTTONS:
        return k
    return "kb:shift"


def hold_key_label(k) -> str:
    """啟動鍵的人類可讀標籤（面板顯示用）。"""
    k = normalize_hold_key(k)
    if k.startswith("mouse:"):
        return _MOUSE_LABELS.get(k[6:], k)
    name = k[3:]
    return _KB_LABELS.get(name, name.upper())
AIM_POINTS = ("head", "body")
AIM_POINT_LABELS = {"head": "頭部", "body": "胸口"}


@dataclass(frozen=True)
class Config:
    """所有可調參數。frozen：跨執行緒傳遞時不可被意外修改。"""

    # ── 偵測 ──
    model_size: str = "n"          # "n" 快速 / "s" 精準
    imgsz: int = 640               # 推論輸入尺寸 320 / 416 / 640
    confidence: float = 0.45       # 偵測信心度門檻 0.05–0.95
    capture_backend: str = "auto"  # auto / dxcam / mss
    # ── 掃描範圍 / 顯示 ──
    roi_size: int = 640            # ROI 邊長 px（螢幕正中央）
    grid_cells: int = 8            # 網格密度（每邊格數）
    show_grid: bool = True
    show_detections: bool = True
    show_overlay: bool = True
    # ── 瞄準 ──
    aim_point: str = "head"        # head = 框頂+20% / body = 框頂+55%
    sticky_lock: bool = True       # 黏性鎖定：多人時鎖住同一目標不跳
    half_life_ms: int = 55          # 收斂半衰期：誤差減半所需時間，越小拉越快
    jitter_suppression: float = 0.35  # 1€ 濾波強度 0–1：目標點除抖
    aim_prediction: float = 0.7    # 提前量 0–1：補償延遲與控制器落後的提前瞄
    deadzone_px: float = 2.0       # 誤差小於此值不移動（防抖）
    sensitivity: float = 1.0       # 滑鼠位移倍率
    # ── 啟動 ──
    activation_mode: str = "hold"  # hold / toggle
    hold_key: str = "shift"        # 見 HOLD_KEY_CHOICES
    toggle_key: str = "f6"
    aim_switch_key: str = "f7"
    quit_key: str = "f8"
    diag_key: str = "f9"           # 輸入診斷（遊戲內按）

    def sanitized(self) -> "Config":
        """夾限所有數值到合法範圍，未知列舉回退預設。"""
        c = self
        if c.model_size not in MODEL_SIZES:
            c = replace(c, model_size="n")
        if c.capture_backend not in ("auto", "dxcam", "mss"):
            c = replace(c, capture_backend="auto")
        c = replace(c, imgsz=min(IMGSZ_CHOICES, key=lambda v: abs(v - c.imgsz)))
        c = replace(
            c,
            confidence=min(0.95, max(0.05, float(c.confidence))),
            roi_size=int(min(1200, max(320, c.roi_size))),
            grid_cells=int(min(24, max(2, c.grid_cells))),
            half_life_ms=int(min(300, max(20, int(c.half_life_ms)))),
            jitter_suppression=min(1.0, max(0.0, float(c.jitter_suppression))),
            aim_prediction=min(1.0, max(0.0, float(c.aim_prediction))),
            deadzone_px=min(30.0, max(0.0, float(c.deadzone_px))),
            sensitivity=min(3.0, max(0.2, float(c.sensitivity))),
        )
        if c.aim_point not in AIM_POINTS:
            c = replace(c, aim_point="head")
        if c.activation_mode not in ("hold", "toggle"):
            c = replace(c, activation_mode="hold")
        c = replace(c, hold_key=normalize_hold_key(c.hold_key))
        return c


class ConfigManager:
    """載入／更新／持久化 config.json。update() 為原子替換，可安全跨執行緒。"""

    def __init__(self, path: str = CONFIG_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._config = self._load()

    def _load(self) -> Config:
        defaults = Config().sanitized()
        if not os.path.exists(self._path):
            self._save_unlocked(defaults)
            return defaults
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            known = {f.name for f in fields(Config)}
            clean = {k: v for k, v in data.items() if k in known}
            cfg = replace(defaults, **clean).sanitized()
            return cfg
        except (json.JSONDecodeError, TypeError, ValueError):
            return defaults

    def _save_unlocked(self, cfg: Config) -> None:
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    def get(self) -> Config:
        with self._lock:
            return self._config

    def update(self, **kwargs) -> Config:
        with self._lock:
            self._config = replace(self._config, **kwargs).sanitized()
            self._save_unlocked(self._config)
            return self._config

    def reset(self) -> Config:
        with self._lock:
            self._config = Config().sanitized()
            self._save_unlocked(self._config)
            return self._config
