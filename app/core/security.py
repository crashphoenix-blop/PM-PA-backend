from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.settings import get_settings
from app.models import User
from app.schemas.user import TokenData

# Используем pbkdf2_sha256 (NIST SP 800-132).
#
# Изначально планировался переход на bcrypt, но passlib 1.7.4 имеет
# известную несовместимость с bcrypt >= 4.1: при инициализации passlib
# скармливает 73-байтовую строку для проверки давнего бага с обрезанием
# длинных паролей. Старые версии bcrypt молча обрезали, новые (>=4.1)
# корректно бросают ValueError("password cannot be longer than 72 bytes"),
# что роняет любой hash() ещё до полезной работы. Единственный путь
# использовать bcrypt с этим passlib — пиннить bcrypt<4.1, что
# нежелательно (старая версия рано или поздно перестанет ставиться).
#
# pbkdf2_sha256 для наших задач безопасности эквивалентен bcrypt:
# адаптивная стоимость, соль, отсутствие лимита на длину пароля.
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)
oauth2_scheme = HTTPBearer()
oauth2_scheme_optional = HTTPBearer(auto_error=False)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(
        data=data,
        expires_delta=expires_delta,
        token_type="access",
    )


def create_refresh_token(data: dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    settings = get_settings()
    return _create_token(
        data=data,
        expires_delta=expires_delta or timedelta(days=settings.refresh_token_expire_days),
        token_type="refresh",
    )


def decode_token(token: str) -> dict[str, Any]:
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def _create_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta],
    token_type: str,
) -> str:
    settings = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    to_encode.update({"exp": expire})
    to_encode.update({"type": token_type})
    encoded_jwt = jwt.encode(
        to_encode,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    return encoded_jwt


async def _user_from_token(
    credentials: Optional[HTTPAuthorizationCredentials],
    session: AsyncSession,
) -> Optional[User]:
    """
    Достаёт пользователя по access-токену.
    Возвращает None, если credentials пустые или токен невалидный.
    Бросает HTTP 401 только если токен формально валиден,
    но содержит непонятный sub.
    """
    if credentials is None:
        return None
    token = credentials.credentials
    try:
        payload = decode_token(token)
    except JWTError:
        return None

    if payload.get("type") != "access":
        return None

    user_id_raw = payload.get("sub")
    if user_id_raw is None:
        return None
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError):
        return None

    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_session),
) -> User:
    """Обязательная аутентификация: 401, если токена нет / невалиден / юзер не найден."""
    user = await _user_from_token(credentials, session)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    # Для совместимости со старым кодом, который ожидал TokenData в проверке payload —
    # сейчас не нужно, оставлено как явный noqa-якорь.
    _ = TokenData(user_id=user.id)
    return user


async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(oauth2_scheme_optional),
    session: AsyncSession = Depends(get_session),
) -> Optional[User]:
    """
    Опциональная аутентификация: возвращает User или None, не бросая 401.
    Нужна для эндпоинтов вроде GET /gifts, где is_favorite зависит от того,
    залогинен ли вызывающий.
    """
    return await _user_from_token(credentials, session)


async def get_current_admin_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user
