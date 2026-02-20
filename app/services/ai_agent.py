import json
import logging
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.prompt import SystemPrompt
from app.schemas.resume import ResumeData

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

DEFAULT_SYSTEM_PROMPT = """You are an expert professional resume writer and career consultant specializing in ATS optimization and AI-driven resume formatting.
Your task is to create a polished, ATS-friendly, and SEO-optimized resume by combining data from available sources:

1. **LinkedIn Job Description** - Contains the job requirements, responsibilities, and qualifications.
2. **LinkedIn Profile Data** - Contains the user's work history, education, skills, and professional summary.
3. **GitHub Profile Data** - Contains repositories, commits, pull requests, and contribution statistics.

Your job is to:
- Customize the resume to match the job requirements and keywords for optimal ATS scoring
- Highlight the user's relevant experience and skills that match the job
- Prioritize ACCURACY: only include information that is supported by the provided data
- Write a compelling professional summary that highlights both their professional experience and technical skills
- Organize technical skills by category, matching the job requirements
- For work experience, use the profile data as the primary source but tailor bullet points to match the job
- Use strong action verbs and quantify achievements wherever the data supports it
- Keep the tone professional, concise, and impactful
- Format experience bullet points to follow the STAR method where possible (Situation, Task, Action, Result)
- **SEO & AI Optimization**: Include relevant industry keywords, technical terminology, and skills that match the job description
- **SEO Keywords**: Extract and include key terms from the job posting (technologies, methodologies, frameworks, certifications) to maximize ATS compatibility
- Use semantic HTML formatting with <strong> tags for key achievements and technologies

IMPORTANT: You must respond with a valid JSON object matching the exact schema specified. Do not include any text outside the JSON object. Do not wrap in markdown code blocks."""

USER_PROMPT_LINKEDIN_ONLY = """Based on the following LinkedIn data, generate a complete professional resume tailored to the job description.

## LinkedIn Job Description
{job_data}

## LinkedIn Profile Data
{linkedin_data}

## Required JSON Output Schema
Respond with a JSON object with this EXACT structure:
{{
    "full_name": "User's full name",
    "title": "Professional title/headline",
    "email": "email@example.com",
    "github_url": "https://github.com/username",
    "linkedin_url": "https://linkedin.com/in/username",
    "professional_summary": "A compelling 3-5 sentence professional summary combining profile and job requirements. Use <strong> tags for key highlights.",
    "technical_skills": {{
        "ai_data": "AI/ML related skills if any, comma separated",
        "languages_frameworks": "Programming languages and frameworks, comma separated",
        "data_infrastructure": "Databases, message queues, data tools, comma separated",
        "cloud_devops": "Cloud providers, DevOps tools, CI/CD, comma separated",
        "testing_practices": "Testing frameworks and methodologies, comma separated",
        "ai_safety": "AI safety and guardrails skills if any, comma separated"
    }},
    "experience": [
        {{
            "company": "Company Name",
            "position": "Job Title",
            "date_range": "Month Year - Month Year",
            "bullets": [
                "Achievement-oriented bullet point with <strong>key metrics</strong> highlighted",
                "Another bullet point"
            ]
        }}
    ],
    "education": [
        {{
            "institution": "University Name",
            "degree": "Degree type and field",
            "date_range": "Year - Year"
        }}
    ],
    "languages": ["English (Fluent)", "Portuguese (Native)"],
    "personal_projects": [],
    "seo_keywords": "Comma-separated list of key technologies, skills, and methodologies from the job description (e.g., Project Management, Agile, Leadership, Data Analysis, Strategic Planning)"
}}

IMPORTANT RULES FOR LINKEDIN PROFILES:
1. Only include skill categories that have actual content. If a category has no relevant skills, set it to an empty string "".
2. Use <strong> HTML tags to highlight key metrics, technologies, and achievements in the summary and bullet points.
3. Keep bullet points concise but impactful - each should demonstrate value.
4. The professional summary should be a single paragraph suitable for HTML rendering.
5. Customize the resume content to match the job requirements and keywords.
6. SEO keywords must include key terms from the job posting to maximize ATS compatibility
7. Personal projects should be an empty array [] for LinkedIn-only profiles
8. Respond ONLY with the JSON object, no additional text."""

