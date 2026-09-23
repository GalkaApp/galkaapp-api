import uuid
from datetime import date, datetime

import pytest

from app.mailer import Email, InMemoryMailer, Mailer
from app.routers.admin import get_mailer
from app.scheduler import Scheduler
from app.services.digest import DigestService, DigestText
from tests.conftest import auth, register
from tests.test_admin import sign_in

NOW = datetime(2026, 9, 23, 5, 30)  # 08:30 in Moscow, Wednesday


def task(title, due, **fields):
    return {"uuid": str(uuid.uuid4()), "title": title, "due_date": due,
            "created_at": "2026-09-01T00:00:00.000Z", "updated_at": "2026-09-01T00:00:00.000Z",
            **fields}


async def moscow_user(client, email="a@example.com", language="en"):
    token = await register(client, email=email)
    await client.patch("/account", json={"daily_digest": True, "timezone": "Europe/Moscow",
                                         "language": language}, headers=auth(token))
    return token


def db(client):
    return client._transport.app.state.db


@pytest.fixture
def mailer(client):
    outbox = InMemoryMailer()
    client._transport.app.dependency_overrides[get_mailer] = lambda: outbox
    return outbox


def scheduler(client, mailer):
    return Scheduler(db(client), mailer, interval=300)


async def test_collect_splits_overdue_and_today_in_local_time(client):
    token = await moscow_user(client)
    archived = {"uuid": str(uuid.uuid4()), "name": "Old", "archived_at": "2026-09-01T00:00:00.000Z",
                "created_at": "2026-09-01T00:00:00.000Z", "updated_at": "2026-09-01T00:00:00.000Z"}
    work = {"uuid": str(uuid.uuid4()), "name": "Work",
            "created_at": "2026-09-01T00:00:00.000Z", "updated_at": "2026-09-01T00:00:00.000Z"}
    # All-day dates are local midnight in UTC: 23 Sep 00:00 MSK == 22 Sep 21:00Z.
    tasks = [
        task("Yesterday", "2026-09-21T21:00:00.000Z"),
        task("All-day today", "2026-09-22T21:00:00.000Z", project_uuid=work["uuid"]),
        task("Call at 14", "2026-09-23T11:00:00.000Z", has_time=True, priority=3),
        task("Tomorrow", "2026-09-23T21:00:00.000Z"),
        task("No date", None),
        task("Done", "2026-09-22T21:00:00.000Z", is_completed=True),
        task("Trashed", "2026-09-22T21:00:00.000Z", trashed_at="2026-09-22T00:00:00.000Z"),
        task("Archived project", "2026-09-22T21:00:00.000Z", project_uuid=archived["uuid"]),
    ]
    await client.post("/sync", json={"projects": [archived, work], "tasks": tasks}, headers=auth(token))

    async with db(client).session() as session:
        user = (await DigestService.due_users(session, NOW))[0]
        overdue, today = await DigestService.collect(session, user, NOW)

    assert [t["title"] for t in overdue] == ["Yesterday"]
    assert [t["title"] for t in today] == ["Call at 14", "All-day today"]
    assert today[0]["time"] == "14:00" and today[0]["priority"] == 3
    assert today[1] == {"title": "All-day today", "time": None, "project": "Work", "priority": 0}


async def test_send_due_emails_once_and_skips_empty_days(client, mailer):
    token = await moscow_user(client)
    await moscow_user(client, email="empty@example.com")
    await client.post("/sync", json={"tasks": [task("Plan <day>", "2026-09-22T21:00:00.000Z")]},
                      headers=auth(token))

    jobs = scheduler(client, mailer)
    assert await jobs.tick(NOW) == {"sent": 1, "empty": 1}
    assert await jobs.tick(NOW) == {}

    assert len(mailer.outbox) == 1
    email = mailer.outbox[0]
    assert email.to == "a@example.com"
    assert email.subject == "Your tasks for Wednesday, 23 September"
    assert "Plan <day>" in email.text
    assert "Plan &lt;day&gt;" in email.html  # task titles are escaped in HTML


async def test_failed_send_is_retried_next_tick(client):
    class Flaky(Mailer):
        def __init__(self):
            self.calls = 0

        async def send(self, email: Email) -> None:
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("smtp down")

    token = await moscow_user(client)
    await client.post("/sync", json={"tasks": [task("T", "2026-09-22T21:00:00.000Z")]}, headers=auth(token))
    jobs = scheduler(client, Flaky())
    assert await jobs.tick(NOW) == {"failed": 1}
    assert await jobs.tick(NOW) == {"sent": 1}
    assert await jobs.tick(NOW) == {}


async def test_russian_digest(client, mailer):
    token = await moscow_user(client, language="ru")
    await client.post("/sync", json={"tasks": [
        task(f"Задача {i}", "2026-09-22T21:00:00.000Z") for i in range(3)
    ]}, headers=auth(token))
    await scheduler(client, mailer).tick(NOW)
    email = mailer.outbox[0]
    assert email.subject == "Задачи на среду, 23 сентября"
    assert "3 задачи на сегодня" in email.text
    assert "Доброе утро" in email.html


def test_russian_plurals():
    text = DigestText("ru")
    assert [text.summary(n, 0) for n in (1, 2, 5, 11, 21, 22)] == [
        "1 задача на сегодня", "2 задачи на сегодня", "5 задач на сегодня",
        "11 задач на сегодня", "21 задача на сегодня", "22 задачи на сегодня",
    ]
    assert text.summary(0, 1) == "1 просроченная"
    assert DigestText("en").summary(1, 2) == "1 task today · 2 overdue"
    assert DigestText("xx").day(date(2026, 9, 23)) == "Wednesday, 23 September"


async def test_deliver_rechecks_schedule(client, mailer):
    token = await moscow_user(client)
    await client.post("/sync", json={"tasks": [task("T", "2026-09-22T21:00:00.000Z")]}, headers=auth(token))
    await client.patch("/account", json={"daily_digest": False}, headers=auth(token))
    async with db(client).session() as session:
        # Turned off between the due check and the send: nothing goes out.
        assert await DigestService.deliver(session, mailer, 1, NOW) == "not_due"
        assert await DigestService.deliver(session, mailer, 999, NOW) == "missing"
    assert mailer.outbox == []


async def test_scheduler_stops_between_ticks(client, mailer):
    jobs = Scheduler(db(client), mailer, interval=3600)
    jobs.stopping.set()
    await jobs.run()  # returns at once instead of sleeping an hour


async def test_admin_send_digest_now(client, mailer):
    await moscow_user(client)
    await sign_in(client)
    response = await client.post("/pu/users/1/digest")
    assert response.status_code == 303
    assert response.headers["location"] == "/pu/users/1?digest=sent"
    assert len(mailer.outbox) == 1  # sent even with nothing due
    page = await client.get("/pu/users/1?digest=sent")
    assert "Digest sent to a@example.com" in page.text


async def test_admin_send_digest_off_without_smtp(client):
    client._transport.app.dependency_overrides[get_mailer] = lambda: None
    await moscow_user(client)
    await sign_in(client)
    response = await client.post("/pu/users/1/digest")
    assert response.headers["location"] == "/pu/users/1?digest=off"


async def test_admin_send_digest_requires_login(client):
    await moscow_user(client)
    assert (await client.post("/pu/users/1/digest")).status_code == 303
