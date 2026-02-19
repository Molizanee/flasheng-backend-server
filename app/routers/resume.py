import asyncio
import base64
import logging
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user_id
from app.database import get_db
from app.models.job import ResumeJob
from app.schemas.job import (
    MyResumeItem,
    ResumeDownloadLinks,
    ResumeJobCreatedResponse,
    ResumeJobResponse,
)
from app.services.payment import payment_service
from app.services.resume_builder import ResumeBuilder

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/resume", tags=["resume"])


async def _run_resume_pipeline(
    job_id: str,
    github_token: str,
    linkedin_pdf_bytes: bytes,
    db_url: str,
):
    """Background task that runs the full resume generation pipeline.

    This runs outside the request lifecycle, so it manages its own DB session.
    """
    from app.database import get_async_session

    session_factory = get_async_session()
    async with session_factory() as session:
        # Mark job as processing
        job = await session.get(ResumeJob, job_id)
        if not job:
            logger.error("[Job %s] Job not found in database", job_id)
            return

        job.status = "processing"
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()

        try:
            builder = ResumeBuilder()
            result = await builder.build_resume(
                github_token=github_token,
                linkedin_pdf_bytes=linkedin_pdf_bytes,
                job_id=job_id,
            )

            # Update job with results
            job.status = "completed"
            job.html_url = result["html_url"]
            job.pdf_url = result["pdf_url"]
            job.cover_url = result.get("cover_url")
            job.github_username = result.get("github_username")
            job.github_data = result.get("github_data")
            job.linkedin_data = result.get("linkedin_data")
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
    github_token: str = Form(..., description="GitHub personal access token"),
    linkedin_pdf: UploadFile = File(..., description="LinkedIn exported PDF resume"),
    user_id: str = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """Submit a resume generation job.

    Accepts a GitHub token and LinkedIn PDF upload. Creates a background job
    and returns a job_id immediately. Poll GET /api/v1/resume/{job_id} for status.

    Requires a valid Supabase JWT in the Authorization header.
    """
    # Validate file type
    if not linkedin_pdf.filename or not linkedin_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="linkedin_pdf must be a PDF file (.pdf extension required)",
        )

    # Read the PDF bytes
    pdf_bytes = await linkedin_pdf.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded PDF file is empty")

    if len(pdf_bytes) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="PDF file too large (max 10MB)")

    credits = await payment_service.get_user_credits(db, user_id)
    if credits < 1:
        raise HTTPException(
            status_code=402,
            detail="Insufficient credits. Please purchase credits to generate a resume.",
        )

    job = ResumeJob(
        status="pending",
        user_id=user_id,
        linkedin_filename=linkedin_pdf.filename,
    )
    session = db
    session.add(job)
    await session.commit()
    await session.refresh(job)

    job_id = str(job.id)
    logger.info(
        "[Job %s] Created for user %s. Starting background pipeline...", job_id, user_id
    )

    # Launch background task
    asyncio.create_task(
        _run_resume_pipeline(
            job_id=job_id,
            github_token=github_token,
            linkedin_pdf_bytes=pdf_bytes,
            db_url="",  # Not needed, we use the shared session factory
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
