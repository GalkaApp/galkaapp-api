import uuid as uuid_lib
from datetime import timedelta
from typing import Iterator

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import EventBus
from app.models import LogEntry, Project, Section, Tag, Task, User, utcnow
from app.services.recurrence import RecurrenceRule, reset_checklist
from app.schemas import (
    LogOut,
    LogPayload,
    ProjectOut,
    ProjectPayload,
    SectionOut,
    SectionPayload,
    SyncConflicts,
    SyncPullResponse,
    SyncPushRequest,
    SyncPushResponse,
    TagOut,
    TagPayload,
    TaskOut,
    TaskPayload,
)


class SyncService:
    """Delta sync: per-user sequence cursor + last-write-wins on updated_at."""

    @staticmethod
    async def pull(session: AsyncSession, user: User, since: int) -> SyncPullResponse:
        projects = (await session.scalars(
            select(Project).where(Project.user_id == user.id, Project.seq > since)
        )).all()
        sections = (await session.scalars(
            select(Section).where(Section.user_id == user.id, Section.seq > since)
        )).all()
        tags = (await session.scalars(
            select(Tag).where(Tag.user_id == user.id, Tag.seq > since)
        )).all()
        tasks = (await session.scalars(
            select(Task).where(Task.user_id == user.id, Task.seq > since)
        )).all()
        logs = (await session.scalars(
            select(LogEntry).where(LogEntry.user_id == user.id, LogEntry.seq > since)
        )).all()
        seq = await session.scalar(select(User.last_seq).where(User.id == user.id))
        return SyncPullResponse(
            seq=seq or 0,
            projects=[ProjectOut.model_validate(p) for p in projects],
            sections=[SectionOut.model_validate(s) for s in sections],
            tags=[TagOut.model_validate(t) for t in tags],
            tasks=[TaskOut.model_validate(t) for t in tasks],
            logs=[LogOut.model_validate(entry) for entry in logs],
        )

    @staticmethod
    async def push(
        session: AsyncSession,
        user: User,
        payload: SyncPushRequest,
        origin: str,
        bus: EventBus,
    ) -> SyncPushResponse:
        total = (len(payload.projects) + len(payload.sections) + len(payload.tags)
                 + len(payload.tasks) + len(payload.logs))
        if total == 0:
            seq = await session.scalar(select(User.last_seq).where(User.id == user.id))
            return SyncPushResponse(seq=seq or 0, applied=0, conflicts=SyncConflicts())

        # Allocate a contiguous seq block up front; gaps from conflicts are harmless.
        end_seq = await SyncService._advance_seq(session, user.id, total)
        seq_iter = iter(range(end_seq - total + 1, end_seq + 1))

        conflicts = SyncConflicts()
        applied = 0

        for incoming in payload.projects:
            row = await SyncService._apply(session, user.id, Project, incoming, seq_iter)
            if row is None:
                applied += 1
            else:
                conflicts.projects.append(ProjectOut.model_validate(row))

        for incoming in payload.sections:
            row = await SyncService._apply(session, user.id, Section, incoming, seq_iter)
            if row is None:
                applied += 1
            else:
                conflicts.sections.append(SectionOut.model_validate(row))

        for incoming in payload.tags:
            row = await SyncService._apply(session, user.id, Tag, incoming, seq_iter)
            if row is None:
                applied += 1
            else:
                conflicts.tags.append(TagOut.model_validate(row))

        for incoming in payload.tasks:
            row = await SyncService._apply_task(session, user.id, incoming, seq_iter)
            if row is None:
                applied += 1
            else:
                conflicts.tasks.append(TaskOut.model_validate(row))

        for incoming in payload.logs:
            row = await SyncService._apply(session, user.id, LogEntry, incoming, seq_iter)
            if row is None:
                applied += 1
            else:
                conflicts.logs.append(LogOut.model_validate(row))

        await session.commit()
        await bus.publish(user.id, {"seq": end_seq, "origin": origin})
        return SyncPushResponse(seq=end_seq, applied=applied, conflicts=conflicts)

    # ------------------------------------------------------------------ internals

    @staticmethod
    async def _advance_seq(session: AsyncSession, user_id: int, count: int) -> int:
        result = await session.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_seq=User.last_seq + count)
            .returning(User.last_seq)
        )
        return result.scalar_one()

    @staticmethod
    async def _apply(
        session: AsyncSession,
        user_id: int,
        model: type[Project] | type[Section] | type[Tag] | type[Task] | type[LogEntry],
        incoming: ProjectPayload | SectionPayload | TagPayload | TaskPayload | LogPayload,
        seq_iter: Iterator[int],
    ):
        """Upsert one record. Returns None when applied, or the (newer) server row on conflict."""
        existing = await session.get(model, (user_id, incoming.uuid))
        if existing is not None and existing.updated_at > incoming.updated_at:
            return existing  # server wins

        values = incoming.model_dump()
        if existing is None:
            session.add(model(user_id=user_id, seq=next(seq_iter), **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.seq = next(seq_iter)
        return None

    @staticmethod
    def _log(
        session: AsyncSession,
        user_id: int,
        *,
        seq: int,
        action: str,
        at,
        entity_uuid=None,
        entity_type: str = "task",
        title: str = "",
        detail: str = "",
    ) -> None:
        """Record a server-generated activity entry (clients pull it like any
        other row, so the history is identical everywhere)."""
        session.add(
            LogEntry(
                user_id=user_id,
                uuid=uuid_lib.uuid4(),
                action=action,
                entity_type=entity_type,
                entity_uuid=entity_uuid,
                title=title,
                detail=detail,
                created_at=at,
                updated_at=at,
                seq=seq,
            )
        )

    @staticmethod
    async def _apply_task(
        session: AsyncSession,
        user_id: int,
        incoming: TaskPayload,
        seq_iter: Iterator[int],
    ):
        """Task upsert with server-side recurrence: completing a repeating task
        logs a completed copy and rolls the task to its next occurrence."""
        existing = await session.get(Task, (user_id, incoming.uuid))
        if existing is not None and existing.updated_at > incoming.updated_at:
            return existing  # server wins

        values = incoming.model_dump()
        # JSON columns can't hold UUID objects — store them as strings.
        values["tag_uuids"] = [str(u) for u in values["tag_uuids"]]

        rule = RecurrenceRule.parse(incoming.recurrence_rule)
        completing = incoming.is_completed and not (existing is not None and existing.is_completed)
        if rule is not None and completing and not incoming.deleted and incoming.trashed_at is None:
            now = utcnow()
            # Rolled rows need seqs BEYOND the response's block: the pushing
            # client treats the block as already seen and must pull these.
            end = await SyncService._advance_seq(session, user_id, 3)

            log_values = dict(values)
            log_values["uuid"] = uuid_lib.uuid4()
            log_values["recurrence_rule"] = None
            log_values["completed_at"] = log_values["completed_at"] or now
            session.add(Task(user_id=user_id, seq=end - 2, **log_values))
            SyncService._log(
                session, user_id, seq=end - 1, action="repeated", at=now,
                entity_uuid=incoming.uuid, title=incoming.title,
                detail=f"Rolled forward to the next occurrence ({incoming.recurrence_rule})",
            )

            anchor = incoming.due_date or now.replace(hour=0, minute=0, second=0, microsecond=0)
            next_due = rule.next_date(anchor, incoming.has_time, now)
            if incoming.reminder_date is not None and incoming.due_date is not None:
                values["reminder_date"] = next_due + (incoming.reminder_date - incoming.due_date)
            values["due_date"] = next_due
            values["is_completed"] = False
            values["completed_at"] = None
            values["checklist"] = reset_checklist(values["checklist"])
            # Must out-LWW the client's completion write so the roll sticks.
            values["updated_at"] = max(incoming.updated_at, now) + timedelta(milliseconds=1)
            next(seq_iter)  # burn the block seq; the roll takes the fresh one
            seq = end
        else:
            seq = next(seq_iter)

        if existing is None:
            session.add(Task(user_id=user_id, seq=seq, **values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            existing.seq = seq
        return None
