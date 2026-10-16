"""Database-backed API budget enforcement (turns, uploads, registration, global ceiling)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.config import get_settings
from backend.app.models.rate_limit import RateLimitBucket, utc_now

SCOPE_TURNS_HOUR = "turns_hour"
SCOPE_TURNS_DAY = "turns_day"
SCOPE_UPLOADS_DAY = "uploads_day"
SCOPE_GLOBAL_TURNS_DAY = "global_turns_day"
SCOPE_REGISTER_IP_DAY = "register_ip_day"
GLOBAL_SUBJECT = "global"


def hour_window_start(now: datetime) -> datetime:
    """Truncate to the start of the UTC hour."""
    aware = now.astimezone(timezone.utc)
    return aware.replace(minute=0, second=0, microsecond=0)


def day_window_start(now: datetime) -> datetime:
    """Truncate to the start of the UTC day."""
    aware = now.astimezone(timezone.utc)
    return aware.replace(hour=0, minute=0, second=0, microsecond=0)


def seconds_until(next_boundary: datetime, now: datetime) -> int:
    """Seconds until `next_boundary`, floored at 1 for Retry-After."""
    delta = int((next_boundary - now.astimezone(timezone.utc)).total_seconds())
    return max(1, delta)


def retry_after_hour(now: datetime) -> int:
    """Seconds remaining in the current UTC hour window."""
    return seconds_until(hour_window_start(now) + timedelta(hours=1), now)


def retry_after_day(now: datetime) -> int:
    """Seconds remaining in the current UTC day window."""
    return seconds_until(day_window_start(now) + timedelta(days=1), now)


def client_ip_from_request(request: Request) -> str:
    """Best-effort client IP (honors X-Forwarded-For on Cloud Run)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or "unknown"
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


async def _get_or_create_bucket(
    session: AsyncSession,
    *,
    scope: str,
    subject_key: str,
    window_start: datetime,
) -> RateLimitBucket:
    """Fetch the bucket row, creating it at count=0 when missing."""
    result = await session.exec(
        select(RateLimitBucket).where(
            RateLimitBucket.scope == scope,
            RateLimitBucket.subject_key == subject_key,
            RateLimitBucket.window_start == window_start,
        )
    )
    bucket = result.first()
    if bucket is not None:
        return bucket

    bucket = RateLimitBucket(
        scope=scope,
        subject_key=subject_key,
        window_start=window_start,
        count=0,
    )
    session.add(bucket)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        result = await session.exec(
            select(RateLimitBucket).where(
                RateLimitBucket.scope == scope,
                RateLimitBucket.subject_key == subject_key,
                RateLimitBucket.window_start == window_start,
            )
        )
        bucket = result.first()
        assert bucket is not None
    return bucket


async def consume_quota(
    session: AsyncSession,
    *,
    scope: str,
    subject_key: str,
    window_start: datetime,
    limit: int,
    retry_after_seconds: int,
    detail: str,
    status_code: int = status.HTTP_429_TOO_MANY_REQUESTS,
) -> None:
    """Increment a durable counter; raise HTTPException when `limit` is exceeded."""
    if limit <= 0:
        headers = (
            {"Retry-After": str(retry_after_seconds)}
            if status_code == status.HTTP_429_TOO_MANY_REQUESTS
            else None
        )
        raise HTTPException(status_code=status_code, detail=detail, headers=headers)

    bucket = await _get_or_create_bucket(
        session,
        scope=scope,
        subject_key=subject_key,
        window_start=window_start,
    )
    if bucket.count >= limit:
        headers = (
            {"Retry-After": str(retry_after_seconds)}
            if status_code == status.HTTP_429_TOO_MANY_REQUESTS
            else None
        )
        raise HTTPException(status_code=status_code, detail=detail, headers=headers)

    bucket.count += 1
    bucket.updated_at = utc_now()
    session.add(bucket)
    await session.commit()


async def enforce_turn_budgets(session: AsyncSession, user_id: int) -> None:
    """Apply global daily ceiling, then per-user hourly and daily turn caps."""
    settings = get_settings()
    now = utc_now()
    user_key = str(user_id)

    await consume_quota(
        session,
        scope=SCOPE_GLOBAL_TURNS_DAY,
        subject_key=GLOBAL_SUBJECT,
        window_start=day_window_start(now),
        limit=settings.global_turns_per_day,
        retry_after_seconds=retry_after_day(now),
        detail="The tutor is resting, try tomorrow.",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )
    await consume_quota(
        session,
        scope=SCOPE_TURNS_HOUR,
        subject_key=user_key,
        window_start=hour_window_start(now),
        limit=settings.turns_per_user_per_hour,
        retry_after_seconds=retry_after_hour(now),
        detail="Hourly turn limit reached. Try again later.",
    )
    await consume_quota(
        session,
        scope=SCOPE_TURNS_DAY,
        subject_key=user_key,
        window_start=day_window_start(now),
        limit=settings.turns_per_user_per_day,
        retry_after_seconds=retry_after_day(now),
        detail="Daily turn limit reached. Try again tomorrow.",
    )


async def enforce_upload_budget(session: AsyncSession, user_id: int) -> None:
    """Apply per-user daily PDF upload cap."""
    settings = get_settings()
    now = utc_now()
    await consume_quota(
        session,
        scope=SCOPE_UPLOADS_DAY,
        subject_key=str(user_id),
        window_start=day_window_start(now),
        limit=settings.uploads_per_user_per_day,
        retry_after_seconds=retry_after_day(now),
        detail="Daily upload limit reached. Try again tomorrow.",
    )


async def enforce_registration_budget(session: AsyncSession, request: Request) -> None:
    """Gate public signup and enforce per-IP daily registration limits."""
    settings = get_settings()
    if not settings.allow_public_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registration is disabled. Contact an administrator.",
        )
    now = utc_now()
    await consume_quota(
        session,
        scope=SCOPE_REGISTER_IP_DAY,
        subject_key=client_ip_from_request(request),
        window_start=day_window_start(now),
        limit=settings.registrations_per_ip_per_day,
        retry_after_seconds=retry_after_day(now),
        detail="Too many accounts created from this network today. Try again tomorrow.",
    )
