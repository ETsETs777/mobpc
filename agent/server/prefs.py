"""Небольшие настройки, которые меняются из интерфейса и переживают перезапуск агента."""

import json
import threading
from typing import Any

from server.config import settings

_PATH = settings.data_dir / "prefs.json"
_DEFAULTS: dict[str, Any] = {"keep_awake": False, "tunnel": False}
_lock = threading.Lock()


def load() -> dict[str, Any]:
    try:
        data = json.loads(_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {**_DEFAULTS, **{k: v for k, v in data.items() if k in _DEFAULTS}}


def get(key: str) -> Any:
    return load()[key]


def set_value(key: str, value: Any) -> None:
    with _lock:
        data = load()
        data[key] = value
        tmp = _PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(_PATH)
