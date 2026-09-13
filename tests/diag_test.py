"""輸入診斷測試：位移量測 + 模擬遊戲端到端（三種案例）。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from aimbot.diagnostic import (DiagnosticResult, measure_shift,
                               run_input_diagnostic)

rng = np.random.default_rng(42)
WORLD = (rng.random((1400, 1400, 3)) * 255).astype(np.uint8)  # 全紋理世界


class FakeGame:
    """模擬 FPS：move() 依增益移動視角（dx→水平、dy→垂直）；gain=0 模擬輸入被擋。"""

    def __init__(self, gain: float = 0.4, texture: bool = True):
        self.gain = gain
        self.texture = texture
        self.camx = 500.0  # 視角（浮點累積）
        self.camy = 500.0
        self.frame_i = 0

    def move(self, dx: int, dy: int) -> None:
        self.camx += dx * self.gain
        self.camy += dy * self.gain

    def grab(self):
        self.frame_i += 1
        if not self.texture:
            return np.full((640, 640, 3), 128, dtype=np.uint8)
        cx, cy = int(round(self.camx)), int(round(self.camy))
        return WORLD[cy:cy + 640, cx:cx + 640].copy()


# ── 單元：位移量測 ──
a = WORLD[500:1140, 200:840].copy()
b = WORLD[500:1140, 200 - 37:840 - 37].copy()  # b 取景左移 37px → 內容在畫面中向右移 37px → dx=+37
dx, dy, conf = measure_shift(a, b)
assert dx == 37 and dy == 0 and conf > 0.9, f"量測錯誤: {dx},{dy},{conf}"
print(f"UNIT measure_shift: dx={dx} dy={dy} conf={conf:.2f} ✓")

# ── 端到端 1：輸入正常（gain 0.4）──
g = FakeGame(gain=0.4)
res = run_input_diagnostic(g.grab, g.move)
assert res.measurable and res.input_ok, f"應判定輸入正常: {res}"
assert abs(res.gain_x - 0.4) < 0.06, f"增益量測誤差過大: {res.gain_x}"
print(f"E2E 正常輸入: input_ok={res.input_ok} gain={res.gain_x:.2f} (期望 0.4) ✓")

# ── 端到端 2：輸入被擋（move 無效，畫面不動）──
class Blocked(FakeGame):
    def move(self, dx, dy):
        pass  # 遊戲丟棄輸入

res2 = run_input_diagnostic(Blocked(gain=0.4).grab, Blocked().move)
assert res2.measurable and not res2.input_ok, f"應判定輸入未到達: {res2}"
print(f"E2E 輸入被擋: input_ok={res2.input_ok} ✓")

# ── 端到端 3：無紋理場景（對著天空/白牆）──
g3 = FakeGame(gain=0.4, texture=False)
res3 = run_input_diagnostic(g3.grab, g3.move)
assert not res3.measurable, f"應判定無法測量: {res3}"
print(f"E2E 無紋理: measurable={res3.measurable} ✓")

print("DIAG_TESTS_ALL_OK")
