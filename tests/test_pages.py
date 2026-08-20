"""The public pages: landing, privacy, terms, support.

The App Store listing links to the privacy and support URLs, so these must
resolve without an account and without touching the database.
"""

import pytest


PUBLIC_PATHS = ["/", "/privacy", "/terms", "/support"]


@pytest.mark.parametrize("path", PUBLIC_PATHS)
async def test_page_renders_anonymously(client, path):
    response = await client.get(path)
    assert response.status_code == 200, response.text
    assert "text/html" in response.headers["content-type"]
    assert "Galka" in response.text


async def test_landing_leads_with_the_pitch(client):
    body = (await client.get("/")).text
    assert "Tasks, projects, and a plan" in body
    # The only call to action that always works: sync accounts are made on the web.
    assert 'href="/signup"' in body


async def test_landing_hides_the_store_button_until_there_is_a_link(client):
    body = (await client.get("/")).text
    assert "Get Galka" not in body


@pytest.mark.parametrize("path", PUBLIC_PATHS)
async def test_every_page_links_to_the_legal_pages(client, path):
    body = (await client.get(path)).text
    for link in ('href="/privacy"', 'href="/terms"', 'href="/support"'):
        assert link in body, f"{path} is missing {link}"


async def test_privacy_covers_what_app_review_asks_for(client):
    body = (await client.get("/privacy")).text
    for claim in ["Email address", "bcrypt", "never sold", "Delete your account",
                  "support@getgalka.ru"]:
        assert claim in body, f"privacy policy does not mention {claim!r}"


async def test_terms_name_the_operator_and_the_contact(client):
    body = (await client.get("/terms")).text
    assert "Terms of Use" in body
    assert "Andrey Fanyagin" in body
    assert "support@getgalka.ru" in body


async def test_signup_links_back_to_the_legal_pages(client):
    body = (await client.get("/signup")).text
    assert 'href="/privacy"' in body and 'href="/terms"' in body


async def test_public_pages_are_absent_from_the_openapi_schema(client):
    """The Swift type generator reads this schema; page routes must stay out."""
    paths = (await client.get("/openapi.json")).json()["paths"]
    for path in PUBLIC_PATHS:
        assert path not in paths
