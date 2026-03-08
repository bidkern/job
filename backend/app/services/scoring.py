from datetime import datetime, timezone
import re

from app.services.constants import (
    DEFAULT_WEIGHTS,
    ENTRY_LEVEL_TITLE_TERMS,
    HOBBY_JOB_SIGNALS,
    RECOMMENDATION_BLEND,
    ROLE_SYNONYMS,
    SCORE_TUNING_MODES,
    SENIOR_TITLE_TERMS,
    SOURCE_TRUST,
    TRANSFERABLE_SKILL_GROUPS,
)
from app.services.decision_engine import build_decision_metrics
from app.services.role_family import classify_role_family

GENERIC_ROLE_HINTS = [
    "analyst",
    "specialist",
    "associate",
    "assistant",
    "crew",
    "cashier",
    "cook",
    "line cook",
    "server",
    "barista",
    "clerk",
    "laborer",
    "assembler",
    "packer",
    "stocker",
    "dishwasher",
    "driver",
    "coordinator",
    "representative",
    "technician",
    "operator",
    "worker",
    "manager",
    "engineer",
    "developer",
    "consultant",
]

ENTRY_ACCESSIBLE_HINTS = [
    "crew member",
    "team member",
    "cashier",
    "line cook",
    "cook",
    "food service",
    "fast food",
    "restaurant",
    "retail associate",
    "sales associate",
    "customer service representative",
    "warehouse associate",
    "warehouse worker",
    "material handler",
    "assembler",
    "production worker",
    "picker",
    "packer",
    "stocker",
    "delivery driver",
    "general labor",
]

REQUIREMENT_NOISE_PATTERNS = [
    re.compile(
        r"\b(?:bachelor'?s|master'?s|phd|doctoral|associate(?:'s)?\s+degree|degree)\b[^.\n;]{0,120}",
        re.I,
    ),
    re.compile(
        r"\b\d{1,2}\+?\s*(?:-|to)?\s*\d{0,2}\+?\s*years?\b[^.\n;]{0,120}",
        re.I,
    ),
]


