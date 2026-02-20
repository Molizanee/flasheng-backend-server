import asyncio
import base64
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db
from app.models.job import ResumeJob
from app.models.user import User
from app.schemas.job import (
    MyResumeItem,
    ResumeDownloadLinks,
    ResumeJobCreatedResponse,
    ResumeJobResponse,
)
from app.services.linkedin_scraper import (
    LinkedInScraper,
    validate_linkedin_job_url,
)
from app.config import get_settings
from app.services.payment import payment_service
from app.services.resume_builder import ResumeBuilder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/resume", tags=["resume"])

settings = get_settings()


async def _run_resume_pipeline(
    job_id: str,
    job_url: str,
    profile_url: str,
    language: str,
    platform_content: str = "linkedin",
    github_token: str | None = None,
):
    """Background task that runs the full resume generation pipeline.

    This runs outside the request lifecycle, so it manages its own DB session.
    """
    from app.database import get_async_session
    from app.services.github import GitHubService
    from app.services.linkedin_scraper import LinkedInScraper

    session_factory = get_async_session()
    async with session_factory() as session:
        job = await session.get(ResumeJob, job_id)
        if not job:
            logger.error("[Job %s] Job not found in database", job_id)
            return

        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()

        try:
            scraper = LinkedInScraper()

            job_data = {}
            if job_url and settings.experimental_job_details:
                logger.info("[Job %s] Scraping LinkedIn job: %s", job_id, job_url)
                job_data = await scraper.scrape_job(job_url)
                logger.info(
                    "[Job %s] Job scraped: %s at %s",
                    job_id,
                    job_data.get("title"),
                    job_data.get("company"),
                )
            elif job_url and not settings.experimental_job_details:
                logger.info("[Job %s] Skipping job scraping - experimental_job_details disabled", job_id)

            linkedin_data = {}
            github_data = {}

            if platform_content in ["linkedin", "mixed"]:
                if profile_url:
                    logger.info(
                        "[Job %s] Scraping LinkedIn profile: %s", job_id, profile_url
                    )
                    linkedin_data = await scraper.scrape_profile(profile_url)
                    logger.info(
                        "[Job %s] Profile scraped: %s",
                        job_id,
                        linkedin_data.get("name"),
                    )

            if platform_content in ["github", "mixed"]:
                if github_token:
                    logger.info("[Job %s] Fetching GitHub profile...", job_id)
                    github_service = GitHubService(token=github_token)
                    github_data = await github_service.fetch_comprehensive_profile()
                    logger.info(
                        "[Job %s] GitHub data fetched for user: %s",
                        job_id,
                        github_data.get("profile", {}).get("username"),
                    )

            builder = ResumeBuilder()
            result = await builder.build_resume(
                db=session,
                job_data=job_data,
                linkedin_data=linkedin_data,
                github_data=github_data,
                platform_content=platform_content,
                language=language,
                job_id=job_id,
            )

            job.status = "completed"
            job.html_url = result["html_url"]
            job.pdf_url = result["pdf_url"]
            job.cover_url = result.get("cover_url")
            job.linkedin_data = result.get("linkedin_data")
            job.github_data = result.get("github_data")
            job.ai_generated_data = result.get("resume_data")
            job.updated_at = datetime.now(timezone.utc)

            session_factory_deduct = get_async_session()
            async with session_factory_deduct() as deduct_session:
                deducted = await payment_service.deduct_credit(
                    deduct_session, str(job.user_id)
                )
                if not deducted:
                    logger.error(
                        "[Job %s] Failed to deduct credit from user %s",
                        job_id,
                        job.user_id,
                    )

            await session.commit()

            logger.info("[Job %s] Pipeline completed successfully", job_id)

        except Exception as e:
            logger.exception("[Job %s] Pipeline failed: %s", job_id, e)
            job.status = "failed"
            job.error = str(e)
            job.updated_at = datetime.now(timezone.utc)
            await session.commit()


# ──────────────────────────────────────────────────────────────────────
# IMPORTANT: /my-resumes must be defined BEFORE /{job_id} so that
# FastAPI does not try to interpret "my-resumes" as a UUID path param.
# ──────────────────────────────────────────────────────────────────────


