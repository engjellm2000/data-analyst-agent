"""Recommendation sizing uses explicit arithmetic rather than model-generated numbers."""
from __future__ import annotations


def recommend(finding: dict, metrics: dict) -> dict:
    current, previous = metrics["current"], metrics["previous"]
    if finding["id"] == "returns":
        excess = max(0, current["return_rate"] - previous["return_rate"]) * current["orders"]
        impact = excess * current["aov"]
        action = "Audit the delayed category with fulfillment; sample recent return reasons before changing policy."
    elif finding["id"] in {"revenue", "basket-value"}:
        impact = max(0, previous["revenue"] - current["revenue"])
        action = "Review the measured segment mix and validate promotion or pricing changes in the source system before changing spend or pricing."
    else:
        impact, action = 0, "Continue monitoring; no action is supported by the available evidence."
    confidence = "medium" if finding["id"] != "steady" else "low"
    return {"action": action, "estimated_impact_usd": round(impact, 2), "assumption": "Impact is an observed-period estimate, not a causal forecast.", "confidence": confidence}
