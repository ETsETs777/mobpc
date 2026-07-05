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
from server.config import settings

logger = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


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
        }
        self._stream_task: Optional[asyncio.Task] = None
        self._stream_ws = None

    def _wrap_sync(self, fn: Callable[[dict[str, Any]], dict[str, Any]]) -> Handler:
        async def handler(payload: dict[str, Any]) -> dict[str, Any]:
            return await asyncio.to_thread(fn, payload)

        return handler

    async def dispatch(
        self, command_type: str, payload: dict[str, Any], client_id: str
    ) -> dict[str, Any]:
        if not self.rate_limiter.allow(client_id):
            raise PermissionError("Rate limit exceeded")
        handler = self._handlers.get(command_type)
        if handler is None:
            raise ValueError(f"Unknown command: {command_type}")
        logger.info("command=%s client=%s", command_type, client_id)
        return await handler(payload or {})

    def register(self, command_type: str, handler: Handler) -> None:
        self._handlers[command_type] = handler


dispatcher = CommandDispatcher()
