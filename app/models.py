import uuid as uuid_lib
from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Naive UTC now — all datetimes are stored as naive UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    # Per-user monotonically increasing change sequence (sync cursor).
    last_seq: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    device_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Project(Base):
    __tablename__ = "projects"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    uuid: Mapped[uuid_lib.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    color_key: Mapped[str] = mapped_column(String(32), default="blue")
    sort_order: Mapped[int] = mapped_column(default=0)
    # Non-null while the project is archived: it keeps every task but drops
    # out of the sidebar and out of the cross-project screens.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    deleted: Mapped[bool] = mapped_column(default=False)
    seq: Mapped[int] = mapped_column(BigInteger, index=True)


class Tag(Base):
    __tablename__ = "tags"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    uuid: Mapped[uuid_lib.UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    color_key: Mapped[str] = mapped_column(String(32), default="blue")
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    deleted: Mapped[bool] = mapped_column(default=False)
    seq: Mapped[int] = mapped_column(BigInteger, index=True)


class Task(Base):
    __tablename__ = "tasks"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    uuid: Mapped[uuid_lib.UUID] = mapped_column(Uuid, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    notes: Mapped[str] = mapped_column(Text, default="")
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    has_time: Mapped[bool] = mapped_column(default=False)
    priority: Mapped[int] = mapped_column(default=0)
    is_completed: Mapped[bool] = mapped_column(default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reminder_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Non-null while the task sits in the Trash (soft delete, still restorable).
    trashed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    # Manual position within a day on the Upcoming screen (Todoist's day_order).
    day_order: Mapped[int] = mapped_column(default=0)
    # Opaque client-side blobs: recurrence rule string and checklist JSON.
    recurrence_rule: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checklist: Mapped[str] = mapped_column(Text, default="")
    # Things-style evening block: the task sits under "This Evening" on its day.
    is_evening: Mapped[bool] = mapped_column(default=False)
    # Time blocking: expected length in minutes, 0 = unestimated.
    duration_minutes: Mapped[int] = mapped_column(default=0)
    # Kanban column on the project board: "todo" | "doing" (done is derived
    # from is_completed, so it is never stored).
    board_status: Mapped[str] = mapped_column(String(16), default="todo")
    # Loose references by uuid — the referenced rows may sync in a later batch.
    project_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(Uuid, nullable=True)
    tag_uuids: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    deleted: Mapped[bool] = mapped_column(default=False)
    seq: Mapped[int] = mapped_column(BigInteger, index=True)


class LogEntry(Base):
    """Append-only activity record. Written by the clients and by the server
    itself (recurrence rolls, emptying the trash) and synced like everything
    else, so every device sees the same history."""

    __tablename__ = "logs"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    uuid: Mapped[uuid_lib.UUID] = mapped_column(Uuid, primary_key=True)
    action: Mapped[str] = mapped_column(String(32))
    entity_type: Mapped[str] = mapped_column(String(32), default="task")
    entity_uuid: Mapped[uuid_lib.UUID | None] = mapped_column(Uuid, nullable=True)
    title: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    # created_at is the moment the action happened; updated_at exists only so
    # the shared last-write-wins upsert works unchanged.
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    deleted: Mapped[bool] = mapped_column(default=False)
    seq: Mapped[int] = mapped_column(BigInteger, index=True)
