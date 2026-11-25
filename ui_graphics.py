"""Pillow 4x supersampled anti-aliased UI graphic helpers for Tkinter."""

from __future__ import annotations

from typing import Optional

from PIL import Image, ImageColor, ImageDraw, ImageTk

SUPERSAMPLE = 4


def _to_rgba(color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    rgb = ImageColor.getrgb(color)
    return (rgb[0], rgb[1], rgb[2], alpha)


def make_rounded_rect_photo(
    width: int,
    height: int,
    radius: int,
    fill_color: str,
    border_color: Optional[str] = None,
    border_width: int = 1,
    parent_bg: Optional[str] = None,
) -> ImageTk.PhotoImage:
    """Render an anti-aliased rounded rectangle via 4x LANCZOS supersampling."""
    s = SUPERSAMPLE
    w_hi, h_hi = max(1, width * s), max(1, height * s)

    base_color = _to_rgba(parent_bg, 255) if parent_bg else (0, 0, 0, 0)
    img = Image.new("RGBA", (w_hi, h_hi), base_color)
    draw = ImageDraw.Draw(img)

    pad = s // 2
    outline = _to_rgba(border_color) if border_color else None
    bw = border_width * s if border_color else 0

    draw.rounded_rectangle(
        (pad, pad, w_hi - pad - 1, h_hi - pad - 1),
        radius=radius * s,
        fill=_to_rgba(fill_color),
        outline=outline,
        width=bw,
    )

    lo_res = img.resize((width, height), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(lo_res)


def make_circle_photo(
    size: int,
    fill_color: str,
    ring_color: Optional[str] = None,
    ring_width: int = 2,
    parent_bg: Optional[str] = None,
) -> ImageTk.PhotoImage:
    """Render an anti-aliased circle (with optional selection ring) at 4x scale."""
    s = SUPERSAMPLE
    hi = max(1, size * s)
    base_color = _to_rgba(parent_bg, 255) if parent_bg else (0, 0, 0, 0)
    img = Image.new("RGBA", (hi, hi), base_color)
    draw = ImageDraw.Draw(img)

    if ring_color:
        ring_pad = s
        draw.ellipse(
            (ring_pad, ring_pad, hi - ring_pad - 1, hi - ring_pad - 1),
            outline=_to_rgba(ring_color),
            width=ring_width * s,
        )

    inner_pad = 4 * s
    draw.ellipse(
        (inner_pad, inner_pad, hi - inner_pad - 1, hi - inner_pad - 1),
        fill=_to_rgba(fill_color),
    )

    lo_res = img.resize((size, size), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(lo_res)


def make_toggle_photo(
    width: int,
    height: int,
    is_on: bool,
    on_color: str = "#0066FF",
    off_color: str = "#CBD5E1",
    knob_color: str = "#FFFFFF",
    parent_bg: Optional[str] = None,
) -> ImageTk.PhotoImage:
    """Render an anti-aliased iOS pill toggle switch at 4x scale."""
    s = SUPERSAMPLE
    w_hi, h_hi = width * s, height * s
    base_color = _to_rgba(parent_bg, 255) if parent_bg else (0, 0, 0, 0)
    img = Image.new("RGBA", (w_hi, h_hi), base_color)
    draw = ImageDraw.Draw(img)

    track_color = _to_rgba(on_color if is_on else off_color)
    draw.rounded_rectangle(
        (0, 0, w_hi - 1, h_hi - 1),
        radius=(height * s) // 2,
        fill=track_color,
    )

    pad = 3 * s
    knob_d = h_hi - pad * 2
    knob_x = (w_hi - pad - knob_d) if is_on else pad
    draw.ellipse(
        (knob_x, pad, knob_x + knob_d, pad + knob_d),
        fill=_to_rgba(knob_color),
    )

    lo_res = img.resize((width, height), Image.Resampling.LANCZOS)
    return ImageTk.PhotoImage(lo_res)
