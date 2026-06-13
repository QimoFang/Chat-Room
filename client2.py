import tkinter as tk
import tkinter.ttk
import tkinter.messagebox
import tkinter.filedialog
import tkinter.font as tkfont
import socket
import ssl
import threading
import time
import json
import os
import pickle
import base64
import io
import sys
import unicodedata
from collections import deque
from PIL import Image, ImageDraw, ImageGrab, ImageTk

# TinUI 导入
from tinui.TinUI import BasicTinUI, TinUI, TinUIXml, TinUIString, FuncList, TinUINum


class DialogueInterface:
    def __init__(self, canvas: tk.Canvas, scrollbar: tk.Scrollbar):
        self.canvas = canvas
        self.scrollbar = scrollbar
        self.y = 20
        self.avatar_cache = {}  # {uid: PhotoImage} 消息头像缓存
        self._username_items = {}  # {uid: [canvas_text_id, ...]} 用户名文字项
        self.AVATAR_SIZE = 40
        self.message_history = []  # 消息历史用于窗口缩放时重绘
        self._resize_after_id = None
        self._last_canvas_w = None  # 初始为 None，首次 Configure 跳过实时位移
        self.canvas.bind('<Configure>', self._on_canvas_resize)
        self.canvas.config(scrollregion=(0, 0, 0, self.canvas.winfo_height()))
        self.canvas.config(yscrollcommand=self.scrollbar.set)

    def _on_canvas_resize(self, event):
        """画布尺寸变化时，实时位移右侧消息 + 防抖全量重绘"""
        new_w = self.canvas.winfo_width()
        if self._last_canvas_w is not None:
            delta = new_w - self._last_canvas_w
            if delta != 0:
                # 实时移动所有右侧消息的 canvas 元素
                for msg in self.message_history:
                    if msg['direction'] == 'right':
                        msg_items = msg.get('items')
                        if msg_items:
                            for item_id in msg_items:
                                self.canvas.move(item_id, delta, 0)
        self._last_canvas_w = new_w

        # 防抖全量重绘（松手后 200ms 执行）
        if self._resize_after_id:
            self.canvas.after_cancel(self._resize_after_id)
        self._resize_after_id = self.canvas.after(200, self.redraw_messages)

    def redraw_messages(self):
        """根据当前画布宽度重绘所有消息气泡"""
        if not self.message_history:
            return
        # 保存滚动位置
        old_yview = self.canvas.yview()
        was_at_bottom = (old_yview[1] >= 0.99)

        self.canvas.delete("all")
        self.y = 20
        self._username_items.clear()
        canvas_w = self.canvas.winfo_width() or 400

        for msg in self.message_history:
            if msg['direction'] == 'left':
                x = 20
            else:
                # 右边距20 + 头像40 + 间距20 = 80(有头像) 或 右边距20(无头像)
                right_margin = 20 + (self.AVATAR_SIZE + 20 if msg.get('has_avatar_on_right') else 0)
                x = canvas_w - right_margin - msg['width']
            self._draw_stored(x, msg)

        self.canvas.config(scrollregion=(0, 0, 0, self.y))
        # 恢复滚动位置
        if was_at_bottom:
            self.canvas.yview_moveto(1.0)
        else:
            self.canvas.yview_moveto(old_yview[0])

        # 更新画布宽度记录，使后续 resize 实时位移基于正确基线
        self._last_canvas_w = canvas_w

        # 全量重绘后更新每条消息的 items 指向（_draw_stored 已创建新元素）

    def _draw_stored(self, x, msg):
        """根据存储的消息数据重绘一条消息（draw_msg 的精简版）"""
        if msg['color'] == "#95EC69":
            bg_color = Theme.MSG_SENT
            shadow_color = "#7BC85C"
        else:
            bg_color = Theme.MSG_RECEIVED
            shadow_color = Theme.MSG_SHADOW

        point = msg['direction']
        width = msg['width']
        height = msg['height']
        radius = msg['radius']
        txt = msg['lines']
        avatar_img = msg.get('avatar_img')
        username = msg.get('username', '')
        sender_uid = msg.get('sender_uid', 0)
        has_username = bool(username) and point == "left"

        new_items = []

        # 用户名
        if has_username:
            tid = self.canvas.create_text(x + 12, self.y, text=username, anchor=tk.NW,
                                          fill=Theme.TEXT_SECONDARY, font=('微软雅黑', 9))
            if sender_uid:
                self._username_items.setdefault(sender_uid, []).append(tid)
            self.y += 16

        # 头像
        avatar_offset = 0
        avatar_size = self.AVATAR_SIZE
        if avatar_img is not None:
            avatar_y = self.y
            if point == "left":
                img_id = self.canvas.create_image(x + avatar_size // 2, avatar_y + avatar_size // 2,
                                                  image=avatar_img, anchor='center')
                new_items.append(img_id)
                avatar_offset = avatar_size + 20
            else:
                avatar_x_right = x + width + 20
                img_id = self.canvas.create_image(avatar_x_right + avatar_size // 2,
                                                  avatar_y + avatar_size // 2,
                                                  image=avatar_img, anchor='center')
                new_items.append(img_id)

        # 阴影
        shadow_offset = 2
        if point == "right":
            shadow_pos = [x + radius, self.y + shadow_offset,
                         x + width - radius, self.y + shadow_offset,
                         x + width, self.y + shadow_offset,
                         x + width, self.y + radius + shadow_offset,
                         x + width + 4, self.y + radius + 2 + shadow_offset,
                         x + width + 8, self.y + radius + 5 + shadow_offset,
                         x + width + 4, self.y + radius + 8 + shadow_offset,
                         x + width, self.y + radius + 10 + shadow_offset,
                         x + width, self.y + height - radius + shadow_offset,
                         x + width, self.y + height + shadow_offset,
                         x + width - radius, self.y + height + shadow_offset,
                         x + radius, self.y + height + shadow_offset,
                         x, self.y + height + shadow_offset,
                         x, self.y + height - radius + shadow_offset,
                         x, self.y + radius + shadow_offset,
                         x, self.y + shadow_offset]
        else:
            shadow_pos = [x + radius + avatar_offset, self.y + shadow_offset,
                         x + width - radius + avatar_offset, self.y + shadow_offset,
                         x + width + avatar_offset, self.y + shadow_offset,
                         x + width + avatar_offset, self.y + radius + shadow_offset,
                         x + width + avatar_offset, self.y + height - radius + shadow_offset,
                         x + width + avatar_offset, self.y + height + shadow_offset,
                         x + width - radius + avatar_offset, self.y + height + shadow_offset,
                         x + radius + avatar_offset, self.y + height + shadow_offset,
                         x + avatar_offset, self.y + height + shadow_offset,
                         x + avatar_offset, self.y + height - radius + shadow_offset,
                         x + avatar_offset, self.y + radius + 10 + shadow_offset,
                         x + avatar_offset - 4, self.y + radius + 8 + shadow_offset,
                         x + avatar_offset - 8, self.y + radius + 5 + shadow_offset,
                         x + avatar_offset - 4, self.y + radius + 2 + shadow_offset,
                         x + avatar_offset, self.y + radius + shadow_offset,
                         x + avatar_offset, self.y + shadow_offset]

        shadow = self.canvas.create_polygon(shadow_pos, fill=shadow_color, smooth=True, outline="")
        new_items.append(shadow)

        # 气泡主体
        if point == "right":
            pos = [x + radius, self.y,
                   x + width - radius, self.y,
                   x + width, self.y,
                   x + width, self.y + radius,
                   x + width+4, self.y + radius+2,
                   x + width + 8, self.y + radius+5,
                   x + width+4, self.y + radius+8,
                   x + width, self.y + radius+10,
                   x + width, self.y + height - radius,
                   x + width, self.y + height,
                   x + width - radius, self.y + height,
                   x + radius, self.y + height,
                   x, self.y + height,
                   x, self.y + height - radius,
                   x, self.y + radius,
                   x, self.y]
        else:
            pos = [x + radius + avatar_offset, self.y,
                   x + width - radius + avatar_offset, self.y,
                   x + width + avatar_offset, self.y,
                   x + width + avatar_offset, self.y + radius,
                   x + width + avatar_offset, self.y + height - radius,
                   x + width + avatar_offset, self.y + height,
                   x + width - radius + avatar_offset, self.y + height,
                   x + radius + avatar_offset, self.y + height,
                   x + avatar_offset, self.y + height,
                   x + avatar_offset, self.y + height - radius,
                   x + avatar_offset, self.y + radius + 10,
                   x + avatar_offset - 4, self.y + radius + 8,
                   x + avatar_offset - 8, self.y + radius + 5,
                   x + avatar_offset - 4, self.y + radius + 2,
                   x + avatar_offset, self.y + radius,
                   x + avatar_offset, self.y]

        polygon = self.canvas.create_polygon(pos, fill=bg_color, smooth=True, outline="")
        new_items.append(polygon)

        # 文本
        text_color = Theme.TEXT_PRIMARY if point == "left" else "#000000"
        font = msg.get('font', ('微软雅黑', 11))
        base_x = x + avatar_offset if point == "left" else x

        if len(txt) == 1:
            text_item = self.canvas.create_text(base_x + 12, self.y + 10, text=txt[0], anchor=tk.NW,
                                                fill=text_color, font=font)
            new_items.append(text_item)
        else:
            line_height = 18
            for num in range(len(txt)):
                text_item = self.canvas.create_text(base_x + 12, self.y + 10 + num * line_height,
                                                    text=txt[num], anchor=tk.NW,
                                                    fill=text_color, font=font)
                new_items.append(text_item)

        self.y += height + 25

        # 更新该消息的 canvas item IDs，供后续 resize 实时位移用
        msg['items'] = new_items

    def _make_circular(self, pil_img):
        """将 PIL Image 裁剪为圆形（返回 RGBA 格式），高倍数采样实现抗锯齿"""
        size = self.AVATAR_SIZE
        pil_img = pil_img.resize((size, size), Image.LANCZOS).convert('RGBA')

        # 高倍数采样：在 4x 分辨率下绘制遮罩后缩小，实现边缘抗锯齿
        scale = 4
        mask_size = size * scale
        mask = Image.new('L', (mask_size, mask_size), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((2, 2, mask_size - 2, mask_size - 2), fill=255)
        mask = mask.resize((size, size), Image.LANCZOS)

        pil_img.putalpha(mask)
        return pil_img

    def set_message_avatar(self, uid, icon_b64):
        """设置消息区域头像（base64 头像数据）"""
        if not icon_b64 or uid in self.avatar_cache:
            print(f"[DIAG] set_message_avatar SKIP: uid={uid}, icon_b64非空={bool(icon_b64)}, 已在缓存={uid in self.avatar_cache}")
            return
        try:
            img_bytes = base64.b64decode(icon_b64)
            pil_img = Image.open(io.BytesIO(img_bytes))
            pil_img = self._make_circular(pil_img)
            self.avatar_cache[uid] = ImageTk.PhotoImage(pil_img)
            print(f"[DIAG] set_message_avatar OK: uid={uid}, 大小={len(img_bytes)} bytes")
        except Exception as e:
            print(f"[DIAG] set_message_avatar FAIL: uid={uid}, 错误={e}")
            self.avatar_cache[uid] = None

    def set_message_avatar_pil(self, uid, pil_img):
        """直接设置消息区域头像（PIL Image -> 缓存到 PhotoImage）"""
        if not pil_img or uid in self.avatar_cache:
            return
        try:
            pil_img = self._make_circular(pil_img)
            self.avatar_cache[uid] = ImageTk.PhotoImage(pil_img)
        except Exception:
            self.avatar_cache[uid] = None

    def update_username_text(self, uid, new_name):
        """更新指定 uid 的用户名文字（改名后刷新历史消息的用户名）"""
        if uid in self._username_items:
            for tid in self._username_items[uid]:
                try:
                    self.canvas.itemconfig(tid, text=new_name)
                except tk.TclError:
                    pass

    def draw_msg(self, x, width, height, color, txt, point="right", radius=18, avatar_img=None, **kwargs):
        """绘制现代化消息气泡 - 支持头像和用户名"""

        if color == "#95EC69":
            bg_color = Theme.MSG_SENT
            shadow_color = "#7BC85C"
        else:
            bg_color = Theme.MSG_RECEIVED
            shadow_color = Theme.MSG_SHADOW

        username = kwargs.get('username', '')
        sender_uid = kwargs.get('sender_uid', 0)
        has_username = bool(username) and point == "left"

        # 先绘制用户名（如果有点）
        if has_username:
            username_color = Theme.TEXT_SECONDARY
            tid = self.canvas.create_text(
                x + 12, self.y,
                text=username, anchor=tk.NW,
                fill=username_color, font=('微软雅黑', 9))
            if sender_uid:
                self._username_items.setdefault(sender_uid, []).append(tid)
            self.y += 16  # 用户名区域占16px（9pt字体约12px高）

        # 绘制头像（如果提供）
        avatar_offset = 0
        avatar_size = self.AVATAR_SIZE
        if avatar_img is not None:
            avatar_y = self.y
            if point == "left":
                img_id = self.canvas.create_image(x + avatar_size // 2, avatar_y + avatar_size // 2,
                                                  image=avatar_img, anchor='center')
                avatar_offset = avatar_size + 20
            else:  # point == "right"，发送者头像放在消息气泡右侧
                avatar_x_right = x + width + 20
                img_id = self.canvas.create_image(avatar_x_right + avatar_size // 2,
                                                  avatar_y + avatar_size // 2,
                                                  image=avatar_img, anchor='center')
        
        shadow_offset = 2
        if point == "right":
            shadow_pos = [x + radius, self.y + shadow_offset,
                         x + width - radius, self.y + shadow_offset,
                         x + width, self.y + shadow_offset,
                         x + width, self.y + radius + shadow_offset,
                         x + width + 4, self.y + radius + 2 + shadow_offset,
                         x + width + 8, self.y + radius + 5 + shadow_offset,
                         x + width + 4, self.y + radius + 8 + shadow_offset,
                         x + width, self.y + radius + 10 + shadow_offset,
                         x + width, self.y + height - radius + shadow_offset,
                         x + width, self.y + height + shadow_offset,
                         x + width - radius, self.y + height + shadow_offset,
                         x + radius, self.y + height + shadow_offset,
                         x, self.y + height + shadow_offset,
                         x, self.y + height - radius + shadow_offset,
                         x, self.y + radius + shadow_offset,
                         x, self.y + shadow_offset]
        else:
            shadow_pos = [x + radius + avatar_offset, self.y + shadow_offset,
                         x + width - radius + avatar_offset, self.y + shadow_offset,
                         x + width + avatar_offset, self.y + shadow_offset,
                         x + width + avatar_offset, self.y + radius + shadow_offset,
                         x + width + avatar_offset, self.y + height - radius + shadow_offset,
                         x + width + avatar_offset, self.y + height + shadow_offset,
                         x + width - radius + avatar_offset, self.y + height + shadow_offset,
                         x + radius + avatar_offset, self.y + height + shadow_offset,
                         x + avatar_offset, self.y + height + shadow_offset,
                         x + avatar_offset, self.y + height - radius + shadow_offset,
                         x + avatar_offset, self.y + radius + 10 + shadow_offset,
                         x + avatar_offset - 4, self.y + radius + 8 + shadow_offset,
                         x + avatar_offset - 8, self.y + radius + 5 + shadow_offset,
                         x + avatar_offset - 4, self.y + radius + 2 + shadow_offset,
                         x + avatar_offset, self.y + radius + shadow_offset,
                         x + avatar_offset, self.y + shadow_offset]
        
        shadow = self.canvas.create_polygon(shadow_pos, fill=shadow_color, smooth=True, outline="")
        
        if point == "right":
            pos = [x + radius, self.y,
                   x + width - radius, self.y,
                   x + width, self.y,
                   x + width, self.y + radius,
                   x + width+4, self.y + radius+2,
                   x + width + 8, self.y + radius+5,
                   x + width+4, self.y + radius+8,
                   x + width, self.y + radius+10,
                   x + width, self.y + height - radius,
                   x + width, self.y + height,
                   x + width - radius, self.y + height,
                   x + radius, self.y + height,
                   x, self.y + height,
                   x, self.y + height - radius,
                   x, self.y + radius,
                   x, self.y]
        else:
            pos = [x + radius + avatar_offset, self.y,
                   x + width - radius + avatar_offset, self.y,
                   x + width + avatar_offset, self.y,
                   x + width + avatar_offset, self.y + radius,
                   x + width + avatar_offset, self.y + height - radius,
                   x + width + avatar_offset, self.y + height,
                   x + width - radius + avatar_offset, self.y + height,
                   x + radius + avatar_offset, self.y + height,
                   x + avatar_offset, self.y + height,
                   x + avatar_offset, self.y + height - radius,
                   x + avatar_offset, self.y + radius + 10,
                   x + avatar_offset - 4, self.y + radius + 8,
                   x + avatar_offset - 8, self.y + radius + 5,
                   x + avatar_offset - 4, self.y + radius + 2,
                   x + avatar_offset, self.y + radius,
                   x + avatar_offset, self.y]
        
        polygon = self.canvas.create_polygon(pos, fill=bg_color, smooth=True, outline="")

        text_color = Theme.TEXT_PRIMARY if point == "left" else "#000000"
        font = kwargs.get('font', ('微软雅黑', 11))
        text_items = []
        
        base_x = x + avatar_offset if point == "left" else x
        
        if len(txt) == 1:
            text = self.canvas.create_text(base_x + 12, self.y + 10, text=txt[0], anchor=tk.NW, 
                                          fill=text_color, font=font)
            text_items.append(text)
        elif len(txt) > 1:
            line_height = 18
            for num in range(len(txt)):
                text = self.canvas.create_text(base_x + 12, self.y + 10 + num * line_height, 
                                              text=txt[num], anchor=tk.NW, 
                                              fill=text_color, font=font)
                text_items.append(text)
        
        items = [shadow, polygon] + text_items
        if avatar_img is not None:
            items += [img_id]
        AnimationHelper.canvas_slide_up(self.canvas, items, start_offset=25, duration=200)
        
        self.y += height + 25

        # 存储消息历史用于窗口缩放时重绘
        self.message_history.append({
            'direction': point,
            'lines': txt,
            'color': color,
            'width': width,
            'height': height,
            'radius': radius,
            'font': kwargs.get('font', ('微软雅黑', 11)),
            'avatar_img': avatar_img,
            'username': username,
            'sender_uid': sender_uid,
            'has_avatar_on_right': avatar_img is not None and point == 'right',
            'items': items,  # canvas item IDs，用于缩放时实时移动
        })


# ==================== Canvas 用户列表 ====================
class UserListCanvas:
    """Canvas 自绘用户列表，支持真实头像、未读红点、群聊、滚动条焦点显隐"""

    AVATAR_COLORS = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4",
                     "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F",
                     "#BB8FCE", "#85C1E9", "#F8C471", "#82E0AA"]
    ITEM_HEIGHT = 52
    AVATAR_SIZE = 40
    PADDING_X = 10
    TEXT_GAP = 8
    BADGE_AREA = 36
    FONT_FAMILY = '微软雅黑'

    def __init__(self, parent):
        self.parent = parent
        self.canvas = tk.Canvas(parent, bg=Theme.BG_CARD, confine=True,
                                highlightthickness=0, bd=0)
        self.scrollbar = tk.Scrollbar(parent, command=self.canvas.yview,
                                      bg=Theme.BG_CARD, troughcolor=Theme.BG_LIGHT,
                                      width=6, activebackground=Theme.PRIMARY,
                                      highlightbackground=Theme.BORDER)
        self.canvas.config(yscrollcommand=self.scrollbar.set)

        self._name_font = tkfont.Font(family=self.FONT_FAMILY, size=12)
        self._avatar_font = tkfont.Font(family=self.FONT_FAMILY, size=12, weight='bold')
        self._badge_font = tkfont.Font(family=self.FONT_FAMILY, size=10, weight='bold')
        self._small_font = tkfont.Font(family=self.FONT_FAMILY, size=9)

        # 头像缓存 {uid: PhotoImage}
        self._avatar_cache = {}

        self.items = []       # [{name, addr, unread, y, type, members, display_name}]
        self._selected = -1
        self._hovered = -1
        self._on_select_callback = None
        self._last_width = 0
        self._scrollbar_shown = False  # 滚动条显示状态
        self._tooltip_window = None  # ToolTip 窗口
        self._truncated = {}  # {index: full_name} 被截断的项

        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.canvas.bind("<Configure>", self._on_configure)
        # 焦点时显示滚动条
        self.canvas.bind("<Enter>", self._on_focus_in)
        self.canvas.bind("<Leave>", self._on_focus_out, add='+')

    def place(self, **kwargs):
        """放置 Canvas 和 Scrollbar"""
        self.canvas.place(**kwargs)
        # 缓存滚动条放置参数
        self._sb_kwargs = {'y': kwargs.get('y', 0), 'width': 6, 'relx': 1.0, 'x': -6}
        if 'relheight' in kwargs:
            self._sb_kwargs['relheight'] = kwargs['relheight']
        if 'height' in kwargs:
            self._sb_kwargs['height'] = kwargs['height']
        # 初始隐藏滚动条（只放置不显示）
        self.scrollbar.place(self._sb_kwargs)
        self.scrollbar.place_forget()

    def _show_scrollbar(self):
        if not self._scrollbar_shown:
            self.scrollbar.place(self._sb_kwargs)
            self._scrollbar_shown = True

    def _hide_scrollbar(self):
        if self._scrollbar_shown:
            self.scrollbar.place_forget()
            self._scrollbar_shown = False

    def _on_focus_in(self, event):
        self._show_scrollbar()

    def _on_focus_out(self, event):
        # 延迟隐藏，避免在滚动条上时闪烁
        x, y = self.canvas.winfo_pointerxy()
        sb_info = self.scrollbar.place_info()
        if sb_info:
            # 鼠标在canvas或滚动条上都不隐藏
            self.canvas.after(150, self._check_hide_scrollbar)

    def _check_hide_scrollbar(self):
        x, y = self.canvas.winfo_pointerxy()
        c_x = self.canvas.winfo_rootx()
        c_y = self.canvas.winfo_rooty()
        c_w = self.canvas.winfo_width()
        c_h = self.canvas.winfo_height()
        in_canvas = c_x <= x <= c_x + c_w and c_y <= y <= c_y + c_h
        if not in_canvas:
            self._hide_scrollbar()

    def bind_select(self, callback):
        self._on_select_callback = callback

    def get_selection(self):
        return self._selected

    def select(self, index):
        self._selected = index
        self._redraw_all()

    def get_selected_item(self):
        """返回当前选中项的数据"""
        if 0 <= self._selected < len(self.items):
            return self.items[self._selected]
        return None

    def load_avatar(self, uid, icon_b64):
        """加载用户头像: 解码 base64, 裁剪为圆形, 并缓存为 PhotoImage"""
        if not icon_b64 or uid in self._avatar_cache:
            print(f"[DIAG] load_avatar SKIP: uid={uid}, icon_b64非空={bool(icon_b64)}, 已在缓存={uid in self._avatar_cache}")
            return
        try:
            img_bytes = base64.b64decode(icon_b64)
            pil_img = Image.open(io.BytesIO(img_bytes))
            size = self.AVATAR_SIZE
            pil_img = pil_img.resize((size, size), Image.LANCZOS).convert('RGBA')

            # 高倍数采样抗锯齿圆形遮罩
            scale = 4
            mask_size = size * scale
            mask = Image.new('L', (mask_size, mask_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((2, 2, mask_size - 2, mask_size - 2), fill=255)
            mask = mask.resize((size, size), Image.LANCZOS)
            pil_img.putalpha(mask)

            self._avatar_cache[uid] = ImageTk.PhotoImage(pil_img)
            print(f"[DIAG] load_avatar OK: uid={uid}, 大小={len(img_bytes)} bytes")
        except Exception as e:
            print(f"[DIAG] load_avatar FAIL: uid={uid}, 错误={e}")
            self._avatar_cache[uid] = None  # 标记为加载失败

    def rebuild(self, user_list):
        """兼容旧接口: user_list = [(name, addr), ...]"""
        old_unread = {}
        for item in self.items:
            if item.get('addr'):
                old_unread[item['addr']] = item['unread']
        self.items.clear()
        for i, entry in enumerate(user_list):
            name = entry[0] if isinstance(entry, (list, tuple)) else entry
            addr = entry[1] if isinstance(entry, (list, tuple)) and len(entry) > 1 else None
            unread = old_unread.get(addr, 0)
            self.items.append({
                'name': str(name), 'addr': addr, 'unread': unread,
                'y': i * self.ITEM_HEIGHT, 'type': 'user',
                'members': None, 'display_name': str(name).replace("🤖 ", ""),
            })
        if self._selected >= len(self.items):
            self._selected = -1
        self._redraw_all()

    def rebuild_with_groups(self, user_list, groups):
        """根据在线用户和群组列表重建
        user_list: [(name, addr), ...] or [(name, addr, uid), ...]
        groups: [{'name': str, 'addr': str, 'members': [(name, addr), ...]}, ...]
        """
        old_unread = {}
        for item in self.items:
            if item.get('addr'):
                old_unread[item['addr']] = item['unread']
        self.items.clear()
        # 用户列表（含 robot）
        for i, entry in enumerate(user_list):
            name = entry[0] if isinstance(entry, (list, tuple)) else entry
            addr = entry[1] if isinstance(entry, (list, tuple)) and len(entry) > 1 else None
            uid = entry[2] if isinstance(entry, (list, tuple)) and len(entry) > 2 else None
            unread = old_unread.get(addr, 0)
            self.items.append({
                'name': str(name), 'addr': addr, 'uid': uid, 'unread': unread,
                'y': i * self.ITEM_HEIGHT, 'type': 'user',
                'members': None, 'display_name': str(name).replace("🤖 ", ""),
            })
        # 群组列表
        offset = len(self.items)
        for i, grp in enumerate(groups):
            grp_addr = grp.get('addr', f'#group_{i}')
            unread = old_unread.get(grp_addr, 0)
            display = grp.get('name', f'群组{i + 1}')
            self.items.append({
                'name': display, 'addr': grp_addr, 'unread': unread,
                'y': (offset + i) * self.ITEM_HEIGHT, 'type': 'group',
                'members': grp.get('members', []), 'display_name': display,
            })
        if self._selected >= len(self.items):
            self._selected = -1
        self._redraw_all()

    def get_user_index_by_addr(self, addr):
        """根据地址查找用户项的索引"""
        for i, item in enumerate(self.items):
            if item.get('addr') == addr:
                return i
        return -1

    def set_unread(self, addr, increment=True):
        for i, item in enumerate(self.items):
            if item['addr'] == addr:
                if increment:
                    item['unread'] += 1
                else:
                    item['unread'] = 1
                if i != self._selected:
                    self._redraw_item(i)
                break

    def clear_unread(self, index):
        if 0 <= index < len(self.items):
            self.items[index]['unread'] = 0
            self._redraw_item(index)

    def _redraw_all(self):
        self.canvas.delete("all")
        total_h = len(self.items) * self.ITEM_HEIGHT
        self.canvas.config(scrollregion=(0, 0, self.canvas.winfo_width(), max(total_h, 1)))
        for i, item in enumerate(self.items):
            item['y'] = i * self.ITEM_HEIGHT
            self._draw_item(i)

    def _redraw_item(self, index):
        if 0 <= index < len(self.items):
            self.canvas.delete(f"user_{index}")
            self._draw_item(index)

    def _truncate_text(self, text, max_pixel_width):
        if not text:
            return ""
        if self._name_font.measure(text) <= max_pixel_width:
            return text
        ellipsis = "…"
        ellipsis_w = self._name_font.measure(ellipsis)
        available = max(0, max_pixel_width - ellipsis_w)
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self._name_font.measure(text[:mid]) <= available:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo] + ellipsis if lo > 0 else ellipsis

    def _on_configure(self, event):
        if event.widget is not self.canvas:
            return
        new_w = self.canvas.winfo_width()
        if abs(new_w - self._last_width) > 1:
            self._last_width = new_w
            self._redraw_all()

    def _draw_item(self, index):
        """绘制单个列表项：支持真实头像、群组图标"""
        item = self.items[index]
        y = item['y']
        w = self.canvas.winfo_width() or 175
        h = self.ITEM_HEIGHT
        selected = (index == self._selected)
        hovered = (index == self._hovered)
        tag = f"user_{index}"
        is_group = (item.get('type') == 'group')

        # 背景
        if selected:
            bg = Theme.HOVER_LIGHT
        elif hovered:
            bg = Theme.BG_INPUT
        else:
            bg = Theme.BG_CARD
        self.canvas.create_rectangle(0, y, w, y + h, fill=bg, outline="", tags=(tag,))

        avatar_size = self.AVATAR_SIZE
        avatar_x = self.PADDING_X
        avatar_y = y + (h - avatar_size) // 2
        avatar_r = avatar_size // 2

        # ======= 头像绘制 =======
        display_name = item.get('display_name', '')
        first_char = display_name[0] if display_name else "?"
        uid = item.get('uid')
        avatar_img = self._avatar_cache.get(uid) if uid else None
        if uid is not None:
            print(f"[DIAG] _draw_item: name={display_name}, uid={uid}, 缓存命中={avatar_img is not None}")

        if avatar_img is not None:
            # 显示真实头像（圆形裁剪效果）
            self.canvas.create_image(
                avatar_x + avatar_r, avatar_y + avatar_r,
                image=avatar_img, anchor='center', tags=(tag,))
            # 圆形遮罩边框
            self.canvas.create_oval(
                avatar_x - 1, avatar_y - 1,
                avatar_x + avatar_size + 1, avatar_y + avatar_size + 1,
                fill="", outline=Theme.BORDER, width=1, tags=(tag,))
        elif is_group:
            # 群组图标: 浅色背景 + 多人图标
            self.canvas.create_oval(
                avatar_x, avatar_y,
                avatar_x + avatar_size, avatar_y + avatar_size,
                fill="#E3F2FD", outline="", tags=(tag,))
            # 群组文字: 👥 emoji 或简写
            self.canvas.create_text(
                avatar_x + avatar_r, avatar_y + avatar_r,
                text="👥", fill=Theme.TEXT_PRIMARY,
                font=(self.FONT_FAMILY, 11), tags=(tag,))
        else:
            # 无头像时用彩色圆形+首字
            color_idx = hash(display_name) % len(self.AVATAR_COLORS)
            self.canvas.create_oval(
                avatar_x, avatar_y,
                avatar_x + avatar_size, avatar_y + avatar_size,
                fill=self.AVATAR_COLORS[color_idx], outline="", tags=(tag,))
            self.canvas.create_text(
                avatar_x + avatar_r, avatar_y + avatar_r,
                text=first_char, fill=Theme.TEXT_WHITE,
                font=(self.FONT_FAMILY, 13, 'bold'), tags=(tag,))

        # ======= 用户名 =======
        text_x = avatar_x + avatar_size + self.TEXT_GAP
        badge_reserve = self.BADGE_AREA if item['unread'] > 0 and not selected else 12
        max_text_w = max(0, w - text_x - badge_reserve)
        truncated_name = self._truncate_text(display_name, max_text_w)
        # 记录是否截断（用于ToolTip）
        if truncated_name != display_name:
            self._truncated[index] = display_name
        else:
            self._truncated.pop(index, None)
        text_color = Theme.TEXT_PRIMARY
        if is_group:
            text_color = Theme.PRIMARY

        self.canvas.create_text(
            text_x, y + h // 2,
            text=truncated_name, fill=text_color,
            font=self._name_font, anchor='w', tags=(tag,))

        # 群组子标题（成员数）
        if is_group and item.get('members'):
            count = len(item['members'])
            member_names = [m[0] if isinstance(m, (list, tuple)) else str(m)
                           for m in item['members'][:3]]
            sub = f"{count}人: {', '.join(member_names)}"
            sub = self._truncate_text(sub, max_text_w)
            self.canvas.create_text(
                text_x, y + h // 2 + 15,
                text=sub, fill=Theme.TEXT_SECONDARY,
                font=self._small_font, anchor='w', tags=(tag,))

        # ======= 未读红点 =======
        if item['unread'] > 0 and not selected:
            badge_r = 11
            badge_x = w - 22
            badge_y = y + h // 2
            self.canvas.create_oval(
                badge_x - badge_r, badge_y - badge_r,
                badge_x + badge_r, badge_y + badge_r,
                fill=Theme.ERROR, outline="", tags=(tag,))
            unread_str = str(item['unread']) if item['unread'] <= 99 else "99+"
            self.canvas.create_text(
                badge_x, badge_y,
                text=unread_str, fill=Theme.TEXT_WHITE,
                font=self._badge_font, tags=(tag,))

        # 绑定点击事件
        self.canvas.tag_bind(tag, "<Button-1>", lambda e, idx=index: self._handle_click(idx))

    def _handle_click(self, index):
        if index != self._selected:
            old = self._selected
            self._selected = index
            if old >= 0:
                self._redraw_item(old)
            self._redraw_item(index)
            self.clear_unread(index)
            if self._on_select_callback:
                self._on_select_callback(index)

    def _on_click(self, event):
        y = self.canvas.canvasy(event.y)
        index = int(y // self.ITEM_HEIGHT)
        if 0 <= index < len(self.items):
            self._handle_click(index)

    def _on_motion(self, event):
        y = self.canvas.canvasy(event.y)
        index = int(y // self.ITEM_HEIGHT)
        if 0 <= index < len(self.items):
            if index != self._hovered:
                old = self._hovered
                self._hovered = index
                if old >= 0 and old != self._selected:
                    self._redraw_item(old)
                if index != self._selected:
                    self._redraw_item(index)
                self._hide_tooltip()
        else:
            if self._hovered >= 0 and self._hovered != self._selected:
                old = self._hovered
                self._hovered = -1
                self._redraw_item(old)
                self._hide_tooltip()
        # 显示ToolTip（如果截断）
        if 0 <= index < len(self.items) and index in self._truncated:
            self._show_tooltip(event, self._truncated[index])
        else:
            self._hide_tooltip()

    def _on_leave(self, event):
        if self._hovered >= 0 and self._hovered != self._selected:
            old = self._hovered
            self._hovered = -1
            self._redraw_item(old)
        self._hide_tooltip()

    def _show_tooltip(self, event, text):
        """在鼠标位置显示ToolTip"""
        self._hide_tooltip()
        x = self.canvas.winfo_pointerx() + 12
        y = self.canvas.winfo_pointery() + 8
        self._tooltip_window = tk.Toplevel(self.canvas)
        self._tooltip_window.wm_overrideredirect(True)
        self._tooltip_window.wm_geometry(f"+{x}+{y}")
        self._tooltip_window.attributes('-topmost', True)
        label = tk.Label(self._tooltip_window, text=text, bg=Theme.BG_CARD,
                         fg=Theme.TEXT_PRIMARY, font=('微软雅黑', 10),
                         padx=8, pady=4, relief='solid', bd=1,
                         highlightbackground=Theme.BORDER,
                         highlightthickness=1)
        label.pack()

    def _hide_tooltip(self):
        if self._tooltip_window:
            try:
                self._tooltip_window.destroy()
            except:
                pass
            self._tooltip_window = None

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-event.delta / 120), "units")


# ==================== 现代化配色方案 ====================
class Theme:
    """现代化主题配色"""
    # 主色调
    PRIMARY = "#2196F3"          # 主蓝色
    PRIMARY_DARK = "#1976D2"     # 深蓝色
    PRIMARY_LIGHT = "#BBDEFB"    # 浅蓝色
    
    # 背景色
    BG_LIGHT = "#FAFAFA"         # 浅灰背景
    BG_DARK = "#1E1E1E"          # 深色背景
    BG_CARD = "#FFFFFF"          # 卡片背景
    BG_INPUT = "#F5F5F5"         # 输入框背景
    
    # 文字颜色
    TEXT_PRIMARY = "#212121"     # 主要文字
    TEXT_SECONDARY = "#757575"   # 次要文字
    TEXT_HINT = "#9E9E9E"        # 提示文字
    TEXT_WHITE = "#FFFFFF"       # 白色文字
    
    # 消息气泡颜色
    MSG_SENT = "#95EC69"         # 发送消息（微信绿）
    MSG_RECEIVED = "#FFFFFF"     # 接收消息
    MSG_SHADOW = "#E0E0E0"       # 阴影色
    
    # 边框和分隔线
    BORDER = "#E0E0E0"           # 边框
    DIVIDER = "#BDBDBD"          # 分隔线
    
    # 功能色
    SUCCESS = "#4CAF50"          # 成功
    WARNING = "#FFC107"          # 警告
    ERROR = "#F44336"            # 错误
    
    # 按钮悬停效果
    HOVER_LIGHT = "#E3F2FD"      # 浅色悬停
    HOVER_DARK = "#1565C0"       # 深色悬停


# ==================== 动画工具类 ====================
class AnimationHelper:
    """动画辅助类 - 提供流畅的UI过渡动画"""
    
    @staticmethod
    def _hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    @staticmethod
    def _rgb_to_hex(rgb):
        return '#{:02x}{:02x}{:02x}'.format(*rgb)
    
    @staticmethod
    def _lerp_color(start_hex, end_hex, t):
        """在两个颜色之间线性插值"""
        sr, sg, sb = AnimationHelper._hex_to_rgb(start_hex)
        er, eg, eb = AnimationHelper._hex_to_rgb(end_hex)
        r = int(sr + (er - sr) * t)
        g = int(sg + (eg - sg) * t)
        b = int(sb + (eb - sb) * t)
        return AnimationHelper._rgb_to_hex((r, g, b))
    
    @staticmethod
    def color_transition(widget, attr, start_color, end_color, duration=200, steps=20, callback=None):
        """颜色渐变动画 - 平滑过渡控件颜色属性"""
        if not widget.winfo_exists():
            if callback:
                callback()
            return
        
        interval = duration // steps
        current_step = [0]
        
        def animate():
            if current_step[0] > steps:
                if callback:
                    callback()
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_cubic(t)
            color = AnimationHelper._lerp_color(start_color, end_color, eased_t)
            try:
                widget.config(**{attr: color})
            except tk.TclError:
                pass
            current_step[0] += 1
            widget.after(interval, animate)
        
        animate()
    
    @staticmethod
    def color_transition_canvas(canvas, item_id, attr, start_color, end_color, duration=200, steps=20, callback=None):
        """Canvas元素的颜色渐变动画"""
        if not canvas.winfo_exists():
            if callback:
                callback()
            return
        
        interval = duration // steps
        current_step = [0]
        
        def animate():
            if current_step[0] > steps:
                if callback:
                    callback()
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_cubic(t)
            color = AnimationHelper._lerp_color(start_color, end_color, eased_t)
            try:
                canvas.itemconfig(item_id, **{attr: color})
            except tk.TclError:
                pass
            current_step[0] += 1
            canvas.after(interval, animate)
        
        animate()
    
    @staticmethod
    def slide_in(widget, direction='right', duration=250, steps=20, callback=None):
        """滑入动画 - 从指定方向滑入控件"""
        if not widget.winfo_exists():
            if callback:
                callback()
            return
        
        interval = duration // steps
        current_step = [0]
        
        widget.update_idletasks()
        target_x = widget.winfo_x()
        target_y = widget.winfo_y()
        widget_width = widget.winfo_width()
        widget_height = widget.winfo_height()
        
        if direction == 'right':
            start_x = target_x + widget_width
            start_y = target_y
        elif direction == 'left':
            start_x = target_x - widget_width
            start_y = target_y
        elif direction == 'up':
            start_x = target_x
            start_y = target_y - widget_height
        elif direction == 'down':
            start_x = target_x
            start_y = target_y + widget_height
        else:
            start_x, start_y = target_x, target_y
        
        place_info = widget.place_info()
        
        def animate():
            if current_step[0] > steps:
                if '-x' in place_info:
                    widget.place_configure(x=target_x)
                if '-y' in place_info:
                    widget.place_configure(y=target_y)
                if callback:
                    callback()
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_cubic(t)
            current_x = int(start_x + (target_x - start_x) * eased_t)
            current_y = int(start_y + (target_y - start_y) * eased_t)
            try:
                if '-x' in place_info:
                    widget.place_configure(x=current_x)
                if '-y' in place_info:
                    widget.place_configure(y=current_y)
            except tk.TclError:
                pass
            current_step[0] += 1
            widget.after(interval, animate)

        animate()

    @staticmethod
    def slide_out(widget, direction='left', duration=200, steps=20, callback=None):
        """滑出动画"""
        if not widget.winfo_exists():
            if callback:
                callback()
            return
        
        interval = duration // steps
        current_step = [0]
        
        widget.update_idletasks()
        start_x = widget.winfo_x()
        start_y = widget.winfo_y()
        widget_width = widget.winfo_width()
        widget_height = widget.winfo_height()
        
        if direction == 'right':
            target_x = start_x + widget_width
            target_y = start_y
        elif direction == 'left':
            target_x = start_x - widget_width
            target_y = start_y
        elif direction == 'up':
            target_x = start_x
            target_y = start_y - widget_height
        elif direction == 'down':
            target_x = start_x
            target_y = start_y + widget_height
        else:
            target_x, target_y = start_x, start_y
        
        place_info = widget.place_info()
        
        def animate():
            if current_step[0] > steps:
                if callback:
                    callback()
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_cubic(t)
            current_x = int(start_x + (target_x - start_x) * eased_t)
            current_y = int(start_y + (target_y - start_y) * eased_t)
            try:
                if '-x' in place_info:
                    widget.place_configure(x=current_x)
                if '-y' in place_info:
                    widget.place_configure(y=current_y)
            except tk.TclError:
                pass
            current_step[0] += 1
            widget.after(interval, animate)

        animate()

    @staticmethod
    def fade_in_toplevel(window, duration=250, steps=20, callback=None):
        """顶层窗口淡入动画"""
        if not window.winfo_exists():
            if callback:
                callback()
            return
        
        interval = duration // steps
        current_step = [0]
        
        def animate():
            if current_step[0] > steps:
                try:
                    window.attributes('-alpha', 1.0)
                except tk.TclError:
                    pass
                if callback:
                    callback()
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_cubic(t)
            alpha = eased_t
            try:
                window.attributes('-alpha', alpha)
            except tk.TclError:
                pass
            current_step[0] += 1
            window.after(interval, animate)
        
        window.attributes('-alpha', 0.0)
        animate()
    
    @staticmethod
    def fade_out_toplevel(window, duration=200, steps=20, callback=None):
        """顶层窗口淡出动画"""
        if not window.winfo_exists():
            if callback:
                callback()
            return
        
        interval = duration // steps
        current_step = [0]
        
        def animate():
            if current_step[0] > steps:
                try:
                    window.attributes('-alpha', 0.0)
                except tk.TclError:
                    pass
                if callback:
                    callback()
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_cubic(t)
            alpha = 1.0 - eased_t
            try:
                window.attributes('-alpha', alpha)
            except tk.TclError:
                pass
            current_step[0] += 1
            window.after(interval, animate)
        
        animate()
    
    @staticmethod
    def scale_in_window(window, duration=300, steps=25, callback=None):
        """窗口缩放进入动画 - 从小变大"""
        if not window.winfo_exists():
            if callback:
                callback()
            return
        
        window.update_idletasks()
        target_width = window.winfo_width()
        target_height = window.winfo_height()
        target_x = window.winfo_x()
        target_y = window.winfo_y()
        
        start_width = int(target_width * 0.8)
        start_height = int(target_height * 0.8)
        start_x = target_x + (target_width - start_width) // 2
        start_y = target_y + (target_height - start_height) // 2
        
        interval = duration // steps
        current_step = [0]
        
        def animate():
            if current_step[0] > steps:
                try:
                    window.geometry(f"{target_width}x{target_height}+{target_x}+{target_y}")
                    window.attributes('-alpha', 1.0)
                except tk.TclError:
                    pass
                if callback:
                    callback()
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_back(t)
            alpha = min(1.0, t * 1.5)
            w = int(start_width + (target_width - start_width) * eased_t)
            h = int(start_height + (target_height - start_height) * eased_t)
            x = int(start_x + (target_x - start_x) * eased_t)
            y = int(start_y + (target_y - start_y) * eased_t)
            try:
                window.geometry(f"{w}x{h}+{x}+{y}")
                window.attributes('-alpha', alpha)
            except tk.TclError:
                pass
            current_step[0] += 1
            window.after(interval, animate)
        
        window.attributes('-alpha', 0.0)
        animate()
    
    @staticmethod
    def canvas_slide_up(canvas, items, start_offset=30, duration=250, steps=20, callback=None):
        """Canvas元素从下方滑入"""
        if not canvas.winfo_exists():
            if callback:
                callback()
            return
        
        interval = duration // steps
        current_step = [0]
        
        def animate():
            if current_step[0] > steps:
                if callback:
                    callback()
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_cubic(t)
            offset = int(start_offset * (1 - eased_t))
            delta = offset - int(start_offset * (1 - AnimationHelper._ease_out_cubic((current_step[0] - 1) / steps))) if current_step[0] > 0 else 0
            
            actual_delta = offset - (start_offset - int(start_offset * eased_t) if current_step[0] > 0 else 0)
            # Simpler approach: move incrementally
            prev_t = max(0, (current_step[0] - 1) / steps)
            prev_eased = AnimationHelper._ease_out_cubic(prev_t)
            prev_offset = int(start_offset * (1 - prev_eased))
            move_amount = offset - prev_offset
            
            try:
                for item in items:
                    canvas.move(item, 0, move_amount)
            except tk.TclError:
                pass
            current_step[0] += 1
            canvas.after(interval, animate)
        
        # Move items down initially
        try:
            for item in items:
                canvas.move(item, 0, start_offset)
        except tk.TclError:
            pass
        animate()
    
    @staticmethod
    def _ease_out_cubic(t):
        """缓出三次方曲线"""
        return 1 - pow(1 - t, 3)
    
    @staticmethod
    def _ease_out_back(t):
        """缓出回弹曲线"""
        c1 = 1.70158
        c3 = c1 + 1
        return 1 + c3 * pow(t - 1, 3) + c1 * pow(t - 1, 2)
    
    @staticmethod
    def _ease_in_out_cubic(t):
        """缓入缓出三次方曲线"""
        if t < 0.5:
            return 4 * t * t * t
        return 1 - pow(-2 * t + 2, 3) / 2
    
    @staticmethod
    def button_press_effect(button, duration=150):
        """按钮点击动画 - 缩放反馈"""
        if not button.winfo_exists():
            return
        
        original_font = button.cget('font')
        try:
            import tkinter.font as tkfont
            font_obj = tkfont.Font(font=original_font)
            original_size = font_obj.cget('size')
            smaller_size = max(1, original_size - 1)
            
            def shrink():
                try:
                    button.config(font=(font_obj.cget('family'), smaller_size, font_obj.cget('weight')))
                except tk.TclError:
                    pass
                button.after(duration, restore)
            
            def restore():
                try:
                    button.config(font=original_font)
                except tk.TclError:
                    pass
            
            shrink()
        except Exception:
            pass
    
    @staticmethod
    def smooth_scroll_canvas(canvas, target_ratio, duration=200, steps=20):
        """平滑滚动Canvas到目标位置（target_ratio为0.0~1.0的比例值）"""
        if not canvas.winfo_exists():
            return

        current_ratio = canvas.yview()[0]
        if abs(current_ratio - target_ratio) < 0.01:
            return

        interval = duration // steps
        current_step = [0]

        def animate():
            if current_step[0] > steps:
                try:
                    canvas.yview_moveto(target_ratio)
                except tk.TclError:
                    pass
                return
            t = current_step[0] / steps
            eased_t = AnimationHelper._ease_out_cubic(t)
            current = current_ratio + (target_ratio - current_ratio) * eased_t
            try:
                canvas.yview_moveto(current)
            except tk.TclError:
                pass
            current_step[0] += 1
            canvas.after(interval, animate)

        animate()


IP = socket.gethostbyname(socket.gethostname())
PORT = 50000
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE
connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
connection.connect((IP, PORT))
connection = ssl_context.wrap_socket(connection)


def recv_all(sock, size):
    """确保从 socket 读取完整 size 字节"""
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionResetError("连接已断开")
        data += chunk
    return data


def send_pickle(sock, obj):
    """Pickle 对象并用 10 字节固定宽度长度前缀发送（防止 TCP 粘包）"""
    data = pickle.dumps(obj)
    sock.send(f"{len(data):<10}".encode())
    sock.send(data)


# root窗口延迟到登录成功后再创建，避免闪现
root = None
que = deque()
onlines = []
images = {}
image_cache = None
# onlines结构：[[(user_name,(IP,POST)), class interface]]
users = [[("robot", None)]]
groups = []  # 群组列表: [{'name': str, 'addr': str, 'members': [(name, addr), ...], 'interface': DialogueInterface}]
icon_path = ""
_name = ""
_pwd = ""
_my_uid = 0  # 当前登录用户的 UID
think = False
_cropped_icon_b64 = ""  # 注册时预裁剪的头像数据
_crop_root = None  # 供 ImageCrop 使用的根窗口

class ImageCrop:
    """头像裁剪工具 - 从图片中选择正方形区域"""

    def __init__(self, image_path, parent_root=None):
        self.cropped_image = None
        self.sel_start = None
        self.sel_rect = None
        self.handle_size = 8
        self.active_handle = None
        self.mode = 'draw'

        root_win = parent_root or _crop_root

        # 加载并缩放图片
        pil_img = Image.open(image_path)
        max_display = 500
        ratio = min(max_display / pil_img.width, max_display / pil_img.height, 1.0)
        display_w = int(pil_img.width * ratio)
        display_h = int(pil_img.height * ratio)
        self.original_img = pil_img
        self.display_img = pil_img.resize((display_w, display_h), Image.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(self.display_img)
        self.scale = 1.0 / ratio

        # 创建裁剪窗口
        self.top = tk.Toplevel(root_win)
        self.top.title("裁剪头像 - 拖动选择正方形区域")
        self.top.geometry(f"{display_w + 40}x{display_h + 80}")
        self.top.resizable(False, False)
        self.top.configure(bg=Theme.BG_LIGHT)
        self.top.transient(root_win)
        self.top.grab_set()

        canvas_w = display_w + 20
        canvas_h = display_h + 20
        self.canvas = tk.Canvas(self.top, width=canvas_w, height=canvas_h,
                                bg=Theme.BG_CARD, highlightthickness=1,
                                highlightbackground=Theme.BORDER)
        self.canvas.place(x=10, y=10)
        self.img_x = (canvas_w - display_w) // 2
        self.img_y = (canvas_h - display_h) // 2
        self.canvas.create_image(self.img_x, self.img_y, image=self.tk_img, anchor='nw', tag='img')

        btn_frame = tk.Frame(self.top, bg=Theme.BG_LIGHT)
        btn_frame.place(x=0, rely=1.0, y=-45, relwidth=1.0, height=40)

        self.confirm_btn = tk.Button(btn_frame, text="确认", font=('微软雅黑', 11, 'bold'),
                                     bg=Theme.PRIMARY, fg=Theme.TEXT_WHITE, relief=tk.FLAT,
                                     cursor="hand2", state='disabled',
                                     command=self._confirm)
        self.confirm_btn.pack(side=tk.RIGHT, padx=(5, 15), pady=5, ipadx=15)

        cancel_btn = tk.Button(btn_frame, text="取消", font=('微软雅黑', 11),
                               bg=Theme.BG_INPUT, relief=tk.FLAT, cursor="hand2",
                               command=self._cancel)
        cancel_btn.pack(side=tk.RIGHT, padx=5, pady=5, ipadx=15)

        self.canvas.bind('<Button-1>', self._on_down)
        self.canvas.bind('<B1-Motion>', self._on_drag)
        self.canvas.bind('<ButtonRelease-1>', self._on_up)
        self.canvas.bind('<Motion>', self._on_motion)
        self.top.bind('<Escape>', lambda e: self._cancel())
        self.top.protocol("WM_DELETE_WINDOW", self._cancel)
        self.top.wait_window()

    def _abs_coords(self, x, y):
        img_x = max(0, min(x - self.img_x, self.display_img.width))
        img_y = max(0, min(y - self.img_y, self.display_img.height))
        return (int(img_x * self.scale), int(img_y * self.scale))

    def _on_down(self, event):
        if self.mode == 'done':
            handle = self._get_handle(event.x, event.y)
            if handle:
                self.mode = 'adjust'
                self.active_handle = handle
                self._last_x, self._last_y = event.x, event.y
                return
            if self._inside_rect(event.x, event.y):
                self.mode = 'move'
                self._last_x, self._last_y = event.x, event.y
                return
        self._clear_selection()
        self.sel_start = (event.x, event.y)
        self.mode = 'draw'

    def _on_drag(self, event):
        if self.mode == 'draw' and self.sel_start:
            self._draw_square(event.x, event.y)
        elif self.mode == 'adjust':
            self._adjust(event.x, event.y)
        elif self.mode == 'move':
            self._move(event.x, event.y)

    def _on_up(self, event):
        if self.mode == 'draw' and self.sel_rect:
            coords = self.canvas.coords(self.sel_rect)
            if coords[2] - coords[0] >= 10:
                self.mode = 'done'
                self.confirm_btn.config(state='normal')
                self._draw_handles()
        elif self.mode in ('adjust', 'move'):
            self.mode = 'done'

    def _on_motion(self, event):
        if self.mode == 'done':
            handle = self._get_handle(event.x, event.y)
            if handle:
                cursors = {'nw': 'size_nw_se', 'se': 'size_nw_se',
                           'ne': 'size_ne_sw', 'sw': 'size_ne_sw',
                           'n': 'size_ns', 's': 'size_ns',
                           'w': 'size_we', 'e': 'size_we'}
                self.canvas.config(cursor=cursors.get(handle, 'crosshair'))
            elif self._inside_rect(event.x, event.y):
                self.canvas.config(cursor='fleur')
            else:
                self.canvas.config(cursor='crosshair')
        else:
            self.canvas.config(cursor='crosshair')

    def _draw_square(self, ex, ey):
        sx, sy = self.sel_start
        size = min(abs(ex - sx), abs(ey - sy))
        x = sx - size if ex < sx else sx
        y = sy - size if ey < sy else sy
        if self.sel_rect:
            self.canvas.coords(self.sel_rect, x, y, x + size, y + size)
        else:
            self.sel_rect = self.canvas.create_rectangle(
                x, y, x + size, y + size,
                outline='#0078D4', width=2, dash=(5, 3))

    def _clear_selection(self):
        self._delete_handles()
        if self.sel_rect:
            self.canvas.delete(self.sel_rect)
            self.sel_rect = None
        self.confirm_btn.config(state='disabled')

    def _inside_rect(self, x, y):
        if not self.sel_rect:
            return False
        x1, y1, x2, y2 = self.canvas.coords(self.sel_rect)
        return x1 <= x <= x2 and y1 <= y <= y2

    def _get_handle(self, x, y):
        for name, hid in getattr(self, '_handles', {}).items():
            hx1, hy1, hx2, hy2 = self.canvas.coords(hid)
            if hx1 <= x <= hx2 and hy1 <= y <= hy2:
                return name
        return None

    def _draw_handles(self):
        self._delete_handles()
        self._handles = {}
        if not self.sel_rect:
            return
        x1, y1, x2, y2 = self.canvas.coords(self.sel_rect)
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        positions = {'nw': (x1, y1), 'ne': (x2, y1), 'sw': (x1, y2), 'se': (x2, y2),
                     'n': (cx, y1), 's': (cx, y2), 'w': (x1, cy), 'e': (x2, cy)}
        hs = self.handle_size
        for name, (px, py) in positions.items():
            hid = self.canvas.create_rectangle(
                px - hs, py - hs, px + hs, py + hs,
                fill='white', outline='#0078D4', width=2, tags='handle')
            self._handles[name] = hid

    def _delete_handles(self):
        self.canvas.delete('handle')
        self._handles = {}

    def _adjust(self, ex, ey):
        if not self.sel_rect:
            return
        dx, dy = ex - self._last_x, ey - self._last_y
        x1, y1, x2, y2 = self.canvas.coords(self.sel_rect)
        mid_x, mid_y = self.img_x + self.display_img.width, self.img_y + self.display_img.height
        if 'w' in self.active_handle:
            x1 = max(self.img_x, x1 + dx)
        if 'e' in self.active_handle:
            x2 = min(mid_x, x2 + dx)
        if 'n' in self.active_handle:
            y1 = max(self.img_y, y1 + dy)
        if 's' in self.active_handle:
            y2 = min(mid_y, y2 + dy)
        size = min(x2 - x1, y2 - y1)
        if 'w' in self.active_handle:
            x2, y2 = x1 + size, y1 + size
        elif 'e' in self.active_handle:
            x1, y1 = x2 - size, y2 - size
        self.canvas.coords(self.sel_rect, x1, y1, x2, y2)
        self._draw_handles()
        self._last_x, self._last_y = ex, ey

    def _move(self, ex, ey):
        if not self.sel_rect:
            return
        dx, dy = ex - self._last_x, ey - self._last_y
        x1, y1, x2, y2 = self.canvas.coords(self.sel_rect)
        iw = self.display_img.width
        ih = self.display_img.height
        w, h = x2 - x1, y2 - y1
        nx = max(self.img_x, min(self.img_x + iw - w, x1 + dx))
        ny = max(self.img_y, min(self.img_y + ih - h, y1 + dy))
        self.canvas.move(self.sel_rect, nx - x1, ny - y1)
        self._draw_handles()
        self._last_x, self._last_y = ex, ey

    def _confirm(self):
        if not self.sel_rect:
            return
        x1, y1, x2, y2 = self.canvas.coords(self.sel_rect)
        px1, py1 = self._abs_coords(x1, y1)
        px2, py2 = self._abs_coords(x2, y2)
        self.cropped_image = self.original_img.crop((px1, py1, px2, py2))
        self.top.destroy()

    def _cancel(self):
        self.cropped_image = None
        self.top.destroy()

    def get_result(self):
        return self.cropped_image


def main():
    global connection, que, users, groups, icon_path, _name, _pwd, images, root, load, image_cache, main_widgets, user_list_canvas
    # TinUI 深度思考控件追踪
    think_label_uid = None
    think_onoff_uid = None
    # 检查是否已预加载窗口
    if 'main_widgets' in globals() and main_widgets.get('preloaded', False):
        # 使用预加载的窗口
        root = main_widgets['root']
    else:
        # 未预加载，创建新窗口
        root = tk.Tk()
        root.withdraw()
        root.configure(bg=Theme.BG_LIGHT)
        if 'image_cache' in globals():
            images = {key: ImageTk.PhotoImage(value) for key, value in image_cache.items()}
            del image_cache
        root.geometry(f"{int(root.winfo_screenwidth() / 2.5)}x{int(root.winfo_screenheight() / 2)}\
+{int(root.winfo_screenwidth() / 3)}+{int(root.winfo_screenheight() / 4)}")
        root.iconbitmap("icon/icon.ico")
        root.title("聊天屋")
        root.minsize(int(root.winfo_screenwidth() / 2.5 * 0.78125), int(root.winfo_screenheight() / 2.5 * 0.78125) if int(
            root.winfo_screenheight() / 2.5 * 0.78125) >= 400 else 400)

    global _crop_root
    _crop_root = root

    class MyCapture:
        """优化后的截图工具类 - 支持调整选区大小"""
        def __init__(self):
            self.X = self.Y = 0
            self.sel = False
            self.rect_id = None
            self.handle_size = 8
            self.handles = {}
            self.active_handle = None
            self.rect_coords = None
            self.mode = 'draw'  # 'draw', 'adjust', 'move', 'done'
            self.screenWidth = root.winfo_screenwidth()
            self.screenHeight = root.winfo_screenheight()
            
            # 创建截图窗口
            self.top = tk.Toplevel(root, width=self.screenWidth, height=self.screenHeight, bd=0)
            self.top.overrideredirect(True)
            self.top.attributes('-topmost', True)
            
            # 创建画布
            self.canvas = tk.Canvas(
                self.top, bg='white', 
                width=self.screenWidth, height=self.screenHeight, 
                bd=0, highlightthickness=0
            )
            
            # 捕获屏幕并创建遮罩（在显示tooltip之前捕获，避免tooltip被截图）
            self._capture_screen()
            
            # 显示提示
            self.tooltip = ToolTip(self.canvas, "拖动选择区域，松开进入调整模式，双击或按Enter保存，按Esc取消", 
                   0, True, bg="white", font=("SimSun", 10))
            
            # 绑定事件
            self.canvas.bind('<Button-1>', self._on_left_button_down)
            self.canvas.bind('<B1-Motion>', self._on_left_button_move)
            self.canvas.bind('<ButtonRelease-1>', self._on_left_button_up)
            self.canvas.bind('<Double-Button-1>', self._on_double_click)
            self.canvas.bind('<Motion>', self._on_mouse_move, '+')
            self.canvas.bind('<Escape>', lambda e: self._cleanup_and_exit())
            self.top.bind('<Escape>', lambda e: self._cleanup_and_exit())
            self.top.bind('<Key-Escape>', lambda e: self._cleanup_and_exit())
            self.canvas.bind('<Return>', lambda e: self._save_current_selection())
            self.top.bind('<Return>', lambda e: self._save_current_selection())
            
            self.canvas.pack(fill=tk.BOTH, expand=True)
            
            # 强制更新界面，确保pack完成后再设置焦点
            self.top.update_idletasks()
            
            # 设置焦点，确保Esc键事件能被捕获
            self.top.focus_set()
            self.canvas.focus_set()
            
            # 鼠标样式映射 - 使用resize系列
            self._cursor_map = {
                'nw': 'size_nw_se',
                'ne': 'size_ne_sw',
                'sw': 'size_ne_sw',
                'se': 'size_nw_se',
                'n': 'size_ns',
                's': 'size_ns',
                'w': 'size_we',
                'e': 'size_we',
            }
            
            # 为canvas添加圆角矩形绘制方法
            self.canvas.create_rounded_rect = self._create_rounded_rect
            
        def _create_rounded_rect(self, x1, y1, x2, y2, radius=10, **kwargs):
            """创建圆角矩形"""
            points = [
                x1 + radius, y1,
                x2 - radius, y1,
                x2, y1,
                x2, y1 + radius,
                x2, y2 - radius,
                x2, y2,
                x2 - radius, y2,
                x1 + radius, y2,
                x1, y2,
                x1, y2 - radius,
                x1, y1 + radius,
                x1, y1,
            ]
            return self.canvas.create_polygon(points, smooth=True, **kwargs)
            
        def _capture_screen(self):
            """捕获屏幕并创建半透明遮罩"""
            try:
                # 先隐藏截图窗口，避免被截到
                self.top.withdraw()
                # 强制更新界面，确保窗口隐藏
                self.top.update()
                # 短暂延迟，确保窗口完全隐藏
                time.sleep(0.1)
                # 捕获屏幕
                self.original_image = ImageGrab.grab()
                self.image = self.original_image.resize((self.screenWidth, self.screenHeight))
                white_mask = Image.new("RGB", self.image.size, (255, 255, 255))
                self.masked_image = Image.blend(self.image, white_mask, 0.3)
                self.tk_image = ImageTk.PhotoImage(self.masked_image)
                self.canvas.create_image(
                    self.screenWidth / 2, self.screenHeight / 2, 
                    image=self.tk_image, tag='bg'
                )
                # 显示截图窗口
                self.top.deiconify()
            except Exception as e:
                print(f"截图初始化失败: {e}")
                self.top.destroy()

        def _get_handle_at(self, x, y):
            """检查鼠标是否在调整手柄上"""
            if not self.rect_coords:
                return None
            x1, y1, x2, y2 = self.rect_coords
            handles = {
                'nw': (x1, y1),
                'ne': (x2, y1),
                'sw': (x1, y2),
                'se': (x2, y2),
                'n': ((x1 + x2) / 2, y1),
                's': ((x1 + x2) / 2, y2),
                'w': (x1, (y1 + y2) / 2),
                'e': (x2, (y1 + y2) / 2),
            }
            for name, (hx, hy) in handles.items():
                if abs(x - hx) <= self.handle_size and abs(y - hy) <= self.handle_size:
                    return name
            return None

        def _create_handles(self):
            """创建调整手柄"""
            if not self.rect_coords:
                return
            x1, y1, x2, y2 = self.rect_coords
            handle_positions = {
                'nw': (x1, y1),
                'ne': (x2, y1),
                'sw': (x1, y2),
                'se': (x2, y2),
                'n': ((x1 + x2) / 2, y1),
                's': ((x1 + x2) / 2, y2),
                'w': (x1, (y1 + y2) / 2),
                'e': (x2, (y1 + y2) / 2),
            }
            for name, (x, y) in handle_positions.items():
                handle_id = self.canvas.create_rectangle(
                    x - self.handle_size/2, y - self.handle_size/2,
                    x + self.handle_size/2, y + self.handle_size/2,
                    fill='white', outline='#0078D4', width=2, tags='handle'
                )
                self.handles[name] = handle_id

        def _delete_handles(self):
            """删除调整手柄"""
            self.canvas.delete('handle')
            self.handles.clear()

        def _update_display(self):
            """更新显示"""
            if not self.rect_coords:
                return
            x1, y1, x2, y2 = self.rect_coords
            # 确保坐标正确排序（左 < 右，上 < 下）
            left, right = sorted([x1, x2])
            top, bottom = sorted([y1, y2])
            display_image = self.masked_image.copy()
            selected_area = self.image.crop((int(left), int(top), int(right), int(bottom)))
            display_image.paste(selected_area, (int(left), int(top)))
            self.tk_image = ImageTk.PhotoImage(display_image)
            self.canvas.itemconfig('bg', image=self.tk_image)

        def _on_left_button_down(self, event):
            """鼠标左键按下"""
            if self.mode == 'done':
                # 检查是否点击了手柄
                handle = self._get_handle_at(event.x, event.y)
                if handle:
                    self.mode = 'adjust'
                    self.active_handle = handle
                    self.last_x = event.x
                    self.last_y = event.y
                elif self.rect_coords and self._point_in_rect(event.x, event.y):
                    # 拖动整个选区
                    self.mode = 'move'
                    self.last_x = event.x
                    self.last_y = event.y
                else:
                    # 重新开始选择
                    self._reset_selection()
                    self.X, self.Y = event.x, event.y
                    self.sel = True
            else:
                self.X, self.Y = event.x, event.y
                self.sel = True

        def _point_in_rect(self, x, y):
            """检查点是否在选区内"""
            if not self.rect_coords:
                return False
            x1, y1, x2, y2 = self.rect_coords
            return min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2)

        def _reset_selection(self):
            """重置选择"""
            self._delete_handles()
            self._delete_toolbar()
            if self.rect_id:
                self.canvas.delete(self.rect_id)
                self.rect_id = None
            self.rect_coords = None
            self.mode = 'draw'
            self.tk_image = ImageTk.PhotoImage(self.masked_image)
            self.canvas.itemconfig('bg', image=self.tk_image)

        def _delete_toolbar(self):
            """删除工具栏"""
            self.canvas.delete('toolbar')
            for attr in ['toolbar_bg', 'save_btn_bg', 'save_btn', 'cancel_btn_bg', 'cancel_btn']:
                if hasattr(self, attr):
                    try:
                        self.canvas.delete(getattr(self, attr))
                    except:
                        pass
                    delattr(self, attr)

        def _on_left_button_move(self, event):
            """鼠标拖动"""
            if self.mode == 'adjust' and self.active_handle:
                self._adjust_rectangle(event.x, event.y)
            elif self.mode == 'move':
                self._move_rectangle(event.x, event.y)
            elif self.sel and self.mode == 'draw':
                self._draw_rectangle(event.x, event.y)

        def _adjust_rectangle(self, x, y):
            """调整选区大小"""
            if not self.rect_coords:
                return
            x1, y1, x2, y2 = self.rect_coords
            dx = x - self.last_x
            dy = y - self.last_y
            
            if 'w' in self.active_handle:
                x1 += dx
            if 'e' in self.active_handle:
                x2 += dx
            if 'n' in self.active_handle:
                y1 += dy
            if 's' in self.active_handle:
                y2 += dy
                
            self.rect_coords = (x1, y1, x2, y2)
            self.last_x = x
            self.last_y = y
            self._redraw_selection()

        def _move_rectangle(self, x, y):
            """移动选区"""
            if not self.rect_coords:
                return
            dx = x - self.last_x
            dy = y - self.last_y
            x1, y1, x2, y2 = self.rect_coords
            self.rect_coords = (x1 + dx, y1 + dy, x2 + dx, y2 + dy)
            self.last_x = x
            self.last_y = y
            self._redraw_selection()

        def _draw_rectangle(self, event_x, event_y):
            """绘制选区"""
            left, right = sorted([self.X, event_x])
            top, bottom = sorted([self.Y, event_y])
            
            if right - left < 2 or bottom - top < 2:
                return
                
            self.rect_coords = (left, top, right, bottom)
            
            if self.rect_id:
                self.canvas.delete(self.rect_id)
            
            self._update_display()
            self.rect_id = self.canvas.create_rectangle(
                left, top, right, bottom, 
                outline='#0078D4', width=2
            )

        def _redraw_selection(self):
            """重绘选区和手柄"""
            if not self.rect_coords:
                return
            x1, y1, x2, y2 = self.rect_coords
            
            self._update_display()
            
            if self.rect_id:
                self.canvas.delete(self.rect_id)
            self.rect_id = self.canvas.create_rectangle(
                x1, y1, x2, y2, 
                outline='#0078D4', width=2
            )
            
            self._delete_handles()
            self._create_handles()
            self._update_toolbar_position()

        def _on_mouse_move(self, event):
            """鼠标移动 - 更新鼠标样式"""
            if self.mode == 'done':
                handle = self._get_handle_at(event.x, event.y)
                if handle:
                    cursor = self._cursor_map.get(handle, 'arrow')
                    self.canvas.config(cursor=cursor)
                elif self.rect_coords and self._point_in_rect(event.x, event.y):
                    self.canvas.config(cursor='fleur')  # 移动样式
                else:
                    self.canvas.config(cursor='arrow')
            elif self.mode == 'adjust':
                cursor = self._cursor_map.get(self.active_handle, 'arrow')
                self.canvas.config(cursor=cursor)
            elif self.mode == 'move':
                self.canvas.config(cursor='fleur')
            else:
                self.canvas.config(cursor='crosshair')

        def _on_left_button_up(self, event):
            """鼠标左键释放"""
            if self.mode == 'draw' and self.sel:
                self.sel = False
                if self.rect_coords:
                    x1, y1, x2, y2 = self.rect_coords
                    if abs(x2 - x1) >= 2 and abs(y2 - y1) >= 2:
                        self.mode = 'done'
                        self._create_handles()
                        self._show_toolbar()
            elif self.mode in ('adjust', 'move'):
                self.mode = 'done'
                self.active_handle = None
                # 恢复鼠标样式
                handle = self._get_handle_at(event.x, event.y)
                if handle:
                    cursor = self._cursor_map.get(handle, 'arrow')
                    self.canvas.config(cursor=cursor)
                elif self.rect_coords and self._point_in_rect(event.x, event.y):
                    self.canvas.config(cursor='fleur')
                else:
                    self.canvas.config(cursor='arrow')

        def _show_toolbar(self):
            """显示工具栏"""
            if not self.rect_coords:
                return
            x1, y1, x2, y2 = self.rect_coords
            self._toolbar_x = max(10, min(x1, self.screenWidth - 130))
            self._toolbar_y = max(10, y2 + 10)
            if self._toolbar_y + 40 > self.screenHeight:
                self._toolbar_y = max(10, y1 - 45)
            
            self._draw_toolbar()

        def _draw_toolbar(self):
            """绘制现代化工具栏 - 圆角设计，阴影效果"""
            self._delete_toolbar()
            
            # 工具栏尺寸
            toolbar_width = 130
            toolbar_height = 42
            corner_radius = 8
            
            # 创建阴影效果（底层）
            shadow_offset = 3
            self.toolbar_shadow = self.canvas.create_rounded_rect(
                self._toolbar_x + shadow_offset, self._toolbar_y + shadow_offset,
                self._toolbar_x + toolbar_width + shadow_offset, self._toolbar_y + toolbar_height + shadow_offset,
                radius=corner_radius,
                fill='#000000', outline='', width=0,
                tags='toolbar'
            )
            # 设置阴影透明度
            self.canvas.itemconfig(self.toolbar_shadow, stipple='gray50')
            
            # 创建工具栏背景 - 使用圆角矩形
            self.toolbar_bg = self.canvas.create_rounded_rect(
                self._toolbar_x, self._toolbar_y, 
                self._toolbar_x + toolbar_width, self._toolbar_y + toolbar_height,
                radius=corner_radius,
                fill=Theme.BG_CARD, outline=Theme.BORDER, width=1,
                tags='toolbar'
            )
            
            # 按钮尺寸
            btn_width = 55
            btn_height = 30
            btn_radius = 6
            
            # 保存按钮背景 - 圆角设计，主色调
            self.save_btn_bg = self.canvas.create_rounded_rect(
                self._toolbar_x + 8, self._toolbar_y + 6,
                self._toolbar_x + 8 + btn_width, self._toolbar_y + 6 + btn_height,
                radius=btn_radius,
                fill=Theme.PRIMARY, outline='', width=0,
                tags='toolbar'
            )
            
            # 保存按钮文字
            self.save_btn = self.canvas.create_text(
                self._toolbar_x + 8 + btn_width//2, self._toolbar_y + 6 + btn_height//2,
                text='✓ 保存', fill=Theme.TEXT_WHITE, font=('微软雅黑', 10, 'bold'),
                tags='toolbar'
            )
            
            # 取消按钮背景 - 圆角设计，灰色
            self.cancel_btn_bg = self.canvas.create_rounded_rect(
                self._toolbar_x + 8 + btn_width + 4, self._toolbar_y + 6,
                self._toolbar_x + 8 + btn_width * 2 + 4, self._toolbar_y + 6 + btn_height,
                radius=btn_radius,
                fill=Theme.BG_INPUT, outline=Theme.BORDER, width=1,
                tags='toolbar'
            )
            
            # 取消按钮文字
            self.cancel_btn = self.canvas.create_text(
                self._toolbar_x + 8 + btn_width + 4 + btn_width//2, self._toolbar_y + 6 + btn_height//2,
                text='✗ 取消', fill=Theme.TEXT_PRIMARY, font=('微软雅黑', 10),
                tags='toolbar'
            )
            
            # 绑定保存按钮事件
            self.canvas.tag_bind(self.save_btn_bg, '<Button-1>', lambda e: self._on_save_click())
            self.canvas.tag_bind(self.save_btn, '<Button-1>', lambda e: self._on_save_click())
            self.canvas.tag_bind(self.save_btn_bg, '<Enter>', lambda e: self._on_save_hover(True))
            self.canvas.tag_bind(self.save_btn_bg, '<Leave>', lambda e: self._on_save_hover(False))
            self.canvas.tag_bind(self.save_btn, '<Enter>', lambda e: self._on_save_hover(True))
            self.canvas.tag_bind(self.save_btn, '<Leave>', lambda e: self._on_save_hover(False))
            
            # 绑定取消按钮事件
            self.canvas.tag_bind(self.cancel_btn_bg, '<Button-1>', lambda e: self._cleanup_and_exit())
            self.canvas.tag_bind(self.cancel_btn, '<Button-1>', lambda e: self._cleanup_and_exit())
            self.canvas.tag_bind(self.cancel_btn_bg, '<Enter>', lambda e: self._on_cancel_hover(True))
            self.canvas.tag_bind(self.cancel_btn_bg, '<Leave>', lambda e: self._on_cancel_hover(False))
            self.canvas.tag_bind(self.cancel_btn, '<Enter>', lambda e: self._on_cancel_hover(True))
            self.canvas.tag_bind(self.cancel_btn, '<Leave>', lambda e: self._on_cancel_hover(False))

        def _on_save_click(self):
            """保存按钮点击处理"""
            # 防止重复点击 - 只解绑保存按钮的事件
            if hasattr(self, 'save_btn_bg'):
                self.canvas.tag_unbind(self.save_btn_bg, '<Button-1>')
            if hasattr(self, 'save_btn'):
                self.canvas.tag_unbind(self.save_btn, '<Button-1>')
            # 隐藏截图窗口，显示文件保存对话框
            self.top.withdraw()
            self._save_current_selection()

        def _on_save_hover(self, hovering):
            """保存按钮悬停效果 - 现代化样式"""
            if hovering:
                self.canvas.itemconfig(self.save_btn_bg, fill=Theme.HOVER_DARK)
                self.canvas.config(cursor='hand2')
            else:
                self.canvas.itemconfig(self.save_btn_bg, fill=Theme.PRIMARY)
                self.canvas.config(cursor='arrow')

        def _on_cancel_hover(self, hovering):
            """取消按钮悬停效果 - 现代化样式"""
            if hovering:
                self.canvas.itemconfig(self.cancel_btn_bg, fill=Theme.HOVER_LIGHT)
                self.canvas.config(cursor='hand2')
            else:
                self.canvas.itemconfig(self.cancel_btn_bg, fill=Theme.BG_INPUT)
                self.canvas.config(cursor='arrow')

        def _update_toolbar_position(self):
            """更新工具栏位置"""
            if not self.rect_coords:
                return
            x1, y1, x2, y2 = self.rect_coords
            self._toolbar_x = max(10, min(x1, self.screenWidth - 130))
            self._toolbar_y = max(10, y2 + 10)
            if self._toolbar_y + 40 > self.screenHeight:
                self._toolbar_y = max(10, y1 - 45)
            self._draw_toolbar()

        def _on_double_click(self, event):
            """双击保存"""
            if self.mode == 'done' and self.rect_coords:
                self._save_current_selection()

        def _save_current_selection(self):
            """保存当前选区"""
            if not self.rect_coords:
                return
            x1, y1, x2, y2 = self.rect_coords
            left, right = sorted([int(x1), int(x2)])
            top, bottom = sorted([int(y1), int(y2)])
            
            if right - left < 2 or bottom - top < 2:
                return
                
            selected_image = self.image.crop((left, top, right, bottom))
            self._save_screenshot(selected_image)

        def _save_screenshot(self, image):
            """保存截图"""
            try:
                fileName = tk.filedialog.asksaveasfilename(
                    title='保存截图',
                    defaultextension=".png",
                    initialfile=f"截图_{time.strftime('%Y%m%d_%H%M%S')}",
                    filetypes=[
                        ("PNG图片", ".png"),
                        ("JPG图片", ".jpg"),
                        ("JPEG图片", ".jpeg"),
                        ("BMP图片", ".bmp")
                    ]
                )
                
                if fileName:
                    ext = fileName.lower().split('.')[-1]
                    format_map = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'bmp': 'BMP'}
                    img_format = format_map.get(ext, 'PNG')
                    
                    if img_format == 'JPEG':
                        image = image.convert('RGB')
                    
                    image.save(fileName, img_format)
                    print(f"截图已保存: {fileName}")
                    
            except Exception as e:
                print(f"保存截图失败: {e}")
            finally:
                self._cleanup_and_exit()

        def _cleanup_and_exit(self):
            """清理资源并退出"""
            try:
                if hasattr(self, 'image') and self.image:
                    self.image.close()
                if hasattr(self, 'masked_image') and self.masked_image:
                    self.masked_image.close()
                if hasattr(self, 'original_image') and self.original_image:
                    self.original_image.close()
            except:
                pass
            try:
                self.top.destroy()
            except:
                pass

    class ToolTip:
        def __init__(self, wdgt, msg=None, delay=1, follow=True, **kwargs):
            self.wdgt = wdgt
            self.parent = self.wdgt.master
            self.delay = delay
            self.follow = follow
            self.visible = False
            
            # 创建tooltip窗口 - 现代化样式
            self.tooltip = tk.Toplevel(self.parent, bg=Theme.BORDER, padx=0, pady=0)
            self.tooltip.withdraw()
            self.tooltip.overrideredirect(True)
            self.tooltip.attributes('-topmost', True)
            
            # 内部框架 - 圆角效果
            self.inner_frame = tk.Frame(self.tooltip, bg=Theme.BG_CARD, padx=8, pady=5)
            self.inner_frame.grid(sticky='nsew')
            
            # 消息文本 - 使用主题字体和颜色
            font = kwargs.get('font', ('微软雅黑', 10))
            self.msg = tk.Message(self.inner_frame, text=msg, aspect=1000,
                                  bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                                  font=font, width=200)
            self.msg.grid()
            
            self.wdgt.bind('<Enter>', self.on_enter, '+')
            self.wdgt.bind('<Leave>', self.on_leave, '+')
            self.wdgt.bind('<Motion>', self.on_motion, '+')

        def on_enter(self, event=None):
            self.visible = True
            x = self.wdgt.winfo_pointerx() + 10
            y = self.wdgt.winfo_pointery() + 10
            self.tooltip.geometry('+%i+%i' % (x, y))
            self.tooltip.deiconify()
            self.tooltip.lift()

        def on_motion(self, event):
            if self.visible and self.follow:
                self.tooltip.geometry('+%i+%i' % (event.x_root + 10, event.y_root + 10))

        def on_leave(self, event=None):
            self.visible = False
            self.tooltip.withdraw()
    
    class OnOff:
        def __init__(
            self,
            master,
            pos: tuple,
            state: bool = False,
            fg="#5a5a5a",
            bg="#ededed",
            activefg="#575757",
            activebg="#e5e5e5",
            onactivefg="#ffffff",
            onactivebg="#1975c5",
            onfg="#FFFFFF",
            onbg="#3041d8",
            bd: int = 40,
            command=None,
        ):
            self.master = master
            self.fg = fg
            self.bg = bg
            self.activefg = activefg
            self.activebg = activebg
            self.onactivefg = onactivefg
            self.onactivebg = onactivebg
            self.onfg = onfg
            self.onbg = onbg
            self.bd = bd
            self.command = command
            
            self.canvas = tk.Canvas(master, width=bd*2, height=bd, bg=master.cget("bg"), highlightthickness=0)
            self.canvas.place(x=pos[0], y=pos[1])
            
            # 根据初始状态设置颜色
            if state:
                initial_bg = onbg
                initial_fg = onfg
                initial_outline = onbg  # 开启状态下outline与背景同色
            else:
                initial_bg = bg
                initial_fg = fg
                initial_outline = fg  # 关闭状态下outline与前景同色
            
            self.back = self.canvas.create_text(
                (0, 0),
                text="\uec11",
                font=f"{{Segoe Fluent Icons}} {bd}",
                fill=initial_bg,
                anchor="nw",
            )
            
            self.outline = self.canvas.create_text(
                (0, 0),
                text="\uec12",
                font=f"{{Segoe Fluent Icons}} {bd}",
                fill=initial_outline,
                anchor="nw",
            )
            
            bbox = self.canvas.bbox(self.outline)
            # 滑块初始位置固定（关闭状态位置）
            self.state = self.canvas.create_text(
                (bbox[0] + (bd / 10 * 3) + 1, (bbox[1] + bbox[3]) / 2 - 1),
                text="\uf127",
                font=f"{{Segoe Fluent Icons}} {int(bd / 4)}",
                fill=initial_fg,
            )
            # 如果初始状态为开启，移动滑块到右侧
            if state:
                self.canvas.move(self.state, int(bd / 4 * 3), 0)
            
            self.nowstate = state
            
            self.canvas.tag_bind(self.back, "<Button-1>", self._on_click)
            self.canvas.tag_bind(self.back, "<Enter>", self._mouse_in)
            self.canvas.tag_bind(self.back, "<Leave>", self._mouse_out)
            self.canvas.tag_bind(self.outline, "<Button-1>", self._on_click)
            self.canvas.tag_bind(self.outline, "<Enter>", self._mouse_in)
            self.canvas.tag_bind(self.outline, "<Leave>", self._mouse_out)
            self.canvas.tag_bind(self.state, "<Button-1>", self._on_click)
            self.canvas.tag_bind(self.state, "<Enter>", self._mouse_in)
            self.canvas.tag_bind(self.state, "<Leave>", self._mouse_out)
        
        def _on(self):
            self.nowstate = True
            if self.command:
                self.command(True)
        
        def _off(self):
            self.nowstate = False
            if self.command:
                self.command(False)
        
        def _left30(self):
            for i in range(int(self.bd / 4 * 3)):
                self.canvas.after(i * 5, lambda: self.canvas.move(self.state, -1, 0))
        
        def _right30(self):
            for i in range(int(self.bd / 4 * 3)):
                self.canvas.after(i * 5, lambda: self.canvas.move(self.state, 1, 0))
        
        def _on_click(self, event):
            if not self.nowstate:
                self.canvas.itemconfig(self.state, fill=self.onfg)
                self._right30()
                self.canvas.itemconfig(self.back, fill=self.onbg)
                self.canvas.itemconfig(self.outline, fill=self.onbg)
                self._on()
            else:
                self.canvas.itemconfig(self.state, fill=self.fg)
                self._left30()
                self.canvas.itemconfig(self.back, fill=self.bg)
                self.canvas.itemconfig(self.outline, fill=self.fg)
                self._off()
        
        def _mouse_in(self, event):
            if self.nowstate:
                self.canvas.itemconfig(self.state, fill=self.onactivefg)
                self.canvas.itemconfig(self.back, fill=self.onactivebg)
                self.canvas.itemconfig(self.outline, fill=self.onactivebg)
            else:
                self.canvas.itemconfig(self.state, fill=self.activefg)
                self.canvas.itemconfig(self.back, fill=self.activebg)
                self.canvas.itemconfig(self.outline, fill=self.activefg)
        
        def _mouse_out(self, event):
            if self.nowstate:
                self.canvas.itemconfig(self.state, fill=self.onfg)
                self.canvas.itemconfig(self.back, fill=self.onbg)
                self.canvas.itemconfig(self.outline, fill=self.onbg)
            else:
                self.canvas.itemconfig(self.state, fill=self.fg)
                self.canvas.itemconfig(self.back, fill=self.bg)
                self.canvas.itemconfig(self.outline, fill=self.fg)
        
        def get_state(self):
            return self.nowstate
        
        def set_state(self, state):
            if state != self.nowstate:
                if state:
                    self.canvas.itemconfig(self.state, fill=self.onfg)
                    self._right30()
                    self.canvas.itemconfig(self.back, fill=self.onbg)
                    self.canvas.itemconfig(self.outline, fill=self.onbg)
                    self._on()
                else:
                    self.canvas.itemconfig(self.state, fill=self.fg)
                    self._left30()
                    self.canvas.itemconfig(self.back, fill=self.bg)
                    self.canvas.itemconfig(self.outline, fill=self.fg)
                    self._off() 

    def recv():
        global handle_time, _my_uid
        while True:
            try:
                time.sleep(0.1)
                head = recv_all(connection, 1024)
                head = json.loads(head.decode())
                print("head = ", head)
                msg = recv_all(connection, head["size"])
                msg = pickle.loads(msg)
                print("message = ", msg)
                que.append((head, msg))
            except ConnectionAbortedError:
                break
            except ConnectionResetError:
                break

    def handle():
        global onlines, _my_uid
        while True:
            try:
                time.sleep(0.1)
                if not que:
                    continue
                head, msg = que[0]
                if head["type"] in ("text", "group_text", "group_create", "online_users", "update"):
                    que.pop()
                    if head["type"] == "text":
                        txt = msg[1]
                        interface = None
                        sender_idx = -1
                        sender_name = ""
                        sender_uid = 0
                        if msg[3] == "robot":
                            interface = onlines[0][1]
                            sender_idx = 0
                            sender_name = "🤖 deepseek助手"
                        else:
                            for i, user in enumerate(onlines):
                                if isinstance(user[0], (list, tuple)) and len(user[0]) > 1 and user[0][1] == msg[3]:
                                    interface = user[1]
                                    sender_idx = i
                                    sender_name = user[0][0]
                                    sender_uid = user[0][2] if len(user[0]) > 2 else None
                                    break
                        lines = split_for_display(txt)
                        font_obj = tkfont.Font(font=("font/simsun.ttf", 15))
                        max_w = max(font_obj.measure(line) for line in lines) if lines else 100
                        line_height = 18
                        msg_h = len(lines) * line_height + 20 + 10  # +10 为用户名区域
                        print(interface)
                        canvas_w = interface.canvas.winfo_width()
                        # 获取发送者头像
                        avatar_img = None
                        if sender_idx > 0 and isinstance(onlines[sender_idx][0], (list, tuple)) and len(onlines[sender_idx][0]) > 1:
                            avatar_img = interface.avatar_cache.get(sender_uid) if sender_uid else None
                            print(f"[DIAG] 私聊头像: sender_name={sender_name}, sender_uid={sender_uid}, 缓存命中={avatar_img is not None}")
                        else:
                            print(f"[DIAG] 私聊头像跳过: sender_idx={sender_idx}, sender_uid={sender_uid}")
                        interface.draw_msg(20,
                                           int(max_w) + 24,
                                           msg_h,
                                           "white",
                                           lines, point="left", radius=25,
                                           font=("font/simsun.ttf", 15),
                                           avatar_img=avatar_img,
                                           username=sender_name,
                                           sender_uid=sender_uid)
                        # 在更新 scrollregion 前先记录是否已在底部
                        was_at_bottom = interface.canvas.yview()[1] >= 0.98
                        interface.canvas.config(scrollregion=(0, 0, canvas_w, interface.y))
                        if was_at_bottom:
                            AnimationHelper.smooth_scroll_canvas(interface.canvas, 1.0, duration=200)
                        # 来信未读红点提示
                        if sender_idx >= 0 and sender_idx != user_list_canvas.get_selection() and msg[3] != "robot":
                            user_list_canvas.set_unread(msg[3])
                    elif head["type"] == "group_text":
                        # group_text: [type, txt, sender_name, sender_addr, group_name]
                        txt = msg[1]
                        sender_name = msg[2]
                        sender_addr = msg[3]
                        group_name = msg[4] if len(msg) > 4 else "群聊"
                        lines = split_for_display(txt)
                        font_obj = tkfont.Font(font=("font/simsun.ttf", 15))
                        max_w = max(font_obj.measure(line) for line in lines) if lines else 100
                        line_height = 18
                        msg_h = len(lines) * line_height + 20 + 10  # +10 为用户名区域
                        # 查找群组 interface
                        grp_interface = None
                        grp_addr = None
                        for grp in groups:
                            if grp['name'] == group_name:
                                grp_interface = grp['interface']
                                grp_addr = grp['addr']
                                break
                        if grp_interface is None:
                            continue  # 群组不存在则忽略
                        canvas_w = grp_interface.canvas.winfo_width() or 400
                        # 获取发送者头像
                        avatar_img = None
                        sender_uid_val = None
                        for user in onlines:
                            if isinstance(user[0], (list, tuple)) and len(user[0]) > 1 and user[0][1] == sender_addr:
                                sender_uid_val = user[0][2] if len(user[0]) > 2 else None
                                avatar_img = user[1].avatar_cache.get(sender_uid_val) if sender_uid_val else None
                                print(f"[DIAG] 群聊头像: sender_name={sender_name}, sender_uid={sender_uid_val}, 缓存命中={avatar_img is not None}")
                                break
                        grp_interface.draw_msg(20,
                                               int(max_w) + 24,
                                               msg_h,
                                               "white",
                                               lines, point="left", radius=25,
                                               font=("font/simsun.ttf", 15),
                                               avatar_img=avatar_img,
                                               username=sender_name,
                                               sender_uid=sender_uid_val)
                        was_at_bottom = grp_interface.canvas.yview()[1] >= 0.98
                        grp_interface.canvas.config(scrollregion=(0, 0, canvas_w, grp_interface.y))
                        if was_at_bottom:
                            AnimationHelper.smooth_scroll_canvas(grp_interface.canvas, 1.0, duration=200)
                        # 群组未读红点
                        selected_item = user_list_canvas.get_selected_item()
                        if not (selected_item and selected_item.get('type') == 'group' and selected_item.get('name') == group_name):
                            idx = -1
                            for i, item in enumerate(user_list_canvas.items):
                                if item.get('type') == 'group' and item.get('name') == group_name:
                                    idx = i
                                    break
                            if idx >= 0:
                                user_list_canvas.set_unread(grp_addr)

                    elif head["type"] == "group_create":
                        # group_create: [type, group_name, members_list]
                        grp_name = msg[1]
                        members = msg[2]
                        # 避免重复创建
                        existing = None
                        for grp in groups:
                            if grp['name'] == grp_name:
                                existing = grp
                                break
                        if existing is None:
                            grp_addr = f'#group_{len(groups)}_{time.time()}'
                            grp_canvas = tk.Canvas(user_frame, bg=Theme.BG_LIGHT, confine=True, highlightthickness=0)
                            grp_scrollbar = tk.Scrollbar(user_frame, command=grp_canvas.yview, bg=Theme.BG_CARD,
                                                         troughcolor=Theme.BG_LIGHT, width=8,
                                                         activebackground=Theme.PRIMARY,
                                                         highlightbackground=Theme.BORDER)
                            grp_interface = DialogueInterface(grp_canvas, grp_scrollbar)
                            groups.append({
                                'name': grp_name,
                                'addr': grp_addr,
                                'members': members,
                                'interface': grp_interface,
                            })
                        # 刷新用户列表
                        rebuild_list = [("🤖 deepseek助手", "robot", 0)]
                        for user in onlines:
                            if user[0] != ("robot", None) and isinstance(user[0], (list, tuple)) and len(user[0]) > 1:
                                uid_val_grp = user[0][2] if len(user[0]) > 2 else None
                                rebuild_list.append((user[0][0], user[0][1], uid_val_grp))
                        user_list_canvas.rebuild_with_groups(rebuild_list, groups)

                    elif head["type"] == "online_users":
                        # msg: list of [(name, addr, icon_b64, uid), ...] entries
                        users.clear()
                        users.append([("robot", None)])
                        new_onlines = []
                        my_addr = connection.getsockname()
                        for x in msg:
                            name, addr = x[0], x[1]
                            icon_b64 = x[2] if len(x) > 2 else ""
                            uid_val = x[3] if len(x) > 3 else 0
                            # 记录自己的 UID
                            if addr == my_addr and uid_val:
                                _my_uid = uid_val
                                print(f"[DIAG] 设置 _my_uid = {uid_val} (name={name})")
                            found = None
                            for old_user in onlines:
                                if (isinstance(old_user[0], (list, tuple)) and len(old_user[0]) > 1
                                        and old_user[0][1] == addr):
                                    found = old_user
                                    # 更新历史用户名（如果改了名）
                                    if found[0][0] != name:
                                        for g in onlines:
                                            if isinstance(g[0], (list, tuple)) and len(g[0]) > 1:
                                                g[1].update_username_text(uid_val, name)
                                        for g in groups:
                                            g['interface'].update_username_text(uid_val, name)
                                    found[0] = [name, addr, uid_val]
                                    break
                            if found:
                                new_onlines.append(found)
                            else:
                                canvas = tk.Canvas(user_frame, bg=Theme.BG_LIGHT, confine=True, highlightthickness=0)
                                scrollbar = tk.Scrollbar(user_frame, command=canvas.yview, bg=Theme.BG_CARD,
                                                        troughcolor=Theme.BG_LIGHT, width=8,
                                                        activebackground=Theme.PRIMARY,
                                                        highlightbackground=Theme.BORDER)
                                interface = DialogueInterface(canvas, scrollbar)
                                new_onlines.append([[name, addr, uid_val], interface])
                            users.append([(name, addr)])
                            # 加载头像到用户列表和所有聊天界面
                            print(f"[DIAG] online_users: name={name}, icon_b64非空={bool(icon_b64)}, 长度={len(icon_b64)}, uid={uid_val}")
                            if icon_b64:
                                user_list_canvas.load_avatar(uid_val, icon_b64)
                                for ol in new_onlines:
                                    ol[1].set_message_avatar(uid_val, icon_b64)
                                for grp in groups:
                                    grp['interface'].set_message_avatar(uid_val, icon_b64)
                        # 保留robot
                        robot_found = None
                        for old_user in onlines:
                            if old_user[0] == ("robot", None) or old_user[0] == "robot":
                                robot_found = old_user
                                robot_found[0] = ("robot", None)
                                break
                        if robot_found:
                            new_onlines.insert(0, robot_found)
                        else:
                            canvas = tk.Canvas(user_frame, bg=Theme.BG_LIGHT, confine=True, highlightthickness=0)
                            scrollbar = tk.Scrollbar(user_frame, command=canvas.yview, bg=Theme.BG_CARD,
                                                    troughcolor=Theme.BG_LIGHT, width=8,
                                                    activebackground=Theme.PRIMARY,
                                                    highlightbackground=Theme.BORDER)
                            new_onlines.insert(0, [("robot", None), DialogueInterface(canvas, scrollbar)])
                        onlines = new_onlines
                        print(onlines)
                        rebuild_list = [("🤖 deepseek助手", "robot", 0)]
                        for x in msg:
                            rebuild_list.append((x[0], x[1], x[3] if len(x) > 3 else 0))
                        user_list_canvas.rebuild_with_groups(rebuild_list, groups)
                    elif head["type"] == "update":
                        # msg: list of (name, (ip, port), icon_b64, uid) tuples from server
                        users.clear()
                        users.append([("robot", None)])
                        my_addr = connection.getsockname()
                        for x in msg:
                            name, addr = x[0], x[1]
                            icon_b64 = x[2] if len(x) > 2 else ""
                            uid_val = x[3] if len(x) > 3 else 0
                            if addr == my_addr and uid_val:
                                _my_uid = uid_val
                                print(f"[DIAG] update 设置 _my_uid = {uid_val} (name={name})")
                            for i in range(1, len(onlines)):
                                if (isinstance(onlines[i][0], (list, tuple)) and len(onlines[i][0]) > 1
                                        and onlines[i][0][1] == addr):
                                    onlines[i][0] = [name, addr, uid_val]
                                    # 更新该用户在所有聊天界面中的历史用户名
                                    for g in onlines:
                                        if isinstance(g[0], (list, tuple)) and len(g[0]) > 1:
                                            g[1].update_username_text(uid_val, name)
                                    for g in groups:
                                        g['interface'].update_username_text(uid_val, name)
                                    break
                            users.append([(name, addr)])
                            if icon_b64:
                                user_list_canvas.load_avatar(uid_val, icon_b64)
                                for ol in onlines:
                                    ol[1].set_message_avatar(uid_val, icon_b64)
                                for grp in groups:
                                    grp['interface'].set_message_avatar(uid_val, icon_b64)
                        rebuild_list = [("🤖 deepseek助手", "robot", 0)]
                        for entry in msg:
                            rebuild_list.append((entry[0], entry[1], entry[3] if len(entry) > 3 else 0))
                        user_list_canvas.rebuild_with_groups(rebuild_list, groups)
                else:
                    continue

            except ConnectionAbortedError:
                break
            except ConnectionResetError:
                break

    def send_text(txt, color):
        global onlines, think, groups, _my_uid
        sel = user_list_canvas.get_selection()
        if not txt.isspace() and sel >= 0:
            item = user_list_canvas.get_selected_item()
            is_group = (item and item.get('type') == 'group')
            
            raw_txt = txt[0:-1]
            print(users)
            # 发送者（自己）头像：查找本用户在所有 interface 缓存中的头像
            sender_avatar = None
            sender_avatar_size = onlines[0][1].AVATAR_SIZE if onlines else 28
            if _my_uid:
                for u in onlines:
                    if isinstance(u[0], (list, tuple)) and len(u[0]) > 2 and u[0][2] == _my_uid:
                        sender_avatar = u[1].avatar_cache.get(_my_uid)
                        if sender_avatar is not None:
                            break
            print(f"[DIAG] send_text 发送者头像: _my_uid={_my_uid}, 找到={sender_avatar is not None}")
            # 右侧布局：20px边距 + 头像40px + 20px间距 + 气泡 → 向左
            right_margin = 20 + sender_avatar_size + 20 if sender_avatar is not None else 20
            if sel == 0:
                send_pickle(connection,
                    ["text", raw_txt, "robot", connection.getsockname(),think])
                lines = split_for_display(raw_txt)
                font_obj = tkfont.Font(font=("font/simsun.ttf", 15))
                max_w = max(font_obj.measure(line) for line in lines) if lines else 100
                line_height = 18
                msg_h = len(lines) * line_height + 20
                canvas_w = onlines[0][1].canvas.winfo_width()
                onlines[0][1].draw_msg(
                    canvas_w - right_margin - int(max_w) - 24,
                    int(max_w) + 24,
                    msg_h,
                    color, lines, point="right", radius=25,
                    font=("font/simsun.ttf", 15),
                    avatar_img=sender_avatar)
                onlines[0][1].canvas.config(scrollregion=(0, 0, canvas_w, onlines[0][1].y))
                AnimationHelper.smooth_scroll_canvas(onlines[0][1].canvas, 1.0, duration=200)
            elif is_group:
                # 群聊：发送给所有群成员
                members = item.get('members', [])
                if not members:
                    text.delete(1.0, tk.END)
                    return "break"
                target_list = [list(m) if isinstance(m, (list, tuple)) else [m, None] for m in members]
                send_pickle(connection,
                    ["group_text", raw_txt, target_list, connection.getsockname(), item.get('name', '群聊')])
                lines = split_for_display(raw_txt)
                font_obj = tkfont.Font(font=("font/simsun.ttf", 15))
                max_w = max(font_obj.measure(line) for line in lines) if lines else 100
                line_height = 18
                msg_h = len(lines) * line_height + 20
                # 找到群组对应的 interface
                grp_addr = item.get('addr', '')
                for grp in groups:
                    if grp.get('addr') == grp_addr:
                        canvas_w = grp['interface'].canvas.winfo_width()
                        # 群聊中从 onlines 查找自己头像（群组 interface 刚创建时可能无缓存）
                        grp_sender_avatar = None
                        if _my_uid:
                            for u_grp in onlines:
                                if isinstance(u_grp[0], (list, tuple)) and len(u_grp[0]) > 2 and u_grp[0][2] == _my_uid:
                                    grp_sender_avatar = u_grp[1].avatar_cache.get(_my_uid)
                                    break
                        grp_right_margin = 20 + sender_avatar_size + 20 if grp_sender_avatar is not None else 20
                        grp['interface'].draw_msg(
                            canvas_w - grp_right_margin - int(max_w) - 24,
                            int(max_w) + 24,
                            msg_h,
                            color, lines, point="right", radius=25,
                            font=("font/simsun.ttf", 15),
                            avatar_img=grp_sender_avatar)
                        grp['interface'].canvas.config(
                            scrollregion=(0, 0, canvas_w, grp['interface'].y))
                        AnimationHelper.smooth_scroll_canvas(
                            grp['interface'].canvas, 1.0, duration=200)
                        break
            else:
                send_pickle(connection,
                    ["text", raw_txt, users[sel], connection.getsockname()])
                lines = split_for_display(raw_txt)
                font_obj = tkfont.Font(font=("font/simsun.ttf", 15))
                max_w = max(font_obj.measure(line) for line in lines) if lines else 100
                line_height = 18
                msg_h = len(lines) * line_height + 20
                canvas_w = onlines[sel][1].canvas.winfo_width()
                onlines[sel][1].draw_msg(
                    canvas_w - right_margin - int(max_w) - 24,
                    int(max_w) + 24,
                    msg_h,
                    color, lines, point="right", radius=25,
                    font=("font/simsun.ttf", 15),
                    avatar_img=sender_avatar)
                onlines[sel][1].canvas.config(
                    scrollregion=(0, 0, canvas_w, onlines[sel][1].y))
                AnimationHelper.smooth_scroll_canvas(
                    onlines[sel][1].canvas, 1.0, duration=200)
        text.delete(1.0, tk.END)
        return "break"

    def split_str(string, max_width, font):
        """使用 tkFont.measure() 精确测量文本宽度进行截断"""
        parts = []
        buffer = []

        for char in string:
            if buffer and font.measure(''.join(buffer) + char) > max_width:
                parts.append(''.join(buffer))
                buffer = [char]
            else:
                buffer.append(char)
        if buffer:
            parts.append(''.join(buffer))

        return '\n'.join(parts)

    def split_for_display(text, max_px=None, font=None):
        """将文本按行分割，并将超长行用 split_str 截断，返回行列表"""
        if font is None:
            font = tkfont.Font(font=("font/simsun.ttf", 15))
        if max_px is None:
            max_px = font.measure("A" * 30)
        lines = []
        for line in text.split("\n"):
            if font.measure(line) > max_px:
                lines.extend(split_str(line, max_px, font).split("\n"))
            else:
                lines.append(line)
        return lines

    def choose_user(index):
        global onlines, think, groups
        if index < 0:
            return
        # 隐藏所有用户和群组界面
        for user in onlines:
            user[1].canvas.place_forget()
            user[1].scrollbar.pack_forget()
        for grp in groups:
            grp['interface'].canvas.place_forget()
            grp['interface'].scrollbar.pack_forget()
        # 删除深度思考标签和开关（TinUI canvas items）
        nonlocal think_label_uid, think_onoff_uid
        if think_label_uid:
            text_frame_ui.delete(think_label_uid)
            think_label_uid = None
        if think_onoff_uid:
            text_frame_ui.delete(think_onoff_uid)
            think_onoff_uid = None
        
        item = user_list_canvas.get_selected_item()
        is_group = (item and item.get('type') == 'group')
        
        if is_group:
            # 群聊界面
            grp_addr = item.get('addr', '')
            for grp in groups:
                if grp.get('addr') == grp_addr:
                    canvas = grp['interface'].canvas
                    canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
                    grp['interface'].scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
                    user_frame.place(relx=0.2, y=40, relwidth=0.8, height=-120, relheight=1.0)
                    canvas.config(scrollregion=(0, 0, 0, grp['interface'].y))
                    canvas.config(yscrollcommand=grp['interface'].scrollbar.set)
                    canvas.bind("<MouseWheel>",
                                lambda event: grp['interface'].canvas.yview_scroll(
                                    int(-event.delta / 120),
                                    "units"))
                    break
        elif index == 0:
            canvas = onlines[0][1].canvas
            canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            onlines[0][1].scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            user_frame.place(relx=0.2, y=40, relwidth=0.8, height=-120, relheight=1.0)
            # 使用 TinUI 绘制深度思考标签和开关
            think_label_uid = text_frame_ui.add_label((172, 12), "深度思考：",
                font=("微软雅黑", 10), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD, outline=Theme.BG_CARD)
            def on_change(state):
                global think
                think = state
            think_onoff_uid = text_frame_ui.add_onoff((245, 8), state=think, bd=30, command=on_change)
            canvas.config(scrollregion=(0, 0, 0, onlines[0][1].y))
            canvas.config(yscrollcommand=onlines[0][1].scrollbar.set)
            canvas.bind("<MouseWheel>",
                        lambda event: onlines[0][1].canvas.yview_scroll(
                            int(-event.delta / 120),
                            "units"))
        else:
            canvas = onlines[index][1].canvas
            canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)
            onlines[index][1].scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            user_frame.place(relx=0.2, y=40, relwidth=0.8, height=-120, relheight=1.0)
            canvas.config(scrollregion=(0, 0, 0, onlines[index][1].y))
            canvas.config(yscrollcommand=onlines[index][1].scrollbar.set)
            canvas.bind("<MouseWheel>",
                        lambda event: onlines[index][1].canvas.yview_scroll(
                            int(-event.delta / 120),
                            "units"))
        top_frame.place(relx=0.2, y=0, relwidth=0.8, height=40)
        top_separator.place(relx=0.2, y=40, relwidth=0.8, height=1)

    def create_group():
        """组群对话框 - TinUI版本"""
        global groups
        # 获取当前在线用户（除自己外）
        available = []
        my_addr = connection.getsockname()
        for i in range(1, len(onlines)):
            if isinstance(onlines[i][0], (list, tuple)) and len(onlines[i][0]) > 1:
                # 排除自己
                if onlines[i][0][1] != my_addr:
                    available.append(onlines[i][0])
        
        if len(available) < 2:
            tk.messagebox.showinfo("提示", "需要至少2个在线用户才能创建群组！")
            return
        
        grp_win = tk.Toplevel(root)
        grp_win.transient(root)
        grp_win.geometry(f"380x{min(200 + len(available) * 30, 500)}+{int(grp_win.winfo_screenwidth() / 2 - 190)}+{int(grp_win.winfo_screenheight() / 2 - 200)}")
        grp_win.iconbitmap("icon/icon.ico")
        grp_win.title("创建群组")
        grp_win.configure(bg=Theme.BG_LIGHT)
        grp_win.resizable(False, False)
        
        # 使用 TinUI 绘制群组创建界面
        grp_ui = BasicTinUI(grp_win, bg=Theme.BG_LIGHT, width=380, height=min(200 + len(available) * 30, 500))
        grp_ui.pack(fill=tk.BOTH, expand=True)
        
        # 群组名称
        grp_ui.add_label((20, 18), "群组名称：", font=('微软雅黑', 12), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_LIGHT, outline=Theme.BG_LIGHT)
        grp_entry, grp_entry_funcs, grp_entry_uid = grp_ui.add_entry((100, 15), 250, "", font=('微软雅黑', 12),
            fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, onbg=Theme.BG_INPUT, onoutline=Theme.BORDER)
        
        # 成员选择标签
        grp_ui.add_label((20, 58), "选择成员（按住Ctrl多选）：", font=('微软雅黑', 12), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_LIGHT, outline=Theme.BG_LIGHT)
        
        # 多选Listbox（保留tkinter原生，TinUI不支持多选）
        lb = tk.Listbox(grp_win, selectmode=tk.MULTIPLE,
                        font=('微软雅黑', 11), bg=Theme.BG_CARD,
                        fg=Theme.TEXT_PRIMARY, bd=0,
                        highlightthickness=1, highlightbackground=Theme.BORDER,
                        selectbackground=Theme.PRIMARY_LIGHT,
                        selectforeground=Theme.TEXT_PRIMARY,
                        activestyle='none')
        listbox_height = min(len(available) * 30 + 5, 280)
        lb.place(x=20, y=85, width=340, height=listbox_height)
        
        for i, entry in enumerate(available):
            name = entry[0] if isinstance(entry, (list, tuple)) else str(entry)
            lb.insert(tk.END, name)
            lb.selection_set(i)  # 默认全选
        
        def confirm_group():
            grp_name = grp_entry_funcs.get().strip()
            if not grp_name:
                tk.messagebox.showwarning("提示", "请输入群组名称！")
                return
            selections = lb.curselection()
            selected = [available[i] for i in selections]
            if len(selected) + 1 < 3:  # 自己 + 选中的成员 >= 3
                tk.messagebox.showwarning("提示", f"群聊至少需要3人（当前自己+{len(selected)}位成员），请至少选择2位成员！")
                return
            # 发送 group_create 到服务器，由服务器广播给所有用户
            send_pickle(connection, ["group_create", grp_name, selected])
            grp_win.destroy()
            tk.messagebox.showinfo("提示", f'群组"{grp_name}"创建请求已发送！')
        
        # 底部按钮（使用 TinUI）
        btn_y = 85 + listbox_height + 10
        grp_ui.add_button((380 - 120, btn_y), "创建群组",
            font=('微软雅黑', 11, 'bold'), fg=Theme.TEXT_WHITE, bg=Theme.PRIMARY, line=Theme.PRIMARY,
            activefg=Theme.TEXT_WHITE, activebg=Theme.HOVER_DARK, activeline=Theme.HOVER_DARK,
            command=lambda event: confirm_group())
        grp_ui.add_button((380 - 220, btn_y), "取消",
            font=('微软雅黑', 11), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, line=Theme.BG_INPUT,
            activefg=Theme.TEXT_PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
            command=lambda event: grp_win.destroy())
        
        grp_win.mainloop()

    def update(*args):
        def send_update_msg(name="", pwd=""):
            global _name, _pwd, _cropped_icon_b64
            try:
                if _cropped_icon_b64:
                    icon_data = _cropped_icon_b64.encode()
                    _cropped_icon_b64 = ""
                elif icon_path:
                    with open(icon_path, "rb") as img:
                        icon_data = base64.b64encode(img.read())
                else:
                    icon_data = b""
                send_pickle(connection, ["update", (_name, _pwd), (name, pwd, icon_data)])
                while True:
                    try:
                        head, echo_msg = que.pop()
                        break
                    except IndexError:
                        continue
                print(f"update_echo:{echo_msg}")
                if head["type"] == "update_echo":
                    if echo_msg == "Update Success":
                        for index, item in enumerate(users):
                            if (_name, connection.getsockname()) in item:
                                users[index].remove((_name, connection.getsockname()))
                                users[index].append((name, connection.getsockname()))
                        for index, item in enumerate(onlines):
                            if isinstance(item[0], (list, tuple)) and item[0][0] == _name:
                                old_uid = item[0][2] if len(item[0]) > 2 else None
                                item[0] = [name, item[0][1], old_uid]
                                break
                        _name = name
                        _pwd = pwd
                        rebuild_list = [("🤖 deepseek助手", "robot", 0)]
                        for user in onlines:
                            if user[0] != ("robot", None):
                                uid_val_echo = user[0][2] if len(user[0]) > 2 else None
                                rebuild_list.append((user[0][0], user[0][1], uid_val_echo))
                        user_list_canvas.rebuild_with_groups(rebuild_list, groups)
                        tk.messagebox.showinfo("修改成功", "修改成功！")
                        update_win.destroy()
                    elif echo_msg == "Repeated Update":
                        tk.messagebox.showinfo("修改失败", "当前用户已存在，请重试！")
                    else:
                        tk.messagebox.showerror("修改失败", "修改失败，请稍后再试！")
            except FileNotFoundError:
                tk.messagebox.showerror("错误", f"文件{icon_path}不存在，请确认文件是否被删除！")
            except PermissionError:
                tk.messagebox.showerror("错误", f"没有权限对文件{icon_path}进行操作！")
            except ValueError:
                pass

        def choose_icon_for_update():
            """修改信息对话框选择头像（TinUI版本）"""
            global icon_path, _cropped_icon_b64
            icon_path = tk.filedialog.askopenfilename(filetypes=[("图片", ("*.png", "*.jpg", "*.gif", "*.ico")), ])
            if icon_path:
                upd_icon_funcs.normal()  # 启用
                upd_icon_funcs.delete()  # 清空
                upd_icon_funcs.insert(0, icon_path)  # 插入路径
                upd_icon_funcs.disable()  # 禁用
                # 选完文件立即裁剪
                crop = ImageCrop(icon_path)
                cropped = crop.get_result()
                if cropped is not None:
                    buf = io.BytesIO()
                    cropped.save(buf, format='PNG')
                    _cropped_icon_b64 = base64.b64encode(buf.getvalue()).decode()
                    buf.close()

        update_win = tk.Toplevel(root)
        update_win.transient(root)
        update_win.geometry(
            f"320x240+{int(update_win.winfo_screenwidth() / 2 - 160)}+{int(update_win.winfo_screenheight() / 2 - 120)}")
        update_win.iconbitmap("icon/icon.ico")
        update_win.title("修改信息")
        update_win.configure(bg="white")
        update_win.resizable(False, False)

        # 使用 TinUI 绘制修改信息界面
        upd_ui = BasicTinUI(update_win, bg="white", width=320, height=240)
        upd_ui.pack(fill=tk.BOTH, expand=True)

        upd_ui.add_title((160, 18), "修改信息", font="font/simsun.ttf", size=0, fg="black", anchor="center")
        
        upd_ui.add_label((10, 75), "用户名：", font=("font/simsun.ttf", 15), fg="black", bg="white", outline="white")
        upd_user, upd_user_funcs, upd_user_uid = upd_ui.add_entry((85, 73), 180, "", font=("font/simsun.ttf", 15),
            fg="black", bg="#D4D0C8", onbg="#D4D0C8", onoutline="grey")
        
        upd_ui.add_label((10, 110), "密  码：", font=("font/simsun.ttf", 15), fg="black", bg="white", outline="white")
        upd_pwd, upd_pwd_funcs, upd_pwd_uid = upd_ui.add_entry((85, 108), 180, "", font=("font/simsun.ttf", 15),
            fg="black", bg="#D4D0C8", onbg="#D4D0C8", onoutline="grey")
        
        upd_ui.add_label((10, 145), "头  像：", font=("font/simsun.ttf", 15), fg="black", bg="white", outline="white")
        upd_icon, upd_icon_funcs, upd_icon_uid = upd_ui.add_entry((85, 143), 140, "", font=("font/simsun.ttf", 15),
            fg="black", bg="#D4D0C8", onbg="#D4D0C8", onoutline="grey")
        upd_icon_funcs.disable()  # 初始禁用
        
        upd_ui.add_button((240, 143), "浏览\u2026", font=("font/simsun.ttf", 10),
            fg="black", bg="#D4D0C8", line="#D4D0C8",
            activefg="black", activebg="#c0c0c0", activeline="#c0c0c0",
            command=lambda event: choose_icon_for_update())
        
        upd_ui.add_button((50, 178), "修改", font=("font/simsun.ttf", 15),
            fg="black", bg="#D4D0C8", line="#D4D0C8",
            activefg="black", activebg="#c0c0c0", activeline="#c0c0c0",
            command=lambda event: send_update_msg(upd_user_funcs.get(), upd_pwd_funcs.get()))
        upd_ui.add_button((175, 178), "取消", font=("font/simsun.ttf", 15),
            fg="black", bg="#D4D0C8", line="#D4D0C8",
            activefg="black", activebg="#c0c0c0", activeline="#c0c0c0",
            command=lambda event: update_win.destroy())
        update_win.mainloop()

    def delete(*args):
        global _name
        answer = tk.messagebox.askyesno(title="是否继续", message="注销将不可逆，是否仍要注销？")
        if answer:
            send_pickle(connection, ["delete", _name, None])
            while True:
                try:
                    head, echo_msg = que.pop()
                    break
                except IndexError:
                    continue
            print(f"delete_echo:{echo_msg}")
            if head["type"] == "delete_echo":
                if echo_msg == "Delete Success":
                    tk.messagebox.showinfo("注销成功", "注销成功！")
                    root.destroy()
                    sys.exit(0)
                else:
                    tk.messagebox.showerror("注销失败", "注销失败，请稍后再试！")

    def captureScreen():
        root.state('icon')
        time.sleep(0.5)
        w = MyCapture()
        capture.wait_window(w.top)
        root.state('normal')

    def show_emoji_picker():
        """显示emoji选择器 - TinUI版本"""
        emoji_window = tk.Toplevel(root)
        emoji_window.overrideredirect(True)
        emoji_window.attributes('-topmost', True)

        # 计算位置（显示在输入框上方）
        x = text_frame.winfo_rootx() + 100
        y = text_frame.winfo_rooty() - 200
        emoji_window.geometry(f'280x180+{x}+{y}')
        emoji_window.configure(bg=Theme.BORDER)

        # emoji列表
        emojis = [
            '😊', '😄', '😂', '😅', '😍', '🤩', '😢', '😡',
            '👍', '👎', '❤️', '💔', '🎉', '🔥', '⭐', '✨',
            '💯', '😎', '🤔', '😴', '🙈', '🙉', '🙊', '💪',
            '👋', '🙏', '🤝', '💡', '📌', '⏰', '💻', '📱'
        ]

        # 使用 TinUI 绘制emoji选择器
        emoji_ui = BasicTinUI(emoji_window, bg=Theme.BG_CARD, width=280, height=180)
        emoji_ui.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        # 创建emoji按钮（网格布局）
        cols = 8
        btn_size = 30
        gap = 2
        for i, emoji in enumerate(emojis):
            row = i // cols
            col = i % cols
            px = 5 + col * (btn_size + gap)
            py = 5 + row * (btn_size + gap)
            emoji_ui.add_button((px, py), emoji,
                font=('Segoe UI Emoji', 14), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD, line=Theme.BG_CARD,
                activefg=Theme.PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
                minwidth=btn_size, command=lambda event, e=emoji: insert_emoji(e, emoji_window))

        # 点击外部关闭
        def close_on_click(event):
            if event.widget != emoji_window:
                AnimationHelper.fade_out_toplevel(emoji_window, duration=150, callback=emoji_window.destroy)

        emoji_window.bind('<FocusOut>', lambda e: AnimationHelper.fade_out_toplevel(emoji_window, duration=150, callback=emoji_window.destroy))
        root.bind('<Button-1>', close_on_click, add='+')

        # 淡入动画
        AnimationHelper.fade_in_toplevel(emoji_window, duration=200)

    def insert_emoji(emoji, window):
        """插入emoji到输入框"""
        text.insert(tk.END, emoji)
        window.destroy()
        text.focus_set()

    def vchat():
        pass
        # port = 10087
        # while True:
        #     try:
        #         vchat = VideoChat(port, 1, 4)
        #         achat = AudioChat(port + 1, 4)
        #         break
        #     except OSError as e:
        #         if e.winerror == 10048:
        #             port += 1
        #
        # vchat.start()
        # achat.start()

    def achat():
        pass
        # port = 10089
        # while True:
        #     try:
        #         achat = AudioChat(port + 1, 4)
        #         break
        #     except OSError as e:
        #         if e.winerror == 10048:
        #             port += 1
        # achat.start()

    # root.overrideredirect(True)

    # 在线用户区域 - 使用 TinUI 绘制标题
    online_frame = tk.Frame(root, width=175, bg=Theme.BG_CARD)

    # 标题区域 - 使用 TinUI 绘制
    online_header_ui = BasicTinUI(online_frame, bg=Theme.BG_CARD, width=175, height=45, highlightthickness=0)
    online_header_ui.place(x=15, y=0, relwidth=1.0, width=-30)
    online_header_ui.add_title((5, 10), "在线用户", font="微软雅黑", size=1, fg=Theme.TEXT_PRIMARY, anchor="w")

    # 分隔线 - 使用 TinUI 绘制
    online_sep_ui = BasicTinUI(online_frame, bg=Theme.BORDER, width=175, height=1, highlightthickness=0)
    online_sep_ui.place(x=15, y=45, relwidth=1.0, width=-30)

    # 用户列表 - Canvas 自绘，支持头像和未读红点
    user_list_canvas = UserListCanvas(online_frame)
    user_list_canvas.bind_select(choose_user)
    user_list_canvas.rebuild_with_groups([("🤖 deepseek助手", "robot")], groups)
    user_list_canvas.place(x=0, y=55, relwidth=1.0, width=0, height=-70, relheight=1.0)
    user_list_canvas.select(0)
    online_frame.place(x=0, y=0, relwidth=0.2, relheight=1.0)
    # online_frame.pack(expand=tk.YES, fill=tk.Y, anchor=tk.W)
    # online_frame.grid(row=0, column=0, rowspan=2)

    # 顶部框架 - 使用现代化背景色，添加底部边框
    top_frame = tk.Frame(root, bg=Theme.BG_LIGHT, height=40, borderwidth=0,
                         highlightbackground=Theme.BORDER, highlightthickness=1)
    top_frame.configure(highlightthickness=1, highlightbackground=Theme.BORDER)
    
    # 顶部工具栏分隔线
    top_separator = tk.Frame(root, bg=Theme.BORDER, height=1)
    
    extend = tk.Menu(root, tearoff=False, bg=Theme.BG_CARD, fg=Theme.TEXT_PRIMARY,
                     activebackground=Theme.PRIMARY_LIGHT, activeforeground=Theme.TEXT_PRIMARY)
    extend.add_command(label="修改信息", font=('微软雅黑', 10), command=update)
    extend.add_separator()
    extend.add_command(label="组群", font=('微软雅黑', 10), command=create_group)
    extend.add_command(label="注销", font=('微软雅黑', 10), foreground=Theme.ERROR, command=delete)
    
    # 菜单按钮 - 扁平化设计
    show = tk.Button(top_frame, text="☰", font=('微软雅黑', 16), bg=Theme.BG_LIGHT,
                     relief=tk.FLAT, bd=0, activebackground=Theme.HOVER_LIGHT,
                     fg=Theme.TEXT_SECONDARY, activeforeground=Theme.PRIMARY,
                     cursor="hand2",
                     command=lambda: extend.post(x=root.winfo_rootx() + root.winfo_width() - 50,
                                                 y=root.winfo_rooty() + 40))
    show.place(x=-50, relx=1.0, y=-17.5, rely=0.5, height=35, width=40)

    # 用户区域框架
    user_frame = tk.Frame(root, bg=Theme.BG_LIGHT)

    # 输入区域框架 - 使用 TinUI 绘制
    text_frame_ui = BasicTinUI(root, bg=Theme.BG_CARD, width=600, height=85,
                               highlightthickness=1, highlightbackground=Theme.BORDER)
    text_frame = text_frame_ui  # 兼容旧的变量名引用
    
    # 功能按钮 - 使用 TinUI 绘制（文字代替图标）
    text_frame_ui.add_button((8, 8), "截屏",
        font=('微软雅黑', 9), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD, line=Theme.BG_CARD,
        activefg=Theme.PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
        minwidth=36, command=lambda event: captureScreen())
    
    text_frame_ui.add_button((46, 8), "视频",
        font=('微软雅黑', 9), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD, line=Theme.BG_CARD,
        activefg=Theme.PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
        minwidth=36, command=lambda event: vchat())
    
    text_frame_ui.add_button((84, 8), "语音",
        font=('微软雅黑', 9), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD, line=Theme.BG_CARD,
        activefg=Theme.PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
        minwidth=36, command=lambda event: achat())
    
    text_frame_ui.add_button((122, 8), "文件",
        font=('微软雅黑', 9), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD, line=Theme.BG_CARD,
        activefg=Theme.PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
        minwidth=36, command=lambda event: achat())

    # Emoji按钮
    text_frame_ui.add_button((160, 8), "😊",
        font=('Segoe UI Emoji', 12), fg=Theme.TEXT_PRIMARY, bg=Theme.BG_CARD, line=Theme.BG_CARD,
        activefg=Theme.PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
        minwidth=36, command=lambda event: show_emoji_picker())
    
    # 输入框 - 使用 TinUI add_textbox
    text_result = text_frame_ui.add_textbox((8, 35), width=420, height=40, text="",
        font="微软雅黑 11", fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT,
        outline=Theme.BORDER, onoutline=Theme.PRIMARY)
    text, text_funcs, text_uid = text_result
    text.bind("<Return>", lambda event: send_text(str(text_funcs.get(1.0, tk.END)), Theme.MSG_SENT))
    text.bind("<Control-KeyPress-Return>", lambda event: True)
    
    # 发送按钮 - 使用 TinUI add_button
    send_result = text_frame_ui.add_button((530, 35), "发送",
        font=('微软雅黑', 11, 'bold'), fg="#000000", bg="#95EC69", line="#95EC69",
        activefg="#000000", activebg="#7BC85C", activeline="#7BC85C",
        minwidth=60, command=lambda event: send_text(str(text_funcs.get(1.0, tk.END)), "#95EC69"))
    send_id, send_back, send_funcs, send_uid = send_result
    
    text_frame_ui.place(relx=0.2, y=-85, rely=1.0, relwidth=0.8, height=85)

    recv_thread = threading.Thread(target=recv)
    recv_thread.daemon = True
    recv_thread.start()
    handle_thread = threading.Thread(target=handle)
    handle_thread.daemon = True
    handle_thread.start()
    # 显示主窗口并启动主循环
    root.deiconify()
    AnimationHelper.scale_in_window(root, duration=350)
    root.mainloop()
    connection.close()


