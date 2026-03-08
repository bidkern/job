from __future__ import annotations

from app.services.role_family import get_role_family_config


# Config-driven weights to support future UI tuning.
BASE_DECISION_WEIGHTS: dict[str, float] = {
    "resume_fit": 0.60,
    "requirement_match": 0.23,
    "compensation_logistics": 0.12,
    "preference": 0.05,
}


def resolve_decision_weights(role_family_key: str | None) -> dict[str, float]:
    cfg = get_role_family_config(role_family_key)
    merged = dict(BASE_DECISION_WEIGHTS)
    for k, delta in (cfg.weight_adjustments or {}).items():
        if k not in merged:
            continue
        merged[k] = max(0.0, merged[k] + float(delta))

    total = sum(merged.values()) or 1.0
    return {k: round(v / total, 6) for k, v in merged.items()}

