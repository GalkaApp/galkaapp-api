import uuid

from tests.conftest import auth, register

ADMIN = ("admin", "admin")


async def test_admin_requires_basic_auth(client):
    assert (await client.get("/admin")).status_code == 401
    assert (await client.get("/admin", auth=("admin", "wrong"))).status_code == 401


async def test_admin_overview_and_user_page(client):
    token = await register(client, email="a@example.com")
    task = {
        "uuid": str(uuid.uuid4()),
        "title": "Admin visible task",
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": "2026-08-17T09:00:00Z",
    }
    await client.post("/sync", json={"tasks": [task]}, headers=auth(token))

    index = await client.get("/admin", auth=ADMIN)
    assert index.status_code == 200
    assert "a@example.com" in index.text

    page = await client.get("/admin/users/1", auth=ADMIN)
    assert page.status_code == 200
    assert "Admin visible task" in page.text

    assert (await client.get("/admin/users/999", auth=ADMIN)).status_code == 404


async def test_admin_hidden_from_openapi(client):
    spec = (await client.get("/openapi.json")).json()
    assert not any(path.startswith("/admin") for path in spec["paths"])
