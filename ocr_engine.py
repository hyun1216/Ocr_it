"""Windows built-in OCR engine wrapper for Ocr_it."""

from __future__ import annotations

import asyncio
import io
import re
from typing import Optional

from PIL import Image


class OcrEngineError(Exception):
    """Raised when the Windows OCR engine cannot process an image."""


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


def _normalize_ocr_result(result: object) -> str:
    """Convert winocr / WinRT OCR result objects into a clean string."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result.strip()

    # winocr may return a dict with 'text' or 'lines', or a WinRT OcrResult
    if isinstance(result, dict):
        if "text" in result and result["text"]:
            return str(result["text"]).strip()
        lines = result.get("lines") or []
        return "\n".join(str(line.get("text", "")).strip() for line in lines if line).strip()

    lines = getattr(result, "lines", None)
    if lines is not None:
        extracted = [str(getattr(line, "text", "")).strip() for line in lines]
        joined = "\n".join(item for item in extracted if item)
        if joined:
            return joined

    text_attr = getattr(result, "text", None)
    if text_attr:
        return str(text_attr).strip()

    return str(result).strip()


def _recognize_with_winocr(image: Image.Image, lang: str) -> str:
    """Run OCR using the winocr package."""
    import winocr  # type: ignore

    rgb_image = image.convert("RGB")

    # Prefer synchronous helper if the installed winocr version provides one
    sync_fn = getattr(winocr, "recognize_pil_sync", None)
    if callable(sync_fn):
        result = sync_fn(rgb_image, lang=lang)
        return _normalize_ocr_result(result)

    async_fn = getattr(winocr, "recognize_pil", None)
    if callable(async_fn):
        coro = async_fn(rgb_image, lang=lang)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            new_loop = asyncio.new_event_loop()
            try:
                result = new_loop.run_until_complete(coro)
            finally:
                new_loop.close()
        else:
            result = asyncio.run(coro)
        return _normalize_ocr_result(result)

    raise OcrEngineError("지원되는 winocr 인식 함수를 찾을 수 없습니다.")


async def _recognize_with_winrt_async(image: Image.Image, lang: str) -> str:
    """Fallback OCR implementation using WinRT / WinSDK Windows.Media.Ocr."""
    try:
        from winrt.windows.globalization import Language  # type: ignore
        from winrt.windows.graphics.imaging import BitmapDecoder  # type: ignore
        from winrt.windows.media.ocr import OcrEngine  # type: ignore
        from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream  # type: ignore
    except ImportError:
        from winsdk.windows.globalization import Language  # type: ignore
        from winsdk.windows.graphics.imaging import BitmapDecoder  # type: ignore
        from winsdk.windows.media.ocr import OcrEngine  # type: ignore
        from winsdk.windows.storage.streams import DataWriter, InMemoryRandomAccessStream  # type: ignore

    language = Language(lang)
    if not OcrEngine.is_language_supported(language):
        raise OcrEngineError(
            f"Windows OCR '{lang}' 언어팩이 설치되어 있지 않습니다. "
            "Windows 설정 > 시간 및 언어 > 언어 및 지역에서 한국어 언어팩을 확인해 주세요."
        )

    engine = OcrEngine.try_create_from_language(language)
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrEngineError("Windows OCR 엔진을 초기화할 수 없습니다.")

    buf = io.BytesIO()
    image.convert("RGBA").save(buf, format="PNG")
    png_bytes = buf.getvalue()

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    software_bitmap = await decoder.get_software_bitmap_async()
    ocr_result = await engine.recognize_async(software_bitmap)
    return _normalize_ocr_result(ocr_result)


def _recognize_with_winrt(image: Image.Image, lang: str) -> str:
    """Synchronous wrapper for the WinRT fallback OCR."""
    new_loop = asyncio.new_event_loop()
    try:
        return new_loop.run_until_complete(_recognize_with_winrt_async(image, lang))
    finally:
        new_loop.close()


def extract_text(image: Image.Image, lang: str = "ko") -> str:
    """Extract text from a PIL Image using Windows built-in OCR (Korean first).

    Tries `winocr` first, then falls back to `winrt` / `winsdk` if `winocr`
    is unavailable or fails.
    """
    if image is None or image.width < 1 or image.height < 1:
        return ""

    winocr_error: Optional[Exception] = None
    try:
        return _recognize_with_winocr(image, lang=lang)
    except ImportError as exc:
        winocr_error = exc
    except Exception as exc:
        winocr_error = exc

    try:
        return _recognize_with_winrt(image, lang=lang)
    except ImportError as exc:
        if isinstance(winocr_error, ImportError):
            raise OcrEngineError(
                "OCR 라이브러리(winocr 또는 winrt)가 설치되어 있지 않습니다.\n"
                "`pip install winocr` 실행 후 다시 시도해 주세요."
            ) from exc
        raise OcrEngineError(
            f"Windows OCR 호출에 실패했습니다: {winocr_error}"
        ) from winocr_error
    except OcrEngineError:
        raise
    except Exception as exc:
        raise OcrEngineError(
            f"Windows OCR 처리 중 오류가 발생했습니다: {exc}"
        ) from exc
