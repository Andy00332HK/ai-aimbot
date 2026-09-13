"""YOLO 偵測器：YOLO11（COCO 預訓練、只抓 person 類別）+ ByteTrack 追蹤。

追蹤：model.track(persist=True) 給每個目標持續的 track_id，
偵測閃斷時 ByteTrack 用低信心度框關聯新舊幀，ID 不跳。

後端自動降級鏈：
  1. TensorRT FP16 engine（若已匯出或 tensorrt 可用）
  2. PyTorch CUDA
  3. PyTorch CPU

僅供單機／離線遊戲使用。
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import numpy as np

from .config import PROJECT_ROOT

MODEL_DIR = os.path.join(PROJECT_ROOT, "models")
PERSON_CLASS_ID = 0  # COCO: person
TRACKER_YAML = os.path.join(PROJECT_ROOT, "aimbot", "botsort.yaml")


@dataclass(frozen=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    track_id: int = -1   # ByteTrack 持續 ID；-1 = 尚未分配

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2.0

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2.0

    @property
    def w(self) -> float:
        return self.x2 - self.x1

    @property
    def h(self) -> float:
        return self.y2 - self.y1


class Detector:
    """載入模型並執行推論。reload 可在執行期切換模型／尺寸／門檻。"""

    def __init__(self, model_size: str = "n", imgsz: int = 640, confidence: float = 0.45):
        self.model_size = model_size
        self.imgsz = imgsz
        self.confidence = confidence
        self.backend = "未載入"
        self._model = None
        self._use_cuda = False
        self.last_infer_ms = 0.0
        os.makedirs(MODEL_DIR, exist_ok=True)

    # ── 模型路徑 ──
    def _pt_path(self) -> str:
        return os.path.join(MODEL_DIR, f"yolo11{self.model_size}.pt")

    def _engine_path(self) -> str:
        # engine 內嵌固定輸入尺寸 → 檔名含 imgsz，避免切換尺寸後誤用
        return os.path.join(MODEL_DIR, f"yolo11{self.model_size}_{self.imgsz}.engine")

    # ── 載入 ──
    def load(self) -> None:
        """載入模型（首次會自動下載權重 / 嘗試匯出 TensorRT）。"""
        from ultralytics import YOLO

        # 1) TensorRT engine：已存在就直接用
        if os.path.exists(self._engine_path()):
            try:
                m = YOLO(self._engine_path(), task="detect")
                self._model = m
                self._use_cuda = True
                self.backend = "TensorRT FP16"
                return
            except Exception:
                pass  # 引擎損毀 → 刪除快取重試其他後端
        # 2) .pt（會自動下載）+ CUDA；tensorrt 可用時先匯出 engine
        m = YOLO(self._pt_path())
        try:
            import torch

            cuda_ok = torch.cuda.is_available()
        except Exception:
            cuda_ok = False
        if cuda_ok:
            self._try_export_engine(m)
            if os.path.exists(self._engine_path()):
                try:
                    m = YOLO(self._engine_path(), task="detect")
                    self._model = m
                    self._use_cuda = True
                    self.backend = "TensorRT FP16"
                    return
                except Exception:
                    pass
            self._model = m
            self._use_cuda = True
            self.backend = "PyTorch CUDA"
        else:
            self._model = m
            self._use_cuda = False
            self.backend = "CPU"

    def _try_export_engine(self, model) -> None:
        """tensorrt 套件存在時才嘗試匯出；任何失敗都靜默退回 .pt。"""
        try:
            import tensorrt  # noqa: F401
        except Exception:
            return
        try:
            model.export(
                format="engine",
                half=True,
                device=0,
                dynamic=False,
                simplify=True,
                imgsz=self.imgsz,
            )
        except Exception:
            pass

    # ── 推論（含 ByteTrack 追蹤） ──
    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """回傳 ROI 座標系中的 person 偵測結果（含持續 track_id）。
        persist=True 讓追蹤器複用前幀狀態（幀序列來自同一畫面串流）。
        任何錯誤回傳空列表。"""
        if self._model is None:
            return []
        t0 = time.perf_counter()
        try:
            results = self._model.track(
                frame_bgr,
                imgsz=self.imgsz,
                conf=self.confidence,
                classes=[PERSON_CLASS_ID],
                persist=True,
                tracker=TRACKER_YAML,
                verbose=False,
                device=0 if self._use_cuda else "cpu",
            )
        except Exception:
            self.last_infer_ms = (time.perf_counter() - t0) * 1000.0
            return []
        self.last_infer_ms = (time.perf_counter() - t0) * 1000.0
        dets: list[Detection] = []
        for r in results:
            boxes = getattr(r, "boxes", None)
            if boxes is None:
                continue
            xyxy = boxes.xyxy.cpu().numpy() if boxes.xyxy is not None else []
            confs = boxes.conf.cpu().numpy() if boxes.conf is not None else []
            ids = boxes.id
            ids = ids.cpu().numpy().astype(int) if ids is not None else None
            for i, ((x1, y1, x2, y2), cf) in enumerate(zip(xyxy, confs)):
                tid = int(ids[i]) if ids is not None and i < len(ids) else -1
                dets.append(Detection(float(x1), float(y1), float(x2), float(y2),
                                      float(cf), tid))
        return dets

    # ── Kalman 狀態（來自 tracker 內建的每軌跡濾波器） ──
    def track_state(self, track_id: int) -> Optional[tuple]:
        """取得指定軌跡的 Kalman 狀態 (cx, cy, h, vx, vy)。

        ByteTrack/BoT-SORT 內部為每條軌跡維護 Kalman 濾波器；偵測閃斷時
        丟失軌跡仍每幀被預測（位置沿速度外推），故鎖定中的目標即使
        暫時偵測不到也能取得外推位置與平滑速度。
        ultralytics 內部 API（新版為 predictor.trackers 列表，舊版為
        predictor.tracker），任何變動/錯誤一律回傳 None（呼叫端回退）。"""
        if self._model is None:
            return None
        try:
            trackers = getattr(self._model.predictor, "trackers", None) or \
                [self._model.predictor.tracker]
            for tracker in trackers:
                for t in (*tracker.tracked_stracks, *tracker.lost_stracks):
                    if getattr(t, "track_id", None) != track_id:
                        continue
                    m = t.mean  # [cx, cy, aspect, h, vx, vy, va, vh]
                    return (float(m[0]), float(m[1]), float(m[3]),
                            float(m[4]), float(m[5]))
        except Exception:
            return None
        return None

    # ── 執行期切換 ──
    def reload(self, model_size: str | None = None, imgsz: int | None = None,
               confidence: float | None = None) -> None:
        """切換模型／尺寸／門檻（阻塞約 1–3 秒，由 engine 在背景執行緒呼叫）。"""
        if model_size is not None:
            self.model_size = model_size
        if imgsz is not None:
            self.imgsz = imgsz
        if confidence is not None:
            self.confidence = confidence
        self._model = None
        self.backend = "載入中…"
        try:
            self.load()
        except Exception as e:
            self.backend = f"載入失敗：{type(e).__name__}"
            raise
