"""Create the schema (and ALTER in any newly added columns), then exit.

The app does this in its own lifespan too, but two uvicorn workers starting
against an empty database both emit the same CREATE TABLE and the one that
loses dies on the duplicate — which uvicorn treats as a failed startup and
takes the whole process down with. Running it once to completion first means
the workers find nothing left to do and the lifespan call is a no-op.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings  # noqa: E402
from app.db import Database  # noqa: E402


async def main() -> None:
    db = Database(settings.database_url)
    try:
        await db.create_all()
    finally:
        await db.dispose()
    print(f"schema ready: {settings.database_url.rsplit('@', 1)[-1]}")


if __name__ == "__main__":
    asyncio.run(main())
