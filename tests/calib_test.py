"""擷取對齊校準：engine 的 grab() 結果 vs 直接 mss 截圖同一 ROI，並排比對。"""
import mss
import numpy as np
from PIL import Image

from aimbot.capture import ScreenCapture

cap = ScreenCapture(640)
roi = cap.effective_roi
left, top = cap.roi_origin
print(f"screen={cap.screen_w}x{cap.screen_h} roi={roi} origin=({left},{top})")

frame = cap.grab()  # 引擎實際看到的 BGR
print(f"frame shape={frame.shape}")
Image.fromarray(frame[..., ::-1]).save("calib_engine.png")  # 轉回 RGB 存檔

with mss.MSS() as sct:
    shot = sct.grab({"left": left, "top": top, "width": roi, "height": roi})
direct = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3)
Image.fromarray(direct).save("calib_direct.png")

# 量化差異
diff = np.abs(frame.astype(int) - direct.astype(int)).mean()
print(f"mean_abs_diff={diff:.2f}  (0=完全一致)")
print("CALIB_DONE")
