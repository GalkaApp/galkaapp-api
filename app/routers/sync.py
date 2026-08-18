from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import User
from app.schemas import SyncPullResponse, SyncPushRequest, SyncPushResponse
from app.services.sync import SyncService

router = APIRouter(tags=["sync"])


@router.get("/sync", response_model=SyncPullResponse)
async def pull(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    since: Annotated[int, Query(ge=0)] = 0,
):
    """Delta pull: every record (incl. tombstones) with seq > since."""
    return await SyncService.pull(session, user, since)


@router.post("/sync", response_model=SyncPushResponse)
async def push(
    payload: SyncPushRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    x_device_id: Annotated[str | None, Header()] = None,
):
    """Batch upsert with last-write-wins on updated_at; deletes are tombstones."""
    return await SyncService.push(
        session, user, payload, origin=x_device_id or "", bus=request.app.state.bus
    )
