from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.mailer import Email, Mailer
from app.models import Project, Task, User, utcnow

TEMPLATES = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
    autoescape=select_autoescape(["html"]),
)


class DigestText:
    """English and Russian copy for the digest email, plurals included."""

    STRINGS = {
        "en": {
            "greeting": "Good morning",
            "overdue": "Overdue",
            "today": "Today",
            "empty": "Nothing is due today.",
            "more": "and {n} more",
            "footer": "You get this email because the daily digest is on in Galka. "
                      "Turn it off in Settings ▸ Account.",
        },
        "ru": {
            "greeting": "Доброе утро",
            "overdue": "Просрочено",
            "today": "Сегодня",
            "empty": "На сегодня ничего не запланировано.",
            "more": "и ещё {n}",
            "footer": "Вы получаете это письмо, потому что в Galka включена ежедневная сводка. "
                      "Отключить её можно в Настройках ▸ Аккаунт.",
        },
    }
    EN_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    EN_MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December"]
    RU_WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
    # Accusative, for "Задачи на среду".
    RU_WEEKDAYS_ACC = ["понедельник", "вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье"]
    RU_MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                     "августа", "сентября", "октября", "ноября", "декабря"]

    def __init__(self, language: str):
        self.language = language if language in self.STRINGS else "en"

    def __getitem__(self, key: str) -> str:
        return self.STRINGS[self.language][key]

    @staticmethod
    def ru_plural(n: int, one: str, few: str, many: str) -> str:
        if n % 10 == 1 and n % 100 != 11:
            return one
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return few
        return many

    def day(self, day: date) -> str:
        if self.language == "ru":
            return f"{self.RU_WEEKDAYS[day.weekday()]}, {day.day} {self.RU_MONTHS_GEN[day.month - 1]}"
        return f"{self.EN_WEEKDAYS[day.weekday()]}, {day.day} {self.EN_MONTHS[day.month - 1]}"

    def subject(self, day: date) -> str:
        if self.language == "ru":
            weekday = self.RU_WEEKDAYS_ACC[day.weekday()]
            return f"Задачи на {weekday}, {day.day} {self.RU_MONTHS_GEN[day.month - 1]}"
        return f"Your tasks for {self.day(day)}"

    def summary(self, today: int, overdue: int) -> str:
        parts = []
        if self.language == "ru":
            if today:
                parts.append(f"{today} {self.ru_plural(today, 'задача', 'задачи', 'задач')} на сегодня")
            if overdue:
                parts.append(f"{overdue} "
                             f"{self.ru_plural(overdue, 'просроченная', 'просроченные', 'просроченных')}")
        else:
            if today:
                parts.append(f"{today} {'task' if today == 1 else 'tasks'} today")
            if overdue:
                parts.append(f"{overdue} overdue")
        return " · ".join(parts) or self["empty"]


