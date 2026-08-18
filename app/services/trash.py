from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import EventBus
from app.models import Task, User, utcnow
from app.schemas import TaskOut, TrashEmptyResponse, TrashResponse
from app.services.sync import SyncService


class TrashService:
    """The Trash is the set of tasks with a non-null `trashed_at` that are not
    yet tombstoned. Emptying it turns every one of them into a tombstone, so
    the deletion propagates to the other devices through the normal sync."""

    @staticmethod
    async def list(session: AsyncSession, user: User) -> TrashResponse:
        rows = (await session.scalars(
            select(Task)
            .where(Task.user_id == user.id, ~Task.deleted, Task.trashed_at.is_not(None))
            .order_by(Task.trashed_at.desc())
        )).all()
        return TrashResponse(tasks=[TaskOut.model_validate(row) for row in rows])

    @staticmethod
    async def empty(
        session: AsyncSession, user: User, origin: str, bus: EventBus
    ) -> TrashEmptyResponse:
        rows = (await session.scalars(
            select(Task).where(Task.user_id == user.id, ~Task.deleted, Task.trashed_at.is_not(None))
        )).all()
        if not rows:
            seq = await session.scalar(select(User.last_seq).where(User.id == user.id))
            return TrashEmptyResponse(seq=seq or 0, purged=0)

        now = utcnow()
        # One seq per tombstone plus one for the activity entry.
        end_seq = await SyncService._advance_seq(session, user.id, len(rows) + 1)
        for offset, row in enumerate(rows):
            row.deleted = True
            row.trashed_at = None
            row.updated_at = now
            row.seq = end_seq - len(rows) + offset
        SyncService._log(
            session, user.id, seq=end_seq, action="trash_emptied", at=now,
            entity_type="trash", title="Trash emptied",
            detail=f"{len(rows)} task{'' if len(rows) == 1 else 's'} deleted permanently",
        )
        await session.commit()
        await bus.publish(user.id, {"seq": end_seq, "origin": origin})
        return TrashEmptyResponse(seq=end_seq, purged=len(rows))
