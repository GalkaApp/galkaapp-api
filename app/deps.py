from typing import Annotated, AsyncIterator

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthToken, User


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.db.session() as session:
        yield session


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> User:
    """Bearer token auth; `?token=` also accepted for SSE convenience."""
    value = token
    if value is None and authorization is not None and authorization.lower().startswith("bearer "):
        value = authorization[7:].strip()
    if not value:
        raise HTTPException(status_code=401, detail="Not authenticated")

    user = await session.scalar(
        select(User).join(AuthToken, AuthToken.user_id == User.id).where(AuthToken.token == value)
    )
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user


async def get_bearer_token(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if authorization is None or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return authorization[7:].strip()
