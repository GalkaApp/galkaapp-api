from datetime import date, datetime

from app.models import User
from app.services.digest import DigestService
from tests.conftest import auth, register


async def test_account_defaults(client):
    token = await register(client, email="a@example.com")
    response = await client.get("/account", headers=auth(token))
    assert response.status_code == 200
    assert response.json() == {
        "email": "a@example.com", "daily_digest": False, "timezone": "UTC", "digest_hour": 8,
        "language": "en",
    }


async def test_account_requires_token(client):
    assert (await client.get("/account")).status_code == 401
    assert (await client.patch("/account", json={})).status_code == 401


async def test_account_partial_update(client):
    token = await register(client)
    response = await client.patch(
        "/account", json={"daily_digest": True, "timezone": "Asia/Kolkata"}, headers=auth(token)
    )
    assert response.status_code == 200
    assert response.json()["timezone"] == "Asia/Kolkata"

    response = await client.patch("/account", json={"digest_hour": 6}, headers=auth(token))
    body = response.json()
    assert body["daily_digest"] is True and body["timezone"] == "Asia/Kolkata"
    assert body["digest_hour"] == 6

    assert (await client.get("/account", headers=auth(token))).json() == body


async def test_account_rejects_bad_values(client):
    token = await register(client)
    for payload in ({"timezone": "Mars/Olympus"}, {"timezone": ""}, {"digest_hour": 24},
                    {"digest_hour": -1}, {"language": "de"}):
        response = await client.patch("/account", json=payload, headers=auth(token))
        assert response.status_code == 422, payload


def make_user(**fields) -> User:
    defaults = {"daily_digest": True, "timezone": "UTC", "digest_hour": 8, "digest_sent_on": None,
                "language": "en"}
    return User(email="a@example.com", password_hash="x", **{**defaults, **fields})


def test_digest_due_in_users_local_morning():
    moscow = make_user(timezone="Europe/Moscow")  # UTC+3
    assert not DigestService.is_due(moscow, datetime(2026, 9, 23, 4, 59))
    assert DigestService.is_due(moscow, datetime(2026, 9, 23, 5, 0))
    # Catch-up window closes three hours after the digest hour.
    assert DigestService.is_due(moscow, datetime(2026, 9, 23, 7, 59))
    assert not DigestService.is_due(moscow, datetime(2026, 9, 23, 8, 0))


def test_digest_uses_local_date_across_utc_midnight():
    tokyo = make_user(timezone="Asia/Tokyo", digest_hour=7)  # UTC+9
    now = datetime(2026, 9, 22, 22, 30)  # 07:30 on the 23rd in Tokyo
    assert DigestService.is_due(tokyo, now)
    assert DigestService.local_now(tokyo, now).date() == date(2026, 9, 23)

    tokyo.digest_sent_on = date(2026, 9, 23)
    assert not DigestService.is_due(tokyo, now)
    tokyo.digest_sent_on = date(2026, 9, 22)
    assert DigestService.is_due(tokyo, now)


def test_digest_off_or_bad_timezone():
    assert not DigestService.is_due(make_user(daily_digest=False), datetime(2026, 9, 23, 8, 0))
    # An unresolvable stored zone falls back to UTC rather than crashing the sender.
    assert DigestService.is_due(make_user(timezone="Nope/Nope"), datetime(2026, 9, 23, 8, 0))


async def test_due_users_and_claim(client):
    token = await register(client, email="a@example.com")
    await register(client, email="b@example.com")
    await client.patch("/account", json={"daily_digest": True, "timezone": "Europe/Moscow"},
                       headers=auth(token))

    now = datetime(2026, 9, 23, 5, 30)  # 08:30 in Moscow
    async with client._transport.app.state.db.session() as session:
        due = await DigestService.due_users(session, now)
        assert [u.email for u in due] == ["a@example.com"]
        assert await DigestService.claim(session, due[0], date(2026, 9, 23))
        # A second worker racing for the same user loses the claim.
        assert not await DigestService.claim(session, due[0], date(2026, 9, 23))
        assert await DigestService.due_users(session, now) == []
