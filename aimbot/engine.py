"""瞄準引擎：背景執行緒跑「擷取 → 偵測 →（啟用時）瞄準」主迴圈。

UI（面板／覆蓋層）只讀 state 快照，不直接碰引擎內部。
僅供單機／離線遊戲使用。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace

from .capture import ScreenCapture
from .config import ConfigManager
from .detector import Detection, Detector
from .mouse import MouseController
from .targeting import aim_point, compute_move, pick_target


@dataclass
class EngineState:
    """供 UI 讀取的即時狀態快照（整體替換，避免競態）。"""

    fps: float = 0.0
    inference_ms: float = 0.0
    n_detections: int = 0
    detections: list[Detection] = field(default_factory=list)
    lock_conf: float = 0.0
    lock_point: tuple[float, float] | None = None
    lock_box: tuple[float, float, float, float] | None = None
    active: bool = False
    backend: str = "載入中…"
    aim_point_mode: str = "head"
    model_ready: bool = False
    error: str = ""


class AimEngine:
    def __init__(self, config_manager: ConfigManager):
        self.cm = config_manager
        self.state = EngineState()
        self.capture: ScreenCapture | None = None
        self.detector = Detector()
        self.mouse = MouseController()
        # 啟動控制
        self._hold_pressed = threading.Event()   # 實體按住鍵
        self._latch = threading.Event()          # 面板大按鈕／F6 的鎖定狀態
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_model_key: str = ""

    # ── 生命週期 ──
    def start(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="aim-engine", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    # ── 啟動控制（熱鍵 / 面板共用） ──
    def set_hold_pressed(self, pressed: bool) -> None:
        if pressed:
            self._hold_pressed.set()
        else:
            self._hold_pressed.clear()

    def toggle_active(self) -> None:
        """面板大按鈕與 F6 共用：hold 模式下鎖住「持續啟用」，toggle 模式下直接切換。"""
        if self._latch.is_set():
            self._latch.clear()
        else:
            self._latch.set()

    def is_active(self, cfg) -> bool:
        if cfg.activation_mode == "hold":
            return self._hold_pressed.is_set() or self._latch.is_set()
        return self._latch.is_set()

    def switch_aim_point(self) -> str:
        """F7：頭部 ↔ 胸口。回傳切換後的模式。"""
        new = "body" if self.cm.get().aim_point == "head" else "head"
        self.cm.update(aim_point=new)
        return new

    # ── 主迴圈 ──
    def _run(self) -> None:
        cfg = self.cm.get()
        self.capture = ScreenCapture(cfg.roi_size)
        ema_dt = 0.0
        while not self._stop.is_set():
            try:
                cfg = self.cm.get()
                # ROI 即時調整
                if self.capture.roi_size != cfg.roi_size:
                    self.capture.roi_size = cfg.roi_size
                # 模型／尺寸變更 → 重建偵測器
                model_key = f"{cfg.model_size}|{cfg.imgsz}"
                if model_key != self._last_model_key:
                    self.detector.reload(model_size=cfg.model_size, imgsz=cfg.imgsz,
                                         confidence=cfg.confidence)
                    self._last_model_key = model_key
                elif abs(self.detector.confidence - cfg.confidence) > 1e-6:
                    self.detector.confidence = cfg.confidence

                t0 = time.perf_counter()
                frame = self.capture.grab()
                if frame is None:
                    time.sleep(0.05)
                    continue
                h, w = frame.shape[:2]
                cx, cy = w / 2.0, h / 2.0

                dets = self.detector.detect(frame)

                active = self.detector._model is not None and self.is_active(cfg)
                lock_conf, lock_pt, lock_box = 0.0, None, None
                if active and dets:
                    target = pick_target(dets, cx, cy)
                    if target is not None:
                        tx, ty = aim_point(target, cfg.aim_point)
                        dx, dy = compute_move(
                            tx, ty, cx, cy,
                            smoothing=cfg.smoothing,
                            deadzone_px=cfg.deadzone_px,
                            max_speed_px=cfg.max_speed_px,
                            sensitivity=cfg.sensitivity,
                        )
                        self.mouse.move_relative(dx, dy)
                        lock_conf = target.conf
                        lock_pt = (tx, ty)
                        lock_box = (target.x1, target.y1, target.x2, target.y2)

                dt = time.perf_counter() - t0
                ema_dt = dt if ema_dt == 0.0 else ema_dt * 0.9 + dt * 0.1
                self.state = replace(
                    self.state,
                    fps=1.0 / ema_dt if ema_dt > 0 else 0.0,
                    inference_ms=self.detector.last_infer_ms,
                    n_detections=len(dets),
                    detections=dets,
                    lock_conf=lock_conf,
                    lock_point=lock_pt,
                    lock_box=lock_box,
                    active=active,
                    backend=self.detector.backend,
                    aim_point_mode=cfg.aim_point,
                    model_ready=self.detector._model is not None,
                    error="",
                )
            except Exception as e:  # 引擎不因單幀錯誤死亡
                self.state = replace(self.state, error=f"{type(e).__name__}: {e}")
                time.sleep(0.2)
        if self.capture is not None:
            self.capture.close()
