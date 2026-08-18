import pytest
from httpx import ASGITransport, AsyncClient

from app.events import InMemoryEventBus
from app.main import create_app


@pytest.fixture
def bus():
    return InMemoryEventBus()


@pytest.fixture
async def client(bus):
    app = create_app(database_url="sqlite+aiosqlite:///:memory:", bus=bus)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as http:
            yield http


async def register(client: AsyncClient, email="a@example.com", password="secret1"):
    response = await client.post(
        "/auth/register", json={"email": email, "password": password, "device_name": "tests"}
    )
    assert response.status_code == 201, response.text
    return response.json()["token"]


def auth(token: str, device: str = "device-a") -> dict:
    return {"Authorization": f"Bearer {token}", "X-Device-Id": device}
