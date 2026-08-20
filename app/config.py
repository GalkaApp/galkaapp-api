from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Server configuration; values can be overridden via environment variables."""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/todoapi"
    redis_url: str = "redis://localhost:6379/0"
    sse_ping_seconds: int = 15
    admin_username: str = "admin"
    admin_password: str = "admin"

    # Shown on the public pages (landing, privacy, terms, support).
    owner_name: str = "Andrey Fanyagin"
    contact_email: str = "support@getgalka.ru"
    public_url: str = "https://api.getgalka.ru"
    app_store_url: str = ""  # empty until the app is on the store; hides the button

    model_config = {"env_prefix": "TODOAPI_"}


settings = Settings()
