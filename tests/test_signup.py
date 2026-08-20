"""The web signup page.

The app signs in only — accounts are created here, so this page is the only
way a new user gets one.
"""

import pytest

CONSENT = {"accept_terms": "yes", "accept_privacy": "yes"}


def form(**fields) -> dict:
    """A filled-in form: the fields given, both consent boxes ticked."""
    return CONSENT | fields


async def test_form_renders(client):
    response = await client.get("/signup")
    assert response.status_code == 200
    assert "Create your Galka account" in response.text


async def test_creates_an_account_that_can_then_sign_in(client):
    response = await client.post("/signup", data=form(
        email="New@Example.com", password="secret1", password_confirm="secret1",
    ))
    assert response.status_code == 200, response.text
    assert "Account created" in response.text
    # Stored lower-cased, the way AuthService.register normalises it.
    assert "new@example.com" in response.text

    login = await client.post("/auth/login", json={
        "email": "new@example.com", "password": "secret1", "device_name": "mac",
    })
    assert login.status_code == 200, login.text
    assert login.json()["email"] == "new@example.com"


async def test_mismatched_passwords_are_rejected(client):
    response = await client.post("/signup", data=form(
        email="a@example.com", password="secret1", password_confirm="secret2",
    ))
    assert response.status_code == 400
    assert "do not match" in response.text
    # The address survives the round trip; retyping it is the annoying part.
    assert 'value="a@example.com"' in response.text

    login = await client.post("/auth/login", json={
        "email": "a@example.com", "password": "secret1", "device_name": "mac",
    })
    assert login.status_code == 401, "no account should have been created"


async def test_short_password_is_rejected(client):
    response = await client.post("/signup", data=form(
        email="b@example.com", password="short", password_confirm="short",
    ))
    assert response.status_code == 400
    assert "6 and 72 characters" in response.text


async def test_invalid_email_is_rejected(client):
    response = await client.post("/signup", data=form(
        email="not-an-email", password="secret1", password_confirm="secret1",
    ))
    assert response.status_code == 400
    assert "valid email address" in response.text


async def test_duplicate_email_points_at_the_app(client):
    payload = form(email="dup@example.com", password="secret1", password_confirm="secret1")
    first = await client.post("/signup", data=payload)
    assert first.status_code == 200

    second = await client.post("/signup", data=payload)
    assert second.status_code == 409
    assert "already has an account" in second.text


async def test_form_asks_for_both_consents(client):
    body = (await client.get("/signup")).text
    assert 'name="accept_terms"' in body and 'name="accept_privacy"' in body
    # Ticking blind is not consent: both boxes link to what is being accepted.
    assert 'href="/terms"' in body and 'href="/privacy"' in body


@pytest.mark.parametrize("consent, missing", [
    ({}, "the terms of use and the privacy policy"),
    ({"accept_privacy": "yes"}, "the terms of use"),
    ({"accept_terms": "yes"}, "the privacy policy"),
])
async def test_an_account_needs_both_consents(client, consent, missing):
    """The checkboxes are `required` in the browser; the server is the backstop."""
    response = await client.post("/signup", data={
        "email": "c@example.com", "password": "secret1", "password_confirm": "secret1",
        **consent,
    })
    assert response.status_code == 400
    assert f"Please accept {missing} to continue." in response.text

    login = await client.post("/auth/login", json={
        "email": "c@example.com", "password": "secret1", "device_name": "mac",
    })
    assert login.status_code == 401, "no account should have been created"


async def test_the_tick_you_did_make_survives_a_rejection(client):
    response = await client.post("/signup", data={
        "email": "d@example.com", "password": "secret1", "password_confirm": "secret2",
        "accept_terms": "yes", "accept_privacy": "yes",
    })
    assert response.status_code == 400
    assert "do not match" in response.text
    assert response.text.count("checked") == 2


async def test_signup_is_absent_from_the_openapi_schema(client):
    """The Swift type generator reads this schema; page routes must stay out."""
    schema = (await client.get("/openapi.json")).json()
    assert "/signup" not in schema["paths"]
