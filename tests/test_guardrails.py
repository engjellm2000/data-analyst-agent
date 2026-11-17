import pytest
import duckdb

from agent.guardrails import GuardrailError, InvestigationBudget, validate_select_sql
from agent.tools.sql import compare_periods


def test_sql_validator_allows_select_and_rejects_mutation():
    assert validate_select_sql("SELECT * FROM orders") == "SELECT * FROM orders"
    for query in ("DELETE FROM orders", "SELECT 1; DROP TABLE orders", "SELECT 1 -- comment"):
        with pytest.raises(GuardrailError):
            validate_select_sql(query)


def test_budget_stops_extra_queries():
    budget = InvestigationBudget(max_queries=1)
    budget.record("query")
    with pytest.raises(GuardrailError):
        budget.record("query")


def test_period_comparison_scans_only_the_requested_date_range():
    connection = duckdb.connect(":memory:")
    connection.execute(
        "CREATE TABLE orders (order_date DATE, category VARCHAR, net_revenue DOUBLE, returned BOOLEAN)"
    )
    connection.execute(
        """
        INSERT INTO orders VALUES
          ('2025-01-01', 'historical-only', 999, false),
          ('2026-01-01', 'current', 100, false),
          ('2025-12-31', 'current', 80, false)
        """
    )

    result = compare_periods(
        connection, "category", "2026-01-01", "2026-01-01", "2025-12-31", "2025-12-31", InvestigationBudget()
    )

    assert "error" not in result
    assert result["rows"] == [["current", 100.0, 80.0, 1, 0.0, 0.0]]
    connection.close()
