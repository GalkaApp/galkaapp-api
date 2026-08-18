import uuid

from tests.conftest import auth, register

TASK_UUID = str(uuid.uuid4())


def task_payload(updated_at="2026-08-17T10:00:00Z", **overrides):
    payload = {
        "uuid": TASK_UUID,
        "title": "Prepare presentation",
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": updated_at,
    }
    payload.update(overrides)
    return payload


def log_payload(action="created", **overrides):
    payload = {
        "uuid": str(uuid.uuid4()),
        "action": action,
        "entity_type": "task",
        "entity_uuid": TASK_UUID,
        "title": "Prepare presentation",
        "detail": "",
        "created_at": "2026-08-17T10:00:00Z",
        "updated_at": "2026-08-17T10:00:00Z",
    }
    payload.update(overrides)
    return payload


async def test_trashed_task_syncs_and_lists(client):
    token = await register(client)
    await client.post("/sync", json={"tasks": [task_payload()]}, headers=auth(token))

    empty = (await client.get("/trash", headers=auth(token))).json()
    assert empty["tasks"] == []

    await client.post(
        "/sync",
        json={"tasks": [task_payload("2026-08-17T11:00:00Z", trashed_at="2026-08-17T11:00:00Z")]},
        headers=auth(token),
    )
    listing = (await client.get("/trash", headers=auth(token))).json()
    assert [t["uuid"] for t in listing["tasks"]] == [TASK_UUID]
    assert listing["tasks"][0]["trashed_at"] == "2026-08-17T11:00:00"

    # Restoring is a plain field update pushed through sync.
    await client.post(
        "/sync",
        json={"tasks": [task_payload("2026-08-17T12:00:00Z", trashed_at=None)]},
        headers=auth(token),
    )
    assert (await client.get("/trash", headers=auth(token))).json()["tasks"] == []


async def test_empty_trash_tombstones_and_logs(client):
    token = await register(client)
    await client.post(
        "/sync",
        json={"tasks": [task_payload(trashed_at="2026-08-17T11:00:00Z")]},
        headers=auth(token),
    )

    response = await client.post("/trash/empty", headers=auth(token))
    assert response.status_code == 200, response.text
    assert response.json()["purged"] == 1

    assert (await client.get("/trash", headers=auth(token))).json()["tasks"] == []

    # A second device pulls the tombstone plus the server-written log entry.
    pull = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()
    assert [t["deleted"] for t in pull["tasks"]] == [True]
    assert [entry["action"] for entry in pull["logs"]] == ["trash_emptied"]

    again = await client.post("/trash/empty", headers=auth(token))
    assert again.json()["purged"] == 0


async def test_logs_push_pull_and_filter(client):
    token = await register(client)
    push = await client.post(
        "/sync",
        json={"logs": [log_payload("created"), log_payload("completed")]},
        headers=auth(token),
    )
    assert push.json()["applied"] == 2

    pull = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()
    assert len(pull["logs"]) == 2

    listing = (await client.get("/logs", headers=auth(token))).json()
    assert {entry["action"] for entry in listing["entries"]} == {"created", "completed"}

    filtered = (await client.get("/logs?action=completed", headers=auth(token))).json()
    assert [entry["action"] for entry in filtered["entries"]] == ["completed"]

    # Clearing the log is a tombstone, exactly like every other entity.
    cleared = listing["entries"][0]
    await client.post(
        "/sync",
        json={"logs": [{**cleared, "deleted": True, "updated_at": "2026-08-18T10:00:00Z"}]},
        headers=auth(token),
    )
    assert len((await client.get("/logs", headers=auth(token))).json()["entries"]) == 1


async def test_trashed_repeating_task_does_not_roll_forward(client):
    token = await register(client)
    payload = task_payload(
        due_date="2026-08-17T00:00:00Z",
        recurrence_rule="daily",
        is_completed=True,
        completed_at="2026-08-17T10:00:00Z",
        trashed_at="2026-08-17T10:00:00Z",
    )
    await client.post("/sync", json={"tasks": [payload]}, headers=auth(token))

    pull = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()
    assert len(pull["tasks"]) == 1
    assert pull["tasks"][0]["is_completed"] is True


async def test_repeating_roll_forward_writes_a_log_entry(client):
    token = await register(client)
    payload = task_payload(
        due_date="2026-08-17T00:00:00Z",
        recurrence_rule="daily",
        is_completed=True,
        completed_at="2026-08-17T10:00:00Z",
    )
    await client.post("/sync", json={"tasks": [payload]}, headers=auth(token))

    logs = (await client.get("/logs", headers=auth(token))).json()["entries"]
    assert [entry["action"] for entry in logs] == ["repeated"]
    assert logs[0]["entity_uuid"] == TASK_UUID


async def test_delete_wins_over_a_sub_second_server_roll(client):
    """Regression: the client used to send whole seconds, so a delete made in
    the same second as the server's recurrence roll (updated_at + 1 ms) lost the
    last-write-wins comparison and the task came back on the next pull."""
    token = await register(client)
    await client.post(
        "/sync",
        json={"tasks": [task_payload(
            "2026-08-17T10:00:00Z",
            due_date="2026-08-17T00:00:00Z",
            recurrence_rule="daily",
            is_completed=True,
            completed_at="2026-08-17T10:00:00Z",
        )]},
        headers=auth(token),
    )
    rolled = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()
    server_stamp = next(t for t in rolled["tasks"] if t["uuid"] == TASK_UUID)["updated_at"]
    assert "." in server_stamp, "the roll is expected to carry sub-second precision"

    whole_second = server_stamp.split(".")[0] + "Z"
    rejected = await client.post(
        "/sync",
        json={"tasks": [task_payload(whole_second, deleted=True)]},
        headers=auth(token),
    )
    assert rejected.json()["conflicts"]["tasks"], "whole seconds still lose — hence ms on the wire"

    accepted = await client.post(
        "/sync",
        json={"tasks": [task_payload("2026-08-18T09:00:00.250Z", deleted=True)]},
        headers=auth(token),
    )
    assert accepted.json()["conflicts"]["tasks"] == []
    assert accepted.json()["applied"] == 1
