import ctypes
import os
import subprocess
from typing import Any

import psutil

try:
    import win32clipboard
    import win32con
    import win32gui
    import win32process
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


class ProcessExecutor:
    def list_processes(self, _payload: dict[str, Any]) -> dict[str, Any]:
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = proc.info
                mem = info.get("memory_info")
                processes.append({
                    "pid": info["pid"],
                    "name": info["name"] or "",
                    "cpu": info.get("cpu_percent") or 0,
                    "memory": mem.rss if mem else 0,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        processes.sort(key=lambda p: p["memory"], reverse=True)
        return {"processes": processes[:100]}

    def kill_process(self, payload: dict[str, Any]) -> dict[str, Any]:
        pid = int(payload["pid"])
        proc = psutil.Process(pid)
        proc.kill()
        return {"killed": pid}


class ClipboardExecutor:
    def get_clipboard(self, _payload: dict[str, Any]) -> dict[str, Any]:
        if not HAS_WIN32:
            raise RuntimeError("pywin32 required for clipboard")
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                text = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            else:
                text = ""
        finally:
            win32clipboard.CloseClipboard()
        return {"text": text or ""}

    def set_clipboard(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not HAS_WIN32:
            raise RuntimeError("pywin32 required for clipboard")
        text = payload.get("text", "")
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        finally:
            win32clipboard.CloseClipboard()
        return {"set": True}


class WindowExecutor:
    def list_windows(self, _payload: dict[str, Any]) -> dict[str, Any]:
        if not HAS_WIN32:
            raise RuntimeError("pywin32 required for windows")
        windows = []

        def callback(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    windows.append({
                        "hwnd": int(hwnd),
                        "title": title,
                        "visible": True,
                    })
            return True

        win32gui.EnumWindows(callback, None)
        return {"windows": windows}

    def focus_window(self, payload: dict[str, Any]) -> dict[str, Any]:
        hwnd = int(payload["hwnd"])
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        return {"focused": hwnd}

    def minimize_window(self, payload: dict[str, Any]) -> dict[str, Any]:
        hwnd = int(payload["hwnd"])
        win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
        return {"minimized": hwnd}

    def close_window(self, payload: dict[str, Any]) -> dict[str, Any]:
        hwnd = int(payload["hwnd"])
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        return {"closed": hwnd}


class AppExecutor:
    def launch(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = payload["path"]
        args = payload.get("args", "")
        if args:
            subprocess.Popen(f'"{path}" {args}', shell=True)
        else:
            os.startfile(path)
        return {"launched": path}


class PowerExecutor:
    def lock(self, _payload: dict[str, Any]) -> dict[str, Any]:
        ctypes.windll.user32.LockWorkStation()
        return {"locked": True}

    def sleep(self, _payload: dict[str, Any]) -> dict[str, Any]:
        subprocess.run(
            ["powershell", "-Command", "Add-Type -Assembly System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState('Suspend',$false,$false)"],
            check=False,
        )
        return {"sleep": True}

    def shutdown(self, _payload: dict[str, Any]) -> dict[str, Any]:
        subprocess.run(["shutdown", "/s", "/t", "5"], check=False)
        return {"shutdown": True}

    def restart(self, _payload: dict[str, Any]) -> dict[str, Any]:
        subprocess.run(["shutdown", "/r", "/t", "5"], check=False)
        return {"restart": True}


class MediaExecutor:
    def _send_media_key(self, vk: int) -> dict[str, Any]:
        # VK codes for media keys
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
        return {"sent": vk}

    def play(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return self._send_media_key(0xB3)  # VK_MEDIA_PLAY_PAUSE

    def pause(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return self._send_media_key(0xB3)

    def next_track(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return self._send_media_key(0xB0)  # VK_MEDIA_NEXT_TRACK

    def prev_track(self, _payload: dict[str, Any]) -> dict[str, Any]:
        return self._send_media_key(0xB1)  # VK_MEDIA_PREV_TRACK

    def volume(self, payload: dict[str, Any]) -> dict[str, Any]:
        level = payload.get("level")
        if level == "mute":
            return self._send_media_key(0xAD)
        if level == "unmute":
            return self._send_media_key(0xAD)
        if isinstance(level, str) and level.lstrip("-").isdigit():
            level = int(level)
        if isinstance(level, int):
            vk = 0xAF if level > 0 else 0xAE  # volume up / down
            for _ in range(abs(level)):
                self._send_media_key(vk)
            return {"volume": level}
        return self._send_media_key(0xAF)


process_executor = ProcessExecutor()
clipboard_executor = ClipboardExecutor()
window_executor = WindowExecutor()
app_executor = AppExecutor()
power_executor = PowerExecutor()
media_executor = MediaExecutor()