def show_main_window():
    """显示已预加载的主窗口"""
    global main_widgets
    if 'main_widgets' in globals() and main_widgets.get('preloaded', False):
        root = main_widgets['root']
        root.deiconify()
        AnimationHelper.scale_in_window(root, duration=350)
        root.mainloop()
    else:
        # 未预加载，正常启动
        main()


def preload_before_login(user_name, password):
    """点击登录按钮时先预加载资源，然后发送登录请求"""
    global image_cache
    # 预加载图片数据
    image_cache = {
        "cut": Image.open("icons/cut.png"),
        "vchat": Image.open("icons/vchat.png"),
        "achat": Image.open("icons/achat.png"),
        "file": Image.open("icons/file.png"),
        "emoji": Image.open("icons/emoji.png"),
    }
    # 隐藏登录窗口
    #load.withdraw()
    # 发送登录请求（阻塞等待验证）
    user_msg_ctrl("login", user_name, password)


# noinspection PyGlobalUndefined
def user_msg_ctrl(command, user_name, password, icon_b64=""):
    global connection, icon_path, _name, _pwd
    send_pickle(connection, [command, user_name, password, icon_b64])
    head = recv_all(connection, 1024)
    head = json.loads(head.decode())
    echo_msg = recv_all(connection, head["size"])
    echo_msg = echo_msg.decode()
    if user_name != "" and password != "" and user_name.strip() and password.strip():
        if head["type"] == "login_echo":
            if echo_msg == "Login Success":
                _name = user_name
                _pwd = password
                icon_path = ""
                # 登录成功，销毁登录窗口并显示预加载的主窗口
                load.destroy()
                show_main_window()
            elif echo_msg == "Repeated Login":
                tk.messagebox.showwarning("登录失败", "此账号已在其他设备上登录！")
            else:
                tk.messagebox.showwarning("登录失败", "登录失败，请检查输入数据是否正确！")
        elif head["type"] == "sign up_echo":
            if echo_msg == "Sign Up Success":
                tk.messagebox.showinfo("注册成功", "注册成功！")
            elif echo_msg == "Repeated Sign Up":
                tk.messagebox.showwarning("重复注册", "此用户名的账户已存在！")
            else:
                tk.messagebox.showwarning("注册失败", "注册失败，请稍后再试！")
    else:
        tk.messagebox.showwarning("提示", "信息不得为空!")


