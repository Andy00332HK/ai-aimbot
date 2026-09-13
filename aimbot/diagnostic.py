"""輸入診斷：驗證滑鼠輸入是否到達遊戲，並量測視角移動增益（px/mickey）。

流程：送出左右/上下互相抵銷的已知位移，前後比對畫面位移
（模板匹配，取樣區避開螢幕中央的固定準心與 HUD）。

結論三種：
  ✓ 輸入正常（附增益與建議靈敏度）
  ✗ 輸入未到達遊戲（畫面完全沒動）
  ？ 無法測量（場景缺乏紋理，請對準有細節的場景再試）
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np

GrabFn = Callable[[], "np.ndarray | None"]
MoveFn = Callable[[int, int], None]

# 量測參數
HX_MICKEYS = 150      # 水平測試位移（右再左，互相抵銷）
HY_MICKEYS = 100      # 垂直測試位移（下再上）
SETTLE_S = 0.15       # 量測前靜置
RENDER_S = 0.13       # 送出位移後等遊戲渲染
CONF_MIN = 0.55       # 模板匹配最低信心度


@dataclass(frozen=True)
class DiagnosticResult:
    input_ok: bool        # 輸入有到達且視角有移動
    measurable: bool      # 場景可測量（紋理足夠）
    gain_x: float         # 水平增益 px/mickey（0=沒動）
    gain_y: float
    confidence: float
    detail: str = ""


def measure_shift(a: np.ndarray, b: np.ndarray) -> tuple[int, int, float]:
    """量測 b 相對 a 的畫面位移（dx, dy, 信心度）。
    模板取自左上象限，避開中央準心與 HUD。"""
    h, w = a.shape[:2]
    tx, ty = int(w * 0.18), int(h * 0.18)
    tw, th = int(w * 0.28), int(h * 0.28)
    tpl = cv2.cvtColor(a[ty:ty + th, tx:tx + tw], cv2.COLOR_BGR2GRAY)
    if float(tpl.std()) < 3.0:
        return 0, 0, 0.0  # 平坦畫面（天空／白牆）無可匹配特徵
    img = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    r = 320  # 搜尋半徑
    x0, y0 = max(0, tx - r), max(0, ty - r)
    x1, y1 = min(w, tx + tw + r), min(h, ty + th + r)
    res = cv2.matchTemplate(img[y0:y1, x0:x1], tpl, cv2.TM_CCOEFF_NORMED)
    _, maxv, _, maxloc = cv2.minMaxLoc(res)
    if not np.isfinite(maxv):
        return 0, 0, 0.0
    dx = (x0 + maxloc[0]) - tx
    dy = (y0 + maxloc[1]) - ty
    return dx, dy, float(maxv)


def _send_smooth(move: MoveFn, dx: int, dy: int, steps: int = 6) -> None:
    for i in range(steps):
        move(round(dx / steps), round(dy / steps))
        time.sleep(0.01)


def run_input_diagnostic(grab: GrabFn, move: MoveFn) -> DiagnosticResult:
    base = grab()
    if base is None:
        return DiagnosticResult(False, False, 0.0, 0.0, 0.0, "擷取失敗")
    time.sleep(SETTLE_S)

    # 水平：右移 → 量測 → 左移回來 → 量測（兩次取平均，抗漂移）
    _send_smooth(move, HX_MICKEYS, 0)
    time.sleep(RENDER_S)
    f1 = grab()
    _send_smooth(move, -HX_MICKEYS, 0)
    time.sleep(RENDER_S)
    f2 = grab()
    # 垂直：下移 → 量測 → 上移回來
    _send_smooth(move, 0, HY_MICKEYS)
    time.sleep(RENDER_S)
    f3 = grab()
    _send_smooth(move, 0, -HY_MICKEYS)

    if f1 is None or f2 is None or f3 is None:
        return DiagnosticResult(False, False, 0.0, 0.0, 0.0, "擷取失敗")

    dx1, _, c1 = measure_shift(base, f1)
    dx2, _, c2 = measure_shift(f1, f2)
    _, dy1, c3 = measure_shift(f2, f3)
    conf = min(c1, c2, c3)
    if conf < CONF_MIN:
        return DiagnosticResult(False, False, 0.0, 0.0, conf,
                                "場景缺乏可辨識紋理")

    shift_x = (abs(dx1) + abs(dx2)) / 2.0
    gain_x = shift_x / HX_MICKEYS
    gain_y = abs(dy1) / HY_MICKEYS
    input_ok = gain_x > 0.02  # 150 滑格應至少動 3px
    return DiagnosticResult(input_ok, True, gain_x, gain_y, conf,
                            f"水平 {dx1:+d}/{dx2:+d}px 垂直 {dy1:+d}px")


def format_result(r: DiagnosticResult) -> str:
    if not r.measurable:
        return ("診斷：？ 無法測量——請對準有紋理的場景（室內／牆面細節），"
                "在遊戲內可轉視角時按 F9 重試")
    if not r.input_ok:
        return ("診斷：✗ 輸入未到達遊戲（畫面完全沒動）——依序檢查："
                "① 工具以管理員執行 ② 遊戲設為無邊框視窗 "
                "③ 點一下遊戲畫面取得焦點 ④ 確認在遊戲內而非選單")
    sugg = 1.0 / r.gain_x if r.gain_x > 0.05 else 1.0
    return (f"診斷：✓ 輸入正常 | 水平 {r.gain_x:.2f} px/滑格 · "
            f"垂直 {r.gain_y:.2f} | 建議滑鼠靈敏度 ≈ {sugg:.2f}")
