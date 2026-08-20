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
    # An unticked checkbox is simply absent from the form body, so both default
    # to False. The `required` attribute stops it in the browser; this is the
    # backstop for anything that posts straight to the endpoint.
    accept_terms: Annotated[bool, Form()] = False,
    accept_privacy: Annotated[bool, Form()] = False,
):
    # Re-render with the address and the ticks the user did make on every
    # failure: redoing them is the most annoying part of a form that rejects you.
    typed = {"email": email, "accept_terms": accept_terms, "accept_privacy": accept_privacy}

    if not (accept_terms and accept_privacy):
        # Name the one that is missing; "accept the terms" is no help when the
        # terms are ticked and the policy is not.
        missing = "the terms of use" if not accept_terms else "the privacy policy"
        if not (accept_terms or accept_privacy):
            missing = "the terms of use and the privacy policy"
        return _page(request, 400, **typed, error=f"Please accept {missing} to continue.")

    if password != password_confirm:
        return _page(request, 400, **typed, error="The passwords do not match.")

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
        return _page(request, 400, **typed, error=error)

    try:
        await AuthService.register(session, payload)
    except HTTPException as exc:
        if exc.status_code == 409:
            return _page(request, 409, **typed,
                         error="That email already has an account. Sign in from the app instead.")
        raise

    return _page(request, created=True, email=payload.email.lower())
