from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import User
from app.schemas import LogListResponse
from app.services.logs import LogService

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", response_model=LogListResponse)
async def list_logs(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    action: Annotated[str | None, Query(max_length=32)] = None,
):
    """Activity history, newest first; optionally filtered to one action."""
    return await LogService.list(session, user, limit=limit, action=action)
