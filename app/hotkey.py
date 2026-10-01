# -*- coding: utf-8 -*-
"""
hotkey.py — 全局热键监听（pynput）
默认 Ctrl+Alt+M，可在设置中修改。
"""
from pynput import keyboard


class HotkeyManager:
    def __init__(self, hotkey_str: str = "<ctrl>+<alt>+m", on_trigger=None):
        self.hotkey_str = hotkey_str
        self.on_trigger = on_trigger
        self._listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> bool:
        """启动监听。热键非法时返回 False。"""
        if self._listener is not None:
            return True
        try:
            self._listener = keyboard.GlobalHotKeys({
                self.hotkey_str: self._fire,
            })
            self._listener.start()
            return True
        except Exception:
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    def _fire(self) -> None:
        if self.on_trigger:
            try:
                self.on_trigger()
            except Exception:
                pass
