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
from executor.shell_files import exec_shell, file_executor
from server.config import settings

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
    def __init__(self) -> None:
        self.rate_limiter = RateLimiter(settings.rate_limit_per_second)
        self._handlers: dict[str, Handler] = {
            "system.ping": self._wrap_sync(system_executor.ping),
            "system.info": self._wrap_sync(system_executor.info),
            "mouse.move": self._wrap_sync(mouse_executor.move),
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
        }

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

    async def dispatch(
        self,
        command_type: str,
        payload: dict[str, Any],
        client_id: str,
        event_sender: Optional[EventSender] = None,
    ) -> dict[str, Any]:
        if not self.rate_limiter.allow(client_id):
            raise PermissionError("Rate limit exceeded")
        handler = self._handlers.get(command_type)
        if handler is None:
            raise ValueError(f"Unknown command: {command_type}")
        logger.info("command=%s client=%s", command_type, client_id)
        if command_type == "shell.exec":
            return await handler(payload or {}, event_sender)
        return await handler(payload or {})

    def register(self, command_type: str, handler: Handler) -> None:
        self._handlers[command_type] = handler


dispatcher = CommandDispatcher()
