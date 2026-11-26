"""Screenshot collector for building your training set.

Usage:
    python training/collect.py            # saves to training/dataset_raw/
    python training/collect.py --interval 2.0 --key f8
      --interval: auto-capture every N seconds (0 = manual only)
      --key:      hotkey for manual capture (default F8)

Captures the primary monitor with mss, saves PNGs with timestamps.
Play the game, gather 500-2000 varied shots (maps / lighting / distances /
enemy poses), then label them with LabelImg (pip install labelImg, YOLO
format) and split into training/dataset/{images,labels}/{train,val}/.
Press Ctrl+C to stop.
"""
import argparse
import os
import time
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(PROJECT_ROOT, "training", "dataset_raw")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=0.0)
    ap.add_argument("--key", default="f8")
    args = ap.parse_args()

    import mss
    import mss.tools

    try:
        from pynput import keyboard
    except ImportError:
        keyboard = None
        print("pynput not installed; manual hotkey disabled, use --interval N.")

    os.makedirs(OUT_DIR, exist_ok=True)
    sct = mss.mss()
    mon = sct.monitors[0]  # full virtual desktop; crop later if multi-monitor
    count = [0]

    def snap() -> None:
        shot = sct.grab(mon)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = os.path.join(OUT_DIR, f"shot_{ts}.png")
        mss.tools.to_png(shot.rgb, shot.size, output=path)
        count[0] += 1
        print(f"[{count[0]}] {path}", flush=True)

    listener = None
    if keyboard is not None:
        try:
            hotkey = keyboard.Key[args.key.lower()]
        except KeyError:
            hotkey = keyboard.KeyCode.from_char(args.key.lower())

        def on_press(k) -> None:
            if k == hotkey:
                snap()

        listener = keyboard.Listener(on_press=on_press)
        listener.start()
        print(f"Press {args.key.upper()} to capture. Ctrl+C to stop.")

    try:
        if args.interval > 0:
            print(f"Auto-capture every {args.interval}s.")
            while True:
                snap()
                time.sleep(args.interval)
        elif listener is None:
            print("Nothing to do: install pynput or pass --interval N.")
        else:
            while True:
                time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        if listener is not None:
            listener.stop()
    print(f"Saved {count[0]} screenshots to {OUT_DIR}")


if __name__ == "__main__":
    main()
