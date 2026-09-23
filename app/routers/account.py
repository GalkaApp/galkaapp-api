from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, get_session
from app.models import User
from app.schemas import AccountOut, AccountUpdate
from app.services.account import AccountService

router = APIRouter(prefix="/account", tags=["account"])


@router.get("", response_model=AccountOut)
async def get_account(user: Annotated[User, Depends(get_current_user)]):
    return user


@router.patch("", response_model=AccountOut)
async def update_account(
    payload: AccountUpdate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Daily digest settings; the app sends its current timezone here too."""
    return await AccountService.update(session, user, payload)
