from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import Database
from app.events import EventBus, RedisEventBus
from app.routers import account, admin, auth, events, logs, pages, signup, sync, trash


STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app(database_url: str | None = None, bus: EventBus | None = None) -> FastAPI:
    """App factory; tests inject a SQLite URL and an in-memory bus."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.db = Database(database_url or settings.database_url)
        await app.state.db.create_all()
        app.state.bus = bus or RedisEventBus(settings.redis_url)
        await app.state.bus.connect()
        yield
        await app.state.bus.close()
        await app.state.db.dispose()

    app = FastAPI(title="Galka", version="1.0", lifespan=lifespan)
    app.include_router(auth.router)
    app.include_router(account.router)
    app.include_router(sync.router)
    app.include_router(events.router)
    app.include_router(trash.router)
    app.include_router(logs.router)
    app.include_router(admin.router)
    app.include_router(signup.router)
    app.include_router(pages.router)
    # App icon, shared by the public, signup and admin pages.
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
