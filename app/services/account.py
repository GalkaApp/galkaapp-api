from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.schemas import AccountOut, AccountUpdate


class AccountService:

    @staticmethod
    async def update(session: AsyncSession, user: User, payload: AccountUpdate) -> AccountOut:
        for field, value in payload.model_dump(exclude_unset=True, exclude_none=True).items():
            setattr(user, field, value)
        await session.commit()
        return AccountOut.model_validate(user)
