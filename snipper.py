"""Full-screen freeze-frame snipping overlay with mss capture and lazy UIA detection."""

from __future__ import annotations

import ctypes
import os
import threading
import tkinter as tk
from ctypes import wintypes
from typing import Callable, Optional

import mss
import numpy as np
from PIL import Image, ImageGrab, ImageTk

SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

ACCENT_BLUE = "#0066FF"
BADGE_TEXT = "#FFFFFF"
DIM_FACTOR = 0.65
MIN_DRAG_DISTANCE = 5
MIN_SMART_WIDTH = 28
MIN_SMART_HEIGHT = 20
HOVER_DEBOUNCE_MS = 80


def get_virtual_screen_rect() -> tuple[int, int, int, int]:
    """Return (left, top, width, height) covering all connected monitors."""
    user32 = ctypes.windll.user32
    left = int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
    top = int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN))
    width = int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
    height = int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
    return left, top, width, height


def _grab_virtual_screen_fast(
    v_left: int, v_top: int, v_width: int, v_height: int
) -> tuple[Image.Image, Image.Image]:
    """Capture virtual screen with mss and build dimmed background via NumPy."""
    try:
        with mss.mss() as sct:
            monitor = {
                "left": v_left,
                "top": v_top,
                "width": v_width,
                "height": v_height,
            }
            shot = sct.grab(monitor)
            bgra = np.frombuffer(shot.bgra, dtype=np.uint8).reshape(
                shot.height, shot.width, 4
            )
            rgb = np.ascontiguousarray(bgra[:, :, 2::-1])
            frozen_img = Image.fromarray(rgb)
            dimmed_arr = (rgb.astype(np.uint16) * int(DIM_FACTOR * 256) >> 8).astype(
                np.uint8
            )
            dimmed_img = Image.fromarray(dimmed_arr)
            return frozen_img, dimmed_img
    except Exception:
        frozen_img = ImageGrab.grab(
            bbox=(v_left, v_top, v_left + v_width, v_top + v_height),
            all_screens=True,
        ).convert("RGB")
        arr = np.asarray(frozen_img, dtype=np.uint16)
        dimmed_arr = (arr * int(DIM_FACTOR * 256) >> 8).astype(np.uint8)
        return frozen_img, Image.fromarray(dimmed_arr)