def goto_sign_up(*args):
    global login_ui, sign_up_ui
    load.update_idletasks()
    frame_w = login_ui.winfo_width()
    
    sign_up_ui.place(x=10, y=10)

    def after_slide_out():
        login_ui.place_forget()
        AnimationHelper.slide_in(sign_up_ui, direction='left', duration=250, callback=None)

    AnimationHelper.slide_out(login_ui, direction='left', duration=200, callback=after_slide_out)


def goto_login(*args):
    global login_ui, sign_up_ui
    load.update_idletasks()
    frame_w = sign_up_ui.winfo_width()

    login_ui.place(x=10, y=10)
    
    def after_slide_out():
        sign_up_ui.place_forget()
        AnimationHelper.slide_in(login_ui, direction='left', duration=250, callback=None)
    
    AnimationHelper.slide_out(sign_up_ui, direction='left', duration=200, callback=after_slide_out)


def choose_icon_for_sign():
    """注册界面选择头像（TinUI版本）"""
    global icon_path, _cropped_icon_b64
    icon_path = tk.filedialog.askopenfilename(filetypes=[("图片", ("*.png", "*.jpg", "*.gif", "*.ico")), ])
    if icon_path:
        sign_icon_funcs.normal()  # 启用输入框
        sign_icon_funcs.delete()  # 清空
        sign_icon_funcs.insert(0, icon_path)  # 插入路径
        sign_icon_funcs.disable()  # 禁用输入框
        # 选完文件立即裁剪
        crop = ImageCrop(icon_path)
        cropped = crop.get_result()
        if cropped is not None:
            buf = io.BytesIO()
            cropped.save(buf, format='PNG')
            _cropped_icon_b64 = base64.b64encode(buf.getvalue()).decode()
            buf.close()


