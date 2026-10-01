"""
ui.py — CustomTkinter 现代化深色界面
三个页签：密码库 / 人脸 / 设置，底部为运行日志。
"""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import cv2
from PIL import Image, ImageDraw, ImageTk
import customtkinter as ctk

import matcher
import screen
from autofill import run_autofill

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

BG = "#1a1a1a"
CARD = "#2b2b2b"
ACCENT = "#1f6aa5"
DANGER = "#a51f2e"


class FaceScanOverlay:
    """人脸识别动画：0.9s 黑圆→胶囊→圆角方块，之后播放 faceid 帧序列（30fps）。"""

    def __init__(self, app):
        self.app = app
        self.tl = None
        self.canvas = None
        self.photo = None
        self.frames = []   # faceid 帧 PhotoImage 列表
        self._frames_loaded = False

    def _resource_dir(self):
        import sys
        if getattr(sys, "frozen", False):
            return sys._MEIPASS
        return os.path.dirname(os.path.abspath(__file__))

    def _load_frames(self):
        import glob
        import numpy as np
        d = os.path.join(self._resource_dir(), "faceid")
        files = sorted(glob.glob(os.path.join(d, "FaceID*.png")))[::2]   # 抽一半帧减少卡顿
        try:
            self.app._log(f"查找 faceid 帧：{d}，找到 {len(files)} 个")
        except Exception:
            pass
        R = 24
        # 预生成圆角 mask（200x200）
        mask_img = Image.new("L", (200, 200), 0)
        ImageDraw.Draw(mask_img).rounded_rectangle([0, 0, 199, 199], radius=R, fill=255)
        mask_arr = np.array(mask_img)   # 255=保留, 0=透明
        for f in files:
            img = Image.open(f).convert("RGB")
            img = img.resize((200, 200), Image.LANCZOS)
            arr = np.array(img)
            # 圆角外像素设为透明色 (15,15,15)
            arr[mask_arr == 0] = (15, 15, 15)
            self.frames.append(ImageTk.PhotoImage(Image.fromarray(arr)))

    def _ease(self, t):
        return 1 - (1 - t) ** 3

    def start(self):
        self.app.after(0, self._show)

    def _show(self):
        self.tl = tk.Toplevel(self.app)
        self.tl.overrideredirect(True)
        self.tl.attributes("-topmost", True)
        W = H = 200
        sw = self.tl.winfo_screenwidth()
        sh = self.tl.winfo_screenheight()
        # 屏幕顶部中间（灵动岛位置）
        y = 16
        self.tl.geometry(f"{W}x{H}+{sw//2 - W//2}+{y}")
        # 背景透明：把 #0f0f0f 设为透明色，只显示黑色形状
        self.tl.configure(bg="#0f0f0f")
        try:
            self.tl.attributes("-transparentcolor", "#0f0f0f")
        except Exception:
            pass
        self.canvas = tk.Canvas(self.tl, width=W, height=H, bg="#0f0f0f",
                                highlightthickness=0, bd=0)
        self.canvas.pack()
        self.W = W
        self.H = H
        self.t0 = time.time()
        self.finished = False
        self.tl.lift()
        self.tl.update_idletasks()
        self._tick()
        # 帧加载放到变形动画之后（不阻塞窗口显示）
        if not self._frames_loaded:
            self.tl.after(50, self._do_load_frames)

    def _do_load_frames(self):
        try:
            self._load_frames()
            self._frames_loaded = True
            try:
                self.app._log(f"faceid 帧加载完成：{len(self.frames)} 帧")
            except Exception:
                pass
        except Exception as e:
            try:
                import traceback
                self.app._log(f"faceid 帧加载失败：{e}\n{traceback.format_exc()}")
            except Exception:
                pass

    def _tick(self):
        if self.finished or self.tl is None or not self.tl.winfo_exists():
            return
        el = (time.time() - self.t0) / 0.9   # 变形总时长 0.9s
        if el >= 1:
            # 变形结束，停在圆角方块（等识别结果）
            self._render_shape(180, 180, 24)
            return
        if el < 0.45:
            p = self._ease(el / 0.45)
            w = 100 + (220 - 100) * p
            h = 100
            cr = 50
        else:
            p = self._ease((el - 0.45) / 0.55)
            w = 220
            h = 100 + (220 - 100) * p
            cr = 50 - (50 - 30) * p
        self._render_shape(w, h, cr)
        self.tl.after(16, self._tick)

    def _play_sound(self):
        try:
            import ctypes
            path = os.path.join(self._resource_dir(), "faceid", "faceid.m4a")
            if not os.path.exists(path):
                return
            # 用 MCI 异步播放 m4a
            ctypes.windll.winmm.mciSendStringW('close snd', None, 0, None)
            ctypes.windll.winmm.mciSendStringW(
                f'open "{path}" type mpegvideo alias snd', None, 0, None)
            ctypes.windll.winmm.mciSendStringW('play snd from 0', None, 0, None)
        except Exception:
            pass

    def on_success(self):
        """人脸验证通过：播 faceid 帧动画+音效，然后变绿勾。"""
        def _do():
            if self.tl is None:
                return
            self._play_sound()
            self._play_frames()
            self.tl.after(20 * 50, self._show_check)
        self.app.after(0, _do)

    def _show_check(self):
        if self.finished or self.tl is None:
            return
        self.finished = True
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (self.W, self.H), (15, 15, 15, 255))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([10, 10, 190, 190], radius=24, fill=(0, 0, 0, 255))
        cx, cy = self.W//2, self.H//2
        d.line([(cx-28, cy+2), (cx-8, cy+22), (cx+30, cy-18)],
               fill=(80, 230, 120, 255), width=8, joint="curve")
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.tl.after(900, self._close)

    def on_fail(self):
        """人脸验证失败：直接画红叉。"""
        def _do():
            self.finished = True
            if self.tl is None:
                return
            self.canvas.delete("all")
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (self.W, self.H), (15, 15, 15, 255))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([10, 10, 190, 190], radius=24, fill=(0, 0, 0, 255))
            cx, cy = self.W//2, self.H//2
            d.line([(cx-22, cy-22), (cx+22, cy+22)], fill=(255, 90, 90, 255), width=8)
            d.line([(cx+22, cy-22), (cx-22, cy+22)], fill=(255, 90, 90, 255), width=8)
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
            self.tl.after(900, self._close)
        self.app.after(0, _do)

    def _play_frames(self):
        """30fps 播放 faceid 帧序列（圆角遮罩已加好，保持窗口透明）。"""
        if self.finished or self.tl is None:
            return
        if not self.frames:
            # 帧还在加载，100ms 后重试
            self.tl.after(100, self._play_frames)
            return
        self.fi_idx = 0
        self._next_frame()

    def _next_frame(self):
        if self.finished or self.tl is None or not self.tl.winfo_exists():
            return
        if not hasattr(self, "_img_item") or self._img_item is None:
            self._img_item = self.canvas.create_image(0, 0, anchor="nw", image=self.frames[0])
        else:
            self.canvas.itemconfig(self._img_item, image=self.frames[self.fi_idx])
        self.fi_idx += 1
        if self.fi_idx < len(self.frames):
            self.tl.after(50, self._next_frame)
        else:
            self.fi_idx = len(self.frames) - 1

    def _render_shape(self, w, h, cr):
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (self.W, self.H), (15, 15, 15, 255))
        d = ImageDraw.Draw(img)
        x0 = self.W/2 - w/2
        y0 = self.H/2 - h/2
        d.rounded_rectangle([x0, y0, x0+w, y0+h], radius=cr, fill=(0, 0, 0, 255))
        self.photo = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)

    def end(self, ok: bool):
        def _do():
            self.finished = True
            if self.tl is None:
                return
            self.canvas.delete("all")   # 清掉帧，绿色圆脸消失
            # 画圆角黑方块
            from PIL import Image, ImageDraw
            img = Image.new("RGBA", (self.W, self.H), (15, 15, 15, 255))
            d = ImageDraw.Draw(img)
            d.rounded_rectangle([20, 20, 240, 240], radius=30, fill=(0, 0, 0, 255))
            cx, cy = self.W//2, self.H//2
            if ok:
                d.line([(cx-28, cy+2), (cx-8, cy+22), (cx+30, cy-18)],
                       fill=(80, 230, 120, 255), width=8, joint="curve")
            else:
                d.line([(cx-22, cy-22), (cx+22, cy+22)], fill=(255, 90, 90, 255), width=8)
                d.line([(cx+22, cy-22), (cx-22, cy+22)], fill=(255, 90, 90, 255), width=8)
            self.photo = ImageTk.PhotoImage(img)
            self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
            self.tl.after(1000, self._close)
        self.app.after(0, _do)

    def _close(self):
        try:
            self.tl.destroy()
        except Exception:
            pass
        self.tl = None


