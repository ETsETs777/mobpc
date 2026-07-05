import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import qrcode
from jose import jwt

from server.config import settings


@dataclass
class PairingSession:
    code: str
    created_at: float
    expires_at: float
    used: bool = False


@dataclass
class AuthManager:
    jwt_secret: str = field(default="")
    pairing_sessions: dict[str, PairingSession] = field(default_factory=dict)
    paired_devices: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        secret_path = settings.data_dir / settings.jwt_secret_file
        if secret_path.exists():
            self.jwt_secret = secret_path.read_text(encoding="utf-8").strip()
        else:
            self.jwt_secret = secrets.token_hex(32)
            secret_path.write_text(self.jwt_secret, encoding="utf-8")

    def create_pairing_code(self) -> PairingSession:
        code = secrets.token_urlsafe(16)
        now = time.time()
        session = PairingSession(
            code=code,
            created_at=now,
            expires_at=now + settings.pairing_ttl_seconds,
        )
        self.pairing_sessions[code] = session
        self._cleanup_expired()
        return session

    def exchange_pairing_code(self, code: str, device_name: str) -> Optional[str]:
        self._cleanup_expired()
        session = self.pairing_sessions.get(code)
        if not session or session.used or time.time() > session.expires_at:
            return None
        session.used = True
        token = self.create_token(device_name)
        self.paired_devices.append(device_name)
        return token

    def create_token(self, device_name: str) -> str:
        payload = {
            "sub": device_name,
            "iat": int(time.time()),
            "exp": int(time.time()) + settings.jwt_expire_days * 86400,
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_token(self, token: str) -> Optional[str]:
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            return payload.get("sub")
        except Exception:
            return None

    def pairing_qr_payload(self, session: PairingSession, host: str, port: int) -> str:
        return json.dumps(
            {
                "type": "mobpc_pairing",
                "host": host,
                "port": port,
                "code": session.code,
            }
        )

    def generate_qr_image(self, data: str, output: Path) -> Path:
        img = qrcode.make(data)
        img.save(output)
        return output

    def _cleanup_expired(self) -> None:
        now = time.time()
        expired = [k for k, v in self.pairing_sessions.items() if v.expires_at < now]
        for key in expired:
            del self.pairing_sessions[key]


auth_manager = AuthManager()
