"""瞄準邏輯：目標選擇、瞄準點計算、訊號濾波與平滑控制。

控制模型（AimController）：
- 幀率無關指數收斂：move = err × (1 − exp(−k·dt))，k = ln2/半衰期
- 雙區增益：誤差小於細調區時降增益，消除終點震盪
- 加速度限制：輸出速度變化率有上限，拉槍有自然的加減速
- 次像素累積：小數位移留到下幀，準心能真正到點
"""
from __future__ import annotations

import math
from typing import Optional

from .detector import Detection

HEAD_RATIO = 0.20   # 框頂往下 20% ≈ 頭部
BODY_RATIO = 0.55   # 框頂往下 55% ≈ 胸口

STICKY_LOST_FRAMES = 10   # 黏性鎖定：目標偵測中斷的容忍幀數（約 0.2 秒）
STICKY_IOU_MIN = 0.2      # 前後幀視為同一目標的最小 IoU

# 重獲寬限：鎖定完全丟失後，優先找回與上鎖框重疊的目標（防鄰近敵人搶鎖）
REACQUIRE_FRAMES = 15     # 寬限幀數（約 0.3 秒）
REACQUIRE_IOU = 0.05      # 與上鎖框 IoU ≥ 此值才視為「原目標重新出現」

# AimController 內建常數（專家調校值，不暴露 UI）
FINE_ZONE_PX = 15.0       # 細調區半徑：誤差小於此值降增益
FINE_GAIN = 0.35          # 細調區增益倍率
MAX_ACCEL_PX_S2 = 60000.0 # 輸出加速度上限 px/s²
MAX_SPEED_PX_S = 8000.0   # 輸出速度安全上限 px/s


def pick_target(dets: list[Detection], crosshair_x: float, crosshair_y: float) -> Optional[Detection]:
    """選擇偵測框中心離準心最近的目標。"""
    best: Optional[Detection] = None
    best_dist = float("inf")
    for d in dets:
        dist = math.hypot(d.cx - crosshair_x, d.cy - crosshair_y)
        if dist < best_dist:
            best_dist = dist
            best = d
    return best


def box_iou(a: tuple[float, float, float, float],
            b: tuple[float, float, float, float]) -> float:
    """兩個 (x1, y1, x2, y2) 框的 IoU。"""
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0.0:
        return 0.0
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return inter / (area_a + area_b - inter + 1e-6)


def match_locked(dets: list[Detection],
                 prev_box: tuple[float, float, float, float]) -> Optional[Detection]:
    """黏性鎖定：在前幀偵測中找出與上一幀鎖定框重疊最大的同一目標。"""
    best: Optional[Detection] = None
    best_iou = STICKY_IOU_MIN
    for d in dets:
        v = box_iou(prev_box, (d.x1, d.y1, d.x2, d.y2))
        if v > best_iou:
            best_iou = v
            best = d
    return best


def reacquire_score(det: Detection, prev_box: tuple[float, float, float, float],
                    crosshair_x: float, crosshair_y: float) -> float:
    """重獲評分（越小越好）：準心距離為主，與上鎖框重疊越多越優先。

    用於鎖定完全丟失後的寬限期：優先找回「原目標」（即使它暫時被
    鄰近敵人更靠近準心），IoU 除法項讓重疊者得分大幅下降。"""
    dist = math.hypot(det.cx - crosshair_x, det.cy - crosshair_y)
    iou = box_iou(prev_box, (det.x1, det.y1, det.x2, det.y2))
    return dist / (0.25 + iou)


def aim_point(det: Detection, mode: str) -> tuple[float, float]:
    """計算瞄準點（ROI 座標）。head=框頂+20%高、body=框頂+55%高。"""
    ratio = HEAD_RATIO if mode == "head" else BODY_RATIO
    return det.cx, det.y1 + det.h * ratio