USER_PROMPT_GITHUB_ONLY = """Based on the following GitHub profile data, generate a complete professional resume tailored to the job description.

## LinkedIn Job Description
{job_data}

## GitHub Profile Data
{github_data}

## Required JSON Output Schema
Respond with a JSON object with this EXACT structure:
{{
    "full_name": "User's full name",
    "title": "Professional title/headline",
    "email": "Use the email from github_data.profile.email if available, otherwise leave empty",
    "github_url": "https://github.com/username",
    "linkedin_url": "https://linkedin.com/in/username",
    "professional_summary": "A compelling 3-5 sentence professional summary highlighting technical skills from GitHub and matching job requirements. Use <strong> tags for key highlights. Focus on quantifiable impact from GitHub contributions.",
    "technical_skills": {{
        "ai_data": "AI/ML related skills if any, comma separated",
        "languages_frameworks": "Programming languages and frameworks, comma separated",
        "data_infrastructure": "Databases, message queues, data tools, comma separated",
        "cloud_devops": "Cloud providers, DevOps tools, CI/CD, comma separated",
        "testing_practices": "Testing frameworks and methodologies, comma separated",
        "ai_safety": "AI safety and guardrails skills if any, comma separated"
    }},
    "experience": [
        {{
            "company": "Company Name (if available from GitHub profile, otherwise 'Independent/Freelance')",
            "position": "Software Developer / Open Source Contributor",
            "date_range": "Based on GitHub account creation and activity",
            "bullets": [
                "Achievement-oriented bullet point with <strong>key metrics</strong> highlighted"
            ]
        }}
    ],
    "education": [
        {{
            "institution": "University Name",
            "degree": "Degree type and field",
            "date_range": "Year - Year"
        }}
    ],
    "languages": ["English (Fluent)", "Portuguese (Native)"],
    "personal_projects": [
        {{
            "name": "Repository Name",
            "description": "Brief description of what the project does and its purpose",
            "technologies": "Tech stack used (e.g., Python, React, Docker, AWS)",
            "url": "https://github.com/username/repo-name",
            "highlights": [
                "Analyzed <strong>X commits</strong> showing consistent development practices",
                "Implemented <strong>feature Y</strong> resulting in Z improvement",
                "Collaborated through <strong>N pull requests</strong> demonstrating code review skills",
                "Built with <strong>technologies</strong> matching industry standards",
                "Maintained <strong>high code quality</strong> with descriptive commit messages"
            ]
        }}
    ],
    "seo_keywords": "Comma-separated list of key technologies, skills, and methodologies from the job description and GitHub activity (e.g., Python, React, AWS, CI/CD, Agile, Machine Learning, REST APIs)"
}}

IMPORTANT RULES FOR GITHUB PROFILES:
1. Extract and showcase ALL GitHub work - repositories, commits, pull requests, and contributions
2. For personal_projects, analyze repositories, recent commits, and pinned repos to understand what the user built
3. Include repository-specific highlights showing: commit patterns, PR activity, technologies used, and project impact
4. Transform GitHub activity into professional experience bullets (e.g., 'Maintained 5+ active repositories with 200+ commits')
5. SEO keywords must include technologies from both the job posting AND the user's most-used languages from GitHub
6. Only include skill categories that have actual content. If a category has no relevant skills, set it to an empty string "".
7. Use <strong> HTML tags to highlight key metrics, technologies, and achievements in the summary and bullet points.
8. The professional summary should emphasize technical expertise shown in GitHub activity.
9. Customize the resume content to match the job requirements and keywords.
10. Respond ONLY with the JSON object, no additional text."""

USER_PROMPT_MIXED = """Based on the following LinkedIn and GitHub data, generate a complete professional resume tailored to the job description.

## LinkedIn Job Description
{job_data}

## LinkedIn Profile Data
{linkedin_data}

## GitHub Profile Data
{github_data}

## Required JSON Output Schema
Respond with a JSON object with this EXACT structure:
{{
    "full_name": "User's full name",
    "title": "Professional title/headline",
    "email": "Use the email from github_data.profile.email if available, otherwise use linkedin_data contact info if available, otherwise leave empty",
    "github_url": "https://github.com/username",
    "linkedin_url": "https://linkedin.com/in/username",
    "professional_summary": "A compelling 3-5 sentence professional summary combining LinkedIn professional experience with GitHub technical achievements. Use <strong> tags for key highlights.",
    "technical_skills": {{
        "ai_data": "AI/ML related skills if any, comma separated",
        "languages_frameworks": "Programming languages and frameworks, comma separated",
        "data_infrastructure": "Databases, message queues, data tools, comma separated",
        "cloud_devops": "Cloud providers, DevOps tools, CI/CD, comma separated",
        "testing_practices": "Testing frameworks and methodologies, comma separated",
        "ai_safety": "AI safety and guardrails skills if any, comma separated"
    }},
    "experience": [
        {{
            "company": "Company Name",
            "position": "Job Title",
            "date_range": "Month Year - Month Year",
            "bullets": [
                "Achievement-oriented bullet point with <strong>key metrics</strong> highlighted",
                "Another bullet point"
            ]
        }}
    ],
    "education": [
        {{
            "institution": "University Name",
            "degree": "Degree type and field",
            "date_range": "Year - Year"
        }}
    ],
    "languages": ["English (Fluent)", "Portuguese (Native)"],
    "personal_projects": [
        {{
            "name": "Repository Name",
            "description": "Brief description of what the project does and its purpose",
            "technologies": "Tech stack used (e.g., Python, React, Docker, AWS)",
            "url": "https://github.com/username/repo-name",
            "highlights": [
                "Analyzed <strong>X commits</strong> showing consistent development practices",
                "Implemented <strong>feature Y</strong> resulting in Z improvement",
                "Collaborated through <strong>N pull requests</strong> demonstrating code review skills",
                "Built with <strong>technologies</strong> matching industry standards",
                "Maintained <strong>high code quality</strong> with descriptive commit messages"
            ]
        }}
    ],
    "seo_keywords": "Comma-separated list of key technologies, skills, and methodologies from the job description and GitHub activity (e.g., Python, React, AWS, CI/CD, Agile, Machine Learning, REST APIs)"
}}

IMPORTANT RULES FOR MIXED PROFILES:
1. Combine LinkedIn work experience with GitHub technical contributions
2. For personal_projects, analyze repositories, recent commits, and pinned repos to showcase technical depth
3. Include repository-specific highlights showing: commit patterns, PR activity, technologies used, and project impact
4. Highlight notable GitHub projects within experience bullets where relevant
5. SEO keywords must include technologies from both the job posting AND the user's most-used languages from GitHub
6. Only include skill categories that have actual content. If a category has no relevant skills, set it to an empty string "".
7. Use <strong> HTML tags to highlight key metrics, technologies, and achievements in the summary and bullet points.
8. Keep bullet points concise but impactful - each should demonstrate value.
9. The professional summary should be a single paragraph suitable for HTML rendering.
10. Customize the resume content to match the job requirements and keywords.
11. Respond ONLY with the JSON object, no additional text."""


