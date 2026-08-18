import secrets
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.deps import get_session
from app.services.admin import AdminService

# Plain server-rendered pages; hidden from the OpenAPI schema so the
# Swift type generator never sees them.
router = APIRouter(prefix="/admin", include_in_schema=False)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
security = HTTPBasic()


def require_admin(credentials: Annotated[HTTPBasicCredentials, Depends(security)]) -> str:
    username_ok = secrets.compare_digest(credentials.username, settings.admin_username)
    password_ok = secrets.compare_digest(credentials.password, settings.admin_password)
    if not (username_ok and password_ok):
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


@router.get("")
async def index(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[str, Depends(require_admin)],
):
    rows = await AdminService.overview(session)
    return templates.TemplateResponse(request, "admin/index.html", {"rows": rows})


@router.get("/users/{user_id}")
async def user_detail(
    user_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[str, Depends(require_admin)],
):
    detail = await AdminService.user_detail(session, user_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="User not found")
    return templates.TemplateResponse(request, "admin/user.html", detail)
