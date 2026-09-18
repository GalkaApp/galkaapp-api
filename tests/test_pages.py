"""The public pages: landing, privacy, terms, support, self-hosting.

The App Store listing links to the privacy and support URLs, so these must
resolve without an account and without touching the database.
"""

import pytest


PUBLIC_PATHS = ["/", "/privacy", "/terms", "/support", "/self-hosting"]


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


async def test_landing_leads_with_the_store_button(client):
    body = (await client.get("/")).text
    assert 'href="https://apps.apple.com/app/id6803008508"' in body
    assert "Get Galka" in body


async def test_landing_hides_the_store_button_without_a_link(client, monkeypatch):
    """The button is dropped rather than pointing nowhere, e.g. before release."""
    from app.config import settings

    monkeypatch.setattr(settings, "app_store_url", "")
    body = (await client.get("/")).text
    assert "Get Galka" not in body
    # The sync-account button takes over as the page's one filled call to action.
    assert 'class="btn primary" href="/signup"' in body


async def test_landing_carries_the_analytics_tag_when_configured(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "shepta_project", "mm_test")
    body = (await client.get("/")).text
    assert 'src="https://api.shepta.ru/m.js"' in body
    assert 'data-project="mm_test"' in body


async def test_no_page_carries_the_analytics_tag_by_default(client):
    """Unset by default, so a self-hosted copy serves no third-party script."""
    for path in PUBLIC_PATHS:
        assert "shepta.ru" not in (await client.get(path)).text


async def test_analytics_stays_off_the_other_pages(client, monkeypatch):
    """Only the landing page is counted; the legal and signup pages are not."""
    from app.config import settings

    monkeypatch.setattr(settings, "shepta_project", "mm_test")
    for path in ["/privacy", "/terms", "/support", "/self-hosting", "/signup"]:
        assert "shepta.ru" not in (await client.get(path)).text, path


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


async def test_self_hosting_points_at_the_image_and_the_source(client):
    """The two things a self-hoster needs before anything else."""
    body = (await client.get("/self-hosting")).text
    assert "https://github.com/GalkaApp/galkaapp-api" in body
    assert "https://hub.docker.com/r/skymanrm/galkaapp-api" in body
    # The compose snippet has to name the image people can actually pull.
    assert "skymanrm/galkaapp-api:latest" in body


async def test_self_hosting_covers_the_setup_a_run_needs(client):
    body = (await client.get("/self-hosting")).text
    for claim in ["TODOAPI_DATABASE_URL", "TODOAPI_ADMIN_PASSWORD", "docker compose up -d",
                  "pg_dump", "Settings \u25b8 Account \u25b8 Sign in"]:
        assert claim in body, f"self-hosting page does not mention {claim!r}"


async def test_every_page_links_to_the_self_hosting_guide(client):
    """It is reachable from the footer, so no page is a dead end for it."""
    for path in PUBLIC_PATHS:
        assert 'href="/self-hosting"' in (await client.get(path)).text


async def test_signup_links_back_to_the_legal_pages(client):
    body = (await client.get("/signup")).text
    assert 'href="/privacy"' in body and 'href="/terms"' in body


async def test_public_pages_are_absent_from_the_openapi_schema(client):
    """The Swift type generator reads this schema; page routes must stay out."""
    paths = (await client.get("/openapi.json")).json()["paths"]
    for path in PUBLIC_PATHS:
        assert path not in paths
