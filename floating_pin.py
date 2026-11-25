"""Floating pinned image window with sticky label tabs, color picker, and inline editor."""

from __future__ import annotations

import io
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import colorchooser, filedialog
from typing import Callable, Optional

import win32clipboard  # type: ignore
from PIL import Image, ImageDraw, ImageTk

from snipper import get_virtual_screen_rect
from ui_graphics import make_circle_photo, make_rounded_rect_photo

PRIMARY_BLUE = "#0066FF"
SOFT_BLUE_BG = "#EBF3FE"
ALERT_RED = "#FF3B30"
BG_WHITE = "#FFFFFF"
CARD_BG = "#F3F4F6"
BORDER_GRAY = "#D1D5DB"
TOOLBAR_BORDER = "#E5E7EB"
DIVIDER_COLOR = "#F1F3F5"
TRANSPARENT_KEY = "#010203"
TEXT_PRIMARY = "#111827"
TEXT_SECONDARY = "#4B5563"

MIN_SCALE = 0.25
MAX_SCALE = 3.0
MOSAIC_BLOCK_DIVISOR = 12
PRESET_COLORS = ("#FF3B30", "#0066FF", "#10B981", "#F59E0B", "#111827")
STROKE_WIDTHS = (
    (2, "얇게"),
    (4, "보통"),
    (7, "굵게"),
)


def copy_image_to_clipboard(image: Image.Image) -> None:
    """Copy a PIL Image to the Windows clipboard in CF_DIB format."""
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="BMP")
    dib_data = buf.getvalue()[14:]  # Strip 14-byte BITMAPFILEHEADER
    buf.close()

    last_err: Optional[Exception] = None
    for _ in range(4):
        try:
            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
                return
            finally:
                win32clipboard.CloseClipboard()
        except Exception as exc:
            last_err = exc
            time.sleep(0.025)

    if last_err is not None:
        raise last_err


def _draw_rounded_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    radius: float,
    **kwargs: object,
) -> int:
    """Draw a smooth rounded rectangle on a Tkinter Canvas."""
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
    return canvas.create_polygon(points, smooth=True, **kwargs)


