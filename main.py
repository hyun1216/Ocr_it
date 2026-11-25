"""Entry point for Ocr_it (오씨알잇) desktop OCR utility."""

from __future__ import annotations

import ctypes
import json
import os
import queue
import sys
import threading
import tkinter as tk
import winreg
from datetime import datetime
from pathlib import Path
from typing import Optional

import keyboard
from PIL import Image

from ocr_engine import OcrEngineError, extract_text, filter_numbers_only
from snipper import ScreenSnipper
from tray import (
    AboutDialog,
    HistoryItem,
    HistoryPopup,
    SettingsDialog,
    ToastNotification,
    TrayController,
    resolve_font_family,
)

APP_NAME = "Ocr_it"
MAX_HISTORY = 15
DEFAULT_HOTKEY = "alt+q"
RUN_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"


def enable_high_dpi() -> None:
    """Apply High-DPI awareness before creating any Tk windows."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_config_path() -> Path:
    """Return the user config file path under %APPDATA%\\Ocr_it\\config.json."""
    appdata = os.environ.get("APPDATA") or str(Path.home())
    config_dir = Path(appdata) / APP_NAME
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.json"


def load_config() -> dict:
    """Load persisted settings or return defaults."""
    path = get_config_path()
    defaults = {"hotkey": DEFAULT_HOTKEY, "numbers_only": False}
    if not path.exists():
        return defaults
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {
            "hotkey": str(data.get("hotkey") or DEFAULT_HOTKEY),
            "numbers_only": bool(data.get("numbers_only", False)),
        }
    except Exception:
        return defaults


def save_config(config: dict) -> None:
    """Persist settings to config.json."""
    try:
        get_config_path().write_text(
            json.dumps(config, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def is_startup_enabled() -> bool:
    """Check whether Ocr_it is registered in Windows startup."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def set_startup_enabled(enabled: bool) -> None:
    """Add or remove Ocr_it from Windows startup registry."""
    if getattr(sys, "frozen", False):
        launch_cmd = f'"{sys.executable}"'
    else:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pythonw if pythonw.exists() else sys.executable)
        launch_cmd = f'"{exe}" "{Path(__file__).resolve()}"'

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass


