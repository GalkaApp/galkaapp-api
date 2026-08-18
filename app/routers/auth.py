from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_bearer_token, get_session
from app.schemas import AuthResponse, LoginRequest, RegisterRequest
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    payload: RegisterRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await AuthService.register(session, payload)


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
):
    return await AuthService.login(session, payload)


@router.post("/logout", status_code=204)
async def logout(
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str, Depends(get_bearer_token)],
):
    await AuthService.logout(session, token)
