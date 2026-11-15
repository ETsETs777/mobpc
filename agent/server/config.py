from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

VERSION = "1.2.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MOBPC_")

    host: str = "0.0.0.0"
    port: int = 8765
    reload: bool = False
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    logs_dir: Path = Path(__file__).resolve().parent.parent / "logs"
    jwt_secret_file: str = "jwt_secret.txt"
    pairing_ttl_seconds: int = 300
    jwt_expire_days: int = 90
    rate_limit_per_second: int = 120
    screen_default_quality: int = 60
    screen_max_width: int = 1280
    shell_timeout_seconds: int = 120
    max_ws_file_bytes: int = 20 * 1024 * 1024
    # Создавать коды привязки можно только с самого ПК (localhost).
    # Включайте только если понимаете риск: любой в сети сможет получить доступ.
    allow_remote_pairing: bool = False
    open_browser: bool = False
    # Включить доступ через интернет (Cloudflare Quick Tunnel) сразу при запуске
    tunnel: bool = False


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.logs_dir.mkdir(parents=True, exist_ok=True)