class OcrItApp:
    """Main application coordinator running Tk on the main thread."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.withdraw()
        self.font_family = resolve_font_family(self.root)

        self.config = load_config()
        self.hotkey: str = self.config["hotkey"]
        self.numbers_only: bool = self.config["numbers_only"]

        self.history: list[HistoryItem] = []
        self._ui_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._active_snipper: Optional[ScreenSnipper] = None
        self._active_history: Optional[HistoryPopup] = None
        self._active_toast: Optional[ToastNotification] = None
        self._hotkey_handle: Optional[object] = None

        self.tray = TrayController(
            hotkey=self.hotkey,
            on_capture=lambda: self._ui_queue.put(("capture", None)),
            on_history=lambda: self._ui_queue.put(("history", None)),
            on_settings=lambda: self._ui_queue.put(("settings", None)),
            on_about=lambda: self._ui_queue.put(("about", None)),
            on_quit=lambda: self._ui_queue.put(("quit", None)),
        )

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text to the Windows clipboard via Tkinter."""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def _register_hotkey(self, hotkey: str) -> bool:
        if self._hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self._hotkey_handle)
            except Exception:
                pass
            self._hotkey_handle = None

        try:
            self._hotkey_handle = keyboard.add_hotkey(
                hotkey,
                lambda: self._ui_queue.put(("capture", None)),
            )
            return True
        except Exception as exc:
            self._show_toast(f"단축키 등록 실패 ({hotkey}): {exc}", is_error=True)
            return False

    def _show_toast(self, message: str, is_error: bool = False) -> None:
        if self._active_toast is not None:
            self._active_toast.close()
        self._active_toast = ToastNotification(
            self.root,
            font_family=self.font_family,
            preview_text=message,
            is_error=is_error,
            duration_ms=1500,
        )

    def _start_capture(self) -> None:
        if self._active_snipper is not None:
            return
        if self._active_history is not None:
            self._active_history.close()
            self._active_history = None

        self._active_snipper = ScreenSnipper(
            self.root,
            on_capture=self._on_image_captured,
            on_cancel=self._on_capture_cancelled,
        )

    def _on_capture_cancelled(self) -> None:
        self._active_snipper = None

    def _on_image_captured(self, image: Image.Image) -> None:
        self._active_snipper = None
        worker = threading.Thread(
            target=self._run_ocr_worker,
            args=(image,),
            daemon=True,
        )
        worker.start()

    def _run_ocr_worker(self, image: Image.Image) -> None:
        try:
            text = extract_text(image, lang="ko")
            if self.numbers_only:
                text = filter_numbers_only(text)
            self._ui_queue.put(("ocr_done", text))
        except OcrEngineError as exc:
            self._ui_queue.put(("ocr_error", str(exc)))
        except Exception as exc:
            self._ui_queue.put(("ocr_error", f"텍스트 추출 실패: {exc}"))

    def _handle_ocr_done(self, text: str) -> None:
        if not text:
            self._show_toast("인식된 텍스트가 없습니다.", is_error=True)
            return

        self.copy_to_clipboard(text)
        item = HistoryItem(
            text=text,
            timestamp=datetime.now().strftime("%H:%M:%S"),
            numbers_only=self.numbers_only,
        )
        self.history.insert(0, item)
        del self.history[MAX_HISTORY:]
        self._show_toast(text)

    def _open_history(self) -> None:
        if self._active_history is not None:
            self._active_history.close()
            self._active_history = None

        self._active_history = HistoryPopup(
            master=self.root,
            font_family=self.font_family,
            history=self.history,
            numbers_only=self.numbers_only,
            hotkey=self.hotkey,
            on_toggle_numbers=self._on_toggle_numbers,
            on_copy_item=self.copy_to_clipboard,
            on_trigger_capture=self._start_capture,
        )

    def _on_toggle_numbers(self, enabled: bool) -> None:
        self.numbers_only = enabled
        self.config["numbers_only"] = enabled
        save_config(self.config)

    def _open_settings(self) -> None:
        SettingsDialog(
            master=self.root,
            font_family=self.font_family,
            current_hotkey=self.hotkey,
            startup_enabled=is_startup_enabled(),
            on_save=self._apply_settings,
        )

    def _apply_settings(self, new_hotkey: str, startup_enabled: bool) -> None:
        if new_hotkey != self.hotkey and self._register_hotkey(new_hotkey):
            self.hotkey = new_hotkey
            self.config["hotkey"] = new_hotkey
            save_config(self.config)
            self.tray.update_hotkey_label(new_hotkey)

        try:
            set_startup_enabled(startup_enabled)
        except OSError as exc:
            self._show_toast(f"시작프로그램 설정 실패: {exc}", is_error=True)
            return

        self._show_toast("설정이 저장되었습니다.")

    def _poll_queue(self) -> None:
        while True:
            try:
                action, payload = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            if action == "capture":
                self._start_capture()
            elif action == "ocr_done":
                self._handle_ocr_done(str(payload))
            elif action == "ocr_error":
                self._show_toast(str(payload), is_error=True)
            elif action == "history":
                self._open_history()
            elif action == "settings":
                self._open_settings()
            elif action == "about":
                AboutDialog(self.root, self.font_family)
            elif action == "quit":
                self.quit()
                return

        self.root.after(50, self._poll_queue)

    def run(self) -> None:
        """Start tray icon, register hotkey, and enter the Tk event loop."""
        self._register_hotkey(self.hotkey)
        self.tray.start()
        self.root.after(50, self._poll_queue)
        self.root.mainloop()

    def quit(self) -> None:
        """Cleanly release hotkeys, tray icon, and Tk loop."""
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass
        self.tray.stop()
        try:
            self.root.quit()
            self.root.destroy()
        except tk.TclError:
            pass


def main() -> None:
    enable_high_dpi()
    app = OcrItApp()
    app.run()


if __name__ == "__main__":
    main()
