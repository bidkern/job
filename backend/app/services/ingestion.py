import csv
import io
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

try:
    import httpx
except Exception:  # pragma: no cover - optional for remote ingestion
    httpx = None

try:
    from dateutil import parser as dateparser
except Exception:  # pragma: no cover - optional helper
    dateparser = None

from app.services.dedupe import canonicalize_url


def _money_to_float(raw: str) -> float | None:
    txt = (raw or "").strip().lower().replace("$", "").replace(",", "")
    if not txt:
        return None
    mult = 1000 if txt.endswith("k") else 1
    if mult == 1000:
        txt = txt[:-1]
    try:
        return float(txt) * mult
    except ValueError:
        return None


def _salary_from_text(text: str | None) -> tuple[float | None, float | None, str | None]:
    body = (text or "").replace("\n", " ")
    if not body:
        return None, None, None
    body = body.replace("–", "-").replace("—", "-")
    lower = body.lower()

    # Strict patterns to avoid false positives like "3-5 years".
    range_patterns = [
        re.compile(
            r"(\$\s*\d[\d,]*(?:\.\d+)?k?)\s*(?:-|to)\s*(\$\s*\d[\d,]*(?:\.\d+)?k?)\s*(per\s*(?:year|hour)|/yr|/year|/hr|/hour|annual|hourly)?",
            re.I,
        ),
        re.compile(
            r"(usd\s*\d[\d,]*(?:\.\d+)?k?)\s*(?:-|to)\s*(usd\s*\d[\d,]*(?:\.\d+)?k?)\s*(per\s*(?:year|hour)|/yr|/year|/hr|/hour|annual|hourly)?",
            re.I,
        ),
    ]
    for pattern in range_patterns:
        m = pattern.search(body)
        if not m:
            continue
        low = _money_to_float(m.group(1).replace("usd", "").strip())
        high = _money_to_float(m.group(2).replace("usd", "").strip())
        if low is None or high is None:
            continue
        unit_text = (m.group(3) or "").lower()
        if low > high:
            low, high = high, low
        if "hour" in unit_text:
            if high < 8 or high > 500:
                continue
        elif "year" in unit_text or "annual" in unit_text or low >= 1000 or high >= 1000:
            if high < 10000:
                continue
        return low, high, f"${int(low):,} - ${int(high):,}"

    single_pattern = re.compile(
        r"(\$\s*\d[\d,]*(?:\.\d+)?k?|usd\s*\d[\d,]*(?:\.\d+)?k?)\s*(per\s*(?:year|hour)|/yr|/year|/hr|/hour|annual|hourly)",
        re.I,
    )
    m2 = single_pattern.search(body)
    if m2:
        value = _money_to_float(m2.group(1).replace("usd", "").strip())
        unit_text = (m2.group(2) or "").lower()
        if value is None:
            return None, None, None
        if "hour" in unit_text and (value < 8 or value > 500):
            return None, None, None
        if ("year" in unit_text or "annual" in unit_text) and value < 10000:
            return None, None, None
        return value, value, f"${int(value):,}"

    # Last resort: explicit "$120k-$150k" style with salary context.
    if "$" in body and any(tok in lower for tok in ["salary", "compensation", "pay range", "pay", "earn"]):
        m3 = re.search(r"(\$\s*\d[\d,]*(?:\.\d+)?k?)\s*(?:-|to)\s*(\$\s*\d[\d,]*(?:\.\d+)?k?)", body, re.I)
        if m3:
            low = _money_to_float(m3.group(1))
            high = _money_to_float(m3.group(2))
            if low is not None and high is not None:
                if low > high:
                    low, high = high, low
                if low >= 10000 and high >= 10000:
                    return low, high, f"${int(low):,} - ${int(high):,}"

    return None, None, None


def _safe_date(value: str | None) -> datetime | None:
    if not value:
        return None

    if dateparser:
        try:
            return dateparser.parse(value)
        except Exception:
            pass

    candidate = value.strip()
    if not candidate:
        return None

    for fmt in (
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m/%d/%Y",
        "%a, %d %b %Y %H:%M:%S %z",
    ):
        try:
            return datetime.strptime(candidate, fmt)
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None


def _require_httpx(feature_name: str) -> None:
    if httpx is None:
        raise RuntimeError(
            f"{feature_name} requires the optional dependency 'httpx'. "
            "Install dependencies from backend/requirements.txt."
        )


