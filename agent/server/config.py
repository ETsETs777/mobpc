from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    rate_limit_per_second: int = 50
    screen_default_quality: int = 70


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.logs_dir.mkdir(parents=True, exist_ok=True)
