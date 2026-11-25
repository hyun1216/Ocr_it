"""Apple iOS-style modern settings window for Ocr_it."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional

from PIL import ImageTk

from ui_graphics import make_rounded_rect_photo, make_toggle_photo

BG_WINDOW = "#F5F7FA"
BG_CARD = "#FFFFFF"
BORDER_CARD = "#E5E7EB"
DIVIDER_COLOR = "#F1F3F5"

PRIMARY_BLUE = "#0066FF"
SOFT_BLUE_BG = "#EBF3FE"
SOFT_BLUE_BORDER = "#BFDBFE"

RECORD_BG = "#FFFBEB"
RECORD_BORDER = "#F59E0B"
RECORD_TEXT = "#D97706"

TEXT_PRIMARY = "#111827"
TEXT_SECONDARY = "#6B7280"
TEXT_PLACEHOLDER = "#9CA3AF"

BTN_RESTORE_BG = "#E5E7EB"
BTN_CANCEL_BORDER = "#D1D5DB"
TOGGLE_OFF_BG = "#CBD5E1"

MODIFIER_KEYSYMS = {
    "Control_L": "ctrl",
    "Control_R": "ctrl",
    "Alt_L": "alt",
    "Alt_R": "alt",
    "Shift_L": "shift",
    "Shift_R": "shift",
    "Super_L": "windows",
    "Super_R": "windows",
}


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


def _format_hotkey_display(hotkey: str) -> str:
    """Format 'alt+q' as 'ALT + Q' for keycap display."""
    parts = [p.strip().upper() for p in hotkey.split("+") if p.strip()]
    return " + ".join(parts) if parts else "ALT + Q"


class RoundedButton(tk.Canvas):
    """Canvas button with 4x supersampled rounded background and crisp native text."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        font: tuple,
        bg_color: str,
        fg_color: str,
        border_color: str = "",
        radius: int = 10,
        width: int = 96,
        height: int = 36,
        parent_bg: str = BG_WINDOW,
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
        self._command = command
        self._bg_photo = make_rounded_rect_photo(
            width=width,
            height=height,
            radius=radius,
            fill_color=bg_color,
            border_color=border_color or None,
            border_width=1,
            parent_bg=parent_bg,
        )
        self.create_image(0, 0, anchor=tk.NW, image=self._bg_photo)
        self.create_text(
            width // 2,
            height // 2,
            text=text,
            font=font,
            fill=fg_color,
        )
        self.bind("<Button-1>", self._on_click)

    def _on_click(self, _event: tk.Event) -> None:
        if self._command:
            self._command()


class KeycapBadge(tk.Canvas):
    """Clickable keycap badge that records a new keyboard shortcut on click."""

    def __init__(
        self,
        master: tk.Misc,
        hotkey: str,
        font_family: str,
        on_start_record: Callable[["KeycapBadge"], None],
        on_change: Callable[[str], None],
        width: int = 152,
        height: int = 32,
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=height,
            bg=BG_CARD,
            highlightthickness=0,
            cursor="hand2",
        )
        self._width = width
        self._height = height
        self._hotkey = hotkey
        self._font_family = font_family
        self._on_start_record = on_start_record
        self._on_change = on_change
        self._recording = False

        self.bind("<Button-1>", self._handle_click)
        self._redraw()

    @property
    def hotkey(self) -> str:
        return self._hotkey

    def set_hotkey(self, hotkey: str) -> None:
        self._hotkey = hotkey
        self._recording = False
        self._redraw()

    def set_recording(self, recording: bool) -> None:
        self._recording = recording
        self._redraw()

    def _handle_click(self, _event: tk.Event) -> None:
        self._recording = True
        self._redraw()
        self._on_start_record(self)

    def _redraw(self) -> None:
        self.delete("all")
        if self._recording:
            self._badge_photo = make_rounded_rect_photo(
                width=self._width,
                height=self._height,
                radius=8,
                fill_color=RECORD_BG,
                border_color=RECORD_BORDER,
                border_width=1,
                parent_bg=BG_CARD,
            )
            self.create_image(0, 0, anchor=tk.NW, image=self._badge_photo)
            self.create_text(
                self._width // 2,
                self._height // 2,
                text="키 조합을 누르세요...",
                font=(self._font_family, 9, "bold"),
                fill=RECORD_TEXT,
            )
        else:
            self._badge_photo = make_rounded_rect_photo(
                width=self._width,
                height=self._height,
                radius=8,
                fill_color=SOFT_BLUE_BG,
                border_color=SOFT_BLUE_BORDER,
                border_width=1,
                parent_bg=BG_CARD,
            )
            self.create_image(0, 0, anchor=tk.NW, image=self._badge_photo)
            self.create_text(
                self._width // 2,
                self._height // 2,
                text=_format_hotkey_display(self._hotkey),
                font=(self._font_family, 9, "bold"),
                fill=PRIMARY_BLUE,
            )