class AIAgent:
    """AI agent that uses OpenRouter to generate structured resume content."""

    def __init__(self):
        self.settings = get_settings()

    async def get_system_prompt(self, db: AsyncSession, language: str = "en") -> str:
        """Fetch the system prompt from the database based on language.

        Args:
            db: Database session
            language: Language code (e.g., "en", "pt-br")

        Returns:
            The system prompt string
        """
        result = await db.execute(
            select(SystemPrompt).where(SystemPrompt.language == language)
        )
        prompt = result.scalar_one_or_none()

        if prompt:
            return prompt.prompt

        logger.warning(
            f"No custom prompt found for language '{language}', using default"
        )
        return DEFAULT_SYSTEM_PROMPT

    async def generate_resume_data(
        self,
        db: AsyncSession,
        job_data: dict[str, Any],
        linkedin_data: dict[str, Any] | None = None,
        github_data: dict[str, Any] | None = None,
        platform_content: str = "linkedin",
        language: str = "en",
    ) -> ResumeData:
        """Send job and profile data to the AI model and get structured resume data back.

        Args:
            db: Database session
            job_data: Scraped LinkedIn job data.
            linkedin_data: Scraped LinkedIn profile data (optional).
            github_data: Fetched GitHub profile data (optional).
            platform_content: Platform mode - "linkedin", "github", or "mixed".
            language: Language code for the system prompt (default: "en")

        Returns:
            ResumeData with all resume sections populated.

        Raises:
            ValueError: If the AI response cannot be parsed.
            httpx.HTTPStatusError: If the API call fails.
        """
        system_prompt = await self.get_system_prompt(db, language)

        if platform_content == "linkedin":
            user_prompt = USER_PROMPT_LINKEDIN_ONLY.format(
                job_data=json.dumps(job_data, indent=2, default=str),
                linkedin_data=json.dumps(linkedin_data or {}, indent=2, default=str),
            )
        elif platform_content == "github":
            user_prompt = USER_PROMPT_GITHUB_ONLY.format(
                job_data=json.dumps(job_data, indent=2, default=str),
                github_data=json.dumps(github_data or {}, indent=2, default=str),
            )
        else:
            user_prompt = USER_PROMPT_MIXED.format(
                job_data=json.dumps(job_data, indent=2, default=str),
                linkedin_data=json.dumps(linkedin_data or {}, indent=2, default=str),
                github_data=json.dumps(github_data or {}, indent=2, default=str),
            )

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {self.settings.openrouter_api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://flash-resume-builder.com",
                    "X-Title": "Flash Resume Builder",
                },
                json={
                    "model": self.settings.openrouter_model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 8000,
                },
            )

            if response.status_code != 200:
                logger.error(
                    "OpenRouter API error %s: %s",
                    response.status_code,
                    response.text,
                )
                response.raise_for_status()

        result = response.json()
        content = result["choices"][0]["message"]["content"]

        logger.info(
            "AI generation complete. Model: %s, Tokens: %s",
            result.get("model", "unknown"),
            result.get("usage", {}),
        )

        # Parse the JSON response
        try:
            # Handle potential markdown code blocks in response
            cleaned = content.strip()
            if not cleaned:
                logger.error("AI returned empty response. Raw result: %s", result)
                raise ValueError("AI returned empty response")

            if cleaned.startswith("```"):
                # Remove markdown code block wrapper
                lines = cleaned.split("\n")
                cleaned = "\n".join(lines[1:-1])

            resume_dict = json.loads(cleaned)
            return ResumeData(**resume_dict)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Failed to parse AI response: %s", e)
            logger.debug("Raw AI response: %s", content)
            raise ValueError(
                f"AI returned invalid resume data: {e}. "
                "This may be a transient issue - try regenerating."
            ) from e
