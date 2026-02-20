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
                request_json = {
                    "source": html_content,
                    "margin": {
                        "top": "0px",
                        "right": "0px",
                        "bottom": "0px",
                        "left": "0px",
                    },
                }
                logger.info("PDFShift request: %s", request_json)
                response = await client.post(
                    "https://api.pdfshift.io/v3/convert/pdf",
                    headers={"X-API-Key": settings.pdfshift_api_key},
                    json=request_json,
                )
                logger.info(
                    "PDFShift response status: %s, body: %s",
                    response.status_code,
                    response.text,
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
    async def html_to_cover(html_content: str) -> bytes:
        """Render HTML string to a PNG cover image.

        Args:
            html_content: Complete HTML document string.

        Returns:
            PNG image as bytes.
        """
        try:
            async with httpx.AsyncClient() as client:
                request_json = {
                    "source": html_content,
                    "viewport": "794x1123",
                    "fullpage": True,
                }
                logger.info("PDFShift cover request: %s", request_json)
                response = await client.post(
                    "https://api.pdfshift.io/v3/convert/png",
                    headers={"X-API-Key": settings.pdfshift_api_key},
                    json=request_json,
                )
                logger.info(
                    "PDFShift cover response status: %s, body: %s",
                    response.status_code,
                    response.text,
                )
                response.raise_for_status()
                logger.info("Cover image generated (%d bytes)", len(response.content))
                return response.content
        except Exception as e:
            logger.error("Cover generation failed: %s", exc_info=True)
            raise
