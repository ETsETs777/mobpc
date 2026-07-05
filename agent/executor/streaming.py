import asyncio
import base64
import io
import logging
from typing import Any, Optional

import mss
from PIL import Image

logger = logging.getLogger(__name__)


class ScreenStreamer:
    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._fps = 10
        self._quality = 50
        self._client_id: Optional[str] = None
        self._send_event = None

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(
        self,
        payload: dict[str, Any],
        client_id: str,
        send_event,
    ) -> dict[str, Any]:
        await self.stop()
        self._fps = int(payload.get("fps", 10))
        self._quality = int(payload.get("quality", 50))
        self._client_id = client_id
        self._send_event = send_event
        self._running = True
        self._task = asyncio.create_task(self._loop())
        return {"streaming": True, "fps": self._fps}

    async def stop(self) -> dict[str, Any]:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        return {"streaming": False}

    async def handle(self, payload: dict[str, Any], client_id: str, send_event) -> dict[str, Any]:
        action = payload.get("action", "start")
        if action == "stop":
            return await self.stop()
        return await self.start(payload, client_id, send_event)

    async def _loop(self) -> None:
        interval = 1.0 / max(self._fps, 1)
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            while self._running:
                try:
                    shot = sct.grab(monitor)
                    img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
                    buf = io.BytesIO()
                    img.save(buf, format="JPEG", quality=self._quality)
                    encoded = base64.b64encode(buf.getvalue()).decode("ascii")
                    if self._send_event:
                        await self._send_event({
                            "type": "screen.stream",
                            "data": {
                                "image": encoded,
                                "width": shot.width,
                                "height": shot.height,
                            },
                        })
                except Exception:
                    logger.exception("Screen stream frame failed")
                await asyncio.sleep(interval)


screen_streamer = ScreenStreamer()
