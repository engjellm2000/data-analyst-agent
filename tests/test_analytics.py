from datetime import date, timedelta

import duckdb

from app.analytics import ALLOWED_WINDOWS, forecast_revenue, investigate
from app.db import connect
from app.seed import initialize_database


def test_synthetic_seed_persists_and_investigation_is_evidence_grounded(tmp_path):
    database = tmp_path / "test.duckdb"
    as_of = date(2026, 10, 31)
    row_count = initialize_database(str(database), end_date=as_of)
    assert row_count > 20_000

    with connect(database) as connection:
        result = investigate(connection, window_days=30, as_of=as_of)
        second_result = investigate(connection, window_days=30, as_of=as_of)

    assert result["current_start"] == "2026-10-02"
    assert result["current_end"] == "2026-10-31"
    assert result["metrics"] == second_result["metrics"]
    assert result["series"] == second_result["series"]
    assert result["forecast"] == second_result["forecast"]
    assert result["findings"] == second_result["findings"]
    assert len(result["series"]) == 30
    assert set(result["revenue_drivers"]) == {"category", "channel"}
    assert len(result["revenue_drivers"]["category"]) == 5
    assert len(result["revenue_drivers"]["channel"]) == 5
    assert result["revenue_drivers"]["category"] == sorted(
        result["revenue_drivers"]["category"], key=lambda driver: driver["change"]
    )
    assert {finding["id"] for finding in result["findings"]} >= {"returns", "basket-value"}
    for finding in result["findings"]:
        assert finding["evidence"]
        assert finding["recommendation"]
        assert "does not establish" in finding["explanation"] or "cannot establish" in finding["explanation"] or finding["id"] == "basket-value"

    with connect(database) as connection:
        persisted_count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert persisted_count == row_count


def test_investigation_rejects_unsupported_windows(tmp_path):
    database = tmp_path / "test.duckdb"
    initialize_database(str(database), end_date=date(2026, 10, 31))
    with connect(database) as connection:
        try:
            investigate(connection, window_days=11, as_of=date(2026, 10, 31))
        except ValueError as error:
            assert "must be one of" in str(error)
        else:
            raise AssertionError("Unsupported window should be rejected")

    assert ALLOWED_WINDOWS == (7, 14, 30, 60, 90)


def test_all_supported_windows_return_adjacent_periods(tmp_path):
    database = tmp_path / "test.duckdb"
    as_of = date(2026, 10, 31)
    initialize_database(str(database), end_date=as_of)

    with connect(database) as connection:
        for window_days in ALLOWED_WINDOWS:
            result = investigate(connection, window_days=window_days, as_of=as_of)
            assert result["current_end"] == as_of.isoformat()
            assert result["previous_end"] < result["current_start"]
            assert result["current_start"] == (
                as_of - timedelta(days=window_days - 1)
            ).isoformat()
            assert result["metrics"]["current"]["orders"] > 0
            assert result["metrics"]["previous"]["orders"] > 0


def test_default_investigation_uses_latest_available_order_date(tmp_path):
    database = tmp_path / "test.duckdb"
    as_of = date(2026, 10, 31)
    initialize_database(str(database), end_date=as_of)

    with connect(database) as connection:
        result = investigate(connection, window_days=30)

    assert result["current_end"] == as_of.isoformat()


def test_forecast_returns_a_caveated_two_week_planning_range(tmp_path):
    database = tmp_path / "test.duckdb"
    as_of = date(2026, 10, 31)
    initialize_database(str(database), end_date=as_of)

    with connect(database) as connection:
        forecast = forecast_revenue(connection, as_of)

    assert forecast["available"] is True
    assert forecast["lookback_days"] == 28
    assert forecast["horizon_days"] == 14
    assert len(forecast["daily"]) == 14
    assert forecast["daily"][0]["date"] == "2026-11-01"
    assert forecast["daily"][-1]["date"] == "2026-11-14"
    assert all(item["lower"] <= item["revenue"] <= item["upper"] for item in forecast["daily"])
    assert "No seasonality" in forecast["method"]


def test_forecast_is_unavailable_without_enough_active_days():
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE TABLE orders (order_date DATE, net_revenue DOUBLE)")
    connection.execute(
        "INSERT INTO orders VALUES ('2026-10-01', 10), ('2026-10-02', 20), ('2026-10-03', 30)"
    )

    forecast = forecast_revenue(connection, date(2026, 10, 3))

    assert forecast["available"] is False
    assert forecast["daily"] == []
    connection.close()


def test_investigation_handles_missing_segment_dimensions():
    connection = duckdb.connect(":memory:")
    connection.execute(
        """
        CREATE TABLE orders (
            order_date DATE, net_revenue DOUBLE, returned BOOLEAN, delivery_days INTEGER,
            category VARCHAR, channel VARCHAR, device VARCHAR, region VARCHAR, warehouse VARCHAR,
            discount_rate DOUBLE
        )
        """
    )
    rows = []
    for day in range(60):
        order_date = date(2026, 9, 2) + timedelta(days=day)
        for order in range(2):
            # Imported snapshots can legitimately omit every segment label.
            returned = day >= 30
            revenue = 50 if day < 30 else 40
            rows.append((order_date, revenue, returned, 3, None, None, None, None, None, 0.1))
    connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)

    result = investigate(connection, window_days=30, as_of=date(2026, 10, 31))

    assert result["revenue_drivers"] == {"category": [], "channel": []}
    assert {finding["id"] for finding in result["findings"]} >= {"revenue"}
    connection.close()
