import json
import uuid
from datetime import datetime

from app.services.recurrence import RecurrenceRule, reset_checklist
from tests.conftest import auth, register


def d(s):
    return datetime.fromisoformat(s)


def test_parse_and_next():
    now = d("2026-08-18 15:00")  # Tuesday

    daily = RecurrenceRule.parse("daily")
    assert daily.next_date(d("2026-08-18 00:00"), False, now) == d("2026-08-19 00:00")
    # Overdue for a week: skips to tomorrow, not another past date.
    assert daily.next_date(d("2026-08-10 00:00"), False, now) == d("2026-08-19 00:00")

    every3 = RecurrenceRule.parse("daily;interval=3")
    assert every3.next_date(d("2026-08-17 00:00"), False, now) == d("2026-08-20 00:00")

    weekdays = RecurrenceRule.parse("weekdays")
    assert weekdays.next_date(d("2026-08-21 00:00"), False, now) == d("2026-08-24 00:00")  # Fri -> Mon

    legacy = RecurrenceRule.parse("weekly;weekday=2")  # every Monday
    assert legacy.next_date(d("2026-08-17 00:00"), False, now) == d("2026-08-24 00:00")

    multi = RecurrenceRule.parse("weekly;days=2,6")  # Mon + Fri
    assert multi.next_date(d("2026-08-17 00:00"), False, now) == d("2026-08-21 00:00")  # Mon -> Fri
    assert multi.next_date(d("2026-08-21 00:00"), False, now) == d("2026-08-24 00:00")  # Fri -> Mon

    monthly = RecurrenceRule.parse("monthly")
    assert monthly.next_date(d("2027-01-31 00:00"), False, d("2027-01-31 10:00")) == d("2027-02-28 00:00")

    weekly_timed = RecurrenceRule.parse("weekly")
    assert weekly_timed.next_date(d("2026-08-18 09:30"), True, now) == d("2026-08-25 09:30")

    assert RecurrenceRule.parse("bogus") is None
    assert RecurrenceRule.parse(None) is None
    assert reset_checklist('[{"id":"x","title":"a","isDone":true}]') == '[{"id": "x", "title": "a", "isDone": false}]'


async def test_completing_recurring_task_rolls_forward(client):
    token = await register(client)
    task_uuid = str(uuid.uuid4())

    base = {
        "uuid": task_uuid,
        "title": "Water plants",
        "due_date": "2026-08-18T09:00:00",
        "has_time": True,
        "reminder_date": "2026-08-18T08:00:00",
        "recurrence_rule": "daily",
        "checklist": '[{"id":"c1","title":"front room","isDone":false}]',
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": "2026-08-17T09:00:00Z",
    }
    push = await client.post("/sync", json={"tasks": [base]}, headers=auth(token))
    assert push.status_code == 200, push.text

    # Complete it (with a checked-off checklist item).
    done = dict(base, is_completed=True, completed_at="2026-08-18T09:05:00Z",
                updated_at="2026-08-18T09:05:00Z",
                checklist='[{"id":"c1","title":"front room","isDone":true}]')
    push = await client.post("/sync", json={"tasks": [done]}, headers=auth(token))
    body = push.json()
    assert body["applied"] == 1 and body["conflicts"]["tasks"] == []

    # The pushing client pulls from the returned seq and must receive BOTH
    # the rolled-forward task and the completed history row.
    pull = (await client.get(f"/sync?since={body['seq']}", headers=auth(token))).json()
    by_uuid = {t["uuid"]: t for t in pull["tasks"]}
    assert len(by_uuid) == 2 and task_uuid in by_uuid

    rolled = by_uuid[task_uuid]
    assert rolled["is_completed"] is False
    assert rolled["completed_at"] is None
    assert rolled["due_date"] == "2026-08-19T09:00:00"
    assert rolled["reminder_date"] == "2026-08-19T08:00:00"
    assert json.loads(rolled["checklist"])[0]["isDone"] is False
    assert rolled["recurrence_rule"] == "daily"
    assert rolled["updated_at"] > "2026-08-18T09:05:00"  # out-LWWs the completion

    log = next(t for u, t in by_uuid.items() if u != task_uuid)
    assert log["is_completed"] is True
    assert log["recurrence_rule"] is None
    assert log["title"] == "Water plants"
    assert json.loads(log["checklist"])[0]["isDone"] is True

    # Completing a NON-recurring task stays a plain completion.
    plain_uuid = str(uuid.uuid4())
    plain = {"uuid": plain_uuid, "title": "One-off", "is_completed": True,
             "completed_at": "2026-08-18T10:00:00Z",
             "created_at": "2026-08-18T09:00:00Z", "updated_at": "2026-08-18T10:00:00Z"}
    body = (await client.post("/sync", json={"tasks": [plain]}, headers=auth(token))).json()
    pull = (await client.get("/sync?since=0", headers=auth(token))).json()
    plain_out = next(t for t in pull["tasks"] if t["uuid"] == plain_uuid)
    assert plain_out["is_completed"] is True
