import json

try:
    import httpx
except Exception:  # pragma: no cover - optional dependency for OpenAI call
    httpx = None

from app.core.config import settings
from app.services.extraction import extract_keywords, extract_skills


def _split_responsibilities(description: str) -> list[str]:
    lines = [l.strip(" -\t") for l in description.splitlines() if l.strip()]
    return [l for l in lines if len(l) > 25][:10]


async def _openai_enhance(payload: dict) -> dict | None:
    if not (settings.openai_enabled and settings.openai_api_key and httpx):
        return None
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.openai_model,
                    "input": (
                        "Return strict JSON with keys ats_keywords, resume_bullet_suggestions, "
                        "cover_letter_draft, outreach_message_draft. Never fabricate claims. "
                        f"Context: {json.dumps(payload)}"
                    ),
                },
            )
            resp.raise_for_status()
            data = resp.json()
        content = data.get("output", [{}])[0].get("content", [{}])[0].get("text")
        return json.loads(content) if content else None
    except Exception:
        return None


async def generate_materials(
    title: str,
    company: str | None,
    description: str | None,
    profile_skills: list[str],
    experience_areas: list[str],
    include_cover_letter: bool,
) -> dict:
    text = description or ""
    job_skills = extract_skills(text)
    keywords = extract_keywords(text)
    ats_keywords = [k for k in job_skills if k.lower() in {s.lower() for s in profile_skills}]
    ats_keywords.extend([k for k in keywords if k in {"sql", "python", "tableau", "power", "dashboard", "analysis"}])
    ats_keywords = sorted(set(ats_keywords))[:20]

    responsibilities = _split_responsibilities(text)
    bullets: list[str] = []
    for area in experience_areas[:6]:
        bullets.append(
            f"Highlight {area} with measurable outcomes tied to {title} responsibilities (only if accurate)."
        )
    for resp in responsibilities[:4]:
        bullets.append(f"Map prior work to this responsibility: {resp[:120]}...")

    company_name = company or "the company"
    outreach = (
        f"Hi, I saw the {title} opportunity at {company_name}. "
        "My background aligns with the core requirements and I would value a short conversation about fit."
    )

    cover_letter = None
    if include_cover_letter:
        cover_letter = (
            f"Dear Hiring Team,\n\n"
            f"I am applying for the {title} role at {company_name}. "
            "My experience aligns with the role requirements, and I can contribute quickly with practical, measurable impact. "
            "I would welcome the chance to discuss how my background maps to your priorities.\n\n"
            "Sincerely,\n[Your Name]"
        )

    base_result = {
        "ats_keywords": ats_keywords,
        "resume_bullet_suggestions": bullets[:10],
        "cover_letter_draft": cover_letter,
        "outreach_message_draft": outreach,
        "requires_export_approval": True,
        "openai_used": False,
    }

    enhanced = await _openai_enhance(
        {
            "title": title,
            "company": company,
            "description": description,
            "profile_skills": profile_skills,
            "experience_areas": experience_areas,
            "include_cover_letter": include_cover_letter,
        }
    )
    if enhanced:
        base_result.update({k: v for k, v in enhanced.items() if k in base_result})
        base_result["openai_used"] = True

    return base_result
