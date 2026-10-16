"""SQLModel database models for Users and Subject Enrollments."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


class User(SQLModel, table=True):
    """Registered student account supporting Local (Bcrypt) and Google OAuth2 login."""

    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=255)
    full_name: str = Field(max_length=255)
    hashed_password: Optional[str] = Field(default=None, max_length=255)
    auth_provider: str = Field(default="LOCAL", max_length=32)
    google_sub: Optional[str] = Field(default=None, index=True, unique=True, max_length=255)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now)


class SubjectEnrollment(SQLModel, table=True):
    """Student enrollment in one of the 3 Socratic learning tracks (MATH, CODE, RAG)."""

    __tablename__ = "subject_enrollments"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    track: str = Field(index=True, max_length=16)  # "MATH", "CODE", or "RAG"
    enrolled_at: datetime = Field(default_factory=utc_now)
