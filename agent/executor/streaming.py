"""Захват и трансляция экрана.

Захват идёт в отдельных потоках (не блокирует event loop), кадр уменьшается
до max_width и не отправляется повторно, если экран не изменился.
"""

import asyncio
import base64
import hashlib
import io
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Awaitable, Callable, Optional

import mss
from PIL import Image

from server.config import settings

logger = logging.getLogger(__name__)

_capture_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="capture")
_local = threading.local()
_KEYFRAME_INTERVAL = 2.0  # даже на статичном экране шлём кадр раз в 2 секунды

EventSender = Callable[[dict[str, Any]], Awaitable[None]]


def _sct() -> "mss.base.MSSBase":
    # mss на Windows привязан к потоку, поэтому у каждого потока свой экземпляр.
    sct = getattr(_local, "sct", None)
    if sct is None:
        sct = mss.mss()
        _local.sct = sct
    return sct


def grab_frame(monitor: int = 0, quality: int = 60, max_width: int = 1280) -> dict[str, Any]:
    """Снимок экрана в JPEG. width/height — реальный размер монитора (для координат мыши)."""
    sct = _sct()
    monitors = sct.monitors
    idx = monitor if 1 <= monitor < len(monitors) else (1 if len(monitors) > 1 else 0)
    mon = monitors[idx]
    shot = sct.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    if max_width and img.width > max_width:
        img = img.resize((max_width, round(img.height * max_width / img.width)), Image.BILINEAR)
    digest = hashlib.blake2b(img.tobytes(), digest_size=12).digest()
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=max(10, min(95, quality)))
    return {
        "image": base64.b64encode(buf.getvalue()).decode("ascii"),
        "width": shot.width,
        "height": shot.height,
        "left": mon["left"],
        "top": mon["top"],
        "img_width": img.width,
        "img_height": img.height,
        "monitor": idx,
        "monitors": len(monitors) - 1,
        "_digest": digest,
    }


async def grab_frame_async(**kwargs: Any) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_capture_pool, lambda: grab_frame(**kwargs))


class ScreenStream:
    def __init__(self, send_event: EventSender, payload: dict[str, Any]) -> None:
        self.send_event = send_event
        self.fps = max(1, min(30, int(payload.get("fps", 10))))
        self.quality = int(payload.get("quality", settings.screen_default_quality))
        self.max_width = int(payload.get("max_width", settings.screen_max_width))
        self.monitor = int(payload.get("monitor", 0))
        self.frames_sent = 0
        self.task: Optional[asyncio.Task] = None

    def start(self) -> None:
        self.task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _loop(self) -> None:
        interval = 1.0 / self.fps
        last_digest = None
        last_sent = 0.0
        while True:
            started = time.monotonic()
            try:
                frame = await grab_frame_async(
                    monitor=self.monitor, quality=self.quality, max_width=self.max_width
                )
                digest = frame.pop("_digest")
                if digest != last_digest or started - last_sent > _KEYFRAME_INTERVAL:
                    await self.send_event({"type": "screen.stream", "data": frame})
                    last_digest, last_sent = digest, time.monotonic()
                    self.frames_sent += 1
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Screen stream frame failed")
                await asyncio.sleep(1.0)
            await asyncio.sleep(max(0.0, interval - (time.monotonic() - started)))


class StreamManager:
    """Отдельный поток экрана на каждое WebSocket-подключение."""

    def __init__(self) -> None:
        self._streams: dict[str, ScreenStream] = {}

    @property
    def active(self) -> int:
        return len(self._streams)

    async def handle(self, conn_id: str, payload: dict[str, Any], send_event: Optional[EventSender]) -> dict[str, Any]:
        action = payload.get("action", "start")
        await self.stop(conn_id)
        if action == "stop":
            return {"streaming": False}
        if send_event is None:
            raise RuntimeError("screen.stream requires a live connection")
        stream = ScreenStream(send_event, payload)
        self._streams[conn_id] = stream
        stream.start()
        return {"streaming": True, "fps": stream.fps, "max_width": stream.max_width}

    async def stop(self, conn_id: str) -> None:
        stream = self._streams.pop(conn_id, None)
        if stream:
            await stream.stop()


stream_manager = StreamManager()
