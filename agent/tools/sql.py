from __future__ import annotations

from contextlib import nullcontext
import time
from pathlib import Path
from typing import Any

import duckdb

from app.db import connect
from agent.guardrails import InvestigationBudget, GuardrailError, validate_select_sql


def run_sql(database: str | Path | duckdb.DuckDBPyConnection, sql: str, budget: InvestigationBudget) -> dict[str, Any]:
    query = validate_select_sql(sql)
    started = time.perf_counter()
    try:
        connection_scope = nullcontext(database) if hasattr(database, "execute") else connect(database, read_only=True)
        with connection_scope as connection:
            cursor = connection.execute(f"SELECT * FROM ({query}) AS safe_query LIMIT {budget.max_rows + 1}")
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchall()
        truncated = len(rows) > budget.max_rows
        rows = rows[: budget.max_rows]
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        if elapsed_ms > budget.max_seconds * 1000:
            raise GuardrailError("Query timeout budget exceeded")
        payload = {"sql": query, "columns": columns, "rows": [list(row) for row in rows], "truncated": truncated, "latency_ms": elapsed_ms}
        budget.record("query", latency_ms=elapsed_ms, rows=len(rows), sql=query)
        return payload
    except Exception as error:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        budget.record("query", latency_ms=elapsed_ms, error=str(error))
        return {"sql": query, "columns": [], "rows": [], "truncated": False, "latency_ms": elapsed_ms, "error": str(error)}


def compare_periods(database: str | Path | duckdb.DuckDBPyConnection, dimension: str, current_start: str, current_end: str, previous_start: str, previous_end: str, budget: InvestigationBudget) -> dict[str, Any]:
    allowed = {"category", "channel", "region", "warehouse", "device"}
    if dimension not in allowed:
        raise GuardrailError(f"Unsupported comparison dimension: {dimension}")
    sql = f"""
      SELECT {dimension} AS segment,
        ROUND(SUM(net_revenue) FILTER (WHERE order_date BETWEEN DATE '{current_start}' AND DATE '{current_end}'), 2) AS current_revenue,
        ROUND(SUM(net_revenue) FILTER (WHERE order_date BETWEEN DATE '{previous_start}' AND DATE '{previous_end}'), 2) AS previous_revenue,
        COUNT(*) FILTER (WHERE order_date BETWEEN DATE '{current_start}' AND DATE '{current_end}') AS current_orders,
        AVG(CAST(returned AS DOUBLE)) FILTER (WHERE order_date BETWEEN DATE '{current_start}' AND DATE '{current_end}') AS current_return_rate,
        AVG(CAST(returned AS DOUBLE)) FILTER (WHERE order_date BETWEEN DATE '{previous_start}' AND DATE '{previous_end}') AS previous_return_rate
      FROM orders
      WHERE order_date BETWEEN DATE '{previous_start}' AND DATE '{current_end}'
      GROUP BY {dimension}
      ORDER BY current_revenue - previous_revenue ASC
    """
    return run_sql(database, sql, budget)
