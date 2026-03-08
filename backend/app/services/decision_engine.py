from __future__ import annotations

import re
from datetime import datetime, timezone

from app.services.constants import SOURCE_TRUST
from app.services.ranking_config import resolve_decision_weights
from app.services.role_family import get_role_family_config


REQUIRED_PHRASE_RE = re.compile(
    r"\b(?:required|must have|minimum|need to have)\b[^.\n;]{0,140}",
    re.IGNORECASE,
)
DEGREE_REQUIRED_RE = re.compile(r"\b(?:bachelor|master|phd|degree)\b[^.\n;]{0,30}\b(?:required|must)\b", re.IGNORECASE)
YEARS_REQUIRED_RE = re.compile(r"\b(\d{1,2})\+?\s*(?:years?|yrs?)\b", re.IGNORECASE)
SUSPICIOUS_TEXT_RE = re.compile(r"\b(?:urgent hire|wire transfer|crypto payment|upfront fee|commission only|1099 only)\b", re.IGNORECASE)
LOW_SIGNAL_TITLE_RE = re.compile(r"\b(?:rockstar|ninja|guru|wizard)\b", re.IGNORECASE)
HIGH_FRICTION_RE = re.compile(r"\b(?:cover letter|required assessment|take-home|portfolio required|multi-step)\b", re.IGNORECASE)
LOW_FRICTION_RE = re.compile(r"\b(?:easy apply|quick apply|one click|short application)\b", re.IGNORECASE)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _extract_required_snippets(description: str | None) -> list[str]:
    text = (description or "").strip()
    if not text:
        return []
    snippets = [re.sub(r"\s+", " ", m.group(0)).strip() for m in REQUIRED_PHRASE_RE.finditer(text)]
    return sorted(set(snippets))[:8]


def _quality_risk(
    title: str | None,
    description: str | None,
    posted_date: datetime | None,
    pay_min: float | None,
    pay_max: float | None,
    source: str | None,
) -> float:
    text = (description or "").lower()
    risk = 0.16
    if len(text) < 320:
        risk += 0.12
    if (pay_min or pay_max) is None:
        risk += 0.08
    if LOW_SIGNAL_TITLE_RE.search(title or ""):
        risk += 0.10
    if SUSPICIOUS_TEXT_RE.search(text):
        risk += 0.25
    if posted_date:
        now = datetime.now(timezone.utc)
        dt = posted_date if posted_date.tzinfo else posted_date.replace(tzinfo=timezone.utc)
        age_days = max(0, (now - dt).days)
        if age_days > 45:
            risk += 0.16
        elif age_days > 21:
            risk += 0.08
    trust = SOURCE_TRUST.get((source or "").lower(), 0.6)
    risk -= (trust - 0.6) * 0.18
    return _clamp01(risk)


def _application_friction(description: str | None, url: str | None, source: str | None) -> float:
    text = (description or "").lower()
    friction = 0.48
    if HIGH_FRICTION_RE.search(text):
        friction += 0.24
    if LOW_FRICTION_RE.search(text):
        friction -= 0.2
    if url and any(host in url.lower() for host in ["greenhouse.io", "lever.co"]):
        friction -= 0.04
    if (source or "").lower() in {"greenhouse", "lever"}:
        friction -= 0.04
    return _clamp01(friction)


def _salary_upside(pay_min: float | None, pay_max: float | None) -> float:
    anchor = float(pay_max or pay_min or 0)
    if anchor <= 0:
        return 0.42
    if anchor >= 160000:
        return 1.0
    if anchor >= 120000:
        return 0.9
    if anchor >= 90000:
        return 0.78
    if anchor >= 70000:
        return 0.66
    if anchor >= 50000:
        return 0.52
    return 0.38


def _work_style_fit(remote_type: str | None, distance_score: float) -> float:
    mode = (remote_type or "unknown").lower().strip()
    if mode == "remote":
        return 0.74
    if mode == "hybrid":
        return 0.84 if distance_score >= 0.65 else 0.62
    if mode == "onsite":
        return 0.9 if distance_score >= 0.72 else 0.55
    return 0.62 if distance_score >= 0.65 else 0.48


