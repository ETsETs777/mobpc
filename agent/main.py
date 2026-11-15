"""Entry point for mobpc Windows agent.

    python main.py            # запуск агента
    python main.py --open     # и открыть страницу подключения телефона
    python main.py --tunnel   # сразу включить доступ через интернет
    python main.py --port 9000
"""

import argparse
import ctypes
import os
import sys


def _enable_dpi_awareness() -> None:
    """Иначе на экранах с масштабом 125–150% клик по картинке попадёт мимо."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="mobpc — агент удалённого управления ПК")
    parser.add_argument("--port", type=int, help="порт (по умолчанию 8765)")
    parser.add_argument("--host", help="адрес прослушивания (по умолчанию 0.0.0.0)")
    parser.add_argument("--open", action="store_true", help="открыть страницу подключения в браузере")
    parser.add_argument("--tunnel", action="store_true", help="сразу включить доступ через интернет (Cloudflare)")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    if args.port:
        os.environ["MOBPC_PORT"] = str(args.port)
    if args.host:
        os.environ["MOBPC_HOST"] = args.host
    if args.open:
        os.environ["MOBPC_OPEN_BROWSER"] = "1"
    if args.tunnel:
        os.environ["MOBPC_TUNNEL"] = "1"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_enable_dpi_awareness()

import uvicorn  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import settings  # noqa: E402

app = create_app()

if __name__ == "__main__":
    if settings.reload:
        uvicorn.run("main:app", host=settings.host, port=settings.port, reload=True, log_level="info")
    else:
        uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")
