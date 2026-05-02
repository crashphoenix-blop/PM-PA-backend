from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


def _validate_phone(value: Optional[str]) -> Optional[str]:
    """
    Минимальная серверная валидация телефона: должно быть не меньше 10 цифр.
    Тот же критерий используется на iOS в ValidationService.validatePhone.

    Раньше валидации не было вовсе, поэтому через Swagger UI можно было
    зарегистрировать юзера с phone='string' (Swagger подставляет это
    как плейсхолдер по умолчанию). Тут от такого мусора и защищаемся.

    None и пустая строка трактуются как «телефон не указан» и пропускаются;
    обязательность хотя бы одного из email/phone проверяется отдельным
    model_validator на UserCreate.
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    digits = sum(1 for ch in stripped if ch.isdigit())
    if digits < 10:
        raise ValueError("Phone must contain at least 10 digits")
    return stripped


class UserBase(BaseModel):
    name: str = Field(..., max_length=100)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None

    @field_validator("phone", mode="before")
    @classmethod
    def _normalize_phone(cls, value):
        return _validate_phone(value)


class UserCreate(UserBase):
    password: str = Field(..., min_length=6, max_length=128)

    @model_validator(mode="after")
    def email_or_phone_required(self) -> "UserCreate":
        """
        iOS в RegistrationViewController использует одно поле email/phone
        и кладёт значение либо в email (если есть @), либо в phone.
        На бэке закрепляем тот же инвариант: без хотя бы одного из них
        регистрация невозможна (иначе получится юзер, который не сможет залогиниться).
        """
        if not self.email and not self.phone:
            raise ValueError("Either email or phone must be provided")
        return self


class UserRead(UserBase):
    id: int
    is_guest: bool = False
    is_admin: bool = False
    created_at: datetime
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True


class AuthResponse(BaseModel):
    user: UserRead
    token: str
    refresh_token: str


class LoginRequest(BaseModel):
    email_or_phone: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class RefreshTokenResponse(BaseModel):
    token: str
    refresh_token: str


class TokenData(BaseModel):
    user_id: int


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None

    @field_validator("phone", mode="before")
    @classmethod
    def _normalize_phone(cls, value):
        return _validate_phone(value)
