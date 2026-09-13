"""煙霧測試 v3：啟動主程式 → 顯示人物照片於全螢幕（自行排程關閉）→ 截圖 → 結束。"""
import os
import subprocess
import sys
import time

import mss
from PIL import Image, ImageTk

import ultralytics
import tkinter as tk

BUS = os.path.join(os.path.dirname(ultralytics.__file__), "assets", "bus.jpg")

proc = subprocess.Popen([sys.executable, "main.py"])
time.sleep(8)  # 讓引擎與模型載入


def show_image_thread():
    """在 daemon 執行緒開全螢幕照片；顯示 7 秒後自行關閉（不跨執行緒碰 Tk）。"""
    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.configure(bg="black")
    img = Image.open(BUS).resize((960, 720))
    photo = ImageTk.PhotoImage(img)
    tk.Label(root, image=photo, bg="black").pack(expand=True)
    root.after(7000, root.destroy)
    root.mainloop()


import threading
t = threading.Thread(target=show_image_thread, daemon=True)
t.start()
time.sleep(4)  # 照片顯示中（視窗存活 0–7 秒，於第 4 秒截圖）

with mss.MSS() as sct:
    mon = sct.monitors[1]
    shot = sct.grab(mon)
img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
img.save("smoke_screen.png")
img.crop((620, 200, 1300, 900)).save("smoke_roi.png")
print("SCREENSHOT_SAVED", shot.size)
time.sleep(4)  # 等照片視窗自行關閉

proc.terminate()
try:
    proc.wait(timeout=5)
except subprocess.TimeoutExpired:
    proc.kill()
print("SMOKE_DONE")
