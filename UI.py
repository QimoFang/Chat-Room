"""
UI.py
=====
Modern desktop chat interface.

A self-contained, runnable Tkinter module that renders a contemporary
three-pane chat surface (sidebar / conversation / inspector) inspired
by Linear / Telegram / WeChat. Designed to slot into the existing
Chat Room project as a drop-in UI layer.

Usage
-----
    python UI.py            # launch demo window with sample data
    from UI import ChatApp  # import the application class

Design notes
------------
* Linear-style restraint: one accent color, calm surface hierarchy,
  no decorative card mosaic.
* Single typeface, generous spacing, hairline borders.
* Message bubbles drawn on a Canvas for pixel-perfect control.
* Tasteful motion: short fade / slide on insert, button-press feedback.
"""

from __future__ import annotations

import math
import time
import random
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass, field
from typing import Callable, List, Optional


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
class Theme:
    """Single source of truth for the visual system."""

    # Surface
    BG_APP = "#F4F5F7"          # app background
    BG_SIDEBAR = "#FFFFFF"      # left rail
    BG_MAIN = "#FFFFFF"         # conversation
    BG_INSPECTOR = "#FAFAFB"   # right rail
    BG_HOVER = "#EEF0F3"        # list hover
    BG_ACTIVE = "#E7F3FF"       # selected list row
    BG_INPUT = "#F4F5F7"        # input field
    BG_CHIP = "#F0F2F5"         # chip / pill background
    BG_BUBBLE_SENT = "#0084FF"  # outgoing bubble
    BG_BUBBLE_RECV = "#F0F2F5"  # incoming bubble
    BG_DIVIDER_DAY = "#E4E6EB"  # date pill border
    BG_SENT_TAIL = "#006FD6"    # subtle tail / shadow for sent

    # Text
    TEXT_PRIMARY = "#050505"
    TEXT_SECONDARY = "#65676B"
    TEXT_TERTIARY = "#8A8D91"
    TEXT_INVERSE = "#FFFFFF"
    TEXT_ACCENT = "#0084FF"
    TEXT_BUBBLE_SENT = "#FFFFFF"
    TEXT_BUBBLE_RECV = "#050505"

    # Lines
    BORDER = "#E4E6EB"
    BORDER_SOFT = "#F0F2F5"

    # Accent / state
    PRIMARY = "#0084FF"
    PRIMARY_HOVER = "#1976D2"
    SUCCESS = "#07C160"
    DANGER = "#F02849"
    WARNING = "#FFB400"

    # Layout
    SIDEBAR_WIDTH = 280
    INSPECTOR_WIDTH = 0  # hidden by default, toggleable
    HEADER_HEIGHT = 60
    INPUT_HEIGHT = 76

    # Typography
    FONT_FAMILY = "Segoe UI"
    FONT_FAMILY_CN = "微软雅黑"
    FONT_SIZE_NAME = 14
    FONT_SIZE_PREVIEW = 12
    FONT_SIZE_HEADER = 15
    FONT_SIZE_BODY = 14
    FONT_SIZE_META = 11
    FONT_SIZE_DAY = 11

    # Motion
    ANIM_FAST = 120
    ANIM_NORMAL = 200
    ANIM_SLOW = 320


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------
@dataclass
class Contact:
    name: str
    subtitle: str = ""          # e.g. "@handle" or last seen
    avatar_color: str = "#0084FF"
    avatar_initials: str = ""
    online: bool = False
    unread: int = 0
    preview: str = ""
    timestamp: str = ""
    pinned: bool = False
    is_group: bool = False
    members: int = 0
    accent: str = ""            # optional override for the row


@dataclass
class Message:
    text: str
    sender: str                 # "me" or contact name
    timestamp: str
    status: str = "sent"        # sent / delivered / read / failed
    pending: bool = False


