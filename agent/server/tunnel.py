"""Доступ через интернет: Cloudflare Quick Tunnel.

Агент запускает cloudflared, тот выдаёт публичный HTTPS-адрес вида
https://<слова>.trycloudflare.com. Не нужны ни аккаунт, ни проброс портов на роутере.
Если cloudflared не установлен, агент скачивает официальный exe с GitHub Cloudflare
в agent/tools (только по явному нажатию кнопки на самом ПК).
"""

import asyncio
import logging
import re
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Any, Optional

from server import prefs
from server.config import settings

logger = logging.getLogger(__name__)

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_REGISTERED_RE = re.compile(r"Registered tunnel connection", re.I)
_DNS_FAIL_RE = re.compile(r"DNS query failed|lookup argotunnel\.com|Could not lookup srv", re.I)
_EDGE_FAIL_RE = re.compile(r"Unable to establish connection with Cloudflare edge|TLS handshake with edge", re.I)
# Если системный DNS не отдаёт SRV-записи (так бывает с VPN), подключаемся к серверам Cloudflare напрямую
_EDGE_FALLBACK = ["--protocol", "http2", "--edge", "region1.v2.argotunnel.com:7844", "--edge", "region2.v2.argotunnel.com:7844"]
_URL_TIMEOUT = 40
_CONNECT_TIMEOUT = 30
_MSG_BLOCKED = ("Сеть этого компьютера не пускает к серверам Cloudflare (порт 7844). "
                "Так бывает при включённом VPN или блокировке у провайдера. "
                "Выключите VPN и попробуйте снова или используйте Tailscale.")


class TunnelError(Exception):
    pass


def find_cloudflared() -> Optional[str]:
    local = TOOLS_DIR / "cloudflared.exe"
    if local.exists() and local.stat().st_size > 5_000_000:
        return str(local)
    return shutil.which("cloudflared")


class TunnelManager:
    def __init__(self) -> None:
        self.state = "off"  # off | downloading | starting | on | error
        self.url: Optional[str] = None
        self.error: Optional[str] = None
        self.progress = 0.0
        self.proc: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "url": self.url,
            "error": self.error,
            "progress": round(self.progress, 3),
            "installed": find_cloudflared() is not None,
            "autostart": bool(prefs.get("tunnel")),
        }

    # ---------- загрузка cloudflared ----------
    def _download_blocking(self) -> str:
        TOOLS_DIR.mkdir(parents=True, exist_ok=True)
        target = TOOLS_DIR / "cloudflared.exe"
        part = target.with_suffix(".part")
        req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "mobpc-agent"})
        with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    self.progress = done / total
        if part.stat().st_size < 5_000_000:
            part.unlink(missing_ok=True)
            raise RuntimeError("Скачанный cloudflared слишком мал — загрузка оборвалась")
        part.replace(target)
        return str(target)

    # ---------- запуск и остановка ----------
    async def start(self) -> dict[str, Any]:
        async with self._lock:
            if self.state in ("on", "starting", "downloading"):
                return self.status()
            self.error = None
            self.url = None
            try:
                exe = find_cloudflared()
                if not exe:
                    self.state = "downloading"
                    self.progress = 0.0
                    exe = await asyncio.to_thread(self._download_blocking)
                self.state = "starting"
                try:
                    await self._launch(exe, [])
                except TunnelError as exc:
                    if str(exc) != "dns":
                        raise
                    logger.info("Tunnel: system DNS can't resolve Cloudflare SRV records, retrying with direct edge hosts")
                    await self._kill()
                    await self._launch(exe, _EDGE_FALLBACK)
                self.state = "on"
                self._reader = asyncio.create_task(self._drain())
                prefs.set_value("tunnel", True)
                logger.info("Tunnel is up: %s", self.url)
            except Exception as exc:
                logger.warning("Tunnel failed: %s", exc)
                await self._kill()
                self.state = "error"
                self.url = None
                if isinstance(exc, TunnelError):
                    self.error = _MSG_BLOCKED if str(exc) in ("dns", "edge") else str(exc)
                elif isinstance(exc, asyncio.TimeoutError):
                    self.error = "Туннель не подключился вовремя. " + _MSG_BLOCKED
                else:
                    self.error = str(exc) or exc.__class__.__name__
            return self.status()

    async def _launch(self, exe: str, extra: list[str]) -> None:
        """Запускает cloudflared и ждёт, пока туннель реально подключится к Cloudflare.

        Адрес выдаётся сразу, но работает он только после строки «Registered tunnel connection».
        """
        self.proc = await asyncio.create_subprocess_exec(
            exe, "tunnel", "--no-autoupdate", *extra, "--url", f"http://127.0.0.1:{settings.port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + _URL_TIMEOUT
        url = None
        edge_fails = 0
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise TunnelError("edge" if url else "cloudflared не выдал адрес. Проверьте подключение к интернету.")
            line = await asyncio.wait_for(self.proc.stdout.readline(), remaining)
            if not line:
                raise TunnelError("cloudflared неожиданно завершился")
            text = line.decode("utf-8", errors="replace")
            m = _URL_RE.search(text)
            if m and not url:
                url = m.group(0)
                self.url = url
                deadline = loop.time() + _CONNECT_TIMEOUT
            elif _REGISTERED_RE.search(text) and url:
                return
            elif _DNS_FAIL_RE.search(text) and not extra:
                raise TunnelError("dns")
            elif _EDGE_FAIL_RE.search(text):
                edge_fails += 1
                if edge_fails >= 4:
                    raise TunnelError("edge")

    async def _drain(self) -> None:
        """Читаем вывод, чтобы буфер не переполнился, и замечаем падение процесса."""
        proc = self.proc
        try:
            while proc and proc.stdout:
                if not await proc.stdout.readline():
                    break
        finally:
            if self.proc is proc and self.state == "on":
                self.state = "error"
                self.error = "Туннель неожиданно закрылся"
                self.url = None

    async def _kill(self) -> None:
        if self._reader:
            self._reader.cancel()
            self._reader = None
        proc, self.proc = self.proc, None
        if proc and proc.returncode is None:
            proc.kill()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                pass

    async def stop(self, remember: bool = True) -> dict[str, Any]:
        async with self._lock:
            await self._kill()
            self.state = "off"
            self.url = None
            self.error = None
            if remember:
                prefs.set_value("tunnel", False)
        return self.status()


tunnel_manager = TunnelManager()


class KeepAwake:
    """Не даёт Windows уснуть, пока работает агент (нужно для удалённого доступа).

    SetThreadExecutionState действует, пока жив вызвавший поток, поэтому держим свой поток.
    """

    _ES_CONTINUOUS = 0x80000000
    _ES_SYSTEM_REQUIRED = 0x00000001

    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    @property
    def enabled(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.SetThreadExecutionState(self._ES_CONTINUOUS | self._ES_SYSTEM_REQUIRED)
        self._stop.wait()
        k32.SetThreadExecutionState(self._ES_CONTINUOUS)

    def set(self, enabled: bool, remember: bool = True) -> bool:
        if enabled and not self.enabled:
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="keep-awake", daemon=True)
            self._thread.start()
        elif not enabled and self.enabled:
            self._stop.set()
            self._thread.join(timeout=2)
            self._thread = None
        if remember:
            prefs.set_value("keep_awake", enabled)
        return self.enabled


keep_awake = KeepAwake()
