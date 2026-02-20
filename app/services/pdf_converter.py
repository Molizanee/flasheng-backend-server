import logging

import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()


class PDFConverter:
    """Converts HTML resume to PDF using PDFShift API."""

    @staticmethod
    async def html_to_pdf(html_content: str) -> bytes:
        """Render HTML string to a PDF byte buffer.

        Args:
            html_content: Complete HTML document string.

        Returns:
            PDF file as bytes.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.pdfshift.io/v3/convert/pdf",
                    headers={"X-API-Key": settings.pdfshift_api_key},
                    json={
                        "source": html_content,
                        "format": "pdf",
                        "options": {
                            "margin": {
                                "top": "0",
                                "right": "0",
                                "bottom": "0",
                                "left": "0",
                            },
                        },
                    },
                )
                response.raise_for_status()
                logger.info(
                    "PDF generated successfully (%d bytes)", len(response.content)
                )
                return response.content
        except Exception as e:
            logger.error("PDF generation failed: %s", exc_info=True)
            raise

    @staticmethod
    async def html_to_screenshot(html_content: str) -> bytes:
        """Render HTML string to a PNG screenshot (cover thumbnail).

        Args:
            html_content: Complete HTML document string.

        Returns:
            PNG image as bytes.
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.pdfshift.io/v3/convert/pdf",
                    headers={"X-API-Key": settings.pdfshift_api_key},
                    json={
                        "source": html_content,
                        "format": "png",
                        "options": {
                            "width": 794,
                            "height": 1123,
                        },
                    },
                )
                response.raise_for_status()
                logger.info(
                    "Cover screenshot generated (%d bytes)", len(response.content)
                )
                return response.content
        except Exception as e:
            logger.error("Cover screenshot generation failed: %s", exc_info=True)
            raise