class IOSToggleSwitch(tk.Canvas):
    """Smooth iOS-style rounded toggle switch."""

    def __init__(
        self,
        master: tk.Misc,
        initial: bool,
        on_toggle: Callable[[bool], None],
        width: int = 44,
        height: int = 24,
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=height,
            bg=BG_CARD,
            highlightthickness=0,
            cursor="hand2",
        )
        self._width = width
        self._height = height
        self._state = initial
        self._on_toggle = on_toggle
        self.bind("<Button-1>", self._handle_click)
        self._redraw()

    @property
    def state(self) -> bool:
        return self._state

    def set_state(self, state: bool) -> None:
        self._state = state
        self._redraw()

    def _handle_click(self, _event: tk.Event) -> None:
        self._state = not self._state
        self._redraw()
        self._on_toggle(self._state)

    def _redraw(self) -> None:
        self.delete("all")
        self._toggle_photo = make_toggle_photo(
            width=self._width,
            height=self._height,
            is_on=self._state,
            on_color=PRIMARY_BLUE,
            off_color=TOGGLE_OFF_BG,
            knob_color=BG_CARD,
            parent_bg=BG_CARD,
        )
        self.create_image(0, 0, anchor=tk.NW, image=self._toggle_photo)


class SettingsWindow:
    """Modern Apple iOS-style settings dialog with rounded cards and keycap inputs."""

    def __init__(
        self,
        master: tk.Tk,
        font_family: str,
        current_hotkey: str,
        current_pin_hotkey: str,
        current_scroll_hotkey: str,
        current_save_dir: str,
        startup_enabled: bool,
        icon_image: Optional[object],
        work_area: tuple[int, int, int, int],
        on_save: Callable[[str, str, str, str, bool], None],
    ) -> None:
        self.font_family = font_family
        self.on_save = on_save
        self._save_dir = current_save_dir.strip()
        self._startup_enabled = startup_enabled
        self._recording_badge: Optional[KeycapBadge] = None
        self._held_modifiers: set[str] = set()
        self._icon_photo: Optional[ImageTk.PhotoImage] = None

        self.win = tk.Toplevel(master)
        self.win.title("Ocr_it 설정")
        self.win.configure(bg=BG_WINDOW)
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self._apply_window_icon(icon_image)

        container = tk.Frame(self.win, bg=BG_WINDOW, padx=20, pady=18)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            container,
            text="설정",
            font=(font_family, 15, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_WINDOW,
        ).pack(anchor="w", pady=(0, 14))

        # Card 1: Hotkeys
        tk.Label(
            container,
            text="단축키 설정",
            font=(font_family, 10, "bold"),
            fg=TEXT_SECONDARY,
            bg=BG_WINDOW,
        ).pack(anchor="w", padx=4, pady=(0, 6))

        card1 = self._create_section_card(container, width=420, height=166)
        card1.pack(pady=(0, 16))

        row1 = tk.Frame(card1, bg=BG_CARD, width=392, height=48)
        row1.pack_propagate(False)
        card1.create_window(14, 6, anchor="nw", window=row1)

        tk.Label(
            row1,
            text="OCR 텍스트 추출",
            font=(font_family, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
        ).pack(side=tk.LEFT, pady=10)

        self._ocr_badge = KeycapBadge(
            row1,
            hotkey=current_hotkey,
            font_family=font_family,
            on_start_record=self._begin_recording,
            on_change=lambda _hk: None,
        )
        self._ocr_badge.pack(side=tk.RIGHT, pady=8)

        card1.create_line(14, 57, 406, 57, fill=DIVIDER_COLOR, width=1)

        row2 = tk.Frame(card1, bg=BG_CARD, width=392, height=48)
        row2.pack_propagate(False)
        card1.create_window(14, 60, anchor="nw", window=row2)

        tk.Label(
            row2,
            text="플로팅 화면 캡처",
            font=(font_family, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
        ).pack(side=tk.LEFT, pady=10)

        self._pin_badge = KeycapBadge(
            row2,
            hotkey=current_pin_hotkey,
            font_family=font_family,
            on_start_record=self._begin_recording,
            on_change=lambda _hk: None,
        )
        self._pin_badge.pack(side=tk.RIGHT, pady=8)

        card1.create_line(14, 111, 406, 111, fill=DIVIDER_COLOR, width=1)

        row_scroll = tk.Frame(card1, bg=BG_CARD, width=392, height=48)
        row_scroll.pack_propagate(False)
        card1.create_window(14, 114, anchor="nw", window=row_scroll)

        tk.Label(
            row_scroll,
            text="스크롤 캡처",
            font=(font_family, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
        ).pack(side=tk.LEFT, pady=10)

        self._scroll_badge = KeycapBadge(
            row_scroll,
            hotkey=current_scroll_hotkey,
            font_family=font_family,
            on_start_record=self._begin_recording,
            on_change=lambda _hk: None,
        )
        self._scroll_badge.pack(side=tk.RIGHT, pady=8)

        # Card 2: Storage & System
        tk.Label(
            container,
            text="저장 및 시스템",
            font=(font_family, 10, "bold"),
            fg=TEXT_SECONDARY,
            bg=BG_WINDOW,
        ).pack(anchor="w", padx=4, pady=(0, 6))

        card2 = self._create_section_card(container, width=420, height=118)
        card2.pack(pady=(0, 20))

        row3 = tk.Frame(card2, bg=BG_CARD, width=392, height=52)
        row3.pack_propagate(False)
        card2.create_window(14, 6, anchor="nw", window=row3)

        path_text_col = tk.Frame(row3, bg=BG_CARD)
        path_text_col.pack(side=tk.LEFT, fill=tk.Y, pady=4)

        tk.Label(
            path_text_col,
            text="플로팅 이미지 저장 경로",
            font=(font_family, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
            anchor="w",
        ).pack(anchor="w")

        self._path_label = tk.Label(
            path_text_col,
            text="",
            font=(font_family, 9),
            bg=BG_CARD,
            anchor="w",
        )
        self._path_label.pack(anchor="w")
        self._refresh_path_label()

        RoundedButton(
            row3,
            text="폴더 선택",
            font=(font_family, 9, "bold"),
            bg_color=SOFT_BLUE_BG,
            fg_color=PRIMARY_BLUE,
            border_color=SOFT_BLUE_BORDER,
            radius=15,
            width=86,
            height=30,
            parent_bg=BG_CARD,
            command=self._browse_save_dir,
        ).pack(side=tk.RIGHT, pady=10)

        card2.create_line(14, 61, 406, 61, fill=DIVIDER_COLOR, width=1)

        row4 = tk.Frame(card2, bg=BG_CARD, width=392, height=48)
        row4.pack_propagate(False)
        card2.create_window(14, 64, anchor="nw", window=row4)

        tk.Label(
            row4,
            text="Windows 시작 시 자동 실행",
            font=(font_family, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_CARD,
        ).pack(side=tk.LEFT, pady=10)

        self._startup_toggle = IOSToggleSwitch(
            row4,
            initial=startup_enabled,
            on_toggle=self._on_toggle_startup,
        )
        self._startup_toggle.pack(side=tk.RIGHT, pady=12)

        # Bottom rounded action buttons
        btn_row = tk.Frame(container, bg=BG_WINDOW, width=420, height=38)
        btn_row.pack_propagate(False)
        btn_row.pack(fill=tk.X)

        RoundedButton(
            btn_row,
            text="기본값 복원",
            font=(font_family, 9, "bold"),
            bg_color=BTN_RESTORE_BG,
            fg_color=TEXT_SECONDARY,
            radius=10,
            width=98,
            height=36,
            parent_bg=BG_WINDOW,
            command=self._restore_defaults,
        ).pack(side=tk.LEFT)

        RoundedButton(
            btn_row,
            text="저장하기",
            font=(font_family, 10, "bold"),
            bg_color=PRIMARY_BLUE,
            fg_color=BG_CARD,
            radius=10,
            width=92,
            height=36,
            parent_bg=BG_WINDOW,
            command=self._save,
        ).pack(side=tk.RIGHT, padx=(8, 0))

        RoundedButton(
            btn_row,
            text="취소",
            font=(font_family, 10),
            bg_color=BG_CARD,
            fg_color=TEXT_PRIMARY,
            border_color=BTN_CANCEL_BORDER,
            radius=10,
            width=76,
            height=36,
            parent_bg=BG_WINDOW,
            command=self.win.destroy,
        ).pack(side=tk.RIGHT)

        self.win.bind("<KeyPress>", self._on_key_press)
        self.win.bind("<KeyRelease>", self._on_key_release)

        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        h = self.win.winfo_reqheight()
        _, _, work_right, work_bottom = work_area
        self.win.geometry(f"+{work_right - w - 24}+{work_bottom - h - 24}")
        self.win.focus_force()

    def _apply_window_icon(self, icon_image: Optional[object]) -> None:
        ico_path = Path(__file__).resolve().with_name("Ocr_it.ico")
        if ico_path.exists():
            try:
                self.win.iconbitmap(str(ico_path))
                return
            except tk.TclError:
                pass
        if icon_image is not None:
            try:
                self._icon_photo = ImageTk.PhotoImage(icon_image)
                self.win.iconphoto(False, self._icon_photo)
            except Exception:
                pass

    def _create_section_card(
        self, parent: tk.Misc, width: int, height: int
    ) -> tk.Canvas:
        canvas = tk.Canvas(
            parent,
            width=width,
            height=height,
            bg=BG_WINDOW,
            highlightthickness=0,
        )
        card_photo = make_rounded_rect_photo(
            width=width,
            height=height,
            radius=14,
            fill_color=BG_CARD,
            border_color=BORDER_CARD,
            border_width=1,
            parent_bg=BG_WINDOW,
        )
        if not hasattr(self, "_card_photos"):
            self._card_photos: list[ImageTk.PhotoImage] = []
        self._card_photos.append(card_photo)
        canvas.create_image(0, 0, anchor=tk.NW, image=card_photo)
        return canvas

    def _refresh_path_label(self) -> None:
        if not self._save_dir:
            self._path_label.configure(
                text="저장할 때마다 폴더 선택",
                fg=TEXT_PLACEHOLDER,
            )
            return
        display = self._save_dir
        if len(display) > 36:
            display = "…" + display[-35:]
        self._path_label.configure(text=display, fg=TEXT_SECONDARY)

    def _browse_save_dir(self) -> None:
        selected = filedialog.askdirectory(
            parent=self.win,
            title="플로팅 이미지 자동 저장 폴더 선택",
            initialdir=self._save_dir or None,
        )
        if selected:
            self._save_dir = selected
            self._refresh_path_label()

    def _on_toggle_startup(self, enabled: bool) -> None:
        self._startup_enabled = enabled

    def _begin_recording(self, badge: KeycapBadge) -> None:
        if self._recording_badge is not None and self._recording_badge is not badge:
            self._recording_badge.set_recording(False)
        self._recording_badge = badge
        self._held_modifiers.clear()
        self.win.focus_force()

    def _on_key_release(self, event: tk.Event) -> None:
        mod = MODIFIER_KEYSYMS.get(event.keysym)
        if mod:
            self._held_modifiers.discard(mod)

    def _on_key_press(self, event: tk.Event) -> None:
        mod = MODIFIER_KEYSYMS.get(event.keysym)
        if mod:
            self._held_modifiers.add(mod)
            return

        if self._recording_badge is None:
            return

        if event.keysym == "Escape":
            self._recording_badge.set_recording(False)
            self._recording_badge = None
            return

        mods: list[str] = []
        state = int(event.state)
        if "ctrl" in self._held_modifiers or (state & 0x0004):
            mods.append("ctrl")
        if "alt" in self._held_modifiers or (state & 0x20000):
            mods.append("alt")
        if "shift" in self._held_modifiers or (state & 0x0001):
            mods.append("shift")

        key_name = event.keysym.lower()
        if not key_name:
            return

        combo = "+".join([*mods, key_name])
        self._recording_badge.set_hotkey(combo)
        self._recording_badge = None
        self._held_modifiers.clear()

    def _restore_defaults(self) -> None:
        if self._recording_badge is not None:
            self._recording_badge.set_recording(False)
            self._recording_badge = None
        self._ocr_badge.set_hotkey("alt+q")
        self._pin_badge.set_hotkey("alt+w")
        self._scroll_badge.set_hotkey("alt+s")
        self._save_dir = ""
        self._refresh_path_label()
        self._startup_enabled = False
        self._startup_toggle.set_state(False)

    def _save(self) -> None:
        ocr_hk = self._ocr_badge.hotkey
        pin_hk = self._pin_badge.hotkey
        scroll_hk = self._scroll_badge.hotkey
        save_dir = self._save_dir
        startup = self._startup_enabled
        self.win.destroy()
        self.on_save(ocr_hk, pin_hk, scroll_hk, save_dir, startup)