def do_sign_up(name, pwd):
    """执行注册流程：使用预裁剪的头像数据"""
    global _cropped_icon_b64
    user_msg_ctrl("sign up", name, pwd, _cropped_icon_b64)
    _cropped_icon_b64 = ""  # 复位


load = tk.Tk()
load.geometry(f"360x300+{int(load.winfo_screenwidth() / 2 - 180)}+{int(load.winfo_screenheight() / 2 - 150)}")
load.iconbitmap("icon/icon.ico")
load.title("登录")
load.resizable(False, False)
load.configure(bg=Theme.BG_LIGHT)

# ===== 使用 TinUI 构建登录界面 =====
login_ui = BasicTinUI(load, bg=Theme.BG_CARD, width=340, height=280, highlightthickness=1, highlightbackground=Theme.BORDER)
login_ui.place(x=10, y=10)

sign_up_ui = BasicTinUI(load, bg=Theme.BG_CARD, width=340, height=280, highlightthickness=1, highlightbackground=Theme.BORDER)

# TinUI 风格定义
title_font = ('微软雅黑', 24, 'bold')
label_font = ('微软雅黑', 12)
entry_font = ('微软雅黑', 12)
btn_font = ('微软雅黑', 12, 'bold')

# ===== 登录界面（TinUI绘制） =====
login_ui.add_title(
    (170, 25), "欢迎登录",
    font="微软雅黑", size=4, fg=Theme.TEXT_PRIMARY, anchor="center"
)

