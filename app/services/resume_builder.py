import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.schemas.resume import ResumeData
from app.services.github import GitHubService
from app.services.linkedin_parser import LinkedInParser
from app.services.ai_agent import AIAgent
from app.services.pdf_converter import PDFConverter
from app.services.storage import StorageService

logger = logging.getLogger(__name__)

# Template directory
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


class ResumeBuilder:
    """Orchestrates the full resume generation pipeline.

    Flow:
    1. Parse LinkedIn PDF
    2. Fetch GitHub data
    3. Send both to AI agent
    4. Render HTML from template
    5. Convert HTML to PDF
    6. Generate cover screenshot (PNG)
    7. Upload HTML, PDF, and cover to Supabase Storage
    """

    def __init__(self):
        self.ai_agent = AIAgent()
        self.storage = StorageService()
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=False,  # We need raw HTML in template (bold tags etc.)
        )

    async def build_resume(
        self,
        github_token: str,
        linkedin_pdf_bytes: bytes,
        job_id: str,
    ) -> dict:
        """Execute the full resume generation pipeline.

        Args:
            github_token: GitHub personal access token.
            linkedin_pdf_bytes: Raw bytes of the LinkedIn PDF.
            job_id: Unique job identifier for file naming.

        Returns:
            Dict with html_url, pdf_url, and generated resume_data.

        Raises:
            Exception: Any step failure propagates up.
        """
        # Step 1: Parse LinkedIn PDF
        logger.info("[Job %s] Parsing LinkedIn PDF...", job_id)
        linkedin_data = await LinkedInParser.parse_pdf(linkedin_pdf_bytes)
        logger.info(
            "[Job %s] LinkedIn data extracted: %d sections found",
            job_id,
            len(linkedin_data.get("sections", {})),
        )

        # Step 2: Fetch comprehensive GitHub profile
        logger.info("[Job %s] Fetching GitHub profile...", job_id)
        github_service = GitHubService(token=github_token)
        github_data = await github_service.fetch_comprehensive_profile()
        github_username = github_data.get("profile", {}).get("username", "unknown")
        logger.info(
            "[Job %s] GitHub data fetched for user: %s (%d repos)",
            job_id,
            github_username,
            len(github_data.get("repositories", [])),
        )

        # Step 3: Generate resume content via AI
        logger.info("[Job %s] Generating resume with AI agent...", job_id)
        resume_data = await self.ai_agent.generate_resume_data(
            linkedin_data=linkedin_data,
            github_data=github_data,
        )
        logger.info("[Job %s] AI resume data generated successfully", job_id)

        # Step 4: Render HTML
        logger.info("[Job %s] Rendering HTML template...", job_id)
        html_content = self._render_html(resume_data)

        # Step 5: Convert to PDF
        logger.info("[Job %s] Converting HTML to PDF...", job_id)
        pdf_bytes = await PDFConverter.html_to_pdf(html_content)

        # Step 6: Generate cover screenshot
        logger.info("[Job %s] Generating cover screenshot...", job_id)
        cover_bytes = await PDFConverter.html_to_screenshot(html_content)

        # Step 7: Upload to Supabase Storage
        logger.info("[Job %s] Uploading to Supabase Storage...", job_id)
        html_url = await self.storage.upload_html(html_content, job_id)
        pdf_url = await self.storage.upload_pdf(pdf_bytes, job_id)
        cover_url = await self.storage.upload_cover(cover_bytes, job_id)

        logger.info("[Job %s] Resume build complete!", job_id)

        return {
            "html_url": html_url,
            "pdf_url": pdf_url,
            "cover_url": cover_url,
            "github_username": github_username,
            "github_data": github_data,
            "linkedin_data": linkedin_data,
            "resume_data": resume_data.model_dump(),
        }

    def _render_html(self, resume_data: ResumeData) -> str:
        """Render the Jinja2 template with resume data.

        Args:
            resume_data: Structured resume data from the AI agent.

        Returns:
            Complete HTML document string.
        """
        template = self.jinja_env.get_template("resume_template.html")
        return template.render(resume=resume_data)