class AddServiceWizard(ctk.CTkToplevel):
    """新增服务向导：截屏预览 → 点击用户名框 → 点击密码框 → 填表单 → 保存。"""

    def __init__(self, master, vault):
        super().__init__(master)
        self.title("新增服务（点击标坐标）")
        self.transient(master)
        self.grab_set()
        self.configure(fg_color=BG)
        self.vault = vault
        self.saved = False
        self.user_pt = None
        self.pwd_pt = None
        self.step = "user"
        self.raw_bgr, self.monitor = screen.capture_bgr(max_width=1400)
        self.scale = 700 / self.raw_bgr.shape[1]
        self.preview = self.raw_bgr[:, :, ::-1].copy()
        self.preview = cv2.resize(self.preview, None, fx=self.scale, fy=self.scale,
                                  interpolation=cv2.INTER_AREA)
        self.photo = ImageTk.PhotoImage(Image.fromarray(self.preview))
        self.snap_bgrs = [self.raw_bgr]
        self._build()

    def _build(self):
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(10, 4))
        self.hint = tk.StringVar(value="第 1 步：请在下方预览图中点击【用户名输入框】位置")
        ctk.CTkLabel(top, textvariable=self.hint, text_color="#ff6b6b",
                     font=ctk.CTkFont(size=13, weight="bold")).pack(anchor="w")

        self.canvas = tk.Canvas(self, width=700, height=int(700 * self.raw_bgr.shape[0] / self.raw_bgr.shape[1]),
                                bg="#202020", highlightthickness=0)
        self.canvas.pack(padx=12)
        self.canvas.create_image(0, 0, anchor="nw", image=self.photo)
        self.canvas.bind("<Button-1>", self._on_click)

        form = ctk.CTkFrame(self)
        form.pack(fill="x", padx=12, pady=8)
        self.vars = {}
        fields = [("service", "服务名 *"), ("url", "网址"),
                  ("username", "用户名"), ("password", "密码"), ("note", "备注")]
        for i, (key, label) in enumerate(fields):
            ctk.CTkLabel(form, text=label, width=90, anchor="w").grid(row=i, column=0, padx=10, pady=5, sticky="w")
            v = tk.StringVar()
            self.vars[key] = v
            show = "*" if key == "password" else ""
            ctk.CTkEntry(form, textvariable=v, width=340, show=show).grid(row=i, column=1, padx=10, pady=5)
        ctk.CTkLabel(form, text="自定义宏", width=90, anchor="nw").grid(row=5, column=0, padx=10, pady=5, sticky="nw")
        self.macro_txt = ctk.CTkTextbox(form, width=340, height=60)
        self.macro_txt.grid(row=5, column=1, padx=10, pady=5)
        ctk.CTkLabel(form, text="宏每行：click x,y / type 文本 / key ENTER / sleep 秒",
                     text_color="#888", font=ctk.CTkFont(size=11)).grid(
            row=6, column=1, sticky="w", padx=10)

        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=10)
        ctk.CTkButton(btns, text="📷 屏幕截图（自动最小化）", command=self._capture_screen,
                      fg_color="#3a7d44", hover_color="#2d6336").pack(side="left", padx=6)
        ctk.CTkButton(btns, text="✓ 保存此服务", command=self._save).pack(side="left", padx=6)
        ctk.CTkButton(btns, text="取消", command=self.destroy,
                      fg_color="#555", hover_color="#777").pack(side="left", padx=6)

    def _capture_screen(self):
        self.iconify()
        self.update_idletasks()
        time.sleep(0.6)
        try:
            bgr, _ = screen.capture_bgr(max_width=1400)
            self.snap_bgrs.append(bgr)
        finally:
            self.deiconify()
            self.lift()
        self.hint.set(f"已追加登录页截图，共 {len(self.snap_bgrs)} 张。可继续点坐标或再截多张。")

    def _on_click(self, event):
        rx = event.x / 700.0
        ry = event.y / self.canvas.winfo_height()
        if self.step == "user":
            self.user_pt = (rx, ry)
            self.canvas.create_oval(event.x - 6, event.y - 6, event.x + 6, event.y + 6,
                                    outline="#ff4444", width=3)
            self.hint.set("已标记用户名框（红点）。第 2 步：点击【密码输入框】位置")
            self.step = "pwd"
        elif self.step == "pwd":
            self.pwd_pt = (rx, ry)
            self.canvas.create_oval(event.x - 6, event.y - 6, event.x + 6, event.y + 6,
                                    outline="#4488ff", width=3)
            self.hint.set("已标记密码框（蓝点）。请填写账号信息后保存。")
            self.step = "done"

    def _save(self):
        service = self.vars["service"].get().strip()
        if not service:
            messagebox.showwarning("提示", "服务名不能为空", parent=self)
            return
        if not self.pwd_pt:
            messagebox.showwarning("提示", "请先在预览图上点击密码输入框位置", parent=self)
            return
        entry = self.vault.add(
            service=service,
            url=self.vars["url"].get().strip(),
            username=self.vars["username"].get().strip(),
            password=self.vars["password"].get(),
            note=self.vars["note"].get().strip(),
            user_coord=self.user_pt,
            pwd_coord=self.pwd_pt,
            macro=self.macro_txt.get("1.0", "end").strip(),
        )
        files = []
        for i, bgr in enumerate(self.snap_bgrs):
            files.append(matcher.save_snapshot(bgr, entry["id"], i))
        self.vault.update(entry["id"], snapshots=files)
        self.saved = True
        self.destroy()


