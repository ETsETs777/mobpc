import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Optional

from executor.input import (
    keyboard_executor,
    mouse_executor,
    screen_executor,
    system_executor,
)
from executor.downloads import download_manager
from executor.input_block import input_blocker
from executor.macros import macro_runner
from executor.notify import notify_executor
from executor.streaming import stream_manager
from executor.shell_files import exec_shell, file_executor
from executor.system_control import (
    app_executor,
    clipboard_executor,
    media_executor,
    power_executor,
    process_executor,
    window_executor,
)
from server.config import settings
from server.tunnel import keep_awake

logger = logging.getLogger(__name__)

Handler = Callable[..., Awaitable[dict[str, Any]]]
EventSender = Callable[[dict[str, Any]], Awaitable[None]]


class RateLimiter:
    def __init__(self, max_per_second: int) -> None:
        self.max_per_second = max_per_second
        self._hits: dict[str, list[float]] = defaultdict(list)

    def allow(self, client_id: str) -> bool:
        now = time.time()
        window = self._hits[client_id]
        self._hits[client_id] = [t for t in window if now - t < 1.0]
        if len(self._hits[client_id]) >= self.max_per_second:
            return False
        self._hits[client_id].append(now)
        return True


class CommandDispatcher:
    # Частые команды ввода не пишем в лог, чтобы не засорять его.
    _QUIET = {"mouse.move", "mouse.move_rel", "mouse.scroll", "system.ping", "system.stats", "download.list"}

    def __init__(self) -> None:
        self.rate_limiter = RateLimiter(settings.rate_limit_per_second)
        self._handlers: dict[str, Handler] = {
            "system.ping": self._wrap_sync(system_executor.ping),
            "system.info": self._wrap_sync(system_executor.info),
            "system.stats": self._wrap_sync(system_executor.stats),
            "mouse.move": self._wrap_sync(mouse_executor.move),
            "mouse.move_rel": self._wrap_sync(mouse_executor.move_rel),
            "mouse.button": self._wrap_sync(mouse_executor.button),
            "mouse.click": self._wrap_sync(mouse_executor.click),
            "mouse.scroll": self._wrap_sync(mouse_executor.scroll),
            "mouse.drag": self._wrap_sync(mouse_executor.drag),
            "keyboard.type": self._wrap_sync(keyboard_executor.type_text),
            "keyboard.key": self._wrap_sync(keyboard_executor.key),
            "keyboard.hotkey": self._wrap_sync(keyboard_executor.hotkey),
            "screen.capture": self._wrap_sync(screen_executor.capture),
            "file.list": self._wrap_sync(file_executor.list_dir),
            "file.read": self._wrap_sync(file_executor.read_file),
            "file.write": self._wrap_sync(file_executor.write_file),
            "file.delete": self._wrap_sync(file_executor.delete_file),
            "file.download": self._wrap_sync(file_executor.download_file),
            "shell.exec": self._shell_exec,
            "process.list": self._wrap_sync(process_executor.list_processes),
            "process.kill": self._wrap_sync(process_executor.kill_process),
            "clipboard.get": self._wrap_sync(clipboard_executor.get_clipboard),
            "clipboard.set": self._wrap_sync(clipboard_executor.set_clipboard),
            "window.list": self._wrap_sync(window_executor.list_windows),
            "window.focus": self._wrap_sync(window_executor.focus_window),
            "window.minimize": self._wrap_sync(window_executor.minimize_window),
            "app.launch": self._wrap_sync(app_executor.launch),
            "app.close": self._wrap_sync(window_executor.close_window),
            "power.lock": self._wrap_sync(power_executor.lock),
            "power.sleep": self._wrap_sync(power_executor.sleep),
            "power.shutdown": self._wrap_sync(power_executor.shutdown),
            "power.restart": self._wrap_sync(power_executor.restart),
            "media.play": self._wrap_sync(media_executor.play),
            "media.pause": self._wrap_sync(media_executor.pause),
            "media.volume": self._wrap_sync(media_executor.volume),
            "media.next": self._wrap_sync(media_executor.next_track),
            "media.prev": self._wrap_sync(media_executor.prev_track),
            "screen.stream": self._screen_stream,
            "macro.run": self._macro_run,
            "input.block": self._wrap_sync(input_blocker.set_blocked),
            "notify.send": self._wrap_sync(notify_executor.send),
            "download.start": self._wrap_sync(download_manager.start),
            "download.list": self._wrap_sync(download_manager.list),
            "download.cancel": self._wrap_sync(download_manager.cancel),
            "power.keep_awake": self._wrap_sync(self._keep_awake),
        }

    @staticmethod
    def _keep_awake(payload: dict[str, Any]) -> dict[str, Any]:
        if "enabled" in payload:
            keep_awake.set(bool(payload["enabled"]))
        return {"keep_awake": keep_awake.enabled}

    def _wrap_sync(self, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Handler:
        async def handler(payload: dict[str, Any]) -> dict[str, Any]:
            return await asyncio.to_thread(fn, payload)

        return handler

    async def _shell_exec(
        self,
        payload: dict[str, Any],
        event_sender: Optional[EventSender] = None,
    ) -> dict[str, Any]:
        async def on_stream(stream: str, data: str) -> None:
            if event_sender:
                await event_sender(
                    {"type": "shell.stream", "data": {"stream": stream, "data": data}}
                )

        return await exec_shell(payload, on_stream)

    async def _screen_stream(
        self,
        payload: dict[str, Any],
        event_sender: Optional[EventSender] = None,
        conn_id: str = "",
    ) -> dict[str, Any]:
        return await stream_manager.handle(conn_id or "default", payload, event_sender)

    async def _macro_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await macro_runner.run(payload)

    async def dispatch(
        self,
        command_type: str,
        payload: dict[str, Any],
        client_id: str,
        event_sender: Optional[EventSender] = None,
        conn_id: str = "",
    ) -> dict[str, Any]:
        if not self.rate_limiter.allow(client_id):
            raise PermissionError("Rate limit exceeded")
        handler = self._handlers.get(command_type)
        if handler is None:
            raise ValueError(f"Unknown command: {command_type}")
        if command_type not in self._QUIET:
            logger.info("command=%s client=%s", command_type, client_id)
        if command_type == "shell.exec":
            return await handler(payload or {}, event_sender)
        if command_type == "screen.stream":
            return await handler(payload or {}, event_sender, conn_id)
        return await handler(payload or {})

    @property
    def commands(self) -> list[str]:
        return sorted(self._handlers)

    def register(self, command_type: str, handler: Handler) -> None:
        self._handlers[command_type] = handler


dispatcher = CommandDispatcher()
