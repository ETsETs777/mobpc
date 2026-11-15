import getpass
import logging
import os
import platform
import socket
import time
from typing import Any

import mss
import psutil
from pynput.keyboard import Controller as KeyboardController
from pynput.keyboard import Key, KeyCode
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
    "insert": Key.insert,
    "caps_lock": Key.caps_lock,
    "print_screen": Key.print_screen,
    "menu": Key.menu,
}

_BUTTON_MAP = {
    "left": Button.left,
    "right": Button.right,
    "middle": Button.middle,
}


# Виртуальные коды клавиш для знаков препинания (не зависят от раскладки)
_VK_PUNCT = {".": 0xBE, ",": 0xBC, "/": 0xBF, ";": 0xBA, "'": 0xDE, "[": 0xDB, "]": 0xDD,
             "-": 0xBD, "=": 0xBB, "`": 0xC0, "\\": 0xDC}


def _resolve_key(key_name: str):
    lower = key_name.lower()
    if lower in _KEY_MAP:
        return _KEY_MAP[lower]
    if len(key_name) == 1:
        return key_name
    return None


def _resolve_shortcut_key(key_name: str):
    """Для сочетаний нужна физическая клавиша, а не символ: иначе Ctrl+C не сработает
    на русской раскладке (pynput напечатает «c» как Unicode-символ без Ctrl)."""
    if len(key_name) == 1:
        ch = key_name.lower()
        if ch.isascii() and ch.isalnum():
            return KeyCode.from_vk(ord(ch.upper()))
        if ch in _VK_PUNCT:
            return KeyCode.from_vk(_VK_PUNCT[ch])
    return _resolve_key(key_name)


class MouseExecutor:
    def move(self, payload: dict[str, Any]) -> dict[str, Any]:
        _mouse.position = (payload["x"], payload["y"])
        return {"x": payload["x"], "y": payload["y"]}

    def move_rel(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Относительное перемещение — режим тачпада."""
        dx = int(round(float(payload.get("dx", 0))))
        dy = int(round(float(payload.get("dy", 0))))
        if dx or dy:
            _mouse.move(dx, dy)
        x, y = _mouse.position
        return {"x": x, "y": y}

    def button(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Нажать/отпустить кнопку мыши — для перетаскивания с тачпада."""
        button = _BUTTON_MAP.get(payload.get("button", "left"), Button.left)
        if payload.get("action", "press") == "release":
            _mouse.release(button)
        else:
            _mouse.press(button)
        return {"button": payload.get("button", "left"), "action": payload.get("action", "press")}

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
        key = _resolve_shortcut_key(payload["key"])
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
        keys = [_resolve_shortcut_key(k) for k in payload["keys"]]
        if any(k is None for k in keys):
            raise ValueError("Unknown key in hotkey")
        for key in keys:
            _keyboard.press(key)
        for key in reversed(keys):
            _keyboard.release(key)
        return {"keys": payload["keys"]}


class ScreenExecutor:
    def capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        from executor.streaming import grab_frame

        frame = grab_frame(
            monitor=int(payload.get("monitor", 0)),
            quality=int(payload.get("quality", 70)),
            max_width=int(payload.get("max_width", 1920)),
        )
        frame.pop("_digest", None)
        return frame


def _keep_awake_enabled() -> bool:
    from server.tunnel import keep_awake

    return keep_awake.enabled


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

    def stats(self, _payload: dict[str, Any]) -> dict[str, Any]:
        """Живые показатели ПК для панели «Система»."""
        vm = psutil.virtual_memory()
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        try:
            du = psutil.disk_usage(drive)
            disk = {"path": drive, "used": du.used, "total": du.total, "percent": du.percent}
        except OSError:
            disk = None
        battery = None
        try:
            bat = psutil.sensors_battery()
            if bat is not None:
                battery = {"percent": round(bat.percent), "plugged": bool(bat.power_plugged)}
        except Exception:
            battery = None
        return {
            "hostname": socket.gethostname(),
            "user": getpass.getuser(),
            "os": f"{platform.system()} {platform.release()}",
            "cpu": psutil.cpu_percent(interval=0.25),
            "cpu_count": psutil.cpu_count(),
            "ram": {"used": vm.used, "total": vm.total, "percent": vm.percent},
            "disk": disk,
            "battery": battery,
            "uptime": int(time.time() - psutil.boot_time()),
            "processes": len(psutil.pids()),
            "keep_awake": _keep_awake_enabled(),
        }


mouse_executor = MouseExecutor()
keyboard_executor = KeyboardExecutor()
screen_executor = ScreenExecutor()
system_executor = SystemExecutor()