# ---------------------------------------------------------------------------
# Animation helpers
# ---------------------------------------------------------------------------
class Anim:
    """Tiny tween helpers built on Tk's after()."""

    @staticmethod
    def _tween(start: float, end: float, step: int, total: int) -> float:
        if total <= 0:
            return end
        # ease-out cubic
        t = max(0.0, min(1.0, step / total))
        eased = 1 - (1 - t) ** 3
        return start + (end - start) * eased

    @classmethod
    def fade(cls, widget: tk.Widget, start: float, end: float,
             duration: int, on_done: Optional[Callable] = None,
             steps: int = 20):
        if duration <= 0:
            try:
                widget.attributes("-alpha", end)
            except Exception:
                pass
            if on_done:
                on_done()
            return

        interval = max(1, duration // steps)
        state = {"step": 0, "total": steps}

        def tick():
            state["step"] += 1
            v = cls._tween(start, end, state["step"], state["total"])
            try:
                widget.attributes("-alpha", v)
            except Exception:
                pass
            if state["step"] >= state["total"]:
                if on_done:
                    on_done()
            else:
                widget.after(interval, tick)

        widget.after(interval, tick)

    @staticmethod
    def slide_y(widget: tk.Widget, start_y: int, end_y: int,
                duration: int, on_done: Optional[Callable] = None,
                steps: int = 18):
        if duration <= 0:
            widget.place(y=end_y)
            if on_done:
                on_done()
            return

        interval = max(1, duration // steps)
        state = {"step": 0, "total": steps}

        def tick():
            state["step"] += 1
            t = state["step"] / state["total"]
            eased = 1 - (1 - t) ** 3
            y = start_y + (end_y - start_y) * eased
            widget.place(y=int(y))
            if state["step"] >= state["total"]:
                if on_done:
                    on_done()
            else:
                widget.after(interval, tick)

        widget.after(interval, tick)

    @staticmethod
    def color_to(c1: str, c2: str, t: float) -> str:
        def hx(s): return int(s, 16)
        r1, g1, b1 = hx(c1[1:3]), hx(c1[3:5]), hx(c1[5:7])
        r2, g2, b2 = hx(c2[1:3]), hx(c2[3:5]), hx(c2[5:7])
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02X}{g:02X}{b:02X}"


# ---------------------------------------------------------------------------
# Reusable building blocks
# ---------------------------------------------------------------------------
class Avatar(tk.Canvas):
    """A circular avatar that can show initials, a solid color, or a photo."""

    SIZE = 40

    def __init__(self, master, color: str, initials: str, size: int = SIZE, **kw):
        super().__init__(master, width=size, height=size,
                         bg=kw.pop("bg", Theme.BG_SIDEBAR),
                         highlightthickness=0, bd=0, **kw)
        self.size = size
        self.color = color
        self.initials = initials
        self._draw()

    def set_color(self, color: str, initials: Optional[str] = None):
        self.color = color
        if initials is not None:
            self.initials = initials
        self._draw()

    def _draw(self):
        self.delete("all")
        s = self.size
        pad = 1
        # subtle ring
        self.create_oval(pad, pad, s - pad, s - pad,
                         fill=self.color, outline=Theme.BORDER, width=1)
        # initials
        if self.initials:
            font = tkfont.Font(family=Theme.FONT_FAMILY, size=max(10, s // 2 - 6),
                               weight="bold")
            self.create_text(s / 2, s / 2, text=self.initials,
                             fill="#FFFFFF", font=font)


class FlatButton(tk.Label):
    """A borderless, focus-less button with hover/press feedback."""

    def __init__(self, master, text: str = "", icon: str = "",
                 bg: str = Theme.BG_SIDEBAR,
                 hover_bg: str = Theme.BG_HOVER,
                 active_bg: str = Theme.BG_HOVER,
                 fg: str = Theme.TEXT_PRIMARY,
                 font: Optional[tkfont.Font] = None,
                 padx: int = 10, pady: int = 6,
                 radius: int = 8,
                 command: Optional[Callable] = None,
                 **kw):
        super().__init__(master, text=(text or icon), bg=bg, fg=fg,
                         cursor="hand2", font=font or (
                             Theme.FONT_FAMILY, Theme.FONT_SIZE_BODY),
                         padx=padx, pady=pady, **kw)
        self._bg = bg
        self._hover = hover_bg
        self._active = active_bg
        self._command = command
        self._radius = radius
        self._pressed = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def _on_enter(self, _):
        if not self._pressed:
            self.config(bg=self._hover)

    def _on_leave(self, _):
        self._pressed = False
        self.config(bg=self._bg)

    def _on_press(self, _):
        self._pressed = True
        self.config(bg=self._active)

    def _on_release(self, e):
        was_pressed = self._pressed
        self._pressed = False
        # only fire if released inside widget
        x, y = e.widget.winfo_pointerxy()
        rx, ry = self.winfo_rootx(), self.winfo_rooty()
        w, h = self.winfo_width(), self.winfo_height()
        if rx <= x <= rx + w and ry <= y <= ry + h:
            self.config(bg=self._hover)
            if was_pressed and self._command:
                self._command()
        else:
            self.config(bg=self._bg)


class IconButton(tk.Label):
    """Compact square icon-only button (used in headers / toolbars)."""

    def __init__(self, master, icon: str, command: Optional[Callable] = None,
                 size: int = 36, font_size: int = 16, **kw):
        bg = kw.pop("bg", Theme.BG_MAIN)
        fg = kw.pop("fg", Theme.TEXT_SECONDARY)
        hover_bg = kw.pop("hover_bg", Theme.BG_HOVER)
        super().__init__(master, text=icon, bg=bg, fg=fg,
                         font=(Theme.FONT_FAMILY, font_size),
                         width=size // 9, height=size // 18,
                         cursor="hand2", **kw)
        self._bg = bg
        self._hover = hover_bg
        self._fg_default = fg
        self._command = command
        self.bind("<Enter>", lambda _: self.config(bg=self._hover, fg=Theme.TEXT_PRIMARY))
        self.bind("<Leave>", lambda _: self.config(bg=self._bg, fg=self._fg_default))
        self.bind("<Button-1>", lambda _: self._command() if self._command else None)


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
class Sidebar(tk.Frame):
    """Left rail: search + contact list + footer."""

    def __init__(self, master, on_select: Callable[[Contact], None],
                 on_new_chat: Optional[Callable] = None):
        super().__init__(master, bg=Theme.BG_SIDEBAR, width=Theme.SIDEBAR_WIDTH)
        self.pack_propagate(False)
        self.on_select = on_select
        self.contacts: List[Contact] = []
        self.rows: List["ContactRow"] = []
        self._selected_index: int = -1

        self._build_header(on_new_chat)
        self._build_search()
        self._build_list()
        self._build_footer()

    # ----- sections
    def _build_header(self, on_new_chat):
        header = tk.Frame(self, bg=Theme.BG_SIDEBAR, height=64)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        # Title
        title = tk.Label(header, text="消息",
                         bg=Theme.BG_SIDEBAR, fg=Theme.TEXT_PRIMARY,
                         font=(Theme.FONT_FAMILY, 18, "bold"))
        title.pack(side=tk.LEFT, padx=20, pady=18)

        # New chat
        new_btn = IconButton(header, "✏️", command=on_new_chat or (lambda: None),
                             size=36, font_size=14,
                             bg=Theme.BG_SIDEBAR,
                             fg=Theme.TEXT_SECONDARY,
                             hover_bg=Theme.BG_HOVER)
        new_btn.pack(side=tk.RIGHT, padx=12, pady=14)

        # separator
        tk.Frame(self, bg=Theme.BORDER_SOFT, height=1).pack(fill=tk.X)

    def _build_search(self):
        wrap = tk.Frame(self, bg=Theme.BG_SIDEBAR)
        wrap.pack(fill=tk.X, padx=14, pady=(12, 8))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._refresh_filter())
        entry = tk.Entry(wrap, textvariable=self.search_var,
                         bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY,
                         insertbackground=Theme.TEXT_PRIMARY,
                         relief=tk.FLAT, bd=0,
                         font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_PREVIEW),
                         highlightthickness=0)
        entry.insert(0, "🔍  搜索")
        entry.config(fg=Theme.TEXT_TERTIARY)
        entry.bind("<FocusIn>", lambda _: (
            entry.delete(0, tk.END),
            entry.config(fg=Theme.TEXT_PRIMARY)))
        entry.bind("<FocusOut>", lambda _: (
            entry.delete(0, tk.END),
            entry.insert(0, "🔍  搜索"),
            entry.config(fg=Theme.TEXT_TERTIARY)))
        entry.pack(fill=tk.X, ipady=8)

    def _build_list(self):
        wrap = tk.Frame(self, bg=Theme.BG_SIDEBAR)
        wrap.pack(fill=tk.BOTH, expand=True)
        # canvas-based list for unlimited rows
        self.canvas = tk.Canvas(wrap, bg=Theme.BG_SIDEBAR,
                                highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(wrap, orient=tk.VERTICAL,
                                      command=self.canvas.yview,
                                      width=4, troughcolor=Theme.BG_SIDEBAR,
                                      bg=Theme.BG_SIDEBAR)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.scrollbar.pack_forget()

        self.list_inner = tk.Frame(self.canvas, bg=Theme.BG_SIDEBAR)
        self._list_window = self.canvas.create_window(
            (0, 0), window=self.list_inner, anchor="nw")
        self.list_inner.bind(
            "<Configure>",
            lambda _: self.canvas.configure(
                scrollregion=self.canvas.bbox("all")))
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(
                self._list_window, width=e.width))

        self.canvas.bind("<Enter>", lambda _: self._show_sb())
        self.canvas.bind("<Leave>", lambda _: self._schedule_hide_sb())
        self.canvas.bind("<MouseWheel>", self._on_wheel)

    def _build_footer(self):
        tk.Frame(self, bg=Theme.BORDER_SOFT, height=1).pack(fill=tk.X, side=tk.TOP)
        foot = tk.Frame(self, bg=Theme.BG_SIDEBAR, height=56)
        foot.pack(side=tk.BOTTOM, fill=tk.X)
        foot.pack_propagate(False)

        Avatar(foot, color="#0084FF", initials="M", size=32).pack(
            side=tk.LEFT, padx=(14, 10), pady=12)

        info = tk.Frame(foot, bg=Theme.BG_SIDEBAR)
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=10)
        tk.Label(info, text="Mei", bg=Theme.BG_SIDEBAR,
                 fg=Theme.TEXT_PRIMARY,
                 font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_BODY, "bold")
                 ).pack(anchor="w")
        tk.Label(info, text="在线", bg=Theme.BG_SIDEBAR,
                 fg=Theme.SUCCESS,
                 font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_META)
                 ).pack(anchor="w")

        IconButton(foot, "⚙", size=36, font_size=16,
                   bg=Theme.BG_SIDEBAR, fg=Theme.TEXT_SECONDARY,
                   hover_bg=Theme.BG_HOVER).pack(side=tk.RIGHT, padx=12)

    # ----- list API
    def set_contacts(self, contacts: List[Contact]):
        self.contacts = contacts
        self._render_rows()

    def _render_rows(self):
        for w in self.list_inner.winfo_children():
            w.destroy()
        self.rows.clear()
        for i, c in enumerate(self.contacts):
            row = ContactRow(self.list_inner, c, i,
                             on_click=lambda ci=i: self._select(ci))
            row.pack(fill=tk.X)
            self.rows.append(row)
        if self.rows and self._selected_index < 0:
            self._select(0, fire=False)

    def _select(self, index: int, fire: bool = True):
        if not (0 <= index < len(self.rows)):
            return
        for i, r in enumerate(self.rows):
            r.set_active(i == index)
        self._selected_index = index
        if fire:
            self.on_select(self.contacts[index])

    def _refresh_filter(self):
        q = self.search_var.get().strip()
        if q.startswith("🔍"):
            q = ""
        q = q.lower()
        for r in self.rows:
            c = r.contact
            visible = (not q) or (q in c.name.lower()) or (q in c.preview.lower())
            r.pack(fill=tk.X) if visible else r.pack_forget()

    # ----- scrollbar
    def _show_sb(self):
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _schedule_hide_sb(self):
        self.after(180, self._hide_sb_if_leave)

    def _hide_sb_if_leave(self):
        x, y = self.canvas.winfo_pointerxy()
        rx, ry = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if not (rx <= x <= rx + w and ry <= y <= ry + h):
            self.scrollbar.pack_forget()

    def _on_scroll(self, *args):
        # args is e.g. ("0.0", "0.5") from the canvas
        self.scrollbar.set(*args)
        self._show_sb()
        self._schedule_hide_sb()

    def _on_wheel(self, e):
        delta = -1 if e.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")


