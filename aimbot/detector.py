"""YOLO 偵測器：YOLO11（COCO 預訓練、只抓 person 類別）。

後端自動降級鏈：
  1. TensorRT FP16 engine（若已匯出或 tensorrt 可用）
  2. PyTorch CUDA（FP16 推論）
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


@dataclass(frozen=True)
class Detection:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float

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

    # ── 推論 ──
    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        """回傳 ROI 座標系中的 person 偵測結果。任何錯誤回傳空列表。"""
        if self._model is None:
            return []
        t0 = time.perf_counter()
        try:
            results = self._model.predict(
                frame_bgr,
                imgsz=self.imgsz,
                conf=self.confidence,
                classes=[PERSON_CLASS_ID],
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
            for (x1, y1, x2, y2), cf in zip(xyxy, confs):
                dets.append(Detection(float(x1), float(y1), float(x2), float(y2), float(cf)))
        return dets

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