def _find_hwnd_under_cursor(x: int, y: int) -> Optional[int]:
    """Find the topmost visible non-self window containing (x, y)."""
    user32 = ctypes.windll.user32
    current_pid = os.getpid()
    found_hwnd: list[int] = []
    rect = wintypes.RECT()
    pid = wintypes.DWORD()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum_cb(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == current_pid:
            return True
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            if rect.left <= x <= rect.right and rect.top <= y <= rect.bottom:
                if (rect.right - rect.left) >= MIN_SMART_WIDTH and (
                    rect.bottom - rect.top
                ) >= MIN_SMART_HEIGHT:
                    found_hwnd.append(hwnd)
                    return False
        return True

    user32.EnumWindows(_enum_cb, 0)
    return found_hwnd[0] if found_hwnd else None


def _query_ui_box_at_point(
    x: int, y: int, max_area: int
) -> Optional[tuple[int, int, int, int]]:
    """Query a single point via UIA by descending only along the matching branch."""
    try:
        import uiautomation as auto  # type: ignore
    except ImportError:
        return None

    hwnd = _find_hwnd_under_cursor(x, y)
    if not hwnd:
        return None

    candidates: list[tuple[int, int, int, int]] = []
    try:
        with auto.UIAutomationInitializerInThread():
            ctrl = auto.ControlFromHandle(hwnd)
            for _ in range(12):
                if ctrl is None:
                    break
                rect = ctrl.BoundingRectangle
                if rect is not None:
                    l, t, r, b = (
                        int(rect.left),
                        int(rect.top),
                        int(rect.right),
                        int(rect.bottom),
                    )
                    w, h = r - l, b - t
                    if (
                        w >= MIN_SMART_WIDTH
                        and h >= MIN_SMART_HEIGHT
                        and (w * h) < max_area
                        and l <= x <= r
                        and t <= y <= b
                    ):
                        candidates.append((l, t, r, b))

                next_ctrl = None
                for child in ctrl.GetChildren():
                    try:
                        c_rect = child.BoundingRectangle
                        if (
                            c_rect is not None
                            and c_rect.left <= x <= c_rect.right
                            and c_rect.top <= y <= c_rect.bottom
                        ):
                            next_ctrl = child
                            break
                    except Exception:
                        continue
                ctrl = next_ctrl
    except Exception:
        return None

    if not candidates:
        return None

    candidates.sort(key=lambda rc: (rc[2] - rc[0]) * (rc[3] - rc[1]))
    for rc in candidates:
        if (rc[2] - rc[0]) >= 80 and (rc[3] - rc[1]) >= 40:
            return rc
    return candidates[0]


class ScreenSnipper:
    """Opaque freeze-frame multi-monitor overlay with lazy debounced UIA detection."""

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
        self._max_smart_area = int(self._v_width * self._v_height * 0.92)

        # Fast mss snapshot + NumPy dimming (no UIA scan at startup)
        self._frozen_image, dimmed = _grab_virtual_screen_fast(
            self._v_left, self._v_top, self._v_width, self._v_height
        )
        self._dimmed_photo = ImageTk.PhotoImage(dimmed)
        self._crop_photo: Optional[ImageTk.PhotoImage] = None

        self._start_x = 0
        self._start_y = 0
        self._is_dragging = False
        self._has_dragged = False
        self._smart_bbox: Optional[tuple[int, int, int, int]] = None
        self._hover_timer: Optional[str] = None
        self._hover_req_id = 0

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
        self.overlay.update_idletasks()
        self.overlay.focus_force()
        try:
            self.overlay.grab_set()
        except tk.TclError:
            pass

        # Trigger initial smart-region query at current cursor position immediately
        pt = wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
            self._dispatch_smart_query(pt.x, pt.y)

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
        if self._is_dragging or self._closed:
            return

        if self._hover_timer is not None:
            try:
                self.overlay.after_cancel(self._hover_timer)
            except tk.TclError:
                pass
            self._hover_timer = None

        x_root, y_root = event.x_root, event.y_root
        self._hover_timer = self.overlay.after(
            HOVER_DEBOUNCE_MS,
            lambda: self._dispatch_smart_query(x_root, y_root),
        )

    def _dispatch_smart_query(self, x_root: int, y_root: int) -> None:
        self._hover_timer = None
        if self._is_dragging or self._closed:
            return

        self._hover_req_id += 1
        req_id = self._hover_req_id

        def _worker() -> None:
            bbox = _query_ui_box_at_point(x_root, y_root, self._max_smart_area)
            if self._closed or req_id != self._hover_req_id:
                return
            try:
                self.overlay.after(
                    0, lambda: self._apply_smart_rect(req_id, bbox)
                )
            except tk.TclError:
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_smart_rect(
        self, req_id: int, bbox: Optional[tuple[int, int, int, int]]
    ) -> None:
        if self._closed or self._is_dragging or req_id != self._hover_req_id:
            return
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
        if self._hover_timer is not None:
            try:
                self.overlay.after_cancel(self._hover_timer)
            except tk.TclError:
                pass
            self._hover_timer = None
        self._hover_req_id += 1
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

        smart_bbox = self._smart_bbox
        if smart_bbox is None:
            smart_bbox = _query_ui_box_at_point(
                event.x_root, event.y_root, self._max_smart_area
            )
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
        if self._hover_timer is not None:
            try:
                self.overlay.after_cancel(self._hover_timer)
            except tk.TclError:
                pass
            self._hover_timer = None
        try:
            self.overlay.grab_release()
        except tk.TclError:
            pass
        try:
            self.overlay.destroy()
        except tk.TclError:
            pass
        self.master.update_idletasks()
