import logging
import platform
import socket
import time
from typing import Any

import mss
import psutil
from PIL import Image
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key
from pynput.mouse import Button, Controller as MouseController

logger = logging.getLogger(__name__)

_mouse = MouseController()
_keyboard = KeyboardController()

_KEY_MAP = {
    "enter": Key.enter,
    "tab": Key.tab,
    "space": Key.space,
    "backspace": Key.backspace,
    "delete": Key.delete,
    "esc": Key.esc,
    "escape": Key.esc,
    "up": Key.up,
    "down": Key.down,
    "left": Key.left,
    "right": Key.right,
    "home": Key.home,
    "end": Key.end,
    "page_up": Key.page_up,
    "page_down": Key.page_down,
    "ctrl": Key.ctrl,
    "alt": Key.alt,
    "shift": Key.shift,
    "win": Key.cmd,
    "cmd": Key.cmd,
    "f1": Key.f1,
    "f2": Key.f2,
    "f3": Key.f3,
    "f4": Key.f4,
    "f5": Key.f5,
    "f6": Key.f6,
    "f7": Key.f7,
    "f8": Key.f8,
    "f9": Key.f9,
    "f10": Key.f10,
    "f11": Key.f11,
    "f12": Key.f12,
}

_BUTTON_MAP = {
    "left": Button.left,
    "right": Button.right,
    "middle": Button.middle,
}


def _resolve_key(key_name: str):
    lower = key_name.lower()
    if lower in _KEY_MAP:
        return _KEY_MAP[lower]
    if len(key_name) == 1:
        return key_name
    return None


class MouseExecutor:
    def move(self, payload: dict[str, Any]) -> dict[str, Any]:
        _mouse.position = (payload["x"], payload["y"])
        return {"x": payload["x"], "y": payload["y"]}

    def click(self, payload: dict[str, Any]) -> dict[str, Any]:
        button = _BUTTON_MAP.get(payload.get("button", "left"), Button.left)
        clicks = int(payload.get("clicks", 1))
        if "x" in payload and "y" in payload:
            _mouse.position = (payload["x"], payload["y"])
        _mouse.click(button, clicks)
        return {"clicked": True}

    def scroll(self, payload: dict[str, Any]) -> dict[str, Any]:
        if "x" in payload and "y" in payload:
            _mouse.position = (payload["x"], payload["y"])
        _mouse.scroll(payload.get("dx", 0), payload.get("dy", 0))
        return {"scrolled": True}

    def drag(self, payload: dict[str, Any]) -> dict[str, Any]:
        button = _BUTTON_MAP.get(payload.get("button", "left"), Button.left)
        _mouse.position = (payload["x1"], payload["y1"])
        with _mouse.pressed(button):
            _mouse.position = (payload["x2"], payload["y2"])
        return {"dragged": True}


class KeyboardExecutor:
    def type_text(self, payload: dict[str, Any]) -> dict[str, Any]:
        _keyboard.type(payload["text"])
        return {"typed": len(payload["text"])}

    def key(self, payload: dict[str, Any]) -> dict[str, Any]:
        key = _resolve_key(payload["key"])
        if key is None:
            raise ValueError(f"Unknown key: {payload['key']}")
        action = payload.get("action", "tap")
        if action == "press":
            _keyboard.press(key)
        elif action == "release":
            _keyboard.release(key)
        else:
            _keyboard.press(key)
            _keyboard.release(key)
        return {"key": payload["key"], "action": action}

    def hotkey(self, payload: dict[str, Any]) -> dict[str, Any]:
        keys = [_resolve_key(k) for k in payload["keys"]]
        if any(k is None for k in keys):
            raise ValueError("Unknown key in hotkey")
        for key in keys:
            _keyboard.press(key)
        for key in reversed(keys):
            _keyboard.release(key)
        return {"keys": payload["keys"]}


class ScreenExecutor:
    def capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        import base64
        import io

        monitor_index = int(payload.get("monitor", 0))
        quality = int(payload.get("quality", 70))
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index >= len(monitors):
                monitor_index = 0
            monitor = monitors[monitor_index] if monitor_index else monitors[1]
            shot = sct.grab(monitor)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality)
            encoded = base64.b64encode(buf.getvalue()).decode("ascii")
            return {
                "image": encoded,
                "width": shot.width,
                "height": shot.height,
            }


class SystemExecutor:
    def ping(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return {"pong": True, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def info(self, _payload: dict[str, Any]) -> dict[str, Any]:
        with mss.mss() as sct:
            primary = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            screen = {"width": primary["width"], "height": primary["height"]}
        return {
            "hostname": socket.gethostname(),
            "os": f"{platform.system()} {platform.release()}",
            "cpu_count": psutil.cpu_count(),
            "memory_total": psutil.virtual_memory().total,
            "screen": screen,
        }


mouse_executor = MouseExecutor()
keyboard_executor = KeyboardExecutor()
screen_executor = ScreenExecutor()
system_executor = SystemExecutor()
