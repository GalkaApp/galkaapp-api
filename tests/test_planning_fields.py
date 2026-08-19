"""The fields added for the evening block, time blocking, the project board
and project archiving. They are plain columns, but they go through the same
last-write-wins upsert and the same recurrence roll as everything else, so the
round trip is what is worth pinning down."""

import uuid

from tests.conftest import auth, register

PROJECT_UUID = str(uuid.uuid4())
TASK_UUID = str(uuid.uuid4())


def project_payload(updated_at="2026-08-17T10:00:00Z", **overrides):
    payload = {
        "uuid": PROJECT_UUID,
        "name": "Work",
        "color_key": "blue",
        "sort_order": 0,
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": updated_at,
    }
    payload.update(overrides)
    return payload


def task_payload(updated_at="2026-08-17T10:00:00Z", **overrides):
    payload = {
        "uuid": TASK_UUID,
        "title": "Prepare presentation",
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": updated_at,
    }
    payload.update(overrides)
    return payload


async def test_planning_fields_default_when_absent(client):
    """Older clients push payloads without the new keys — they must not fail,
    and the defaults have to match the Swift model's."""
    token = await register(client)
    await client.post("/sync", json={"tasks": [task_payload()]}, headers=auth(token))

    task = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()["tasks"][0]
    assert task["is_evening"] is False
    assert task["duration_minutes"] == 0
    assert task["board_status"] == "todo"

    await client.post("/sync", json={"projects": [project_payload()]}, headers=auth(token))
    project = (await client.get("/sync?since=0", headers=auth(token, "device-c"))).json()["projects"][0]
    assert project["archived_at"] is None


async def test_planning_fields_round_trip(client):
    token = await register(client)
    await client.post(
        "/sync",
        json={
            "projects": [project_payload(archived_at="2026-08-18T12:00:00Z")],
            "tasks": [task_payload(
                is_evening=True, duration_minutes=90, board_status="doing",
                project_uuid=PROJECT_UUID,
            )],
        },
        headers=auth(token),
    )

    pull = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()
    task = pull["tasks"][0]
    assert task["is_evening"] is True
    assert task["duration_minutes"] == 90
    assert task["board_status"] == "doing"
    assert pull["projects"][0]["archived_at"].startswith("2026-08-18T12:00:00")


async def test_unarchiving_is_a_normal_last_write_wins_update(client):
    token = await register(client)
    await client.post(
        "/sync",
        json={"projects": [project_payload(archived_at="2026-08-18T12:00:00Z")]},
        headers=auth(token),
    )
    await client.post(
        "/sync",
        json={"projects": [project_payload("2026-08-18T13:00:00Z", archived_at=None)]},
        headers=auth(token),
    )

    pull = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()
    assert pull["projects"][0]["archived_at"] is None


async def test_a_negative_duration_is_rejected(client):
    token = await register(client)
    response = await client.post(
        "/sync",
        json={"tasks": [task_payload(duration_minutes=-5)]},
        headers=auth(token),
    )
    assert response.status_code == 422


async def test_recurrence_roll_keeps_the_planning_fields(client):
    """Completing a repeating evening task rolls it to the next occurrence —
    it should still be an evening task, still estimated, still in its column,
    and the logged copy should carry them too."""
    token = await register(client)
    await client.post(
        "/sync",
        json={"tasks": [task_payload(
            due_date="2026-08-17T00:00:00Z",
            recurrence_rule="daily",
            is_completed=True,
            completed_at="2026-08-17T20:00:00Z",
            is_evening=True,
            duration_minutes=45,
            board_status="doing",
        )]},
        headers=auth(token),
    )

    tasks = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()["tasks"]
    rolled = next(t for t in tasks if t["uuid"] == TASK_UUID)
    logged = next(t for t in tasks if t["uuid"] != TASK_UUID)

    assert rolled["is_completed"] is False
    assert (rolled["is_evening"], rolled["duration_minutes"], rolled["board_status"]) \
        == (True, 45, "doing")
    assert (logged["is_evening"], logged["duration_minutes"], logged["board_status"]) \
        == (True, 45, "doing")
