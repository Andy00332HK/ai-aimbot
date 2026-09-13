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
CAPTURE_BACKEND_LABELS = {
    "auto": "自動（dxcam 優先）",
    "dxcam": "dxcam（低延遲）",
    "mss": "mss（相容備援）",
}


def _probe_screen() -> dict:
    """取得主螢幕邊界（兩種後端共用同一幾何來源）。"""
    with mss.MSS() as sct:
        return dict(sct.monitors[1])


class _CaptureBase:
    """統一介面：grab() 回傳 BGR ndarray（ROI 座標系）或 None。"""

    backend_name = "base"

    def __init__(self, roi_size: int):
        self.roi_size = int(roi_size)
        self._mon = _probe_screen()
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

    def __init__(self, roi_size: int):
        super().__init__(roi_size)
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
    """dxcam 連續擷取模式；ROI 變更時重建 camera（dxcam 的 region 建立時固定）。"""

    backend_name = "dxcam"

    def __init__(self, roi_size: int):
        super().__init__(roi_size)
        import dxcam  # 延遲匯入：未安裝時讓 factory 退回 mss

        self._dxcam = dxcam
        self._cam = None
        self._last: Optional[np.ndarray] = None
        self._rebuild()

    def _rebuild(self) -> None:
        self._release_cam()
        roi = self.effective_roi
        left, top = self.roi_origin
        # dxcam region = (left, top, right, bottom)，output_color='BGR' 免轉換
        self._cam = self._dxcam.create(
            output_idx=0, output_color="BGR",
            region=(left, top, left + roi, top + roi),
        )
        if self._cam is None:
            raise RuntimeError("dxcam.create() 回傳 None（DDA 不支援此環境）")
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
                left, top = self.roi_origin
                roi = self.effective_roi
                frame = self._cam.grab(region=(left, top, left + roi, top + roi))
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


def create_capture(roi_size: int, preferred: str = "auto") -> _CaptureBase:
    """依設定建立擷取器；dxcam 失敗自動退回 mss。"""
    if preferred in ("auto", "dxcam"):
        try:
            cap = DxcamCapture(roi_size)
            # 驗證真的抓得到幀
            if cap.grab() is not None:
                return cap
            cap.close()
        except Exception:
            pass
    return MssCapture(roi_size)
