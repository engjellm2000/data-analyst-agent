from __future__ import annotations

from typing import Any


def morning_briefing(findings: list[dict[str, Any]], recommendations: dict[str, dict]) -> list[dict[str, Any]]:
    brief = []
    for finding in findings:
        recommendation = recommendations.get(finding["id"], {})
        brief.append({"rank": len(brief) + 1, "issue": finding["title"], "priority": finding["priority"], "explanation": finding["summary"], "recommended_action": recommendation.get("action", finding["recommendation"]), "estimated_impact_usd": recommendation.get("estimated_impact_usd", 0), "confidence": recommendation.get("confidence", "low"), "trace_link": "#trace"})
    return brief
