"""Database seed data for local development."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.user import User

DEFAULT_ADMIN_EMAIL = "admin@admin.com"
DEFAULT_ADMIN_PASSWORD = "admin"
DEFAULT_ADMIN_NAME = "Admin"


async def seed_default_admin(db: AsyncSession) -> None:
    result = await db.execute(select(User).where(User.email == DEFAULT_ADMIN_EMAIL))
    if result.scalar_one_or_none() is not None:
        return

    db.add(
        User(
            email=DEFAULT_ADMIN_EMAIL,
            hashed_password=hash_password(DEFAULT_ADMIN_PASSWORD),
            full_name=DEFAULT_ADMIN_NAME,
        )
    )
    await db.commit()
    print(f"Default admin user created: {DEFAULT_ADMIN_EMAIL}")
