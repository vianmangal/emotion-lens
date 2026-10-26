from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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
    SAFETY_VISUAL_WEIGHTS_PATH: str = ''
    SAFETY_VISUAL_WEIGHTS_SHA256: str = ''
    SAFETY_VISUAL_HEAD_PATH: str = ''
    SAFETY_VISUAL_HEAD_SHA256: str = ''
    SAFETY_VISUAL_SYNCHRONOUS: bool = False
    SAFETY_PERSON_PATH: str = ''
    SAFETY_PERSON_SHA256: str = ''
    SAFETY_CALL_MODE: str = 'off'
    SAFETY_CALL_PROVIDER: Literal['elevenlabs', 'sarvam'] = 'elevenlabs'
    ELEVENLABS_API_KEY: SecretStr = SecretStr('')
    ELEVENLABS_AGENT_ID: str = ''
    ELEVENLABS_AGENT_PHONE_NUMBER_ID: str = ''
    SARVAM_API_KEY: SecretStr = SecretStr('')
    SARVAM_ORG_ID: str = ''
    SARVAM_WORKSPACE_ID: str = ''
    SARVAM_AGENT_ID: str = ''
    SARVAM_AGENT_VERSION: int = Field(1, ge=1)
    SARVAM_CONNECTION_ID: str = ''
    SARVAM_AGENT_PHONE_NUMBER: SecretStr = SecretStr('')
    SAFETY_ALERT_TO_NUMBER: SecretStr = SecretStr('')
    SAFETY_CALL_GRACE_SECONDS: float = Field(10, ge=1, le=60)
    SAFETY_CALL_COOLDOWN_SECONDS: float = Field(300, ge=1)
    SAFETY_CALL_MAX_PER_HOUR: int = Field(3, ge=1, le=3)
    SAFETY_CLIP_QUOTA_MB: int = Field(500, ge=1, le=5000)
    SAFETY_CLIP_RETENTION_HOURS: int = Field(24, ge=1)
    SAFETY_METADATA_RETENTION_DAYS: int = Field(7, ge=1)
    SAFETY_SESSION_TTL_SECONDS: int = Field(3600, ge=60, le=3600)
    SAFETY_EVENT_ENTRY_SCORE: float = Field(.75, ge=0, le=1, allow_inf_nan=False)
    SAFETY_EVENT_EXIT_SCORE: float = Field(.35, ge=0, le=1, allow_inf_nan=False)
    SAFETY_EVENT_ENTRY_SECONDS: float = Field(.3, ge=0, le=10, allow_inf_nan=False)
    SAFETY_EVENT_QUIET_SECONDS: float = Field(2, gt=0, le=60, allow_inf_nan=False)
    SAFETY_EVENT_COOLDOWN_SECONDS: float = Field(30, ge=0, le=3600, allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_thresholds(self):
        if self.SAFETY_EVENT_EXIT_SCORE >= self.SAFETY_EVENT_ENTRY_SCORE:
            raise ValueError('Event exit score must be below entry score')
        return self

    def event_policy_options(self):
        return {'entry': self.SAFETY_EVENT_ENTRY_SCORE, 'exit': self.SAFETY_EVENT_EXIT_SCORE,
                'entry_seconds': self.SAFETY_EVENT_ENTRY_SECONDS,
                'quiet_seconds': self.SAFETY_EVENT_QUIET_SECONDS,
                'cooldown': self.SAFETY_EVENT_COOLDOWN_SECONDS}

    model_config = SettingsConfigDict(env_file=ROOT / '.env', env_file_encoding='utf-8', extra='ignore')


settings = Settings()