class ToolbarPillButton(tk.Canvas):
    """4x supersampled anti-aliased toolbar button with crisp native text."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        font: tuple,
        width: int,
        height: int,
        bg_color: str,
        fg_color: str,
        border_color: Optional[str] = None,
        radius: int = 8,
        parent_bg: str = BG_WHITE,
        command: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=height,
            bg=parent_bg,
            highlightthickness=0,
            cursor="hand2",
        )
        self._text = text
        self._font = font
        self._width = width
        self._height = height
        self._radius = radius
        self._parent_bg = parent_bg
        self._command = command
        self._photo: Optional[ImageTk.PhotoImage] = None
        self.set_colors(bg_color, fg_color, border_color)
        self.bind("<Button-1>", self._on_click)

    def set_colors(
        self,
        bg_color: str,
        fg_color: str,
        border_color: Optional[str] = None,
        text: Optional[str] = None,
    ) -> None:
        if text is not None:
            self._text = text
        self.delete("all")
        self._photo = make_rounded_rect_photo(
            width=self._width,
            height=self._height,
            radius=self._radius,
            fill_color=bg_color,
            border_color=border_color,
            border_width=1,
            parent_bg=self._parent_bg,
        )
        self.create_image(0, 0, anchor=tk.NW, image=self._photo)
        self.create_text(
            self._width // 2,
            self._height // 2,
            text=self._text,
            font=self._font,
            fill=fg_color,
        )

    def _on_click(self, _event: tk.Event) -> None:
        if self._command:
            self._command()


class FloatingContextMenu:
    """Apple iOS-style rounded context menu replacing legacy tk.Menu."""

    def __init__(
        self,
        parent: tk.Misc,
        font_family: str,
        x_root: int,
        y_root: int,
        items: list[Optional[tuple[str, Callable[[], None], bool]]],
    ) -> None:
        self.win = tk.Toplevel(parent)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANSPARENT_KEY)
        try:
            self.win.attributes("-transparentcolor", TRANSPARENT_KEY)
        except tk.TclError:
            pass

        width = 188
        row_h = 36
        sep_h = 9
        pad_y = 8
        total_h = pad_y * 2 + sum(sep_h if it is None else row_h for it in items)

        canvas = tk.Canvas(
            self.win,
            width=width,
            height=total_h,
            bg=TRANSPARENT_KEY,
            highlightthickness=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        _draw_rounded_rect(
            canvas,
            1,
            1,
            width - 2,
            total_h - 2,
            radius=12,
            fill=BG_WHITE,
            outline=TOOLBAR_BORDER,
            width=1,
        )

        cur_y = pad_y
        for entry in items:
            if entry is None:
                mid_y = cur_y + sep_h // 2
                canvas.create_line(
                    12, mid_y, width - 12, mid_y, fill=DIVIDER_COLOR, width=1
                )
                cur_y += sep_h
                continue

            label_txt, callback, is_danger = entry
            y1 = cur_y + 2
            y2 = cur_y + row_h - 2

            hover_bg = "#FEE2E2" if is_danger else SOFT_BLUE_BG
            default_fg = ALERT_RED if is_danger else TEXT_PRIMARY
            hover_fg = ALERT_RED if is_danger else PRIMARY_BLUE

            bg_id = _draw_rounded_rect(
                canvas,
                8,
                y1,
                width - 8,
                y2,
                radius=8,
                fill=BG_WHITE,
                outline="",
            )
            text_id = canvas.create_text(
                20,
                (y1 + y2) // 2,
                text=label_txt,
                anchor="w",
                font=(font_family, 10, "bold" if is_danger else "normal"),
                fill=default_fg,
            )
            hit_id = canvas.create_rectangle(
                8, y1, width - 8, y2, fill="", outline=""
            )

            def on_enter(
                _e: tk.Event,
                b: int = bg_id,
                tx: int = text_id,
                hbg: str = hover_bg,
                hfg: str = hover_fg,
            ) -> None:
                canvas.itemconfigure(b, fill=hbg)
                canvas.itemconfigure(tx, fill=hfg)

            def on_leave(
                _e: tk.Event,
                b: int = bg_id,
                tx: int = text_id,
                dfg: str = default_fg,
            ) -> None:
                canvas.itemconfigure(b, fill=BG_WHITE)
                canvas.itemconfigure(tx, fill=dfg)

            def on_click(_e: tk.Event, cb: Callable[[], None] = callback) -> None:
                self.close()
                parent.after(10, cb)

            for item_id in (hit_id, bg_id, text_id):
                canvas.tag_bind(item_id, "<Enter>", on_enter)
                canvas.tag_bind(item_id, "<Leave>", on_leave)
                canvas.tag_bind(item_id, "<Button-1>", on_click)

            cur_y += row_h

        # Keep menu inside virtual screen bounds across all monitors
        v_left, v_top, v_width, v_height = get_virtual_screen_rect()
        max_x = v_left + v_width - width - 8
        max_y = v_top + v_height - total_h - 8
        pos_x = max(v_left, min(x_root, max_x))
        pos_y = max(v_top, min(y_root, max_y))

        self.win.geometry(f"{width}x{total_h}+{pos_x}+{pos_y}")
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self.win.bind("<FocusOut>", lambda _e: self.win.after(60, self.close))
        self.win.bind("<Escape>", lambda _e: self.close())

    def close(self) -> None:
        """Close the context menu safely."""
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class FloatingPinWindow:
    """Always-on-top frameless floating screenshot with sticky tabs and inline editing."""

    def __init__(
        self,
        master: tk.Tk,
        font_family: str,
        image: Image.Image,
        bbox: tuple[int, int, int, int],
        get_save_dir: Optional[Callable[[], str]] = None,
        on_notify: Optional[Callable[[str, bool], None]] = None,
        on_close: Optional[Callable[["FloatingPinWindow"], None]] = None,
    ) -> None:
        self.master = master
        self.font_family = font_family
        self.get_save_dir = get_save_dir
        self.on_notify = on_notify
        self.on_close = on_close

        self._image: Image.Image = image.convert("RGB")
        self._undo_stack: list[Image.Image] = []
        screen_h = master.winfo_screenheight()
        if self._image.height > int(screen_h * 0.78):
            self._scale = max(MIN_SCALE, (screen_h * 0.72) / self._image.height)
        else:
            self._scale = 1.0
        self._photo: Optional[ImageTk.PhotoImage] = None

        self._edit_mode = False
        self._tool = "pen"  # "pen", "rect", "mosaic", "crop"
        self._color = ALERT_RED
        self._stroke_width = 4

        self._drag_win_x = 0
        self._drag_win_y = 0
        self._edit_start_x = 0
        self._edit_start_y = 0
        self._last_draw_x = 0
        self._last_draw_y = 0
        self._preview_item: Optional[int] = None
        self._stroke_snapshot: Optional[Image.Image] = None
        self._active_menu: Optional[FloatingContextMenu] = None

        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BORDER_GRAY)

        self._outer = tk.Frame(self.win, bg=BORDER_GRAY, padx=1, pady=1)
        self._outer.pack(fill=tk.BOTH, expand=True)

        # Sticky label bar on top (Save / Close / Edit)
        self._label_bar = self._build_label_bar()
        self._label_bar.pack(side=tk.TOP, fill=tk.X)

        self._toolbar = self._build_toolbar()

        self._canvas = tk.Canvas(
            self._outer,
            bg=BG_WHITE,
            highlightthickness=0,
            cursor="fleur",
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._canvas.bind("<ButtonPress-1>", self._on_left_down)
        self._canvas.bind("<B1-Motion>", self._on_left_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_left_up)
        self._canvas.bind("<Button-3>", self._on_right_click)
        self._canvas.bind("<MouseWheel>", self._on_mouse_wheel)

        # ESC does NOT close floating window (only Close label / right-click menu closes it)
        self.win.bind("<Control-c>", lambda _e: self.copy_to_clipboard())
        self.win.bind("<Control-C>", lambda _e: self.copy_to_clipboard())
        self.win.bind("<Control-z>", lambda _e: self.undo())
        self.win.bind("<Control-Z>", lambda _e: self.undo())

        self._render_image()
        pos_x = bbox[0] - 1
        pos_y = max(0, bbox[1] - 34)
        self.win.geometry(f"+{pos_x}+{pos_y}")
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def _build_label_bar(self) -> tk.Frame:
        bar = tk.Frame(self._outer, bg=BG_WHITE, padx=8, pady=5)

        drag_hint = tk.Label(
            bar,
            text="플로팅",
            font=(self.font_family, 9, "bold"),
            fg=TEXT_SECONDARY,
            bg=BG_WHITE,
            cursor="fleur",
            padx=4,
            pady=2,
        )
        drag_hint.pack(side=tk.LEFT)
        drag_hint.bind("<ButtonPress-1>", self._on_bar_drag_start)
        drag_hint.bind("<B1-Motion>", self._on_bar_drag_move)
        bar.bind("<ButtonPress-1>", self._on_bar_drag_start)
        bar.bind("<B1-Motion>", self._on_bar_drag_move)

        # Clean text-only action labels (right-aligned)
        close_lbl = self._make_bar_text_btn(
            bar, "닫기", ALERT_RED, self.close
        )
        close_lbl.pack(side=tk.RIGHT, padx=(6, 0))

        save_lbl = self._make_bar_text_btn(
            bar, "저장", PRIMARY_BLUE, self.save_image
        )
        save_lbl.pack(side=tk.RIGHT, padx=(6, 0))

        self._edit_lbl = self._make_bar_text_btn(
            bar, "편집", TEXT_PRIMARY, self.toggle_edit_mode
        )
        self._edit_lbl.pack(side=tk.RIGHT)

        return bar

    def _make_bar_text_btn(
        self,
        parent: tk.Misc,
        text: str,
        fg_color: str,
        command: Callable[[], None],
    ) -> tk.Label:
        lbl = tk.Label(
            parent,
            text=text,
            font=(self.font_family, 9, "bold"),
            fg=fg_color,
            bg=BG_WHITE,
            padx=6,
            pady=2,
            cursor="hand2",
        )
        lbl.bind("<Button-1>", lambda _e: command())
        lbl.bind("<Enter>", lambda _e: lbl.configure(font=(self.font_family, 9, "bold", "underline")))
        lbl.bind("<Leave>", lambda _e: lbl.configure(font=(self.font_family, 9, "bold")))
        return lbl

    def _on_bar_drag_start(self, event: tk.Event) -> None:
        self._drag_win_x = event.x_root - self.win.winfo_x()
        self._drag_win_y = event.y_root - self.win.winfo_y()

    def _on_bar_drag_move(self, event: tk.Event) -> None:
        new_x = event.x_root - self._drag_win_x
        new_y = event.y_root - self._drag_win_y
        self.win.geometry(f"+{new_x}+{new_y}")

    def _build_toolbar(self) -> tk.Frame:
        bar = tk.Frame(self._outer, bg=BG_WHITE, padx=8, pady=6)

        self._tool_buttons: dict[str, ToolbarPillButton] = {}
        tools = [
            ("pen", "펜", 46),
            ("rect", "사각형", 62),
            ("mosaic", "모자이크", 72),
            ("crop", "자르기", 62),
        ]
        for key, label_text, btn_w in tools:
            btn = ToolbarPillButton(
                bar,
                text=label_text,
                font=(self.font_family, 9, "bold"),
                width=btn_w,
                height=28,
                bg_color=CARD_BG,
                fg_color=TEXT_SECONDARY,
                radius=8,
                parent_bg=BG_WHITE,
                command=lambda k=key: self._select_tool(k),
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            self._tool_buttons[key] = btn

        tk.Frame(bar, bg=TOOLBAR_BORDER, width=1, height=22).pack(
            side=tk.LEFT, padx=6
        )

        # Preset color swatches (4x supersampled anti-aliased circles)
        self._color_swatches: dict[str, tk.Canvas] = {}
        self._swatch_photos: dict[str, ImageTk.PhotoImage] = {}
        for hex_color in PRESET_COLORS:
            swatch = tk.Canvas(
                bar,
                width=22,
                height=22,
                bg=BG_WHITE,
                highlightthickness=0,
                cursor="hand2",
            )
            swatch.pack(side=tk.LEFT, padx=2)
            swatch.bind("<Button-1>", lambda _e, c=hex_color: self._select_color(c))
            self._color_swatches[hex_color] = swatch

        self._custom_color_btn = ToolbarPillButton(
            bar,
            text="색상",
            font=(self.font_family, 9, "bold"),
            width=48,
            height=28,
            bg_color=CARD_BG,
            fg_color=TEXT_PRIMARY,
            radius=8,
            parent_bg=BG_WHITE,
            command=self._pick_custom_color,
        )
        self._custom_color_btn.pack(side=tk.LEFT, padx=(4, 6))

        tk.Frame(bar, bg=TOOLBAR_BORDER, width=1, height=22).pack(
            side=tk.LEFT, padx=4
        )

        # Stroke width selector (Thin / Medium / Thick)
        self._width_buttons: dict[int, ToolbarPillButton] = {}
        for px, label_txt in STROKE_WIDTHS:
            w_btn = ToolbarPillButton(
                bar,
                text=label_txt,
                font=(self.font_family, 9, "bold"),
                width=48,
                height=28,
                bg_color=CARD_BG,
                fg_color=TEXT_SECONDARY,
                radius=8,
                parent_bg=BG_WHITE,
                command=lambda w=px: self._select_width(w),
            )
            w_btn.pack(side=tk.LEFT, padx=(0, 3))
            self._width_buttons[px] = w_btn

        ToolbarPillButton(
            bar,
            text="되돌리기",
            font=(self.font_family, 9, "bold"),
            width=68,
            height=28,
            bg_color=CARD_BG,
            fg_color=TEXT_PRIMARY,
            radius=8,
            parent_bg=BG_WHITE,
            command=self.undo,
        ).pack(side=tk.LEFT, padx=(2, 6))

        ToolbarPillButton(
            bar,
            text="완료",
            font=(self.font_family, 9, "bold"),
            width=54,
            height=28,
            bg_color=PRIMARY_BLUE,
            fg_color=BG_WHITE,
            radius=8,
            parent_bg=BG_WHITE,
            command=self.toggle_edit_mode,
        ).pack(side=tk.RIGHT)

        self._refresh_toolbar_styles()
        return bar

    def _build_context_menu_items(
        self,
    ) -> list[Optional[tuple[str, Callable[[], None], bool]]]:
        edit_label = "편집 종료" if self._edit_mode else "편집하기"
        return [
            (edit_label, self.toggle_edit_mode, False),
            ("이미지 복사", self.copy_to_clipboard, False),
            ("이미지 저장", self.save_image, False),
            ("다른 이름으로 저장...", self.save_as_png, False),
            None,
            ("플로팅 닫기", self.close, True),
        ]

    def _refresh_toolbar_styles(self) -> None:
        for key, btn in self._tool_buttons.items():
            active = key == self._tool
            btn.set_colors(
                bg_color=SOFT_BLUE_BG if active else CARD_BG,
                fg_color=PRIMARY_BLUE if active else TEXT_SECONDARY,
            )
        for hex_color, swatch in self._color_swatches.items():
            swatch.delete("all")
            photo = make_circle_photo(
                size=22,
                fill_color=hex_color,
                ring_color=PRIMARY_BLUE if self._color == hex_color else None,
                ring_width=2,
                parent_bg=BG_WHITE,
            )
            self._swatch_photos[hex_color] = photo
            swatch.create_image(0, 0, anchor=tk.NW, image=photo)
        if self._color not in self._color_swatches:
            self._custom_color_btn.set_colors(self._color, BG_WHITE)
        else:
            self._custom_color_btn.set_colors(CARD_BG, TEXT_PRIMARY)
        for px, w_btn in self._width_buttons.items():
            active = px == self._stroke_width
            w_btn.set_colors(
                bg_color=SOFT_BLUE_BG if active else CARD_BG,
                fg_color=PRIMARY_BLUE if active else TEXT_SECONDARY,
            )

    def _select_tool(self, tool: str) -> None:
        self._tool = tool
        self._refresh_toolbar_styles()

    def _select_color(self, color: str) -> None:
        self._color = color
        self._refresh_toolbar_styles()

    def _select_width(self, width_px: int) -> None:
        self._stroke_width = width_px
        self._refresh_toolbar_styles()

    def _pick_custom_color(self) -> None:
        chosen = colorchooser.askcolor(
            color=self._color,
            parent=self.win,
            title="그리기 색상 선택",
        )
        if chosen and chosen[1]:
            self._color = str(chosen[1])
            self._refresh_toolbar_styles()

    def toggle_edit_mode(self) -> None:
        """Toggle the inline editing toolbar and canvas interaction mode."""
        self._edit_mode = not self._edit_mode
        if self._edit_mode:
            self._outer.configure(bg=PRIMARY_BLUE)
            self._toolbar.pack(side=tk.TOP, fill=tk.X, before=self._canvas)
            self._canvas.configure(cursor="crosshair")
            self._edit_lbl.configure(text="편집중", fg=PRIMARY_BLUE)
        else:
            self._outer.configure(bg=BORDER_GRAY)
            self._toolbar.pack_forget()
            self._canvas.configure(cursor="fleur")
            self._edit_lbl.configure(text="편집", fg=TEXT_PRIMARY)
            self.copy_to_clipboard(silent=True)

    def _render_image(self) -> None:
        disp_w = max(1, int(round(self._image.width * self._scale)))
        disp_h = max(1, int(round(self._image.height * self._scale)))

        if self._scale == 1.0:
            disp_img = self._image
        else:
            disp_img = self._image.resize((disp_w, disp_h), Image.Resampling.LANCZOS)

        self._photo = ImageTk.PhotoImage(disp_img)
        self._canvas.configure(width=disp_w, height=disp_h)
        self._canvas.delete("all")
        self._canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)

    def _to_image_coords(self, cx: int, cy: int) -> tuple[int, int]:
        ix = max(0, min(self._image.width - 1, int(round(cx / self._scale))))
        iy = max(0, min(self._image.height - 1, int(round(cy / self._scale))))
        return ix, iy

    def _push_undo(self, snapshot: Optional[Image.Image] = None) -> None:
        self._undo_stack.append((snapshot or self._image).copy())
        if len(self._undo_stack) > 20:
            self._undo_stack.pop(0)

    def undo(self) -> None:
        """Restore the previous image state from the undo stack."""
        if not self._undo_stack:
            return
        self._image = self._undo_stack.pop()
        self._render_image()
        self.copy_to_clipboard(silent=True)

    def _on_left_down(self, event: tk.Event) -> None:
        self.win.focus_force()
        if not self._edit_mode:
            self._drag_win_x = event.x_root - self.win.winfo_x()
            self._drag_win_y = event.y_root - self.win.winfo_y()
            return

        self._edit_start_x = event.x
        self._edit_start_y = event.y
        self._last_draw_x = event.x
        self._last_draw_y = event.y
        self._stroke_snapshot = self._image.copy()

        if self._tool in ("rect", "mosaic", "crop"):
            outline = PRIMARY_BLUE if self._tool in ("mosaic", "crop") else self._color
            dash = (4, 2) if self._tool in ("mosaic", "crop") else ()
            preview_w = (
                max(1, int(round(self._stroke_width * self._scale)))
                if self._tool == "rect"
                else 2
            )
            self._preview_item = self._canvas.create_rectangle(
                event.x,
                event.y,
                event.x,
                event.y,
                outline=outline,
                width=preview_w,
                dash=dash,
            )

    def _on_left_drag(self, event: tk.Event) -> None:
        if not self._edit_mode:
            new_x = event.x_root - self._drag_win_x
            new_y = event.y_root - self._drag_win_y
            self.win.geometry(f"+{new_x}+{new_y}")
            return

        if self._tool == "pen":
            x1, y1 = self._to_image_coords(self._last_draw_x, self._last_draw_y)
            x2, y2 = self._to_image_coords(event.x, event.y)
            draw = ImageDraw.Draw(self._image)
            draw.line([(x1, y1), (x2, y2)], fill=self._color, width=self._stroke_width)
            self._canvas.create_line(
                self._last_draw_x,
                self._last_draw_y,
                event.x,
                event.y,
                fill=self._color,
                width=max(1, int(round(self._stroke_width * self._scale))),
                capstyle=tk.ROUND,
                smooth=True,
            )
            self._last_draw_x = event.x
            self._last_draw_y = event.y
        elif self._preview_item is not None:
            self._canvas.coords(
                self._preview_item,
                self._edit_start_x,
                self._edit_start_y,
                event.x,
                event.y,
            )

    def _on_left_up(self, event: tk.Event) -> None:
        if not self._edit_mode:
            return

        if self._preview_item is not None:
            self._canvas.delete(self._preview_item)
            self._preview_item = None

        if self._tool == "pen":
            if self._stroke_snapshot is not None:
                self._push_undo(self._stroke_snapshot)
                self._stroke_snapshot = None
            self._render_image()
            self.copy_to_clipboard(silent=True)
            return

        x1, y1 = self._to_image_coords(
            min(self._edit_start_x, event.x),
            min(self._edit_start_y, event.y),
        )
        x2, y2 = self._to_image_coords(
            max(self._edit_start_x, event.x),
            max(self._edit_start_y, event.y),
        )
        if (x2 - x1) < 4 or (y2 - y1) < 4:
            self._stroke_snapshot = None
            return

        self._push_undo(self._stroke_snapshot)
        self._stroke_snapshot = None

        if self._tool == "rect":
            draw = ImageDraw.Draw(self._image)
            draw.rectangle(
                [x1, y1, x2, y2], outline=self._color, width=self._stroke_width
            )
        elif self._tool == "mosaic":
            self._apply_mosaic(x1, y1, x2, y2)
        elif self._tool == "crop":
            self._image = self._image.crop((x1, y1, x2, y2))

        self._render_image()
        self.copy_to_clipboard(silent=True)

    def _apply_mosaic(self, x1: int, y1: int, x2: int, y2: int) -> None:
        region = self._image.crop((x1, y1, x2, y2))
        w, h = region.size
        small_w = max(1, w // MOSAIC_BLOCK_DIVISOR)
        small_h = max(1, h // MOSAIC_BLOCK_DIVISOR)
        pixelated = region.resize((small_w, small_h), Image.Resampling.NEAREST).resize(
            (w, h), Image.Resampling.NEAREST
        )
        self._image.paste(pixelated, (x1, y1))

    def _on_mouse_wheel(self, event: tk.Event) -> None:
        factor = 1.1 if event.delta > 0 else 0.9
        new_scale = max(MIN_SCALE, min(MAX_SCALE, self._scale * factor))
        if abs(new_scale - self._scale) < 0.01:
            return
        self._scale = new_scale
        self._render_image()

    def _on_right_click(self, event: tk.Event) -> None:
        if self._active_menu is not None:
            self._active_menu.close()
        self._active_menu = FloatingContextMenu(
            parent=self.win,
            font_family=self.font_family,
            x_root=event.x_root,
            y_root=event.y_root,
            items=self._build_context_menu_items(),
        )

    def copy_to_clipboard(self, silent: bool = False) -> None:
        """Copy the current floating image to the Windows clipboard."""
        try:
            copy_image_to_clipboard(self._image)
            if not silent and self.on_notify:
                self.on_notify("이미지가 클립보드에 복사되었습니다.", False)
        except Exception as exc:
            if self.on_notify:
                self.on_notify(f"이미지 복사 실패: {exc}", True)

    def save_image(self) -> None:
        """Save to configured auto-save directory, or prompt if none is set."""
        auto_dir = self.get_save_dir().strip() if self.get_save_dir else ""
        if auto_dir:
            try:
                target_dir = Path(auto_dir)
                target_dir.mkdir(parents=True, exist_ok=True)
                filename = f"Ocr_it_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                target_path = target_dir / filename
                self._image.save(target_path, format="PNG")
                if self.on_notify:
                    self.on_notify(f"자동 저장 완료: {filename}", False)
                return
            except Exception as exc:
                if self.on_notify:
                    self.on_notify(f"자동 저장 실패: {exc}", True)
                return

        self.save_as_png()

    def save_as_png(self) -> None:
        """Prompt user to save the current floating image as a PNG file."""
        auto_dir = self.get_save_dir().strip() if self.get_save_dir else ""
        default_name = f"Ocr_it_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        file_path = filedialog.asksaveasfilename(
            parent=self.win,
            title="이미지 저장",
            initialdir=auto_dir or None,
            defaultextension=".png",
            initialfile=default_name,
            filetypes=[("PNG 이미지", "*.png"), ("모든 파일", "*.*")],
        )
        if not file_path:
            return
        try:
            self._image.save(file_path, format="PNG")
            if self.on_notify:
                self.on_notify(f"저장 완료: {Path(file_path).name}", False)
        except Exception as exc:
            if self.on_notify:
                self.on_notify(f"이미지 저장 실패: {exc}", True)

    def close(self) -> None:
        """Close the floating window cleanly."""
        try:
            self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close(self)
