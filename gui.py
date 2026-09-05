"""Interfata grafica (Tkinter) pentru Serato Migrator."""
from __future__ import annotations

import queue
import threading
import time
import tkinter.font as tkfont
from pathlib import Path
from tkinter import (
    Tk, Canvas, PhotoImage, Text, StringVar, BooleanVar, Toplevel, N, S, E, W, END, HORIZONTAL,
    filedialog,
)
from tkinter import ttk

import scanner
import copier

APP_TITLE = "Serato Migrator"
APP_VERSION = "0.4.0"

BASE_FONT_SIZE = 14
MONO_FONT_SIZE = 13

# glife checkbox pentru arborele de crate-uri din tab-ul Migrare
CHK_ON = "☑"    # casuta bifata
CHK_OFF = "☐"   # casuta goala
CHK_PART = "▣"  # patrat plin partial (unele copii selectate)

# paleta moderna - albastrul e ales din mijlocul degradeului violet->turcoaz al logo-ului
ACCENT = "#3B8FDA"
ACCENT_DARK = "#327AB9"
ACCENT_2 = "#00CEC9"
APP_BG = "#E7E7ED"
SURFACE = "#FFFFFF"
BORDER = "#E3E3EA"
TEXT_MAIN = "#1C1C1E"
TEXT_MUTED = "#6E6E76"
DISABLED_BG = "#D8D8DE"

SPLASH_BG = "#14161a"
SPLASH_ACCENT = "#ff5a1f"
SPLASH_DURATION_MS = 3200

# logo modern: patrat rotunjit cu degrade + bare de equalizer
LOGO_GRAD_START = "#6C5CE7"   # violet
LOGO_GRAD_END = "#00CEC9"    # turcoaz
LOGO_BAR_HEIGHTS = (0.42, 0.68, 1.0, 0.55)


def _hex_lerp(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = round(r1 + (r2 - r1) * t)
    g = round(g1 + (g2 - g1) * t)
    b = round(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _inside_rounded_square(x: float, y: float, size: int, r: float) -> bool:
    if x < r and y < r:
        return (x - r) ** 2 + (y - r) ** 2 <= r * r
    if x > size - r and y < r:
        return (x - (size - r)) ** 2 + (y - r) ** 2 <= r * r
    if x < r and y > size - r:
        return (x - r) ** 2 + (y - (size - r)) ** 2 <= r * r
    if x > size - r and y > size - r:
        return (x - (size - r)) ** 2 + (y - (size - r)) ** 2 <= r * r
    return 0 <= x <= size and 0 <= y <= size


def _draw_logo_bars_on_canvas(canvas: Canvas, cx: int, cy: int, box: int):
    """Deseneaza marca (barele de equalizer) pe un canvas, direct pe fundalul existent."""
    n = len(LOGO_BAR_HEIGHTS)
    bar_w = box * 0.16
    gap = box * 0.08
    total_w = n * bar_w + (n - 1) * gap
    start_x = cx - total_w / 2
    max_h = box
    base_y = cy + box / 2
    for i, frac in enumerate(LOGO_BAR_HEIGHTS):
        color = _hex_lerp(LOGO_GRAD_START, LOGO_GRAD_END, i / (n - 1))
        x0 = start_x + i * (bar_w + gap)
        x1 = x0 + bar_w
        h = max_h * frac
        y0 = base_y - h
        radius = bar_w / 2
        canvas.create_rectangle(x0, y0 + radius, x1, base_y, fill=color, outline="")
        canvas.create_oval(x0, y0, x1, y0 + 2 * radius, fill=color, outline="")


def _build_app_icon(size: int = 128) -> PhotoImage:
    """Deseneaza programatic o iconita moderna (patrat rotunjit, degrade + bare) - fara logo extern."""
    img = PhotoImage(width=size, height=size)
    radius = size * 0.22

    n = len(LOGO_BAR_HEIGHTS)
    bar_w = size * 0.11
    gap = size * 0.055
    total_w = n * bar_w + (n - 1) * gap
    start_x = (size - total_w) / 2
    max_bar_h = size * 0.46
    base_y = size * 0.72

    bars = []
    for i, frac in enumerate(LOGO_BAR_HEIGHTS):
        x0 = start_x + i * (bar_w + gap)
        x1 = x0 + bar_w
        h = max_bar_h * frac
        bars.append((x0, x1, base_y - h, base_y))

    rows = []
    transparent_px = []
    for y in range(size):
        colors = []
        for x in range(size):
            xf, yf = x + 0.5, y + 0.5
            if not _inside_rounded_square(xf, yf, size, radius):
                colors.append(SPLASH_BG)
                transparent_px.append((x, y))
                continue
            t = (x + y) / (2 * size)
            bg = _hex_lerp(LOGO_GRAD_START, LOGO_GRAD_END, t)
            in_bar = any(x0 <= x < x1 and y0 <= y <= y1 for x0, x1, y0, y1 in bars)
            colors.append("#ffffff" if in_bar else bg)
        rows.append("{" + " ".join(colors) + "}")
    img.put(" ".join(rows))
    for x, y in transparent_px:
        img.transparency_set(x, y, True)
    return img


def _inside_rounded_rect(x: float, y: float, w: int, h: int, r: float) -> bool:
    if x < r and y < r:
        return (x - r) ** 2 + (y - r) ** 2 <= r * r
    if x > w - r and y < r:
        return (x - (w - r)) ** 2 + (y - r) ** 2 <= r * r
    if x < r and y > h - r:
        return (x - r) ** 2 + (y - (h - r)) ** 2 <= r * r
    if x > w - r and y > h - r:
        return (x - (w - r)) ** 2 + (y - (h - r)) ** 2 <= r * r
    return 0 <= x <= w and 0 <= y <= h


def _build_pill_image(width: int, height: int, color: str, radius: float | None = None) -> PhotoImage:
    """Dreptunghi complet rotunjit (capsula), umplut cu `color`, restul transparent."""
    if radius is None:
        radius = height / 2
    img = PhotoImage(width=width, height=height)
    rows = []
    transparent_px = []
    for y in range(height):
        colors = []
        for x in range(width):
            if _inside_rounded_rect(x + 0.5, y + 0.5, width, height, radius):
                colors.append(color)
            else:
                colors.append("#000000")
                transparent_px.append((x, y))
        rows.append("{" + " ".join(colors) + "}")
    img.put(" ".join(rows))
    for x, y in transparent_px:
        img.transparency_set(x, y, True)
    return img


def _new_blank_image(size: int) -> tuple[PhotoImage, list]:
    """Creaza o imagine size x size, complet transparenta, gata de desenat pe ea."""
    img = PhotoImage(width=size, height=size)
    px = [["#000000"] * size for _ in range(size)]
    return img, px


def _flush_image(img: PhotoImage, px: list, transparent_default="#000000"):
    rows = ["{" + " ".join(row) + "}" for row in px]
    img.put(" ".join(rows))
    size = len(px)
    for y in range(size):
        for x in range(size):
            if px[y][x] == transparent_default:
                img.transparency_set(x, y, True)


def _dist_to_segment(px_, py_, x0, y0, x1, y1) -> float:
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return ((px_ - x0) ** 2 + (py_ - y0) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px_ - x0) * dx + (py_ - y0) * dy) / length_sq))
    projx, projy = x0 + t * dx, y0 + t * dy
    return ((px_ - projx) ** 2 + (py_ - projy) ** 2) ** 0.5


def _point_in_triangle(px_, py_, ax, ay, bx, by, cx_, cy_) -> bool:
    def sign(x1, y1, x2, y2, x3, y3):
        return (x1 - x3) * (y2 - y3) - (x2 - x3) * (y1 - y3)
    d1 = sign(px_, py_, ax, ay, bx, by)
    d2 = sign(px_, py_, bx, by, cx_, cy_)
    d3 = sign(px_, py_, cx_, cy_, ax, ay)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _build_refresh_icon(size: int = 28) -> PhotoImage:
    """Sageata circulara (rescanare) - degrade ca la logo."""
    import math
    img, px = _new_blank_image(size)
    cx = cy = size / 2
    r = size * 0.30
    thickness = max(2.0, size * 0.13)
    gap_deg = 60
    start_a = 90 + gap_deg / 2
    end_a = start_a + (360 - gap_deg)

    for y in range(size):
        for x in range(size):
            dx, dy = x - cx + 0.5, y - cy + 0.5
            d = (dx * dx + dy * dy) ** 0.5
            if abs(d - r) <= thickness / 2:
                ang = math.degrees(math.atan2(-dy, dx))
                if ang < start_a:
                    ang += 360
                if start_a <= ang <= end_a:
                    t = (ang - start_a) / (end_a - start_a)
                    px[y][x] = _hex_lerp(LOGO_GRAD_START, LOGO_GRAD_END, t)

    end_rad = math.radians(end_a % 360)
    tip = (cx + r * math.cos(end_rad), cy - r * math.sin(end_rad))
    tangent_rad = end_rad - math.pi / 2
    head_len = size * 0.24
    head_w = size * 0.16
    base_x = tip[0] - head_len * math.cos(tangent_rad)
    base_y = tip[1] + head_len * math.sin(tangent_rad)
    perp_rad = tangent_rad + math.pi / 2
    p1 = tip
    p2 = (base_x + head_w * math.cos(perp_rad), base_y - head_w * math.sin(perp_rad))
    p3 = (base_x - head_w * math.cos(perp_rad), base_y + head_w * math.sin(perp_rad))
    end_color = _hex_lerp(LOGO_GRAD_START, LOGO_GRAD_END, 1.0)
    for y in range(size):
        for x in range(size):
            if _point_in_triangle(x + 0.5, y + 0.5, *p1, *p2, *p3):
                px[y][x] = end_color

    _flush_image(img, px)
    return img


