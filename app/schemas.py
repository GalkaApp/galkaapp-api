from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from pydantic import AfterValidator, BaseModel, EmailStr, Field


def _to_naive_utc(dt: datetime) -> datetime:
    """Normalize any incoming datetime to naive UTC (the storage format)."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


NaiveUTC = Annotated[datetime, AfterValidator(_to_naive_utc)]


# ---------------------------------------------------------------- auth

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6, max_length=72)
    device_name: str = ""


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=72)
    device_name: str = ""


class AuthResponse(BaseModel):
    token: str
    email: str
    seq: int


# ---------------------------------------------------------------- entities

class ProjectPayload(BaseModel):
    uuid: UUID
    name: str
    color_key: str = "blue"
    sort_order: int = 0
    archived_at: NaiveUTC | None = None
    created_at: NaiveUTC
    updated_at: NaiveUTC
    deleted: bool = False


class TagPayload(BaseModel):
    uuid: UUID
    name: str
    color_key: str = "blue"
    created_at: NaiveUTC
    updated_at: NaiveUTC
    deleted: bool = False


class TaskPayload(BaseModel):
    uuid: UUID
    title: str
    notes: str = ""
    due_date: NaiveUTC | None = None
    has_time: bool = False
    priority: int = Field(default=0, ge=0, le=3)
    is_completed: bool = False
    completed_at: NaiveUTC | None = None
    reminder_date: NaiveUTC | None = None
    trashed_at: NaiveUTC | None = None
    sort_order: int = 0
    day_order: int = 0
    recurrence_rule: str | None = None
    checklist: str = ""
    is_evening: bool = False
    duration_minutes: int = Field(default=0, ge=0)
    board_status: str = Field(default="todo", max_length=16)
    project_uuid: UUID | None = None
    tag_uuids: list[UUID] = []
    created_at: NaiveUTC
    updated_at: NaiveUTC
    deleted: bool = False


class LogPayload(BaseModel):
    uuid: UUID
    action: str = Field(max_length=32)
    entity_type: str = Field(default="task", max_length=32)
    entity_uuid: UUID | None = None
    title: str = ""
    detail: str = ""
    created_at: NaiveUTC
    updated_at: NaiveUTC
    deleted: bool = False


class ProjectOut(ProjectPayload):
    seq: int

    model_config = {"from_attributes": True}


class TagOut(TagPayload):
    seq: int

    model_config = {"from_attributes": True}


class TaskOut(TaskPayload):
    seq: int

    model_config = {"from_attributes": True}


class LogOut(LogPayload):
    seq: int

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------- sync

class SyncPushRequest(BaseModel):
    projects: list[ProjectPayload] = []
    tags: list[TagPayload] = []
    tasks: list[TaskPayload] = []
    logs: list[LogPayload] = []


class SyncConflicts(BaseModel):
    """Server-side versions that were newer than the pushed ones (server wins)."""

    projects: list[ProjectOut] = []
    tags: list[TagOut] = []
    tasks: list[TaskOut] = []
    logs: list[LogOut] = []


class SyncPushResponse(BaseModel):
    seq: int
    applied: int
    conflicts: SyncConflicts


class SyncPullResponse(BaseModel):
    seq: int
    projects: list[ProjectOut]
    tags: list[TagOut]
    tasks: list[TaskOut]
    logs: list[LogOut] = []


# ---------------------------------------------------------------- trash / logs

class TrashResponse(BaseModel):
    """Everything currently sitting in the Trash, newest first."""

    tasks: list[TaskOut]


class TrashEmptyResponse(BaseModel):
    """Result of permanently deleting the whole Trash."""

    seq: int
    purged: int


class LogListResponse(BaseModel):
    entries: list[LogOut]
