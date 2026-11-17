"""A provider-neutral tool-calling loop. Planner output can later be supplied by an LLM."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from agent.guardrails import InvestigationBudget, GuardrailError
from agent.planner import generate_hypotheses
from agent.scratchpad import Scratchpad
from agent.tools import compare_periods


def investigate_finding(
    database: str | Path | duckdb.DuckDBPyConnection,
    finding: dict,
    periods: dict,
    budget: InvestigationBudget | None = None,
) -> dict[str, Any]:
    budget = budget or InvestigationBudget()
    pad = Scratchpad()
    pad.add("Detect", "observed", finding["summary"], finding_id=finding["id"])
    for plan in generate_hypotheses(finding):
        if pad.tested(plan["hypothesis"]):
            continue
        try:
            result = compare_periods(database, plan["dimension"], periods["current_start"], periods["current_end"], periods["previous_start"], periods["previous_end"], budget)
            if result.get("error"):
                pad.add("Test hypothesis", "failed", result["error"], **plan)
                continue
            rows = result["rows"]
            material = bool(rows and any(abs(float(row[1] or 0) - float(row[2] or 0)) > 1 for row in rows))
            pad.add("Test hypothesis", "supported" if material else "ruled out", f"Compared {len(rows)} {plan['dimension']} segments.", **plan, query=result["sql"], result_rows=rows[:5], latency_ms=result["latency_ms"])
        except GuardrailError as error:
            pad.add("Guardrail", "stopped", str(error), **plan)
            break
    return {"trace": pad.entries, "budget": {"steps": budget.steps, "queries": budget.queries, "estimated_cost_usd": round(budget.estimated_cost_usd, 4), "max_steps": budget.max_steps, "max_queries": budget.max_queries}}
