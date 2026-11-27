import asyncio
import json
import logging
import socket
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from auth.pairing import TooManyAttempts, auth_manager, format_code
from executor.dispatcher import dispatcher
from executor.streaming import stream_manager
from server import network, prefs
from server.config import VERSION, settings
from server.tunnel import keep_awake, tunnel_manager

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}
_FORWARD_HEADERS = ("x-forwarded-for", "forwarded", "cf-connecting-ip", "x-real-ip")

# Команды, которые могут выполняться долго — запускаем их параллельно,
# чтобы мышь и клавиатура не «замирали», пока работает, например, терминал.
_CONCURRENT = {
    "shell.exec", "macro.run", "file.download", "file.read", "file.list", "file.write",
    "file.delete", "process.list", "window.list", "system.stats", "system.info",
    "screen.capture", "app.launch", "notify.send", "power.sleep",
    "download.start", "download.list", "download.cancel", "power.keep_awake",
}


class PairingExchangeRequest(BaseModel):
    code: str
    device_name: str = "mobile"


@dataclass
class Connection:
    id: str
    device_id: str
    device_name: str
    ip: str
    since: float
    websocket: WebSocket
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    tasks: set = field(default_factory=set)

    async def send(self, message: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_json(message)


class ConnectionRegistry:
    def __init__(self) -> None:
        self.items: dict[str, Connection] = {}

    def online_device_ids(self) -> set[str]:
        return {c.device_id for c in self.items.values()}

    async def close_device(self, device_id: str) -> None:
        for conn in [c for c in self.items.values() if c.device_id == device_id]:
            try:
                await conn.websocket.close(code=4401, reason="Revoked")
            except Exception:
                pass


connections = ConnectionRegistry()
_started_at = time.time()


def _setup_logging() -> None:
    root = logging.getLogger()
    if any(getattr(h, "_mobpc", False) for h in root.handlers):
        return
    log_file = settings.logs_dir / f"agent_{datetime.now():%Y%m%d}.log"
    fh = logging.FileHandler(log_file, encoding="utf-8")
    sh = logging.StreamHandler()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    for h in (fh, sh):
        h.setFormatter(fmt)
        h._mobpc = True  # type: ignore[attr-defined]
        root.addHandler(h)
    root.setLevel(logging.INFO)


def is_local_request(client_host: Optional[str], headers) -> bool:
    """Запрос пришёл с самого ПК, а не из сети и не через туннель (cloudflared)."""
    if client_host not in _LOOPBACK:
        return False
    return not any(h in headers for h in _FORWARD_HEADERS)


def _require_local(request: Request) -> None:
    if settings.allow_remote_pairing:
        return
    host = request.client.host if request.client else None
    if not is_local_request(host, request.headers):
        raise HTTPException(403, "Это действие доступно только на самом компьютере (localhost).")


def _app_url(host: str, code: Optional[str] = None) -> str:
    """host — IP в локальной сети/Tailscale или полный адрес туннеля (https://…)."""
    if host.startswith(("http://", "https://")):
        url = host.rstrip("/") + "/app"
    else:
        url = f"http://{host}:{settings.port}/app"
    return f"{url}#pair={code}" if code else url


def _print_banner() -> None:
    ip = network.best_ip()
    line = "─" * 58
    print(f"\n  {line}")
    print(f"   mobpc {VERSION} — агент запущен")
    print(f"  {line}")
    print(f"   Лендинг проекта:      http://127.0.0.1:{settings.port}/")
    print(f"   Подключить телефон:   http://127.0.0.1:{settings.port}/connect")
    print(f"   Адрес для телефона:   {_app_url(ip)}")
    print(f"  {line}")
    print("   Телефон и ПК должны быть в одной сети Wi-Fi.")
    print("   Остановить агент: Ctrl+C")
    print(f"  {line}\n", flush=True)


def create_app() -> FastAPI:
    _setup_logging()

    async def _start_tunnel_and_report() -> None:
        st = await tunnel_manager.start()
        if st["state"] == "on":
            print(f"   Доступ через интернет: {st['url']}/app", flush=True)
        else:
            print(f"   Туннель не запустился: {st['error']}", flush=True)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        _print_banner()
        saved = prefs.load()
        if saved["keep_awake"]:
            keep_awake.set(True, remember=False)
        if settings.tunnel or saved["tunnel"]:
            asyncio.create_task(_start_tunnel_and_report())
        if settings.open_browser:
            webbrowser.open(f"http://127.0.0.1:{settings.port}/connect")
        yield
        await tunnel_manager.stop(remember=False)
        keep_awake.set(False, remember=False)

    app = FastAPI(title="mobpc agent", version=VERSION, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def no_stale_assets(request: Request, call_next):
        # Браузер перепроверяет файлы по ETag — после обновления никогда не будет старой версии.
        response = await call_next(request)
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    # ---------- веб-интерфейс ----------
    if WEB_DIR.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIR / "assets"), name="assets")

    def _page(name: str) -> FileResponse:
        return FileResponse(WEB_DIR / name, media_type="text/html", headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    async def landing():
        return _page("index.html")

    @app.get("/app", include_in_schema=False)
    async def web_client():
        return _page("app.html")

    @app.get("/connect", include_in_schema=False)
    async def connect_page():
        return _page("connect.html")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    async def manifest():
        return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")

    # ---------- служебные API ----------
    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": VERSION}

    @app.get("/api/status")
    async def status(request: Request):
        host = request.client.host if request.client else None
        return {
            "status": "ok",
            "version": VERSION,
            "hostname": socket.gethostname(),
            "uptime": int(time.time() - _started_at),
            "online": len(connections.items),
            "paired": len(auth_manager.devices),
            "commands": len(dispatcher.commands),
            "remote": bool(request.headers.get("cf-connecting-ip")),
            "local": is_local_request(host, request.headers),
        }

    @app.get("/api/network")
    async def network_info(request: Request):
        _require_local(request)
        return {"port": settings.port, "addresses": network.list_addresses()}

    # ---------- доступ через интернет ----------
    @app.get("/api/tunnel")
    async def tunnel_status(request: Request):
        _require_local(request)
        return {**tunnel_manager.status(), "keep_awake": keep_awake.enabled}

    @app.post("/api/tunnel/start")
    async def tunnel_start(request: Request):
        _require_local(request)
        asyncio.create_task(tunnel_manager.start())
        await asyncio.sleep(0.2)
        return {**tunnel_manager.status(), "keep_awake": keep_awake.enabled}

    @app.post("/api/tunnel/stop")
    async def tunnel_stop(request: Request):
        _require_local(request)
        return {**await tunnel_manager.stop(), "keep_awake": keep_awake.enabled}

    @app.post("/api/keep-awake")
    async def set_keep_awake(request: Request, enabled: bool = Query(...)):
        _require_local(request)
        return {"keep_awake": keep_awake.set(enabled)}

    @app.get("/api/commands")
    async def commands():
        return {"commands": dispatcher.commands}

    # ---------- привязка ----------
    @app.post("/api/pairing")
    async def create_pairing(request: Request, host: Optional[str] = Query(None)):
        _require_local(request)
        host = host or network.best_ip()
        session = auth_manager.create_pairing_code()
        url = _app_url(host, session.code)
        auth_manager.qr_png(url)
        return {
            "code": session.code,
            "display_code": session.display_code,
            "expires_at": session.expires_at,
            "ttl": settings.pairing_ttl_seconds,
            "host": host,
            "port": settings.port,
            "app_url": url,
            "qr_url": f"/api/pairing/{session.code}/qr.png?host={host}",
            # Старый формат QR для Flutter-приложения
            "qr_payload": {"type": "mobpc_pairing", "host": host, "port": settings.port, "code": session.code},
        }

    @app.get("/api/pairing/qr")
    async def get_latest_qr(request: Request):
        _require_local(request)
        if not auth_manager.latest_qr:
            raise HTTPException(404, "No pairing QR available. POST /api/pairing first.")
        return Response(auth_manager.latest_qr, media_type="image/png")

    @app.get("/api/pairing/{code}")
    async def pairing_status(code: str, request: Request):
        _require_local(request)
        session = auth_manager.get_session(code)
        if not session:
            raise HTTPException(404, "Unknown code")
        return {
            "code": session.code,
            "display_code": session.display_code,
            "status": session.status,
            "device_name": session.device_name,
            "expires_in": max(0, int(session.expires_at - time.time())),
        }

    @app.get("/api/pairing/{code}/qr.png")
    async def pairing_qr(code: str, request: Request, host: Optional[str] = Query(None)):
        _require_local(request)
        session = auth_manager.get_session(code)
        if not session:
            raise HTTPException(404, "Unknown code")
        png = auth_manager.qr_png(_app_url(host or network.best_ip(), session.code))
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/api/pairing/exchange")
    async def exchange_pairing(req: PairingExchangeRequest):
        try:
            result = auth_manager.exchange_pairing_code(req.code, req.device_name)
        except TooManyAttempts:
            raise HTTPException(429, "Слишком много неверных кодов. Подождите минуту.")
        if not result:
            raise HTTPException(401, "Код неверный или устарел. Обновите QR на компьютере.")
        token, device = result
        logger.info("Paired new device: %s (%s)", device.name, device.id[:8])
        return {
            "token": token,
            "device_name": device.name,
            "device_id": device.id,
            "hostname": socket.gethostname(),
        }

    # ---------- устройства ----------
    @app.get("/api/devices")
    async def list_devices(request: Request):
        _require_local(request)
        online = connections.online_device_ids()
        return {
            "devices": [
                {
                    "id": d.id,
                    "name": d.name,
                    "paired_at": d.paired_at,
                    "last_seen": d.last_seen,
                    "online": d.id in online,
                }
                for d in auth_manager.list_devices()
            ]
        }

    @app.delete("/api/devices/{device_id}")
    async def revoke_device(device_id: str, request: Request):
        _require_local(request)
        if not auth_manager.revoke(device_id):
            raise HTTPException(404, "Unknown device")
        await connections.close_device(device_id)
        return {"revoked": device_id}

    # ---------- файлы по HTTP (большие файлы, без base64) ----------
    @app.get("/api/files/download")
    async def download(request: Request, path: str, token: Optional[str] = None):
        if not token:
            auth = request.headers.get("authorization", "")
            token = auth[7:] if auth.lower().startswith("bearer ") else None
        device = auth_manager.verify_token(token)
        if not device:
            raise HTTPException(401, "Unauthorized")
        p = Path(path)
        if not p.is_file():
            raise HTTPException(404, "File not found")
        logger.info("download path=%s client=%s", p, device.name)
        return FileResponse(p, filename=p.name)

    # ---------- WebSocket ----------
    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        token = websocket.query_params.get("token")
        if not token:
            auth_header = websocket.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:]
        device = auth_manager.verify_token(token)
        if not device:
            await websocket.close(code=4401, reason="Unauthorized")
            return

        conn = Connection(
            id=uuid.uuid4().hex,
            device_id=device.id,
            device_name=device.name,
            ip=websocket.client.host if websocket.client else "?",
            since=time.time(),
            websocket=websocket,
        )
        connections.items[conn.id] = conn
        auth_manager.touch(device.id)
        logger.info("Client connected: %s from %s", device.name, conn.ip)

        await conn.send({"type": "connected", "data": {"client": device.name, "hostname": socket.gethostname(), "version": VERSION}})

        async def run_command(msg_id: Any, cmd_type: str, payload: dict) -> None:
            async def send_event(event: dict) -> None:
                event["id"] = msg_id
                await conn.send(event)

            try:
                result = await dispatcher.dispatch(
                    cmd_type, payload, device.name, event_sender=send_event, conn_id=conn.id
                )
                await conn.send({"id": msg_id, "ok": True, "data": result, "error": None})
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Command failed: %s: %s", cmd_type, exc)
                try:
                    await conn.send({"id": msg_id, "ok": False, "data": None, "error": str(exc)})
                except Exception:
                    pass

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await conn.send({"id": None, "ok": False, "data": None, "error": "Invalid JSON"})
                    continue
                if not isinstance(msg, dict):
                    await conn.send({"id": None, "ok": False, "data": None, "error": "Command must be a JSON object"})
                    continue
                msg_id = msg.get("id")
                cmd_type = msg.get("type")
                payload = msg.get("payload", {})
                if payload is None:
                    payload = {}
                if not isinstance(cmd_type, str) or not cmd_type.strip():
                    await conn.send({"id": msg_id, "ok": False, "data": None, "error": "Command type must be a non-empty string"})
                    continue
                if not isinstance(payload, dict):
                    await conn.send({"id": msg_id, "ok": False, "data": None, "error": "Command payload must be a JSON object"})
                    continue
                if cmd_type in _CONCURRENT:
                    task = asyncio.create_task(run_command(msg_id, cmd_type, payload))
                    conn.tasks.add(task)
                    task.add_done_callback(conn.tasks.discard)
                else:
                    await run_command(msg_id, cmd_type, payload)
        except WebSocketDisconnect:
            pass
        except RuntimeError:
            pass  # сокет закрыт сервером (например, устройство отозвано)
        finally:
            logger.info("Client disconnected: %s", device.name)
            connections.items.pop(conn.id, None)
            await stream_manager.stop(conn.id)
            for task in list(conn.tasks):
                task.cancel()
            auth_manager.touch(device.id)

    return app
