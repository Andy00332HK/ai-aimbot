"""螢幕擷取：擷取螢幕正中央的 ROI 方形區域（BGR）。

mss 不是執行緒安全的，實例必須只在單一執行緒中使用
（engine 執行緒會懶載入自己的 mss 實例）。
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import mss


class ScreenCapture:
    def __init__(self, roi_size: int):
        self.roi_size = int(roi_size)
        self._sct: Optional[mss.mss] = None
        self._mon = {"left": 0, "top": 0, "width": 1920, "height": 1080}
        self.screen_w = 1920
        self.screen_h = 1080
        self._probe_screen()

    def _probe_screen(self) -> None:
        with mss.mss() as sct:
            mon = sct.monitors[1]  # 主螢幕
        self._mon = dict(mon)
        self.screen_w = mon["width"]
        self.screen_h = mon["height"]

    @property
    def effective_roi(self) -> int:
        """ROI 不得大於螢幕（留 40px 邊距）。"""
        limit = max(200, min(self.screen_w, self.screen_h) - 40)
        return int(min(self.roi_size, limit))

    @property
    def roi_origin(self) -> tuple[int, int]:
        """ROI 左上角在螢幕上的實際座標（供覆蓋層對齊）。"""
        roi = self.effective_roi
        left = self._mon["left"] + (self._mon["width"] - roi) // 2
        top = self._mon["top"] + (self._mon["height"] - roi) // 2
        return left, top

    def grab(self) -> Optional[np.ndarray]:
        """回傳 ROI 的 BGR 影像；失敗回傳 None。"""
        if self._sct is None:
            self._sct = mss.mss()
        roi = self.effective_roi
        left, top = self.roi_origin
        region = {"left": left, "top": top, "width": roi, "height": roi}
        try:
            shot = self._sct.grab(region)
        except (mss.error.ScreenShotError, OSError, ValueError):
            self._sct = None  # 下次重建
            return None
        # mss 的 shot.rgb 是 bytes（RGB 順序）→ 轉為 BGR 連續陣列供 YOLO 使用
        rgb = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3)
        return np.ascontiguousarray(rgb[..., ::-1])

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None