# 用户名
login_ui.add_label((40, 75), "用户名", font=label_font, fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD, outline=Theme.BG_CARD)
user_entry, user_entry_funcs, user_entry_uid = login_ui.add_entry((110, 75), 190, "", font=entry_font,
    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, onbg=Theme.BG_INPUT, onoutline=Theme.BORDER)
login_ui.add_label((40, 120), "密码", font=label_font, fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD, outline=Theme.BG_CARD)
pwd_entry, pwd_entry_funcs, pwd_entry_uid = login_ui.add_entry((110, 120), 190, "", font=entry_font,
    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, onbg=Theme.BG_INPUT, onoutline=Theme.BORDER)

# 登录按钮
login_btn_result = login_ui.add_button((50, 185), "登 录",
    font=btn_font, fg=Theme.TEXT_WHITE, bg=Theme.PRIMARY, line=Theme.PRIMARY,
    activefg=Theme.TEXT_WHITE, activebg=Theme.HOVER_DARK, activeline=Theme.HOVER_DARK,
    command=lambda event: preload_before_login(user_entry_funcs.get(), pwd_entry_funcs.get()))
login_btn_id, login_btn_back, login_btn_funcs, login_btn_uid = login_btn_result
# 设置按钮最小宽度
login_ui.coords(login_btn_back, 50 - 3, 185 - 3, 50 + 100 + 3, 185 + 30 + 3)

