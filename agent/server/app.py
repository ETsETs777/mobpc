import json
import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from auth.pairing import auth_manager
from executor.dispatcher import dispatcher
from server.config import settings

logger = logging.getLogger(__name__)


class PairingExchangeRequest(BaseModel):
    code: str
    device_name: str = "mobile"


def _setup_logging() -> None:
    log_file = settings.logs_dir / f"agent_{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def create_app() -> FastAPI:
    _setup_logging()
    app = FastAPI(title="mobpc agent", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "version": "1.0.0"}

    @app.post("/api/pairing")
    async def create_pairing():
        session = auth_manager.create_pairing_code()
        host = settings.host if settings.host != "0.0.0.0" else "127.0.0.1"
        qr_data = auth_manager.pairing_qr_payload(session, host, settings.port)
        qr_path = settings.data_dir / f"pairing_{session.code[:8]}.png"
        auth_manager.generate_qr_image(qr_data, qr_path)
        return {
            "code": session.code,
            "expires_at": session.expires_at,
            "qr_path": str(qr_path),
            "qr_payload": json.loads(qr_data),
        }

    @app.get("/api/pairing/qr")
    async def get_latest_qr():
        png_files = sorted(settings.data_dir.glob("pairing_*.png"), reverse=True)
        if not png_files:
            raise HTTPException(404, "No pairing QR available. POST /api/pairing first.")
        return FileResponse(png_files[0], media_type="image/png")

    @app.post("/api/pairing/exchange")
    async def exchange_pairing(req: PairingExchangeRequest):
        token = auth_manager.exchange_pairing_code(req.code, req.device_name)
        if not token:
            raise HTTPException(401, "Invalid or expired pairing code")
        return {"token": token, "device_name": req.device_name}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        token = websocket.query_params.get("token")
        if not token:
            auth_header = websocket.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:]
        client_id = auth_manager.verify_token(token) if token else None
        if not client_id:
            await websocket.close(code=4401, reason="Unauthorized")
            return

        await websocket.send_json(
            {"type": "connected", "data": {"client": client_id}}
        )
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json(
                        {"id": None, "ok": False, "data": None, "error": "Invalid JSON"}
                    )
                    continue

                msg_id = msg.get("id")
                cmd_type = msg.get("type")
                payload = msg.get("payload") or {}
                try:
                    async def send_event(event: dict) -> None:
                        event["id"] = msg_id
                        await websocket.send_json(event)

                    result = await dispatcher.dispatch(
                        cmd_type, payload, client_id, event_sender=send_event
                    )
                    await websocket.send_json(
                        {"id": msg_id, "ok": True, "data": result, "error": None}
                    )
                except Exception as exc:
                    logger.exception("Command failed: %s", cmd_type)
                    await websocket.send_json(
                        {"id": msg_id, "ok": False, "data": None, "error": str(exc)}
                    )
        except WebSocketDisconnect:
            logger.info("Client disconnected: %s", client_id)

    return app
