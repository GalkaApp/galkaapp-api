from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_session
from app.schemas import RegisterRequest
from app.services.auth import AuthService

# The app signs in only; accounts are made here. Server-rendered like /admin,
# and hidden from the OpenAPI schema so the Swift type generator never sees it.
router = APIRouter(include_in_schema=False)

templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))

DEVICE_NAME = "Web signup"


def _page(request: Request, status_code: int = 200, **context) -> HTMLResponse:
    return templates.TemplateResponse(request, "signup.html", context, status_code=status_code)


@router.get("/signup")
async def signup_form(request: Request):
    return _page(request)


@router.post("/signup")
async def signup(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    password_confirm: Annotated[str, Form()],
):
    # Re-render with the address filled in on every failure: retyping it is the
    # most annoying part of a form that rejects you.
    if password != password_confirm:
        return _page(request, 400, email=email, error="The passwords do not match.")

    try:
        payload = RegisterRequest(email=email, password=password, device_name=DEVICE_NAME)
    except ValidationError:
        # The only two rules are a real address and six characters, so saying
        # which one failed is more use than echoing pydantic.
        error = (
            "Enter a valid email address."
            if "@" not in email
            else "The password must be between 6 and 72 characters."
        )
        return _page(request, 400, email=email, error=error)

    try:
        await AuthService.register(session, payload)
    except HTTPException as exc:
        if exc.status_code == 409:
            return _page(request, 409, email=email,
                         error="That email already has an account. Sign in from the app instead.")
        raise

    return _page(request, created=True, email=payload.email.lower())
