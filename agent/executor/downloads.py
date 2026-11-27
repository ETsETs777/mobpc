"""Скачивание файлов на компьютер по ссылке — можно «поставить на загрузку» прямо с телефона."""

import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Optional

_CHUNK = 256 * 1024
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class Download:
    id: str
    url: str
    path: str
    status: str = "starting"  # starting | downloading | done | error | cancelled
    received: int = 0
    total: int = 0
    speed: float = 0.0
    error: Optional[str] = None
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id, "url": self.url, "path": self.path, "name": Path(self.path).name,
            "status": self.status, "received": self.received, "total": self.total,
            "speed": round(self.speed), "error": self.error, "started": self.started, "finished": self.finished,
        }


def _filename(url: str, headers) -> str:
    cd = headers.get("Content-Disposition") or ""
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd, re.I) or re.search(r'filename="?([^";]+)"?', cd, re.I)
    name = urllib.parse.unquote(m.group(1)) if m else urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name)
    name = _BAD_CHARS.sub("_", name).strip(" .")
    return name or "download"


def _reserve(path: Path) -> tuple[Path, Path, BinaryIO]:
    for i in range(1000):
        candidate = path if i == 0 else path.with_name(f"{path.stem} ({i}){path.suffix}")
        if candidate.exists():
            continue
        part = candidate.with_name(candidate.name + ".part")
        try:
            output = part.open("xb")
        except FileExistsError:
            continue
        return candidate, part, output
    raise FileExistsError(str(path))


class DownloadManager:
    def __init__(self) -> None:
        self.items: dict[str, Download] = {}

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = str(payload.get("url", "")).strip()
        if not re.match(r"^https?://", url, re.I):
            raise ValueError("Нужна ссылка, начинающаяся с http:// или https://")
        folder = Path(payload.get("dir") or Path.home() / "Downloads").expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        item = Download(id=uuid.uuid4().hex[:12], url=url, path=str(folder / _filename(url, {})))
        self.items[item.id] = item
        threading.Thread(target=self._run, args=(item, folder), daemon=True, name=f"dl-{item.id}").start()
        return item.public()

    def _run(self, item: Download, folder: Path) -> None:
        part: Optional[Path] = None
        try:
            req = urllib.request.Request(item.url, headers={"User-Agent": "Mozilla/5.0 (mobpc)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                content_length = r.headers.get("Content-Length")
                item.total = int(content_length) if content_length is not None else 0
                if item.total < 0:
                    raise ValueError("Некорректный размер загружаемого файла")
                target, part, output = _reserve(folder / _filename(r.geturl(), r.headers))
                item.path = str(target)
                item.status = "downloading"
                window_start, window_bytes = time.time(), 0
                with output as f:
                    while not item.cancel.is_set():
                        chunk = r.read(_CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)
                        item.received += len(chunk)
                        window_bytes += len(chunk)
                        now = time.time()
                        if now - window_start >= 1.0:
                            item.speed = window_bytes / (now - window_start)
                            window_start, window_bytes = now, 0
            if item.cancel.is_set():
                part.unlink(missing_ok=True)
                item.status = "cancelled"
            else:
                if content_length is not None and item.received != item.total:
                    raise IOError(f"Неполная загрузка: получено {item.received} из {item.total} байт")
                part.rename(target)
                item.status = "done"
        except Exception as exc:
            if part:
                part.unlink(missing_ok=True)
            item.status = "error"
            item.error = str(exc)
        finally:
            item.speed = 0.0
            item.finished = time.time()

    def list(self, _payload: dict[str, Any]) -> dict[str, Any]:
        items = sorted(self.items.values(), key=lambda d: d.started, reverse=True)[:20]
        return {"downloads": [d.public() for d in items]}

    def cancel(self, payload: dict[str, Any]) -> dict[str, Any]:
        item = self.items.get(str(payload.get("id", "")))
        if not item:
            raise KeyError("Загрузка не найдена")
        item.cancel.set()
        return {"cancelled": item.id}


download_manager = DownloadManager()