# 取消按钮
cancel_btn_result = login_ui.add_button((190, 185), "取 消",
    font=btn_font, fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, line=Theme.BG_INPUT,
    activefg=Theme.TEXT_PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
    command=lambda event: load.destroy())
cancel_btn_id, cancel_btn_back, cancel_btn_funcs, cancel_btn_uid = cancel_btn_result
login_ui.coords(cancel_btn_back, 190 - 3, 185 - 3, 190 + 100 + 3, 185 + 30 + 3)

# 注册链接
reg_link_id, reg_link_back, reg_link_funcs, reg_link_uid = login_ui.add_link((170, 240), "还没有账号？立即注册", goto_sign_up,
    font=('微软雅黑', 10), fg=Theme.PRIMARY, anchor="center")

# ===== 注册界面（TinUI绘制） =====
sign_up_ui.add_title(
    (170, 25), "创建账号",
    font="微软雅黑", size=4, fg=Theme.TEXT_PRIMARY, anchor="center"
)

# 用户名
sign_up_ui.add_label((40, 70), "用户名", font=label_font, fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD, outline=Theme.BG_CARD)
sign_user, sign_user_funcs, sign_user_uid = sign_up_ui.add_entry((110, 70), 190, "", font=entry_font,
    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, onbg=Theme.BG_INPUT, onoutline=Theme.BORDER)

