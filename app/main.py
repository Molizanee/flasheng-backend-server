import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import get_engine
from app.models.base import Base
from app.routers.health import router as health_router
from app.routers.payment import router as payment_router
from app.routers.resume import router as resume_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

DB_RETRY_ATTEMPTS = 5
DB_RETRY_DELAY_SECONDS = 3


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown events."""
    settings = get_settings()
    logger.info("Starting %s...", settings.app_name)

    # Create database tables with retries
    engine = get_engine()
    for attempt in range(1, DB_RETRY_ATTEMPTS + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created/verified")
            break
        except Exception as e:
            if attempt < DB_RETRY_ATTEMPTS:
                logger.warning(
                    "Database connection attempt %d/%d failed: %s. Retrying in %ds...",
                    attempt,
                    DB_RETRY_ATTEMPTS,
                    e,
                    DB_RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(DB_RETRY_DELAY_SECONDS)
            else:
                logger.error(
                    "Database connection failed after %d attempts: %s. "
                    "The app will start but database operations will fail "
                    "until connectivity is restored.",
                    DB_RETRY_ATTEMPTS,
                    e,
                )

    # Verify Playwright browsers (first run)
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            await browser.close()
            logger.info("Playwright Chromium browser verified")
    except Exception as e:
        logger.warning(
            "Playwright browser not available: %s. "
            "Run 'playwright install chromium' to install.",
            e,
        )

    yield

    # Shutdown
    await engine.dispose()
    logger.info("Database connections closed. Shutting down.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "AI-powered resume builder that combines GitHub profile data "
            "and LinkedIn PDF resumes to generate professional, ATS-friendly resumes."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health_router)
    app.include_router(payment_router)
    app.include_router(resume_router)

    return app


app = create_app()
