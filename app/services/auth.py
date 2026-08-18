from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthToken, User
from app.schemas import AuthResponse, LoginRequest, RegisterRequest
from app.security import Security


class AuthService:

    @staticmethod
    async def register(session: AsyncSession, payload: RegisterRequest) -> AuthResponse:
        email = payload.email.lower()
        existing = await session.scalar(select(User).where(User.email == email))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Email already registered")

        user = User(email=email, password_hash=Security.hash_password(payload.password))
        session.add(user)
        await session.flush()
        token = await AuthService._issue_token(session, user, payload.device_name)
        await session.commit()
        return AuthResponse(token=token, email=user.email, seq=user.last_seq)

    @staticmethod
    async def login(session: AsyncSession, payload: LoginRequest) -> AuthResponse:
        user = await session.scalar(select(User).where(User.email == payload.email.lower()))
        if user is None or not Security.verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        token = await AuthService._issue_token(session, user, payload.device_name)
        await session.commit()
        return AuthResponse(token=token, email=user.email, seq=user.last_seq)

    @staticmethod
    async def logout(session: AsyncSession, token: str) -> None:
        await session.execute(delete(AuthToken).where(AuthToken.token == token))
        await session.commit()

    @staticmethod
    async def _issue_token(session: AsyncSession, user: User, device_name: str) -> str:
        token = Security.new_token()
        session.add(AuthToken(token=token, user_id=user.id, device_name=device_name[:120]))
        return token