def normalize_job(raw: dict[str, Any], source: str) -> dict[str, Any]:
    title = (raw.get("title") or raw.get("text") or "Untitled Role").strip()
    raw_description = raw.get("raw_description") or raw.get("description") or raw.get("content") or ""
    company = (raw.get("company") or raw.get("company_name") or "").strip() or None
    location = (raw.get("location") or raw.get("location_text") or raw.get("city") or "").strip() or None
    url = (raw.get("url") or raw.get("absolute_url") or "").strip() or None
    remote = (raw.get("remote_type") or "unknown").strip().lower()
    remote_hint = f"{raw.get('location') or ''} {raw.get('description') or raw.get('content') or ''}".lower()
    if remote == "unknown":
        if "hybrid" in remote_hint:
            remote = "hybrid"
        elif "remote" in remote_hint:
            remote = "remote"
        elif any(term in remote_hint for term in ["on-site", "onsite", "on site", "in-office", "in office"]):
            remote = "onsite"
    if remote not in {"onsite", "hybrid", "remote", "unknown"}:
        remote = "unknown"

    def _to_float(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace("$", "").replace(",", "").strip())
        except ValueError:
            return None

    pay_min = _to_float(raw.get("pay_min"))
    pay_max = _to_float(raw.get("pay_max"))
    pay_text = (raw.get("pay_text") or raw.get("salary") or "").strip() or None
    if pay_min is None and pay_max is None:
        parsed_min, parsed_max, parsed_text = _salary_from_text(raw.get("description") or raw.get("content"))
        pay_min = parsed_min
        pay_max = parsed_max
        if not pay_text:
            pay_text = parsed_text

    return {
        "title": title,
        "company": company,
        "location_text": location,
        "city": (raw.get("city") or "").strip() or None,
        "state": (raw.get("state") or "").strip() or None,
        "remote_type": remote,
        "pay_min": pay_min,
        "pay_max": pay_max,
        "pay_text": pay_text,
        "job_type": (raw.get("job_type") or "").strip() or None,
        "seniority": (raw.get("seniority") or "").strip() or None,
        "posted_date": _safe_date(raw.get("posted_date") or raw.get("created_at")),
        "source": source,
        "url": url,
        "canonical_url": canonicalize_url(url),
        "description": (raw.get("description") or raw.get("content") or "").strip(),
        "raw_description": str(raw_description),
        "status": "new",
    }


async def fetch_greenhouse(board_token: str) -> list[dict[str, Any]]:
    _require_httpx("Greenhouse ingestion")
    url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    jobs = data.get("jobs", [])
    out: list[dict[str, Any]] = []
    for j in jobs:
        out.append(
            normalize_job(
                {
                    "title": j.get("title"),
                    "company": board_token,
                    "location": (j.get("location") or {}).get("name"),
                    "url": j.get("absolute_url"),
                    "description": j.get("content"),
                    "posted_date": j.get("updated_at"),
                    "remote_type": "unknown",
                },
                source="greenhouse",
            )
        )
    return out


async def fetch_lever(company_slug: str) -> list[dict[str, Any]]:
    _require_httpx("Lever ingestion")
    url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    out: list[dict[str, Any]] = []
    for j in data:
        out.append(
            normalize_job(
                {
                    "title": j.get("text"),
                    "company": company_slug,
                    "location": (j.get("categories") or {}).get("location"),
                    "url": j.get("hostedUrl"),
                    "description": j.get("descriptionPlain") or j.get("description"),
                    "posted_date": j.get("createdAt"),
                    "remote_type": "unknown",
                },
                source="lever",
            )
        )
    return out


async def fetch_adzuna(app_id: str, app_key: str, where: str, what: str, page: int = 1) -> list[dict[str, Any]]:
    _require_httpx("Adzuna ingestion")
    url = (
        "https://api.adzuna.com/v1/api/jobs/us/search/"
        f"{page}?app_id={app_id}&app_key={app_key}&where={where}&what={what}&results_per_page=30"
    )
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    out: list[dict[str, Any]] = []
    for j in data.get("results", []):
        out.append(
            normalize_job(
                {
                    "title": j.get("title"),
                    "company": (j.get("company") or {}).get("display_name"),
                    "location": (j.get("location") or {}).get("display_name"),
                    "url": j.get("redirect_url"),
                    "description": j.get("description"),
                    "posted_date": j.get("created"),
                    "salary": f"{j.get('salary_min')} - {j.get('salary_max')}",
                    "pay_min": j.get("salary_min"),
                    "pay_max": j.get("salary_max"),
                },
                source="adzuna",
            )
        )
    return out


