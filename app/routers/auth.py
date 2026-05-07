import os

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_password_hash,
    verify_password,
)
from app.models import User
from app.schemas.user import (
    AuthResponse,
    LoginRequest,
    RefreshTokenRequest,
    RefreshTokenResponse,
    UserCreate,
    UserRead,
)
from scripts.ensure_admin import ensure_admin

router = APIRouter()

def _normalize_identifier(value: str) -> str:
    normalized = (value or "").strip()
    if "@" in normalized:
        return normalized.lower()
    return normalized


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserCreate,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    """
    Регистрация нового пользователя.

    Проверяет уникальность email/phone, хэширует пароль (pbkdf2_sha256,
    см. комментарий в app/core/security.py о выборе алгоритма) и сразу
    выдаёт пару access/refresh токенов. Инвариант «должен быть указан
    хотя бы один из email/phone» проверяется в схеме UserCreate.

    Из соображений продакшена пока не делаем:
    - подтверждение email / SMS-код,
    - rate limiting,
    - хранение refresh-токенов в БД с возможностью отзыва.
    """
    if payload.email or payload.phone:
        stmt = select(User).where(
            or_(
                User.email == payload.email,
                User.phone == payload.phone,
            )
        )
        result = await session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User with this email or phone already exists. Try logging in.",
            )

    user = User(
        name=payload.name,
        email=payload.email,
        phone=payload.phone,
        password_hash=get_password_hash(payload.password),
        is_guest=False,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return AuthResponse(
        user=UserRead.model_validate(user, from_attributes=True),
        token=token,
        refresh_token=refresh_token,
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> AuthResponse:
    """
    Логин по email или телефону + пароль.
    """
    identifier = _normalize_identifier(payload.email_or_phone)
    stmt = select(User).where(
        or_(
            func.lower(User.email) == identifier.lower(),
            User.phone == identifier,
        )
    )
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    admin_login = _normalize_identifier(os.getenv("SURPRISE_ADMIN_LOGIN", ""))
    admin_password = os.getenv("SURPRISE_ADMIN_PASSWORD", "").strip()
    if (not user or not verify_password(payload.password, user.password_hash)) and admin_login and admin_password:
        if identifier == admin_login and payload.password == admin_password:
            await ensure_admin(session)
            result = await session.execute(
                select(User).where(
                    or_(
                        func.lower(User.email) == identifier.lower(),
                        User.phone == identifier,
                    )
                )
            )
            user = result.scalar_one_or_none()

    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email/phone or password",
        )

    token = create_access_token({"sub": str(user.id)})
    refresh_token = create_refresh_token({"sub": str(user.id)})

    return AuthResponse(
        user=UserRead.model_validate(user, from_attributes=True),
        token=token,
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(
    payload: RefreshTokenRequest,
    session: AsyncSession = Depends(get_session),
) -> RefreshTokenResponse:
    try:
        token_payload = decode_token(payload.refresh_token)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    if token_payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    user_id_raw = token_payload.get("sub")
    if user_id_raw is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    new_access_token = create_access_token({"sub": str(user.id)})
    new_refresh_token = create_refresh_token({"sub": str(user.id)})

    return RefreshTokenResponse(
        token=new_access_token,
        refresh_token=new_refresh_token,
    )
