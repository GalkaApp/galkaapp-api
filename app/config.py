from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Server configuration; values can be overridden via environment variables."""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/todoapi"
    redis_url: str = "redis://localhost:6379/0"
    sse_ping_seconds: int = 15
    admin_username: str = "admin"
    admin_password: str = "admin"

    model_config = {"env_prefix": "TODOAPI_"}


settings = Settings()
