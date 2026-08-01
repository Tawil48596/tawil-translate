from __future__ import annotations

import ctypes
import os

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_T = 0x54


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint),
        ("pt_x", ctypes.c_long),
        ("pt_y", ctypes.c_long),
    ]


class GlobalHotkey(QObject, QAbstractNativeEventFilter):
    activated = Signal()

    def __init__(self, hotkey_id: int = 0x5457) -> None:
        QObject.__init__(self)
        QAbstractNativeEventFilter.__init__(self)
        self.hotkey_id = hotkey_id
        self.registered = False

    def register(self) -> bool:
        if os.name != "nt":
            return False
        self.registered = bool(
            ctypes.windll.user32.RegisterHotKey(None, self.hotkey_id, MOD_CONTROL | MOD_SHIFT, VK_T)
        )
        return self.registered

    def close(self) -> None:
        if self.registered:
            ctypes.windll.user32.UnregisterHotKey(None, self.hotkey_id)
            self.registered = False

    def nativeEventFilter(self, event_type, message):
        if os.name == "nt":
            event = ctypes.cast(int(message), ctypes.POINTER(_MSG)).contents
            if event.message == WM_HOTKEY and event.wParam == self.hotkey_id:
                self.activated.emit()
                return True, 0
        return False, 0