class ContactRow(tk.Frame):
    """A single row in the sidebar list."""

    HEIGHT = 68

    def __init__(self, master, contact: Contact, index: int,
                 on_click: Callable):
        super().__init__(master, bg=Theme.BG_SIDEBAR, height=self.HEIGHT)
        self.pack_propagate(False)
        self.contact = contact
        self.index = index
        self._on_click = on_click
        self._active = False
        self._hover = False

        # avatar
        self.avatar = Avatar(self, contact.avatar_color,
                             contact.avatar_initials, size=44)
        self.avatar.pack(side=tk.LEFT, padx=(14, 10), pady=12)

        # online dot overlay (small green circle at bottom-right of avatar)
        if contact.online and not contact.is_group:
            self._online_dot = tk.Frame(self, bg=Theme.SUCCESS,
                                        width=10, height=10,
                                        highlightbackground=Theme.BG_SIDEBAR,
                                        highlightthickness=2)
            self._online_dot.place(x=14 + 36, y=12 + 36, anchor="center")

        # text column
        text_col = tk.Frame(self, bg=Theme.BG_SIDEBAR)
        text_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=12)
        text_col.pack_propagate(False)

        # top: name + time
        top = tk.Frame(text_col, bg=Theme.BG_SIDEBAR)
        top.pack(fill=tk.X)
        name_font = (Theme.FONT_FAMILY, Theme.FONT_SIZE_BODY,
                     "bold" if contact.unread else "normal")
        self.name_lbl = tk.Label(top, text=contact.name, bg=Theme.BG_SIDEBAR,
                                 fg=Theme.TEXT_PRIMARY, font=name_font,
                                 anchor="w")
        self.name_lbl.pack(side=tk.LEFT)

        if contact.timestamp:
            ts = tk.Label(top, text=contact.timestamp, bg=Theme.BG_SIDEBAR,
                          fg=Theme.TEXT_TERTIARY,
                          font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_META))
            ts.pack(side=tk.RIGHT, padx=(0, 14))

        # bottom: preview (+ badge)
        bot = tk.Frame(text_col, bg=Theme.BG_SIDEBAR)
        bot.pack(fill=tk.X, pady=(2, 0))
        preview_text = contact.preview or contact.subtitle
        self.preview_lbl = tk.Label(
            bot, text=preview_text, bg=Theme.BG_SIDEBAR,
            fg=Theme.TEXT_SECONDARY,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_PREVIEW),
            anchor="w")
        self.preview_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        if contact.unread > 0:
            self.badge = tk.Label(
                bot, text=str(min(contact.unread, 99)) if contact.unread < 100
                else "99+",
                bg=Theme.DANGER, fg="#FFFFFF",
                font=(Theme.FONT_FAMILY, 10, "bold"),
                padx=6, pady=1)
            self.badge.pack(side=tk.RIGHT, padx=(0, 14))

        # hover/click bindings (apply to children too)
        for w in (self, self.avatar, text_col, top, bot,
                  self.name_lbl, self.preview_lbl):
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)
            w.bind("<Button-1>", self._on_press)

    def set_active(self, active: bool):
        self._active = active
        self._apply_bg(Theme.BG_ACTIVE if active
                       else (Theme.BG_HOVER if self._hover else Theme.BG_SIDEBAR))

    def _on_enter(self, _=None):
        self._hover = True
        if not self._active:
            self._apply_bg(Theme.BG_HOVER)

    def _on_leave(self, _=None):
        self._hover = False
        if not self._active:
            self._apply_bg(Theme.BG_SIDEBAR)

    def _on_press(self, _=None):
        self._on_click()

    def _apply_bg(self, color: str):
        for w in self.winfo_children():
            try:
                w.config(bg=color)
            except tk.TclError:
                pass
        for w in self.winfo_children():
            for sub in w.winfo_children():
                try:
                    if isinstance(sub, Avatar):
                        sub.config(bg=color)
                    else:
                        sub.config(bg=color)
                except tk.TclError:
                    pass