class DigestService:
    """Works out whose morning it is, builds their digest and sends it."""

    # A digest missed at its hour (server down) still goes out within this many hours.
    CATCH_UP_HOURS = 3
    # Longer lists end in "and N more"; the app is the place to read them all.
    SECTION_LIMIT = 30

    @staticmethod
    def zone(user: User) -> ZoneInfo:
        try:
            return ZoneInfo(user.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    @staticmethod
    def local_now(user: User, now: datetime) -> datetime:
        """`now` is naive UTC (the storage format); returns the user's wall-clock time."""
        return now.replace(tzinfo=timezone.utc).astimezone(DigestService.zone(user))

    @staticmethod
    def is_due(user: User, now: datetime) -> bool:
        if not user.daily_digest:
            return False
        local = DigestService.local_now(user, now)
        in_window = user.digest_hour <= local.hour < user.digest_hour + DigestService.CATCH_UP_HOURS
        return in_window and user.digest_sent_on != local.date()

    @staticmethod
    async def due_users(session: AsyncSession, now: datetime | None = None) -> list[User]:
        now = now or utcnow()
        users = (await session.scalars(select(User).where(User.daily_digest))).all()
        return [user for user in users if DigestService.is_due(user, now)]

    @staticmethod
    async def due_user_ids(session: AsyncSession, now: datetime | None = None) -> list[int]:
        return [user.id for user in await DigestService.due_users(session, now)]

    @staticmethod
    async def claim(session: AsyncSession, user: User, today: date) -> bool:
        """Atomically mark today's digest as taken; False if another worker got it first."""
        result = await session.execute(
            update(User)
            .where(User.id == user.id,
                   or_(User.digest_sent_on.is_(None), User.digest_sent_on != today))
            .values(digest_sent_on=today)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        user.digest_sent_on = today
        return result.rowcount == 1

    @staticmethod
    async def release(session: AsyncSession, user: User, previous: date | None) -> None:
        """Undo a claim after a failed send so the next tick retries."""
        await session.execute(
            update(User).where(User.id == user.id).values(digest_sent_on=previous)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        user.digest_sent_on = previous

    @staticmethod
    async def collect(session: AsyncSession, user: User, now: datetime) -> tuple[list[dict], list[dict]]:
        """Open tasks due before the end of the user's local today, split into overdue / today."""
        zone = DigestService.zone(user)
        local_midnight = DigestService.local_now(user, now).replace(hour=0, minute=0, second=0, microsecond=0)

        def to_utc(moment: datetime) -> datetime:
            return moment.astimezone(timezone.utc).replace(tzinfo=None)

        day_start = to_utc(local_midnight)
        # Wall-clock arithmetic, so a DST day is 23 or 25 hours as it should be.
        day_end = to_utc((local_midnight.replace(tzinfo=None) + timedelta(days=1)).replace(tzinfo=zone))

        projects = (await session.scalars(
            select(Project).where(Project.user_id == user.id, ~Project.deleted)
        )).all()
        names = {p.uuid: p.name for p in projects}
        archived = {p.uuid for p in projects if p.archived_at is not None}

        tasks = (await session.scalars(
            select(Task).where(
                Task.user_id == user.id, ~Task.deleted, ~Task.is_completed,
                Task.trashed_at.is_(None), Task.due_date.is_not(None), Task.due_date < day_end,
            )
        )).all()

        def item(task: Task) -> dict:
            local_due = task.due_date.replace(tzinfo=timezone.utc).astimezone(zone)
            return {
                "title": task.title,
                "time": local_due.strftime("%H:%M") if task.has_time else None,
                "project": names.get(task.project_uuid),
                "priority": task.priority,
            }

        visible = [t for t in tasks if t.project_uuid not in archived]
        overdue = sorted((t for t in visible if t.due_date < day_start), key=lambda t: t.due_date)
        today = sorted(
            (t for t in visible if t.due_date >= day_start),
            # Timed tasks first, in clock order, then the all-day ones in the app's day order.
            key=lambda t: (not t.has_time, t.due_date if t.has_time else datetime.min,
                           t.day_order, t.sort_order),
        )
        return [item(t) for t in overdue], [item(t) for t in today]

    @staticmethod
    def render(user: User, day: date, overdue: list[dict], today: list[dict]) -> Email:
        text = DigestText(user.language)
        limit = DigestService.SECTION_LIMIT
        sections = [
            {"title": text[key], "items": items[:limit], "more": max(0, len(items) - limit)}
            for key, items in (("overdue", overdue), ("today", today)) if items
        ]
        context = {
            "t": text, "language": text.language, "day": text.day(day),
            "summary": text.summary(len(today), len(overdue)), "sections": sections,
        }
        return Email(
            to=user.email,
            subject=text.subject(day),
            text=TEMPLATES.get_template("email/digest.txt").render(context),
            html=TEMPLATES.get_template("email/digest.html").render(context),
        )

    @staticmethod
    async def build(session: AsyncSession, user: User, now: datetime) -> tuple[Email, int]:
        """The email and how many tasks it lists."""
        overdue, today = await DigestService.collect(session, user, now)
        day = DigestService.local_now(user, now).date()
        return DigestService.render(user, day, overdue, today), len(overdue) + len(today)

    @staticmethod
    async def deliver(session: AsyncSession, mailer: Mailer, user_id: int,
                      now: datetime | None = None, force: bool = False) -> str:
        """Send one user's digest. `force` skips the schedule and sends even an empty day.
        Returns sent | empty | not_due | taken | missing; a failed send re-raises after
        releasing the claim so a retry can take it again."""
        now = now or utcnow()
        user = await session.get(User, user_id)
        if user is None:
            return "missing"
        if force:
            email, _count = await DigestService.build(session, user, now)
            await mailer.send(email)
            return "sent"
        if not DigestService.is_due(user, now):
            return "not_due"
        previous = user.digest_sent_on
        if not await DigestService.claim(session, user, DigestService.local_now(user, now).date()):
            return "taken"
        try:
            email, count = await DigestService.build(session, user, now)
            if not count:
                return "empty"
            await mailer.send(email)
        except Exception:
            await DigestService.release(session, user, previous)
            raise
        return "sent"
