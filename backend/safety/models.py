import uuid
import time
from sqlalchemy import String, Float, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base


def new_id():
    return str(uuid.uuid4())


class Incident(Base):
    __tablename__ = 'safety_events'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String)
    captured_at: Mapped[float] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time, index=True)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    event_type: Mapped[str] = mapped_column(String, default='possible_striking_motion')
    status: Mapped[str] = mapped_column(String, default='active')
    model_version: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    threshold_version: Mapped[str] = mapped_column(String, default='experimental-v1')
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    track_ids: Mapped[list] = mapped_column(JSON, default=list)
    review_label: Mapped[str] = mapped_column(String, default='unreviewed')
    source: Mapped[str] = mapped_column(String, default='live')
    clip_name: Mapped[str | None] = mapped_column(String, nullable=True)
    clip_status: Mapped[str] = mapped_column(String, default='off')
    clip_details: Mapped[dict] = mapped_column(JSON, default=dict)


class Action(Base):
    __tablename__ = 'safety_actions'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    event_id: Mapped[str | None] = mapped_column(ForeignKey('safety_events.id', ondelete='SET NULL'), nullable=True)
    dedup_key: Mapped[str] = mapped_column(String, unique=True)
    mode: Mapped[str] = mapped_column(String)
    action_type: Mapped[str] = mapped_column(String, default='phone')
    recipient_alias: Mapped[str] = mapped_column(String, default='configured recipient')
    state: Mapped[str] = mapped_column(String, default='countdown')
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    due_at: Mapped[float] = mapped_column(Float)
    attempt_at: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    provider_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    error_category: Mapped[str | None] = mapped_column(String, nullable=True)