@router.get("/my-resumes", response_model=list[MyResumeItem])
async def get_my_resumes(
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Return all completed resumes for the authenticated user.

    Each item includes a base64-encoded PNG cover thumbnail and download
    links for the PDF and HTML files stored in Supabase Storage.

    Requires a valid Supabase JWT in the Authorization header.
    """
    result = await db.execute(
        select(ResumeJob)
        .where(ResumeJob.user_id == user_id, ResumeJob.status == "completed")
        .order_by(ResumeJob.created_at.desc())
    )
    jobs = result.scalars().all()

    items: list[MyResumeItem] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for job in jobs:
            # Fetch cover image and encode as base64
            resume_cover = ""
            if job.cover_url:
                try:
                    resp = await client.get(job.cover_url)
                    resp.raise_for_status()
                    cover_b64 = base64.b64encode(resp.content).decode("ascii")
                    resume_cover = f"data:image/png;base64,{cover_b64}"
                except Exception as exc:
                    logger.warning(
                        "[Job %s] Failed to fetch cover image: %s", job.id, exc
                    )

            items.append(
                MyResumeItem(
                    resume_cover=resume_cover,
                    download_links=ResumeDownloadLinks(
                        pdf=job.pdf_url,
                        html=job.html_url,
                    ),
                )
            )

    return items


@router.post("/generate", response_model=ResumeJobCreatedResponse, status_code=202)
async def generate_resume(
    linkedin_job_url: str | None = Form(None, description="LinkedIn job URL (optional, requires experimental_job_details flag)"),
    language: str = Form("en", description="Resume language (en or pt-br)"),
    platform_content: str = Form(
        "linkedin", description="Content platform: linkedin, github, or mixed"
    ),
    github_token: str | None = Form(
        None, description="GitHub personal access token (required for github/mixed)"
    ),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Submit a resume generation job.

    Accepts a LinkedIn job URL, language, and platform_content. Creates a background job
    and returns a job_id immediately. Poll GET /api/v1/resume/{job_id} for status.

    platform_content options:
    - "linkedin": Use only LinkedIn profile data
    - "github": Use only GitHub profile data (requires github_token)
    - "mixed": Use both LinkedIn and GitHub data (requires github_token)

    The user's LinkedIn profile URL must be saved in their profile before
    generating a resume (unless using github-only mode).

    Requires a valid Supabase JWT in the Authorization header.
    """
    logger.info(
        "[Request] /generate called by user %s | job_url=%s | language=%s | platform=%s",
        user_id,
        linkedin_job_url,
        language,
        platform_content,
    )

    if linkedin_job_url and not validate_linkedin_job_url(linkedin_job_url):
        logger.warning("[Request] Invalid LinkedIn job URL: %s", linkedin_job_url)
        raise HTTPException(
            status_code=400,
            detail="Invalid LinkedIn job URL. Please provide a valid LinkedIn job URL.",
        )

    if language not in ["en", "pt-br"]:
        logger.warning("[Request] Unsupported language: %s", language)
        raise HTTPException(
            status_code=400,
            detail="Unsupported language. Supported languages: en, pt-br",
        )

    if platform_content not in ["linkedin", "github", "mixed"]:
        logger.warning("[Request] Invalid platform_content: %s", platform_content)
        raise HTTPException(
            status_code=400,
            detail="Invalid platform_content. Supported: linkedin, github, mixed",
        )

    if platform_content in ["github", "mixed"] and not github_token:
        logger.warning(
            "[Request] Missing GitHub token for platform: %s", platform_content
        )
        raise HTTPException(
            status_code=400,
            detail="GitHub token is required for github and mixed platform modes",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        logger.warning("[Request] User not found: %s", user_id)
        raise HTTPException(status_code=404, detail="User not found")

    if platform_content != "github" and not user.linkedin_url:
        logger.warning(
            "[Request] User %s has no LinkedIn URL (platform: %s)",
            user_id,
            platform_content,
        )
        raise HTTPException(
            status_code=400,
            detail="LinkedIn profile URL not found. Please save your LinkedIn profile URL first using PUT /api/v1/users/me",
        )

    credits = await payment_service.get_user_credits(db, user_id)
    logger.info("[Request] User %s has %s credits", user_id, credits)
    if credits < 1:
        logger.warning(
            "[Request] User %s has insufficient credits: %s", user_id, credits
        )
        raise HTTPException(
            status_code=402,
            detail="Insufficient credits. Please purchase credits to generate a resume.",
        )

    job = ResumeJob(
        status="pending",
        user_id=user_id,
        linkedin_filename=linkedin_job_url,
    )
    session = db
    session.add(job)
    await session.commit()
    await session.refresh(job)

    job_id = str(job.id)
    logger.info(
        "[Job %s] Created for user %s | platform=%s | language=%s | profile_url=%s | credits=%s. Starting background pipeline...",
        job_id,
        user_id,
        platform_content,
        language,
        user.linkedin_url if user.linkedin_url else "none",
        credits,
    )

    asyncio.create_task(
        _run_resume_pipeline(
            job_id=job_id,
            job_url=linkedin_job_url,
            profile_url=user.linkedin_url if user.linkedin_url else "",
            language=language,
            platform_content=platform_content,
            github_token=github_token,
        )
    )

    return ResumeJobCreatedResponse(
        job_id=job.id,
        status="pending",
        message="Resume generation started. Poll GET /api/v1/resume/{job_id} for status.",
    )


@router.get("/{job_id}", response_model=ResumeJobResponse)
async def get_job_status(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get the status of a resume generation job.

    Returns current status and, when completed, the URLs to download the resume.
    """
    result = await db.execute(select(ResumeJob).where(ResumeJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return ResumeJobResponse.model_validate(job)


@router.get("/{job_id}/download")
async def download_resume(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get download URLs for a completed resume.

    Returns both HTML and PDF URLs when the job is completed.
    """
    result = await db.execute(select(ResumeJob).where(ResumeJob.id == job_id))
    job = result.scalar_one_or_none()

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status == "pending" or job.status == "processing":
        raise HTTPException(
            status_code=409,
            detail=f"Resume is still being generated (status: {job.status}). Please try again later.",
        )

    if job.status == "failed":
        raise HTTPException(
            status_code=500,
            detail=f"Resume generation failed: {job.error}",
        )

    return {
        "job_id": str(job.id),
        "status": job.status,
        "html_url": job.html_url,
        "pdf_url": job.pdf_url,
    }