def _norm_ratio(hit: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return min(1.0, hit / total)


def _normalize_phrase(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _contains_phrase(haystack: str, phrase: str) -> bool:
    normalized_phrase = _normalize_phrase(phrase)
    if not normalized_phrase:
        return False
    pattern = r"\b" + re.escape(normalized_phrase).replace(r"\ ", r"\s+") + r"\b"
    return re.search(pattern, haystack) is not None


def _match_count(haystack: str, terms: list[str]) -> int:
    return sum(1 for term in terms if _contains_phrase(haystack, term))


def _strip_requirement_noise(value: str | None) -> tuple[str, int]:
    text = value or ""
    hit_count = 0
    for pattern in REQUIREMENT_NOISE_PATTERNS:
        text, matches = pattern.subn(" ", text)
        hit_count += matches
    return text, hit_count


def _resume_strength_score(profile_skills: list[str]) -> float:
    profile_set = _normalize_skill_set(profile_skills)
    if not profile_set:
        return 0.35

    transferable_groups = 0
    for terms in TRANSFERABLE_SKILL_GROUPS.values():
        if any(_skill_in_term(skill, _normalize_phrase(term)) for skill in profile_set for term in terms):
            transferable_groups += 1

    breadth_ratio = min(1.0, len(profile_set) / 20.0)
    group_ratio = min(1.0, transferable_groups / 5.0)
    core_terms = {
        "communication",
        "customer service",
        "inventory",
        "sales",
        "operations",
        "excel",
        "python",
        "sql",
        "leadership",
        "problem solving",
    }
    core_ratio = min(1.0, sum(1 for t in core_terms if t in profile_set) / 5.0)
    score = 0.5 + 0.3 * breadth_ratio + 0.1 * group_ratio + 0.1 * core_ratio
    return max(0.0, min(1.0, score))


def normalize_score_tuning_mode(score_tuning_mode: str | None) -> str:
    mode = (score_tuning_mode or "balanced").strip().lower()
    if mode not in SCORE_TUNING_MODES:
        return "balanced"
    return mode


def role_match_score(title: str, description: str | None) -> tuple[float, list[str]]:
    clean_description, _ = _strip_requirement_noise(description)
    haystack = _normalize_phrase(f"{title or ''} {clean_description or ''}")
    best = 0.0
    matched_groups: list[str] = []
    for role, terms in ROLE_SYNONYMS.items():
        normalized_terms: list[str] = []
        for raw in terms:
            term = _normalize_phrase(raw)
            compact_len = len(re.sub(r"[^a-z0-9]+", "", term))
            if compact_len < 3:
                continue
            normalized_terms.append(term)
        hits = _match_count(haystack, normalized_terms)
        ratio = _norm_ratio(hits, max(1, len(normalized_terms) // 2))
        if hits > 0:
            matched_groups.append(role)
        best = max(best, ratio)

    if best <= 0:
        # Broader fallback so non-preloaded role families still rank fairly.
        generic_hits = _match_count(haystack, GENERIC_ROLE_HINTS)
        if generic_hits >= 2:
            return 0.7, []
        if generic_hits == 1:
            return 0.62, []
        return 0.52, []

    return best, sorted(set(matched_groups))


def _normalize_skill_set(skills: list[str]) -> set[str]:
    normalized = {_normalize_phrase(s) for s in skills if s and _normalize_phrase(s)}
    return normalized


def _skill_in_term(skill: str, term: str) -> bool:
    return skill == term or skill in term or term in skill


def _group_match_from_signals(group_terms: list[str], skill_set: set[str], text_haystack: str) -> bool:
    for raw in group_terms:
        term = _normalize_phrase(raw)
        if not term:
            continue
        if any(_skill_in_term(skill, term) for skill in skill_set):
            return True
        if _contains_phrase(text_haystack, term):
            return True
    return False


def _skill_match_details(
    job_skills: list[str],
    profile_skills: list[str],
    title: str | None,
    description: str | None,
) -> dict:
    profile_set = _normalize_skill_set(profile_skills)
    job_set = _normalize_skill_set(job_skills)
    clean_description, _ = _strip_requirement_noise(description)
    text_haystack = _normalize_phrase(f"{title or ''} {clean_description or ''}")

    if not profile_set:
        return {
            "score": 0.0,
            "direct_ratio": 0.0,
            "transferable_ratio": 0.0,
            "direct_hits": 0,
            "transferable_group_hits": 0,
            "matched_transferable_groups": [],
            "signal_sparse": not bool(job_set),
        }

    direct_hit_terms: set[str] = set()
    for skill in profile_set:
        if skill in job_set:
            direct_hit_terms.add(skill)
            continue
        if _contains_phrase(text_haystack, skill):
            direct_hit_terms.add(skill)

    profile_groups: set[str] = set()
    job_groups: set[str] = set()
    for group, terms in TRANSFERABLE_SKILL_GROUPS.items():
        if _group_match_from_signals(terms, profile_set, ""):
            profile_groups.add(group)
        if _group_match_from_signals(terms, job_set, text_haystack):
            job_groups.add(group)

    transferable_groups = sorted(profile_groups.intersection(job_groups))
    transferable_hits = len(transferable_groups)
    direct_hits = len(direct_hit_terms)

    direct_ratio = _norm_ratio(direct_hits, max(3, min(8, len(profile_set))))
    transferable_ratio = _norm_ratio(transferable_hits, max(1, min(4, len(profile_groups) or 1)))

    sparse_signal = not bool(job_set) and len(text_haystack) < 80
    if sparse_signal and direct_hits == 0 and transferable_hits == 0:
        score = 0.58
    else:
        score = 0.72 * direct_ratio + 0.28 * transferable_ratio
        if direct_hits > 0:
            score = min(1.0, score + 0.08)
        elif transferable_hits > 0:
            score = max(score, min(1.0, 0.52 + transferable_ratio * 0.38))
        else:
            score = max(score, 0.42)

    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "direct_ratio": round(direct_ratio, 4),
        "transferable_ratio": round(transferable_ratio, 4),
        "direct_hits": direct_hits,
        "transferable_group_hits": transferable_hits,
        "matched_transferable_groups": transferable_groups,
        "signal_sparse": sparse_signal,
    }


def _hobby_match_details(title: str | None, description: str | None, profile_hobbies: list[str] | None) -> dict:
    normalized_hobbies = [_normalize_phrase(h) for h in (profile_hobbies or []) if _normalize_phrase(h)]
    if not normalized_hobbies:
        return {
            "score": 0.0,
            "matched_hobbies": [],
            "matched_hobby_count": 0,
            "hobby_count": 0,
            "active": False,
        }

    text_haystack = _normalize_phrase(f"{title or ''} {description or ''}")
    matched: list[str] = []
    for hobby in normalized_hobbies:
        terms = HOBBY_JOB_SIGNALS.get(hobby, [])
        if hobby and hobby not in terms:
            terms = [*terms, hobby]
        found = any(_contains_phrase(text_haystack, term) for term in terms if term)
        if found:
            matched.append(hobby)

    match_ratio = _norm_ratio(len(matched), max(1, len(normalized_hobbies)))
    # Neutral floor keeps hobby preference influential without zeroing strong resume matches.
    score = min(1.0, 0.4 + (0.6 * match_ratio))
    return {
        "score": round(score, 4),
        "matched_hobbies": sorted(set(matched)),
        "matched_hobby_count": len(set(matched)),
        "hobby_count": len(set(normalized_hobbies)),
        "active": True,
    }


def skill_match_score(
    job_skills: list[str],
    profile_skills: list[str],
    title: str | None = None,
    description: str | None = None,
) -> float:
    details = _skill_match_details(job_skills, profile_skills, title, description)
    return details["score"]


def distance_score(distance_miles: float | None, remote_type: str) -> float:
    # Local-first behavior: unknown locations rank lower than known nearby jobs.
    if remote_type == "remote":
        return 0.65
    if remote_type == "unknown":
        return 0.35 if distance_miles is None else 0.7
    if distance_miles is None:
        return 0.4
    if distance_miles <= 10:
        return 1.0
    if distance_miles <= 20:
        return 0.9
    if distance_miles <= 35:
        return 0.8
    if distance_miles <= 50:
        return 0.45
    return 0.15


def salary_score(pay_min: float | None, pay_max: float | None) -> float:
    if pay_min is None and pay_max is None:
        return 0.7
    anchor = pay_max or pay_min or 0
    if anchor >= 120000:
        return 1.0
    if anchor >= 90000:
        return 0.8
    if anchor >= 70000:
        return 0.65
    if anchor >= 50000:
        return 0.5
    return 0.35


def freshness_score(posted_date: datetime | None) -> float:
    if not posted_date:
        return 0.5
    now = datetime.now(timezone.utc)
    if posted_date.tzinfo is None:
        posted_date = posted_date.replace(tzinfo=timezone.utc)
    age_days = (now - posted_date).days
    if age_days <= 3:
        return 1.0
    if age_days <= 7:
        return 0.85
    if age_days <= 14:
        return 0.7
    if age_days <= 30:
        return 0.5
    return 0.3


def source_score(source: str) -> float:
    return SOURCE_TRUST.get((source or "").lower(), 0.6)


def _seniority_multiplier(
    title: str | None,
    description: str | None,
    entry_boost_cap: float,
    senior_penalty_cap: float,
) -> tuple[float, str]:
    clean_description, _ = _strip_requirement_noise(description)
    title_haystack = _normalize_phrase(title or "")
    desc_haystack = _normalize_phrase(clean_description or "")
    senior_hits = (_match_count(title_haystack, SENIOR_TITLE_TERMS) * 2) + min(1, _match_count(desc_haystack, SENIOR_TITLE_TERMS))
    entry_hits = (_match_count(title_haystack, ENTRY_LEVEL_TITLE_TERMS) * 2) + min(1, _match_count(desc_haystack, ENTRY_LEVEL_TITLE_TERMS))

    if senior_hits > entry_hits:
        # Keep seniority penalty mild: title seniority is informative, not disqualifying.
        penalty = min(max(0.0, senior_penalty_cap), 0.03 * senior_hits)
        return max(0.86, 1.0 - penalty), "senior"
    if entry_hits > senior_hits:
        boost = min(max(0.0, entry_boost_cap), 0.04 * entry_hits)
        return min(1.25, 1.0 + boost), "entry"
    return 1.0, "neutral"


def _entry_accessibility_boost(
    title: str | None,
    description: str | None,
    skill_details: dict,
) -> float:
    clean_description, _ = _strip_requirement_noise(description)
    text = _normalize_phrase(f"{title or ''} {clean_description or ''}")
    entry_hits = _match_count(text, ENTRY_LEVEL_TITLE_TERMS)
    accessible_hits = _match_count(text, ENTRY_ACCESSIBLE_HINTS)
    transferable_hits = int(skill_details.get("transferable_group_hits", 0) or 0)
    direct_hits = int(skill_details.get("direct_hits", 0) or 0)

    boost = 0.0
    if accessible_hits > 0:
        boost += min(0.12, 0.05 + accessible_hits * 0.025)
    if entry_hits > 0:
        boost += min(0.08, 0.03 + entry_hits * 0.02)
    if transferable_hits > 0:
        boost += min(0.06, 0.02 + transferable_hits * 0.02)
    if direct_hits > 0:
        boost += min(0.04, direct_hits * 0.01)
    return min(0.22, boost)


def score_job(
    title: str,
    description: str | None,
    job_skills: list[str],
    profile_skills: list[str],
    distance_miles: float | None,
    remote_type: str,
    pay_min: float | None,
    pay_max: float | None,
    posted_date: datetime | None,
    source: str,
    weights: dict[str, float] | None = None,
    score_tuning_mode: str = "balanced",
    profile_hobbies: list[str] | None = None,
) -> tuple[float, dict]:
    weights = weights or DEFAULT_WEIGHTS
    tuning_mode = normalize_score_tuning_mode(score_tuning_mode)
    tuning = SCORE_TUNING_MODES[tuning_mode]
    _, ignored_requirement_phrases = _strip_requirement_noise(description)
    role_value, matched_roles = role_match_score(title, description)
    resume_signal_available = bool(profile_skills)
    resume_strength = _resume_strength_score(profile_skills)
    skill_details = _skill_match_details(job_skills, profile_skills, title, description)
    hobby_details = _hobby_match_details(title, description, profile_hobbies)
    hobby_active = bool(hobby_details.get("active"))
    hobby_score = float(hobby_details.get("score") or 0)
    accessibility_boost = _entry_accessibility_boost(title, description, skill_details)
    skill_value = skill_details["score"]
    distance_value = distance_score(distance_miles, remote_type)
    salary_value = salary_score(pay_min, pay_max)
    freshness_value = freshness_score(posted_date)
    source_value = source_score(source)

    legacy_total = (
        weights["role"] * role_value
        + weights["skills"] * skill_value
        + weights["distance"] * distance_value
        + weights["salary"] * salary_value
        + weights["freshness"] * freshness_value
        + weights["source"] * source_value
    )
    legacy_score = round(legacy_total * 100, 2)

    if resume_signal_available:
        resume_compatibility_core = (
            0.25 * role_value
            + 0.36 * skill_details["direct_ratio"]
            + 0.24 * skill_details["transferable_ratio"]
            + 0.15 * resume_strength
        )
        compat_floor = 0.53 + (0.12 * resume_strength)
        if skill_details["direct_hits"] > 0 or skill_details["transferable_group_hits"] > 0:
            compat_floor += 0.06
        if accessibility_boost > 0:
            compat_floor += 0.03
        resume_compatibility_core = max(resume_compatibility_core, min(0.9, compat_floor))
    else:
        resume_compatibility_core = max(0.58, (0.5 * role_value) + (0.28 * resume_strength))

    if hobby_active:
        compatibility_core = (
            RECOMMENDATION_BLEND["resume"] * resume_compatibility_core
            + RECOMMENDATION_BLEND["hobbies"] * hobby_score
        )
    else:
        compatibility_core = resume_compatibility_core

    seniority_multiplier, seniority_signal = _seniority_multiplier(
        title,
        description,
        entry_boost_cap=float(tuning.get("entry_boost_cap", 0.12)),
        senior_penalty_cap=float(tuning.get("senior_penalty_cap", 0.30)),
    )
    if resume_signal_available:
        interview_core_base = (
            0.5 * compatibility_core
            + 0.16 * role_value
            + 0.14 * distance_value
            + 0.08 * freshness_value
            + 0.12 * resume_strength
        )
    else:
        interview_core_base = 0.5 * role_value + 0.22 * distance_value + 0.14 * freshness_value + 0.14 * resume_strength
    interview_core = max(
        0.0,
        min(
            1.0,
            interview_core_base * seniority_multiplier + float(tuning.get("interview_bonus", 0.0)) + accessibility_boost,
        ),
    )

    if resume_signal_available:
        interview_floor = 0.6 + (0.13 * resume_strength)
        if skill_details["direct_hits"] > 0 or skill_details["transferable_group_hits"] > 0:
            interview_floor += 0.07
        if distance_value >= 0.8:
            interview_floor += 0.03
        if accessibility_boost > 0:
            interview_floor += 0.05
        interview_core = max(interview_core, min(0.94, interview_floor))

    interview_core = max(0.0, min(1.0, interview_core * float(tuning.get("interview_multiplier", 1.0))))
    compatibility_core = max(0.0, min(1.0, compatibility_core * float(tuning.get("compatibility_multiplier", 1.0))))

    # Linear mapping: 100% -> 10/10, 90% -> 9/10, etc.
    interview_score = round(interview_core * 100, 2)
    potential_match_score = round(compatibility_core * 100, 2)

    profile_set = _normalize_skill_set(profile_skills)
    job_set = _normalize_skill_set(job_skills)
    text_haystack = _normalize_phrase(f"{title or ''} {description or ''}")
    matched_skills = sorted(
        {
            skill
            for skill in profile_set
            if skill in job_set or _contains_phrase(text_haystack, skill)
        }
    )
    missing_skills = sorted([skill for skill in job_set if skill not in profile_set])[:8]
    role_family = classify_role_family(title, description, job_skills)
    decision_metrics = build_decision_metrics(
        title=title,
        description=description,
        role_family_key=str(role_family.get("key") or "general_fallback"),
        role_family_confidence=float(role_family.get("confidence") or 0.0),
        compatibility_core=compatibility_core,
        interview_core=interview_core,
        role_score=role_value,
        skill_direct_ratio=skill_details["direct_ratio"],
        skill_transferable_ratio=skill_details["transferable_ratio"],
        resume_strength=resume_strength,
        distance_score=distance_value,
        salary_score=salary_value,
        freshness_score=freshness_value,
        source_score=source_value,
        hobby_score=hobby_score,
        pay_min=pay_min,
        pay_max=pay_max,
        posted_date=posted_date,
        source=source,
        remote_type=remote_type,
        seniority_signal=seniority_signal,
        job_skills=job_skills,
        matched_skills=matched_skills,
        missing_skills=missing_skills,
    )
    score = round(float(decision_metrics.get("final_weighted_score") or legacy_score), 2)
    expected_value_score = round(float(decision_metrics.get("expected_value_score") or 0.0), 2)
    confidence_raw = float(decision_metrics.get("confidence") or 0.0)

    if role_value >= 0.75:
        role_reason = "Strong role alignment"
    elif role_value >= 0.45:
        role_reason = "Moderate role alignment"
    else:
        role_reason = "Limited role-alignment signals"

    if skill_details["direct_hits"] >= 2:
        skill_reason = "Strong direct resume-to-job skill overlap"
    elif skill_details["transferable_group_hits"] >= 2:
        skill_reason = "Good transferable-skill alignment"
    elif skill_details["direct_hits"] == 0 and skill_details["transferable_group_hits"] == 0:
        skill_reason = "Limited explicit skill overlap"
    else:
        skill_reason = "Partial direct/transferable skill overlap"

    if seniority_signal == "senior":
        seniority_reason = "Title appears senior, reducing interview odds"
    elif seniority_signal == "entry":
        seniority_reason = "Entry-level signals increase interview odds"
    else:
        seniority_reason = "Seniority level appears neutral"

    if hobby_active:
        if hobby_details["matched_hobby_count"] >= 2:
            hobby_reason = "Role aligns with multiple hobby preferences"
        elif hobby_details["matched_hobby_count"] == 1:
            hobby_reason = "Role aligns with one hobby preference"
        else:
            hobby_reason = "Limited hobby alignment for this role"
    else:
        hobby_reason = "No hobby preferences set"

    breakdown = {
        "total": score,
        "legacy_total": legacy_score,
        "hire_probability_percent": score,
        "interview_chance_percent": interview_score,
        "potential_match_percent": potential_match_score,
        "expected_value_score": expected_value_score,
        "confidence_score": round(confidence_raw * 100, 2),
        "resume_influence_percent": int(RECOMMENDATION_BLEND["resume"] * 100) if hobby_active else 100,
        "hobbies_influence_percent": int(RECOMMENDATION_BLEND["hobbies"] * 100) if hobby_active else 0,
        "resume_signal_available": resume_signal_available,
        "score_tuning_mode": tuning_mode,
        "weights": weights,
        "role_family": role_family,
        "decision": decision_metrics,
        "components": {
            "role": round(role_value, 4),
            "skills": round(skill_value, 4),
            "skills_direct": round(skill_details["direct_ratio"], 4),
            "skills_transferable": round(skill_details["transferable_ratio"], 4),
            "resume_strength": round(resume_strength, 4),
            "resume_compatibility_core": round(resume_compatibility_core, 4),
            "hobby_alignment": round(hobby_score, 4),
            "entry_accessibility_boost": round(accessibility_boost, 4),
            "distance": round(distance_value, 4),
            "salary": round(salary_value, 4),
            "freshness": round(freshness_value, 4),
            "source": round(source_value, 4),
            "seniority_multiplier": round(seniority_multiplier, 4),
        },
        "hobby_signals": {
            "active": hobby_active,
            "matched_hobby_count": hobby_details["matched_hobby_count"],
            "hobby_count": hobby_details["hobby_count"],
            "matched_hobbies": hobby_details["matched_hobbies"],
        },
        "requirements_ignored_count": ignored_requirement_phrases,
        "skill_signals": {
            "direct_overlap_count": skill_details["direct_hits"],
            "transferable_group_count": skill_details["transferable_group_hits"],
            "transferable_groups": skill_details["matched_transferable_groups"],
            "signal_sparse": skill_details["signal_sparse"],
        },
        "seniority_signal": seniority_signal,
        "matched_role_categories": matched_roles,
        "why_ranked_high": [
            role_reason,
            (
                skill_reason
                if resume_signal_available
                else "Resume signal unavailable; using role/distance fallback"
            ),
            "Local distance fit" if distance_value >= 0.8 else "Distance lowers hiring odds",
            "Compensation signal present" if (pay_min or pay_max) else "Compensation not listed",
            (
                "Degree/years requirements ignored in scoring"
                if ignored_requirement_phrases > 0
                else "Scored by transferable fit over formal requirement text"
            ),
            seniority_reason,
            hobby_reason,
            str(decision_metrics.get("reason_summary") or ""),
        ],
    }
    return score, breakdown
