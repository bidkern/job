from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RoleFamilyConfig:
    key: str
    label: str
    keywords: tuple[str, ...]
    transferable_signals: tuple[str, ...]
    weight_adjustments: dict[str, float]
    recommended_resume_variant: str
    recommended_apply_strategy: str


ROLE_FAMILY_CONFIGS: dict[str, RoleFamilyConfig] = {
    "data_analyst": RoleFamilyConfig(
        key="data_analyst",
        label="Data Analyst",
        keywords=("data analyst", "analytics analyst", "sql", "dashboard", "tableau", "power bi"),
        transferable_signals=("reporting", "excel", "insights", "kpi", "analysis"),
        weight_adjustments={"resume_fit": 0.04, "requirement_match": 0.02},
        recommended_resume_variant="Data Analyst",
        recommended_apply_strategy="Tailor lightly",
    ),
    "business_analyst": RoleFamilyConfig(
        key="business_analyst",
        label="Business Analyst",
        keywords=("business analyst", "requirements analyst", "process analyst", "systems analyst", "functional analyst"),
        transferable_signals=("stakeholder", "requirements", "documentation", "workflow", "process improvement"),
        weight_adjustments={"resume_fit": 0.03, "requirement_match": 0.03},
        recommended_resume_variant="Business Analyst",
        recommended_apply_strategy="Tailor lightly",
    ),
    "market_research_analyst": RoleFamilyConfig(
        key="market_research_analyst",
        label="Market Research Analyst",
        keywords=("market research", "consumer insights", "research analyst", "survey", "competitive analysis"),
        transferable_signals=("analysis", "reporting", "trends", "data", "customer insights"),
        weight_adjustments={"resume_fit": 0.03, "compensation_logistics": -0.01},
        recommended_resume_variant="Market Research",
        recommended_apply_strategy="Tailor heavily",
    ),
    "operations_analyst": RoleFamilyConfig(
        key="operations_analyst",
        label="Operations Analyst",
        keywords=("operations analyst", "operations coordinator", "process improvement", "supply chain", "logistics analyst"),
        transferable_signals=("inventory", "fulfillment", "scheduling", "quality", "kpi"),
        weight_adjustments={"requirement_match": 0.03, "compensation_logistics": 0.01},
        recommended_resume_variant="Generalist",
        recommended_apply_strategy="Apply now",
    ),
    "ai_workflow_automation": RoleFamilyConfig(
        key="ai_workflow_automation",
        label="AI Workflow / AI Automation",
        keywords=("ai workflow", "ai automation", "prompt engineer", "llm", "langchain", "n8n", "zapier", "make"),
        transferable_signals=("automation", "api", "python", "agent workflow", "integration"),
        weight_adjustments={"resume_fit": 0.05, "requirement_match": 0.02},
        recommended_resume_variant="AI Workflow / Automation",
        recommended_apply_strategy="Tailor heavily",
    ),
    "sales_ops_revops_analyst": RoleFamilyConfig(
        key="sales_ops_revops_analyst",
        label="Sales Ops / RevOps Analyst",
        keywords=("sales operations", "revops", "revenue operations", "sales analyst", "pipeline analytics"),
        transferable_signals=("crm", "salesforce", "forecasting", "dashboard", "quota"),
        weight_adjustments={"resume_fit": 0.03, "compensation_logistics": 0.02},
        recommended_resume_variant="Business Analyst",
        recommended_apply_strategy="Apply now",
    ),
    "product_growth_analyst": RoleFamilyConfig(
        key="product_growth_analyst",
        label="Product / Growth Analyst",
        keywords=("product analyst", "growth analyst", "experimentation", "a/b testing", "product insights"),
        transferable_signals=("analytics", "sql", "funnel", "retention", "experiments"),
        weight_adjustments={"resume_fit": 0.04, "requirement_match": 0.01},
        recommended_resume_variant="Data Analyst",
        recommended_apply_strategy="Tailor lightly",
    ),
    "quant_research_adjacent": RoleFamilyConfig(
        key="quant_research_adjacent",
        label="Quant / Research Adjacent",
        keywords=("quant", "quantitative", "modeling analyst", "research analyst", "statistical analyst"),
        transferable_signals=("statistics", "python", "r", "risk", "forecast"),
        weight_adjustments={"requirement_match": 0.05, "preference": -0.02},
        recommended_resume_variant="Market Research",
        recommended_apply_strategy="Reach out first",
    ),
    "general_fallback": RoleFamilyConfig(
        key="general_fallback",
        label="General fallback",
        keywords=(),
        transferable_signals=("operations", "customer service", "communication", "sales", "analytics"),
        weight_adjustments={},
        recommended_resume_variant="Generalist",
        recommended_apply_strategy="Save for later",
    ),
}


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def classify_role_family(title: str | None, description: str | None, job_skills: list[str] | None = None) -> dict[str, object]:
    text = _normalize_text(f"{title or ''} {description or ''} {' '.join(job_skills or [])}")
    if not text:
        fallback = ROLE_FAMILY_CONFIGS["general_fallback"]
        return {"key": fallback.key, "label": fallback.label, "confidence": 0.2, "matched_keywords": []}

    best_key = "general_fallback"
    best_score = 0.0
    best_hits: list[str] = []
    for key, cfg in ROLE_FAMILY_CONFIGS.items():
        if key == "general_fallback":
            continue
        hits = [kw for kw in cfg.keywords if kw and re.search(rf"\b{re.escape(kw.lower())}\b", text)]
        signal_hits = [sig for sig in cfg.transferable_signals if sig and re.search(rf"\b{re.escape(sig.lower())}\b", text)]
        raw_score = (len(hits) * 1.7) + (len(signal_hits) * 0.8)
        normalized = min(1.0, raw_score / max(2.0, len(cfg.keywords) * 0.9))
        if normalized > best_score:
            best_key = key
            best_score = normalized
            best_hits = [*hits[:4], *signal_hits[:3]]

    cfg = ROLE_FAMILY_CONFIGS[best_key]
    if best_key == "general_fallback":
        return {"key": cfg.key, "label": cfg.label, "confidence": 0.35, "matched_keywords": []}
    return {"key": cfg.key, "label": cfg.label, "confidence": round(best_score, 3), "matched_keywords": sorted(set(best_hits))[:6]}


def get_role_family_config(role_family_key: str | None) -> RoleFamilyConfig:
    key = (role_family_key or "").strip().lower()
    return ROLE_FAMILY_CONFIGS.get(key, ROLE_FAMILY_CONFIGS["general_fallback"])

