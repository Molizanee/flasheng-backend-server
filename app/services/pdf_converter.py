import logging
import tempfile
import os

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class PDFConverter:
    """Converts HTML resume to PDF using Playwright (headless Chromium)."""

    @staticmethod
    async def html_to_pdf(html_content: str) -> bytes:
        """Render HTML string to a PDF byte buffer.

        Args:
            html_content: Complete HTML document string.

        Returns:
            PDF file as bytes.
        """
        # Write HTML to a temp file so Playwright can load it
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            temp_path = f.name

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()

                # Load the HTML file
                await page.goto(f"file://{temp_path}", wait_until="networkidle")

                # Generate PDF with A4 dimensions matching the template
                pdf_bytes = await page.pdf(
                    format="A4",
                    print_background=True,
                    margin={
                        "top": "0mm",
                        "right": "0mm",
                        "bottom": "0mm",
                        "left": "0mm",
                    },
                )

                await browser.close()
                logger.info("PDF generated successfully (%d bytes)", len(pdf_bytes))
                return pdf_bytes

        finally:
            # Clean up temp file
            os.unlink(temp_path)

    @staticmethod
    async def html_to_screenshot(html_content: str) -> bytes:
        """Render HTML string to a WebP screenshot (cover thumbnail).

        Takes a screenshot of the rendered resume at A4-like proportions
        and returns it as WebP bytes suitable for base64 encoding.

        Args:
            html_content: Complete HTML document string.

        Returns:
            WebP image as bytes.
        """
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".html", delete=False, encoding="utf-8"
        ) as f:
            f.write(html_content)
            temp_path = f.name

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                # A4 proportions: 794 x 1123 px at 96 DPI
                page = await browser.new_page(viewport={"width": 794, "height": 1123})

                await page.goto(f"file://{temp_path}", wait_until="networkidle")

                screenshot_bytes = await page.screenshot(
                    type="png",
                    full_page=False,
                )

                await browser.close()
                logger.info(
                    "Cover screenshot generated (%d bytes)", len(screenshot_bytes)
                )
                return screenshot_bytes

        except Exception as e:
            logger.error("Cover screenshot generation failed: %s", e, exc_info=True)
            raise

        finally:
            os.unlink(temp_path)
