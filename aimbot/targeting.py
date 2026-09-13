"""瞄準邏輯：目標選擇、瞄準點計算、平滑位移計算。"""
from __future__ import annotations

import math
from typing import Optional

from .detector import Detection

HEAD_RATIO = 0.20   # 框頂往下 20% ≈ 頭部
BODY_RATIO = 0.55   # 框頂往下 55% ≈ 胸口

STICKY_LOST_FRAMES = 10   # 黏性鎖定：目標偵測中斷的容忍幀數（約 0.2 秒）
STICKY_IOU_MIN = 0.2      # 前後幀視為同一目標的最小 IoU


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