class EntryDialog(ctk.CTkToplevel):
    def __init__(self, master, title="密码条目", entry: dict | None = None):
        super().__init__(master)
        self.title(title)
        self.configure(fg_color=BG)
        self.entry = entry
        self.result: dict | None = None
        self.transient(master)
        self.grab_set()

        fields = [
            ("service", "服务名 *"),
            ("url", "网址"),
            ("username", "用户名"),
            ("password", "密码"),
            ("note", "备注"),
        ]
        self.vars = {}
        for row, (key, label) in enumerate(fields):
            ctk.CTkLabel(self, text=label, width=90, anchor="w").grid(
                row=row, column=0, padx=10, pady=6, sticky="w")
            var = tk.StringVar(value=(entry or {}).get(key, ""))
            self.vars[key] = var
            show = "*" if key == "password" else ""
            ctk.CTkEntry(self, textvariable=var, width=320, show=show).grid(
                row=row, column=1, padx=10, pady=6)
        ctk.CTkLabel(self, text="自定义宏", width=90, anchor="nw").grid(
            row=len(fields), column=0, padx=10, pady=6, sticky="nw")
        self.macro_txt = ctk.CTkTextbox(self, width=320, height=60)
        self.macro_txt.insert("1.0", (entry or {}).get("macro", ""))
        self.macro_txt.grid(row=len(fields), column=1, padx=10, pady=6)
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.grid(row=len(fields) + 1, column=0, columnspan=2, pady=12)
        ctk.CTkButton(btns, text="保存", command=self._save).pack(side="left", padx=8)
        ctk.CTkButton(btns, text="取消", command=self.destroy,
                      fg_color="#555", hover_color="#777").pack(side="left", padx=8)

    def _save(self):
        service = self.vars["service"].get().strip()
        if not service:
            messagebox.showwarning("提示", "服务名不能为空", parent=self)
            return
        self.result = {k: v.get().strip() for k, v in self.vars.items()}
        self.result["macro"] = self.macro_txt.get("1.0", "end").strip()
        self.destroy()


