from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    DATA_DIR: Path = ROOT / 'data'
    DATABASE_URL: str = f'sqlite+aiosqlite:///{ROOT / "data/emotion-lens.db"}'
    MODEL_PATH: str = ''  # Optional local expression weights; never downloaded at startup.
    CORS_ALLOW_ORIGINS: list[str] = ['http://localhost:5173', 'http://127.0.0.1:5173']
    ALLOWED_HOSTS: list[str] = ['localhost', '127.0.0.1', '[::1]']
    SAFETY_POSE_PATH: str = ''
    SAFETY_POSE_SHA256: str = ''
    SAFETY_TEMPORAL_MODEL: str = 'baseline'
    SAFETY_STGCN_PATH: str = ''
    SAFETY_STGCN_SHA256: str = ''
    SAFETY_STGCN_CONFIG: str = ''
    SAFETY_CALL_MODE: str = 'off'
    ELEVENLABS_API_KEY: SecretStr = SecretStr('')
    ELEVENLABS_AGENT_ID: str = ''
    ELEVENLABS_AGENT_PHONE_NUMBER_ID: str = ''
    SAFETY_ALERT_TO_NUMBER: SecretStr = SecretStr('')
    SAFETY_CALL_GRACE_SECONDS: float = Field(10, ge=1, le=60)
    SAFETY_CALL_COOLDOWN_SECONDS: float = Field(300, ge=1)
    SAFETY_CALL_MAX_PER_HOUR: int = Field(3, ge=1, le=3)
    SAFETY_CLIP_QUOTA_MB: int = Field(500, ge=1, le=5000)
    SAFETY_CLIP_RETENTION_HOURS: int = Field(24, ge=1)
    SAFETY_METADATA_RETENTION_DAYS: int = Field(7, ge=1)

    model_config = SettingsConfigDict(env_file=ROOT / '.env', env_file_encoding='utf-8', extra='ignore')


settings = Settings()
