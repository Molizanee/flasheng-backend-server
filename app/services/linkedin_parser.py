import io
import logging
from typing import Any

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


class LinkedInParser:
    """Parses a LinkedIn-exported PDF resume and extracts structured text data."""

    # Common section headers found in LinkedIn PDFs
    SECTION_MARKERS = [
        "summary",
        "experience",
        "education",
        "skills",
        "licenses & certifications",
        "certifications",
        "volunteer experience",
        "projects",
        "publications",
        "languages",
        "honors & awards",
        "honors-awards",
        "courses",
        "recommendations",
        "interests",
        "organizations",
        "contact",
        "top skills",
    ]

    @staticmethod
    async def parse_pdf(file_bytes: bytes) -> dict[str, Any]:
        """Parse LinkedIn PDF and return structured data.

        Args:
            file_bytes: Raw bytes of the uploaded PDF file.

        Returns:
            Dictionary with extracted resume sections.
        """
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            full_text = ""
            for page in doc:
                full_text += page.get_text("text") + "\n"
            doc.close()

            return LinkedInParser._structure_text(full_text)

        except Exception as e:
            logger.error(f"Failed to parse LinkedIn PDF: {e}")
            return {
                "raw_text": "",
                "sections": {},
                "parse_error": str(e),
            }

    @staticmethod
    def _structure_text(text: str) -> dict[str, Any]:
        """Attempt to split the extracted text into resume sections."""
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # Extract name (usually the first non-empty line)
        name = lines[0] if lines else ""

        # Try to identify headline/title (usually second line)
        headline = lines[1] if len(lines) > 1 else ""

        # Find contact info patterns
        contact_info = LinkedInParser._extract_contact_info(lines)

        # Split into sections
        sections = LinkedInParser._split_into_sections(lines)

        return {
            "raw_text": text,
            "name": name,
            "headline": headline,
            "contact_info": contact_info,
            "sections": sections,
        }

    @staticmethod
    def _extract_contact_info(lines: list[str]) -> dict[str, str]:
        """Extract email, phone, location from lines."""
        info: dict[str, str] = {}
        for line in lines[:15]:  # Contact info is usually near the top
            lower = line.lower()
            if "@" in line and "." in line:
                info["email"] = line.strip()
            elif any(kw in lower for kw in ["linkedin.com", "linkedin.com/in/"]):
                info["linkedin"] = line.strip()
            elif any(kw in lower for kw in ["github.com"]):
                info["github"] = line.strip()
        return info

    @staticmethod
    def _split_into_sections(lines: list[str]) -> dict[str, str]:
        """Split text lines into resume sections based on known headers."""
        sections: dict[str, str] = {}
        current_section = "header"
        current_content: list[str] = []

        for line in lines:
            lower = line.lower().strip()
            # Check if this line is a section header
            is_header = False
            for marker in LinkedInParser.SECTION_MARKERS:
                if lower == marker or lower == marker.replace(" ", ""):
                    # Save previous section
                    if current_content:
                        sections[current_section] = "\n".join(current_content)
                    current_section = marker
                    current_content = []
                    is_header = True
                    break

            if not is_header:
                current_content.append(line)

        # Save the last section
        if current_content:
            sections[current_section] = "\n".join(current_content)

        return sections
