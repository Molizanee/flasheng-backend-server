import logging

import pdfshift
from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()
pdfshift.api_key = settings.pdfshift_api_key


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
            response = pdfshift.convert(
                html_content,
                {
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
            logger.info("PDF generated successfully (%d bytes)", len(response))
            return response
        except Exception as e:
            logger.error("PDF generation failed: %s", e, exc_info=True)
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
            response = pdfshift.convert(
                html_content,
                {
                    "format": "png",
                    "options": {
                        "width": 794,
                        "height": 1123,
                    },
                },
            )
            logger.info("Cover screenshot generated (%d bytes)", len(response))
            return response
        except Exception as e:
            logger.error("Cover screenshot generation failed: %s", e, exc_info=True)
            raise
