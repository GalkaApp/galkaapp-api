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
        "due_date": "2026-08-21T10:00:00Z",
        "has_time": True,
        "priority": 3,
        "project_uuid": PROJECT_UUID,
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": updated_at,
    }
    payload.update(overrides)
    return payload


async def test_register_login_and_wrong_password(client):
    token = await register(client)
    assert len(token) == 64

    ok = await client.post("/auth/login", json={"email": "a@example.com", "password": "secret1"})
    assert ok.status_code == 200

    bad = await client.post("/auth/login", json={"email": "a@example.com", "password": "nope99"})
    assert bad.status_code == 401

    dup = await client.post("/auth/register", json={"email": "a@example.com", "password": "secret1"})
    assert dup.status_code == 409


async def test_push_and_pull_roundtrip(client):
    token = await register(client)

    push = await client.post(
        "/sync",
        json={"projects": [project_payload()], "tasks": [task_payload()]},
        headers=auth(token),
    )
    assert push.status_code == 200, push.text
    body = push.json()
    assert body["applied"] == 2
    assert body["seq"] == 2

    # Second device: full pull.
    pull = await client.get("/sync?since=0", headers=auth(token, "device-b"))
    data = pull.json()
    assert data["seq"] == 2
    assert len(data["projects"]) == 1 and len(data["tasks"]) == 1
    assert data["tasks"][0]["title"] == "Prepare presentation"
    assert data["tasks"][0]["project_uuid"] == PROJECT_UUID

    # Incremental pull from the cursor: nothing new.
    empty = (await client.get(f"/sync?since={data['seq']}", headers=auth(token, "device-b"))).json()
    assert empty["projects"] == [] and empty["tasks"] == []


async def test_last_write_wins_conflict(client):
    token = await register(client)
    await client.post("/sync", json={"tasks": [task_payload("2026-08-17T12:00:00Z")]}, headers=auth(token))

    # Older edit from another device → server wins, current row returned.
    stale = await client.post(
        "/sync",
        json={"tasks": [task_payload("2026-08-17T11:00:00Z", title="Stale title")]},
        headers=auth(token, "device-b"),
    )
    body = stale.json()
    assert body["applied"] == 0
    assert len(body["conflicts"]["tasks"]) == 1
    assert body["conflicts"]["tasks"][0]["title"] == "Prepare presentation"

    # Newer edit → applied.
    fresh = await client.post(
        "/sync",
        json={"tasks": [task_payload("2026-08-17T13:00:00Z", title="Newer title")]},
        headers=auth(token, "device-b"),
    )
    assert fresh.json()["applied"] == 1

    pull = (await client.get("/sync?since=0", headers=auth(token))).json()
    assert pull["tasks"][0]["title"] == "Newer title"


async def test_tombstone_delete_syncs(client):
    token = await register(client)
    await client.post("/sync", json={"tasks": [task_payload()]}, headers=auth(token))
    first = (await client.get("/sync?since=0", headers=auth(token))).json()

    deleted = await client.post(
        "/sync",
        json={"tasks": [task_payload("2026-08-17T14:00:00Z", deleted=True)]},
        headers=auth(token),
    )
    assert deleted.json()["applied"] == 1

    delta = (await client.get(f"/sync?since={first['seq']}", headers=auth(token, "device-b"))).json()
    assert len(delta["tasks"]) == 1
    assert delta["tasks"][0]["deleted"] is True


async def test_push_publishes_event(client, bus):
    token = await register(client)

    events = []

    async def listen():
        async for event in bus.subscribe(1):
            events.append(event)
            break

    import asyncio

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0)
    await client.post("/sync", json={"tasks": [task_payload()]}, headers=auth(token, "device-a"))
    await asyncio.wait_for(listener, timeout=2)

    assert events == [{"seq": 1, "origin": "device-a"}]


async def test_requires_auth(client):
    assert (await client.get("/sync")).status_code == 401
    assert (await client.post("/sync", json={})).status_code == 401


SECTION_UUID = str(uuid.uuid4())
TAG_UUID = str(uuid.uuid4())


async def test_sections_tags_and_new_task_fields_roundtrip(client):
    token = await register(client)

    section = {
        "uuid": SECTION_UUID,
        "project_uuid": PROJECT_UUID,
        "name": "Backlog",
        "sort_order": 1,
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": "2026-08-17T10:00:00Z",
    }
    tag = {
        "uuid": TAG_UUID,
        "name": "errand",
        "color_key": "green",
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": "2026-08-17T10:00:00Z",
    }
    task = task_payload(
        sort_order=5,
        recurrence_rule="weekly;weekday=2",
        checklist='[{"id":"x","title":"step 1","isDone":false}]',
        section_uuid=SECTION_UUID,
        tag_uuids=[TAG_UUID],
    )

    push = await client.post(
        "/sync",
        json={"projects": [project_payload()], "sections": [section], "tags": [tag], "tasks": [task]},
        headers=auth(token),
    )
    assert push.status_code == 200, push.text
    assert push.json()["applied"] == 4

    pull = (await client.get("/sync?since=0", headers=auth(token, "device-b"))).json()
    assert len(pull["sections"]) == 1 and pull["sections"][0]["name"] == "Backlog"
    assert pull["sections"][0]["project_uuid"] == PROJECT_UUID
    assert len(pull["tags"]) == 1 and pull["tags"][0]["name"] == "errand"
    out = pull["tasks"][0]
    assert out["sort_order"] == 5
    assert out["recurrence_rule"] == "weekly;weekday=2"
    assert out["checklist"].startswith("[{")
    assert out["section_uuid"] == SECTION_UUID
    assert out["tag_uuids"] == [TAG_UUID]

    # LWW applies to sections too: older update is rejected as a conflict.
    stale = dict(section, name="Renamed", updated_at="2026-08-17T08:00:00Z")
    conflict = (await client.post("/sync", json={"sections": [stale]}, headers=auth(token))).json()
    assert conflict["applied"] == 0
    assert conflict["conflicts"]["sections"][0]["name"] == "Backlog"
