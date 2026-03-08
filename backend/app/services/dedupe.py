import re
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:
    from rapidfuzz import fuzz as rapidfuzz_fuzz
except Exception:  # pragma: no cover - fallback when optional dependency missing
    rapidfuzz_fuzz = None


TRACKING_QUERY_KEYS = {
    "gh_src",
    "lever-source",
    "source",
    "src",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}
ID_QUERY_KEYS = {
    "gh_jid",
    "id",
    "jid",
    "jobid",
    "job_id",
    "jobreq",
    "posting_id",
    "req",
    "reqid",
    "requisition",
    "requisitionid",
}
COMPANY_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "plc",
}


def canonicalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    query_pairs = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        normalized_key = (key or "").strip().lower()
        if normalized_key in TRACKING_QUERY_KEYS or normalized_key.startswith("utm_"):
            continue
        query_pairs.append((normalized_key, value))
    query = urlencode(sorted(query_pairs))
    normalized_path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), normalized_path, query, ""))


def _similarity(left: str, right: str) -> float:
    if rapidfuzz_fuzz:
        return float(rapidfuzz_fuzz.token_set_ratio(left, right))
    return SequenceMatcher(a=left, b=right).ratio() * 100


def _normalize_text(value: str | None) -> str:
    text = (value or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_company_name(value: str | None) -> str:
    tokens = [token for token in _normalize_text(value).split() if token not in COMPANY_SUFFIXES]
    return " ".join(tokens)


def normalize_title(value: str | None) -> str:
    text = _normalize_text(value)
    text = re.sub(r"\b(role|position|opening|opportunity|job)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_location(value: str | None) -> str:
    text = _normalize_text(value)
    replacements = {
        "on site": "onsite",
        "in office": "in office",
        "united states": "us",
    }
    for left, right in replacements.items():
        text = text.replace(left, right)
    return re.sub(r"\s+", " ", text).strip()


def salary_ranges_overlap(
    left_min: float | None,
    left_max: float | None,
    right_min: float | None,
    right_max: float | None,
) -> bool:
    left_values = [float(value) for value in (left_min, left_max) if value is not None]
    right_values = [float(value) for value in (right_min, right_max) if value is not None]
    if not left_values or not right_values:
        return False
    left_low, left_high = min(left_values), max(left_values)
    right_low, right_high = min(right_values), max(right_values)
    if max(left_low, right_low) <= min(left_high, right_high):
        return True
    left_anchor = left_high or left_low
    right_anchor = right_high or right_low
    if not left_anchor or not right_anchor:
        return False
    gap_ratio = abs(left_anchor - right_anchor) / max(left_anchor, right_anchor)
    return gap_ratio <= 0.15


def description_similarity(left: str | None, right: str | None) -> float:
    left_text = " ".join(_normalize_text(left).split()[:80])
    right_text = " ".join(_normalize_text(right).split()[:80])
    if not left_text or not right_text:
        return 0.0
    return _similarity(left_text, right_text)


def extract_external_job_keys(url: str | None, source: str | None = None, description: str | None = None) -> set[str]:
    keys: set[str] = set()
    canonical = canonicalize_url(url)
    normalized_source = (source or "").strip().lower()
    if canonical:
        parts = urlsplit(canonical)
        host = parts.netloc.lower()
        path = parts.path or ""
        query_pairs = dict(parse_qsl(parts.query, keep_blank_values=True))
        for key, value in query_pairs.items():
            normalized_key = (key or "").strip().lower()
            normalized_value = _normalize_text(value)
            if normalized_key in ID_QUERY_KEYS and len(normalized_value) >= 3:
                keys.add(f"param:{normalized_key}:{normalized_value}")

        path_segments = [segment for segment in path.split("/") if segment]
        digit_tokens = re.findall(r"\b\d{4,}\b", path)
        for token in digit_tokens:
            keys.add(f"path:id:{token}")

        if "greenhouse" in host or normalized_source == "greenhouse":
            for token in digit_tokens:
                keys.add(f"greenhouse:id:{token}")
        if "lever.co" in host or normalized_source == "lever":
            if path_segments:
                tail = _normalize_text(path_segments[-1])
                if len(tail.replace(" ", "")) >= 6:
                    keys.add(f"lever:path:{tail}")
        if "themuse" in host or normalized_source == "themuse":
            if path_segments:
                tail = _normalize_text(path_segments[-1])
                if len(tail.replace(" ", "")) >= 6:
                    keys.add(f"themuse:path:{tail}")
        if "adzuna" in host or normalized_source == "adzuna":
            for token in digit_tokens:
                keys.add(f"adzuna:id:{token}")

    if description:
        for match in re.findall(
            r"\b(?:job|posting|position|requisition|req)(?:\s*(?:id|#|number|no))?\s*[:#-]?\s*([A-Z0-9-]{4,})\b",
            description,
            flags=re.I,
        ):
            keys.add(f"text:ref:{_normalize_text(match)}")
    return keys


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


def is_probable_duplicate(
    *,
    existing_company: str | None,
    existing_title: str | None,
    existing_location: str | None,
    existing_url: str | None,
    existing_source: str | None,
    existing_description: str | None,
    existing_pay_min: float | None,
    existing_pay_max: float | None,
    company: str | None,
    title: str | None,
    location: str | None,
    url: str | None,
    source: str | None,
    description: str | None,
    pay_min: float | None,
    pay_max: float | None,
) -> bool:
    existing_keys = extract_external_job_keys(existing_url, existing_source, existing_description)
    incoming_keys = extract_external_job_keys(url, source, description)
    if existing_keys and incoming_keys and existing_keys.intersection(incoming_keys):
        return True

    company_similarity = _similarity(normalize_company_name(existing_company), normalize_company_name(company))
    title_similarity = _similarity(normalize_title(existing_title), normalize_title(title))
    location_similarity = _similarity(normalize_location(existing_location), normalize_location(location))
    desc_similarity = description_similarity(existing_description, description)
    salary_overlap = salary_ranges_overlap(existing_pay_min, existing_pay_max, pay_min, pay_max)

    if company_similarity >= 95 and title_similarity >= 92 and location_similarity >= 82:
        return True
    if company_similarity >= 92 and title_similarity >= 88 and (salary_overlap or desc_similarity >= 86):
        return True
    if company_similarity >= 90 and desc_similarity >= 93 and title_similarity >= 78:
        return True
    if is_fuzzy_duplicate(
        existing_company,
        existing_title or "",
        existing_location,
        company,
        title or "",
        location,
        threshold=84,
    ):
        if salary_overlap or desc_similarity >= 82 or location_similarity >= 80:
            return True
    return False
