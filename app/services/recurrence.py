"""Recurrence engine — the server owns roll-forward of repeating tasks.

Rule strings match the Swift client's `RecurrenceRule` format:
    "daily"                     every day
    "daily;interval=3"          every 3 days
    "weekdays"                  every Mon-Fri day
    "weekly"                    every week (same weekday as the anchor)
    "weekly;days=2,6"           every Monday and Friday
    "weekly;weekday=2"          legacy single-day form (== days=2)
    "monthly" / "yearly"        every month / year, with optional interval

Weekday numbers use the Apple Calendar convention: 1=Sunday … 7=Saturday.
"""

import json
from datetime import datetime, timedelta


def _apple_weekday(dt: datetime) -> int:
    """Python Monday=0 … Sunday=6  →  Apple Sunday=1 … Saturday=7."""
    return (dt.weekday() + 1) % 7 + 1


class RecurrenceRule:
    FREQS = ("daily", "weekdays", "weekly", "monthly", "yearly")

    def __init__(self, freq: str, interval: int = 1, days: set[int] | None = None):
        self.freq = freq
        self.interval = max(1, interval)
        self.days = {d for d in (days or set()) if 1 <= d <= 7}

    @classmethod
    def parse(cls, raw: str | None) -> "RecurrenceRule | None":
        if not raw:
            return None
        parts = raw.split(";")
        if parts[0] not in cls.FREQS:
            return None
        interval, days = 1, set()
        for part in parts[1:]:
            key, _, value = part.partition("=")
            if key == "interval" and value.isdigit():
                interval = int(value)
            elif key == "weekday" and value.isdigit():
                days = {int(value)}
            elif key == "days":
                days = {int(v) for v in value.split(",") if v.strip().isdigit()}
        return cls(parts[0], interval, days)

    # ------------------------------------------------------------- schedule

    def next_date(self, anchor: datetime, has_time: bool, now: datetime) -> datetime:
        """Next occurrence strictly after both the anchor and now, preserving
        the anchor's time of day (completing an overdue "every day" task lands
        on tomorrow, not another past date)."""
        floor = now if has_time else now.replace(hour=0, minute=0, second=0, microsecond=0)
        date = anchor
        while True:
            date = self._step(date)
            if date > max(floor, anchor):
                return date

    def _step(self, date: datetime) -> datetime:
        if self.freq == "daily":
            return date + timedelta(days=self.interval)
        if self.freq == "weekdays":
            step = date + timedelta(days=1)
            while step.weekday() >= 5:  # Sat/Sun
                step += timedelta(days=1)
            return step
        if self.freq == "weekly":
            if not self.days:
                return date + timedelta(weeks=self.interval)
            step = date + timedelta(days=1)
            while _apple_weekday(step) not in self.days:
                step += timedelta(days=1)
            # "Every N weeks on ..." — a week-boundary crossing skips ahead.
            if self.interval > 1 and self._week_index(step) != self._week_index(date):
                step += timedelta(weeks=self.interval - 1)
            return step
        if self.freq == "monthly":
            return self._add_months(date, self.interval)
        return self._add_months(date, 12 * self.interval)  # yearly

    @staticmethod
    def _week_index(dt: datetime) -> int:
        """Weeks counted from epoch, starting on Sunday (Apple's default)."""
        days = (dt.date() - datetime(1970, 1, 4).date()).days  # 1970-01-04 was a Sunday
        return days // 7

    @staticmethod
    def _add_months(date: datetime, months: int) -> datetime:
        month0 = date.month - 1 + months
        year = date.year + month0 // 12
        month = month0 % 12 + 1
        # Clamp to the target month's last day (Jan 31 -> Feb 28).
        for day in range(date.day, 27, -1):
            try:
                return date.replace(year=year, month=month, day=day)
            except ValueError:
                continue
        return date.replace(year=year, month=month, day=min(date.day, 28))


def reset_checklist(checklist_json: str) -> str:
    """Uncheck every checklist item (opaque JSON pass-through otherwise)."""
    if not checklist_json:
        return checklist_json
    try:
        items = json.loads(checklist_json)
        for item in items:
            if isinstance(item, dict):
                item["isDone"] = False
        return json.dumps(items)
    except (ValueError, TypeError):
        return checklist_json
