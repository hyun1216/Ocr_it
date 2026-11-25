"""Full-screen multi-monitor snipping overlay for Ocr_it."""

from __future__ import annotations

import ctypes
import tkinter as tk
from typing import Callable, Optional

from PIL import Image, ImageGrab

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

ACCENT_BLUE = "#0066FF"
MIN_SELECTION_SIZE = 5


def get_virtual_screen_rect() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) covering all connected monitors."""
    user32 = ctypes.windll.user32
    left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    return left, top, width, height


class ScreenSnipper:
    """Semi-transparent multi-monitor drag-to-capture overlay."""

    def __init__(
        self,
        master: tk.Tk,
        on_capture: Callable[[Image.Image], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        self.master = master
        self.on_capture = on_capture
        self.on_cancel = on_cancel

        self._v_left, self._v_top, self._v_width, self._v_height = get_virtual_screen_rect()
        self._start_x = 0
        self._start_y = 0
        self._rect_id: Optional[int] = None
        self._closed = False

        self.overlay = tk.Toplevel(master)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", 0.35)
        self.overlay.configure(bg="#000000", cursor="crosshair")
        self.overlay.geometry(
            f"{self._v_width}x{self._v_height}+{self._v_left}+{self._v_top}"
        )

        self.canvas = tk.Canvas(
            self.overlay,
            width=self._v_width,
            height=self._v_height,
            bg="#000000",
            highlightthickness=0,
            cursor="crosshair",
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.overlay.bind("<Escape>", self._handle_escape)
        self.canvas.bind("<Escape>", self._handle_escape)

        self.overlay.deiconify()
        self.overlay.lift()
        self.overlay.focus_force()
        self.overlay.grab_set()

    def _on_mouse_down(self, event: tk.Event) -> None:
        self._start_x = event.x
        self._start_y = event.y
        if self._rect_id is not None:
            self.canvas.delete(self._rect_id)
        self._rect_id = self.canvas.create_rectangle(
            self._start_x,
            self._start_y,
            self._start_x,
            self._start_y,
            outline=ACCENT_BLUE,
            width=2,
            fill="#FFFFFF",
        )

    def _on_mouse_drag(self, event: tk.Event) -> None:
        if self._rect_id is None:
            return
        self.canvas.coords(
            self._rect_id,
            self._start_x,
            self._start_y,
            event.x,
            event.y,
        )

    def _on_mouse_up(self, event: tk.Event) -> None:
        x1 = min(self._start_x, event.x)
        y1 = min(self._start_y, event.y)
        x2 = max(self._start_x, event.x)
        y2 = max(self._start_y, event.y)

        self._close_overlay()

        if (x2 - x1) < MIN_SELECTION_SIZE or (y2 - y1) < MIN_SELECTION_SIZE:
            if self.on_cancel:
                self.on_cancel()
            return

        abs_bbox = (
            self._v_left + x1,
            self._v_top + y1,
            self._v_left + x2,
            self._v_top + y2,
        )
        # Allow DWM to finish removing the overlay before grabbing pixels
        self.master.after(40, lambda: self._capture_bbox(abs_bbox))

    def _capture_bbox(self, bbox: tuple[int, int, int, int]) -> None:
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
        self.on_capture(image)

    def _handle_escape(self, _event: Optional[tk.Event] = None) -> None:
        self._close_overlay()
        if self.on_cancel:
            self.on_cancel()

    def _close_overlay(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.overlay.grab_release()
        except tk.TclError:
            pass
        try:
            self.overlay.destroy()
        except tk.TclError:
            pass
        self.master.update_idletasks()