# 密码
sign_up_ui.add_label((40, 105), "密码", font=label_font, fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD, outline=Theme.BG_CARD)
sign_pwd, sign_pwd_funcs, sign_pwd_uid = sign_up_ui.add_entry((110, 105), 190, "", font=entry_font,
    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, onbg=Theme.BG_INPUT, onoutline=Theme.BORDER)

# 头像
sign_up_ui.add_label((40, 140), "头像", font=label_font, fg=Theme.TEXT_SECONDARY, bg=Theme.BG_CARD, outline=Theme.BG_CARD)
sign_icon, sign_icon_funcs, sign_icon_uid = sign_up_ui.add_entry((110, 140), 140, "", font=('微软雅黑', 9),
    fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, onbg=Theme.BG_INPUT, onoutline=Theme.BORDER)
# 禁用头像输入框（只读显示路径）
sign_icon_funcs.disable()

sign_up_ui.add_button((220, 140), "浏览\u2026",
    font=('微软雅黑', 9), fg=Theme.TEXT_PRIMARY, bg=Theme.PRIMARY_LIGHT, line=Theme.PRIMARY_LIGHT,
    activefg=Theme.TEXT_PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT, maxwidth=70,
    command=lambda event: choose_icon_for_sign())

# 注册按钮
sign_btn_result = sign_up_ui.add_button((50, 185), "注 册",
    font=btn_font, fg=Theme.TEXT_WHITE, bg=Theme.PRIMARY, line=Theme.PRIMARY,
    activefg=Theme.TEXT_WHITE, activebg=Theme.HOVER_DARK, activeline=Theme.HOVER_DARK,
    command=lambda event: do_sign_up(sign_user_funcs.get(), sign_pwd_funcs.get()))
sign_btn_id, sign_btn_back, sign_btn_funcs, sign_btn_uid = sign_btn_result
sign_up_ui.coords(sign_btn_back, 50 - 3, 185 - 3, 50 + 100 + 3, 185 + 30 + 3)

# 取消按钮
sign_cancel_result = sign_up_ui.add_button((190, 185), "取 消",
    font=btn_font, fg=Theme.TEXT_PRIMARY, bg=Theme.BG_INPUT, line=Theme.BG_INPUT,
    activefg=Theme.TEXT_PRIMARY, activebg=Theme.HOVER_LIGHT, activeline=Theme.HOVER_LIGHT,
    command=lambda event: load.destroy())
sign_cancel_id, sign_cancel_back, sign_cancel_funcs, sign_cancel_uid = sign_cancel_result
sign_up_ui.coords(sign_cancel_back, 190 - 3, 185 - 3, 190 + 100 + 3, 185 + 30 + 3)

# 登录链接
sign_login_id, sign_login_back, sign_login_funcs, sign_login_uid = sign_up_ui.add_link((170, 240), "已有账号？立即登录", goto_login,
    font=('微软雅黑', 10), fg=Theme.PRIMARY, anchor="center")
load.update()
load.mainloop()
connection.close()