def _build_locate_icon(size: int = 28) -> PhotoImage:
    """Crosshair/radar (localizare track-uri mutate) - degrade ca la logo."""
    img, px = _new_blank_image(size)
    cx = cy = size / 2
    outer_r = size * 0.34
    inner_r = size * 0.09
    thickness = max(1.6, size * 0.09)
    tick_gap = size * 0.05
    tick_len = size * 0.13

    for y in range(size):
        for x in range(size):
            dx, dy = x - cx + 0.5, y - cy + 0.5
            d = (dx * dx + dy * dy) ** 0.5
            t = max(0.0, min(1.0, d / outer_r))
            if abs(d - outer_r) < thickness / 2:
                px[y][x] = _hex_lerp(LOGO_GRAD_START, LOGO_GRAD_END, t)
            elif d <= inner_r:
                px[y][x] = LOGO_GRAD_START

    for tdx, tdy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
        x0 = cx + tdx * (outer_r + tick_gap)
        y0 = cy + tdy * (outer_r + tick_gap)
        x1 = cx + tdx * (outer_r + tick_gap + tick_len)
        y1 = cy + tdy * (outer_r + tick_gap + tick_len)
        for y in range(size):
            for x in range(size):
                if _dist_to_segment(x, y, x0, y0, x1, y1) < thickness / 2:
                    px[y][x] = _hex_lerp(LOGO_GRAD_START, LOGO_GRAD_END, 0.5)

    _flush_image(img, px)
    return img


def _build_dot_icon(size: int = 13, filled: bool = False, color: str = TEXT_MUTED) -> PhotoImage:
    """Punct folosit ca indicator de expand/collapse in arbori, in loc de sageata clasica."""
    img, px = _new_blank_image(size)
    cx = cy = size / 2
    r = size * 0.30
    for y in range(size):
        for x in range(size):
            d = ((x - cx + 0.5) ** 2 + (y - cy + 0.5) ** 2) ** 0.5
            if filled and d <= r:
                px[y][x] = color
            elif not filled and abs(d - r) < 1.0:
                px[y][x] = color
    _flush_image(img, px)
    return img


def _show_dialog(parent, title: str, message: str, yesno: bool = False) -> bool:
    """Dialog modal centrat exact peste fereastra `parent` - inlocuieste
    tkinter.messagebox, care pe macOS ignora `parent` si centreaza pe ecran."""
    win = Toplevel(parent)
    win.title(title)
    win.transient(parent)
    win.resizable(False, False)
    win.configure(bg=SURFACE)

    frame = ttk.Frame(win, padding=20)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text=message, wraplength=380, justify="left",
              font=(None, BASE_FONT_SIZE)).pack(pady=(0, 18))

    result = {"value": False}

    def close(value):
        result["value"] = value
        win.destroy()

    btns = ttk.Frame(frame)
    btns.pack(anchor="e")
    if yesno:
        ttk.Button(btns, text="Nu", command=lambda: close(False)).pack(side="right", padx=(6, 0))
        ttk.Button(btns, text="Da", command=lambda: close(True)).pack(side="right")
    else:
        ttk.Button(btns, text="OK", command=lambda: close(True)).pack(side="right")

    win.update_idletasks()
    w, h = win.winfo_width(), win.winfo_height()
    parent.update_idletasks()
    px, py = parent.winfo_rootx(), parent.winfo_rooty()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    win.geometry(f"+{px + (pw - w) // 2}+{py + (ph - h) // 2}")

    win.grab_set()
    win.wait_window()
    return result["value"]


def show_info(parent, title: str, message: str):
    _show_dialog(parent, title, message, yesno=False)


def show_warning(parent, title: str, message: str):
    _show_dialog(parent, title, message, yesno=False)


def ask_yesno(parent, title: str, message: str) -> bool:
    return _show_dialog(parent, title, message, yesno=True)


class _Tooltip:
    """Tooltip simplu: apare la hover peste un widget, dupa o mica intarziere."""

    def __init__(self, widget, text: str, delay_ms: int = 400):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._hide)
        widget.bind("<ButtonPress>", self._hide)

    def _schedule(self, _event=None):
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _show(self):
        if self._tip is not None:
            return
        x = self.widget.winfo_rootx() + self.widget.winfo_width() // 2
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._tip = Toplevel(self.widget)
        self._tip.overrideredirect(True)
        self._tip.attributes("-topmost", True)
        label = ttk.Label(self._tip, text=self.text, background="#2b2d33", foreground="white",
                           padding=(8, 4), font=(None, BASE_FONT_SIZE - 2))
        label.pack()
        self._tip.update_idletasks()
        tip_w = self._tip.winfo_width()
        self._tip.geometry(f"+{x - tip_w // 2}+{y}")

    def _hide(self, _event=None):
        if self._after_id is not None:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None


