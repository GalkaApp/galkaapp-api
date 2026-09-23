import logging
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import quote
from zoneinfo import available_timezones

from fastapi import APIRouter, Cookie, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_session
from app.mailer import Mailer, SmtpMailer
from app.models import User
from app.services.admin import AdminAuthService, AdminService, AdminUserForm
from app.services.digest import DigestService

# Plain server-rendered pages; hidden from the OpenAPI schema so the
# Swift type generator never sees them.
PREFIX = "/pu"
COOKIE = "galka_pu"

router = APIRouter(prefix=PREFIX, include_in_schema=False)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
logger = logging.getLogger(__name__)


def get_mailer() -> Mailer | None:
    """None when SMTP is not configured; tests override it with an in-memory outbox."""
    return SmtpMailer.from_settings(settings)


@lru_cache(maxsize=1)
def timezone_names() -> list[str]:
    return sorted(available_timezones())


def _safe_next(target: str | None) -> str:
    """Only redirect back into /pu, never to another host."""
    if target and target.startswith(PREFIX) and not target.startswith("//"):
        return target
    return PREFIX


async def require_admin(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=COOKIE)] = None,
) -> str:
    username = await AdminAuthService.resolve(session, token)
    if username is None:
        target = quote(request.url.path, safe="/")
        raise HTTPException(status_code=303, headers={"Location": f"{PREFIX}/login?next={target}"})
    return username


@router.get("/login")
async def login_form(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    next: str | None = None,
    token: Annotated[str | None, Cookie(alias=COOKIE)] = None,
):
    if await AdminAuthService.resolve(session, token) is not None:
        return RedirectResponse(_safe_next(next), status_code=303)
    return templates.TemplateResponse(request, "admin/login.html", {"next": _safe_next(next)})


@router.post("/login")
async def login(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    username: Annotated[str, Form()],
    password: Annotated[str, Form()],
    next: Annotated[str | None, Form()] = None,
):
    if not AdminAuthService.check_credentials(username, password):
        return templates.TemplateResponse(
            request, "admin/login.html",
            {"next": _safe_next(next), "username": username, "error": "Wrong username or password."},
            status_code=401,
        )
    token = await AdminAuthService.create_session(session, username)
    response = RedirectResponse(_safe_next(next), status_code=303)
    response.set_cookie(
        COOKIE, token,
        max_age=int(AdminAuthService.SESSION_TTL.total_seconds()),
        path=PREFIX, httponly=True, samesite="lax",
        secure=request.url.scheme == "https",
    )
    return response


@router.post("/logout")
async def logout(
    session: Annotated[AsyncSession, Depends(get_session)],
    token: Annotated[str | None, Cookie(alias=COOKIE)] = None,
):
    await AdminAuthService.revoke(session, token)
    response = RedirectResponse(f"{PREFIX}/login", status_code=303)
    response.delete_cookie(COOKIE, path=PREFIX)
    return response


@router.get("")
async def index(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[str, Depends(require_admin)],
):
    rows = await AdminService.overview(session)
    return templates.TemplateResponse(request, "admin/index.html", {"rows": rows, "admin": admin})


async def _user_or_404(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


async def _user_page(request: Request, session: AsyncSession, user_id: int, admin: str,
                     status_code: int = 200, **extra):
    detail = await AdminService.user_detail(session, user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="User not found")
    context = {**detail, "admin": admin, "mail_enabled": bool(settings.smtp_host),
               "timezones": timezone_names(), **extra}
    return templates.TemplateResponse(request, "admin/user.html", context, status_code=status_code)


@router.get("/users/{user_id}")
async def user_detail(
    user_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[str, Depends(require_admin)],
    digest: str | None = None,
    saved: bool = False,
):
    return await _user_page(request, session, user_id, admin, digest=digest, saved=saved)


@router.post("/users/{user_id}")
async def update_user(
    user_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin: Annotated[str, Depends(require_admin)],
    email: Annotated[str, Form()],
    timezone: Annotated[str, Form()],
    digest_hour: Annotated[str, Form()],
    language: Annotated[str, Form()],
    password: Annotated[str, Form()] = "",
    # An unticked checkbox is absent from the body.
    daily_digest: Annotated[bool, Form()] = False,
):
    user = await _user_or_404(session, user_id)
    typed = {"email": email, "timezone": timezone, "digest_hour": digest_hour,
             "language": language, "daily_digest": daily_digest}
    try:
        form = AdminUserForm(**typed, password=password)
    except ValidationError as exc:
        return await _user_page(request, session, user_id, admin, 400,
                                form=typed, error=AdminUserForm.first_error(exc))
    error = await AdminService.update_user(session, user, form)
    if error:
        return await _user_page(request, session, user_id, admin, 400, form=typed, error=error)
    return RedirectResponse(f"{PREFIX}/users/{user_id}?saved=1", status_code=303)


@router.post("/users/{user_id}/digest-toggle")
async def toggle_digest(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[str, Depends(require_admin)],
    enabled: Annotated[bool, Form()] = False,
    next: Annotated[str | None, Form()] = None,
):
    await AdminService.set_digest(session, await _user_or_404(session, user_id), enabled)
    return RedirectResponse(_safe_next(next), status_code=303)


@router.post("/users/{user_id}/digest")
async def send_digest_now(
    user_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    mailer: Annotated[Mailer | None, Depends(get_mailer)],
    _: Annotated[str, Depends(require_admin)],
):
    """Send today's digest right away, outside the schedule and even if empty."""
    await _user_or_404(session, user_id)
    outcome = "off"
    if mailer is not None:
        try:
            await DigestService.deliver(session, mailer, user_id, force=True)
            outcome = "sent"
        except Exception:
            logger.exception("manual digest to user %s failed", user_id)
            outcome = "failed"
    return RedirectResponse(f"{PREFIX}/users/{user_id}?digest={outcome}", status_code=303)