async def fetch_themuse(location: str = "Ohio", category: str | None = None, page: int = 1) -> list[dict[str, Any]]:
    _require_httpx("The Muse ingestion")
    params = {"location": location, "page": page}
    if category:
        params["category"] = category
    url = "https://www.themuse.com/api/public/jobs"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    out: list[dict[str, Any]] = []
    for j in data.get("results", []):
        locations = j.get("locations") or []
        categories = j.get("categories") or []
        location_text = ", ".join([x.get("name", "") for x in locations if x.get("name")])
        description = j.get("contents") or j.get("description") or ""
        out.append(
            normalize_job(
                {
                    "title": j.get("name"),
                    "company": (j.get("company") or {}).get("name"),
                    "location": location_text,
                    "url": j.get("refs", {}).get("landing_page") or j.get("refs", {}).get("job_detail") or j.get("id"),
                    "description": description,
                    "posted_date": j.get("publication_date"),
                    "job_type": ", ".join([x.get("name", "") for x in categories if x.get("name")]),
                    "remote_type": "unknown",
                },
                source="themuse",
            )
        )
    return out


async def fetch_rss(rss_url: str) -> list[dict[str, Any]]:
    _require_httpx("RSS ingestion")
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(rss_url)
        resp.raise_for_status()
        xml_text = resp.text

    root = ET.fromstring(xml_text)
    items = root.findall(".//item")
    out: list[dict[str, Any]] = []
    for item in items:
        out.append(
            normalize_job(
                {
                    "title": (item.findtext("title") or "").strip(),
                    "company": None,
                    "location": None,
                    "url": (item.findtext("link") or "").strip(),
                    "description": (item.findtext("description") or "").strip(),
                    "posted_date": (item.findtext("pubDate") or "").strip(),
                },
                source="rss",
            )
        )
    return out


async def discover_company_board_sources(site_url: str) -> list[dict[str, str]]:
    _require_httpx("Company site discovery")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(site_url)
        resp.raise_for_status()
        html = resp.text

    text = f"{site_url}\n{html}"
    found: list[dict[str, str]] = []

    greenhouse_tokens = set(re.findall(r"(?:boards|job-boards)\.greenhouse\.io/([a-zA-Z0-9_.-]+)", text, flags=re.I))
    lever_slugs = set(re.findall(r"(?:jobs\.lever\.co|api\.lever\.co/v0/postings)/([a-zA-Z0-9_.-]+)", text, flags=re.I))

    for token in sorted(greenhouse_tokens):
        found.append({"source_type": "greenhouse", "token": token})
    for slug in sorted(lever_slugs):
        found.append({"source_type": "lever", "token": slug})

    return found


def _normalize_headers(fieldnames: list[str] | None) -> dict[str, str]:
    if not fieldnames:
        return {}
    normalized: dict[str, str] = {}
    for name in fieldnames:
        cleaned = (name or "").replace("\ufeff", "").strip().lower()
        if cleaned:
            normalized[cleaned] = name
    return normalized


def parse_csv_content(csv_content: str) -> list[dict[str, Any]]:
    if not csv_content or not csv_content.strip():
        return []

    prepared = csv_content.lstrip("\ufeff")
    sample = prepared[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel

    reader = csv.DictReader(io.StringIO(prepared), dialect=dialect)
    header_map = _normalize_headers(reader.fieldnames)
    if not header_map:
        return []

    aliases = {
        "title": ["title", "job_title", "role"],
        "company": ["company", "company_name", "employer"],
        "location_text": ["location_text", "location", "job_location"],
        "city": ["city"],
        "state": ["state", "province"],
        "remote_type": ["remote_type", "remote", "work_type"],
        "pay_min": ["pay_min", "salary_min", "min_salary"],
        "pay_max": ["pay_max", "salary_max", "max_salary"],
        "pay_text": ["pay_text", "salary", "compensation"],
        "job_type": ["job_type", "employment_type"],
        "seniority": ["seniority", "level"],
        "posted_date": ["posted_date", "created_at", "date_posted"],
        "url": ["url", "job_url", "link"],
        "description": ["description", "job_description", "content"],
    }

    def pick(row: dict[str, Any], logical_key: str) -> Any:
        for alias in aliases[logical_key]:
            source_name = header_map.get(alias)
            if source_name and row.get(source_name) not in (None, ""):
                return row.get(source_name)
        return None

    jobs: list[dict[str, Any]] = []
    for row in reader:
        if not row:
            continue
        mapped = {key: pick(row, key) for key in aliases}
        if not any((mapped.get(k) or "").strip() for k in ("title", "company", "url", "description")):
            continue
        jobs.append(normalize_job(mapped, source="csv"))

    return jobs


def to_csv(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    output = io.StringIO()
    fieldnames = sorted(rows[0].keys())
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
