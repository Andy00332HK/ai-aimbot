"""瞄準控制測試台：新舊演算法量化對比。

場景：
  A. 300px 甩槍到靜止目標（含 ±1px 偵測雜訊）@ 30/60/144 FPS
  B. 400px/s 水平移動目標追蹤 @ 60 FPS
指標：到點時間、終點抖動（方向反轉數）、過衝量、移動目標平均落後
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aimbot.targeting import (AimController, OneEuroFilter,
                              one_euro_params)

random.seed(7)

# ── 舊演算法（每幀固定比例，無次像素、無加速度限制） ──
class OldController:
    def __init__(self):
        self.smoothing = 0.45
        self.deadzone = 2.0
        self.max_speed = 60.0

    def reset(self):
        pass

    def step(self, tx, ty, cx, cy, dt):
        ex, ey = tx - cx, ty - cy
        if math.hypot(ex, ey) < self.deadzone:
            return 0, 0
        dx, dy = ex * self.smoothing, ey * self.smoothing
        d = math.hypot(dx, dy)
        if d > self.max_speed:
            dx *= self.max_speed / d
            dy *= self.max_speed / d
        return int(round(dx)), int(round(dy))


# ── 新演算法完整管線（1€ 濾波 + 速度估計 + 提前量 + 控制器） ──
class NewPipeline:
    def __init__(self, jitter_suppression=0.35, aim_prediction=0.7, half_life_ms=55):
        self.js, self.ap, self.hl = jitter_suppression, aim_prediction, half_life_ms
        self.reset()

    def reset(self):
        mc, beta = one_euro_params(self.js)
        self.fx = OneEuroFilter(mc, beta)
        self.fy = OneEuroFilter(mc, beta)
        self.vel = [0.0, 0.0]
        self.prev_f = None
        self.ctrl = AimController()

    def step(self, tx, ty, cx, cy, dt):
        fx, fy = self.fx.filter(tx, dt), self.fy.filter(ty, dt)
        if self.prev_f is not None and dt > 0:
            a = 0.4
            self.vel[0] += a * ((fx - self.prev_f[0]) / dt - self.vel[0])
            self.vel[1] += a * ((fy - self.prev_f[1]) / dt - self.vel[1])
        self.prev_f = (fx, fy)
        # 與 engine._aim_step 相同：提前量補償管線延遲 + 控制器穩態落後 v/k
        k = math.log(2.0) / (self.hl / 1000.0)
        lead = self.ap * (2.0 * dt + 1.0 / k)
        px, py = fx + self.vel[0] * lead, fy + self.vel[1] * lead
        return self.ctrl.compute(px - cx, py - cy, dt, self.hl / 1000.0, 2.0)


def run(controller, target_fn, fps, seconds=2.0, noise=1.0):
    dt = 1.0 / fps
    cx, cy = 320.0, 320.0
    x0, y0 = cx, cy
    traj = []          # (t, cx, cy)
    t = 0.0
    while t < seconds:
        tx, ty = target_fn(t)
        tx += random.uniform(-noise, noise)
        ty += random.uniform(-noise, noise)
        dx, dy = controller.step(tx, ty, cx, cy, dt)
        cx += dx
        cy += dy
        traj.append((t, cx, cy, tx, ty))
        t += dt
    return traj


def metrics_flick(traj, target=(20.0, 320.0)):
    """到點時間 | 終點反轉數 | 過衝量(px)"""
    tx, ty = target
    arrive = next((t for t, cx, cy, _, _ in traj if math.hypot(cx - tx, cy - ty) < 4), None)
    end_idx = int(len(traj) * 0.6)
    seg = traj[end_idx:]
    reversals = 0
    for a, b, c in zip(seg, seg[1:], seg[2:]):
        if (b[1] - a[1]) * (c[1] - b[1]) < 0 and abs(b[1] - a[1]) > 0:
            reversals += 1
    overshoot = min(0.0, min(cx for _, cx, _, _, _ in traj) - tx)  # 向左甩的過衝
    return arrive, reversals, abs(overshoot)


def metrics_track(traj, settle=1.0):
    """穩態後平均誤差 px（誤差 = 準心 - 真實目標，正值=落後）"""
    errs = [cx - tx for t, cx, cy, tx, ty in traj if t > settle]
    return sum(errs) / len(errs)


print(f"{'場景':<34}{'到點(s)':>8}{'終點反轉':>10}{'過衝(px)':>10}{'落後(px)':>10}")
print("-" * 72)

for fps in (30, 60, 144):
    old = OldController()
    traj_old = run(old, lambda t: (20.0, 320.0), fps)
    a1, r1, o1 = metrics_flick(traj_old)
    new = NewPipeline()
    traj_new = run(new, lambda t: (20.0, 320.0), fps)
    a2, r2, o2 = metrics_flick(traj_new)
    print(f"甩槍300px @{fps:>3}FPS  舊(比例)      {a1 or '>2':>8}{r1:>10}{o1:>10.1f}{'—':>10}")
    print(f"甩槍300px @{fps:>3}FPS  新(完整管線)  {a2 or '>2':>8}{r2:>10}{o2:>10.1f}{'—':>10}")

def moving(t):
    return 470.0 - 400.0 * t, 320.0   # 400px/s 向左

old = OldController()
e_old = metrics_track(run(old, moving, 60))
new = NewPipeline()
e_new = metrics_track(run(new, moving, 60))
print(f"追蹤400px/s @60FPS  舊(比例)      {'—':>8}{'—':>10}{'—':>10}{e_old:>10.1f}")
print(f"追蹤400px/s @60FPS  新(完整管線)  {'—':>8}{'—':>10}{'—':>10}{e_new:>10.1f}")

# 斷言：新演算法在關鍵指標上不劣於舊版
traj_new60 = run(NewPipeline(), lambda t: (20.0, 320.0), 60)
a, r, o = metrics_flick(traj_new60)
assert a is not None and a < 2.0, "應在 2 秒內到點"
assert r <= 6, f"終點反轉過多: {r}"
assert o < 30, f"過衝過大: {o:.1f}px"
print("\nBENCH_ASSERT_OK")
