"""Full-screen freeze-frame snipping overlay with UIA smart region detection."""

from __future__ import annotations

import ctypes
import tkinter as tk
from typing import Callable, Optional

from PIL import Image, ImageEnhance, ImageGrab, ImageTk

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

ACCENT_BLUE = "#0066FF"
BADGE_TEXT = "#FFFFFF"
DIM_BRIGHTNESS = 0.65
MIN_DRAG_DISTANCE = 5
MIN_SMART_WIDTH = 28
MIN_SMART_HEIGHT = 20
MAX_SCAN_NODES = 600


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


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

    def _add_rect(ctrl: object) -> None:
        try:
            rect = ctrl.BoundingRectangle  # type: ignore[attr-defined]
            if rect is None:
                return
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
        except Exception:
            pass

    # 1. Immediately capture the control under the cursor and its parent chain
    try:
        pt = _POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            cur = auto.ControlFromPoint(pt.x, pt.y)
            for _ in range(8):
                if cur is None:
                    break
                _add_rect(cur)
                cur = cur.GetParentControl()
    except Exception:
        pass

    # 2. Scan foreground window deeply (up to depth 10) and top-level windows
    roots: list[tuple[object, int]] = []
    try:
        fg_hwnd = ctypes.windll.user32.GetForegroundWindow()
        if fg_hwnd:
            fg_ctrl = auto.ControlFromHandle(fg_hwnd)
            if fg_ctrl is not None:
                roots.append((fg_ctrl, 0))
        root_ctrl = auto.GetRootControl()
        if root_ctrl is not None:
            for child in root_ctrl.GetChildren()[:10]:
                if child is not None:
                    roots.append((child, 6))
    except Exception:
        pass

    queue: list[tuple[object, int]] = list(roots)
    visited = 0

    while queue and visited < MAX_SCAN_NODES:
        ctrl, depth = queue.pop(0)
        visited += 1
        _add_rect(ctrl)
        if depth < 10:
            try:
                for child in ctrl.GetChildren():  # type: ignore[attr-defined]
                    if child is not None:
                        queue.append((child, depth + 1))
            except Exception:
                continue

    rects.sort(key=lambda rc: (rc[2] - rc[0]) * (rc[3] - rc[1]))
    return rects


class ScreenSnipper:
    """Opaque freeze-frame multi-monitor overlay with smart click & manual drag."""

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

        # Freeze entire virtual screen & scan UI tree BEFORE creating/focusing overlay
        self._frozen_image = ImageGrab.grab(
            bbox=(
                self._v_left,
                self._v_top,
                self._v_left + self._v_width,
                self._v_top + self._v_height,
            ),
            all_screens=True,
        ).convert("RGB")
        self._ui_rects = _collect_ui_rects(self._v_width, self._v_height)

        dimmed = ImageEnhance.Brightness(self._frozen_image).enhance(DIM_BRIGHTNESS)
        self._dimmed_photo = ImageTk.PhotoImage(dimmed)
        self._crop_photo: Optional[ImageTk.PhotoImage] = None

        self._start_x = 0
        self._start_y = 0
        self._is_dragging = False
        self._has_dragged = False
        self._smart_bbox: Optional[tuple[int, int, int, int]] = None

        self._crop_img_id: Optional[int] = None
        self._rect_id: Optional[int] = None
        self._badge_bg_id: Optional[int] = None
        self._badge_txt_id: Optional[int] = None
        self._closed = False

        self.overlay = tk.Toplevel(master)
        self.overlay.withdraw()
        self.overlay.overrideredirect(True)
        self.overlay.attributes("-topmost", True)
        self.overlay.attributes("-alpha", 1.0)
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
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self._dimmed_photo)

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

        for rc in matches:
            if (rc[2] - rc[0]) >= 80 and (rc[3] - rc[1]) >= 40:
                return rc
        return matches[0]

    def _clamp_canvas_box(
        self, cx1: int, cy1: int, cx2: int, cy2: int
    ) -> tuple[int, int, int, int]:
        x1 = max(0, min(self._v_width, min(cx1, cx2)))
        y1 = max(0, min(self._v_height, min(cy1, cy2)))
        x2 = max(0, min(self._v_width, max(cx1, cx2)))
        y2 = max(0, min(self._v_height, max(cy1, cy2)))
        return x1, y1, x2, y2

    def _draw_highlight(self, cx1: int, cy1: int, cx2: int, cy2: int) -> None:
        self._clear_highlight()
        x1, y1, x2, y2 = self._clamp_canvas_box(cx1, cy1, cx2, cy2)
        w = x2 - x1
        h = y2 - y1
        if w < 2 or h < 2:
            return

        # Reveal 100%-brightness original snapshot inside the selection box
        bright_crop = self._frozen_image.crop((x1, y1, x2, y2))
        self._crop_photo = ImageTk.PhotoImage(bright_crop)
        self._crop_img_id = self.canvas.create_image(
            x1, y1, anchor=tk.NW, image=self._crop_photo
        )

        self._rect_id = self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            outline=ACCENT_BLUE,
            width=2,
            fill="",
        )
        if w >= 20 and h >= 20:
            label = f"{w} × {h}"
            bx = max(4, x1)
            by = max(4, y1 - 24) if y1 >= 28 else y1 + 4
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
        for item_id in (
            self._crop_img_id,
            self._rect_id,
            self._badge_bg_id,
            self._badge_txt_id,
        ):
            if item_id is not None:
                self.canvas.delete(item_id)
        self._crop_img_id = None
        self._rect_id = None
        self._badge_bg_id = None
        self._badge_txt_id = None
        self._crop_photo = None

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
            self._draw_highlight(self._start_x, self._start_y, event.x, event.y)

    def _on_mouse_up(self, event: tk.Event) -> None:
        self._is_dragging = False
        if self._has_dragged:
            x1, y1, x2, y2 = self._clamp_canvas_box(
                self._start_x, self._start_y, event.x, event.y
            )
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
            image = self._frozen_image.crop((x1, y1, x2, y2))
            self.on_capture(image, abs_bbox)
            return

        # Click without drag -> capture smart-detected UI region from frozen snapshot
        smart_bbox = self._smart_bbox
        self._close_overlay()
        if smart_bbox is None:
            if self.on_cancel:
                self.on_cancel()
            return
        cx1, cy1, cx2, cy2 = self._clamp_canvas_box(
            smart_bbox[0] - self._v_left,
            smart_bbox[1] - self._v_top,
            smart_bbox[2] - self._v_left,
            smart_bbox[3] - self._v_top,
        )
        if (cx2 - cx1) < 2 or (cy2 - cy1) < 2:
            if self.on_cancel:
                self.on_cancel()
            return
        image = self._frozen_image.crop((cx1, cy1, cx2, cy2))
        abs_bbox = (
            self._v_left + cx1,
            self._v_top + cy1,
            self._v_left + cx2,
            self._v_top + cy2,
        )
        self.on_capture(image, abs_bbox)

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
