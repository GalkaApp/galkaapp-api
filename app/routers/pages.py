from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import settings

# The public face of the service: the landing page plus the pages the App Store
# listing has to link to. Server-rendered like /pu and /signup, and hidden
# from the OpenAPI schema so the Swift type generator never sees them.
router = APIRouter(include_in_schema=False)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

# Reviewers read the date at the top of a policy, so it is stated rather than
# generated from "now" — it changes when the text does, not on every deploy.
POLICY_UPDATED = "20 August 2026"


def _context(request: Request) -> dict:
    return {
        "owner": settings.owner_name,
        "contact_email": settings.contact_email,
        "app_store_url": settings.app_store_url,
        "source_url": settings.source_url,
        "docker_image": settings.docker_image,
        "shepta_project": settings.shepta_project,
        "public_url": settings.public_url,
        "server_host": urlparse(settings.public_url).netloc or request.url.netloc,
        "year": date.today().year,
    }


def _page(request: Request, template: str, **extra) -> HTMLResponse:
    return templates.TemplateResponse(request, template, _context(request) | extra)


@router.get("/")
async def landing(request: Request):
    return _page(request, "public/landing.html")


@router.get("/privacy")
async def privacy(request: Request):
    return _page(request, "public/privacy.html", updated=POLICY_UPDATED)


@router.get("/terms")
async def terms(request: Request):
    return _page(request, "public/terms.html", updated=POLICY_UPDATED)


@router.get("/support")
async def support(request: Request):
    return _page(request, "public/support.html")


@router.get("/self-hosting")
async def self_hosting(request: Request):
    return _page(request, "public/self-hosting.html")
