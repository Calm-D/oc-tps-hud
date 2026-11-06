"""Windows 浮层后端：透明窗口、跟随客户端、自动明暗配色。

非 Windows 平台请在 __main__ 里拦截，不要导入本模块。
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes

from . import config, logs

GWL_HWNDPARENT = -8
WS_EX_TOPMOST = 0x00000008

CHIP = {"light": "#FFFFFF", "dark": "#15181D"}

KEY_LIGHT = "#FDFDFD"
KEY_DARK = "#0D0F12"

PALETTE = {
    "light": {
        "text": "#5C6672", "dim": "#78828E", "dim2": "#8B95A1",
        "ok": "#3E9B69", "warn": "#B07F35", "bad": "#B85555", "mute": "#9AA3AD",
    },
    "dark": {
        "text": "#D6DDE6", "dim": "#A2ACB8", "dim2": "#828C97",
        "ok": "#54C98C", "warn": "#DDB05F", "bad": "#DE7A7A", "mute": "#8B949F",
    },
}


def fmt_tok(x):
    if x >= 10000:
        return "%.1fk" % (x / 1000.0)
    if x >= 1000:
        return "%.2fk" % (x / 1000.0)
    return "%d" % int(x)


def fmt_sec(s):
    s = int(max(0, s))
    if s >= 3600:
        return "%d:%02d:%02d" % (s // 3600, s % 3600 // 60, s % 60)
    return "%02d:%02d" % (s // 60, s % 60)


class Halo:
    """描边文字：四个方向各画一层，正文叠在最上，任何底色上都能读。"""

    OFFSETS = ((-1, 0), (1, 0), (0, -1), (0, 1))

    def __init__(self, canvas, x, y, font, anchor="w"):
        self.c = canvas
        self.font = font
        self.anchor = anchor
        self.x, self.y = x, y
        self.rings = [canvas.create_text(x + dx, y + dy, anchor=anchor, text="",
                                         font=font, fill="") for dx, dy in self.OFFSETS]
        self.main = canvas.create_text(x, y, anchor=anchor, text="", font=font, fill="")

    def set(self, text, color, halo):
        for item in self.rings:
            self.c.itemconfigure(item, text=text, fill=halo)
        self.c.itemconfigure(self.main, text=text, fill=color)

    def recolor(self, color, halo):
        for item in self.rings:
            self.c.itemconfigure(item, fill=halo)
        self.c.itemconfigure(self.main, fill=color)

    def move_to(self, x, y=None):
        self.x, self.y = x, (self.y if y is None else y)
        for (dx, dy), item in zip(self.OFFSETS, self.rings):
            self.c.coords(item, self.x + dx, self.y + dy)
        self.c.coords(self.main, self.x, self.y)


class ClientWindow:
    """定位 OpenCode 客户端主窗口（按面积取最大），供浮层停靠。"""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

    def __init__(self, min_size=(480, 360)):
        self.u = ctypes.windll.user32
        self.k = ctypes.windll.kernel32
        self.min_size = min_size
        self.hwnd = None
        self._proto()

    def _proto(self):
        # ctypes 默认按 32 位 int 解释返回值，句柄高位会被截断
        self.k.OpenProcess.restype = wintypes.HANDLE
        self.k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.k.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self.k.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.u.FindWindowW.restype = wintypes.HWND
        self.u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        self.u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.u.IsWindow.argtypes = [wintypes.HWND]
        self.u.IsIconic.argtypes = [wintypes.HWND]
        self.u.IsWindowVisible.argtypes = [wintypes.HWND]

    def _is_client_pid(self, pid):
        h = self.k.OpenProcess(self.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if not self.k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return False
            return os.path.basename(buf.value).lower() == "opencode.exe"
        finally:
            self.k.CloseHandle(h)

    def find(self):
        if self.hwnd and self.u.IsWindow(self.hwnd):
            return self.hwnd
        self.hwnd = None
        hits = []
        u = self.u
        min_w, min_h = self.min_size

        @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        def cb(h, _):
            try:
                if not u.IsWindowVisible(h):
                    return True
                pid = wintypes.DWORD()
                u.GetWindowThreadProcessId(h, ctypes.byref(pid))
                if not self._is_client_pid(pid.value):
                    return True
                r = wintypes.RECT()
                u.GetWindowRect(h, ctypes.byref(r))
                w, hh = r.right - r.left, r.bottom - r.top
                if w < min_w or hh < min_h:
                    return True
                hits.append((w * hh, h))
            except Exception:
                pass
            return True

        u.EnumWindows(cb, 0)
        if hits:
            hits.sort(reverse=True)
            self.hwnd = hits[0][1]
        return self.hwnd

    def state(self):
        h = self.find()
        if not h:
            return "none", None
        if self.u.IsIconic(h):
            return "min", None
        r = wintypes.RECT()
        self.u.GetWindowRect(h, ctypes.byref(r))
        return "ok", (r.left, r.top, r.right, r.bottom)

    def virtual_screen(self):
        return (self.u.GetSystemMetrics(76), self.u.GetSystemMetrics(77),
                self.u.GetSystemMetrics(78), self.u.GetSystemMetrics(79))


class UI:
    def __init__(self, engine, cfg, tr):
        import tkinter as tk
        from tkinter import font as tkfont

        self.engine = engine
        self.cfg = cfg
        self.tr = tr
        self.topmost = bool(cfg.get("topmost", False))
        self._owner = None
        self.settings = cfg
        self.client = ClientWindow(tuple(cfg.get("client_min_size", (480, 360))))
        self.u = self.client.u
        self.mode = cfg.get("theme", "auto")
        self.theme = "light"
        self._pos = None
        self.scale = None
        self._drag = None
        self._press = None
        self._moved = False
        self._last_error = ""

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        root = tk.Tk()
        root.title("oc-tps-hud")
        root.overrideredirect(True)
        root.attributes("-topmost", self.topmost)
        root.configure(bg=KEY_LIGHT)
        try:
            root.attributes("-transparentcolor", KEY_LIGHT)
        except Exception:
            logs.write("error.log", "transparentcolor unsupported; fallback to solid bg")

        try:
            alpha = float(cfg.get("alpha", 0.95))
        except Exception:
            alpha = 0.95
        alpha = max(0.5, min(1.0, alpha))
        root.attributes("-alpha", alpha)

        win = cfg.get("window") or {}
        self.layout = cfg.get("layout", "bar")
        if self.layout == "bar":
            W = int(win.get("bar_width", 560))
            H = int(win.get("bar_height", 26))
        else:
            W = int(win.get("width", 268))
            H = int(win.get("height", 128))
        self.W, self.H = W, H
        self.base_w = W
        self.margin = int(win.get("margin", 12))
        self.bottom_offset = int(win.get("bottom_offset", 104))
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry("%dx%d+%d+%d" % (W, H, sw - W - 28, sh - H - 96))

        c = tk.Canvas(root, width=W, height=H, bg=KEY_LIGHT, highlightthickness=0, borderwidth=0)
        c.pack(fill="both", expand=True)
        self.c = c

        ui_font = config.font_family("ui", cfg)
        num_font = config.font_family("number", cfg)
        self.f_status = tkfont.Font(family=ui_font, size=9)
        self.f_num = tkfont.Font(family=num_font, size=24, weight="bold")
        self.f_line = tkfont.Font(family=ui_font, size=9)
        self.status_w = W - 30 - 16

        if self.layout == "bar":
            self.f_bar = tkfont.Font(family=ui_font, size=10)
            self.bar_bg = c.create_rectangle(-30, -30, -20, -20, fill="", outline="")
            self.dot = c.create_oval(-20, -20, -14, -14, fill="", outline="")
            self.bar = Halo(c, W // 2, H // 2, (ui_font, 10), anchor="center")
        else:
            self.dot = c.create_oval(13, 12, 21, 20, fill="", outline="")
            self.status = Halo(c, 27, 16, (ui_font, 9))
            self.num = Halo(c, 13, 54, (num_font, 24, "bold"))
            self.unit = Halo(c, 110, 61, (num_font, 9))
            self.line1 = Halo(c, 14, 90, (ui_font, 9))
            self.line2 = Halo(c, 14, 110, (ui_font, 9))

        for w in (root, c):
            w.bind("<Button-1>", self.on_press)
            w.bind("<B1-Motion>", self.on_drag)
            w.bind("<Button-3>", self.on_menu)
        root.bind("<Double-Button-1>", lambda e: self.toggle_top())
        root.bind("<Escape>", lambda e: root.destroy())

        self.follow = tk.StringVar(value=cfg.get("follow", "br"))
        self.theme_var = tk.StringVar(value=self.mode)
        self.topmost_var = tk.BooleanVar(value=self.topmost)
        m = tk.Menu(root, tearoff=0)
        m.add_radiobutton(label=tr("menu.follow_br"), variable=self.follow, value="br",
                          command=self.on_follow_change)
        m.add_radiobutton(label=tr("menu.follow_bl"), variable=self.follow, value="bl",
                          command=self.on_follow_change)
        m.add_radiobutton(label=tr("menu.follow_free"), variable=self.follow, value="free",
                          command=self.on_follow_change)
        m.add_separator()
        m.add_radiobutton(label=tr("menu.theme_auto"), variable=self.theme_var, value="auto",
                          command=self.on_theme_change)
        m.add_radiobutton(label=tr("menu.theme_light"), variable=self.theme_var, value="light",
                          command=self.on_theme_change)
        m.add_radiobutton(label=tr("menu.theme_dark"), variable=self.theme_var, value="dark",
                          command=self.on_theme_change)
        m.add_separator()
        m.add_checkbutton(label=tr("menu.topmost"), variable=self.topmost_var,
                          command=self.on_topmost_change)
        m.add_command(label=tr("menu.up"), command=lambda: self.nudge_bottom(-20))
        m.add_command(label=tr("menu.down"), command=lambda: self.nudge_bottom(20))
        m.add_command(label=tr("menu.alpha"), command=self.toggle_alpha)
        m.add_separator()
        m.add_command(label=tr("menu.quit"), command=root.destroy)
        self.menu = m

        self.root = root
        root.report_callback_exception = self.log_exception
        self.apply_palette()
        self.dock()
        self.follow_tick()
        self.refresh()

    # ---------- 日志 ----------

    def log_exception(self, exc, val, tb):
        logs.exception("error.log", val, tb)

    # ---------- 配色 ----------

    def pal(self):
        d = dict(PALETTE[self.theme])
        d["halo"] = getattr(self, "key", KEY_LIGHT)
        return d

    def sample_luma(self):
        if not self._pos:
            return None, None
        x, y = self._pos
        pts = [(x + 6, y + 6), (x + self.W - 6, y + 6),
               (x + 6, y + self.H - 6), (x + self.W - 6, y + self.H - 6)]
        gdi = ctypes.windll.gdi32
        gdi.GetPixel.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
        gdi.GetPixel.restype = wintypes.DWORD
        hdc = self.u.GetDC(0)
        lums, rgbs = [], []
        try:
            for px, py in pts:
                v = gdi.GetPixel(hdc, px, py)
                if v == 0xFFFFFFFF:
                    continue
                r, g, b = v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF
                lums.append(0.299 * r + 0.587 * g + 0.114 * b)
                rgbs.append((r, g, b))
        except Exception:
            return None, None
        finally:
            self.u.ReleaseDC(0, hdc)
        if not lums:
            return None, None
        n = len(rgbs)
        avg = tuple(sum(c[i] for c in rgbs) // n for i in range(3))
        return sum(lums) / n, avg

    def refresh_theme(self):
        if self.mode != "auto":
            want = self.mode
        else:
            luma, rgb = self.sample_luma()
            if luma is None:
                return
            if rgb:
                old = getattr(self, "chip_rgb", None)
                if old is None or max(abs(a - b) for a, b in zip(rgb, old)) > 10:
                    self.chip_rgb = rgb
                    self.chip_hex = "#%02X%02X%02X" % rgb
                    if self.layout == "bar":
                        self.c.itemconfigure(self.bar_bg, fill=self.chip_hex)
            if luma > 150:
                want = "light"
            elif luma < 105:
                want = "dark"
            else:
                want = self.theme
        if want != self.theme:
            self.theme = want
            self.apply_palette()

    def apply_palette(self):
        key = KEY_DARK if self.theme == "dark" else KEY_LIGHT
        self.key = key
        try:
            self.root.attributes("-transparentcolor", key)
        except Exception:
            pass
        self.c.configure(bg=key)
        self.root.configure(bg=key)
        p = self.pal()
        self.c.itemconfigure(self.dot, fill=p["mute"])
        if self.layout == "bar":
            self.bar.recolor(p["text"], p["halo"])
            self.c.itemconfigure(self.bar_bg,
                                 fill=getattr(self, "chip_hex", None) or CHIP[self.theme])
        else:
            for h, k in ((self.status, "dim"), (self.num, "text"),
                         (self.unit, "dim2"), (self.line1, "dim"), (self.line2, "dim2")):
                h.recolor(p[k], p["halo"])

    # ---------- 窗口行为 ----------

    def on_press(self, e):
        self._press = (e.x_root, e.y_root)
        self._moved = False
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def on_drag(self, e):
        if not self._drag:
            return
        if self._press and not self._moved:
            if abs(e.x_root - self._press[0]) < 4 and abs(e.y_root - self._press[1]) < 4:
                return
            self._moved = True
            if self.follow.get() != "free":
                self.follow.set("free")
                self.on_follow_change()
        self.root.geometry("+%d+%d" % (e.x_root - self._drag[0], e.y_root - self._drag[1]))
        self._pos = (self.root.winfo_x(), self.root.winfo_y())

    def on_menu(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def _persist(self, key, value):
        self.cfg[key] = value
        user = config.load_user()
        user[key] = value
        config.save(user)

    def on_follow_change(self):
        self._persist("follow", self.follow.get())
        self._pos = None
        if self.follow.get() != "free":
            if self.root.state() == "withdrawn":
                self.root.deiconify()
                self.root.attributes("-topmost", self.topmost)
            self.dock()

    def on_theme_change(self):
        self.mode = self.theme_var.get()
        self._persist("theme", self.mode)
        if self.mode != "auto":
            self.theme = self.mode
            self.apply_palette()

    def toggle_top(self):
        self.topmost_var.set(not self.topmost)
        self.on_topmost_change()

    def nudge_bottom(self, delta):
        """微调「距底边的抬升量」，避开输入框和按钮。"""
        self.bottom_offset = max(0, min(800, self.bottom_offset + delta))
        self.cfg.setdefault("window", {})["bottom_offset"] = self.bottom_offset
        user = config.load_user()
        user.setdefault("window", {})["bottom_offset"] = self.bottom_offset
        config.save(user)
        self._pos = None
        self.dock()

    def on_topmost_change(self):
        self.topmost = bool(self.topmost_var.get())
        self.root.attributes("-topmost", self.topmost)
        self._persist("topmost", self.topmost)
        if not self.topmost:
            self._owner = None
            self.attach_owner()

    def attach_owner(self):
        """把浮层登记为客户端窗口的附属窗口：压在客户端之上，但不盖住别的程序。"""
        try:
            h = self.u.FindWindowW(None, "oc-tps-hud")
            owner = self.client.find()
            if not h or not owner or self._owner == owner:
                return
            self.u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
            self.u.SetWindowLongPtrW.restype = ctypes.c_longlong
            self.u.SetWindowLongPtrW(h, GWL_HWNDPARENT, owner)
            self._owner = owner
        except Exception as e:
            logs.write("error.log", "attach_owner failed: %r" % (e,))

    def toggle_alpha(self):
        cur = self.root.attributes("-alpha")
        nxt = 1.0 if cur < 0.99 else 0.95
        self.root.attributes("-alpha", nxt)
        self._persist("alpha", nxt)

    def measure_scale(self):
        h = self.u.FindWindowW(None, "oc-tps-hud")
        if not h:
            return self.scale or 1.0
        r = wintypes.RECT()
        self.u.GetWindowRect(h, ctypes.byref(r))
        w = r.right - r.left
        if w > 0:
            v = self.W / float(w)
            if 0.5 <= v <= 3.0:
                self.scale = v
        return self.scale or 1.0

    def dock(self):
        st, rect = self.client.state()
        if st in ("none", "min"):
            if self.root.state() != "withdrawn":
                self.root.withdraw()
            return
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.attributes("-topmost", self.topmost)
            self._owner = None
        if not self.topmost:
            self.attach_owner()

        if self.follow.get() == "free":
            return

        s = self.scale or 1.0
        left, top, right, bottom = [int(v * s) for v in rect]
        m = int(self.margin * s)
        dy = int((self.margin + self.bottom_offset) * s)
        if self.layout == "bar":
            self.set_width((right - left) - 2 * m)
            x = left + ((right - left) - self.W) // 2
        elif self.follow.get() == "bl":
            x = left + m
        else:
            x = right - self.W - m
        y = bottom - self.H - dy
        vx, vy, vw, vh = self.client.virtual_screen()
        x = max(int(vx * s), min(x, int((vx + vw) * s) - self.W))
        y = max(int(vy * s), min(y, int((vy + vh) * s) - self.H))
        if self._pos == (x, y):
            return
        self._pos = (x, y)
        self.root.geometry("+%d+%d" % (x, y))
        self.root.update_idletasks()
        self.measure_scale()

    def follow_tick(self):
        try:
            self.dock()
            self.refresh_theme()
        except Exception as e:
            logs.exception("error.log", e)
        self.root.after(400, self.follow_tick)

    # ---------- 内容 ----------

    def render_bar(self, d):
        """一行式显示：状态 · 模型 · 速度 · 本步 · 中位，居中排布。"""
        p = self.pal()
        tr = self.tr
        st = d.get("state")
        model = d.get("model") or "—"
        tok = d.get("tokens") or 0
        elapsed = d.get("elapsed") or 0

        key = {"run": "state.run", "wait": "state.wait", "done": "state.done",
               "ttft": "state.ttft", "queue": "state.queue", "idle": "state.idle",
               "error": "state.error", "noschema": "state.noschema"}.get(st)
        head = tr(key) if key else tr("state.nodata")
        if st in ("run", "wait", "done", "ttft", "queue", "idle"):
            head = head + " · " + model

        dot = p["mute"]
        if st == "run":
            dot = p["ok"]
        elif st in ("wait", "ttft", "queue"):
            dot = p["warn"]
        elif st == "done":
            dot = p["ok"]
        elif st in ("error", "noschema", "nodata"):
            dot = p["bad"]

        if st in ("run", "wait", "done") and (d.get("rate") or 0) > 0.05:
            rate = "%s%.1f tok/s" % ("≈" if st in ("run", "wait") else "", d["rate"])
        else:
            rate = "— tok/s"

        # 放不下的顺序：先砍「本步」，再砍「中位」，保留状态与当前速度
        parts = [head, rate]
        recent = d.get("recent")
        if recent:
            parts.append(tr("bar.median", v="%.1f" % recent))
        if st in ("run", "wait", "done", "ttft"):
            parts.append("%s tok · %s" % (fmt_tok(tok), fmt_sec(elapsed)))

        sep = " · "
        maxw = self.W - 26
        text = sep.join(parts)
        while self.f_bar.measure(text) > maxw and len(parts) > 2:
            parts.pop()
            text = sep.join(parts)
        if self.f_bar.measure(text) > maxw:
            while text and self.f_bar.measure(text + "…") > maxw:
                text = text[:-1]
            text = text + "…"

        self.bar.set(text, p["text"] if st in ("run", "wait", "done") else p["dim"], p["halo"])
        w = self.f_bar.measure(text)
        cx = self.W // 2
        dx = cx - w / 2.0 - 10

        # 底板：把背后的正文挡住，避免两层文字糊在一起
        left = max(2, dx - 14)
        right = min(self.W - 2, cx + w / 2.0 + 12)
        self.c.coords(self.bar_bg, left, 3, right, self.H - 3)
        self.c.itemconfigure(self.bar_bg, state="normal",
                             fill=getattr(self, "chip_hex", None) or CHIP[self.theme])
        if dx > 6:
            r = 3
            cy = self.H // 2
            self.c.coords(self.dot, dx - r, cy - r, dx + r, cy + r)
            self.c.itemconfigure(self.dot, state="normal", fill=dot)
        else:
            self.c.itemconfigure(self.dot, state="hidden")

    def set_width(self, w):
        """客户端窗口比条窄时收窄，变宽时恢复；不会超过配置宽度。"""
        w = max(200, min(w, self.base_w))
        if w == self.W:
            return
        self.W = w
        self.root.geometry("%dx%d" % (w, self.H))
        self.c.configure(width=w)
        self.bar.move_to(w // 2, self.H // 2)
        self._pos = None

    def fit(self, text, maxw):
        """放不下时优先保模型名（状态还能靠圆点颜色分辨），再退化为左截断。"""
        f = self.f_status
        if f.measure(text) <= maxw:
            return text
        head, sep, tail = text.partition(" · ")
        if sep and f.measure(tail) <= maxw:
            return tail
        if not sep:
            while text and f.measure(text + "…") > maxw:
                text = text[:-1]
            return text + "…"
        avail = maxw - f.measure(head + sep)
        m = "…" + tail
        while len(m) > 1 and f.measure(m) > avail:
            m = "…" + m[2:]
        return head + sep + m

    def refresh(self):
        d = self.engine.tick()
        if self.layout == "bar":
            self.render_bar(d)
            self.root.after(int(self.cfg.get("poll_ms", 400)), self.refresh)
            return
        p = self.pal()
        tr = self.tr
        st = d.get("state")
        model = d.get("model") or "—"
        tok = d.get("tokens") or 0
        elapsed = d.get("elapsed") or 0
        big, color = "—", p["mute"]
        dot = p["mute"]
        label = ""

        if st in ("run", "wait", "done", "ttft", "queue"):
            key = {"run": "state.run", "wait": "state.wait", "done": "state.done",
                   "ttft": "state.ttft", "queue": "state.queue"}[st]
            dot = p["warn"] if st in ("ttft", "queue", "wait") else p["ok"]
            label = tr(key) + " · " + model

        if st == "run":
            big = ("≈%.1f" % d["rate"]) if (d.get("rate") or 0) > 0.05 else "—"
            self.line1.set(tr("line.step", tok=fmt_tok(tok), time=fmt_sec(elapsed)),
                           p["dim"], p["halo"])
        elif st == "ttft":
            self.line1.set(tr("line.elapsed", time=fmt_sec(elapsed)), p["dim"], p["halo"])
        elif st == "wait":
            big = ("%.1f" % d["rate"]) if (d.get("rate") or 0) > 0.05 else "—"
            self.line1.set(tr("line.step", tok=fmt_tok(tok), time=fmt_sec(elapsed)),
                           p["dim"], p["halo"])
        elif st == "done":
            big = ("%.1f" % d["rate"]) if (d.get("rate") or 0) > 0.05 else "—"
            self.line1.set(tr("line.step", tok=fmt_tok(tok), time=fmt_sec(elapsed)),
                           p["dim"], p["halo"])
        elif st == "queue":
            self.line1.set("", p["dim"], p["halo"])
        elif st == "idle":
            dot, label = p["mute"], tr("state.idle") + " · " + model
            self.line1.set(tr("line.idle"), p["dim"], p["halo"])
        elif st == "error":
            dot, label = p["bad"], tr("state.error")
            self.line1.set(tr("hint.retry"), p["dim"], p["halo"])
        elif st == "noschema":
            dot, label = p["bad"], tr("state.noschema")
            self.line1.set(tr("hint.version"), p["dim"], p["halo"])
        else:
            dot, label = p["bad"], tr("state.nodata")
            self.line1.set(tr("hint.start"), p["dim"], p["halo"])

        if big != "—" and st in ("run", "wait", "done"):
            color = p["text"]

        self.status.set(self.fit(label, self.status_w), p["dim"], p["halo"])
        self.num.set(big, color, p["halo"])
        if big == "—":
            self.unit.set("", p["dim2"], p["halo"])
        else:
            self.unit.set(tr("unit"), p["dim2"], p["halo"])
            self.unit.move_to(13 + self.f_num.measure(big) + 7, 61)

        recent = d.get("recent")
        if recent:
            self.line2.set(tr("line.recent", n=len(self.engine.recent), v="%.1f" % recent),
                           p["dim2"], p["halo"])
        elif d.get("last"):
            self.line2.set(tr("line.last", v="%.1f" % d["last"]), p["dim2"], p["halo"])
        else:
            self.line2.set(tr("line.none"), p["dim2"], p["halo"])

        self.c.itemconfigure(self.dot, fill=dot)
        self.root.after(int(self.cfg.get("poll_ms", 400)), self.refresh)

    def run(self):
        self.root.mainloop()
