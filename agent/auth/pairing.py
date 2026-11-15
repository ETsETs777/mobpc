"""Привязка устройств: одноразовые коды → JWT с возможностью отзыва."""

import io
import json
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Optional

import qrcode
from jose import jwt

from server.config import settings

# Без похожих символов (0/O, 1/I/L), чтобы код было легко ввести вручную.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LEN = 8
_MAX_FAILS_PER_MINUTE = 20


def normalize_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def format_code(code: str) -> str:
    return f"{code[:4]}-{code[4:]}"


class TooManyAttempts(Exception):
    pass


@dataclass
class PairingSession:
    code: str
    created_at: float
    expires_at: float
    used: bool = False
    device_name: Optional[str] = None

    @property
    def display_code(self) -> str:
        return format_code(self.code)

    @property
    def status(self) -> str:
        if self.used:
            return "paired"
        if time.time() > self.expires_at:
            return "expired"
        return "pending"


@dataclass
class Device:
    id: str
    name: str
    paired_at: float
    last_seen: float = 0.0


class AuthManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.jwt_secret = self._load_secret()
        self.pairing_sessions: dict[str, PairingSession] = {}
        self._devices_path = settings.data_dir / "devices.json"
        self.devices: dict[str, Device] = self._load_devices()
        self._fails: list[float] = []
        self.latest_qr: Optional[bytes] = None

    # ---------- хранение ----------
    def _load_secret(self) -> str:
        path = settings.data_dir / settings.jwt_secret_file
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        secret = secrets.token_hex(32)
        path.write_text(secret, encoding="utf-8")
        return secret

    def _load_devices(self) -> dict[str, Device]:
        if not self._devices_path.exists():
            return {}
        try:
            raw = json.loads(self._devices_path.read_text(encoding="utf-8"))
            return {d["id"]: Device(**d) for d in raw}
        except (OSError, ValueError, TypeError, KeyError):
            return {}

    def _save_devices(self) -> None:
        data = [asdict(d) for d in self.devices.values()]
        tmp = self._devices_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._devices_path)

    # ---------- коды привязки ----------
    def create_pairing_code(self) -> PairingSession:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LEN))
        now = time.time()
        session = PairingSession(
            code=code,
            created_at=now,
            expires_at=now + settings.pairing_ttl_seconds,
        )
        with self._lock:
            self._cleanup_expired()
            self.pairing_sessions[code] = session
        return session

    def get_session(self, code: str) -> Optional[PairingSession]:
        return self.pairing_sessions.get(normalize_code(code))

    def _register_fail(self) -> None:
        now = time.time()
        self._fails = [t for t in self._fails if now - t < 60] + [now]

    def exchange_pairing_code(self, code: str, device_name: str) -> Optional[tuple[str, Device]]:
        """Обменивает код на токен. Код одноразовый и живёт pairing_ttl_seconds."""
        code = normalize_code(code)
        name = (device_name or "Устройство").strip()[:40] or "Устройство"
        with self._lock:
            now = time.time()
            if len([t for t in self._fails if now - t < 60]) >= _MAX_FAILS_PER_MINUTE:
                raise TooManyAttempts()
            session = self.pairing_sessions.get(code)
            if not session or session.used or now > session.expires_at:
                self._register_fail()
                return None
            session.used = True
            session.device_name = name
            device = Device(id=uuid.uuid4().hex, name=name, paired_at=now, last_seen=now)
            self.devices[device.id] = device
            self._save_devices()
        return self.create_token(device), device

    # ---------- токены ----------
    def create_token(self, device: Device) -> str:
        now = int(time.time())
        payload = {
            "sub": device.name,
            "jti": device.id,
            "iat": now,
            "exp": now + settings.jwt_expire_days * 86400,
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_token(self, token: Optional[str]) -> Optional[Device]:
        """Возвращает устройство, если токен валиден и не отозван."""
        if not token:
            return None
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
        except Exception:
            return None
        return self.devices.get(payload.get("jti", ""))

    def touch(self, device_id: str) -> None:
        dev = self.devices.get(device_id)
        if dev:
            dev.last_seen = time.time()
            with self._lock:
                self._save_devices()

    def revoke(self, device_id: str) -> bool:
        with self._lock:
            removed = self.devices.pop(device_id, None)
            if removed:
                self._save_devices()
        return removed is not None

    def list_devices(self) -> list[Device]:
        return sorted(self.devices.values(), key=lambda d: d.paired_at, reverse=True)

    # ---------- QR ----------
    def qr_png(self, data: str) -> bytes:
        qr = qrcode.QRCode(border=2, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color="#1b1f24", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        self.latest_qr = png
        return png

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self.pairing_sessions.items() if v.expires_at + 600 < now]
        for key in expired:
            del self.pairing_sessions[key]


auth_manager = AuthManager()
