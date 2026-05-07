import asyncio
import os

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import get_password_hash
from app.models import User


async def ensure_admin(session: AsyncSession) -> None:
    login = os.getenv("SURPRISE_ADMIN_LOGIN", "").strip().lower()
    password = os.getenv("SURPRISE_ADMIN_PASSWORD", "").strip()
    name = os.getenv("SURPRISE_ADMIN_NAME", "Администратор").strip() or "Администратор"

    if not login or not password:
        return

    email = login if "@" in login else None
    phone = None if email else login

    if email:
        existing = await session.execute(select(User).where(User.email == email))
    else:
        existing = await session.execute(select(User).where(User.phone == phone))
    admin_user = existing.scalar_one_or_none()
    if admin_user is None:
        admin_user = User(
            name=name,
            email=email,
            phone=phone,
            password_hash=get_password_hash(password),
            is_guest=False,
            is_admin=True,
        )
        session.add(admin_user)
    else:
        admin_user.name = name
        admin_user.is_admin = True
        admin_user.is_guest = False
        admin_user.password_hash = get_password_hash(password)
        if email:
            admin_user.email = email
        else:
            admin_user.phone = phone

    await session.commit()


async def main() -> None:
    async for session in get_session():
        await ensure_admin(session)
        break


if __name__ == "__main__":
    asyncio.run(main())
