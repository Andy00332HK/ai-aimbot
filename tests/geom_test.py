"""覆蓋層幾何測試：在 canvas 已知座標畫紅框，截圖驗證螢幕位置是否一致。"""
import ctypes
import subprocess
import sys
import time

import mss
import numpy as np
from PIL import Image

# 於獨立程序啟動一個與正式 Overlay 相同幾何的測試視窗
test_script = r'''
import ctypes, tkinter as tk
ctypes.windll.shcore.SetProcessDpiAwareness(2)
root = tk.Tk(); root.withdraw()
win = tk.Toplevel(root)
win.overrideredirect(True)
win.attributes("-topmost", True)
win.attributes("-transparentcolor", "#010101")
win.configure(bg="#010101")
win.geometry("640x640+640+220")
c = tk.Canvas(win, bg="#010101", highlightthickness=0, bd=0)
c.pack(fill="both", expand=True)
c.create_rectangle(320, 100, 500, 400, outline="#ff0000", width=3)
c.create_rectangle(0, 0, 639, 639, outline="#00ff00", width=2)
root.mainloop()
'''
proc = subprocess.Popen([sys.executable, "-c", test_script])
time.sleep(3)

with mss.MSS() as sct:
    shot = sct.grab({"left": 640, "top": 220, "width": 640, "height": 640})
img = np.frombuffer(shot.rgb, dtype=np.uint8).reshape(shot.height, shot.width, 3)
Image.fromarray(img).save("overlay_geom.png")

# 找紅色像素的範圍（canvas (320,100)-(500,400) 應對應影像同座標）
red_mask = (img[:, :, 0] > 200) & (img[:, :, 1] < 80) & (img[:, :, 2] < 80)
ys, xs = np.where(red_mask)
if len(xs):
    print(f"紅框實測範圍: x {xs.min()}-{xs.max()}, y {ys.min()}-{ys.max()}")
    print(f"預期範圍:     x 320-500, y 100-400")
else:
    print("找不到紅色像素！")
proc.terminate()
print("GEOM_DONE")
