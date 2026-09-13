"""Tkinter 控制面板：所有設定即調即用，設定自動持久化。

所有跨執行緒 UI 更新經 UiDispatcher 佇列送回主執行緒。
"""
from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from aimbot.capture import CAPTURE_BACKENDS, CAPTURE_BACKEND_LABELS
from aimbot.config import (AIM_POINT_LABELS, IMGSZ_CHOICES, MODEL_SIZES,
                           MOUSE_BACKEND_LABELS, MOUSE_BACKENDS,
                           ConfigManager, hold_key_label)
from aimbot.engine import AimEngine

BG = "#14161c"
FG = "#e8eaf0"
ACCENT = "#e5484d"
ACCENT_OFF = "#30a46c"
CARD = "#1c1f27"
SUBTLE = "#8b90a0"

MODEL_LABELS = {"n": "快速（n・最流暢）", "s": "精準（s・較準）"}


class UiDispatcher:
    """把「要在 Tk 主執行緒執行的函式」排隊，由面板定期清空。"""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()

    def post(self, fn, *args):
        self.q.put((fn, args))

    def pump(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    pass
        except queue.Empty:
            pass


class ControlPanel:
    def __init__(self, root: tk.Tk, cm: ConfigManager, engine: AimEngine,
                 dispatcher: UiDispatcher, on_quit,
                 suspend_hotkeys=None, resume_hotkeys=None):
        self.root = root
        self.cm = cm
        self.engine = engine
        self.disp = dispatcher
        self.on_quit = on_quit
        self.suspend_hotkeys = suspend_hotkeys  # 擷取按鍵時暫停全域熱鍵，避免誤觸 F6-F8
        self.resume_hotkeys = resume_hotkeys
        self._updating_ui = False  # 防止程式更新 UI 時觸發回寫

        root.title("AI Aimbot 控制台（僅限單機遊戲）")
        root.configure(bg=BG)
        root.resizable(False, False)  # 尺寸由內容自適應，避免不同 DPI 下截斷
        root.protocol("WM_DELETE_WINDOW", on_quit)

        self._setup_style()
        self._build()

        self.root.after(120, self._refresh_stats)

    # ── 樣式 ──
    def _setup_style(self):
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, fieldbackground=CARD)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Sub.TLabel", background=BG, foreground=SUBTLE)
        style.configure("Card.TLabelframe", background=CARD, borderwidth=0)
        style.configure("Card.TLabelframe.Label", background=CARD,
                        foreground=FG, font=("Microsoft JhengHei UI", 10, "bold"))
        style.configure("Card.TFrame", background=CARD)
        style.configure("Card.TCheckbutton", background=CARD, foreground=FG)
        style.map("Card.TCheckbutton",
                  background=[("active", CARD)],
                  foreground=[("active", FG)])
        style.configure("Card.TRadiobutton", background=CARD, foreground=FG)
        style.map("Card.TRadiobutton",
                  background=[("active", CARD)],
                  foreground=[("active", FG)])
        style.configure("TCombobox", fieldbackground=CARD, background=CARD,
                        foreground=FG, arrowcolor=FG, bordercolor="#2a2e3a")
        style.map("TCombobox",
                  fieldbackground=[("readonly", CARD), ("disabled", CARD)],
                  foreground=[("readonly", FG), ("disabled", SUBTLE)],
                  background=[("readonly", CARD), ("active", "#2a2e3a")])
        for opt, val in (("*TCombobox*Listbox.background", CARD),
                         ("*TCombobox*Listbox.foreground", FG),
                         ("*TCombobox*Listbox.selectBackground", "#2a2e3a"),
                         ("*TCombobox*Listbox.selectForeground", FG),
                         ("*TCombobox*Listbox.font", ("Microsoft JhengHei UI", 10))):
            self.root.option_add(opt, val)
        style.configure("TScale", background=BG, troughcolor=CARD)
        style.configure("Start.TButton", background=ACCENT_OFF, foreground="white",
                        font=("Microsoft JhengHei UI", 13, "bold"), borderwidth=0)
        style.map("Start.TButton",
                  background=[("active", "#3cb371"), ("disabled", "#555")])
        style.configure("Stop.TButton", background=ACCENT, foreground="white",
                        font=("Microsoft JhengHei UI", 13, "bold"), borderwidth=0)
        style.map("Stop.TButton", background=[("active", "#ff6b6f")])
        style.configure("Small.TButton", background=CARD, foreground=FG)
        style.map("Small.TButton", background=[("active", "#2a2e3a")])

    def _card(self, parent, title) -> ttk.LabelFrame:
        return ttk.LabelFrame(parent, text=title, style="Card.TLabelframe", padding=10)

    # ── UI 建構 ──
    def _build(self):
        # 可捲動容器：內容放進 self.body，視窗高度超過 85% 螢幕時出現捲軸
        self.canvas = tk.Canvas(self.root, bg=BG, highlightthickness=0, bd=0)
        vbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(self.canvas)
        self._body_win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>",
                       lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>",
                         lambda e: self.canvas.itemconfigure(self._body_win, width=e.width))
        self.root.bind_all("<MouseWheel>", self._on_wheel)

        pad = {"fill": "x", "padx": 12, "pady": (6, 0)}
        parent = self.body

        # 狀態列
        status_row = ttk.Frame(parent, style="Card.TFrame")
        status_row.pack(**pad)
        self.dot = tk.Canvas(status_row, width=12, height=12, bg=BG, highlightthickness=0)
        self.dot.pack(side="left")
        self.status_label = ttk.Label(status_row, text="未啟動", font=("Microsoft JhengHei UI", 11, "bold"))
        self.status_label.pack(side="left", padx=(6, 0))
        self.backend_label = ttk.Label(status_row, text="", style="Sub.TLabel")
        self.backend_label.pack(side="right")

        # 大按鈕
        self.big_btn = ttk.Button(parent, text="▶  啟動輔助瞄準",
                                  style="Start.TButton", command=self._on_big_btn)
        self.big_btn.pack(fill="x", padx=12, pady=8, ipady=6)
        self.big_hint = ttk.Label(parent, text="", style="Sub.TLabel",
                                  font=("Microsoft JhengHei UI", 9))
        self.big_hint.pack(fill="x", padx=14)

        # ── 啟動設定 ──
        c1 = self._card(parent, "啟動設定")
        c1.pack(**pad)
        mode_row = ttk.Frame(c1, style="Card.TFrame")
        mode_row.pack(fill="x")
        self.mode_var = tk.StringVar()
        ttk.Radiobutton(mode_row, text="按住啟動（HOLD）", value="hold",
                        variable=self.mode_var, style="Card.TRadiobutton",
                        command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(mode_row, text="開關切換（TOGGLE）", value="toggle",
                        variable=self.mode_var, style="Card.TRadiobutton",
                        command=self._on_mode_change).pack(side="left", padx=(10, 0))
        key_row = ttk.Frame(c1, style="Card.TFrame")
        key_row.pack(fill="x", pady=(6, 0))
        ttk.Label(key_row, text="啟動鍵").pack(side="left")
        self.hold_key_var = tk.StringVar(value="Shift")
        ttk.Label(key_row, textvariable=self.hold_key_var,
                  font=("Microsoft JhengHei UI", 10, "bold")).pack(side="left", padx=(10, 0))
        ttk.Button(key_row, text="變更…", style="Small.TButton",
                   command=self._open_key_capture).pack(side="left", padx=(10, 0))
        ttk.Label(key_row, text="（鍵盤任意鍵或滑鼠左/右/中/側鍵）",
                  style="Sub.TLabel").pack(side="left", padx=(8, 0))
        aim_row = ttk.Frame(c1, style="Card.TFrame")
        aim_row.pack(fill="x", pady=(6, 0))
        ttk.Label(aim_row, text="瞄準部位").pack(side="left")
        self.aim_var = tk.StringVar()
        ttk.Radiobutton(aim_row, text="頭部", value="head", variable=self.aim_var,
                        style="Card.TRadiobutton", command=self._on_aim_change).pack(side="left", padx=(10, 0))
        ttk.Radiobutton(aim_row, text="胸口", value="body", variable=self.aim_var,
                        style="Card.TRadiobutton", command=self._on_aim_change).pack(side="left", padx=(6, 0))
        ttk.Label(aim_row, text="（熱鍵 F7 即時切換）", style="Sub.TLabel").pack(side="left", padx=(6, 0))

        # ── 偵測設定 ──
        c2 = self._card(parent, "偵測設定")
        c2.pack(**pad)
        model_row = ttk.Frame(c2, style="Card.TFrame")
        model_row.pack(fill="x")
        ttk.Label(model_row, text="模型").pack(side="left")
        self.model_combo = ttk.Combobox(model_row, state="readonly", width=18,
                                        values=[MODEL_LABELS[m] for m in MODEL_SIZES])
        self.model_combo.pack(side="left", padx=(10, 0))
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_change)
        ttk.Label(model_row, text="推論尺寸").pack(side="left", padx=(14, 0))
        self.imgsz_combo = ttk.Combobox(model_row, state="readonly", width=6,
                                        values=[str(v) for v in IMGSZ_CHOICES])
        self.imgsz_combo.pack(side="left", padx=(8, 0))
        self.imgsz_combo.bind("<<ComboboxSelected>>", self._on_imgsz_change)
        cap_row = ttk.Frame(c2, style="Card.TFrame")
        cap_row.pack(fill="x", pady=(6, 0))
        ttk.Label(cap_row, text="擷取後端").pack(side="left")
        self.capture_combo = ttk.Combobox(cap_row, state="readonly", width=18,
                                          values=[CAPTURE_BACKEND_LABELS[b]
                                                  for b in CAPTURE_BACKENDS])
        self.capture_combo.pack(side="left", padx=(10, 0))
        self.capture_combo.bind("<<ComboboxSelected>>", self._on_capture_change)
        mouse_row = ttk.Frame(c2, style="Card.TFrame")
        mouse_row.pack(fill="x", pady=(6, 0))
        ttk.Label(mouse_row, text="注入後端").pack(side="left")
        self.mouse_combo = ttk.Combobox(mouse_row, state="readonly", width=18,
                                        values=[MOUSE_BACKEND_LABELS[b]
                                                for b in MOUSE_BACKENDS])
        self.mouse_combo.pack(side="left", padx=(10, 0))
        self.mouse_combo.bind("<<ComboboxSelected>>", self._on_mouse_change)
        ttk.Label(mouse_row, text="（遊戲過濾注入輸入時用驅動級）",
                  style="Sub.TLabel").pack(side="left", padx=(8, 0))
        self._add_slider(c2, "偵測門檻", "confidence", 0.05, 0.95, 0.05,
                         fmt="{:.2f}")

        # ── 掃描範圍與顯示 ──
        c3 = self._card(parent, "掃描範圍與顯示")
        c3.pack(**pad)
        self._add_slider(c3, "掃描範圍 ROI(px)", "roi_size", 320, 1000, 20,
                         fmt="{:.0f}")
        grid_row = ttk.Frame(c3, style="Card.TFrame")
        grid_row.pack(fill="x")
        ttk.Label(grid_row, text="網格密度").pack(side="left")
        self.grid_combo = ttk.Combobox(grid_row, state="readonly", width=4,
                                       values=[str(v) for v in (4, 6, 8, 10, 12, 16)])
        self.grid_combo.pack(side="left", padx=(8, 0))
        self.grid_combo.bind("<<ComboboxSelected>>", self._on_grid_change)
        self.show_grid_var = tk.BooleanVar()
        ttk.Checkbutton(grid_row, text="顯示網格", variable=self.show_grid_var,
                        style="Card.TCheckbutton",
                        command=self._on_show_grid_change).pack(side="left", padx=(14, 0))
        show_row = ttk.Frame(c3, style="Card.TFrame")
        show_row.pack(fill="x", pady=(4, 0))
        self.show_det_var = tk.BooleanVar()
        ttk.Checkbutton(show_row, text="顯示偵測框", variable=self.show_det_var,
                        style="Card.TCheckbutton",
                        command=self._on_show_det_change).pack(side="left")
        self.show_overlay_var = tk.BooleanVar()
        ttk.Checkbutton(show_row, text="啟用置中覆蓋層", variable=self.show_overlay_var,
                        style="Card.TCheckbutton",
                        command=self._on_show_overlay_change).pack(side="left", padx=(14, 0))

        # ── 瞄準手感 ──
        c4 = self._card(parent, "瞄準手感")
        c4.pack(**pad)
        self.sticky_var = tk.BooleanVar()
        ttk.Checkbutton(c4, text="黏性鎖定（多人時鎖住同一目標不跳）",
                        variable=self.sticky_var, style="Card.TCheckbutton",
                        command=self._on_sticky_change).pack(fill="x")
        self._add_slider(c4, "收斂半衰期(ms)・越小拉越快", "half_life_ms", 20, 300, 10,
                         fmt="{:.0f}")
        self._add_slider(c4, "抖動抑制", "jitter_suppression", 0.0, 1.0, 0.05,
                         fmt="{:.0%}")
        self._add_slider(c4, "提前量（移動目標）", "aim_prediction", 0.0, 1.0, 0.05,
                         fmt="{:.0%}")
        self._add_slider(c4, "滑鼠靈敏度", "sensitivity", 0.2, 3.0, 0.1, fmt="{:.1f}")

        # ── 即時狀態 ──
        c5 = self._card(parent, "即時狀態")
        c5.pack(**pad)
        stats = ttk.Frame(c5, style="Card.TFrame")
        stats.pack(fill="x")
        self.stat_labels = {}
        for i, name in enumerate(("FPS", "推論延遲", "偵測數", "鎖定信心")):
            col = ttk.Frame(stats, style="Card.TFrame")
            col.grid(row=0, column=i, padx=(0, 16))
            v = ttk.Label(col, text="—", font=("Consolas", 12, "bold"))
            v.pack(anchor="w")
            ttk.Label(col, text=name, style="Sub.TLabel").pack(anchor="w")
            self.stat_labels[name] = v
        self.error_label = ttk.Label(c5, text="", foreground=ACCENT, background=CARD)
        self.error_label.pack(fill="x", pady=(4, 0))
        # 輸入診斷
        diag_row = ttk.Frame(c5, style="Card.TFrame")
        diag_row.pack(fill="x", pady=(6, 0))
        self.diag_label = ttk.Label(diag_row, text="輸入診斷：遊戲內按 F9",
                                    style="Sub.TLabel", wraplength=330,
                                    justify="left")
        self.diag_label.pack(side="left", fill="x", expand=True)
        ttk.Button(diag_row, text="F9", style="Small.TButton", width=5,
                   command=self._on_diag).pack(side="right")

        # ── 底部按鈕 ──
        bottom = ttk.Frame(parent)
        bottom.pack(fill="x", padx=12, pady=10)
        ttk.Button(bottom, text="還原預設", style="Small.TButton",
                   command=self._on_reset).pack(side="left")
        ttk.Button(bottom, text="離開", style="Small.TButton",
                   command=self.on_quit).pack(side="right")
        ttk.Label(parent, text="⚠ 僅供單機／離線遊戲使用，請勿用於任何連線遊戲",
                  foreground="#c7a15a", background=BG,
                  font=("Microsoft JhengHei UI", 9)).pack(fill="x", padx=14, pady=(0, 8))

        self._load_from_config()
        self.root.after(50, self._cap_window_height)

    def _on_wheel(self, event):
        """滾輪捲動面板；Combobox 保留自己的滾輪行為（改變選取）。"""
        w = self.root.winfo_containing(event.x_root, event.y_root)
        if w is not None and w.winfo_class() in ("TCombobox", "TSpinbox"):
            return
        self.canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _cap_window_height(self):
        """高度=內容高度，超過 85% 螢幕時鎖高（此時可捲動）。"""
        self.root.update_idletasks()
        bbox = self.canvas.bbox("all")
        content_h = bbox[3] if bbox else 400
        desired = content_h + 10
        h = min(desired, int(self.root.winfo_screenheight() * 0.85))
        w = self.body.winfo_reqwidth() + 40  # 內容寬 + 捲軸與邊距
        self.root.geometry(f"{w}x{h}")

    def _add_slider(self, parent, label, cfg_name, from_, to, res, fmt):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=(4, 0))
        top = ttk.Frame(row, style="Card.TFrame")
        top.pack(fill="x")
        ttk.Label(top, text=label).pack(side="left")
        val = ttk.Label(top, text="", font=("Consolas", 10, "bold"))
        val.pack(side="right")
        slider = ttk.Scale(row, from_=from_, to=to, orient="horizontal")
        slider.set(getattr(self.cm.get(), cfg_name))
        slider.pack(fill="x")
        slider.configure(command=lambda v, n=cfg_name, f=fmt, l=val: self._on_slider(n, v, f, l))
        self._sliders = getattr(self, "_sliders", {})
        self._sliders[cfg_name] = (slider, val, fmt)
        self._update_slider_label(cfg_name)

    def _update_slider_label(self, cfg_name):
        slider, val, fmt = self._sliders[cfg_name]
        val.configure(text=fmt.format(float(slider.get())))

    # ── 事件處理 ──
    def _on_slider(self, cfg_name, v, fmt, label):
        value = float(v)
        label.configure(text=fmt.format(value))
        self.cm.update(**{cfg_name: value})

    def _on_mode_change(self):
        self.cm.update(activation_mode=self.mode_var.get())
        self._refresh_hint()

    def _on_aim_change(self):
        self.cm.update(aim_point=self.aim_var.get())

    def _on_sticky_change(self):
        self.cm.update(sticky_lock=bool(self.sticky_var.get()))

    # ── 啟動鍵擷取對話框：按下任意鍵盤鍵或點擊滑鼠鍵即綁定 ──
    def _open_key_capture(self):
        import time as _time

        from pynput import keyboard, mouse

        if getattr(self, "_capturing", False):
            return
        self._capturing = True
        if self.suspend_hotkeys:
            self.suspend_hotkeys()

        dlg = tk.Toplevel(self.root)
        dlg.title("設定啟動鍵")
        dlg.configure(bg=CARD)
        dlg.resizable(False, False)
        dlg.grab_set()
        ttk.Label(dlg, text="請按下要綁定的按鍵\n鍵盤任意鍵，或點擊滑鼠左/右/中/側鍵",
                  font=("Microsoft JhengHei UI", 11)).pack(padx=24, pady=(18, 6))
        ttk.Label(dlg, style="Sub.TLabel",
                  text="Esc 或點擊本視窗內＝取消",
                  font=("Microsoft JhengHei UI", 9)).pack(pady=(0, 14))

        state = {"done": False, "t0": _time.time()}
        kb_l: list = [None]
        ms_l: list = [None]

        def finish(val: str | None):
            if state["done"]:
                return
            state["done"] = True
            for l in (kb_l[0], ms_l[0]):
                if l is not None:
                    try:
                        l.stop()
                    except Exception:
                        pass
            if self.resume_hotkeys:
                self.resume_hotkeys()
            self._capturing = False
            dlg.destroy()
            if val:
                self.cm.update(hold_key=val)
                self.hold_key_var.set(hold_key_label(val))
                self._refresh_hint()

        def in_dialog(x, y) -> bool:
            x0, y0 = dlg.winfo_rootx(), dlg.winfo_rooty()
            return x0 <= x <= x0 + dlg.winfo_width() and y0 <= y <= y0 + dlg.winfo_height()

        # pynput 回呼在其執行緒 → 一律丟回 Tk 主執行緒
        def on_key(key):
            if state["done"] or _time.time() - state["t0"] < 0.25:
                return
            name = getattr(key, "name", None)
            if not name:
                ch = getattr(key, "char", None)
                if ch and len(ch) == 1 and ch.isascii() and ch.isalnum():
                    name = ch.lower()
            # 左右修飾鍵正規化為 shift/ctrl/alt
            name = {"shift_l": "shift", "shift_r": "shift",
                    "ctrl_l": "ctrl", "ctrl_r": "ctrl",
                    "alt_l": "alt", "alt_r": "alt", "alt_gr": "alt"}.get(name, name)
            if name == "esc":
                self.disp.post(finish, None)
            elif name:
                self.disp.post(finish, f"kb:{name}")

        def on_click(x, y, button, pressed):
            if state["done"] or not pressed:
                return
            if _time.time() - state["t0"] < 0.25 or in_dialog(x, y):
                return
            self.disp.post(finish, f"mouse:{button.name}")

        kb_l[0] = keyboard.Listener(on_press=on_key)
        kb_l[0].daemon = True
        kb_l[0].start()
        ms_l[0] = mouse.Listener(on_click=on_click)
        ms_l[0].daemon = True
        ms_l[0].start()
        dlg.protocol("WM_DELETE_WINDOW", lambda: self.disp.post(finish, None))

    def _on_model_change(self, _evt=None):
        idx = self.model_combo.current()
        if idx >= 0:
            self.cm.update(model_size=MODEL_SIZES[idx])

    def _on_imgsz_change(self, _evt=None):
        self.cm.update(imgsz=int(self.imgsz_combo.get()))

    def _on_capture_change(self, _evt=None):
        idx = self.capture_combo.current()
        if idx >= 0:
            self.cm.update(capture_backend=CAPTURE_BACKENDS[idx])

    def _on_mouse_change(self, _evt=None):
        idx = self.mouse_combo.current()
        if idx >= 0:
            self.cm.update(mouse_backend=MOUSE_BACKENDS[idx])

    def _on_grid_change(self, _evt=None):
        self.cm.update(grid_cells=int(self.grid_combo.get()))

    def _on_show_grid_change(self):
        self.cm.update(show_grid=bool(self.show_grid_var.get()))

    def _on_show_det_change(self):
        self.cm.update(show_detections=bool(self.show_det_var.get()))

    def _on_show_overlay_change(self):
        self.cm.update(show_overlay=bool(self.show_overlay_var.get()))

    def _on_big_btn(self):
        self.engine.toggle_active()

    def _on_diag(self):
        self.engine.request_diagnostic()

    def _on_reset(self):
        cfg = self.cm.reset()
        self._load_from_config()

    # ── UI 與設定同步 ──
    def _load_from_config(self):
        cfg = self.cm.get()
        self._updating_ui = True
        try:
            self.mode_var.set(cfg.activation_mode)
            self.hold_key_var.set(hold_key_label(cfg.hold_key))
            self.aim_var.set(cfg.aim_point)
            self.sticky_var.set(cfg.sticky_lock)
            self.model_combo.current(MODEL_SIZES.index(cfg.model_size))
            self.imgsz_combo.set(str(cfg.imgsz))
            self.capture_combo.current(CAPTURE_BACKENDS.index(cfg.capture_backend))
            self.mouse_combo.current(MOUSE_BACKENDS.index(cfg.mouse_backend))
            self.grid_combo.set(str(cfg.grid_cells))
            self.show_grid_var.set(cfg.show_grid)
            self.show_det_var.set(cfg.show_detections)
            self.show_overlay_var.set(cfg.show_overlay)
            for name in self._sliders:
                slider, _val, _fmt = self._sliders[name]
                slider.set(getattr(cfg, name))
                self._update_slider_label(name)
        finally:
            self._updating_ui = False
        self._refresh_hint()

    def _refresh_hint(self):
        cfg = self.cm.get()
        if cfg.activation_mode == "hold":
            self.big_hint.configure(
                text=f"按住「{hold_key_label(cfg.hold_key)}」或點上方按鈕即可啟動")
        else:
            self.big_hint.configure(text="點上方按鈕或按 F6 切換開關")

    # ── 定時刷新（每 250ms） ──
    def _refresh_stats(self):
        self.disp.pump()
        st = self.engine.state
        cfg = self.cm.get()
        active = st.active
        self.dot.delete("all")
        color = ACCENT_OFF if active else "#666a76"
        self.dot.create_oval(2, 2, 10, 10, fill=color, outline=color)
        self.status_label.configure(
            text=("運行中" if active else "未啟動"),
            foreground=color if active else SUBTLE)
        self.backend_label.configure(
            text=f"{st.backend} · {st.capture_backend} · {st.mouse_backend}")
        big_on = self.engine._latch.is_set()
        self.big_btn.configure(
            text="■  停止輔助瞄準" if big_on else "▶  啟動輔助瞄準",
            style="Stop.TButton" if big_on else "Start.TButton")
        self.stat_labels["FPS"].configure(text=f"{st.fps:.0f}")
        self.stat_labels["推論延遲"].configure(text=f"{st.inference_ms:.1f}ms")
        self.stat_labels["偵測數"].configure(text=f"{st.n_detections}")
        self.stat_labels["鎖定信心"].configure(
            text=f"{st.lock_conf:.2f}" if st.lock_conf else "—")
        self.error_label.configure(text=st.error)
        diag = st.diag_message or "輸入診斷：遊戲內按 F9"
        self.diag_label.configure(
            text=diag,
            foreground=(ACCENT_OFF if "✓" in diag
                        else ACCENT if "✗" in diag else SUBTLE))
        self.root.after(250, self._refresh_stats)