# ---------------------------------------------------------------------------
# Conversation pane
# ---------------------------------------------------------------------------
class ChatHeader(tk.Frame):
    """Top bar of the main chat: avatar, name, status, action buttons."""

    def __init__(self, master, contact: Contact,
                 on_call: Optional[Callable] = None,
                 on_video: Optional[Callable] = None,
                 on_search: Optional[Callable] = None,
                 on_more: Optional[Callable] = None):
        super().__init__(master, bg=Theme.BG_MAIN,
                         height=Theme.HEADER_HEIGHT)
        self.pack_propagate(False)

        left = tk.Frame(self, bg=Theme.BG_MAIN)
        left.pack(side=tk.LEFT, padx=20, pady=10)

        Avatar(left, contact.avatar_color, contact.avatar_initials,
               size=40).pack(side=tk.LEFT, padx=(0, 12))

        info = tk.Frame(left, bg=Theme.BG_MAIN)
        info.pack(side=tk.LEFT)
        self.name_lbl = tk.Label(
            info, text=contact.name, bg=Theme.BG_MAIN,
            fg=Theme.TEXT_PRIMARY,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_HEADER, "bold"))
        self.name_lbl.pack(anchor="w")
        status_text = "在线" if contact.online else contact.subtitle
        if contact.is_group:
            status_text = f"{contact.members} 位成员"
        self.status_lbl = tk.Label(
            info, text=status_text, bg=Theme.BG_MAIN,
            fg=Theme.SUCCESS if contact.online else Theme.TEXT_TERTIARY,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_META))
        self.status_lbl.pack(anchor="w")

        # right toolbar
        right = tk.Frame(self, bg=Theme.BG_MAIN)
        right.pack(side=tk.RIGHT, padx=14, pady=12)
        for icon, cb in (("📞", on_call), ("📹", on_video),
                          ("🔍", on_search), ("⋮", on_more)):
            IconButton(right, icon, command=cb, size=36, font_size=16,
                       bg=Theme.BG_MAIN, fg=Theme.TEXT_SECONDARY,
                       hover_bg=Theme.BG_HOVER).pack(side=tk.LEFT, padx=2)

        # bottom hairline
        tk.Frame(self, bg=Theme.BORDER, height=1).pack(side=tk.BOTTOM, fill=tk.X)


