"""Auto-scroll capture and OpenCV template-matching vertical stitching."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import cv2
import keyboard
import numpy as np
import pyautogui
from PIL import Image, ImageGrab

MAX_SCROLLS = 15
SCROLL_AMOUNT = -500
SCROLL_SETTLE_SEC = 0.45
UNCHANGED_STOP_COUNT = 2
MIN_MATCH_CONFIDENCE = 0.72


def stitch_frames(frames: list[Image.Image]) -> Optional[Image.Image]:
    """Vertically stitch consecutive scroll-captured frames using OpenCV template matching."""
    if not frames:
        return None
    if len(frames) == 1:
        return frames[0]

    stitched_np = np.array(frames[0].convert("RGB"))

    for nxt in frames[1:]:
        nxt_np = np.array(nxt.convert("RGB"))
        prev_h, prev_w = stitched_np.shape[:2]
        nxt_h, nxt_w = nxt_np.shape[:2]
        if prev_w != nxt_w or nxt_h < 20 or prev_h < 20:
            continue

        strip_h = min(60, max(24, nxt_h // 5))
        if prev_h < strip_h:
            continue

        # Exclude rightmost ~24px so stationary scrollbars do not skew matching
        match_w = max(24, prev_w - 24) if prev_w > 64 else prev_w

        prev_gray = cv2.cvtColor(
            stitched_np[prev_h - strip_h : prev_h, :match_w],
            cv2.COLOR_RGB2GRAY,
        )
        nxt_gray = cv2.cvtColor(nxt_np[:, :match_w], cv2.COLOR_RGB2GRAY)

        if nxt_gray.shape[0] <= prev_gray.shape[0]:
            continue

        res = cv2.matchTemplate(nxt_gray, prev_gray, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        crop_y = max_loc[1] + strip_h

        if max_val >= MIN_MATCH_CONFIDENCE and 0 < crop_y < nxt_h:
            new_slice = nxt_np[crop_y:, :]
            if new_slice.shape[0] > 0:
                stitched_np = np.vstack([stitched_np, new_slice])
        elif max_val < MIN_MATCH_CONFIDENCE:
            # Large jump fallback: append bottom half to avoid losing content
            stitched_np = np.vstack([stitched_np, nxt_np[nxt_h // 2 :, :]])

    return Image.fromarray(stitched_np)


def _frames_similar(img_a: Image.Image, img_b: Image.Image) -> bool:
    """Return True if two frames have virtually identical pixel content."""
    arr_a = np.asarray(img_a.convert("RGB"), dtype=np.int16)
    arr_b = np.asarray(img_b.convert("RGB"), dtype=np.int16)
    if arr_a.shape != arr_b.shape:
        return False
    mean_diff = float(np.mean(np.abs(arr_a - arr_b)))
    return mean_diff < 1.2


def run_scroll_capture(
    bbox: tuple[int, int, int, int],
    on_complete: Callable[[Optional[Image.Image]], None],
) -> None:
    """Run auto-scrolling capture in a background thread and invoke on_complete."""
    stop_event = threading.Event()

    def _on_esc() -> None:
        stop_event.set()

    esc_hook = None
    try:
        esc_hook = keyboard.add_hotkey("esc", _on_esc)
    except Exception:
        esc_hook = None

    def _worker() -> None:
        frames: list[Image.Image] = []
        try:
            cx = (bbox[0] + bbox[2]) // 2
            cy = (bbox[1] + bbox[3]) // 2
            pyautogui.moveTo(cx, cy)
            time.sleep(0.15)

            first = ImageGrab.grab(bbox=bbox, all_screens=True)
            frames.append(first)

            unchanged_count = 0
            for _ in range(MAX_SCROLLS):
                if stop_event.is_set():
                    break

                pyautogui.scroll(SCROLL_AMOUNT)
                time.sleep(SCROLL_SETTLE_SEC)

                if stop_event.is_set():
                    break

                current = ImageGrab.grab(bbox=bbox, all_screens=True)
                if _frames_similar(frames[-1], current):
                    unchanged_count += 1
                    if unchanged_count >= UNCHANGED_STOP_COUNT:
                        break
                    continue

                unchanged_count = 0
                frames.append(current)

            result = stitch_frames(frames)
            on_complete(result)
        finally:
            if esc_hook is not None:
                try:
                    keyboard.remove_hotkey(esc_hook)
                except Exception:
                    pass

    threading.Thread(target=_worker, daemon=True).start()
