"""瞄準控制測試台：新舊演算法量化對比。

場景：
  A. 300px 甩槍到靜止目標（含 ±1px 偵測雜訊）@ 30/60/144 FPS
  B. 400px/s 水平移動目標追蹤 @ 60 FPS
  C. 檢測閃斷：外推 vs 凍結（黏性鎖定遺失容忍期的估計誤差）
  D. 相機平移：玩家轉身時的追蹤落後（GMC 場景的對照基準）
  E. 交叉目標：重獲寬限 vs 就近重選的鎖定切換次數
指標：到點時間、終點抖動（方向反轉數）、過衝量、移動目標平均落後
"""
from __future__ import annotations

import math
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aimbot.targeting import (REACQUIRE_FRAMES, REACQUIRE_IOU, AimController,
                              Detection, OneEuroFilter, box_iou,
                              one_euro_params, reacquire_score)

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

# ── 場景 C：檢測閃斷——外推 vs 凍結 ──
FPS = 60
DT = 1.0 / FPS
CROSS = 320.0


def dropout_scenario(drop_start=100, drop_len=8, frames=200):
    """目標 400px/s 向左移動，中途檢測閃斷 drop_len 幀。
    回傳 (凍結誤差列表, 外推誤差列表)——閃斷期間估計點 vs 真實瞄準點。"""
    vel_est = [0.0, 0.0]
    last_obs = None
    err_freeze, err_extrap = [], []
    for i in range(frames):
        t = i * DT
        true_x = 470.0 - 400.0 * t
        true_pt = (true_x, CROSS)
        obs = None if drop_start <= i < drop_start + drop_len else \
            (true_pt[0] + random.uniform(-1, 1), true_pt[1] + random.uniform(-1, 1))
        if obs is not None:
            if last_obs is not None:
                a = 0.4
                vel_est[0] += a * ((obs[0] - last_obs[0]) / DT - vel_est[0])
                vel_est[1] += a * ((obs[1] - last_obs[1]) / DT - vel_est[1])
            last_obs = obs
        elif last_obs is not None:
            # 閃斷第 n 幀
            n = i - drop_start + 1
            err_freeze.append(math.hypot(last_obs[0] - true_x, last_obs[1] - CROSS))
            decay = 0.5 ** (n * DT / 0.25)
            ex = last_obs[0] + vel_est[0] * n * DT * decay
            ey = last_obs[1] + vel_est[1] * n * DT * decay
            err_extrap.append(math.hypot(ex - true_x, ey - CROSS))
    return err_freeze, err_extrap


ef, ee = dropout_scenario()
mf, me = sum(ef) / len(ef), sum(ee) / len(ee)
print(f"\n閃斷8幀估計誤差  凍結(舊) {mf:>6.1f}px   外推(新) {me:>6.1f}px")
assert me < mf, f"外推應優於凍結: {me:.1f} vs {mf:.1f}"

# ── 場景 D：相機平移（玩家轉身）——控制層追蹤落後 ──
def pan_scenario(aim_prediction):
    pan_speed = 800.0   # px/s 的視角平移
    t0, t1 = 0.5, 0.9   # 平移時段
    pipe = NewPipeline(aim_prediction=aim_prediction)
    cx, cy = CROSS, CROSS
    errs_pan, errs_after = [], []
    t, recover_t, pan_end_err = 0.0, None, None
    while t < 1.6:
        world_x = 470.0
        pan = pan_speed * (min(t, t1) - t0) if t > t0 else 0.0
        pan = max(0.0, pan)
        tx = world_x - pan + random.uniform(-1, 1)
        dx, dy = pipe.step(tx, CROSS, cx, cy, DT)
        cx, cy = cx + dx, cy + dy
        if t0 < t < t1:
            errs_pan.append(cx - tx)
        if t >= t1:
            e = abs(cx - tx)
            errs_after.append(e)
            if pan_end_err is None:
                pan_end_err = e
            if e < 4.0 and recover_t is None:
                recover_t = t - t1
        t += DT
    return (sum(errs_pan) / len(errs_pan), pan_end_err, recover_t,
            [abs(e) for e in errs_after])


p0 = pan_scenario(0.0)
p7 = pan_scenario(0.7)
print(f"相機平移800px/s  無提前量落後 {p0[0]:>6.1f}px   提前量0.7落後 {p7[0]:>6.1f}px")
print(f"平移結束瞬間誤差 {p7[1]:.1f}px → 收斂(<4px)耗時 {p7[2]:.2f}s，終態均值誤差 {sum(p7[3][-30:]) / 30:.1f}px")
assert p7[2] is not None and p7[2] < 0.5, "平移結束應在 0.5s 內收斂"
assert sum(p7[3][-30:]) / 30 < 4.0, f"終態均值誤差過大: {sum(p7[3][-30:]) / 30:.1f}px"

# ── 場景 E：交叉目標——重獲寬限 vs 就近重選 ──
def simulate_lock(grace: bool) -> tuple[int, int]:
    """A 從準心緩慢右移（被鎖定），B 從左側快速追上並更靠近準心；
    A 在第 100~123 幀被遮擋（24 幀 > 10 幀容忍）後帶原 ID 重現。
    忠實鏡像 engine 鎖定邏輯，回傳 (鎖定切換次數, 最終鎖定 ID)。"""
    locked_id, last_id = 1, 1
    switches, lost, reacquire = 0, 0, 0
    prev_box, last_pt = None, None
    for i in range(220):
        t = i * DT
        ax, bx = 320.0 + 40.0 * t, 200.0 + 260.0 * t
        dets = []
        if not (100 <= i < 124):
            dets.append(Detection(ax - 20, 300, ax + 20, 360, 0.9, 1))
        dets.append(Detection(bx - 20, 300, bx + 20, 360, 0.9, 2))
        cx, cy = CROSS, CROSS

        target = next((d for d in dets
                       if locked_id != -1 and d.track_id == locked_id), None)
        if target is None:
            if locked_id != -1:
                if lost < 10 and last_pt is not None:
                    lost += 1
                    continue
                locked_id, reacquire = -1, 0   # 容忍期耗盡 → 進入重獲寬限
            if grace and prev_box is not None and reacquire < REACQUIRE_FRAMES:
                reacquire += 1
                lost += 1
                cand = min(dets, key=lambda d: reacquire_score(d, prev_box, cx, cy))
                if box_iou(prev_box, (cand.x1, cand.y1, cand.x2, cand.y2)) >= REACQUIRE_IOU:
                    target = cand
                elif last_pt is not None:
                    continue                    # 寬限期內維持外推，不搶鎖
                if reacquire >= REACQUIRE_FRAMES:
                    prev_box, last_pt = None, None
                    reacquire = 10 ** 9
        if target is None:
            target = min(dets, key=lambda d: math.hypot(d.cx - cx, d.cy - cy))
        if target.track_id != last_id:
            switches += 1
            last_id = target.track_id
        locked_id = target.track_id
        prev_box = (target.x1, target.y1, target.x2, target.y2)
        last_pt = (target.cx, target.cy)
        lost = 0
        reacquire = 0
    return switches, last_id


sw_old, final_old = simulate_lock(grace=False)
sw_new, final_new = simulate_lock(grace=True)
print(f"交叉目標鎖定切換  就近重選(舊) {sw_old} 次（最終鎖 id={final_old}）   "
      f"重獲寬限(新) {sw_new} 次（最終鎖 id={final_new}）")
assert sw_new < sw_old, f"寬限應減少切換: {sw_new} vs {sw_old}"
assert final_new == 1, "新策略應鎖回原目標 A"

print("\nBENCH_ASSERT_OK")
