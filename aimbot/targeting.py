"""瞄準邏輯：目標選擇、瞄準點計算、平滑位移計算。"""
from __future__ import annotations

import math
from typing import Optional

from .detector import Detection

HEAD_RATIO = 0.20   # 框頂往下 20% ≈ 頭部
BODY_RATIO = 0.55   # 框頂往下 55% ≈ 胸口


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


def aim_point(det: Detection, mode: str) -> tuple[float, float]:
    """計算瞄準點（ROI 座標）。head=框頂+20%高、body=框頂+55%高。"""
    ratio = HEAD_RATIO if mode == "head" else BODY_RATIO
    return det.cx, det.y1 + det.h * ratio


def compute_move(
    target_x: float,
    target_y: float,
    crosshair_x: float,
    crosshair_y: float,
    smoothing: float,
    deadzone_px: float,
    max_speed_px: float,
    sensitivity: float,
) -> tuple[float, float]:
    """計算本幀滑鼠位移：每幀只移動誤差的一部分（smoothing），
    誤差小於死區不動，位移上限 max_speed 防止瞬移。
    """
    err_x = target_x - crosshair_x
    err_y = target_y - crosshair_y
    if math.hypot(err_x, err_y) < deadzone_px:
        return 0.0, 0.0
    dx = err_x * smoothing * sensitivity
    dy = err_y * smoothing * sensitivity
    dist = math.hypot(dx, dy)
    if dist > max_speed_px:
        scale = max_speed_px / dist
        dx *= scale
        dy *= scale
    return dx, dy
