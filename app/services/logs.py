from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import LogEntry, User
from app.schemas import LogListResponse, LogOut


class LogService:
    """Read access to the activity log; writes happen through sync (clients)
    and `SyncService._log` (server-side actions)."""

    @staticmethod
    async def list(
        session: AsyncSession, user: User, limit: int = 200, action: str | None = None
    ) -> LogListResponse:
        query = select(LogEntry).where(LogEntry.user_id == user.id, ~LogEntry.deleted)
        if action:
            query = query.where(LogEntry.action == action)
        rows = (await session.scalars(
            query.order_by(LogEntry.created_at.desc(), LogEntry.seq.desc()).limit(limit)
        )).all()
        return LogListResponse(entries=[LogOut.model_validate(row) for row in rows])
