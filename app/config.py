from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Server configuration; values can be overridden via environment variables."""

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/todoapi"
    redis_url: str = "redis://localhost:6379/0"
    sse_ping_seconds: int = 15
    admin_username: str = "admin"
    admin_password: str = "admin"

    # Outgoing mail. An empty host turns email off.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_from_name: str = "Galka"
    # How often the scheduler process (python -m app.scheduler) looks for due digests.
    digest_interval_seconds: int = 300

    # Shown on the public pages (landing, privacy, terms, support).
    owner_name: str = "Andrey Fanyagin"
    contact_email: str = "support@getgalka.ru"
    public_url: str = "https://api.getgalka.ru"
    app_store_url: str = "https://apps.apple.com/app/id6803008508"  # empty hides the button
    # Where the self-hosting page sends people for the code and the image.
    source_url: str = "https://github.com/GalkaApp/galkaapp-api"
    docker_image: str = "skymanrm/galkaapp-api"
    # Shepta project id for the landing page counter. Empty means no script tag,
    # so a self-hosted copy never reports into someone else's account.
    shepta_project: str = ""

    model_config = {"env_prefix": "TODOAPI_"}


settings = Settings()
