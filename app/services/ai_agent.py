import json
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.schemas.resume import ResumeData

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

SYSTEM_PROMPT = """You are an expert professional resume writer and career consultant.
Your task is to create a polished, ATS-friendly resume by combining data from two sources:

1. **LinkedIn PDF Resume** - Contains the user's work history, education, skills, and professional summary as they've presented it on LinkedIn.
2. **GitHub Profile Data** - Contains their repositories, languages used, commit activity, pinned projects, and contribution statistics, showing their actual technical work.

Your job is to:
- Merge and synthesize both sources into a single, cohesive resume
- Prioritize ACCURACY: only include information that is supported by the provided data
- Write a compelling professional summary that highlights both their professional experience and technical GitHub activity
- Organize technical skills by category, drawing from both LinkedIn skills and GitHub language/framework data
- For work experience, use the LinkedIn data as the primary source but enrich bullet points with relevant GitHub contributions when applicable
- Include notable GitHub projects as talking points within experience or as a separate technical highlights section if warranted
- Use strong action verbs and quantify achievements wherever the data supports it
- Keep the tone professional, concise, and impactful
- Format experience bullet points to follow the STAR method where possible (Situation, Task, Action, Result)

IMPORTANT: You must respond with a valid JSON object matching the exact schema specified. Do not include any text outside the JSON object. Do not wrap in markdown code blocks."""

USER_PROMPT_TEMPLATE = """Based on the following data sources, generate a complete professional resume.

## LinkedIn Resume Data
{linkedin_data}

## GitHub Profile Data
{github_data}

## Required JSON Output Schema
Respond with a JSON object with this EXACT structure:
{{
    "full_name": "User's full name",
    "title": "Professional title/headline",
    "email": "email@example.com",
    "github_url": "https://github.com/username",
    "linkedin_url": "https://linkedin.com/in/username",
    "professional_summary": "A compelling 3-5 sentence professional summary combining LinkedIn and GitHub insights. Use <strong> tags for key highlights.",
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
    "languages": ["English (Fluent)", "Portuguese (Native)"]
}}

IMPORTANT RULES:
1. Only include skill categories that have actual content. If a category has no relevant skills, set it to an empty string "".
2. Use <strong> HTML tags to highlight key metrics, technologies, and achievements in the summary and bullet points.
3. Keep bullet points concise but impactful - each should demonstrate value.
4. The professional summary should be a single paragraph suitable for HTML rendering.
5. Respond ONLY with the JSON object, no additional text."""


class AIAgent:
    """AI agent that uses OpenRouter to generate structured resume content."""

    def __init__(self):
        self.settings = get_settings()

    async def generate_resume_data(
        self,
        linkedin_data: dict[str, Any],
        github_data: dict[str, Any],
    ) -> ResumeData:
        """Send both data sources to the AI model and get structured resume data back.

        Args:
            linkedin_data: Parsed LinkedIn PDF data.
            github_data: Comprehensive GitHub profile data.

        Returns:
            ResumeData with all resume sections populated.

        Raises:
            ValueError: If the AI response cannot be parsed.
            httpx.HTTPStatusError: If the API call fails.
        """
        user_prompt = USER_PROMPT_TEMPLATE.format(
            linkedin_data=json.dumps(linkedin_data, indent=2, default=str),
            github_data=json.dumps(github_data, indent=2, default=str),
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
                        {"role": "system", "content": SYSTEM_PROMPT},
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
