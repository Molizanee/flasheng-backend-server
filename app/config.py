from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Supabase
    supabase_url: str
    supabase_key: str
    supabase_bucket_name: str = "resumes"
    supabase_jwt_secret: str = ""

    # Database
    database_url: str

    # OpenRouter AI
    openrouter_api_key: str
    openrouter_model: str = "minimax/m2.5"

    # AbacatePay
    abacatepay_api_key: str
    abacatepay_webhook_secret: str = ""
    abacatepay_public_key: str = ""
    credit_price_cents: int = 1000

    # Scrapfly
    scrapfly_api_key: str

    # AnySite
    anysite_api_key: str

    # CORS
    allowed_domains: list[str] = ["*"]
    app_name: str = "Flash Resume Builder"
    debug: bool = False
    dev: bool = False  # Enables dev features like auto-simulating payments
    experimental_job_details: bool = False  # Enables experimental job scraping feature

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def normalize_database_url(self) -> "Settings":
        """Ensure DATABASE_URL uses the asyncpg driver.

        Supabase and other providers often give a plain 'postgresql://' URL.
        SQLAlchemy needs 'postgresql+asyncpg://' for async support.
        """
        url = self.database_url
        if url.startswith("postgresql://"):
            self.database_url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif url.startswith("postgres://"):
            self.database_url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
