import uuid

from app.config import settings
from tests.conftest import auth, register


async def sign_in(client, username=None, password=None, next_path=None):
    form = {"username": username or settings.admin_username,
            "password": password or settings.admin_password}
    if next_path:
        form["next"] = next_path
    return await client.post("/pu/login", data=form)


async def test_pu_redirects_to_login(client):
    response = await client.get("/pu/users/1")
    assert response.status_code == 303
    assert response.headers["location"] == "/pu/login?next=/pu/users/1"

    page = await client.get("/pu/login")
    assert page.status_code == 200
    assert 'name="password"' in page.text


async def test_pu_rejects_wrong_password(client):
    response = await sign_in(client, password="wrong")
    assert response.status_code == 401
    assert "Wrong username or password" in response.text
    assert "galka_pu" not in client.cookies
    assert (await client.get("/pu")).status_code == 303


async def test_pu_basic_auth_no_longer_works(client):
    response = await client.get("/pu", auth=(settings.admin_username, settings.admin_password))
    assert response.status_code == 303


async def test_pu_login_sets_session_and_returns_to_next(client):
    response = await sign_in(client, next_path="/pu/users/1")
    assert response.status_code == 303
    assert response.headers["location"] == "/pu/users/1"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Path=/pu" in cookie and "samesite=lax" in cookie.lower()

    # Already signed in: the login page bounces straight to the panel.
    assert (await client.get("/pu/login")).headers["location"] == "/pu"


async def test_pu_login_ignores_offsite_next(client):
    for target in ("https://evil.example", "//evil.example", "/signup"):
        client.cookies.clear()
        response = await sign_in(client, next_path=target)
        assert response.headers["location"] == "/pu"


async def test_pu_logout_revokes_session(client):
    await sign_in(client)
    token = client.cookies["galka_pu"]
    assert (await client.get("/pu")).status_code == 200

    response = await client.post("/pu/logout")
    assert response.status_code == 303
    assert response.headers["location"] == "/pu/login"

    # Replaying the old cookie must not work once the session row is gone.
    client.cookies.set("galka_pu", token, path="/pu")
    assert (await client.get("/pu")).status_code == 303


async def test_pu_overview_and_user_page(client):
    token = await register(client, email="a@example.com")
    task = {
        "uuid": str(uuid.uuid4()),
        "title": "Admin visible task",
        "created_at": "2026-08-17T09:00:00Z",
        "updated_at": "2026-08-17T09:00:00Z",
    }
    await client.post("/sync", json={"tasks": [task]}, headers=auth(token))
    await client.patch("/account", json={"daily_digest": True, "timezone": "Europe/Moscow",
                                         "digest_hour": 7}, headers=auth(token))
    await sign_in(client)

    index = await client.get("/pu")
    assert index.status_code == 200
    assert "a@example.com" in index.text
    assert "07:00 Europe/Moscow" in index.text
    assert "Sign out" in index.text

    page = await client.get("/pu/users/1")
    assert page.status_code == 200
    assert "Admin visible task" in page.text
    assert "Europe/Moscow" in page.text

    assert (await client.get("/pu/users/999")).status_code == 404


async def test_old_admin_path_is_gone(client):
    assert (await client.get("/admin")).status_code == 404


async def test_pu_hidden_from_openapi(client):
    spec = (await client.get("/openapi.json")).json()
    assert not any(path.startswith(("/pu", "/admin")) for path in spec["paths"])


def edit_form(**overrides):
    form = {"email": "a@example.com", "timezone": "UTC", "digest_hour": "8", "language": "en"}
    return {**form, **overrides}


async def test_pu_edit_user(client):
    await register(client, email="a@example.com")
    await sign_in(client)
    response = await client.post("/pu/users/1", data=edit_form(
        email="New@Example.com", timezone="Asia/Tokyo", digest_hour="6", language="ru",
        daily_digest="true", password="fresh-pass"))
    assert response.status_code == 303
    assert response.headers["location"] == "/pu/users/1?saved=1"

    login = await client.post("/auth/login", json={"email": "new@example.com", "password": "fresh-pass"})
    token = login.json()["token"]
    account = (await client.get("/account", headers=auth(token))).json()
    assert account == {"email": "new@example.com", "daily_digest": True, "timezone": "Asia/Tokyo",
                       "digest_hour": 6, "language": "ru"}


async def test_pu_edit_keeps_password_when_blank(client):
    await register(client, email="a@example.com", password="secret1")
    await sign_in(client)
    await client.post("/pu/users/1", data=edit_form(password=""))
    login = await client.post("/auth/login", json={"email": "a@example.com", "password": "secret1"})
    assert login.status_code == 200


async def test_pu_edit_rejects_bad_input(client):
    await register(client, email="a@example.com")
    await register(client, email="b@example.com")
    await sign_in(client)
    cases = [
        (edit_form(timezone="Mars/Olympus"), "Unknown timezone"),
        (edit_form(digest_hour="25"), "Digest hour"),
        (edit_form(email="not-an-email"), "Email"),
        (edit_form(password="123"), "between 6 and 72"),
        (edit_form(email="b@example.com"), "already belongs to user #2"),
    ]
    for form, message in cases:
        response = await client.post("/pu/users/1", data=form)
        assert response.status_code == 400, form
        assert message in response.text, (form, response.text[-400:])
        # What was typed is shown again rather than the stored value.
        assert f'value="{form["email"]}"' in response.text
    token = (await client.post("/auth/login", json={"email": "a@example.com", "password": "secret1"})).json()["token"]
    assert (await client.get("/account", headers=auth(token))).json()["timezone"] == "UTC"


async def test_pu_digest_toggle(client):
    token = await register(client, email="a@example.com")
    await sign_in(client)
    response = await client.post("/pu/users/1/digest-toggle", data={"enabled": "true", "next": "/pu"})
    assert response.status_code == 303 and response.headers["location"] == "/pu"
    assert (await client.get("/account", headers=auth(token))).json()["daily_digest"] is True
    assert 'title="Turn off"' in (await client.get("/pu")).text

    await client.post("/pu/users/1/digest-toggle", data={"next": "/pu"})
    assert (await client.get("/account", headers=auth(token))).json()["daily_digest"] is False


async def test_pu_edit_requires_login(client):
    await register(client, email="a@example.com")
    assert (await client.post("/pu/users/1", data=edit_form())).status_code == 303
    assert (await client.post("/pu/users/1/digest-toggle", data={"enabled": "true"})).status_code == 303
    assert (await client.post("/pu/users/999/digest-toggle")).status_code == 303
