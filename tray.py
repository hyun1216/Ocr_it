"""System tray icon, Apple-style toast notification, history popup, and settings UI."""

from __future__ import annotations

import ctypes
import threading
import tkinter as tk
import tkinter.font as tkfont
import webbrowser
from dataclasses import dataclass
from typing import Callable, Optional

import pystray
from PIL import Image, ImageDraw

from ui_graphics import make_rounded_rect_photo, make_toggle_photo

PRIMARY_BLUE = "#0066FF"
SOFT_BLUE_BG = "#EBF3FE"
BG_WHITE = "#FFFFFF"
CARD_BG = "#F9FAFB"
BORDER_GRAY = "#E5E7EB"
TEXT_PRIMARY = "#111827"
TEXT_SECONDARY = "#6B7280"
TOGGLE_OFF_BG = "#CBD5E1"

SPI_GETWORKAREA = 48


@dataclass
class HistoryItem:
    """Represents a single OCR extraction entry."""

    text: str
    timestamp: str
    numbers_only: bool = False


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def get_work_area() -> tuple[int, int, int, int]:
    """Return primary monitor work area (left, top, right, bottom) excluding taskbar."""
    rect = _RECT()
    ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0)
    return rect.left, rect.top, rect.right, rect.bottom


def resolve_font_family(root: tk.Misc) -> str:
    """Prefer Pretendard or SUIT/Noto/Malgun Gothic for crisp Korean UI legibility."""
    available = set(tkfont.families(root))
    for candidate in (
        "Pretendard",
        "Pretendard Variable",
        "SUIT",
        "Noto Sans KR",
        "맑은 고딕",
        "Malgun Gothic",
        "Segoe UI",
    ):
        if candidate in available:
            return candidate
    return "TkDefaultFont"


def _draw_rounded_rect(
    canvas: tk.Canvas,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
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


class ToastNotification:
    """Minimal Apple-style toast notification above the bottom-right taskbar."""

    def __init__(
        self,
        master: tk.Tk,
        font_family: str,
        preview_text: str,
        is_error: bool = False,
        duration_ms: int = 1500,
    ) -> None:
        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BORDER_GRAY)

        inner = tk.Frame(self.win, bg=BG_WHITE, padx=14, pady=10)
        inner.pack(padx=1, pady=1, fill=tk.BOTH, expand=True)

        icon_text = "오류" if is_error else "완료"
        icon_color = "#EF4444" if is_error else PRIMARY_BLUE
        icon_bg = "#FEE2E2" if is_error else SOFT_BLUE_BG

        badge = tk.Label(
            inner,
            text=icon_text,
            font=(font_family, 9, "bold"),
            fg=icon_color,
            bg=icon_bg,
            padx=7,
            pady=2,
        )
        badge.pack(side=tk.LEFT, padx=(0, 10))

        first_line = preview_text.strip().splitlines()[0] if preview_text.strip() else "인식된 텍스트 없음"
        if len(first_line) > 36:
            first_line = first_line[:35] + "…"

        label = tk.Label(
            inner,
            text=first_line,
            font=(font_family, 11),
            fg=TEXT_PRIMARY,
            bg=BG_WHITE,
            anchor="w",
        )
        label.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.win.update_idletasks()
        width = max(240, min(380, self.win.winfo_reqwidth()))
        height = self.win.winfo_reqheight()

        _, _, work_right, work_bottom = get_work_area()
        pos_x = work_right - width - 16
        pos_y = work_bottom - height - 16

        self.win.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        self.win.deiconify()
        self.win.lift()
        self.win.after(duration_ms, self.close)

    def close(self) -> None:
        """Close the toast window safely."""
        try:
            self.win.destroy()
        except tk.TclError:
            pass


class ToggleSwitch(tk.Canvas):
    """Minimal pill-shaped toggle switch widget."""

    def __init__(
        self,
        master: tk.Misc,
        initial: bool,
        on_toggle: Callable[[bool], None],
        width: int = 42,
        height: int = 22,
    ) -> None:
        super().__init__(
            master,
            width=width,
            height=height,
            bg=BG_WHITE,
            highlightthickness=0,
            cursor="hand2",
        )
        self._width = width
        self._height = height
        self._state = initial
        self._on_toggle = on_toggle
        self.bind("<Button-1>", self._handle_click)
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
            knob_color=BG_WHITE,
            parent_bg=BG_WHITE,
        )
        self.create_image(0, 0, anchor=tk.NW, image=self._toggle_photo)