def _growth_fit(role_family_confidence: float, seniority_signal: str, resume_strength: float) -> float:
    growth = 0.45 + (0.3 * _clamp01(role_family_confidence)) + (0.25 * _clamp01(resume_strength))
    if seniority_signal == "entry":
        growth += 0.08
    elif seniority_signal == "senior":
        growth -= 0.1
    return _clamp01(growth)


def _response_probability(
    interview_core: float,
    quality_risk: float,
    friction: float,
    freshness_score: float,
    source_score: float,
) -> float:
    probability = (
        0.55 * _clamp01(interview_core)
        + 0.18 * _clamp01(freshness_score)
        + 0.15 * _clamp01(source_score)
        + 0.12 * (1.0 - _clamp01(friction))
    )
    probability *= 1.0 - (0.5 * _clamp01(quality_risk))
    return _clamp01(probability)


def _hard_match(
    distance_score: float,
    work_style_fit: float,
    skill_direct_ratio: float,
    degree_required: bool,
    required_years: int,
    seniority_signal: str,
) -> float:
    score = (
        0.30 * _clamp01(distance_score)
        + 0.22 * _clamp01(work_style_fit)
        + 0.28 * _clamp01(skill_direct_ratio)
        + 0.20 * (0.65 if required_years >= 5 and seniority_signal != "senior" else 0.88)
    )
    if degree_required:
        score -= 0.14
    return _clamp01(score)


def _soft_match(role_score: float, transferable_ratio: float, resume_strength: float) -> float:
    return _clamp01((0.42 * role_score) + (0.35 * transferable_ratio) + (0.23 * resume_strength))


def _resume_gap_severity(hard_match: float, soft_match: float, required_snippets: list[str], missing_items: list[str]) -> float:
    severity = 1.0 - ((0.64 * hard_match) + (0.36 * soft_match))
    if required_snippets and not missing_items:
        severity -= 0.05
    if missing_items:
        severity += min(0.2, 0.06 * len(missing_items))
    return _clamp01(severity)


def _confidence_score(description: str | None, posted_date: datetime | None, pay_min: float | None, pay_max: float | None, job_skills: list[str]) -> float:
    confidence = 0.45
    if description and len(description) >= 500:
        confidence += 0.18
    if posted_date:
        confidence += 0.1
    if (pay_min or pay_max) is not None:
        confidence += 0.1
    if len(job_skills or []) >= 4:
        confidence += 0.12
    return _clamp01(confidence)


def _strategy_tag(final_score: float, response_probability: float, friction: float, gap_severity: float, quality_risk: float) -> str:
    if quality_risk >= 0.78:
        return "Skip"
    if final_score >= 80 and response_probability >= 0.62 and friction <= 0.42 and gap_severity <= 0.45:
        return "Apply now"
    if final_score >= 70 and gap_severity <= 0.58:
        return "Tailor lightly"
    if gap_severity >= 0.7:
        return "Tailor heavily"
    if friction >= 0.72 and response_probability >= 0.52:
        return "Reach out first"
    if final_score >= 56:
        return "Save for later"
    return "Skip"