def one_euro_params(suppression: float) -> tuple[float, float]:
    """抖動抑制滑桿（0–1）→ 1€ 濾波器參數（min_cutoff, beta）。
    0 = 幾乎不濾波；1 = 最強除抖。對數內插。"""
    s = min(1.0, max(0.0, float(suppression)))
    min_cutoff = 30.0 * (0.4 / 30.0) ** s
    beta = 1.0 * (0.007 / 1.0) ** s
    return min_cutoff, beta


class OneEuroFilter:
    """1€ 濾波器（Casiez & Roussel, CHI 2012）：速度自適應低通濾波。
    訊號靜止時強力除抖、快移時低延遲。每軸一個實例。"""

    def __init__(self, min_cutoff: float = 1.0, beta: float = 0.02,
                 d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self._freq = 60.0
        self._x_prev: Optional[float] = None
        self._dx_prev = 0.0

    @staticmethod
    def _alpha(cutoff: float, freq: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        te = 1.0 / freq
        return 1.0 / (1.0 + tau / te)

    def filter(self, x: float, dt: float) -> float:
        if dt <= 0:
            return self._x_prev if self._x_prev is not None else x
        self._freq = 1.0 / dt
        if self._x_prev is None:
            self._x_prev = x
            self._dx_prev = 0.0
            return x
        dx = (x - self._x_prev) * self._freq
        a_d = self._alpha(self.d_cutoff, self._freq)
        edx = self._dx_prev + a_d * (dx - self._dx_prev)
        self._dx_prev = edx
        cutoff = self.min_cutoff + self.beta * abs(edx)
        a = self._alpha(cutoff, self._freq)
        self._x_prev += a * (x - self._x_prev)
        return self._x_prev


class AimController:
    """幀率無關的瞄準位移控制器（僅在 engine 執行緒使用）。"""

    def __init__(self):
        self._remain = [0.0, 0.0]     # 次像素殘差累積
        self._last_vel = [0.0, 0.0]   # 上幀輸出速度（加速度限制用）
        self.reset()

    def reset(self) -> None:
        self._remain = [0.0, 0.0]
        self._last_vel = [0.0, 0.0]

    def compute(self, err_x: float, err_y: float, dt: float,
                half_life_s: float, deadzone_px: float,
                sensitivity: float = 1.0) -> tuple[int, int]:
        """回傳本幀滑鼠位移（整數 mickey，已含次像素累積與倍率）。"""
        if dt <= 0:
            return 0, 0
        dist = math.hypot(err_x, err_y)
        if dist < deadzone_px:
            self._remain = [0.0, 0.0]  # 進死區：清殘差避免爆量
            self._last_vel = [0.0, 0.0]
            return 0, 0
        # 幀率無關指數收斂
        k = math.log(2.0) / max(half_life_s, 1e-3)
        alpha = 1.0 - math.exp(-k * dt)
        # 雙區增益：細調區降增益防終點震盪
        if dist < FINE_ZONE_PX:
            alpha *= FINE_GAIN
        vx, vy = err_x * alpha, err_y * alpha
        # 加速度限制
        max_dv = MAX_ACCEL_PX_S2 * dt
        for i in range(2):
            v, lv = (vx, vy)[i], self._last_vel[i]
            dv = v - lv
            if abs(dv) > max_dv:
                v = lv + math.copysign(max_dv, dv)
            if i == 0:
                vx = v
            else:
                vy = v
        self._last_vel = [vx, vy]
        # 速度安全上限
        speed = math.hypot(vx, vy)
        cap = MAX_SPEED_PX_S * dt
        if speed > cap:
            vx *= cap / speed
            vy *= cap / speed
        # 次像素累積 + 靈敏度倍率
        out = []
        for i, v in enumerate((vx, vy)):
            total = v * sensitivity + self._remain[i]
            iv = int(round(total))
            self._remain[i] = total - iv
            out.append(iv)
        return out[0], out[1]