class HistoryPopup:
    """Minimal white & sky-blue history popup opened on tray left-click."""

    def __init__(
        self,
        master: tk.Tk,
        font_family: str,
        history: list[HistoryItem],
        numbers_only: bool,
        hotkey: str,
        on_toggle_numbers: Callable[[bool], None],
        on_copy_item: Callable[[str], None],
        on_trigger_capture: Callable[[], None],
    ) -> None:
        self.master = master
        self.font_family = font_family
        self.history = history
        self.on_copy_item = on_copy_item
        self.on_trigger_capture = on_trigger_capture

        self.win = tk.Toplevel(master)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=BORDER_GRAY)

        outer = tk.Frame(self.win, bg=BG_WHITE)
        outer.pack(padx=1, pady=1, fill=tk.BOTH, expand=True)

        # Header
        header = tk.Frame(outer, bg=BG_WHITE, padx=16, pady=12)
        header.pack(fill=tk.X)

        title_row = tk.Frame(header, bg=BG_WHITE)
        title_row.pack(fill=tk.X)

        tk.Label(
            title_row,
            text="Ocr_it",
            font=(font_family, 13, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_WHITE,
        ).pack(side=tk.LEFT)

        close_btn = tk.Label(
            title_row,
            text="닫기",
            font=(font_family, 10, "bold"),
            fg=TEXT_SECONDARY,
            bg=BG_WHITE,
            cursor="hand2",
            padx=6,
        )
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind("<Button-1>", lambda _e: self.close())

        capture_btn = tk.Label(
            title_row,
            text=f"캡처 ({hotkey.upper()})",
            font=(font_family, 10, "bold"),
            fg=PRIMARY_BLUE,
            bg=SOFT_BLUE_BG,
            padx=10,
            pady=4,
            cursor="hand2",
        )
        capture_btn.pack(side=tk.RIGHT, padx=(0, 8))
        capture_btn.bind("<Button-1>", self._handle_capture_click)

        # Numbers-only toggle bar
        toggle_row = tk.Frame(header, bg=BG_WHITE, pady=8)
        toggle_row.pack(fill=tk.X, pady=(6, 0))

        tk.Label(
            toggle_row,
            text="숫자만 추출 모드",
            font=(font_family, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_WHITE,
        ).pack(side=tk.LEFT)

        tk.Label(
            toggle_row,
            text=" (금액·사업자번호)",
            font=(font_family, 9),
            fg=TEXT_SECONDARY,
            bg=BG_WHITE,
        ).pack(side=tk.LEFT)

        ToggleSwitch(toggle_row, initial=numbers_only, on_toggle=on_toggle_numbers).pack(
            side=tk.RIGHT
        )

        tk.Frame(outer, bg=BORDER_GRAY, height=1).pack(fill=tk.X)

        # Scrollable cards area
        list_container = tk.Frame(outer, bg=BG_WHITE)
        list_container.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        self._scroll_canvas = tk.Canvas(
            list_container,
            width=336,
            height=340,
            bg=BG_WHITE,
            highlightthickness=0,
        )
        scrollbar = tk.Scrollbar(
            list_container,
            orient=tk.VERTICAL,
            command=self._scroll_canvas.yview,
        )
        self._scroll_canvas.configure(yscrollcommand=scrollbar.set)
        self._scroll_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._cards_frame = tk.Frame(self._scroll_canvas, bg=BG_WHITE)
        self._scroll_window = self._scroll_canvas.create_window(
            (0, 0),
            window=self._cards_frame,
            anchor="nw",
            width=320,
        )
        self._cards_frame.bind(
            "<Configure>",
            lambda _e: self._scroll_canvas.configure(
                scrollregion=self._scroll_canvas.bbox("all")
            ),
        )
        self._scroll_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        self._render_cards()

        # Position near bottom-right above taskbar
        self.win.update_idletasks()
        width = 364
        height = 450
        _, _, work_right, work_bottom = get_work_area()
        pos_x = work_right - width - 16
        pos_y = work_bottom - height - 16

        self.win.geometry(f"{width}x{height}+{pos_x}+{pos_y}")
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()
        self.win.bind("<Escape>", lambda _e: self.close())
        self.win.bind("<FocusOut>", self._on_focus_out)

    def _on_mousewheel(self, event: tk.Event) -> None:
        try:
            self._scroll_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except tk.TclError:
            pass

    def _on_focus_out(self, _event: tk.Event) -> None:
        self.win.after(120, self._check_focus)

    def _check_focus(self) -> None:
        try:
            focused = self.win.focus_get()
            if focused is None:
                self.close()
        except tk.TclError:
            pass

    def _handle_capture_click(self, _event: tk.Event) -> None:
        self.close()
        self.master.after(60, self.on_trigger_capture)

    def _render_cards(self) -> None:
        if not self.history:
            empty_label = tk.Label(
                self._cards_frame,
                text="최근 추출한 텍스트가 없습니다.\n단축키로 화면 영역을 캡처해 보세요.",
                font=(self.font_family, 10),
                fg=TEXT_SECONDARY,
                bg=BG_WHITE,
                justify=tk.CENTER,
                pady=80,
            )
            empty_label.pack(fill=tk.BOTH, expand=True)
            return

        for item in self.history:
            self._create_card(item)

    def _create_card(self, item: HistoryItem) -> None:
        card_w = 312
        card_h = 66
        card = tk.Canvas(
            self._cards_frame,
            width=card_w,
            height=card_h,
            bg=BG_WHITE,
            highlightthickness=0,
            cursor="hand2",
        )
        card.pack(pady=(0, 8), anchor="w")

        default_photo = make_rounded_rect_photo(
            width=card_w,
            height=card_h,
            radius=10,
            fill_color=CARD_BG,
            border_color=BORDER_GRAY,
            border_width=1,
            parent_bg=BG_WHITE,
        )
        active_photo = make_rounded_rect_photo(
            width=card_w,
            height=card_h,
            radius=10,
            fill_color=SOFT_BLUE_BG,
            border_color=PRIMARY_BLUE,
            border_width=1,
            parent_bg=BG_WHITE,
        )
        if not hasattr(self, "_card_photos"):
            self._card_photos: list[object] = []
        self._card_photos.extend([default_photo, active_photo])

        bg_id = card.create_image(0, 0, anchor=tk.NW, image=default_photo)

        flat_preview = " ".join(item.text.splitlines()).strip()
        if len(flat_preview) > 36:
            flat_preview = flat_preview[:35] + "…"

        card.create_text(
            14,
            23,
            text=flat_preview,
            anchor="w",
            font=(self.font_family, 10),
            fill=TEXT_PRIMARY,
        )

        meta_text = item.timestamp + (" · 숫자모드" if item.numbers_only else "")
        card.create_text(
            14,
            47,
            text=meta_text,
            anchor="w",
            font=(self.font_family, 9),
            fill=TEXT_SECONDARY,
        )

        check_id = card.create_text(
            card_w - 16,
            card_h // 2,
            text="",
            anchor="e",
            font=(self.font_family, 9, "bold"),
            fill=PRIMARY_BLUE,
        )

        def on_click(_event: tk.Event) -> None:
            self.on_copy_item(item.text)
            card.itemconfigure(bg_id, image=active_photo)
            card.itemconfigure(check_id, text="복사됨")
            card.after(
                1000,
                lambda: _reset_card(card, bg_id, default_photo, check_id),
            )

        card.bind("<Button-1>", on_click)

    def close(self) -> None:
        """Destroy the history popup safely."""
        try:
            self._scroll_canvas.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        try:
            self.win.destroy()
        except tk.TclError:
            pass


def _reset_card(
    card: tk.Canvas, bg_id: int, default_photo: object, check_id: int
) -> None:
    try:
        card.itemconfigure(bg_id, image=default_photo)
        card.itemconfigure(check_id, text="")
    except tk.TclError:
        pass


class AboutDialog:
    """Minimal developer support dialog."""

    def __init__(self, master: tk.Tk, font_family: str) -> None:
        win = tk.Toplevel(master)
        win.title("개발자 정보")
        win.configure(bg=BG_WHITE)
        win.resizable(False, False)
        win.attributes("-topmost", True)

        frame = tk.Frame(win, bg=BG_WHITE, padx=22, pady=18)
        frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            frame,
            text="Ocr_it (오씨알잇)",
            font=(font_family, 13, "bold"),
            fg=PRIMARY_BLUE,
            bg=BG_WHITE,
        ).pack(anchor="w")

        tk.Label(
            frame,
            text="초경량 Windows 화면 텍스트 추출 · 플로팅 · 스크롤 캡처 유틸리티",
            font=(font_family, 9),
            fg=TEXT_SECONDARY,
            bg=BG_WHITE,
        ).pack(anchor="w", pady=(2, 12))

        tk.Label(
            frame,
            text="후원하기",
            font=(font_family, 10, "bold"),
            fg=TEXT_PRIMARY,
            bg=BG_WHITE,
        ).pack(anchor="w")

        link = tk.Label(
            frame,
            text="https://buymeacoffee.com/devom",
            font=(font_family, 10, "underline"),
            fg=PRIMARY_BLUE,
            bg=BG_WHITE,
            cursor="hand2",
        )
        link.pack(anchor="w", pady=(4, 14))
        link.bind(
            "<Button-1>",
            lambda _e: webbrowser.open("https://buymeacoffee.com/devom"),
        )

        tk.Button(
            frame,
            text="확인",
            font=(font_family, 9, "bold"),
            fg=BG_WHITE,
            bg=PRIMARY_BLUE,
            relief=tk.FLAT,
            padx=16,
            pady=5,
            cursor="hand2",
            command=win.destroy,
        ).pack(anchor="e")

        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        _, _, work_right, work_bottom = get_work_area()
        win.geometry(f"+{work_right - w - 24}+{work_bottom - h - 24}")
        win.focus_force()


class UsageGuideDialog:
    """Clean Apple-style usage guide window opened from the tray menu."""

    def __init__(
        self,
        master: tk.Tk,
        font_family: str,
        hotkey: str,
        pin_hotkey: str,
        scroll_hotkey: str,
    ) -> None:
        win = tk.Toplevel(master)
        win.title("Ocr_it 사용방법")
        win.configure(bg="#F5F7FA")
        win.resizable(False, False)
        win.attributes("-topmost", True)

        container = tk.Frame(win, bg="#F5F7FA", padx=22, pady=20)
        container.pack(fill=tk.BOTH, expand=True)

        tk.Label(
            container,
            text="Ocr_it 사용방법",
            font=(font_family, 15, "bold"),
            fg=TEXT_PRIMARY,
            bg="#F5F7FA",
        ).pack(anchor="w")

        tk.Label(
            container,
            text="초경량 화면 텍스트 추출 · 플로팅 편집 · 스크롤 캡처 유틸리티",
            font=(font_family, 10),
            fg=TEXT_SECONDARY,
            bg="#F5F7FA",
        ).pack(anchor="w", pady=(2, 14))

        sections = [
            (
                f"1. 텍스트 추출 캡처 ({hotkey.upper()})",
                "원하는 영역을 드래그하거나 UI 블록 위에서 클릭(스마트 영역 감지)하면 "
                "한글·영문·숫자 텍스트를 추출해 클립보드에 자동 복사합니다.",
            ),
            (
                f"2. 화면 캡처 및 플로팅 ({pin_hotkey.upper()})",
                "선택 영역 이미지를 클립보드에 복사하고 항상 맨 위 플로팅 창으로 고정합니다.\n"
                "상단 '편집' 버튼 또는 우클릭으로 펜·사각형(색상/굵기 선택)·모자이크·자르기·저장을 사용할 수 있습니다.",
            ),
            (
                f"3. 스크롤 캡처 ({scroll_hotkey.upper()})",
                "긴 웹페이지나 채팅창 영역을 선택하면 자동으로 스크롤하며 한 장의 긴 이미지로 이어 붙입니다. "
                "(중단: ESC 키)",
            ),
            (
                "4. 트레이 아이콘 활용",
                "- 좌클릭: 최근 추출 기록(최대 15개) 재복사 및 '숫자만 추출 모드' 전환\n"
                "- 우클릭: 단축키 변경, 플로팅 자동 저장 경로, Windows 시작프로그램 설정",
            ),
        ]

        for title, desc in sections:
            card = tk.Frame(
                container,
                bg=BG_WHITE,
                highlightbackground=BORDER_GRAY,
                highlightthickness=1,
                padx=14,
                pady=11,
            )
            card.pack(fill=tk.X, pady=(0, 10))

            tk.Label(
                card,
                text=title,
                font=(font_family, 10, "bold"),
                fg=PRIMARY_BLUE,
                bg=BG_WHITE,
                anchor="w",
            ).pack(anchor="w")

            tk.Label(
                card,
                text=desc,
                font=(font_family, 9),
                fg=TEXT_PRIMARY,
                bg=BG_WHITE,
                justify=tk.LEFT,
                wraplength=420,
                anchor="w",
            ).pack(anchor="w", pady=(4, 0))

        tk.Button(
            container,
            text="확인",
            font=(font_family, 10, "bold"),
            fg=BG_WHITE,
            bg=PRIMARY_BLUE,
            relief=tk.FLAT,
            padx=20,
            pady=6,
            cursor="hand2",
            command=win.destroy,
        ).pack(anchor="e", pady=(6, 0))

        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        _, _, work_right, work_bottom = get_work_area()
        win.geometry(f"+{work_right - w - 24}+{work_bottom - h - 24}")
        win.focus_force()


def create_tray_image() -> Image.Image:
    """Generate a crisp 64x64 sky-blue viewfinder tray icon."""
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(
        (4, 4, size - 4, size - 4),
        radius=14,
        fill=(0, 102, 255, 255),
    )

    white = (255, 255, 255, 255)
    stroke = 5
    pad = 14
    arm = 11

    # Four viewfinder corners
    draw.line([(pad, pad + arm), (pad, pad), (pad + arm, pad)], fill=white, width=stroke)
    draw.line([(size - pad - arm, pad), (size - pad, pad), (size - pad, pad + arm)], fill=white, width=stroke)
    draw.line([(pad, size - pad - arm), (pad, size - pad), (pad + arm, size - pad)], fill=white, width=stroke)
    draw.line([(size - pad - arm, size - pad), (size - pad, size - pad), (size - pad, size - pad - arm)], fill=white, width=stroke)

    # Center text-line bars
    draw.rounded_rectangle((21, 25, 43, 30), radius=2, fill=white)
    draw.rounded_rectangle((21, 35, 37, 40), radius=2, fill=white)
    return img


class TrayController:
    """Manages the pystray icon and menu in a background daemon thread."""

    def __init__(
        self,
        hotkey: str,
        pin_hotkey: str,
        scroll_hotkey: str,
        on_capture: Callable[[], None],
        on_pin_capture: Callable[[], None],
        on_scroll_capture: Callable[[], None],
        on_history: Callable[[], None],
        on_settings: Callable[[], None],
        on_guide: Callable[[], None],
        on_about: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._hotkey = hotkey
        self._pin_hotkey = pin_hotkey
        self._scroll_hotkey = scroll_hotkey
        self._on_capture = on_capture
        self._on_pin_capture = on_pin_capture
        self._on_scroll_capture = on_scroll_capture
        self._on_history = on_history
        self._on_settings = on_settings
        self._on_guide = on_guide
        self._on_about = on_about
        self._on_quit = on_quit

        self._icon = pystray.Icon(
            name="Ocr_it",
            icon=create_tray_image(),
            title="Ocr_it (오씨알잇)",
            menu=self._build_menu(),
        )
        self._thread: Optional[threading.Thread] = None

    def _build_menu(self) -> pystray.Menu:
        hotkey_label = self._hotkey.upper()
        pin_hotkey_label = self._pin_hotkey.upper()
        scroll_hotkey_label = self._scroll_hotkey.upper()
        return pystray.Menu(
            pystray.MenuItem(
                f"텍스트 추출 캡처 ({hotkey_label})",
                lambda _icon, _item: self._on_capture(),
            ),
            pystray.MenuItem(
                f"화면 캡처 및 플로팅 ({pin_hotkey_label})",
                lambda _icon, _item: self._on_pin_capture(),
            ),
            pystray.MenuItem(
                f"스크롤 캡처 ({scroll_hotkey_label})",
                lambda _icon, _item: self._on_scroll_capture(),
            ),
            pystray.MenuItem(
                "최근 추출 기록",
                lambda _icon, _item: self._on_history(),
                default=True,  # Left-click triggers default item on Windows
            ),
            pystray.MenuItem(
                "단축키/시작프로그램 설정",
                lambda _icon, _item: self._on_settings(),
            ),
            pystray.MenuItem(
                "사용방법",
                lambda _icon, _item: self._on_guide(),
            ),
            pystray.MenuItem(
                "개발자 정보 / 후원하기",
                lambda _icon, _item: self._on_about(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "종료",
                lambda _icon, _item: self._on_quit(),
            ),
        )

    def update_hotkeys(
        self, hotkey: str, pin_hotkey: str, scroll_hotkey: str
    ) -> None:
        """Refresh the tray menu to reflect updated hotkeys."""
        self._hotkey = hotkey
        self._pin_hotkey = pin_hotkey
        self._scroll_hotkey = scroll_hotkey
        self._icon.menu = self._build_menu()
        self._icon.update_menu()

    def start(self) -> None:
        """Start the tray icon loop in a daemon thread."""
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the tray icon cleanly."""
        try:
            self._icon.stop()
        except Exception:
            pass
