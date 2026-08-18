import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.deps import get_current_user
from app.models import User

router = APIRouter(tags=["events"])


@router.get("/events")
async def events(
    request: Request,
    user: Annotated[User, Depends(get_current_user)],
):
    """SSE stream: emits {"seq": N, "origin": "<device>"} after each push.

    Clients react by pulling GET /sync?since=<local cursor>; events with their
    own origin (X-Device-Id) can be ignored.
    """
    bus = request.app.state.bus

    async def generator():
        async for event in bus.subscribe(user.id):
            yield {"event": "sync", "data": json.dumps(event)}

    return EventSourceResponse(generator(), ping=settings.sse_ping_seconds)
