"""Durable API budget counters (Cloud Run multi-instance safe)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class RateLimitBucket(SQLModel, table=True):
    """Per-subject counter for a fixed UTC time window.

    `subject_key` is a user id, client IP, or the literal `global`.
    `scope` distinguishes metrics (hourly turns, daily uploads, etc.).
    """

    __tablename__ = "rate_limit_buckets"
    __table_args__ = (
        UniqueConstraint(
            "scope",
            "subject_key",
            "window_start",
            name="uq_rate_limit_scope_subject_window",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    scope: str = Field(index=True, max_length=64)
    subject_key: str = Field(index=True, max_length=128)
    window_start: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    count: int = Field(default=0)
    updated_at: datetime = Field(default_factory=utc_now)
