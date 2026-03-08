import re

from app.services.constants import SKILLS_DICTIONARY


WORD_SEP = r"(?:\b|\s|/|-)"


def _normalize_text(text: str) -> str:
    # Improve OCR resilience (e.g., "DataDrivenAnalyst", pipes, mixed punctuation).
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    cleaned = (
        spaced.replace("|", " ")
        .replace("·", " ")
        .replace("•", " ")
        .replace("_", " ")
    )
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def extract_skills(text: str | None) -> list[str]:
    if not text:
        return []
    lowered = _normalize_text(text)
    found: list[str] = []
    for skill in SKILLS_DICTIONARY:
        normalized_skill = skill.lower().strip()
        pattern = r"(?<!\w)" + re.escape(normalized_skill).replace(r"\ ", r"\s+") + r"(?!\w)"
        if re.search(pattern, lowered):
            found.append(skill)
    return sorted(set(found))


def extract_keywords(text: str | None, min_len: int = 4) -> list[str]:
    if not text:
        return []
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9+#/.\-]{3,}", text.lower())
    stop = {"with", "that", "this", "will", "have", "from", "your", "their", "about", "team", "work"}
    filtered = [t for t in tokens if len(t) >= min_len and t not in stop]
    top = sorted(set(filtered))
    return top[:80]
