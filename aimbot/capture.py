"""螢幕擷取：擷取螢幕正中央的 ROI 方形區域（BGR）。

雙後端：
  - dxcam（Desktop Duplication API）：低延遲、100-240 FPS，主力
  - mss：跨環境備援（dxcam 建立失敗時自動退回）

兩種後端都不是執行緒安全的：實例必須只在單一執行緒中使用
（engine 執行緒會建立並使用自己的實例）。
"""
from __future__ import annotations

import time
from typing import Optional

import numpy as np
import mss

CAPTURE_BACKENDS = ("auto", "dxcam", "mss")


def _tr(key: str) -> str:
    try:
        from .i18n import t as _t
        return _t(key)
    except Exception:
        return key


def get_capture_backend_labels(lang: str | None = None):
    try:
        from .i18n import label_map as _lm
        return _lm("config.enum.capture", CAPTURE_BACKENDS, lang=lang)
    except Exception:
        return {b: b for b in CAPTURE_BACKENDS}


CAPTURE_BACKEND_LABELS = {
    "auto": _tr("config.enum.capture.auto"),
    "dxcam": _tr("config.enum.capture.dxcam"),
    "mss": _tr("config.enum.capture.mss"),
}


def _probe_screen() -> dict:
    """主螢幕邊界（相容舊呼叫；新程式碼請用 list_monitors/get_monitor）。"""
    with mss.MSS() as sct:
        mons = sct.monitors
        for m in mons[1:]:
            if m.get("is_primary"):
                return dict(m)
        return dict(mons[1])


def list_monitors() -> list[dict]:
    """回傳實體螢幕清單，主螢幕排第一。每項含 index(0=主螢幕)、left/top/width/height/is_primary/label。"""
    with mss.MSS() as sct:
        raw = [dict(m) for m in sct.monitors[1:]]
    primary = [m for m in raw if m.get("is_primary")]
    others = [m for m in raw if not m.get("is_primary")]
    ordered = primary + others
    out = []
    for i, m in enumerate(ordered):
        prim = bool(m.get("is_primary"))
        base = _tr("capture.monitor.primary") if prim else _tr("capture.monitor.secondary")
        out.append({
            "index": i,
            "left": m["left"], "top": m["top"],
            "width": m["width"], "height": m["height"],
            "is_primary": prim,
            "label": f"{base} {m['width']}x{m['height']} @({m['left']},{m['top']})",
        })
    return out


def get_monitor(idx: int) -> dict:
    """依 index 取螢幕（0=主螢幕）；越界時退回主螢幕。"""
    mons = list_monitors()
    if not mons:
        return _probe_screen()
    idx = int(idx)
    if idx < 0 or idx >= len(mons):
        return dict(mons[0])
    return dict(mons[idx])


class _CaptureBase:
    """統一介面：grab() 回傳 BGR ndarray（ROI 座標系）或 None。"""

    backend_name = "base"

    def __init__(self, roi_size: int, monitor_index: int = 0):
        self.roi_size = int(roi_size)
        self.monitor_index = int(monitor_index)
        self._mon = get_monitor(self.monitor_index)
        self.screen_w = self._mon["width"]
        self.screen_h = self._mon["height"]

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
        raise NotImplementedError

    def configure(self, roi_size: int) -> None:
        """執行期調整 ROI（dxcam 需重建 camera）。"""
        self.roi_size = int(roi_size)

    def close(self) -> None:
        pass


class MssCapture(_CaptureBase):
    backend_name = "mss"

    def __init__(self, roi_size: int, monitor_index: int = 0):
        super().__init__(roi_size, monitor_index)
        self._sct: Optional[mss.mss] = None

    def grab(self) -> Optional[np.ndarray]:
        if self._sct is None:
            self._sct = mss.MSS()
        roi = self.effective_roi
        left, top = self.roi_origin
        region = {"left": left, "top": top, "width": roi, "height": roi}
        try:
            shot = self._sct.grab(region)
        except (mss.error.ScreenShotError, OSError, ValueError):
            self._sct = None  # 下次重建
            return None
        rgb = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3)
        return np.ascontiguousarray(rgb[..., ::-1])  # RGB → BGR

    def close(self) -> None:
        if self._sct is not None:
            try:
                self._sct.close()
            except Exception:
                pass
            self._sct = None


class DxcamCapture(_CaptureBase):
    """dxcam 連續擷取模式；ROI 變更時重建 camera（dxcam 的 region 建立時固定）。

    注意：dxcam 的 region 是該 output 內相對座標（0..W），不是虛擬桌面絕對座標。
    因此 ROI 取該螢幕置中偏移，覆蓋層則用虛擬座標 (left/top + 偏移) 對齊。
    """

    backend_name = "dxcam"

    def __init__(self, roi_size: int, monitor_index: int = 0):
        super().__init__(roi_size, monitor_index)
        import dxcam  # 延遲匯入：未安裝時讓 factory 退回 mss

        self._dxcam = dxcam
        self._cam = None
        self._last: Optional[np.ndarray] = None
        self._rebuild()

    def _rebuild(self) -> None:
        self._release_cam()
        roi = self.effective_roi
        # output 內相對座標置中（dxcam region 相對於該 output，非虛擬桌面）
        ox = (self.screen_w - roi) // 2
        oy = (self.screen_h - roi) // 2
        # dxcam region = (left, top, right, bottom)，output_color='BGR' 免轉換
        self._cam = self._dxcam.create(
            output_idx=self.monitor_index, output_color="BGR",
            region=(ox, oy, ox + roi, oy + roi),
        )
        if self._cam is None:
            raise RuntimeError(_tr("capture.error.create_none"))
        self._cam.start(target_fps=0, video_mode=False)
        time.sleep(0.05)  # 讓首幀就緒

    def _release_cam(self) -> None:
        if self._cam is not None:
            try:
                if self._cam.is_alive():
                    self._cam.stop()
            except Exception:
                pass
            try:
                self._cam.release()
            except Exception:
                pass
            self._cam = None

    def grab(self) -> Optional[np.ndarray]:
        try:
            frame = self._cam.get_latest_frame()
        except Exception:
            frame = None
        if frame is None:
            # 畫面靜止時 DDA 不產生新幀：退回一次性抓取，再不行用上一次的快取
            try:
                roi = self.effective_roi
                ox = (self.screen_w - roi) // 2
                oy = (self.screen_h - roi) // 2
                frame = self._cam.grab(region=(ox, oy, ox + roi, oy + roi))
            except Exception:
                frame = None
        if frame is not None:
            self._last = frame
        return self._last

    def set_roi_size(self, roi_size: int) -> None:
        if roi_size != self.roi_size:
            self.roi_size = int(roi_size)
            self._rebuild()

    def configure(self, roi_size: int) -> None:
        self.set_roi_size(roi_size)

    def close(self) -> None:
        self._release_cam()


def create_capture(roi_size: int, preferred: str = "auto", monitor_index: int = 0) -> _CaptureBase:
    """依設定建立擷取器；dxcam 失敗自動退回 mss。"""
    try:
        mi = int(monitor_index)
    except Exception:
        mi = 0
    if preferred in ("auto", "dxcam"):
        try:
            cap = DxcamCapture(roi_size, monitor_index=mi)
            # 驗證真的抓得到幀
            if cap.grab() is not None:
                return cap
            cap.close()
        except Exception:
            pass
    return MssCapture(roi_size, monitor_index=mi)
