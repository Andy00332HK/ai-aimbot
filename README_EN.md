# AI Aimbot (Single-Player FPS Aim Assist)

![Python](https://img.shields.io/badge/Python-3.10%2B-blue) ![CUDA](https://img.shields.io/badge/CUDA-12.x-green) ![License](https://img.shields.io/badge/License-MIT-yellow)

[English](README_EN.md) | [繁體中文](README.md)

Real-time object-detection aim assist: captures the center-screen ROI → YOLO11 detects humanoid enemies → transparent overlay draws boxes → smoothly moves the mouse to assist aiming.

> ⚠️ **Important:** This tool is for **single-player / offline games ONLY**. Using it in any online / multiplayer game violates the game's Terms of Service,
> may get your account banned, and ruins the experience for other players. You assume all responsibility for misuse.
> This project contains no anti-cheat bypass. Detection is fully visible on screen at all times.

---

## Features

- 🎯 **YOLO11 + ByteTrack tracking**: every target keeps a persistent ID, trajectory survives flicker, lock does not jump; humanoid enemies (soldiers, zombies, etc.) work with no training
- 🖥️ **Low-latency dxcam capture**: Desktop Duplication API 200+ FPS (auto fallback to mss)
- 🖥️ **Centered transparent overlay**: grid, detection boxes (green), locked box (red) drawn over the screen center, **click-through** so game input is unaffected
- 🎛️ **Graphical control panel**: all parameters live-tunable, auto-saved
- ⌨️ **Two activation modes**: hold-to-aim (HOLD, bindable to Shift / mouse side button) or toggle (TOGGLE)
- 🧠 **Head / chest aim point**: switch instantly via hotkey
- ⚡ **Measured on RTX 4060**: 47 FPS loop, 8–14 ms inference, almost no impact on game FPS
- 🔧 **Automatic backend fallback**: TensorRT FP16 → PyTorch CUDA → CPU

## System Requirements

- Windows 10 / 11
- Python 3.10–3.13
- NVIDIA GPU (recommended, pure CPU also works but slower)

## Install

1. Install [Python](https://www.python.org/downloads/) (check *Add to PATH*)
2. Double-click **`install.bat`** (auto-detects NVIDIA GPU and installs the matching PyTorch build + dependencies)
3. Run `python main.py`

On first launch the YOLO11n weights (~5.4 MB) auto-download to `models/`.

## Usage

| Action | Description |
|---|---|
| **Activate assist** | HOLD mode: hold Shift (or your custom mouse side button); TOGGLE mode: press F6 or click the panel button |
| **Head / chest switch** | Panel radio buttons or **F7** |
| **Input diagnostic** | In-game press **F9**: sends self-canceling test moves and measures actual on-screen motion, tells you if input reaches the game, how many pixels per mickey, and the suggested sensitivity (aim at a textured scene) |
| **Quit** | **F8** or panel "Quit" |

Use **Borderless Windowed** display mode in-game; exclusive fullscreen covers the overlay and may not be capturable.

## Control Panel Tuning Guide

| Setting | Description | Suggestion |
|---|---|---|
| **Activation mode** | HOLD = aim only while held; TOGGLE = on/off switch | HOLD for FPS, more intuitive |
| **Activation key** | Click "Change…" then press any key: any keyboard key or mouse left / right / middle / side | Right-button (handy while ADS); avoid WASD movement keys |
| **Aim point** | Head = top + 20%; Chest = top + 55% | Chest is more stable, less jitter |
| **Sticky lock** | ByteTrack persistent-ID lock on the same target; keeps pulling toward the last known position for ~0.2 s through flicker instead of jumping targets | Enable for multi-enemy close combat |
| **Model** | Fast (n) / Accurate (s) | Even s is plenty on an RTX 4060 |
| **Capture backend** | dxcam (200+ FPS low latency) / mss (compatible fallback) / auto | Leave on auto, switch to mss only if broken |
| **Injection backend** | SendInput (standard injection) / Interception (driver-level, sends as a real mouse) / auto | Default auto; only install the driver + use Interception when the game filters injected input (see FAQ) |
| **Inference size** | 320 / 416 / 640 | Smaller is faster; 640 is most accurate |
| **Scan ROI** | Side length of the center-screen detection area | Smaller is faster and focuses on close targets |
| **Confidence threshold** | Minimum confidence | 0.4–0.5; raise if too many false positives |
| **Convergence half-life (ms)** | Time for the error to halve, smaller pulls faster | 40–80; raise if it overshoots / feels twitchy |
| **Jitter suppression** | 1€ filter on the target point (strong smoothing when still, low lag when moving fast) | 30–50%; raise if tracking jitters |
| **Prediction** | Velocity feed-forward: compensates detection + control lag by aiming ahead of moving targets | 60–80%; 0 for stationary targets |
| **Mouse sensitivity** | Movement multiplier (compensates game / system sensitivity) | Raise if it under-pulls, lower if it overshoots |
| **Grid / boxes / overlay** | Display toggles | Keep only boxes when recording or playing for real |

## Project Structure

```
├── main.py              # entry point
├── install.bat          # one-click install (auto GPU detect)
├── config.json          # settings (auto read/written by panel)
├── aimbot/
│   ├── config.py        # settings management (range validation, thread-safe)
│   ├── capture.py       # screen capture (low-latency dxcam + mss fallback, auto downgrade)
│   ├── detector.py      # YOLO11 load + TensorRT export + backend fallback
│   ├── targeting.py     # target selection / aim point / smoothed motion
│   ├── mouse.py         # mouse injection factory (SendInput / driver-level Interception)
│   ├── diagnostic.py    # input diagnostic (F9: verify input arrival + measure gain)
│   ├── engine.py        # background main loop (capture → detect → aim)
│   ├── overlay.py       # centered transparent click-through overlay
│   └── hotkeys.py       # pynput global hotkeys (keyboard + mouse side buttons)
└── gui/
    └── panel.py         # Tkinter control panel
```

## FAQ

**Q: Mouse pulls the wrong distance / overshoots?**
Press **F9** first for input diagnostics — it measures the real gain and suggests a "Mouse sensitivity" value to paste into the panel, no more trial and error.

**Q: F9 says "input did not reach the game"?**
Check in order: ① run this tool as administrator (most common cause: when the game is elevated, Windows silently drops non-elevated input) ② set the game to borderless windowed ③ click the game view to focus it ④ make sure you can turn the camera in-game, not sitting in a menu.

**Q: Overlay shows boxes and the panel says running, but the crosshair does not move when activated?**
Press **F9** to split the cause: if it says "input did not reach the game" → the game is usually running as admin while this tool is not, restart this tool with **start_admin.bat** (or remove "run as administrator" from the game). If F9 says "✓ input OK" but the crosshair still does not move → the game engine filters software-injected input, switch to driver-level injection: ① download 1.0.1 zip from [Interception](https://github.com/oblitum/Interception/releases) ② as administrator run `command line installer\install-interception.exe /install` then **reboot** ③ `pip install interception-python pywin32` ④ set panel "Injection backend" to Interception (or leave on auto), then press F9 again to confirm gain.

**Q: Overlay does not appear?**
Switch the game to borderless windowed; or confirm panel "Enable center overlay" is checked.

**Q: Low detection rate on cartoon / stylized characters?**
Lower "Confidence threshold" to ~0.25 first — ByteTrack keeps tracking from low-confidence boxes so it tolerates more than pure detection; if still bad switch to the accurate (s) model. The real fix is fine-tuning the model for that game (collect screenshots + label, then train).

**Q: Not enough performance?**
Set inference size to 320, model to n, shrink ROI; with an NVIDIA GPU confirm the panel header shows `PyTorch CUDA`. Advanced users can `pip install tensorrt` to enable TensorRT FP16 (auto-exports on first run, faster after that).

**Q: Enemies not detected?**
This tool uses the COCO "person" class. Non-humanoid enemies (monsters, robots) need their own fine-tuned model from collected screenshots (advanced topic).

## License

MIT License — see [LICENSE](LICENSE).
