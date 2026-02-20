import logging
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.resume import ResumeData
from app.services.ai_agent import AIAgent
from app.services.pdf_converter import PDFConverter
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


class ResumeBuilder:
    """Orchestrates the full resume generation pipeline.

    Flow:
    1. Scrape LinkedIn job data
    2. Scrape LinkedIn profile data (optional based on platform_content)
    3. Fetch GitHub data (optional based on platform_content)
    4. Send data to AI agent
    5. Render HTML from template
    6. Convert HTML to PDF
    7. Generate cover screenshot (PNG)
    8. Upload HTML, PDF, and cover to Supabase Storage
    """

    def __init__(self):
        self.ai_agent = AIAgent()
        self.storage = StorageService()
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,
        )

    async def build_resume(
        self,
        db: AsyncSession,
        job_data: dict[str, Any],
        linkedin_data: dict[str, Any] | None = None,
        github_data: dict[str, Any] | None = None,
        platform_content: str = "linkedin",
        language: str = "en",
        job_id: str = "",
    ) -> dict:
        """Execute the full resume generation pipeline.

        Args:
            db: Database session
            job_data: Scraped LinkedIn job data
            linkedin_data: Scraped LinkedIn profile data (optional)
            github_data: Fetched GitHub profile data (optional)
            platform_content: Platform mode - "linkedin", "github", or "mixed"
            language: Language code for the resume (default: "en")
            job_id: Unique job identifier for file naming

        Returns:
            Dict with html_url, pdf_url, and generated resume_data

        Raises:
            Exception: Any step failure propagates up
        """
        logger.info(
            "[Job %s] Generating resume with AI agent (platform: %s)...",
            job_id,
            platform_content,
        )
        resume_data = await self.ai_agent.generate_resume_data(
            db=db,
            job_data=job_data,
            linkedin_data=linkedin_data,
            github_data=github_data,
            platform_content=platform_content,
            language=language,
        )
        logger.info("[Job %s] AI resume data generated successfully", job_id)

        logger.info("[Job %s] Rendering HTML template...", job_id)
        html_content = self._render_html(resume_data, language)

        logger.info("[Job %s] Converting HTML to PDF...", job_id)
        pdf_bytes = await PDFConverter.html_to_pdf(html_content)

        logger.info("[Job %s] Generating cover image...", job_id)
        cover_bytes = await PDFConverter.html_to_cover(html_content)

        logger.info("[Job %s] Uploading to Supabase Storage...", job_id)
        html_url = await self.storage.upload_html(html_content, job_id)
        pdf_url = await self.storage.upload_pdf(pdf_bytes, job_id)
        cover_url = await self.storage.upload_cover(cover_bytes, job_id)

        logger.info("[Job %s] Resume build complete!", job_id)

        return {
            "html_url": html_url,
            "pdf_url": pdf_url,
            "cover_url": cover_url,
            "job_data": job_data,
            "linkedin_data": linkedin_data,
            "github_data": github_data,
            "resume_data": resume_data.model_dump(),
        }

    def _render_html(self, resume_data: ResumeData, language: str = "en") -> str:
        """Render the Jinja2 template with resume data.

        Args:
            resume_data: Structured resume data from the AI agent
            language: Language code for the resume

        Returns:
            Complete HTML document string
        """
        template = self.jinja_env.get_template("resume_template.html")
        return template.render(resume=resume_data, language=language)
