from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuthToken, Project, Task, User


class AdminService:
    """Read-only queries backing the /admin HTML pages."""

    @staticmethod
    async def overview(session: AsyncSession) -> list[dict]:
        users = (await session.scalars(select(User).order_by(User.id))).all()

        async def counts(query) -> dict[int, int]:
            return dict((await session.execute(query)).all())

        project_counts = await counts(
            select(Project.user_id, func.count()).where(~Project.deleted).group_by(Project.user_id)
        )
        task_counts = await counts(
            select(Task.user_id, func.count()).where(~Task.deleted).group_by(Task.user_id)
        )
        open_counts = await counts(
            select(Task.user_id, func.count())
            .where(~Task.deleted, ~Task.is_completed)
            .group_by(Task.user_id)
        )
        device_counts = await counts(
            select(AuthToken.user_id, func.count()).group_by(AuthToken.user_id)
        )

        return [
            {
                "user": user,
                "projects": project_counts.get(user.id, 0),
                "tasks": task_counts.get(user.id, 0),
                "open_tasks": open_counts.get(user.id, 0),
                "devices": device_counts.get(user.id, 0),
            }
            for user in users
        ]

    @staticmethod
    async def user_detail(session: AsyncSession, user_id: int) -> dict | None:
        user = await session.get(User, user_id)
        if user is None:
            return None

        projects = (await session.scalars(
            select(Project).where(Project.user_id == user_id).order_by(Project.sort_order)
        )).all()
        tasks = (await session.scalars(
            select(Task).where(Task.user_id == user_id).order_by(Task.seq.desc()).limit(500)
        )).all()
        tokens = (await session.scalars(
            select(AuthToken).where(AuthToken.user_id == user_id).order_by(AuthToken.created_at)
        )).all()

        project_names = {p.uuid: p.name for p in projects}
        return {
            "user": user,
            "projects": projects,
            "tasks": tasks,
            "tokens": tokens,
            "project_names": project_names,
        }
