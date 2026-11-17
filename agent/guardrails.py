"""Budgets and safety checks used by every investigation tool."""
from __future__ import annotations

from dataclasses import dataclass, field
import re


class GuardrailError(ValueError):
    pass


@dataclass
class InvestigationBudget:
    max_steps: int = 12
    max_queries: int = 8
    max_rows: int = 200
    max_seconds: float = 8.0
    estimated_cost_cap_usd: float = 0.15
    steps: int = 0
    queries: int = 0
    estimated_cost_usd: float = 0.0
    events: list[dict] = field(default_factory=list)

    def record(self, kind: str, *, cost: float = 0.0, **details: object) -> None:
        self.steps += 1
        if kind == "query":
            self.queries += 1
        self.estimated_cost_usd += cost
        if self.steps > self.max_steps:
            raise GuardrailError("Investigation step budget exceeded")
        if self.queries > self.max_queries:
            raise GuardrailError("Investigation query budget exceeded")
        if self.estimated_cost_usd > self.estimated_cost_cap_usd:
            raise GuardrailError("Investigation cost budget exceeded")
        self.events.append({"kind": kind, "cost_usd": round(cost, 5), **details})


def validate_select_sql(sql: str) -> str:
    """Allow a single read-only SELECT/CTE query; reject comments and mutation."""
    normalized = sql.strip()
    if not normalized:
        raise GuardrailError("SQL cannot be empty")
    if ";" in normalized.rstrip(";") or "--" in normalized or "/*" in normalized:
        raise GuardrailError("Multiple statements and SQL comments are not allowed")
    first = re.match(r"^\s*([a-zA-Z]+)", normalized)
    if not first or first.group(1).upper() not in {"SELECT", "WITH"}:
        raise GuardrailError("Only SELECT queries are allowed")
    forbidden = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|COPY|ATTACH|DETACH|INSTALL|LOAD|CALL|PRAGMA|EXPORT|IMPORT|VACUUM)\b", re.I)
    if forbidden.search(normalized):
        raise GuardrailError("Query contains a prohibited SQL operation")
    return normalized.rstrip(";")
