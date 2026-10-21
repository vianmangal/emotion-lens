import math
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class SessionOptions(StrictModel):
    source: Literal['live', 'replay'] = 'live'
    live_only: bool = False


class ArmOptions(StrictModel):
    phone_mode: Literal['off', 'dry_run', 'real'] = 'off'
    clips: bool = False
    recipient_acknowledged: bool = False
    client_now_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class FrameMessage(StrictModel):
    v: Literal[1]
    session_id: str
    frame_id: int = Field(ge=0)
    captured_ms: float = Field(ge=0)
    jpeg: str = Field(max_length=699052)

    @field_validator('captured_ms')
    @classmethod
    def finite_timestamp(cls, value):
        if not math.isfinite(value):
            raise ValueError('Timestamp must be finite')
        return value


class Review(StrictModel):
    label: Literal['relevant', 'false_alarm', 'unclear', 'unreviewed']


class PhoneTest(StrictModel):
    mode: Literal['dry_run', 'real'] = 'dry_run'
    recipient_acknowledged: bool = False
    request_id: str = Field(min_length=8, max_length=80, pattern=r'^[a-zA-Z0-9-]+$')
