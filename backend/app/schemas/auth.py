"""Pydantic v2 contracts for Hybrid Authentication and Subject Enrollment."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field

TrackType = Literal["MATH", "CODE", "RAG"]


class UserRegisterRequest(BaseModel):
    """Payload for registering a new local student account."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=255)


class UserLoginRequest(BaseModel):
    """Payload for authenticating an existing local student account."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class GoogleAuthRequest(BaseModel):
    """Payload for authenticating or registering via a Google OAuth2 ID token."""

    id_token: str = Field(min_length=10)


class UserResponse(BaseModel):
    """Public profile representation of an authenticated student."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    auth_provider: str
    created_at: datetime


class AuthTokenResponse(BaseModel):
    """JWT Bearer token response paired with the authenticated student's profile."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class SubjectEnrollRequest(BaseModel):
    """Request to enroll the current student in a learning track."""

    track: TrackType


class EnrollmentResponse(BaseModel):
    """Student track enrollment record."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    track: TrackType
    enrolled_at: datetime


class ProblemItemResponse(BaseModel):
    """Curriculum problem item returned to the frontend workspace."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    track: TrackType
    title: str
    prompt: str
    difficulty: str
    symbolic_rules_json: dict[str, Any]
