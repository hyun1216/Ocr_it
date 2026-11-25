"""Full-screen multi-monitor snipping overlay with UIA smart region detection."""

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
BADGE_TEXT = "#FFFFFF"
MIN_DRAG_DISTANCE = 5
MIN_SMART_WIDTH = 28
MIN_SMART_HEIGHT = 20
MAX_SCAN_NODES = 350


def get_virtual_screen_rect() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) covering all connected monitors."""
    user32 = ctypes.windll.user32
    left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    return left, top, width, height


def _collect_ui_rects(
    v_width: int, v_height: int
) -> list[tuple[int, int, int, int]]:
    """Pre-scan visible UI control bounding boxes using Windows UI Automation."""
    try:
        import uiautomation as auto  # type: ignore
    except ImportError:
        return []

    rects: list[tuple[int, int, int, int]] = []
    seen: set[tuple[int, int, int, int]] = set()
    max_area = int(v_width * v_height * 0.92)

    try:
        fg = auto.GetForegroundControl()
        roots = [fg] if fg is not None else []
        root_ctrl = auto.GetRootControl()
        if root_ctrl is not None:
            for child in root_ctrl.GetChildren()[:6]:
                if child is not None:
                    roots.append(child)
    except Exception:
        return []

    queue: list[tuple[object, int]] = [(r, 0) for r in roots if r is not None]
    visited = 0

    while queue and visited < MAX_SCAN_NODES:
        ctrl, depth = queue.pop(0)
        visited += 1
        try:
            rect = ctrl.BoundingRectangle  # type: ignore[attr-defined]
            if rect is not None:
                l, t, r, b = int(rect.left), int(rect.top), int(rect.right), int(rect.bottom)
                w, h = r - l, b - t
                if (
                    w >= MIN_SMART_WIDTH
                    and h >= MIN_SMART_HEIGHT
                    and (w * h) < max_area
                    and (l, t, r, b) not in seen
                ):
                    seen.add((l, t, r, b))
                    rects.append((l, t, r, b))

            if depth < 5:
                for child in ctrl.GetChildren():  # type: ignore[attr-defined]
                    if child is not None:
                        queue.append((child, depth + 1))
        except Exception:
            continue

    # Sort smallest area first so innermost meaningful block is matched first
    rects.sort(key=lambda rc: (rc[2] - rc[0]) * (rc[3] - rc[1]))
    return rects


class ScreenSnipper:
    """Semi-transparent multi-monitor overlay supporting smart click & manual drag."""

    def __init__(
        self,
        master: tk.Tk,
        on_capture: Callable[[Image.Image, tuple[int, int, int, int]], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        self.master = master
        self.on_capture = on_capture
        self.on_cancel = on_cancel

        self._v_left, self._v_top, self._v_width, self._v_height = get_virtual_screen_rect()
        self._ui_rects = _collect_ui_rects(self._v_width, self._v_height)

        self._start_x = 0
        self._start_y = 0
        self._is_dragging = False
        self._has_dragged = False
        self._smart_bbox: Optional[tuple[int, int, int, int]] = None

        self._rect_id: Optional[int] = None
        self._badge_bg_id: Optional[int] = None
        self._badge_txt_id: Optional[int] = None
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

        self.canvas.bind("<Motion>", self._on_mouse_move)
        self.canvas.bind("<ButtonPress-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)
        self.overlay.bind("<Escape>", self._handle_escape)
        self.canvas.bind("<Escape>", self._handle_escape)

        self.overlay.deiconify()
        self.overlay.lift()
        self.overlay.focus_force()
        self.overlay.grab_set()

    def _find_smart_rect(self, x_root: int, y_root: int) -> Optional[tuple[int, int, int, int]]:
        """Find the best UI bounding box under the cursor, expanding tiny controls."""
        matches = [
            rc
            for rc in self._ui_rects
            if rc[0] <= x_root <= rc[2] and rc[1] <= y_root <= rc[3]
        ]
        if not matches:
            return None

        # Prefer a block larger than a tiny button/label if a parent container exists
        for rc in matches:
            if (rc[2] - rc[0]) >= 80 and (rc[3] - rc[1]) >= 40:
                return rc
        return matches[0]

    def _draw_highlight(self, cx1: int, cy1: int, cx2: int, cy2: int) -> None:
        self._clear_highlight()
        self._rect_id = self.canvas.create_rectangle(
            cx1,
            cy1,
            cx2,
            cy2,
            outline=ACCENT_BLUE,
            width=2,
            fill="#FFFFFF",
        )
        w = max(0, cx2 - cx1)
        h = max(0, cy2 - cy1)
        if w >= 20 and h >= 20:
            label = f"{w} × {h}"
            bx = max(4, cx1)
            by = max(4, cy1 - 24) if cy1 >= 28 else cy1 + 4
            self._badge_bg_id = self.canvas.create_rectangle(
                bx,
                by,
                bx + len(label) * 7 + 14,
                by + 20,
                fill=ACCENT_BLUE,
                outline="",
            )
            self._badge_txt_id = self.canvas.create_text(
                bx + 7,
                by + 10,
                text=label,
                anchor="w",
                fill=BADGE_TEXT,
                font=("Segoe UI", 9, "bold"),
            )

    def _clear_highlight(self) -> None:
        for item_id in (self._rect_id, self._badge_bg_id, self._badge_txt_id):
            if item_id is not None:
                self.canvas.delete(item_id)
        self._rect_id = None
        self._badge_bg_id = None
        self._badge_txt_id = None

    def _on_mouse_move(self, event: tk.Event) -> None:
        if self._is_dragging:
            return
        bbox = self._find_smart_rect(event.x_root, event.y_root)
        if bbox == self._smart_bbox:
            return
        self._smart_bbox = bbox
        if bbox is None:
            self._clear_highlight()
            return
        self._draw_highlight(
            bbox[0] - self._v_left,
            bbox[1] - self._v_top,
            bbox[2] - self._v_left,
            bbox[3] - self._v_top,
        )

    def _on_mouse_down(self, event: tk.Event) -> None:
        self._start_x = event.x
        self._start_y = event.y
        self._is_dragging = True
        self._has_dragged = False

    def _on_mouse_drag(self, event: tk.Event) -> None:
        if not self._is_dragging:
            return
        dx = abs(event.x - self._start_x)
        dy = abs(event.y - self._start_y)
        if dx >= MIN_DRAG_DISTANCE or dy >= MIN_DRAG_DISTANCE:
            self._has_dragged = True
        if self._has_dragged:
            x1 = min(self._start_x, event.x)
            y1 = min(self._start_y, event.y)
            x2 = max(self._start_x, event.x)
            y2 = max(self._start_y, event.y)
            self._draw_highlight(x1, y1, x2, y2)

    def _on_mouse_up(self, event: tk.Event) -> None:
        self._is_dragging = False
        if self._has_dragged:
            x1 = min(self._start_x, event.x)
            y1 = min(self._start_y, event.y)
            x2 = max(self._start_x, event.x)
            y2 = max(self._start_y, event.y)
            self._close_overlay()
            if (x2 - x1) < MIN_DRAG_DISTANCE or (y2 - y1) < MIN_DRAG_DISTANCE:
                if self.on_cancel:
                    self.on_cancel()
                return
            abs_bbox = (
                self._v_left + x1,
                self._v_top + y1,
                self._v_left + x2,
                self._v_top + y2,
            )
            self.master.after(40, lambda: self._capture_bbox(abs_bbox))
            return

        # Click without drag -> capture smart-detected UI region
        smart_bbox = self._smart_bbox
        self._close_overlay()
        if smart_bbox is None:
            if self.on_cancel:
                self.on_cancel()
            return
        self.master.after(40, lambda: self._capture_bbox(smart_bbox))

    def _capture_bbox(self, bbox: tuple[int, int, int, int]) -> None:
        image = ImageGrab.grab(bbox=bbox, all_screens=True)
        self.on_capture(image, bbox)

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