class MessageArea(tk.Frame):
    """Canvas-based scrolling message list with date dividers."""

    def __init__(self, master, on_height_change: Optional[Callable] = None):
        super().__init__(master, bg=Theme.BG_MAIN)

        self.canvas = tk.Canvas(self, bg=Theme.BG_MAIN,
                                highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(self, orient=tk.VERTICAL,
                                      command=self.canvas.yview, width=4,
                                      troughcolor=Theme.BG_MAIN,
                                      bg=Theme.BG_MAIN)
        self.canvas.configure(yscrollcommand=self._on_scroll)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.scrollbar.pack_forget()

        self.canvas.bind("<Enter>", lambda _: self._show_sb())
        self.canvas.bind("<Leave>", lambda _: self._hide_sb_delayed())
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        self._y = 24
        self._bubbles: List[int] = []
        self._on_height_change = on_height_change

    # ----- public
    def clear(self):
        self.canvas.delete("all")
        self._y = 24
        self._bubbles.clear()
        self._update_scroll()

    def add_date_divider(self, label: str):
        x = self.winfo_width() / 2 if self.winfo_width() > 0 else 360
        chip_w = max(60, 12 + 8 * len(label))
        chip_h = 22
        self.canvas.create_rectangle(
            x - chip_w / 2, self._y, x + chip_w / 2, self._y + chip_h,
            fill=Theme.BG_MAIN, outline=Theme.BORDER, width=1)
        self.canvas.create_text(
            x, self._y + chip_h / 2, text=label,
            fill=Theme.TEXT_TERTIARY,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_DAY))
        self._y += chip_h + 24

    def add_message(self, msg: Message, contact: Contact,
                    my_avatar_color: str = "#0084FF",
                    contact_avatar_color: Optional[str] = None):
        is_me = msg.sender == "me"
        right_side = is_me
        width = self.canvas.winfo_width() or 700
        pad = 24
        max_bubble_w = int(width * 0.62)

        # wrap text
        text = msg.text
        body_font = tkfont.Font(family=Theme.FONT_FAMILY,
                                size=Theme.FONT_SIZE_BODY)
        lines = self._wrap(text, body_font, max_bubble_w - 28)
        line_h = body_font.metrics("linespace")
        text_h = line_h * len(lines)
        bubble_h = max(36, text_h + 22)
        bubble_w = min(max_bubble_w,
                       max(48, max(body_font.measure(l) for l in lines) + 28))

        if right_side:
            bx = width - pad - bubble_w
            by = self._y
        else:
            bx = pad
            by = self._y

        # avatar (left side for received only)
        avatar_size = 32
        if not right_side:
            avx = bx
            avy = by + bubble_h - avatar_size
            self._draw_avatar(avx + avatar_size / 2,
                              avy + avatar_size / 2,
                              avatar_size,
                              contact_avatar_color or contact.avatar_color,
                              contact.avatar_initials)
            text_x = bx + avatar_size + 8
            text_w = bubble_w
        else:
            text_x = bx
            text_w = bubble_w

        # bubble
        r = 14
        color = Theme.BG_BUBBLE_SENT if is_me else Theme.BG_BUBBLE_RECV
        text_color = Theme.TEXT_BUBBLE_SENT if is_me else Theme.TEXT_BUBBLE_RECV
        self._round_rect(text_x, by, text_x + text_w, by + bubble_h, r, color)

        # small tail for sent
        if right_side:
            self._tail(text_x + text_w, by + bubble_h - 18, 6, 10, color)

        # text
        for i, line in enumerate(lines):
            ty = by + (bubble_h - text_h) / 2 + i * line_h
            self.canvas.create_text(
                text_x + 14, ty, text=line, anchor="nw",
                fill=text_color, font=body_font)

        # meta (time + status)
        meta_font = (Theme.FONT_FAMILY, Theme.FONT_SIZE_META)
        meta = msg.timestamp + ("" if is_me
                                else "" if not msg.status
                                else "")
        if is_me:
            self.canvas.create_text(
                text_x + text_w - 6, by + bubble_h + 4, anchor="ne",
                text=msg.timestamp, fill=Theme.TEXT_TERTIARY,
                font=meta_font)
        else:
            self.canvas.create_text(
                text_x, by + bubble_h + 4, anchor="nw",
                text=msg.timestamp, fill=Theme.TEXT_TERTIARY,
                font=meta_font)

        self._y = by + bubble_h + 28
        self._update_scroll()
        # animate in
        self._animate_in(by)

    def scroll_to_bottom(self):
        self.canvas.update_idletasks()
        self.canvas.yview_moveto(1.0)

    # ----- helpers
    @staticmethod
    def _wrap(text: str, font: tkfont.Font, max_w: int) -> List[str]:
        out: List[str] = []
        for para in text.split("\n"):
            if not para:
                out.append("")
                continue
            line = ""
            for ch in para:
                if font.measure(line + ch) <= max_w:
                    line += ch
                else:
                    out.append(line)
                    line = ch
            out.append(line)
        return out

    def _round_rect(self, x1, y1, x2, y2, r, fill):
        pts = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        self.canvas.create_polygon(pts, smooth=True, fill=fill, outline="")

    def _tail(self, x, y, w, h, fill):
        self.canvas.create_polygon(
            [x, y - h / 2, x + w, y, x, y + h / 2],
            smooth=True, fill=fill, outline="")

    def _draw_avatar(self, cx, cy, size, color, initials):
        s = size
        self.canvas.create_oval(
            cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2,
            fill=color, outline=Theme.BORDER, width=1)
        if initials:
            font = tkfont.Font(family=Theme.FONT_FAMILY,
                               size=max(8, s // 2 - 4), weight="bold")
            self.canvas.create_text(cx, cy, text=initials,
                                    fill="#FFFFFF", font=font)

    def _update_scroll(self):
        self.canvas.configure(scrollregion=(0, 0, 0, self._y + 60))
        if self._on_height_change:
            self._on_height_change(self._y)

    def _animate_in(self, target_y: int):
        # Simple fade-in: re-create with lower opacity by overlaying
        # Not used for now; messages appear instantly for performance.
        pass

    # ----- scrollbar
    def _show_sb(self):
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _hide_sb_delayed(self):
        self.after(180, self._hide_sb_if_leave)

    def _hide_sb_if_leave(self):
        x, y = self.canvas.winfo_pointerxy()
        rx, ry = self.canvas.winfo_rootx(), self.canvas.winfo_rooty()
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if not (rx <= x <= rx + w and ry <= y <= ry + h):
            self.scrollbar.pack_forget()

    def _on_scroll(self, *args):
        self.scrollbar.set(*args)
        self._show_sb()
        self._hide_sb_delayed()

    def _on_wheel(self, e):
        delta = -1 if e.delta > 0 else 1
        self.canvas.yview_scroll(delta, "units")


# ---------------------------------------------------------------------------
# Input area
# ---------------------------------------------------------------------------
class InputBar(tk.Frame):
    """Bottom composer: action buttons, text field, send button."""

    def __init__(self, master, on_send: Callable[[str], None]):
        super().__init__(master, bg=Theme.BG_MAIN,
                         height=Theme.INPUT_HEIGHT)
        self.pack_propagate(False)
        self.on_send = on_send
        self._build()

    def _build(self):
        # top hairline
        tk.Frame(self, bg=Theme.BORDER, height=1).pack(side=tk.TOP, fill=tk.X)

        wrap = tk.Frame(self, bg=Theme.BG_MAIN)
        wrap.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)

        # field
        field = tk.Frame(wrap, bg=Theme.BG_INPUT, highlightthickness=0)
        field.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        field.pack_propagate(False)

        # emoji icon inside the field
        emoji = tk.Label(field, text="😊", bg=Theme.BG_INPUT,
                         fg=Theme.TEXT_SECONDARY, cursor="hand2",
                         font=(Theme.FONT_FAMILY, 16))
        emoji.pack(side=tk.LEFT, padx=(10, 4), pady=10)
        emoji.bind("<Button-1>", lambda _: self._insert_emoji("😊"))

        self.text = tk.Text(
            field, bg=Theme.BG_INPUT, fg=Theme.TEXT_PRIMARY,
            insertbackground=Theme.TEXT_PRIMARY,
            relief=tk.FLAT, bd=0, highlightthickness=0,
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_BODY),
            wrap=tk.WORD, height=2, padx=4, pady=10)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text.bind("<Return>", self._on_enter)
        self.text.bind("<Shift-Return>", lambda _: None)
        self.text.bind("<Control-KeyPress-Return>", lambda _: None)

        # action row inside field (right)
        actions = tk.Frame(field, bg=Theme.BG_INPUT)
        actions.pack(side=tk.RIGHT, padx=6)
        for icon, tip in [("📎", "文件"), ("🖼", "图片")]:
            b = tk.Label(actions, text=icon, bg=Theme.BG_INPUT,
                         fg=Theme.TEXT_SECONDARY, cursor="hand2",
                         font=(Theme.FONT_FAMILY, 14))
            b.pack(side=tk.LEFT, padx=2)
            b.bind("<Enter>", lambda _, x=b: x.config(fg=Theme.PRIMARY))
            b.bind("<Leave>", lambda _, x=b: x.config(fg=Theme.TEXT_SECONDARY))

        # send button
        self.send_btn = FlatButton(
            wrap, text="发送", command=self._send,
            bg=Theme.PRIMARY, hover_bg=Theme.PRIMARY_HOVER,
            active_bg=Theme.PRIMARY_HOVER, fg="#FFFFFF",
            font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_BODY, "bold"),
            padx=18, pady=10, radius=10)
        self.send_btn.pack(side=tk.RIGHT)

    # ----- send
    def _on_enter(self, event):
        if event.state & 0x0001:  # shift held
            return None
        self._send()
        return "break"

    def _send(self):
        text = self.text.get("1.0", tk.END).strip()
        if not text:
            return
        self.text.delete("1.0", tk.END)
        self.on_send(text)
        # visual feedback
        self._pulse_send()

    def _insert_emoji(self, e: str):
        self.text.insert(tk.END, e)
        self.text.focus_set()

    def _pulse_send(self):
        original = self.send_btn.cget("bg")
        self.send_btn.config(bg=Theme.PRIMARY_HOVER)
        self.after(120, lambda: self.send_btn.config(bg=original))


