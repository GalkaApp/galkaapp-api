from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import User
from app.schemas import TrashEmptyResponse, TrashResponse
from app.services.trash import TrashService

router = APIRouter(prefix="/trash", tags=["trash"])


@router.get("", response_model=TrashResponse)
async def list_trash(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Tasks currently in the Trash, most recently trashed first."""
    return await TrashService.list(session, user)


@router.post("/empty", response_model=TrashEmptyResponse)
async def empty_trash(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    x_device_id: Annotated[str | None, Header()] = None,
):
    """Permanently delete everything in the Trash (tombstones, so other
    devices pick the deletion up on their next pull)."""
    return await TrashService.empty(
        session, user, origin=x_device_id or "", bus=request.app.state.bus
    )