def build_decision_metrics(
    *,
    title: str | None,
    description: str | None,
    role_family_key: str,
    role_family_confidence: float,
    compatibility_core: float,
    interview_core: float,
    role_score: float,
    skill_direct_ratio: float,
    skill_transferable_ratio: float,
    resume_strength: float,
    distance_score: float,
    salary_score: float,
    freshness_score: float,
    source_score: float,
    hobby_score: float,
    pay_min: float | None,
    pay_max: float | None,
    posted_date: datetime | None,
    source: str | None,
    remote_type: str | None,
    seniority_signal: str,
    job_skills: list[str],
    matched_skills: list[str],
    missing_skills: list[str],
) -> dict[str, object]:
    required_snippets = _extract_required_snippets(description)
    degree_required = DEGREE_REQUIRED_RE.search(description or "") is not None
    years_match = YEARS_REQUIRED_RE.search(description or "")
    required_years = int(years_match.group(1)) if years_match else 0

    work_style_fit = _work_style_fit(remote_type, distance_score)
    growth_fit = _growth_fit(role_family_confidence, seniority_signal, resume_strength)
    hard_match = _hard_match(
        distance_score=distance_score,
        work_style_fit=work_style_fit,
        skill_direct_ratio=skill_direct_ratio,
        degree_required=degree_required,
        required_years=required_years,
        seniority_signal=seniority_signal,
    )
    soft_match = _soft_match(role_score, skill_transferable_ratio, resume_strength)

    quality_risk = _quality_risk(
        title=title,
        description=description,
        posted_date=posted_date,
        pay_min=pay_min,
        pay_max=pay_max,
        source=source,
    )
    friction = _application_friction(description, source=source, url=None)
    response_probability = _response_probability(
        interview_core=interview_core,
        quality_risk=quality_risk,
        friction=friction,
        freshness_score=freshness_score,
        source_score=source_score,
    )
    salary_likelihood = _clamp01((0.62 * _salary_upside(pay_min, pay_max)) + (0.38 * salary_score))
    resume_gap_severity = _resume_gap_severity(hard_match, soft_match, required_snippets, missing_skills)
    confidence = _confidence_score(description, posted_date, pay_min, pay_max, job_skills)

    weights = resolve_decision_weights(role_family_key)
    requirement_match = _clamp01((0.68 * hard_match) + (0.32 * soft_match))
    resume_fit = _clamp01((0.56 * compatibility_core) + (0.44 * resume_strength))
    compensation_logistics = _clamp01((0.45 * salary_likelihood) + (0.35 * work_style_fit) + (0.20 * growth_fit))
    preference = _clamp01(hobby_score)
    final_weighted = 100 * (
        (weights["resume_fit"] * resume_fit)
        + (weights["requirement_match"] * requirement_match)
        + (weights["compensation_logistics"] * compensation_logistics)
        + (weights["preference"] * preference)
    )
    final_weighted = max(0.0, min(100.0, final_weighted))

    compensation_upside = _salary_upside(pay_min, pay_max)
    desirability = _clamp01(
        (0.38 * (final_weighted / 100.0))
        + (0.28 * response_probability)
        + (0.14 * growth_fit)
        + (0.1 * (1.0 - quality_risk))
        + (0.1 * work_style_fit)
    )
    effort = 0.55 + (0.95 * friction)
    expected_value = 100 * ((response_probability * desirability * compensation_upside) / max(0.45, effort))
    expected_value = max(0.0, min(100.0, expected_value))

    strategy = _strategy_tag(
        final_score=final_weighted,
        response_probability=response_probability,
        friction=friction,
        gap_severity=resume_gap_severity,
        quality_risk=quality_risk,
    )

    role_cfg = get_role_family_config(role_family_key)
    top_matched = sorted(set(matched_skills))[:3]
    top_missing = sorted(set(missing_skills))[:3]

    if strategy == "Apply now":
        reason_summary = "High expected value with strong fit and manageable application effort."
    elif strategy == "Tailor heavily":
        reason_summary = "High upside exists, but key requirement gaps should be addressed before applying."
    elif strategy == "Reach out first":
        reason_summary = "Good fit but application friction is high; a warm intro may increase odds."
    elif strategy == "Skip":
        reason_summary = "Low expected value due fit/risk mismatch relative to better alternatives."
    else:
        reason_summary = "Moderate fit; keep in pipeline while prioritizing stronger opportunities."

    return {
        "role_family_key": role_cfg.key,
        "role_family_label": role_cfg.label,
        "recommended_resume_variant": role_cfg.recommended_resume_variant,
        "recommended_apply_strategy": role_cfg.recommended_apply_strategy,
        "weights_used": weights,
        "hard_match": _clamp01(hard_match),
        "soft_match": _clamp01(soft_match),
        "salary_likelihood": _clamp01(salary_likelihood),
        "application_friction": _clamp01(friction),
        "response_probability": _clamp01(response_probability),
        "realness_risk": _clamp01(quality_risk),
        "career_growth_fit": _clamp01(growth_fit),
        "work_style_fit": _clamp01(work_style_fit),
        "resume_gap_severity": _clamp01(resume_gap_severity),
        "confidence": _clamp01(confidence),
        "expected_value_score": round(expected_value, 2),
        "final_weighted_score": round(final_weighted, 2),
        "strategy_tag": strategy,
        "reason_summary": reason_summary,
        "top_matched_qualifications": top_matched,
        "top_missing_qualifications": top_missing,
        "required_snippets": required_snippets[:4],
        "degree_required_detected": degree_required,
        "required_years_detected": required_years,
    }

