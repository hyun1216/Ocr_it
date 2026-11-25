"""RapidOCR (ONNX Runtime) Korean + English engine wrapper for Ocr_it."""

from __future__ import annotations

import os
import re
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageEnhance

CONTRAST_FACTOR = 1.35
SHARPNESS_FACTOR = 1.4
MAX_UPSCALE_SIDE = 4096

KOREAN_MODEL_URL = (
    "https://huggingface.co/monkt/paddleocr-onnx/resolve/main/languages/korean/rec.onnx"
)
KOREAN_DICT_URL = (
    "https://huggingface.co/monkt/paddleocr-onnx/resolve/main/languages/korean/dict.txt"
)

_engine_lock = threading.Lock()
_ocr_instance: Optional[Any] = None


class OcrEngineError(Exception):
    """Raised when the OCR engine cannot process an image."""


def filter_numbers_only(text: str) -> str:
    """Extract only digits and decimal points, preserving non-empty lines."""
    if not text:
        return ""
    cleaned_lines: list[str] = []
    for line in text.splitlines():
        only_nums = re.sub(r"[^0-9.]", "", line)
        if only_nums:
            cleaned_lines.append(only_nums)
    return "\n".join(cleaned_lines)


def _preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Upscale 2x with LANCZOS and enhance contrast/sharpness for clear spacing."""
    rgb = image.convert("RGB")
    if rgb.width * 2 <= MAX_UPSCALE_SIDE and rgb.height * 2 <= MAX_UPSCALE_SIDE:
        rgb = rgb.resize(
            (rgb.width * 2, rgb.height * 2),
            Image.Resampling.LANCZOS,
        )
    rgb = ImageEnhance.Contrast(rgb).enhance(CONTRAST_FACTOR)
    rgb = ImageEnhance.Sharpness(rgb).enhance(SHARPNESS_FACTOR)
    return rgb


def _resolve_korean_model_paths() -> tuple[Path, Path]:
    """Locate bundled or cached Korean PP-OCR recognition model and dictionary."""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "models")
    candidates.append(Path(__file__).resolve().parent / "models")

    appdata = os.environ.get("APPDATA") or str(Path.home())
    cache_dir = Path(appdata) / "Ocr_it" / "models"
    candidates.append(cache_dir)

    for folder in candidates:
        rec_path = folder / "korean_rec.onnx"
        dict_path = folder / "korean_dict.txt"
        if rec_path.exists() and dict_path.exists():
            return rec_path, dict_path

    # Auto-download to %APPDATA%\Ocr_it\models if not bundled locally
    cache_dir.mkdir(parents=True, exist_ok=True)
    rec_path = cache_dir / "korean_rec.onnx"
    dict_path = cache_dir / "korean_dict.txt"
    try:
        if not rec_path.exists():
            urllib.request.urlretrieve(KOREAN_MODEL_URL, str(rec_path))
        if not dict_path.exists():
            urllib.request.urlretrieve(KOREAN_DICT_URL, str(dict_path))
    except Exception as exc:
        raise OcrEngineError(
            f"한국어 OCR 모델 다운로드에 실패했습니다: {exc}"
        ) from exc

    return rec_path, dict_path


def _get_ocr_engine() -> Any:
    """Lazily initialize and cache the Korean + English RapidOCR instance."""
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance

    with _engine_lock:
        if _ocr_instance is not None:
            return _ocr_instance
        try:
            from rapidocr_onnxruntime import RapidOCR  # type: ignore
            from rapidocr_onnxruntime.ch_ppocr_v3_rec import TextRecognizer  # type: ignore
        except ImportError as exc:
            raise OcrEngineError(
                "rapidocr-onnxruntime 라이브러리가 설치되어 있지 않습니다.\n"
                "`pip install rapidocr-onnxruntime` 실행 후 다시 시도해 주세요."
            ) from exc

        rec_path, dict_path = _resolve_korean_model_paths()

        # Disable angle cls on upright desktop captures so Korean lines are never flipped 180 deg
        engine = RapidOCR(use_angle_cls=False, text_score=0.35)
        engine.text_recognizer = TextRecognizer(
            {
                "use_cuda": False,
                "model_path": str(rec_path),
                "keys_path": str(dict_path),
                "rec_img_shape": [3, 48, 320],
                "rec_batch_num": 6,
            }
        )
        _ocr_instance = engine
        return _ocr_instance


def _merge_lines_by_y(results: list[Any]) -> str:
    """Group OCR boxes by Y-coordinate and insert spaces based on horizontal X-gap."""
    # Each item: (y_center, x_min, x_max, height, text)
    items: list[tuple[float, float, float, float, str]] = []
    for entry in results:
        if not entry or len(entry) < 2:
            continue
        box, text = entry[0], str(entry[1]).strip()
        if not text:
            continue
        xs = [float(pt[0]) for pt in box]
        ys = [float(pt[1]) for pt in box]
        x_min = min(xs)
        x_max = max(xs)
        y_center = sum(ys) / len(ys)
        height = max(ys) - min(ys)
        items.append((y_center, x_min, x_max, height, text))

    if not items:
        return ""

    items.sort(key=lambda item: (item[0], item[1]))

    lines: list[list[tuple[float, float, float, float, str]]] = []
    for item in items:
        y_center, _x_min, _x_max, height, _text = item
        if not lines:
            lines.append([item])
            continue

        current_line = lines[-1]
        avg_y = sum(el[0] for el in current_line) / len(current_line)
        avg_h = sum(el[3] for el in current_line) / len(current_line)
        tolerance = max(avg_h * 0.5, height * 0.5, 8.0)

        if abs(y_center - avg_y) <= tolerance:
            current_line.append(item)
        else:
            lines.append([item])

    merged_lines: list[str] = []
    for line in lines:
        line.sort(key=lambda el: el[1])
        parts: list[str] = [line[0][4]]
        prev_x_max = line[0][2]
        prev_h = line[0][3]

        for _yc, x_min, x_max, height, text in line[1:]:
            x_gap = x_min - prev_x_max
            ref_h = max(prev_h, height, 12.0)
            if x_gap > ref_h * 0.15:
                parts.append(" ")
            parts.append(text)
            prev_x_max = max(prev_x_max, x_max)
            prev_h = height

        merged_lines.append("".join(parts))

    return "\n".join(merged_lines)


def extract_text(image: Image.Image) -> str:
    """Extract mixed Korean/English/numeric text using RapidOCR."""
    if image is None or image.width < 1 or image.height < 1:
        return ""

    processed = _preprocess_for_ocr(image).convert("RGB")
    img_bgr = np.array(processed)[:, :, ::-1]
    engine = _get_ocr_engine()

    try:
        results, _ = engine(img_bgr)
    except Exception as exc:
        raise OcrEngineError(f"RapidOCR 처리 중 오류가 발생했습니다: {exc}") from exc

    if not results:
        return ""

    return _merge_lines_by_y(results)
