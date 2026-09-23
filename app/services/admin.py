import secrets
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, ValidationError, field_validator
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import AdminSession, AuthToken, Project, Task, User, utcnow
from app.schemas import TimezoneName
from app.security import Security


class AdminUserForm(BaseModel):
    """The /pu user edit form. An empty password leaves the current one."""

    email: EmailStr
    password: str = ""
    daily_digest: bool = False
    timezone: TimezoneName
    digest_hour: int = Field(ge=0, le=23)
    language: Literal["en", "ru"]

    @field_validator("password")
    @classmethod
    def password_length(cls, value: str) -> str:
        if value and not 6 <= len(value) <= 72:
            raise ValueError("must be between 6 and 72 characters")
        return value

    @staticmethod
    def first_error(exc: ValidationError) -> str:
        error = exc.errors()[0]
        field = str(error["loc"][0]).replace("_", " ") if error["loc"] else "form"
        return f"{field.capitalize()}: {error['msg'].removeprefix('Value error, ')}."


class AdminService:
    """Queries and edits backing the /pu HTML pages."""

    @staticmethod
    async def update_user(session: AsyncSession, user: User, form: AdminUserForm) -> str | None:
        """Apply the edit form; returns an error message instead of saving on a clash."""
        email = form.email.lower()
        if email != user.email:
            owner = await session.scalar(select(User).where(User.email == email))
            if owner is not None:
                return f"{email} already belongs to user #{owner.id}."
        user.email = email
        if form.password:
            user.password_hash = Security.hash_password(form.password)
        user.daily_digest = form.daily_digest
        user.timezone = form.timezone
        user.digest_hour = form.digest_hour
        user.language = form.language
        await session.commit()
        return None

    @staticmethod
    async def set_digest(session: AsyncSession, user: User, enabled: bool) -> None:
        user.daily_digest = enabled
        await session.commit()

    @staticmethod
    async def overview(session: AsyncSession) -> list[dict]:
        users = (await session.scalars(select(User).order_by(User.id))).all()

        async def counts(query) -> dict[int, int]:
            return dict((await session.execute(query)).all())

        project_counts = await counts(
            select(Project.user_id, func.count()).where(~Project.deleted).group_by(Project.user_id)
        )
        task_counts = await counts(
            select(Task.user_id, func.count()).where(~Task.deleted).group_by(Task.user_id)
        )
        open_counts = await counts(
            select(Task.user_id, func.count())
            .where(~Task.deleted, ~Task.is_completed)
            .group_by(Task.user_id)
        )
        device_counts = await counts(
            select(AuthToken.user_id, func.count()).group_by(AuthToken.user_id)
        )

        return [
            {
                "user": user,
                "projects": project_counts.get(user.id, 0),
                "tasks": task_counts.get(user.id, 0),
                "open_tasks": open_counts.get(user.id, 0),
                "devices": device_counts.get(user.id, 0),
            }
            for user in users
        ]

    @staticmethod
    async def user_detail(session: AsyncSession, user_id: int) -> dict | None:
        user = await session.get(User, user_id)
        if user is None:
            return None

        projects = (await session.scalars(
            select(Project).where(Project.user_id == user_id).order_by(Project.sort_order)
        )).all()
        tasks = (await session.scalars(
            select(Task).where(Task.user_id == user_id).order_by(Task.seq.desc()).limit(500)
        )).all()
        tokens = (await session.scalars(
            select(AuthToken).where(AuthToken.user_id == user_id).order_by(AuthToken.created_at)
        )).all()

        project_names = {p.uuid: p.name for p in projects}
        return {
            "user": user,
            "projects": projects,
            "tasks": tasks,
            "tokens": tokens,
            "project_names": project_names,
        }


class AdminAuthService:
    """Login-form auth for /pu: credentials from Settings, sessions stored in the DB."""

    SESSION_TTL = timedelta(days=7)

    @staticmethod
    def check_credentials(username: str, password: str) -> bool:
        username_ok = secrets.compare_digest(username.encode(), settings.admin_username.encode())
        password_ok = secrets.compare_digest(password.encode(), settings.admin_password.encode())
        return username_ok and password_ok

    @staticmethod
    async def create_session(session: AsyncSession, username: str) -> str:
        now = utcnow()
        await session.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
        token = Security.new_token()
        session.add(AdminSession(
            token=token, username=username, created_at=now,
            expires_at=now + AdminAuthService.SESSION_TTL,
        ))
        await session.commit()
        return token

    @staticmethod
    async def resolve(session: AsyncSession, token: str | None) -> str | None:
        """Username behind a live session token, or None."""
        if not token:
            return None
        row = await session.get(AdminSession, token)
        if row is None or row.expires_at <= utcnow():
            return None
        return row.username

    @staticmethod
    async def revoke(session: AsyncSession, token: str | None) -> None:
        if token:
            await session.execute(delete(AdminSession).where(AdminSession.token == token))
            await session.commit()
