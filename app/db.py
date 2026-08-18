from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base


class Database:
    """Engine + session factory wrapper, stored on app.state."""

    def __init__(self, url: str):
        kwargs = {}
        if url.startswith("sqlite") and ":memory:" in url:
            # Keep a single in-memory DB across sessions (tests).
            kwargs = {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        self.engine = create_async_engine(url, **kwargs)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> AsyncSession:
        return self.session_factory()

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.run_sync(self._add_missing_columns)

    @staticmethod
    def _add_missing_columns(conn) -> None:
        """Poor-man's migration: create_all skips existing tables, so newly
        added columns are ALTERed in here (with the model's default)."""
        inspector = inspect(conn)
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {column.name} '
                ddl += column.type.compile(conn.dialect)
                if not column.nullable:
                    default = column.default.arg if column.default is not None else None
                    if callable(default):
                        default = default(None)  # SQLAlchemy wraps callables with a ctx arg
                    if isinstance(default, (list, dict)):
                        literal = "'[]'" if isinstance(default, list) else "'{}'"
                    elif isinstance(default, bool):
                        literal = "TRUE" if default else "FALSE"
                    elif isinstance(default, (int, float)):
                        literal = str(default)
                    else:
                        literal = "'" + str(default or "").replace("'", "''") + "'"
                    ddl += f" NOT NULL DEFAULT {literal}"
                conn.execute(text(ddl))

    async def dispose(self) -> None:
        await self.engine.dispose()
