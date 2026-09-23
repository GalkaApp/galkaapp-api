"""Periodic jobs: `python -m app.scheduler`, one process beside the API (see docker-compose.yml)."""

import asyncio
import logging
import signal
from datetime import datetime

from app.config import settings
from app.db import Database
from app.mailer import Mailer, SmtpMailer
from app.services.digest import DigestService

logger = logging.getLogger("galka.scheduler")


class Scheduler:
    """Every `interval` seconds, sends the daily digests that are due. The per-user claim in
    DigestService makes a second running copy harmless rather than a double send."""

    def __init__(self, db: Database, mailer: Mailer, interval: int):
        self.db, self.mailer, self.interval = db, mailer, interval
        self.stopping = asyncio.Event()

    async def tick(self, now: datetime | None = None) -> dict[str, int]:
        """One pass; returns how many deliveries ended in each outcome."""
        outcomes: dict[str, int] = {}
        async with self.db.session() as session:
            for user_id in await DigestService.due_user_ids(session, now):
                try:
                    outcome = await DigestService.deliver(session, self.mailer, user_id, now)
                except Exception:
                    # The claim was released, so the next tick retries within the catch-up window.
                    logger.exception("digest to user %s failed", user_id)
                    outcome = "failed"
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
        return outcomes

    async def run(self) -> None:
        logger.info("scheduler started, digest check every %ss", self.interval)
        while not self.stopping.is_set():
            try:
                outcomes = await self.tick()
                if outcomes:
                    logger.info("digests: %s", outcomes)
            except Exception:
                logger.exception("digest run failed")
            try:
                await asyncio.wait_for(self.stopping.wait(), timeout=self.interval)
            except TimeoutError:
                pass
        logger.info("scheduler stopped")

    @staticmethod
    async def main() -> None:
        mailer = SmtpMailer.from_settings(settings)
        if mailer is None:
            # Stay up rather than exit, so `restart: unless-stopped` does not spin.
            logger.warning("TODOAPI_SMTP_HOST is not set; daily digests are off")
            await asyncio.Event().wait()
        db = Database(settings.database_url)
        scheduler = Scheduler(db, mailer, settings.digest_interval_seconds)
        loop = asyncio.get_running_loop()
        # Finish the current tick on `docker stop` instead of dying mid-send.
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, scheduler.stopping.set)
        try:
            await scheduler.run()
        finally:
            await db.dispose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(Scheduler.main())
