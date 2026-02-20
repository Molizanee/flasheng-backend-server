import json
import logging
import os
import re
from datetime import datetime
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

SCRAPFLY_API_URL = "https://api.scrapfly.io/scrape"
SCRAPFLY_MAX_RETRIES = 3

ANYSITE_API_URL = "https://api.anysite.io/scrape"
ANYSITE_MAX_RETRIES = 3

API_LOGS_DIR = "api_responses_logs"

# Extraction prompt for Scrapfly job scraping
SCRAPFLY_JOB_EXTRACTION_PROMPT = """Return in this format only:

# Company
- company name here

# Job description
- Job description here

Obs: dont return any other not relevant information about the job"""


def _save_api_log(filename: str, data: dict[str, Any]) -> None:
    """Save API response data to JSON file in dev mode.

    Args:
        filename: Name of the JSON file
        data: Data to save
    """
    settings = get_settings()
    if not settings.dev:
        return

    try:
        os.makedirs(API_LOGS_DIR, exist_ok=True)
        filepath = os.path.join(API_LOGS_DIR, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved API log to {filepath}")
    except Exception as e:
        logger.warning(f"Failed to save API log: {e}")

LINKEDIN_JOB_URL_PATTERN = re.compile(
    r"https?://(?:www\.)?linkedin\.com/jobs/(?:view|job)/[\w-]+|"
    r"https?://(?:www\.)?linkedin\.com/jobs/collections/recommended/.*currentJobId=\d+"
)
LINKEDIN_PROFILE_URL_PATTERN = re.compile(r"https?://(?:www\.)?linkedin\.com/in/[\w-]+")


def _extract_job_id_from_collections_url(url: str) -> str | None:
    """Extract job ID from LinkedIn collections URL format.

    Args:
        url: LinkedIn URL (e.g., /jobs/collections/recommended/?currentJobId=123)

    Returns:
        Job ID string if found, None otherwise
    """
    import re
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    job_id = query_params.get("currentJobId", [None])[0]
    return job_id


def _convert_to_job_view_url(url: str) -> str:
    """Convert collections URL to job view URL if needed.

    Args:
        url: LinkedIn job URL (collections or view format)

    Returns:
        Proper job view URL
    """
    if "/jobs/collections/" in url:
        job_id = _extract_job_id_from_collections_url(url)
        if job_id:
            return f"https://www.linkedin.com/jobs/view/{job_id}"
    return url


def validate_linkedin_job_url(url: str) -> bool:
    """Validate if the URL is a valid LinkedIn job URL."""
    return bool(LINKEDIN_JOB_URL_PATTERN.match(url))


def validate_linkedin_profile_url(url: str) -> bool:
    """Validate if the URL is a valid LinkedIn profile URL."""
    return bool(LINKEDIN_PROFILE_URL_PATTERN.match(url))


class LinkedInScraper:
    """Scraper service for LinkedIn using Scrapfly API for jobs and AnySite API for profiles."""

    def __init__(self):
        self.settings = get_settings()
        self.scrapfly_api_key = self.settings.scrapfly_api_key
        self.anysite_api_key = self.settings.anysite_api_key

    async def _scrape_with_retry(self, url: str) -> dict[str, Any]:
        """Scrape a URL using Scrapfly with retry logic.

        Args:
            url: The URL to scrape

        Returns:
            Scraped data as dictionary

        Raises:
            Exception: If all retries fail
        """
        last_error = None

        for attempt in range(1, SCRAPFLY_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=60.0) as client:
                    response = await client.get(
                        SCRAPFLY_API_URL,
                        params={
                            "key": self.scrapfly_api_key,
                            "url": url,
                            "asp": "true",
                            "format": "json",
                            "proxy_pool": "public_residential_pool",
                        },
                    )

                    if response.status_code != 200:
                        logger.warning(
                            f"Scrapfly API error (attempt {attempt}/{SCRAPFLY_MAX_RETRIES}): "
                            f"{response.status_code} - {response.text}"
                        )
                        last_error = f"API error: {response.status_code}"
                        continue

                    data = response.json()

                    if data.get("status") == "error":
                        error_msg = data.get("message", "Unknown error")
                        logger.warning(
                            f"Scrapfly error (attempt {attempt}/{SCRAPFLY_MAX_RETRIES}): {error_msg}"
                        )
                        last_error = error_msg
                        continue

                    return data

            except httpx.TimeoutException:
                logger.warning(f"Timeout (attempt {attempt}/{SCRAPFLY_MAX_RETRIES})")
                last_error = "Request timeout"
            except Exception as e:
                logger.warning(f"Error (attempt {attempt}/{SCRAPFLY_MAX_RETRIES}): {e}")
                last_error = str(e)

        raise Exception(
            f"Failed to scrape after {SCRAPFLY_MAX_RETRIES} attempts: {last_error}"
        )

    async def scrape_job(self, job_url: str) -> dict[str, Any]:
        """Scrape job details from LinkedIn using Scrapfly SDK.

        Args:
            job_url: LinkedIn job URL

        Returns:
            Dictionary containing job data:
            - title: Job title
            - company: Company name
            - location: Job location
            - description: Job description
            - requirements: List of requirements
            - responsibilities: List of responsibilities
            - benefits: List of benefits (if available)
            - employment_type: Full-time, part-time, etc.
            - seniority_level: Entry level, senior, etc.
            - posted_date: When the job was posted
            - applicants: Number of applicants (if available)
        """
        from scrapfly import ScrapflyClient, ScrapeConfig

        logger.info(f"Scraping LinkedIn job: {job_url}")

        # Convert collections URL to view URL for better scraping
        actual_url = _convert_to_job_view_url(job_url)
        if actual_url != job_url:
            logger.info(f"Converted collections URL to: {actual_url}")

        last_error = None

        for attempt in range(1, SCRAPFLY_MAX_RETRIES + 1):
            try:
                client = ScrapflyClient(key=self.scrapfly_api_key)
                result = client.scrape(ScrapeConfig(
                    proxy_pool="public_residential_pool",
                    format="text",                    
                    asp=True,
                    url=actual_url,
                ))

                logger.info(f"Scrapfly result: {result.content}")
                # Parse the extracted content from the AI response
                extracted_content = result.content
                job_data = self._parse_extracted_job_content(extracted_content, actual_url)

                logger.info(f"Job scraped data: {job_data}")
                logger.info(f"Successfully scraped job: {job_data.get('title', 'Unknown')}")

                # Save to JSON file in dev mode
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                job_id = actual_url.split("/")[-1].split("?")[0] if "/" in actual_url else "unknown"
                _save_api_log(f"job_{job_id}_{timestamp}.json", job_data)

                return job_data

            except Exception as e:
                logger.warning(f"Error (attempt {attempt}/{SCRAPFLY_MAX_RETRIES}): {e}")
                last_error = str(e)

        raise Exception(
            f"Failed to scrape job after {SCRAPFLY_MAX_RETRIES} attempts: {last_error}"
        )

    def _parse_extracted_job_content(self, extracted_content: str, url: str) -> dict[str, Any]:
        """Parse job data from Scrapfly AI-extracted markdown content.

        Args:
            extracted_content: Markdown content extracted by Scrapfly AI
            url: Original job URL

        Returns:
            Parsed job data
        """
        job_data = {
            "url": url,
            "title": "",
            "company": "",
            "location": "",
            "description": "",
            "requirements": [],
            "responsibilities": [],
            "benefits": [],
            "employment_type": "",
            "seniority_level": "",
            "posted_date": "",
            "applicants": "",
        }

        if not extracted_content:
            logger.warning("Empty extracted content from Scrapfly AI")
            return job_data

        try:
            lines = extracted_content.split("\n")
            current_section = None
            description_lines = []

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                # Parse Company section
                if line.startswith("# Company"):
                    current_section = "company"
                    continue
                elif line.startswith("# Job description"):
                    current_section = "description"
                    continue

                # Extract company name (bullet point format)
                if current_section == "company" and line.startswith("-"):
                    job_data["company"] = line.lstrip("-").strip()
                    current_section = None

                # Extract job description
                if current_section == "description":
                    if line.startswith("-"):
                        description_lines.append(line.lstrip("-").strip())
                    else:
                        description_lines.append(line)

            # Join description lines
            job_data["description"] = "\n".join(description_lines)

            # Try to extract job title from URL if not found in extraction
            if not job_data["title"] and "/jobs/view/" in url:
                job_id = url.split("/jobs/view/")[-1].split("?")[0]
                # Try to get title from description first line if it looks like a title
                if description_lines and len(description_lines[0]) < 100:
                    # Check if first line looks like a job title (short, no bullet)
                    first_line = description_lines[0]
                    if not first_line.startswith("-") and len(first_line) < 100:
                        job_data["title"] = first_line

        except Exception as e:
            logger.error(f"Error parsing extracted job content: {e}")
            # Fallback: store raw content as description
            job_data["description"] = extracted_content

        return job_data

    async def scrape_profile(self, profile_url: str) -> dict[str, Any]:
        """Scrape profile details from LinkedIn.

        Args:
            profile_url: LinkedIn profile URL

        Returns:
            Dictionary containing profile data:
            - name: Full name
            - headline: Professional headline
            - about: About section
            - experience: List of experience items
            - education: List of education items
            - skills: List of skills
            - languages: List of languages
            - location: Location
            - connections: Number of connections
        """
        logger.info(f"Scraping LinkedIn profile: {profile_url}")

        # Use AnySite API for profile scraping
        anysite_data = await self._scrape_profile_with_anysite(profile_url)
        logger.info(f"AnySite raw response: {anysite_data}")

        profile_data = self._parse_anysite_profile(anysite_data, profile_url)
        logger.info(f"Profile parsed data: {profile_data}")
        logger.info(
            f"Successfully scraped profile: {profile_data.get('name', 'Unknown')}"
        )

        # Save to JSON file in dev mode
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        username = profile_url.split("/")[-1].split("?")[0] if "/" in profile_url else "unknown"
        _save_api_log(f"profile_{username}_{timestamp}.json", profile_data)

        return profile_data

    async def _scrape_profile_with_anysite(self, profile_url: str) -> dict[str, Any]:
        """Scrape LinkedIn profile using AnySite API.

        Args:
            profile_url: LinkedIn profile URL (e.g., https://linkedin.com/in/username)

        Returns:
            Raw AnySite API response data

        Raises:
            Exception: If all retries fail
        """
        last_error = None

        # Extract username from URL
        match = re.search(r'linkedin\.com/in/([^/?]+)', profile_url)
        if not match:
            raise ValueError(f"Invalid LinkedIn profile URL: {profile_url}")
        username = match.group(1)

        for attempt in range(1, ANYSITE_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    # Extract username from URL for the "user" parameter
                    match = re.search(r'linkedin\.com/in/([^/?]+)', profile_url)
                    username = match.group(1) if match else profile_url

                    response = await client.post(
                        "https://api.anysite.io/api/linkedin/user",
                        headers={
                            "access-token": self.anysite_api_key,
                            "Content-Type": "application/json",
                        },
                        json={
                            "user": username,
                            "timeout": 300,
                            "with_experience": True,
                            "with_education": True,
                            "with_skills": True,
                            "with_languages": True,
                            "with_honors": False,
                            "with_certificates": False,
                            "with_patents": False,
                        },
                    )

                    if response.status_code != 200:
                        logger.warning(
                            f"AnySite API error (attempt {attempt}/{ANYSITE_MAX_RETRIES}): "
                            f"{response.status_code} - {response.text}"
                        )
                        last_error = f"API error: {response.status_code}"
                        continue

                    data = response.json()
                    return data

            except httpx.TimeoutException:
                logger.warning(f"Timeout (attempt {attempt}/{ANYSITE_MAX_RETRIES})")
                last_error = "Request timeout"
            except Exception as e:
                logger.warning(f"Error (attempt {attempt}/{ANYSITE_MAX_RETRIES}): {e}")
                last_error = str(e)

        raise Exception(
            f"Failed to scrape profile after {ANYSITE_MAX_RETRIES} attempts: {last_error}"
        )

    def _parse_anysite_profile(self, anysite_data: dict[str, Any], url: str) -> dict[str, Any]:
        """Parse AnySite profile response into standard format.

        Args:
            anysite_data: Raw AnySite API response
            url: Original profile URL

        Returns:
            Parsed profile data in standard format
        """
        # AnySite returns a list with one profile object
        profile_list = anysite_data if isinstance(anysite_data, list) else [anysite_data]
        if not profile_list:
            return {
                "url": url,
                "name": "",
                "headline": "",
                "about": "",
                "experience": [],
                "education": [],
                "skills": [],
                "languages": [],
                "location": "",
                "connections": "",
            }

        raw_profile = profile_list[0]

        # Map experience
        experience = []
        for exp in raw_profile.get("experience", []):
            experience.append({
                "company": exp.get("company", {}).get("name", ""),
                "position": exp.get("position", ""),
                "date_range": exp.get("period", exp.get("interval", "")),
                "location": exp.get("location", ""),
                "description": exp.get("description", ""),
            })

        # Map education
        education = []
        for edu in raw_profile.get("education", []):
            education.append({
                "institution": edu.get("company", {}).get("name", ""),
                "degree": edu.get("major", ""),
                "date_range": edu.get("interval", ""),
            })

        # Map skills - combine top_skills and skills
        all_skills = raw_profile.get("top_skills", [])
        for skill_obj in raw_profile.get("skills", []):
            skill_name = skill_obj.get("name", "")
            if skill_name and skill_name not in all_skills:
                all_skills.append(skill_name)

        # Map languages
        languages = []
        for lang in raw_profile.get("languages", []):
            lang_name = lang.get("name", "")
            lang_level = lang.get("level", "")
            if lang_name:
                languages.append(f"{lang_name} ({lang_level})" if lang_level else lang_name)

        # Build full name
        first_name = raw_profile.get("first_name", "")
        last_name = raw_profile.get("last_name", "")
        full_name = f"{first_name} {last_name}".strip()

        profile_data = {
            "url": url,
            "name": full_name,
            "headline": raw_profile.get("headline", ""),
            "about": raw_profile.get("description", ""),
            "experience": experience,
            "education": education,
            "skills": all_skills,
            "languages": languages,
            "location": raw_profile.get("location", ""),
            "connections": str(raw_profile.get("connection_count", "")),
        }

        return profile_data

    def _parse_profile_html(self, html: str, url: str) -> dict[str, Any]:
        """Parse profile data from HTML content.

        Args:
            html: Raw HTML content
            url: Original profile URL

        Returns:
            Parsed profile data
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        profile_data = {
            "url": url,
            "name": "",
            "headline": "",
            "about": "",
            "experience": [],
            "education": [],
            "skills": [],
            "languages": [],
            "location": "",
            "connections": "",
        }

        try:
            name_elem = soup.find("h1", class_=re.compile(r"top-card-layout__title"))
            if not name_elem:
                name_elem = soup.find("h1")
            profile_data["name"] = name_elem.get_text(strip=True) if name_elem else ""

            headline_elem = soup.find(
                "h2", class_=re.compile(r"top-card-layout__headline")
            )
            if not headline_elem:
                headline_elem = soup.find("h2")
            profile_data["headline"] = (
                headline_elem.get_text(strip=True) if headline_elem else ""
            )

            location_elem = soup.find(
                "span", class_=re.compile(r"top-card-layout__location")
            )
            profile_data["location"] = (
                location_elem.get_text(strip=True) if location_elem else ""
            )

            about_elem = soup.find("div", class_=re.compile(r"about-section"))
            if not about_elem:
                about_elem = soup.find("section", {"id": "about"})
            if about_elem:
                profile_data["about"] = about_elem.get_text(strip=True)

            experience_section = soup.find("section", id=re.compile(r"experience"))
            if experience_section:
                exp_items = experience_section.find_all(
                    "li", class_=re.compile(r"experience-item")
                )
                for item in exp_items:
                    exp_data = self._parse_experience_item(item)
                    if exp_data:
                        profile_data["experience"].append(exp_data)

            education_section = soup.find("section", id=re.compile(r"education"))
            if education_section:
                edu_items = education_section.find_all(
                    "li", class_=re.compile(r"education-item")
                )
                for item in edu_items:
                    edu_data = self._parse_education_item(item)
                    if edu_data:
                        profile_data["education"].append(edu_data)

            skills_section = soup.find("section", id=re.compile(r"skills"))
            if skills_section:
                skill_items = skills_section.find_all(
                    "span", class_=re.compile(r"skill-name")
                )
                profile_data["skills"] = [
                    s.get_text(strip=True)
                    for s in skill_items
                    if s.get_text(strip=True)
                ]

            languages_section = soup.find("section", id=re.compile(r"languages"))
            if languages_section:
                lang_items = languages_section.find_all(
                    "li", class_=re.compile(r"languages-item")
                )
                profile_data["languages"] = [
                    l.get_text(strip=True) for l in lang_items if l.get_text(strip=True)
                ]

        except Exception as e:
            logger.error(f"Error parsing profile HTML: {e}")

        if not profile_data["name"]:
            profile_data["name"] = self._extract_name_from_html(html)

        return profile_data

    def _parse_experience_item(self, item) -> dict[str, Any] | None:
        """Parse a single experience item from HTML."""
        exp_data = {
            "company": "",
            "position": "",
            "date_range": "",
            "location": "",
            "description": "",
        }

        try:
            company_elem = item.find(
                "h3", class_=re.compile(r"experience-item__company")
            )
            if company_elem:
                exp_data["company"] = company_elem.get_text(strip=True)

            position_elem = item.find(
                "h4", class_=re.compile(r"experience-item__title")
            )
            if position_elem:
                exp_data["position"] = position_elem.get_text(strip=True)

            date_elem = item.find("time")
            if date_elem:
                exp_data["date_range"] = date_elem.get_text(strip=True)

            location_elem = item.find(
                "span", class_=re.compile(r"experience-item__location")
            )
            if location_elem:
                exp_data["location"] = location_elem.get_text(strip=True)

            desc_elem = item.find(
                "p", class_=re.compile(r"experience-item__description")
            )
            if desc_elem:
                exp_data["description"] = desc_elem.get_text(strip=True)

        except Exception as e:
            logger.warning(f"Error parsing experience item: {e}")

        if exp_data["company"] or exp_data["position"]:
            return exp_data
        return None

    def _parse_education_item(self, item) -> dict[str, Any] | None:
        """Parse a single education item from HTML."""
        edu_data = {
            "institution": "",
            "degree": "",
            "date_range": "",
        }

        try:
            institution_elem = item.find(
                "h3", class_=re.compile(r"education-item__school")
            )
            if institution_elem:
                edu_data["institution"] = institution_elem.get_text(strip=True)

            degree_elem = item.find("h4", class_=re.compile(r"education-item__degree"))
            if degree_elem:
                edu_data["degree"] = degree_elem.get_text(strip=True)

            date_elem = item.find("time")
            if date_elem:
                edu_data["date_range"] = date_elem.get_text(strip=True)

        except Exception as e:
            logger.warning(f"Error parsing education item: {e}")

        if edu_data["institution"] or edu_data["degree"]:
            return edu_data
        return None

    def _extract_name_from_html(self, html: str) -> str:
        """Extract name from HTML when structured parsing fails."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")

        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        return ""


linkedin_scraper = LinkedInScraper()