class App(ctk.CTk):
    def __init__(self, config, vault, face_engine):
        super().__init__()
        self.config = config
        self.vault = vault
        self.face_engine = face_engine
        self.title("人脸识别自动填充密码")
        self.geometry("820x640")
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._busy = False
        self._setup_tree_style()
        self._build()

    def _setup_tree_style(self):
        style = ttk.Style()
        try:
            style.theme_use("default")
        except Exception:
            pass
        style.configure("Treeview", background="#2b2b2b", foreground="white",
                        fieldbackground="#2b2b2b", rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background="#1f1f1f", foreground="white",
                        relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)])

    def _build(self):
        self.tabview = ctk.CTkTabview(self, fg_color=CARD, segmented_button_selected_color=ACCENT)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.tab_vault = self.tabview.add("密码库")
        self.tab_face = self.tabview.add("人脸")
        self.tab_settings = self.tabview.add("设置")
        self._build_vault()
        self._build_face()
        self._build_settings()

        log_frame = ctk.CTkFrame(self, fg_color=CARD)
        log_frame.pack(fill="x", padx=10, pady=(4, 10))
        ctk.CTkLabel(log_frame, text="运行日志", text_color="#aaa",
                     font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w", padx=10, pady=(6, 0))
        self.log_text = ctk.CTkTextbox(log_frame, height=110, fg_color="#202020",
                                       text_color="#ddd", font=ctk.CTkFont(family="Consolas", size=11))
        self.log_text.pack(fill="x", padx=10, pady=6)

    def _build_vault(self):
        f = self.tab_vault
        top = ctk.CTkFrame(f, fg_color="transparent")
        top.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(top, text="🔍 搜索", font=ctk.CTkFont(size=13)).pack(side="left", padx=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._refresh_vault())
        ctk.CTkEntry(top, textvariable=self.search_var, width=200,
                     placeholder_text="搜索服务名或用户名").pack(side="left", padx=4)
        for text, cmd, color in (
                ("＋ 新增", self._add_entry, "#3a7d44"),
                ("编辑", self._edit_entry, ACCENT),
                ("删除", self._del_entry, DANGER),
                ("刷新", self._refresh_vault, "#555")):
            ctk.CTkButton(top, text=text, width=80, command=cmd,
                          fg_color=color, hover_color="#777").pack(side="right", padx=3)

        cols = ("service", "username", "url", "snaps", "updated")
        headers = {"service": "服务名", "username": "用户名", "url": "网址",
                   "snaps": "截图数", "updated": "更新时间"}
        self.tree = ttk.Treeview(f, columns=cols, show="headings", height=12)
        for c in cols:
            self.tree.heading(c, text=headers[c])
            width = {"service": 180, "username": 130, "url": 240, "snaps": 80, "updated": 140}[c]
            self.tree.column(c, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=6, pady=4)
        self._refresh_vault()

    def _build_face(self):
        f = self.tab_face
        box = ctk.CTkFrame(f)
        box.pack(fill="x", padx=10, pady=10)
        self.face_status = tk.StringVar(value=self._face_status_text())
        ctk.CTkLabel(box, textvariable=self.face_status, wraplength=560, justify="left",
                     font=ctk.CTkFont(size=13)).pack(anchor="w", padx=16, pady=(14, 6))
        btns = ctk.CTkFrame(box, fg_color="transparent")
        btns.pack(anchor="w", padx=16, pady=(0, 8))
        ctk.CTkButton(btns, text="📷 开始注册（摄像头采集）", command=self._register_face,
                      fg_color="#3a7d44", hover_color="#2d6336").pack(side="left", padx=6)
        ctk.CTkButton(btns, text="清除已注册人脸", command=self._clear_face,
                      fg_color=DANGER, hover_color="#7a1822").pack(side="left", padx=6)
        tip = ("注册时请保持正对摄像头、光线充足，程序会自动采集多帧生成模板。\n"
               "验证时（按 Ctrl+Alt+M 触发填充）会重新采集画面并与模板比对。")
        ctk.CTkLabel(box, text=tip, text_color="#888", justify="left").pack(
            anchor="w", padx=16, pady=(0, 14))

    def _build_settings(self):
        f = self.tab_settings
        rows = [
            ("api_key", "视觉模型 API Key（已不使用）", 40, True),
            ("model", "模型名", 20, False),
            ("picui_token", "PICUI 图床 Token（可选）", 40, True),
            ("face_threshold", "人脸相似度阈值 (0~1，越大越严)", 10, False),
            ("camera_index", "摄像头索引", 6, False),
        ]
        self.set_vars = {}
        for i, (key, label, width, secret) in enumerate(rows):
            ctk.CTkLabel(f, text=label, anchor="w").grid(row=i, column=0, padx=14, pady=8, sticky="w")
            var = tk.StringVar(value=str(self.config.get(key, "")))
            self.set_vars[key] = var
            ctk.CTkEntry(f, textvariable=var, width=width * 8,
                          show="*" if secret else "").grid(row=i, column=1, padx=14, pady=8)
        ctk.CTkLabel(f, text="全局热键：Ctrl+Alt+M（不可改，触发一次自动填充）",
                     text_color="#888").grid(row=len(rows), column=0, columnspan=2, sticky="w", padx=14, pady=10)
        ctk.CTkButton(f, text="保存设置", command=self._save_settings,
                      fg_color="#3a7d44", hover_color="#2d6336").grid(
            row=len(rows) + 1, column=0, columnspan=2, pady=8)
        ctk.CTkButton(f, text="测试本地匹配（截当前屏）", command=self._test_vision).grid(
            row=len(rows) + 2, column=0, columnspan=2, pady=6)

    # ---------------- 密码库 ----------------
    def _refresh_vault(self):
        kw = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for e in self.vault.entries:
            if kw and kw not in e.get("service", "").lower() \
                    and kw not in e.get("username", "").lower():
                continue
            self.tree.insert("", "end", iid=e["id"], values=(
                e.get("service", ""), e.get("username", ""), e.get("url", ""),
                len(e.get("snapshots") or []), e.get("updated", "")))

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            return None
        eid = sel[0]
        return next((e for e in self.vault.entries if e["id"] == eid), None)

    def _add_entry(self):
        dlg = AddServiceWizard(self, self.vault)
        self.wait_window(dlg)
        if dlg.saved:
            self._refresh_vault()
            self._log("已新增服务（含登录页截图与坐标）")

    def _edit_entry(self):
        e = self._selected()
        if not e:
            messagebox.showinfo("提示", "请先选中一条记录")
            return
        dlg = EntryDialog(self, title="编辑密码条目", entry=e)
        self.wait_window(dlg)
        if dlg.result:
            self.vault.update(e["id"], **dlg.result)
            self._refresh_vault()
            self._log(f"已更新条目：{e['service']}")

    def _del_entry(self):
        e = self._selected()
        if not e:
            messagebox.showinfo("提示", "请先选中一条记录")
            return
        if messagebox.askyesno("确认", f"删除「{e['service']}」这条记录？"):
            matcher.delete_snapshots(e.get("snapshots"))
            self.vault.delete(e["id"])
            self._refresh_vault()
            self._log(f"已删除条目：{e['service']}")

    # ---------------- 人脸 ----------------
    def _face_status_text(self):
        n = len(self.face_engine.templates)
        return f"已注册人脸模板：{n} 帧" + ("（完成注册后才允许自动填充）" if n == 0 else "")

    def _register_face(self):
        if self._busy:
            return
        self._busy = True
        self.face_status.set("正在打开摄像头采集（约 3 秒），请正视摄像头…")
        threading.Thread(target=self._register_worker, daemon=True).start()

    def _register_worker(self):
        def done(text):
            self.face_status.set(text)
            self._busy = False
            self._log(text)

        try:
            cap = cv2.VideoCapture(int(self.config.get("camera_index", 0)))
            if not cap.isOpened():
                self.after(0, lambda: done("错误：无法打开摄像头，请检查设备与权限"))
                return
            frames = []
            for _ in range(10):
                ok, frame = cap.read()
                if ok:
                    frames.append(frame)
                time.sleep(0.15)
            cap.release()
            if len(frames) < 3:
                self.after(0, lambda: done("错误：摄像头采集帧数不足"))
                return
            templates, n = self.face_engine.register_from_frames(frames)
            if n == 0:
                self.after(0, lambda: done("错误：未能从画面中检测到人脸，请正对摄像头重试"))
                return
            self.face_engine.templates = templates
            self.face_engine.save_templates()
            self.after(0, lambda: done(f"注册成功：已保存 {n} 帧人脸模板"))
        except Exception as e:
            self.after(0, lambda: done(f"注册出错：{e}"))

    def _clear_face(self):
        self.face_engine.clear_templates()
        self.face_status.set(self._face_status_text())
        self._log("已清除人脸模板")

    # ---------------- 设置 ----------------
    def _save_settings(self):
        try:
            thr = float(self.set_vars["face_threshold"].get())
            if not (0 < thr < 1):
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "相似度阈值必须是 0~1 之间的数字")
            return
        self.config.set("api_key", self.set_vars["api_key"].get().strip())
        self.config.set("model", self.set_vars["model"].get().strip())
        self.config.set("picui_token", self.set_vars["picui_token"].get().strip())
        self.config.set("face_threshold", thr)
        self.config.set("camera_index", self.set_vars["camera_index"].get().strip())
        self.face_engine.set_threshold(thr)
        self._log("设置已保存（识别已切换为本地截图匹配，不依赖视觉模型）")

    def _test_vision(self):
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._vision_test_worker, daemon=True).start()

    def _vision_test_worker(self):
        def done(text):
            self._busy = False
            self._log(text)
        try:
            self._log("正在截取当前屏幕并做本地匹配测试…")
            bgr, _ = screen.capture_bgr()
            scored = matcher.match_best(bgr, self.vault.entries)
            if scored:
                out = "，".join(f"{e['service']}({s:.2f})" for s, e in scored)
                self.after(0, lambda: done(f"本地匹配到：{out}"))
            else:
                self.after(0, lambda: done("未匹配到任何已保存的登录页（可新增服务）"))
        except Exception as e:
            self.after(0, lambda: done(f"匹配测试失败：{e}"))

    # ---------------- 日志 ----------------
    def _log(self, text):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _on_close(self):
        self.destroy()

    # ---------------- 热键触发的填充 ----------------
    def handle_hotkey(self):
        if self._busy:
            self._log("上一个任务尚未结束，忽略本次热键")
            return
        self._busy = True
        self._log("===== 热键触发：开始自动填充 =====")
        threading.Thread(target=self._autofill_worker, daemon=True).start()

    def _autofill_worker(self):
        overlay = FaceScanOverlay(self)
        result = run_autofill(
            self.config, self.vault, self.face_engine,
            lambda bgr: matcher.match_best(bgr, self.vault.entries),
            notify=lambda stage, text: self.after(0, lambda: self._log(f"[{stage}] {text}")),
            choose=self._choose_candidate,
            face_verify=True,
            face_ui=overlay,
        )
        self.after(0, self._finish_autofill, result)

    def _finish_autofill(self, result):
        self._busy = False
        self._log(f"结果：{result.message}")
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        if result.ok:
            messagebox.showinfo("自动填充", f"✅ {result.message}\n服务：{result.entry.get('service')}")
        else:
            messagebox.showwarning("自动填充未完成", result.message)

    def _choose_candidate(self, candidates):
        q = queue.Queue()

        def _popup():
            top = ctk.CTkToplevel(self)
            top.title("选择要填充的条目")
            top.configure(fg_color=BG)
            top.transient(self)
            top.grab_set()
            box = tk.Listbox(top, width=70, height=min(len(candidates) + 1, 8),
                             bg="#2b2b2b", fg="white", selectbackground=ACCENT,
                             relief="flat", font=("Microsoft YaHei", 11))
            box.pack(padx=16, pady=16)
            for e in candidates:
                box.insert("end", f"{e.get('service')}  |  {e.get('username')}  |  {e.get('url')}")
            box.selection_set(0)

            def _pick():
                idx = box.curselection()
                q.put(candidates[idx[0]] if idx else None)
                top.destroy()

            def _cancel():
                q.put(None)
                top.destroy()

            btns = ctk.CTkFrame(top, fg_color="transparent")
            btns.pack(pady=(0, 14))
            ctk.CTkButton(btns, text="填充此条", command=_pick).pack(side="left", padx=8)
            ctk.CTkButton(btns, text="取消", command=_cancel,
                          fg_color="#555", hover_color="#777").pack(side="left", padx=8)
            top.protocol("WM_DELETE_WINDOW", _cancel)

        self.after(0, _popup)
        return q.get(timeout=120)
