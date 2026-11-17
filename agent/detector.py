"""Deterministic anomaly detection; no model calls are made here."""
from __future__ import annotations

from datetime import date, timedelta
import statistics
from typing import Any


def detect_daily_anomalies(connection, as_of: date | None = None, lookback_days: int = 90, z_threshold: float = 2.5) -> list[dict[str, Any]]:
    end = as_of or connection.execute("SELECT MAX(order_date) FROM orders").fetchone()[0]
    start = end - timedelta(days=lookback_days - 1)
    rows = connection.execute(
        """SELECT order_date, SUM(net_revenue) revenue, COUNT(*) orders,
                  AVG(CASE WHEN returned IS NULL THEN NULL WHEN returned THEN 1.0 ELSE 0.0 END) return_rate
           FROM orders WHERE order_date BETWEEN ? AND ? GROUP BY order_date ORDER BY order_date""",
        [start, end],
    ).fetchall()
    anomalies = []
    for metric_index, metric_name in ((1, "revenue"), (3, "return_rate")):
        observed = [(row, float(row[metric_index])) for row in rows if row[metric_index] is not None]
        if len(observed) < 3:
            continue
        values = [value for _, value in observed]
        median = statistics.median(values)
        deviations = [abs(value - median) for value in values]
        mad = statistics.median(deviations) or 0.0001
        for row, value in observed:
            robust_z = 0.6745 * (value - median) / mad
            if abs(robust_z) >= z_threshold:
                anomalies.append({"date": row[0].isoformat(), "metric": metric_name, "value": round(value, 4), "baseline_median": round(median, 4), "robust_z": round(robust_z, 2), "direction": "up" if robust_z > 0 else "down"})
    return sorted(anomalies, key=lambda item: abs(item["robust_z"]), reverse=True)
