from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class ResumeGenerateRequest(BaseModel):
    """Request body fields sent alongside the file upload.

    The linkedin_pdf is received as an UploadFile, not in this schema.
    """

    github_token: str


class ResumeJobResponse(BaseModel):
    id: UUID
    status: str
    github_username: str | None = None
    html_url: str | None = None
    pdf_url: str | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ResumeJobCreatedResponse(BaseModel):
    job_id: UUID
    status: str
    message: str


class ResumeDownloadLinks(BaseModel):
    """Download URLs for a resume's output files."""

    pdf: str | None = None
    html: str | None = None


class MyResumeItem(BaseModel):
    """A single resume entry returned by the /my-resumes endpoint."""

    resume_cover: str  # base64-encoded PNG screenshot
    download_links: ResumeDownloadLinks
