import logging
import uuid

from supabase import create_client, Client

from app.config import get_settings

logger = logging.getLogger(__name__)


class StorageService:
    """Handles file uploads to Supabase Storage."""

    def __init__(self):
        settings = get_settings()
        self.client: Client = create_client(
            settings.supabase_url, settings.supabase_key
        )
        self.bucket_name = settings.supabase_bucket_name

    async def upload_html(self, html_content: str, job_id: str) -> str:
        """Upload generated HTML resume to Supabase Storage.

        Args:
            html_content: The HTML string.
            job_id: Job identifier used for file naming.

        Returns:
            Public URL of the uploaded file.
        """
        file_path = f"resumes/{job_id}/resume.html"
        content_bytes = html_content.encode("utf-8")

        try:
            logger.info("Uploading HTML to path: %s", file_path)
            response = self.client.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=content_bytes,
                file_options={
                    "content-type": "text/html",
                    "upsert": "true",
                },
            )
            logger.info("HTML upload response: %s", response)
        except Exception as e:
            logger.error("HTML upload failed: %s", e, exc_info=True)
            raise

        public_url = self.client.storage.from_(self.bucket_name).get_public_url(
            file_path
        )
        logger.info("HTML uploaded: %s", public_url)
        return public_url

    async def upload_pdf(self, pdf_bytes: bytes, job_id: str) -> str:
        """Upload generated PDF resume to Supabase Storage.

        Args:
            pdf_bytes: The PDF file as bytes.
            job_id: Job identifier used for file naming.

        Returns:
            Public URL of the uploaded file.
        """
        file_path = f"resumes/{job_id}/resume.pdf"

        try:
            logger.info("Uploading PDF to path: %s", file_path)
            response = self.client.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=pdf_bytes,
                file_options={
                    "content-type": "application/pdf",
                    "upsert": "true",
                },
            )
            logger.info("PDF upload response: %s", response)
        except Exception as e:
            logger.error("PDF upload failed: %s", e, exc_info=True)
            raise

        public_url = self.client.storage.from_(self.bucket_name).get_public_url(
            file_path
        )
        logger.info("PDF uploaded: %s", public_url)
        return public_url

    async def upload_cover(self, cover_bytes: bytes, job_id: str) -> str:
        """Upload resume cover screenshot to Supabase Storage.

        Args:
            cover_bytes: The cover image as PNG bytes.
            job_id: Job identifier used for file naming.

        Returns:
            Public URL of the uploaded file.
        """
        # Use same path structure as HTML and PDF
        file_path = f"resumes/{job_id}/cover.png"

        try:
            logger.info("Uploading cover to path: %s", file_path)
            response = self.client.storage.from_(self.bucket_name).upload(
                path=file_path,
                file=cover_bytes,
                file_options={
                    "content-type": "image/png",
                    "upsert": "true",
                },
            )
            logger.info("Cover upload response: %s", response)
        except Exception as e:
            logger.error("Cover upload failed: %s", e, exc_info=True)
            raise

        public_url = self.client.storage.from_(self.bucket_name).get_public_url(
            file_path
        )
        logger.info("Cover uploaded: %s", public_url)
        return public_url
