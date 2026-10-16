"""Authentication router: /api/auth/register, /login, /google, /me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.app.database import get_session
from backend.app.models.user import User
from backend.app.schemas.auth import (
    AuthTokenResponse,
    GoogleAuthRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserResponse,
)
from backend.app.services.auth_service import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_google_oauth_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_user(
    payload: UserRegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokenResponse:
    """Register a new student account using Local Email/Password (Bcrypt + JWT)."""
    normalized_email = payload.email.lower().strip()
    existing_query = await session.exec(
        select(User).where(User.email == normalized_email)
    )
    if existing_query.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email address already exists.",
        )

    user = User(
        email=normalized_email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        auth_provider="LOCAL",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    assert user.id is not None
    access_token = create_access_token(user_id=user.id, email=user.email)
    return AuthTokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=AuthTokenResponse)
async def login_user(
    payload: UserLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokenResponse:
    """Authenticate an existing student via Local Email/Password."""
    normalized_email = payload.email.lower().strip()
    result = await session.exec(select(User).where(User.email == normalized_email))
    user = result.first()
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    assert user.id is not None
    access_token = create_access_token(user_id=user.id, email=user.email)
    return AuthTokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.post("/google", response_model=AuthTokenResponse)
async def google_oauth_login(
    payload: GoogleAuthRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthTokenResponse:
    """Authenticate or auto-provision a student via Google OAuth2 ID token."""
    claims = verify_google_oauth_token(payload.id_token)
    email = claims["email"]
    google_sub = claims["sub"]
    full_name = claims["name"]

    result = await session.exec(select(User).where(User.email == email))
    user = result.first()
    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=None,
            auth_provider="GOOGLE",
            google_sub=google_sub,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
    elif not user.google_sub:
        user.google_sub = google_sub
        session.add(user)
        await session.commit()
        await session.refresh(user)

    assert user.id is not None
    access_token = create_access_token(user_id=user.id, email=user.email)
    return AuthTokenResponse(
        access_token=access_token,
        user=UserResponse.model_validate(user),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    """Return the currently authenticated student's profile."""
    return UserResponse.model_validate(current_user)