# ---------------------------------------------------------------------------
# Empty state (when no chat is selected)
# ---------------------------------------------------------------------------
class EmptyState(tk.Frame):
    def __init__(self, master):
        super().__init__(master, bg=Theme.BG_MAIN)
        center = tk.Frame(self, bg=Theme.BG_MAIN)
        center.place(relx=0.5, rely=0.5, anchor="center")

        glyph = tk.Label(center, text="💬",
                         bg=Theme.BG_MAIN, fg=Theme.TEXT_TERTIARY,
                         font=(Theme.FONT_FAMILY, 64))
        glyph.pack(pady=(0, 12))

        tk.Label(center, text="选择一个对话开始聊天",
                 bg=Theme.BG_MAIN, fg=Theme.TEXT_PRIMARY,
                 font=(Theme.FONT_FAMILY, 16, "bold")).pack()
        tk.Label(center, text="所有消息都将在此显示",
                 bg=Theme.BG_MAIN, fg=Theme.TEXT_TERTIARY,
                 font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_PREVIEW)
                 ).pack(pady=(4, 0))


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------
class ChatApp:
    """Top-level chat application. Drop into any Tk root window."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self._configure_root()
        self.contacts: List[Contact] = []
        self._current: Optional[Contact] = None
        self._header: Optional[ChatHeader] = None
        self._messages: Optional[MessageArea] = None
        self._input: Optional[InputBar] = None
        self._body_stack: Optional[tk.Frame] = None
        self._build_layout()
        self._seed_sample_data()

    # ----- root config
    def _configure_root(self):
        self.root.title("Chat Room")
        self.root.geometry("1080x680")
        self.root.minsize(900, 560)
        self.root.configure(bg=Theme.BG_APP)

    # ----- layout
    def _build_layout(self):
        # main split: sidebar | body
        self.sidebar = Sidebar(self.root, on_select=self._open_conversation)
        self.sidebar.place(x=0, y=0, relheight=1.0)

        # vertical hairline
        tk.Frame(self.root, bg=Theme.BORDER, width=1).place(
            x=Theme.SIDEBAR_WIDTH, y=0, relheight=1.0)

        # body
        self.body = tk.Frame(self.root, bg=Theme.BG_MAIN)
        self.body.place(x=Theme.SIDEBAR_WIDTH + 1, y=0,
                        relwidth=1.0, width=-(Theme.SIDEBAR_WIDTH + 1),
                        relheight=1.0)

        # empty state shown initially
        self._show_empty_state()

    def _show_empty_state(self):
        for w in self.body.winfo_children():
            w.destroy()
        EmptyState(self.body).pack(fill=tk.BOTH, expand=True)

    def _open_conversation(self, contact: Contact):
        for w in self.body.winfo_children():
            w.destroy()
        self._current = contact
        self._build_conversation(contact)

    def _build_conversation(self, contact: Contact):
        # header
        self._header = ChatHeader(
            self.body, contact,
            on_call=lambda: self._toast("语音通话"),
            on_video=lambda: self._toast("视频通话"),
            on_search=lambda: self._toast("搜索消息"),
            on_more=lambda: self._toast("更多选项"),
        )
        self._header.pack(side=tk.TOP, fill=tk.X)

        # messages
        self._messages = MessageArea(self.body)
        self._messages.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # input
        self._input = InputBar(self.body, on_send=lambda t: self._send(t))
        self._input.pack(side=tk.BOTTOM, fill=tk.X)

        # seed messages for the selected contact
        self._seed_messages(contact)
        self._messages.scroll_to_bottom()

    # ----- send / receive
    def _send(self, text: str):
        if not self._current or not self._messages:
            return
        ts = time.strftime("%H:%M")
        self._messages.add_message(
            Message(text=text, sender="me", timestamp=ts),
            contact=self._current)
        # simulate a reply after a moment
        self.root.after(900, lambda: self._auto_reply(text))

    def _auto_reply(self, prompt: str):
        if not self._current or not self._messages:
            return
        reply = self._compose_reply(prompt)
        ts = time.strftime("%H:%M")
        self._messages.add_message(
            Message(text=reply, sender=self._current.name, timestamp=ts),
            contact=self._current)
        self._messages.scroll_to_bottom()

    def _compose_reply(self, prompt: str) -> str:
        # tiny heuristic mock so the demo feels alive
        p = prompt.lower()
        if "?" in prompt or "吗" in prompt or "?" in p:
            return "好问题，我想想再说~"
        if any(k in prompt for k in ("你好", "hello", "hi", "嗨")):
            return "你好呀！今天有什么想聊的？"
        if any(k in prompt for k in ("再见", "bye", "拜拜")):
            return "回头见 👋"
        if any(k in prompt for k in ("谢", "thanks", "thank")):
            return "不客气 :)"
        return random.choice([
            "收到啦。",
            "有意思，继续说说？",
            "嗯嗯，了解。",
            "稍等我一下，我看看。",
            "好哒。",
        ])

    # ----- toast
    def _toast(self, text: str):
        toast = tk.Label(self.root, text=text, bg="#1F2329",
                         fg="#FFFFFF",
                         font=(Theme.FONT_FAMILY, Theme.FONT_SIZE_PREVIEW),
                         padx=14, pady=8)
        toast.place(relx=0.5, rely=0.92, anchor="center")
        Anim.fade(self.root, 1.0, 0.0, Theme.ANIM_SLOW * 2,
                  on_done=toast.destroy, steps=10)
        toast.after(1200, lambda: Anim.fade(
            self.root, 1.0, 0.0, Theme.ANIM_SLOW,
            on_done=toast.destroy, steps=8))

    # ----- sample data
    def _seed_sample_data(self):
        palette = ["#0084FF", "#07C160", "#FF7A45", "#9254DE",
                   "#F5222D", "#FAAD14", "#13C2C2", "#2F54EB"]
        names = [
            ("Alex Chen", "在线"),
            ("设计组", "群组 · 8 位成员"),
            ("Mira Liu", "在线"),
            ("产品周会", "群组 · 12 位成员"),
            ("Jordan", "30 分钟前"),
            ("Kai", "在线"),
            ("Emma Wang", "昨天"),
            ("开发组", "群组 · 23 位成员"),
            ("Sophia", "在线"),
        ]
        previews = [
            "刚把原型整理好了，发你看看？",
            "明天的评审需要这两个截图",
            "你说的那个动画我也想试一下",
            "会议改成下午三点了",
            "代码我提 PR 了，麻烦看一眼",
            "我刚更新了设计稿",
            "周末一起去看展吗？",
            "新版的图标已经上传",
            "好的，那就这版定稿 👍",
        ]
        times = ["刚刚", "12:42", "11:08", "昨天", "周三", "周二", "周一", "周日", "周六"]
        unreads = [2, 0, 1, 5, 0, 3, 0, 1, 0]

        contacts: List[Contact] = []
        for i, (name, subtitle) in enumerate(names):
            color = palette[i % len(palette)]
            initials = "".join(p[0] for p in name.replace("组", "").split()
                               if p.strip())[:2].upper() or name[0].upper()
            is_group = "组" in name or "周会" in name
            members = 8 + i * 3 if is_group else 0
            contacts.append(Contact(
                name=name,
                subtitle=subtitle,
                avatar_color=color,
                avatar_initials=initials,
                online=(subtitle == "在线"),
                unread=unreads[i],
                preview=previews[i],
                timestamp=times[i],
                pinned=(i == 0),
                is_group=is_group,
                members=members,
            ))
        self.contacts = contacts
        self.sidebar.set_contacts(contacts)

    def _seed_messages(self, contact: Contact):
        # build a believable conversation per contact
        seed_map = {
            "Alex Chen": [
                ("Alex Chen", "在吗？有个东西想让你看看", "10:21"),
                ("me", "在的，什么？", "10:22"),
                ("Alex Chen", "刚把原型整理好了，发你看看？", "10:23"),
                ("me", "好的，我看看 👀", "10:24"),
                ("Alex Chen", "https://figma.com/file/xxxxxx\n重点在第二屏的过渡", "10:25"),
                ("me", "明白了，那个渐变可以再柔和一点", "10:31"),
            ],
            "设计组": [
                ("设计组", "各位，今天的设计评审改到下午 4 点", "09:10"),
                ("me", "收到", "09:11"),
                ("设计组", "@我 这是新的设计规范文档", "09:12"),
                ("设计组", "麻烦大家今天内 review 完", "09:15"),
            ],
            "Mira Liu": [
                ("Mira Liu", "今天一起去吃饭吗？", "12:01"),
                ("me", "可以，几点？", "12:02"),
                ("Mira Liu", "12:30 楼下见", "12:02"),
            ],
            "产品周会": [
                ("产品周会", "本周的关键指标整理好了", "周一 10:00"),
                ("me", "看起来转化率有提升", "周一 10:24"),
                ("产品周会", "对，主要来自新版的登录流程", "周一 10:25"),
            ],
            "Jordan": [
                ("Jordan", "上次说的那个动画我试了一下", "周三 16:42"),
                ("Jordan", "效果不错，但有点卡", "周三 16:42"),
                ("me", "可能是合成层的问题，试试 transform", "周三 17:10"),
            ],
            "Kai": [
                ("Kai", "代码我提 PR 了，麻烦看一眼", "12:42"),
                ("me", "好的", "12:50"),
            ],
            "Emma Wang": [
                ("Emma Wang", "周末一起去看展吗？", "昨天 18:20"),
                ("me", "好啊，看哪个？", "昨天 18:35"),
            ],
            "开发组": [
                ("开发组", "v2.3.1 发布完成", "周日 22:00"),
                ("开发组", "已知问题：登录页偶发 500", "周日 22:01"),
                ("me", "我看看", "周日 22:14"),
            ],
            "Sophia": [
                ("Sophia", "好的，那就这版定稿 👍", "周六 11:08"),
            ],
        }

        msgs = seed_map.get(contact.name, [])
        if not msgs:
            return

        self._messages.add_date_divider("今天")
        prev_day = None
        for sender, text, ts in msgs:
            self._messages.add_message(
                Message(text=text, sender=sender, timestamp=ts),
                contact=contact)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    # cross-platform DPI nicety (best effort)
    try:
        if root.tk.call("tk", "scaling") < 1.2:
            root.tk.call("tk", "scaling", 1.2)
    except Exception:
        pass
    ChatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
