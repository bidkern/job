from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from rapidfuzz import fuzz as rapidfuzz_fuzz
except Exception:  # pragma: no cover - fallback when optional dependency missing
    rapidfuzz_fuzz = None


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)))
    normalized_path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), normalized_path, query, ""))


def _similarity(left: str, right: str) -> float:
    if rapidfuzz_fuzz:
        return float(rapidfuzz_fuzz.token_set_ratio(left, right))
    return SequenceMatcher(a=left, b=right).ratio() * 100


def is_fuzzy_duplicate(
    existing_company: str | None,
    existing_title: str,
    existing_location: str | None,
    company: str | None,
    title: str,
    location: str | None,
    threshold: int = 89,
) -> bool:
    left = " | ".join(
        [
            (existing_company or "").strip().lower(),
            existing_title.strip().lower(),
            (existing_location or "").strip().lower(),
        ]
    )
    right = " | ".join(
        [
            (company or "").strip().lower(),
            title.strip().lower(),
            (location or "").strip().lower(),
        ]
    )
    score = _similarity(left, right)
    return score >= threshold