def _show_splash(root: Tk, on_done):
    splash = Toplevel(root)
    splash.overrideredirect(True)
    splash.configure(bg=SPLASH_BG)
    w, h = 420, 420
    sw, sh = splash.winfo_screenwidth(), splash.winfo_screenheight()
    splash.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")
    splash.attributes("-topmost", True)

    canvas = Canvas(splash, width=w, height=h, bg=SPLASH_BG, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    _draw_logo_bars_on_canvas(canvas, w // 2, 150, 140)

    canvas.create_text(w // 2, 275, text="SERATO MIGRATOR", fill="white",
                        font=("Helvetica", 20, "bold"))
    canvas.create_text(w // 2, 305, text="Verifica, organizeaza si muta biblioteca ta Serato",
                        fill="#8a8f98", font=("Helvetica", 11))
    canvas.create_text(w // 2, 355, text="Se pregateste biblioteca...", fill="#c8ccd2",
                        font=("Helvetica", 12))

    splash.update_idletasks()
    splash.update()
    root.after(SPLASH_DURATION_MS, lambda: (splash.destroy(), on_done()))


class SeratoMigratorApp:
    def __init__(self, root: Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1300x800")
        self.root.minsize(1000, 650)

        self._setup_fonts()

        # cate operatiuni lungi ruleaza acum (migrare, scanari, metadata) - cat
        # timp e > 0 fereastra nu se poate inchide
        self._busy_count = 0
        self._busy_labels: list[str] = []
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.libraries: list[scanner.SeratoLibrary] = []
        self.lib_vars: dict[str, BooleanVar] = {}   # nume biblioteca -> checkbox inclus in migrare

        self._build_ui()
        self.refresh_libraries()

    def _setup_fonts(self):
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            f = tkfont.nametofont(name)
            f.configure(size=BASE_FONT_SIZE)
        self.mono_font = tkfont.Font(family="Menlo", size=MONO_FONT_SIZE)

        self.root.configure(bg=APP_BG)
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=APP_BG, foreground=TEXT_MAIN, font=(None, BASE_FONT_SIZE))
        style.configure("TFrame", background=APP_BG)
        style.configure("TLabel", background=APP_BG, foreground=TEXT_MAIN, font=(None, BASE_FONT_SIZE))
        style.configure("TCheckbutton", background=APP_BG, font=(None, BASE_FONT_SIZE))

        style.configure("TButton", font=(None, BASE_FONT_SIZE), padding=8,
                         background=ACCENT, foreground="white", borderwidth=0, focusthickness=0)
        style.map("TButton",
                  background=[("active", ACCENT_DARK), ("disabled", DISABLED_BG)],
                  foreground=[("disabled", TEXT_MUTED)])

        style.configure("Icon.TButton", padding=6, background=APP_BG, borderwidth=0, relief="flat")
        style.map("Icon.TButton", background=[("active", BORDER)])

        style.configure("TNotebook", background=APP_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=APP_BG, foreground=TEXT_MUTED,
                         padding=(16, 10), font=(None, BASE_FONT_SIZE))
        style.map("TNotebook.Tab",
                  background=[("selected", SURFACE)],
                  foreground=[("selected", ACCENT)])

        style.configure("Treeview", rowheight=32, font=(None, BASE_FONT_SIZE),
                         background=SURFACE, fieldbackground=SURFACE, foreground=TEXT_MAIN,
                         borderwidth=0)
        style.configure("Treeview.Heading", font=(None, BASE_FONT_SIZE, "bold"),
                         background=APP_BG, foreground=TEXT_MUTED, relief="flat")
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])

        style.configure("TLabelframe", background=APP_BG, bordercolor=BORDER)
        style.configure("TLabelframe.Label", font=(None, BASE_FONT_SIZE, "bold"),
                         background=APP_BG, foreground=TEXT_MUTED)
        style.configure("Status.TLabel", font=(None, BASE_FONT_SIZE), padding=6,
                         background=SURFACE, foreground=TEXT_MUTED)
        style.configure("Warn.TLabel", font=(None, BASE_FONT_SIZE, "bold"),
                         background=APP_BG, foreground="#B00020")
        style.configure("Ok.TLabel", font=(None, BASE_FONT_SIZE),
                         background=APP_BG, foreground="#1B7A3D")

        style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE)
        style.configure("TEntry", fieldbackground=SURFACE)

        self._setup_dot_indicator(style)

    def _setup_dot_indicator(self, style: ttk.Style):
        """Inlocuieste sageata clasica de expand/collapse din Treeview cu un punct."""
        self._dot_closed_img = _build_dot_icon(filled=False)
        self._dot_open_img = _build_dot_icon(filled=True, color=ACCENT)
        self._dot_empty_img, _ = _new_blank_image(13)
        _flush_image(self._dot_empty_img, [["#000000"] * 13 for _ in range(13)])

        style.element_create(
            "Dot.Treeitem.indicator", "image", self._dot_closed_img,
            ("user1", "!user2", self._dot_open_img),
            ("user2", self._dot_empty_img),
            sticky="w", width=20,
        )
        style.layout("Treeview.Item", [
            ("Treeitem.padding", {"sticky": "nswe", "children": [
                ("Dot.Treeitem.indicator", {"side": "left", "sticky": ""}),
                ("Treeitem.image", {"side": "left", "sticky": ""}),
                ("Treeitem.text", {"side": "left", "sticky": ""}),
            ]}),
        ])

    # ---------------------------------------------------------- UI generala
    def _build_ui(self):
        style = ttk.Style()
        style.configure("TabItem.TLabel", background=APP_BG, foreground=TEXT_MUTED,
                         font=(None, BASE_FONT_SIZE), padding=(14, 8))

        bar_inner = ttk.Frame(self.root)
        bar_inner.pack(anchor="w", padx=16, pady=(14, 10))

        divider = ttk.Frame(self.root, height=1, style="Divider.TFrame")
        style.configure("Divider.TFrame", background=BORDER)
        divider.pack(fill="x", padx=16)

        content = ttk.Frame(self.root)
        content.pack(fill="both", expand=True, padx=16, pady=14)
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)

        self.tab_libs = ttk.Frame(content)
        self.tab_crates = ttk.Frame(content)
        self.tab_orphans = ttk.Frame(content)
        self.tab_migrate = ttk.Frame(content)
        self.tab_metadata = ttk.Frame(content)
        self.tab_log = ttk.Frame(content)
        self.tab_about = ttk.Frame(content)

        tabs = [
            ("libs", "Biblioteci", self.tab_libs),
            ("crates", "Crate-uri", self.tab_crates),
            ("orphans", "Fisiere orfane", self.tab_orphans),
            ("migrate", "Migrare / Reorganizare", self.tab_migrate),
            ("metadata", "Metadata", self.tab_metadata),
            ("log", "Jurnal", self.tab_log),
            ("about", "Despre", self.tab_about),
        ]
        self._tab_frames: dict[str, ttk.Frame] = {}
        self._tab_labels: dict[str, ttk.Label] = {}
        self._tab_pill_cache: dict[str, PhotoImage] = {}
        self._active_tab = None

        for key, title, frame in tabs:
            self._tab_frames[key] = frame
            frame.grid(row=0, column=0, sticky="nsew")

            lbl = ttk.Label(bar_inner, text=title, style="TabItem.TLabel", cursor="pointinghand")
            lbl.pack(side="left", padx=2)
            lbl.bind("<Button-1>", lambda _e, k=key: self._select_tab(k))
            self._tab_labels[key] = lbl

        self._build_tab_log()   # inainte de celelalte, ca self.log() sa fie disponibil de la inceput
        self._build_tab_libraries()
        self._build_tab_crates()
        self._build_tab_orphans()
        self._build_tab_migrate()
        self._build_tab_metadata()
        self._build_tab_about()

        self._select_tab("libs")

        self.status_var = StringVar(value="Gata.")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, anchor="w",
                                style="Status.TLabel")
        status_bar.pack(fill="x", side="bottom")

    def _select_tab(self, key: str):
        if self._active_tab == key:
            return
        self._active_tab = key
        for k, lbl in self._tab_labels.items():
            if k == key:
                if k not in self._tab_pill_cache:
                    fnt = tkfont.Font(font=lbl.cget("font"))
                    text_w = fnt.measure(lbl.cget("text"))
                    pill_w = text_w + 36
                    pill_h = 32
                    self._tab_pill_cache[k] = _build_pill_image(pill_w, pill_h, SURFACE)
                lbl.configure(image=self._tab_pill_cache[k], compound="center",
                               foreground=ACCENT, font=(None, BASE_FONT_SIZE, "bold"))
            else:
                lbl.configure(image="", compound="none",
                               foreground=TEXT_MUTED, font=(None, BASE_FONT_SIZE))
        self._tab_frames[key].tkraise()

    def set_status(self, text: str):
        self.status_var.set(text)

    # ------------------------------------------------ operatiuni in curs / close
    def _begin_busy(self, label: str):
        """Marcheaza inceputul unei operatiuni lungi. Cat timp exista una,
        fereastra nu se poate inchide."""
        self._busy_count += 1
        self._busy_labels.append(label)

    def _end_busy(self, label: str):
        self._busy_count = max(0, self._busy_count - 1)
        try:
            self._busy_labels.remove(label)
        except ValueError:
            pass

    def _on_close(self):
        if self._busy_count > 0:
            what = ", ".join(dict.fromkeys(self._busy_labels)) or "o operatiune"
            show_warning(
                self.root, APP_TITLE,
                f"O operatiune e in curs ({what}).\n\n"
                f"Asteapta sa se termine inainte sa inchizi aplicatia - altfel poti "
                f"ramane cu o copiere pe jumatate si o baza Serato incompleta.")
            return
        if ask_yesno(self.root, APP_TITLE, "Esti sigur ca vrei sa inchizi Serato Migrator?"):
            self.root.destroy()

    def _guard_serato_not_running(self) -> bool:
        """True = sigur sa continuam. Daca Serato DJ Pro ruleaza, arata un
        avertisment si intoarce False - scrierea directa in _Serato_ cat timp
        Serato ruleaza risca sa fie anulata cand Serato isi salveaza propria
        stare (veche) din memorie peste fisier."""
        if not scanner.is_serato_running():
            return True
        show_warning(
            self.root, APP_TITLE,
            "Serato DJ Pro ruleaza acum. Inchide-l complet (Cmd+Q) inainte de a continua -"
            " altfel Serato poate sa isi salveze propria versiune (veche) peste schimbarea"
            " facuta aici, anuland-o.")
        self.log("Operatie blocata: Serato DJ Pro ruleaza. Inchide-l si incearca din nou.")
        return False

    # ---------------------------------------------------------- Tab Jurnal
    def _build_tab_log(self):
        top = ttk.Frame(self.tab_log)
        top.pack(fill="x", pady=6)
        ttk.Label(top, text="Jurnal de activitate - tot ce face aplicatia apare aici, in timp real.").pack(
            side="left")
        ttk.Button(top, text="Curata jurnalul", command=self._clear_log).pack(side="right", padx=4)

        self.log_text = Text(self.tab_log, font=self.mono_font, wrap="word", state="disabled")
        scroll = ttk.Scrollbar(self.tab_log, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=4)
        scroll.pack(side="right", fill="y", pady=4)

    def log(self, message: str):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(END, f"[{timestamp}] {message}\n")
        self.log_text.see(END)
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", END)
        self.log_text.configure(state="disabled")

    # ---------------------------------------------------------- Tab Despre
    # ---------------------------------------------------------- Tab Metadata
    def _build_tab_metadata(self):
        import metadata_editor
        self._metadata_editor = metadata_editor

        top = ttk.Frame(self.tab_metadata)
        top.pack(fill="x", pady=(0, 6))
        ttk.Label(top, text="Biblioteca:").pack(side="left")
        self.metadata_lib_var = StringVar()
        self.metadata_lib_combo = ttk.Combobox(top, textvariable=self.metadata_lib_var, width=30, state="readonly")
        self.metadata_lib_combo.pack(side="left", padx=4)
        self.metadata_lib_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_metadata_lib_selected())
        ttk.Button(top, text="Deschide folder...", command=self._open_metadata_folder).pack(side="left", padx=4)

        ttk.Label(top, text="Cauta:").pack(side="left", padx=(16, 4))
        self.metadata_search_var = StringVar()
        search_entry = ttk.Entry(top, textvariable=self.metadata_search_var, width=30)
        search_entry.pack(side="left")
        search_entry.bind("<Return>", lambda _e: self._search_metadata_tracks())
        ttk.Button(top, text="Cauta", command=self._search_metadata_tracks).pack(side="left", padx=4)
        ttk.Button(top, text="Analizeaza Artist/Titlu lipsa",
                   command=self._analyze_artist_title).pack(side="left", padx=(16, 0))

        self.metadata_info_var = StringVar(value="Alege o biblioteca si cauta track-uri.")
        ttk.Label(self.tab_metadata, textvariable=self.metadata_info_var).pack(fill="x")

        paned = ttk.Panedwindow(self.tab_metadata, orient="horizontal")
        paned.pack(fill="both", expand=True, pady=(6, 0))
        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=3)
        paned.add(right, weight=1)

        cols = ("artist", "titlu", "album", "gen", "fisier")
        self.metadata_tree = ttk.Treeview(left, columns=cols, show="headings")
        for c, w in zip(cols, (180, 220, 160, 100, 260)):
            self.metadata_tree.heading(c, text=c.capitalize())
            self.metadata_tree.column(c, width=w, anchor="w")
        self.metadata_tree.pack(fill="both", expand=True)
        self.metadata_tree.bind("<<TreeviewSelect>>", lambda _e: self._on_metadata_selection_changed())

        edit_frame = ttk.LabelFrame(right, text="Editare")
        edit_frame.pack(fill="x", padx=(10, 0), pady=4)
        self.metadata_edit_title_var = StringVar(value="Selecteaza track-uri in stanga")
        ttk.Label(edit_frame, textvariable=self.metadata_edit_title_var,
                  font=(None, BASE_FONT_SIZE - 1)).grid(row=0, column=0, columnspan=2, sticky=W, padx=6, pady=(6, 10))

        self.metadata_field_vars: dict[str, StringVar] = {}
        field_labels = {"artist": "Artist", "title": "Titlu", "album": "Album", "genre": "Gen"}
        for i, (field, label) in enumerate(field_labels.items(), start=1):
            var = StringVar()
            self.metadata_field_vars[field] = var
            ttk.Label(edit_frame, text=f"{label}:").grid(row=i, column=0, sticky=W, padx=6, pady=3)
            ttk.Entry(edit_frame, textvariable=var, width=24).grid(row=i, column=1, sticky=(E, W), padx=6, pady=3)
        edit_frame.grid_columnconfigure(1, weight=1)

        self.metadata_write_id3_var = BooleanVar(value=True)
        ttk.Checkbutton(edit_frame, text="Scrie si in tag-urile ID3 ale fisierelor",
                         variable=self.metadata_write_id3_var).grid(
            row=len(field_labels) + 1, column=0, columnspan=2, sticky=W, padx=6, pady=(6, 4))

        self.metadata_save_btn = ttk.Button(edit_frame, text="Salveaza", command=self._save_metadata_edit,
                                             state="disabled")
        self.metadata_save_btn.grid(row=len(field_labels) + 2, column=0, columnspan=2, pady=(4, 8))

        self._metadata_lib: scanner.SeratoLibrary | None = None
        self._metadata_track_ids: list[str] = []

    def _refresh_metadata_lib_choices(self):
        names = [lib.name for lib in self.libraries]
        self.metadata_lib_combo["values"] = names
        if names and not self.metadata_lib_var.get():
            self.metadata_lib_var.set(names[0])
            self._on_metadata_lib_selected()

    def _on_metadata_lib_selected(self):
        name = self.metadata_lib_var.get()
        self._metadata_lib = next((l for l in self.libraries if l.name == name), None)
        self.metadata_tree.delete(*self.metadata_tree.get_children())
        self.metadata_info_var.set(f"'{name}' selectata - {len(self._metadata_lib.tracks) if self._metadata_lib else 0} track-uri. Cauta ceva pentru a le afisa.")

    def _open_metadata_folder(self):
        folder = filedialog.askdirectory(title="Alege folderul radacina al bibliotecii (contine _Serato_)")
        if not folder:
            return
        lib = scanner.load_library_at(folder)
        if not lib:
            show_warning(self.root, APP_TITLE, f"Nu am gasit un folder _Serato_ valid in:\n{folder}")
            return
        self.libraries.append(lib)
        self._refresh_metadata_lib_choices()
        self.metadata_lib_var.set(lib.name)
        self._on_metadata_lib_selected()
        self.log(f"Biblioteca '{lib.name}' incarcata manual din {folder} ({len(lib.tracks)} track-uri).")

    def _search_metadata_tracks(self):
        if not self._metadata_lib:
            show_warning(self.root, APP_TITLE, "Alege mai intai o biblioteca.")
            return
        query = self.metadata_search_var.get().strip().lower()
        self.metadata_tree.delete(*self.metadata_tree.get_children())
        self._metadata_track_ids = []

        count = 0
        LIMIT = 500
        for raw_path, track in self._metadata_lib.tracks.items():
            filename = Path(track.abs_path).name
            haystack = f"{track.artist or ''} {track.title or ''} {filename}".lower()
            if query and query not in haystack:
                continue
            self.metadata_tree.insert("", END, iid=raw_path, values=(
                track.artist or "", track.title or "", track.album or "", track.genre or "", filename,
            ))
            self._metadata_track_ids.append(raw_path)
            count += 1
            if count >= LIMIT:
                break

        total_matching = count if count < LIMIT else "500+"
        self.metadata_info_var.set(f"Afisate {total_matching} track-uri" +
                                    (f" (limitat la {LIMIT})" if count >= LIMIT else "") + ".")

    def _on_metadata_selection_changed(self):
        sel = self.metadata_tree.selection()
        if not sel:
            self.metadata_edit_title_var.set("Selecteaza track-uri in stanga")
            self.metadata_save_btn["state"] = "disabled"
            for var in self.metadata_field_vars.values():
                var.set("")
            return

        self.metadata_save_btn["state"] = "normal"
        if len(sel) == 1:
            track = self._metadata_lib.tracks.get(sel[0])
            self.metadata_edit_title_var.set(f"Track: {Path(track.abs_path).name}")
            self.metadata_field_vars["artist"].set(track.artist or "")
            self.metadata_field_vars["title"].set(track.title or "")
            self.metadata_field_vars["album"].set(track.album or "")
            self.metadata_field_vars["genre"].set(track.genre or "")
        else:
            self.metadata_edit_title_var.set(
                f"Editare de grup - {len(sel)} track-uri (campurile goale nu se modifica)")
            for var in self.metadata_field_vars.values():
                var.set("")

    def _save_metadata_edit(self):
        sel = self.metadata_tree.selection()
        if not sel or not self._metadata_lib:
            return
        if not self._guard_serato_not_running():
            return
        me = self._metadata_editor
        field_tags = {"artist": "tart", "title": "tsng", "album": "talb", "genre": "tgen"}

        is_single = len(sel) == 1
        if is_single:
            # editare individuala: aplicam toate cele 4 campuri asa cum sunt in formular
            # (inclusiv daca sunt golite intentionat)
            fields = {field_tags[f]: v.get().strip() for f, v in self.metadata_field_vars.items()}
        else:
            # editare de grup: doar campurile completate se aplica, restul raman neatinse
            fields = {field_tags[f]: v.get().strip() for f, v in self.metadata_field_vars.items()
                      if v.get().strip()}
        edits: dict[str, dict[str, str]] = {raw_path: fields for raw_path in sel} if fields else {}

        if not edits:
            show_info(self.root, APP_TITLE, "Nimic de salvat - completeaza cel putin un camp.")
            return

        write_id3 = self.metadata_write_id3_var.get()
        self.log(f"Salvez metadata pentru {len(edits)} track-uri (ID3: {'da' if write_id3 else 'nu'})...")
        me.apply_edits(self._metadata_lib, edits, write_id3=write_id3)
        self.log("Metadata salvata.")

        # reincarcam din disc valorile actualizate pentru track-urile afectate
        fresh = scanner.load_library_at(self._metadata_lib.volume_root, self._metadata_lib.name)
        if fresh:
            self._metadata_lib.tracks = fresh.tracks
        for raw_path in sel:
            track = self._metadata_lib.tracks.get(raw_path)
            if track:
                filename = Path(track.abs_path).name
                self.metadata_tree.item(raw_path, values=(
                    track.artist or "", track.title or "", track.album or "", track.genre or "", filename,
                ))
        show_info(self.root, APP_TITLE, f"Metadata salvata pentru {len(edits)} track-uri.")

    def _analyze_artist_title(self):
        if not self._metadata_lib:
            show_warning(self.root, APP_TITLE, "Alege mai intai o biblioteca.")
            return
        me = self._metadata_editor
        self.log(f"Analizez '{self._metadata_lib.name}' pentru Artist/Titlu lipsa...")
        suggestions = me.suggest_artist_title_fixes(self._metadata_lib)
        self.log(f"Gasite {len(suggestions)} track-uri cu sugestii de corectie.")
        if not suggestions:
            show_info(self.root, APP_TITLE, "Niciun track nu are nevoie de corectie Artist/Titlu.")
            return
        self._show_artist_title_review(suggestions)

    def _show_artist_title_review(self, suggestions):
        win = Toplevel(self.root)
        win.title("Corectie Artist / Titlu")
        win.geometry("1000x600")

        ttk.Label(win, text=f"{len(suggestions)} sugestii - deselecteaza ce nu vrei sa aplici, apoi 'Aplica'.",
                  style="Status.TLabel").pack(fill="x")

        tree = ttk.Treeview(win, columns=("fisier", "artist_vechi", "titlu_vechi", "artist_nou", "titlu_nou"),
                             show="headings", selectmode="extended")
        headings = {"fisier": "Fisier", "artist_vechi": "Artist (vechi)", "titlu_vechi": "Titlu (vechi)",
                    "artist_nou": "Artist (nou)", "titlu_nou": "Titlu (nou)"}
        for c, w in zip(tree["columns"], (260, 160, 220, 160, 220)):
            tree.heading(c, text=headings[c])
            tree.column(c, width=w, anchor="w")
        tree.pack(fill="both", expand=True, padx=6, pady=6)

        by_iid = {}
        for i, s in enumerate(suggestions):
            iid = str(i)
            tree.insert("", END, iid=iid, values=(s.filename, s.old_artist, s.old_title, s.new_artist, s.new_title))
            by_iid[iid] = s
        tree.selection_set(list(by_iid.keys()))   # implicit toate bifate/selectate

        write_id3_var = BooleanVar(value=True)
        ttk.Checkbutton(win, text="Scrie si in tag-urile ID3 ale fisierelor",
                         variable=write_id3_var).pack(anchor=W, padx=6)

        def apply_selected():
            selected = tree.selection()
            if not selected:
                show_info(self.root, APP_TITLE, "Nu ai selectat nimic.")
                return
            if not self._guard_serato_not_running():
                return
            edits = {}
            for iid in selected:
                s = by_iid[iid]
                edits[s.raw_path] = {"tart": s.new_artist, "tsng": s.new_title}
            self.log(f"Aplic corectia Artist/Titlu pentru {len(edits)} track-uri...")
            self._metadata_editor.apply_edits(self._metadata_lib, edits, write_id3=write_id3_var.get())
            self.log("Corectie aplicata.")
            fresh = scanner.load_library_at(self._metadata_lib.volume_root, self._metadata_lib.name)
            if fresh:
                self._metadata_lib.tracks = fresh.tracks
            show_info(self.root, APP_TITLE, f"Corectie aplicata pentru {len(edits)} track-uri.")
            win.destroy()

        ttk.Button(win, text="Aplica pe cele selectate", command=apply_selected).pack(pady=8)

    def _build_tab_about(self):
        outer = ttk.Frame(self.tab_about)
        outer.pack(fill="both", expand=True)
        frame = ttk.Frame(outer, padding=30)
        frame.place(relx=0.5, rely=0.5, anchor="center")

        self._about_logo_img = _build_app_icon(96)
        ttk.Label(frame, image=self._about_logo_img).pack(pady=(0, 10))

        ttk.Label(frame, text="Serato Migrator", font=(None, 22, "bold"),
                  justify="center", anchor="center").pack(pady=(0, 2))
        ttk.Label(frame, text=f"Versiune {APP_VERSION}", font=(None, BASE_FONT_SIZE - 1),
                  foreground=TEXT_MUTED, justify="center", anchor="center").pack(pady=(0, 12))
        ttk.Label(frame, text="Unealta personala pentru administrarea bibliotecii Serato DJ Pro.",
                  font=(None, BASE_FONT_SIZE), justify="center", anchor="center").pack(pady=(0, 16))

        info_lines = [
            "Dezvoltata de Gabriel Colceriu, cu asistenta Claude Code (Anthropic).",
            "",
            "Ce face aplicatia:",
            "Biblioteci: detecteaza automat bibliotecile Serato (locala + volume externe)",
            "Crate-uri: navigheaza arborele de crate-uri si vezi ce track-uri lipsesc de pe disk",
            "Fisiere orfane: gaseste fisiere audio de pe disk necunoscute de Serato",
            "Migrare / Reorganizare: copiaza track-urile in foldere numite dupa crate-uri,"
            " pe o destinatie noua, fara sa stearga originalele",
            "Metadata: gaseste track-uri cu artistul lipsa/ingropat in titlu si"
            " permite editare individuala sau de grup a Artist/Titlu/Album/Gen,"
            " atat in baza de date Serato cat si in tag-urile ID3 ale fisierelor",
            "Jurnal: istoricul tuturor operatiilor facute de aplicatie",
        ]
        for line in info_lines:
            ttk.Label(frame, text=line, font=(None, BASE_FONT_SIZE - 1),
                      justify="center", anchor="center").pack(fill="x")

    # ---------------------------------------------------------- Tab Biblioteci
    def _build_tab_libraries(self):
        top = ttk.Frame(self.tab_libs)
        top.pack(fill="x", pady=6)

        self._icon_refresh = _build_refresh_icon()
        self._icon_check = _build_locate_icon()

        refresh_btn = ttk.Button(top, image=self._icon_refresh, style="Icon.TButton",
                                  command=self.refresh_libraries)
        refresh_btn.pack(side="left", padx=(4, 2))
        _Tooltip(refresh_btn, "Rescaneaza bibliotecile Serato")

        self.check_missing_btn = ttk.Button(top, image=self._icon_check, style="Icon.TButton",
                                             command=self._check_missing_elsewhere)
        self.check_missing_btn.pack(side="left", padx=2)
        _Tooltip(self.check_missing_btn, "Verifica track-uri lipsa (cauta pe disk daca au fost mutate)")

        cols = ("nume", "radacina", "tracks", "prezente", "lipsa", "crate_uri")
        self.libs_tree = ttk.Treeview(self.tab_libs, columns=cols, show="headings", height=10)
        headings = {
            "nume": "Biblioteca", "radacina": "Radacina volum", "tracks": "Track-uri",
            "prezente": "Prezente", "lipsa": "Lipsa", "crate_uri": "Crate-uri",
        }
        for c in cols:
            self.libs_tree.heading(c, text=headings[c])
            self.libs_tree.column(c, width=140, anchor="center")
        self.libs_tree.column("radacina", width=220, anchor="w")
        self.libs_tree.pack(fill="both", expand=True, padx=4, pady=4)

    def refresh_libraries(self):
        self.set_status("Scanez bibliotecile Serato...")
        self.log("Scanez bibliotecile Serato (locala + volume externe montate)...")
        t0 = time.time()
        self._begin_busy("scanare biblioteci")

        def work():
            libs = scanner.find_serato_libraries()
            elapsed = time.time() - t0
            self.root.after(0, lambda: self._on_libraries_scanned(libs, elapsed))

        threading.Thread(target=work, daemon=True).start()

    def _on_libraries_scanned(self, libs: list[scanner.SeratoLibrary], elapsed: float):
        self._end_busy("scanare biblioteci")
        self.libraries = libs
        for row in self.libs_tree.get_children():
            self.libs_tree.delete(row)
        for lib in libs:
            self.libs_tree.insert("", END, iid=lib.name, values=(
                lib.name, lib.volume_root, len(lib.tracks),
                len(lib.present_tracks), len(lib.missing_tracks), len(lib.crates),
            ))
        result_text = _ro_count(len(libs), "biblioteca gasita", "biblioteci gasite")
        self.set_status(result_text + ".")
        self.log(f"{result_text} in {elapsed:.1f}s: " +
                 ", ".join(f"{lib.name} ({len(lib.tracks)} track-uri, {len(lib.missing_tracks)} lipsa)"
                           for lib in libs))
        self._refresh_crates_tree()
        self._refresh_migrate_checkboxes()
        self._refresh_orphan_lib_choices()
        self._refresh_metadata_lib_choices()

    def _check_missing_elsewhere(self):
        sel = self.libs_tree.selection()
        if not sel:
            show_warning(self.root, APP_TITLE, "Selecteaza mai intai o biblioteca din lista de mai sus.")
            return
        lib = next((l for l in self.libraries if l.name == sel[0]), None)
        if not lib:
            return
        if not lib.missing_tracks:
            show_info(self.root, APP_TITLE, f"'{lib.name}' nu are track-uri lipsa.")
            return

        self.log(f"Caut pe tot volumul {lib.volume_root} cele "
                 f"{_ro_count(len(lib.missing_tracks), 'track lipsa', 'track-uri lipsa')} din '{lib.name}'"
                 f" (indexez toate fisierele audio de pe disk, poate dura cateva zeci de secunde)...")
        self.check_missing_btn["state"] = "disabled"
        t0 = time.time()
        progress_q: queue.Queue = queue.Queue()
        self._begin_busy("cautare track-uri lipsa")

        def progress_cb(count):
            progress_q.put(count)

        def work():
            found, still_missing = scanner.find_missing_elsewhere(lib, progress_cb=progress_cb)
            elapsed = time.time() - t0
            progress_q.put(None)
            self.root.after(0, lambda: self._show_missing_results(lib, found, still_missing, elapsed))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(200, lambda: self._poll_missing_progress(progress_q, t0))

    def _poll_missing_progress(self, progress_q: queue.Queue, t0: float):
        last = None
        try:
            while True:
                item = progress_q.get_nowait()
                if item is None:
                    return  # rezultatul final vine separat prin _show_missing_results
                last = item
        except queue.Empty:
            pass
        if last is not None:
            elapsed = time.time() - t0
            self.set_status(f"Indexez fisierele de pe disk... {last} fisiere scanate ({elapsed:.0f}s)")
        self.root.after(400, lambda: self._poll_missing_progress(progress_q, t0))

    def _show_missing_results(self, lib: scanner.SeratoLibrary, found, still_missing, elapsed: float):
        self._end_busy("cautare track-uri lipsa")
        self.check_missing_btn["state"] = "normal"
        self.set_status("Verificare terminata.")
        self.log(f"Verificare terminata in {elapsed:.1f}s pentru '{lib.name}': "
                 f"{_ro_count(len(found), 'gasit in alta parte', 'gasite in alta parte')}, "
                 f"{_ro_count(len(still_missing), 'chiar lipsa', 'chiar lipsa')}.")

        win = Toplevel(self.root)
        win.title(f"Track-uri lipsa - {lib.name}")
        win.geometry("1000x600")

        summary = (
            f"{_ro_count(len(found), 'track gasit in alta parte', 'track-uri gasite in alta parte')}   |   "
            f"{_ro_count(len(still_missing), 'track chiar lipsa', 'track-uri chiar lipsa')}"
        )
        ttk.Label(win, text=summary, style="Status.TLabel").pack(fill="x")

        notebook = ttk.Notebook(win)
        notebook.pack(fill="both", expand=True, padx=6, pady=6)

        found_tab = ttk.Frame(notebook)
        missing_tab = ttk.Frame(notebook)
        notebook.add(found_tab, text=f"Gasite in alta parte ({len(found)})")
        notebook.add(missing_tab, text=f"Chiar lipsa ({len(still_missing)})")

        found_tree = ttk.Treeview(found_tab, columns=("veche", "noua"), show="headings")
        found_tree.heading("veche", text="Cale veche (in Serato)")
        found_tree.heading("noua", text="Gasit acum la")
        found_tree.column("veche", width=460, anchor="w")
        found_tree.column("noua", width=460, anchor="w")
        found_tree.pack(fill="both", expand=True)
        for track, candidates in found:
            for candidate in candidates:
                found_tree.insert("", END, values=(track.abs_path, str(candidate)))

        missing_list = ttk.Treeview(missing_tab, columns=("cale",), show="headings")
        missing_list.heading("cale", text="Cale (negasita nicaieri pe disk)")
        missing_list.column("cale", width=940, anchor="w")
        missing_list.pack(fill="both", expand=True)
        for track in still_missing:
            missing_list.insert("", END, values=(track.abs_path,))

    # ---------------------------------------------------------- Tab Crate-uri
    def _build_tab_crates(self):
        paned = ttk.Panedwindow(self.tab_crates, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=4, pady=4)

        left = ttk.Frame(paned)
        right = ttk.Frame(paned)
        paned.add(left, weight=1)
        paned.add(right, weight=2)

        self.crates_tree = ttk.Treeview(left, show="tree")
        self.crates_tree.pack(fill="both", expand=True)
        self.crates_tree.bind("<<TreeviewSelect>>", self._on_crate_selected)

        filter_bar = ttk.Frame(right)
        filter_bar.pack(fill="x", pady=(0, 4))
        ttk.Label(filter_bar, text="Arata:").pack(side="left", padx=(0, 6))
        self.track_filter_var = StringVar(value="toate")
        for value, label in (("toate", "Toate"), ("ok", "Doar OK"), ("lipsa", "Doar lipsa")):
            ttk.Radiobutton(filter_bar, text=label, value=value, variable=self.track_filter_var,
                             command=self._render_tracks_tree).pack(side="left", padx=4)

        self._dot_green = _build_dot_icon(filled=True, color="#2ecc71")
        self._dot_red = _build_dot_icon(filled=True, color="#e74c3c")

        cols = ("artist", "titlu", "cale")
        self.tracks_tree = ttk.Treeview(right, columns=cols, show="tree headings")
        self.tracks_tree.heading("#0", text="Status")
        self.tracks_tree.column("#0", width=60, anchor="center", stretch=False)
        for c, w in zip(cols, (200, 200, 420)):
            self.tracks_tree.heading(c, text=c.capitalize())
            self.tracks_tree.column(c, width=w, anchor="w")
        self.tracks_tree.pack(fill="both", expand=True)

        # mapare: id nod tree -> (library, crate) sau None pt noduri intermediare
        self._crate_node_map: dict[str, tuple[scanner.SeratoLibrary, object]] = {}
        self._current_tracks_data: list[tuple[str, str, str, bool]] = []   # artist, titlu, cale, exista

    def _refresh_crates_tree(self):
        self.crates_tree.delete(*self.crates_tree.get_children())
        self._crate_node_map.clear()

        for lib in self.libraries:
            lib_node = self.crates_tree.insert("", END, text=lib.name, open=False)
            group_nodes: dict[tuple, str] = {}   # prefix hierarhie -> id nod

            for crate in lib.crates:
                parent = lib_node
                prefix: tuple = ()
                for depth, segment in enumerate(crate.hierarchy):
                    prefix = crate.hierarchy[0] if depth == 0 else prefix
                    key = (lib.name,) + tuple(crate.hierarchy[: depth + 1])
                    if key not in group_nodes:
                        node = self.crates_tree.insert(parent, END, text=segment, open=False)
                        group_nodes[key] = node
                    parent = group_nodes[key]
                self._crate_node_map[parent] = (lib, crate)

    def _on_crate_selected(self, _event):
        sel = self.crates_tree.selection()
        if not sel:
            return
        node = sel[0]
        info = self._crate_node_map.get(node)
        if not info:
            self._current_tracks_data = []
            self._render_tracks_tree()
            return
        lib, crate = info
        data = []
        for raw_path in crate.raw_paths:
            abs_path = str(Path(lib.volume_root) / raw_path)
            exists = Path(abs_path).exists()
            track = lib.tracks.get(raw_path)
            title = track.title if track else ""
            artist = track.artist if track else ""
            data.append((artist or "", title or "", abs_path, exists))
        self._current_tracks_data = data
        self._render_tracks_tree()

    def _render_tracks_tree(self):
        self.tracks_tree.delete(*self.tracks_tree.get_children())
        filt = self.track_filter_var.get()
        for artist, title, abs_path, exists in self._current_tracks_data:
            if filt == "ok" and not exists:
                continue
            if filt == "lipsa" and exists:
                continue
            icon = self._dot_green if exists else self._dot_red
            self.tracks_tree.insert("", END, image=icon, values=(artist, title, abs_path))

    # ---------------------------------------------------------- Tab Orfane
    def _build_tab_orphans(self):
        top = ttk.Frame(self.tab_orphans)
        top.pack(fill="x", pady=6)

        ttk.Label(top, text="Scaneaza radacina:").pack(side="left")
        self.orphan_root_var = StringVar()
        self.orphan_combo = ttk.Combobox(top, textvariable=self.orphan_root_var, width=40, state="readonly")
        self.orphan_combo.pack(side="left", padx=4)
        ttk.Button(top, text="Alege folder...", command=self._browse_orphan_root).pack(side="left", padx=4)
        self.scan_orphans_btn = ttk.Button(top, text="Scaneaza dupa orfane", command=self._scan_orphans)
        self.scan_orphans_btn.pack(side="left", padx=10)

        self.orphans_info_var = StringVar(value="")
        ttk.Label(self.tab_orphans, textvariable=self.orphans_info_var).pack(fill="x", padx=4)

        self.orphans_list = ttk.Treeview(self.tab_orphans, columns=("cale", "marime"), show="headings")
        self.orphans_list.heading("cale", text="Cale")
        self.orphans_list.heading("marime", text="Marime")
        self.orphans_list.column("cale", width=700, anchor="w")
        self.orphans_list.column("marime", width=100, anchor="e")
        self.orphans_list.pack(fill="both", expand=True, padx=4, pady=4)

    def _refresh_orphan_lib_choices(self):
        roots = [lib.volume_root for lib in self.libraries]
        self.orphan_combo["values"] = roots
        if roots and not self.orphan_root_var.get():
            self.orphan_root_var.set(roots[0])

    def _browse_orphan_root(self):
        folder = filedialog.askdirectory(title="Alege folderul de scanat")
        if folder:
            self.orphan_root_var.set(folder)

    def _scan_orphans(self):
        root_path = self.orphan_root_var.get().strip()
        if not root_path:
            show_warning(self.root, APP_TITLE, "Alege mai intai un folder de scanat.")
            return

        known: set[str] = set()
        for lib in self.libraries:
            if lib.volume_root == root_path or root_path.startswith(lib.volume_root + "/"):
                known.update(t.abs_path for t in lib.tracks.values())

        self.log(f"Scanez {root_path} dupa fisiere orfane (necunoscute de Serato)...")
        self.scan_orphans_btn["state"] = "disabled"
        t0 = time.time()
        progress_q: queue.Queue = queue.Queue()
        self._begin_busy("scanare fisiere orfane")

        def progress_cb(scanned, orphans_so_far):
            progress_q.put((scanned, orphans_so_far))

        def work():
            orphans = scanner.find_orphan_files(root_path, known, progress_cb=progress_cb)
            elapsed = time.time() - t0
            progress_q.put(None)
            self.root.after(0, lambda: self._on_orphans_found(orphans, elapsed))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(200, lambda: self._poll_orphan_progress(progress_q))

    def _poll_orphan_progress(self, progress_q: queue.Queue):
        last = None
        try:
            while True:
                item = progress_q.get_nowait()
                if item is None:
                    return
                last = item
        except queue.Empty:
            pass
        if last is not None:
            scanned, orphans_so_far = last
            self.set_status(f"Scanez... {scanned} fisiere verificate, {orphans_so_far} orfane pana acum.")
        self.root.after(400, lambda: self._poll_orphan_progress(progress_q))

    def _on_orphans_found(self, orphans: list[Path], elapsed: float):
        self._end_busy("scanare fisiere orfane")
        self.scan_orphans_btn["state"] = "normal"
        self.orphans_list.delete(*self.orphans_list.get_children())
        total_bytes = 0
        for p in orphans:
            try:
                size = p.stat().st_size
            except OSError:
                size = 0
            total_bytes += size
            self.orphans_list.insert("", END, values=(str(p), _human_size(size)))
        count_text = _ro_count(len(orphans), "fisier orfan gasit", "fisiere orfane gasite")
        self.orphans_info_var.set(f"{count_text}, {_human_size(total_bytes)} total.")
        self.set_status("Scanare orfane terminata.")
        self.log(f"Scanare orfane terminata in {elapsed:.1f}s: {count_text}, {_human_size(total_bytes)} total.")

    # ---------------------------------------------------------- Tab Migrare
    def _build_tab_migrate(self):
        top = ttk.Frame(self.tab_migrate)
        top.pack(fill="both", expand=True, pady=6)

        left = ttk.Frame(top)
        left.pack(side="left", fill="y", padx=4)

        self.migrate_checks_frame = ttk.LabelFrame(left, text="Biblioteci de inclus")
        self.migrate_checks_frame.pack(fill="x")

        crates_box = ttk.LabelFrame(left, text="Crate-uri de migrat")
        crates_box.pack(fill="both", expand=True, pady=(8, 0))

        cbtns = ttk.Frame(crates_box)
        cbtns.pack(fill="x", padx=2, pady=2)
        ttk.Button(cbtns, text="Toate", width=8,
                   command=lambda: self._mig_select_all(True)).pack(side="left")
        ttk.Button(cbtns, text="Niciunul", width=9,
                   command=lambda: self._mig_select_all(False)).pack(side="left", padx=4)

        tree_wrap = ttk.Frame(crates_box)
        tree_wrap.pack(fill="both", expand=True, padx=2)
        self.mig_crates_tree = ttk.Treeview(tree_wrap, show="tree", height=14, selectmode="none")
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.mig_crates_tree.yview)
        self.mig_crates_tree.configure(yscrollcommand=vsb.set)
        self.mig_crates_tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.mig_crates_tree.bind("<Button-1>", self._mig_tree_click)

        self.migrate_unsorted_var = BooleanVar(value=True)
        ttk.Checkbutton(
            crates_box, text="Include si track-urile care nu-s in niciun crate",
            variable=self.migrate_unsorted_var,
            command=self._mig_refresh_glyphs).pack(anchor=W, padx=4, pady=(2, 0))

        self.mig_crate_summary_var = StringVar(value="")
        ttk.Label(crates_box, textvariable=self.mig_crate_summary_var,
                  font=(None, BASE_FONT_SIZE - 1)).pack(anchor=W, padx=4, pady=(0, 4))

        # stare selectie crate-uri
        self._mig_leaf_state: dict[str, bool] = {}          # node id -> selectat
        self._mig_leaf_info: dict[str, tuple] = {}          # node id -> (lib, crate)
        self._mig_node_parent: dict[str, str] = {}          # node id -> parinte
        self._mig_group_leaves: dict[str, list[str]] = {}   # node grup/lib -> leaf node ids sub el
        self._mig_crate_size: dict[str, int | None] = {}    # crate_key -> bytes prezenti (None = necalculat)
        self._mig_crate_missing: dict[str, int] = {}
        self._mig_size_queue: queue.Queue = queue.Queue()

        right = ttk.Frame(top)
        right.pack(side="left", fill="both", expand=True, padx=10)

        ttk.Label(right, text="Destinatie:").grid(row=0, column=0, sticky=W)
        self.dest_var = StringVar()
        ttk.Entry(right, textvariable=self.dest_var, width=50).grid(row=0, column=1, sticky=(E, W), padx=4)
        ttk.Button(right, text="Alege...", command=self._browse_dest).grid(row=0, column=2)

        self.copy_serato_var = BooleanVar(value=True)
        self.copy_serato_check = ttk.Checkbutton(
            right, text="Copiaza si folderul _Serato_ (baza de date + crate-urile) la radacina destinatiei",
            variable=self.copy_serato_var, command=self._refresh_space_label)
        self.copy_serato_check.grid(row=1, column=0, columnspan=3, sticky=W, pady=(6, 0))

        self.rewrite_paths_var = BooleanVar(value=True)
        ttk.Checkbutton(
            right, text="Rescrie caile in copia bazei de date (Serato vede totul fara 'Locate Missing Files')",
            variable=self.rewrite_paths_var).grid(row=2, column=0, columnspan=3, sticky=W)

        self.normalize_names_var = BooleanVar(value=True)
        ttk.Checkbutton(
            right, text="Normalizeaza numele SCRISE COMPLET CU MAJUSCULE la Title Case normal",
            variable=self.normalize_names_var).grid(row=3, column=0, columnspan=3, sticky=W)

        btns = ttk.Frame(right)
        btns.grid(row=4, column=0, columnspan=3, pady=10, sticky=W)
        ttk.Button(btns, text="Previzualizare", command=self._preview_migration).pack(side="left")
        self.copy_btn = ttk.Button(btns, text="Copiaza acum", command=self._run_migration, state="disabled")
        self.copy_btn.pack(side="left", padx=6)

        self.migrate_summary_var = StringVar(value="")
        ttk.Label(self.tab_migrate, textvariable=self.migrate_summary_var, justify="left").pack(fill="x", padx=4)

        self.migrate_space_var = StringVar(value="")
        self.migrate_space_lbl = ttk.Label(self.tab_migrate, textvariable=self.migrate_space_var,
                                            justify="left", style="Ok.TLabel")
        self.migrate_space_lbl.pack(fill="x", padx=4)

        self.progress = ttk.Progressbar(self.tab_migrate, orient=HORIZONTAL, mode="determinate")
        self.progress.pack(fill="x", padx=4, pady=4)

        ttk.Label(self.tab_migrate, text="Detaliile copierii apar in tabul 'Jurnal'.",
                  font=(None, BASE_FONT_SIZE - 1)).pack(anchor=W, padx=4)

        self._plan: copier.CopyPlan | None = None
        self._progress_queue: queue.Queue = queue.Queue()

    def _refresh_migrate_checkboxes(self):
        for child in self.migrate_checks_frame.winfo_children():
            child.destroy()
        self.lib_vars.clear()
        for lib in self.libraries:
            var = BooleanVar(value=True)
            self.lib_vars[lib.name] = var
            ttk.Checkbutton(self.migrate_checks_frame, text=f"{lib.name} ({len(lib.tracks)} track-uri)",
                             variable=var, command=self._build_migrate_crate_tree).pack(anchor=W, padx=4, pady=2)
        self._build_migrate_crate_tree()

    # ---------------------------------------------------- selectie crate-uri
    def _build_migrate_crate_tree(self):
        tree = self.mig_crates_tree
        tree.delete(*tree.get_children())
        self._mig_leaf_state.clear()
        self._mig_leaf_info.clear()
        self._mig_node_parent.clear()
        self._mig_group_leaves.clear()

        for lib in self._selected_libraries():
            lib_node = tree.insert("", END, text=f"{CHK_ON} {lib.name}", open=True)
            self._mig_group_leaves[lib_node] = []
            group_nodes: dict[tuple, str] = {}
            for crate in lib.crates:
                parent = lib_node
                for depth, segment in enumerate(crate.hierarchy):
                    key = (lib.name,) + tuple(crate.hierarchy[: depth + 1])
                    is_leaf = depth == len(crate.hierarchy) - 1
                    if key not in group_nodes:
                        node = tree.insert(parent, END, text=f"{CHK_ON} {segment}",
                                            open=False)
                        group_nodes[key] = node
                        self._mig_node_parent[node] = parent
                        if not is_leaf:
                            self._mig_group_leaves[node] = []
                    parent = group_nodes[key]
                # `parent` e acum nodul-frunza al acestui crate
                self._mig_leaf_state[parent] = True
                self._mig_leaf_info[parent] = (lib, crate)
                # inregistreaza frunza la toti stramosii-grup
                anc = self._mig_node_parent.get(parent)
                while anc is not None:
                    self._mig_group_leaves.setdefault(anc, []).append(parent)
                    anc = self._mig_node_parent.get(anc)
                self._mig_group_leaves.setdefault(lib_node, [])
                if parent not in self._mig_group_leaves[lib_node]:
                    self._mig_group_leaves[lib_node].append(parent)

        self._mig_refresh_glyphs()
        self._start_mig_size_computation()

    def _mig_leaf_label(self, node: str) -> str:
        lib, crate = self._mig_leaf_info[node]
        crate_key = str(crate.file_path)
        name = crate.hierarchy[-1]
        size = self._mig_crate_size.get(crate_key)
        n = len(crate.raw_paths)
        if size is None:
            extra = f"{n} track-uri"
        else:
            miss = self._mig_crate_missing.get(crate_key, 0)
            extra = f"{n - miss} track-uri, {_human_size(size)}"
            if miss:
                extra += f", {miss} lipsa"
        state = self._mig_leaf_state.get(node, True)
        return f"{CHK_ON if state else CHK_OFF} {name}  ·  {extra}"

    def _mig_group_glyph(self, node: str) -> str:
        leaves = self._mig_group_leaves.get(node, [])
        if not leaves:
            return CHK_OFF
        vals = [self._mig_leaf_state.get(l, True) for l in leaves]
        if all(vals):
            return CHK_ON
        if not any(vals):
            return CHK_OFF
        return CHK_PART

    def _mig_refresh_glyphs(self):
        tree = self.mig_crates_tree
        for node in self._mig_leaf_state:
            tree.item(node, text=self._mig_leaf_label(node))
        for node in list(self._mig_group_leaves):
            if node in self._mig_leaf_state:
                continue
            cur = tree.item(node, "text")
            rest = cur.split(" ", 1)[1] if " " in cur else cur
            tree.item(node, text=f"{self._mig_group_glyph(node)} {rest}")
        # sumar
        total_leaves = len(self._mig_leaf_state)
        sel = [n for n, v in self._mig_leaf_state.items() if v]
        sel_bytes = 0
        have_all_sizes = True
        for n in sel:
            _lib, crate = self._mig_leaf_info[n]
            s = self._mig_crate_size.get(str(crate.file_path))
            if s is None:
                have_all_sizes = False
            else:
                sel_bytes += s
        approx = "" if have_all_sizes else " (se calculeaza...)"
        size_txt = f" · ~{_human_size(sel_bytes)}{approx}" if sel else ""
        unsorted = "  + ne-incadrate" if self.migrate_unsorted_var.get() else ""
        self.mig_crate_summary_var.set(
            f"{len(sel)}/{total_leaves} crate-uri selectate{size_txt}{unsorted}")

    def _mig_tree_click(self, event):
        tree = self.mig_crates_tree
        # click pe triunghiul de expandare -> lasa comportamentul implicit
        if tree.identify_element(event.x, event.y) == "Treeitem.indicator":
            return
        node = tree.identify_row(event.y)
        if not node:
            return
        # nodul-biblioteca (radacina) nu are parinte inregistrat si nu e frunza
        if node in self._mig_leaf_state:
            new = not self._mig_leaf_state[node]
            self._mig_leaf_state[node] = new
        else:
            leaves = self._mig_group_leaves.get(node, [])
            if not leaves:
                return
            new = not all(self._mig_leaf_state.get(l, True) for l in leaves)
            for l in leaves:
                self._mig_leaf_state[l] = new
        self._mig_refresh_glyphs()

    def _mig_select_all(self, value: bool):
        for n in self._mig_leaf_state:
            self._mig_leaf_state[n] = value
        self._mig_refresh_glyphs()

    def _start_mig_size_computation(self):
        pending = []
        for node, (lib, crate) in self._mig_leaf_info.items():
            ck = str(crate.file_path)
            if ck not in self._mig_crate_size:
                pending.append((lib, crate))
        if not pending:
            return

        def work():
            for lib, crate in pending:
                present, missing, nbytes = copier.crate_stats(lib, crate)
                self._mig_size_queue.put((str(crate.file_path), missing, nbytes))
            self._mig_size_queue.put(None)

        threading.Thread(target=work, daemon=True).start()
        self.root.after(150, self._poll_mig_sizes)

    def _poll_mig_sizes(self):
        changed = False
        try:
            while True:
                item = self._mig_size_queue.get_nowait()
                if item is None:
                    if changed:
                        self._mig_refresh_glyphs()
                    return
                ck, missing, nbytes = item
                self._mig_crate_size[ck] = nbytes
                self._mig_crate_missing[ck] = missing
                changed = True
        except queue.Empty:
            pass
        if changed:
            self._mig_refresh_glyphs()
        self.root.after(200, self._poll_mig_sizes)

    def _selected_crate_keys(self) -> set[str] | None:
        """None = migrare completa (toate crate-urile + ne-incadrate), comportament
        implicit. Altfel, setul de chei de crate de migrat."""
        if not self._mig_leaf_state:
            return None
        all_selected = all(self._mig_leaf_state.values())
        if all_selected and self.migrate_unsorted_var.get():
            return None
        return {
            str(crate.file_path)
            for node, (lib, crate) in self._mig_leaf_info.items()
            if self._mig_leaf_state.get(node)
        }

    def _browse_dest(self):
        folder = filedialog.askdirectory(title="Alege folderul destinatie")
        if folder:
            self.dest_var.set(folder)

    def _selected_libraries(self) -> list[scanner.SeratoLibrary]:
        return [lib for lib in self.libraries if self.lib_vars.get(lib.name) and self.lib_vars[lib.name].get()]

    def _preview_migration(self):
        dest = self.dest_var.get().strip()
        if not dest:
            show_warning(self.root, APP_TITLE, "Alege mai intai folderul destinatie.")
            return
        libs = self._selected_libraries()
        if not libs:
            show_warning(self.root, APP_TITLE, "Bifeaza cel putin o biblioteca.")
            return

        selected_crate_keys = self._selected_crate_keys()
        include_unsorted = self.migrate_unsorted_var.get()
        if selected_crate_keys is not None and not selected_crate_keys and not include_unsorted:
            show_warning(self.root, APP_TITLE, "Selecteaza cel putin un crate sau bifeaza "
                                               "'Include si track-urile care nu-s in niciun crate'.")
            return

        self.set_status("Calculez planul de copiere...")
        scope = "toate crate-urile" if selected_crate_keys is None else f"{len(selected_crate_keys)} crate-uri"
        self.log(f"Calculez planul de copiere pentru {', '.join(l.name for l in libs)} "
                 f"({scope}) -> {dest}...")

        normalize_names = self.normalize_names_var.get()

        def work():
            plan = copier.plan_copy(libs, Path(dest), normalize_names=normalize_names,
                                     selected_crate_keys=selected_crate_keys,
                                     include_unsorted=include_unsorted)
            self.root.after(0, lambda: self._on_plan_ready(plan))

        threading.Thread(target=work, daemon=True).start()

    def _space_report(self, plan: copier.CopyPlan, copy_serato: bool):
        """(required_bytes, free_bytes, fits) pentru planul curent si destinatie.
        free_bytes poate fi None daca nu se poate afla spatiul liber."""
        dest = self.dest_var.get().strip()
        if not dest:
            return None
        selected = self._selected_libraries()
        serato_dir = selected[0].serato_dir if (copy_serato and len(selected) == 1) else None
        required = copier.estimate_required_bytes(plan, Path(dest), serato_dir)
        free = copier.free_space(Path(dest))
        fits = free is None or required <= free
        return required, free, fits

    def _refresh_space_label(self):
        if not self._plan:
            self.migrate_space_var.set("")
            return
        report = self._space_report(self._plan, self.copy_serato_var.get())
        if report is None:
            self.migrate_space_var.set("")
            return
        required, free, fits = report
        if free is None:
            self.migrate_space_lbl.configure(style="Ok.TLabel")
            self.migrate_space_var.set(f"Necesar pe destinatie: ~{_human_size(required)} "
                                        f"(spatiul liber nu a putut fi verificat).")
            return
        if fits:
            self.migrate_space_lbl.configure(style="Ok.TLabel")
            self.migrate_space_var.set(
                f"Incape: necesar ~{_human_size(required)}, liber pe destinatie {_human_size(free)} "
                f"(ramane ~{_human_size(free - required)}).")
        else:
            self.migrate_space_lbl.configure(style="Warn.TLabel")
            self.migrate_space_var.set(
                f"NU INCAPE: necesar ~{_human_size(required)}, liber pe destinatie doar "
                f"{_human_size(free)}. Lipsesc ~{_human_size(required - free)}. "
                f"Debifeaza biblioteci/foldere sau alege alta destinatie.")

    def _on_plan_ready(self, plan: copier.CopyPlan):
        self._plan = plan
        self.log(f"Plan gata: {plan.primary_count} copii, {plan.link_count} hardlink-uri, "
                 f"{_human_size(plan.total_bytes)}, {len(plan.skipped_missing)} lipsa sarite.")
        summary = (
            f"Copii reale: {plan.primary_count}   |   "
            f"Hard link-uri (duplicate, fara spatiu suplimentar): {plan.link_count}   |   "
            f"Marime totala de copiat: {_human_size(plan.total_bytes)}   |   "
            f"Track-uri lipsa (sarite): {len(plan.skipped_missing)}"
        )
        self.migrate_summary_var.set(summary)
        self._refresh_space_label()
        report = self._space_report(plan, self.copy_serato_var.get())
        if report and report[1] is not None:
            required, free, fits = report
            verdict = "incape" if fits else f"NU INCAPE, lipsesc {_human_size(required - free)}"
            self.log(f"Spatiu destinatie: necesar ~{_human_size(required)}, liber {_human_size(free)} -> {verdict}.")
        self.progress["value"] = 0
        self.progress["maximum"] = len(plan.operations)
        self.copy_btn["state"] = "normal" if plan.operations else "disabled"
        self.set_status("Plan gata. Verifica si apasa 'Copiaza acum'.")

    def _run_migration(self):
        if not self._plan or not self._plan.operations:
            return

        copy_serato = self.copy_serato_var.get()
        if copy_serato and not self._guard_serato_not_running():
            return

        selected_libs = self._selected_libraries()
        if copy_serato and len(selected_libs) != 1:
            show_warning(
                self.root, APP_TITLE,
                "Copierea folderului _Serato_ functioneaza doar cu exact o biblioteca bifata "
                "(fiecare biblioteca are propria baza de date - nu are sens sa le amestecam).\n\n"
                "Debifeaza 'Copiaza si folderul _Serato_' sau bifeaza o singura biblioteca.")
            return

        rewrite_paths = self.rewrite_paths_var.get() and copy_serato

        report = self._space_report(self._plan, copy_serato)
        if report is not None:
            required, free, fits = report
            if not fits and free is not None:
                if not ask_yesno(
                    self.root, APP_TITLE,
                    f"NU INCAPE pe destinatie.\n\n"
                    f"Necesar: ~{_human_size(required)}\n"
                    f"Liber pe destinatie: {_human_size(free)}\n"
                    f"Lipsesc: ~{_human_size(required - free)}\n\n"
                    f"Copierea se va opri cu eroare cand se umple discul, iar biblioteca "
                    f"Serato copiata va fi incompleta. Recomandat: renunta, debifeaza "
                    f"biblioteci sau alege alta destinatie.\n\nContinui totusi?",
                ):
                    return

        extra_msg = ""
        if copy_serato:
            extra_msg = (f"\n\nSe copiaza si folderul _Serato_ (baza de date + crate-urile) "
                         f"al bibliotecii '{selected_libs[0].name}' la radacina destinatiei.")
        if rewrite_paths:
            extra_msg += ("\n\nCopia bazei de date va fi rescrisa cu noile cai - Serato va vedea "
                          "track-urile direct, fara 'Locate Missing Files'. Originalul NU e atins.")

        if not ask_yesno(
            self.root, APP_TITLE,
            f"Se vor copia {self._plan.primary_count} fisiere "
            f"({_human_size(self._plan.total_bytes)}) plus {self._plan.link_count} hard link-uri."
            f"{extra_msg}\n\nFisierele originale NU sunt sterse. Continui?",
        ):
            return

        self.copy_btn["state"] = "disabled"
        self.log(f"Incep copierea: {self._plan.primary_count} fisiere, {_human_size(self._plan.total_bytes)}.")
        plan = self._plan
        dest_root = Path(self.dest_var.get().strip())
        self._begin_busy("migrare")

        def progress_cb(done, total, op: copier.CopyOperation):
            self._progress_queue.put((done, total, op))

        def work():
            try:
                copier.execute_plan(plan, progress_callback=progress_cb)
                if copy_serato:
                    self._progress_queue.put(("serato_start",))
                    dest_serato_dir = copier.copy_serato_folder(selected_libs[0], dest_root)
                    self._progress_queue.put(("serato_done",))
                    if rewrite_paths:
                        self._progress_queue.put(("rewrite_start",))
                        copier.rewrite_serato_database(selected_libs[0], plan, dest_serato_dir, dest_root)
                        self._progress_queue.put(("rewrite_done",))
                self._progress_queue.put(None)  # semnal de final OK
            except Exception as exc:  # noqa: BLE001 - raportam orice in UI
                self._progress_queue.put(("error", repr(exc)))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(100, self._poll_progress)

    def _poll_progress(self):
        try:
            while True:
                item = self._progress_queue.get_nowait()
                if item is None:
                    self._end_busy("migrare")
                    self.set_status("Copiere terminata.")
                    self.log("Copiere terminata.")
                    show_info(self.root, APP_TITLE, "Copierea s-a terminat.")
                    self.copy_btn["state"] = "normal"
                    return
                if item[0] == "error":
                    self._end_busy("migrare")
                    self.set_status("Copiere esuata.")
                    self.log(f"EROARE la copiere: {item[1]}")
                    show_warning(self.root, APP_TITLE, f"Copierea a esuat:\n\n{item[1]}")
                    self.copy_btn["state"] = "normal"
                    return
                if item[0] == "serato_start":
                    self.set_status("Copiez folderul _Serato_ (baza de date + crate-urile)...")
                    self.log("Copiez folderul _Serato_ la radacina destinatiei...")
                    continue
                if item[0] == "serato_done":
                    self.log("Folder _Serato_ copiat cu succes.")
                    continue
                if item[0] == "rewrite_start":
                    self.set_status("Rescriu caile in copia bazei de date...")
                    self.log("Rescriu caile in copia bazei de date si in crate-uri...")
                    continue
                if item[0] == "rewrite_done":
                    self.log("Caile din copia bazei de date au fost actualizate. "
                              "Serato ar trebui sa vada track-urile direct, fara relocate.")
                    continue
                done, total, op = item
                self.progress["value"] = done
                self.set_status(f"Copiere: {done}/{total}...")
                kind = "copiat" if op.is_primary else "hardlink"
                self.log(f"[{done}/{total}] ({kind}) {op.dest_path}")
        except queue.Empty:
            pass
        self.root.after(150, self._poll_progress)


def _ro_count(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _human_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def main():
    root = Tk()
    root.withdraw()

    icon = _build_app_icon()
    root.iconphoto(True, icon)
    root._app_icon_ref = icon   # pastreaza referinta, altfel Tk arunca imaginea

    def reveal():
        SeratoMigratorApp(root)
        root.deiconify()

    _show_splash(root, reveal)
    root.mainloop()


if __name__ == "__main__":
    main()
