from datetime import date, timedelta
import math
from typing import Any

import duckdb
from agent.detector import detect_daily_anomalies
from agent.investigator import investigate_finding
from agent.recommender import recommend
from agent.reporter import morning_briefing


ALLOWED_WINDOWS = (7, 14, 30, 60, 90)


def forecast_revenue(
    connection: duckdb.DuckDBPyConnection,
    as_of: date,
    horizon_days: int = 14,
    lookback_days: int = 28,
) -> dict[str, Any]:
    start = as_of - timedelta(days=lookback_days - 1)
    rows = connection.execute(
        """
        SELECT order_date, SUM(net_revenue), COUNT(*)
        FROM orders
        WHERE order_date BETWEEN ? AND ?
        GROUP BY order_date
        ORDER BY order_date
        """,
        [start, as_of],
    ).fetchall()
    revenue_by_date = {row[0]: float(row[1]) for row in rows}
    order_counts = {row[0]: int(row[2]) for row in rows}
    history = [
        {
            "date": (start + timedelta(days=index)).isoformat(),
            "revenue": round(revenue_by_date.get(start + timedelta(days=index), 0.0), 2),
        }
        for index in range(lookback_days)
    ]
    observed_days = sum(1 for count in order_counts.values() if count > 0)
    if observed_days < 7:
        return {
            "available": False,
            "reason": "At least 7 days with orders are required to produce a forecast.",
            "lookback_days": lookback_days,
            "horizon_days": horizon_days,
            "history": history,
            "daily": [],
        }

    values = [item["revenue"] for item in history]
    mean_x = (lookback_days - 1) / 2
    mean_y = sum(values) / lookback_days
    denominator = sum((index - mean_x) ** 2 for index in range(lookback_days))
    slope = (
        sum((index - mean_x) * (value - mean_y) for index, value in enumerate(values)) / denominator
        if denominator
        else 0.0
    )
    intercept = mean_y - slope * mean_x
    residuals = [value - (intercept + slope * index) for index, value in enumerate(values)]
    residual_scale = math.sqrt(sum(residual ** 2 for residual in residuals) / max(lookback_days - 2, 1))

    daily = []
    for offset in range(1, horizon_days + 1):
        x = lookback_days - 1 + offset
        projected = max(0.0, intercept + slope * x)
        margin = 1.96 * residual_scale * math.sqrt(1 + offset / lookback_days)
        forecast_date = as_of + timedelta(days=offset)
        daily.append({
            "date": forecast_date.isoformat(),
            "revenue": round(projected, 2),
            "lower": round(max(0.0, projected - margin), 2),
            "upper": round(projected + margin, 2),
        })

    projected_total = sum(item["revenue"] for item in daily)
    baseline_total = mean_y * horizon_days
    return {
        "available": True,
        "lookback_days": lookback_days,
        "horizon_days": horizon_days,
        "observed_days": observed_days,
        "average_daily_revenue": round(mean_y, 2),
        "projected_total": round(projected_total, 2),
        "lower_total": round(sum(item["lower"] for item in daily), 2),
        "upper_total": round(sum(item["upper"] for item in daily), 2),
        "change_vs_baseline_pct": round((projected_total / baseline_total - 1) * 100, 1) if baseline_total else None,
        "history": history,
        "daily": daily,
        "method": "Linear trend over the last 28 calendar days; approximate planning range from residual variation. No seasonality or causal assumptions.",
    }


def _period_metrics(connection: duckdb.DuckDBPyConnection, current_start: date, as_of: date, previous_start: date) -> dict:
    current_end = as_of
    previous_end = current_start - timedelta(days=1)
    row = connection.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_orders,
            COALESCE(SUM(net_revenue) FILTER (WHERE order_date BETWEEN ? AND ?), 0) AS current_revenue,
            COALESCE(SUM(CASE WHEN returned THEN 1 ELSE 0 END) FILTER (WHERE order_date BETWEEN ? AND ?), 0) AS current_returns,
            COUNT(returned) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_return_observations,
            AVG(delivery_days) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_delivery,
            COUNT(delivery_days) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_delivery_observations,
            COUNT(*) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_orders,
            COALESCE(SUM(net_revenue) FILTER (WHERE order_date BETWEEN ? AND ?), 0) AS previous_revenue,
            COALESCE(SUM(CASE WHEN returned THEN 1 ELSE 0 END) FILTER (WHERE order_date BETWEEN ? AND ?), 0) AS previous_returns,
            COUNT(returned) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_return_observations,
            AVG(delivery_days) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_delivery,
            COUNT(delivery_days) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_delivery_observations
        FROM orders
        WHERE order_date BETWEEN ? AND ?
        """,
        [
            current_start, current_end,
            current_start, current_end,
            current_start, current_end,
            current_start, current_end,
            current_start, current_end,
            current_start, current_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, current_end,
        ],
    ).fetchone()

    (
        current_orders, current_revenue, current_returns, current_return_observations,
        current_delivery, current_delivery_observations, previous_orders, previous_revenue,
        previous_returns, previous_return_observations, previous_delivery,
        previous_delivery_observations,
    ) = row
    current_orders = int(current_orders)
    previous_orders = int(previous_orders)
    current_aov = current_revenue / current_orders if current_orders else 0
    previous_aov = previous_revenue / previous_orders if previous_orders else 0
    current_return_rate = current_returns / current_return_observations if current_return_observations else None
    previous_return_rate = previous_returns / previous_return_observations if previous_return_observations else None
    return {
        "current": {
            "orders": current_orders,
            "revenue": round(float(current_revenue), 2),
            "aov": round(current_aov, 2),
            "returns": int(current_returns),
            "return_rate": round(current_return_rate, 4) if current_return_rate is not None else None,
            "delivery_days": round(float(current_delivery), 2) if current_delivery_observations else None,
        },
        "previous": {
            "orders": previous_orders,
            "revenue": round(float(previous_revenue), 2),
            "aov": round(previous_aov, 2),
            "returns": int(previous_returns),
            "return_rate": round(previous_return_rate, 4) if previous_return_rate is not None else None,
            "delivery_days": round(float(previous_delivery), 2) if previous_delivery_observations else None,
        },
    }


def _segment_metrics(
    connection: duckdb.DuckDBPyConnection,
    dimension: str,
    current_start: date,
    as_of: date,
    previous_start: date,
) -> list[dict]:
    if dimension not in {"category", "channel", "device", "region"}:
        raise ValueError(f"Unsupported segment dimension: {dimension}")

    previous_end = current_start - timedelta(days=1)
    rows = connection.execute(
        f"""
        SELECT
            {dimension} AS segment,
            COUNT(*) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_orders,
            COALESCE(SUM(net_revenue) FILTER (WHERE order_date BETWEEN ? AND ?), 0) AS current_revenue,
            AVG(net_revenue) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_aov,
            AVG(discount_rate) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_discount,
            AVG(CASE WHEN returned IS NULL THEN NULL WHEN returned THEN 1.0 ELSE 0.0 END) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_return_rate,
            AVG(delivery_days) FILTER (WHERE order_date BETWEEN ? AND ?) AS current_delivery,
            COUNT(*) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_orders,
            COALESCE(SUM(net_revenue) FILTER (WHERE order_date BETWEEN ? AND ?), 0) AS previous_revenue,
            AVG(net_revenue) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_aov,
            AVG(discount_rate) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_discount,
            AVG(CASE WHEN returned IS NULL THEN NULL WHEN returned THEN 1.0 ELSE 0.0 END) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_return_rate,
            AVG(delivery_days) FILTER (WHERE order_date BETWEEN ? AND ?) AS previous_delivery
        FROM orders
        WHERE order_date BETWEEN ? AND ?
          AND {dimension} IS NOT NULL
        GROUP BY {dimension}
        """,
        [
            current_start, as_of,
            current_start, as_of,
            current_start, as_of,
            current_start, as_of,
            current_start, as_of,
            current_start, as_of,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, previous_end,
            previous_start, as_of,
        ],
    ).fetchall()
    result = []
    for row in rows:
        (
            segment,
            current_orders,
            current_revenue,
            current_aov,
            current_discount,
            current_return_rate,
            current_delivery,
            previous_orders,
            previous_revenue,
            previous_aov,
            previous_discount,
            previous_return_rate,
            previous_delivery,
        ) = row
        result.append(
            {
                "segment": segment,
                "current_orders": int(current_orders),
                "current_revenue": float(current_revenue or 0),
                "current_aov": float(current_aov or 0),
                "current_discount": float(current_discount) if current_discount is not None else None,
                "current_return_rate": float(current_return_rate) if current_return_rate is not None else None,
                "current_delivery": float(current_delivery or 0),
                "previous_orders": int(previous_orders),
                "previous_revenue": float(previous_revenue or 0),
                "previous_aov": float(previous_aov or 0),
                "previous_discount": float(previous_discount) if previous_discount is not None else None,
                "previous_return_rate": float(previous_return_rate) if previous_return_rate is not None else None,
                "previous_delivery": float(previous_delivery or 0),
            }
        )
    return result


def _revenue_drivers(segments: list[dict], dimension: str) -> list[dict[str, Any]]:
    """Rank revenue changes within one dimension, never across dimensions."""
    drivers = []
    for item in segments:
        change = item["current_revenue"] - item["previous_revenue"]
        drivers.append(
            {
                "dimension": dimension,
                "segment": item["segment"],
                "current_revenue": round(item["current_revenue"], 2),
                "previous_revenue": round(item["previous_revenue"], 2),
                "change": round(change, 2),
                "change_pct": round(change / item["previous_revenue"], 4) if item["previous_revenue"] else None,
            }
        )
    return sorted(drivers, key=lambda driver: driver["change"])


def _finding(
    finding_id: str,
    title: str,
    metric: str,
    priority: str,
    summary: str,
    explanation: str,
    evidence: list[dict[str, str]],
    recommendation: str,
    segment: str,
) -> dict[str, Any]:
    return {
        "id": finding_id,
        "title": title,
        "metric": metric,
        "priority": priority,
        "summary": summary,
        "explanation": explanation,
        "evidence": evidence,
        "recommendation": recommendation,
        "segment": segment,
    }


def investigate(
    connection: duckdb.DuckDBPyConnection,
    window_days: int = 30,
    as_of: date | None = None,
) -> dict[str, Any]:
    if window_days not in ALLOWED_WINDOWS:
        raise ValueError(f"window_days must be one of {ALLOWED_WINDOWS}")

    # A local synthetic database is not necessarily refreshed every calendar
    # day. Anchor an unscheduled investigation to the newest observed order so
    # its "current" window never includes missing future dates.
    if as_of is None:
        latest_order_date = connection.execute("SELECT MAX(order_date) FROM orders").fetchone()[0]
        if latest_order_date is None:
            raise ValueError("Cannot investigate an empty orders dataset")
        end = latest_order_date
    else:
        end = as_of
    current_start = end - timedelta(days=window_days - 1)
    previous_start = current_start - timedelta(days=window_days)
    metrics = _period_metrics(connection, current_start, end, previous_start)
    current = metrics["current"]
    previous = metrics["previous"]

    series_rows = connection.execute(
        """
        SELECT order_date, SUM(net_revenue), COUNT(*)
        FROM orders
        WHERE order_date BETWEEN ? AND ?
        GROUP BY order_date
        ORDER BY order_date
        """,
        [current_start, end],
    ).fetchall()
    series = [
        {"date": row[0].isoformat(), "revenue": round(float(row[1]), 2), "orders": int(row[2])}
        for row in series_rows
    ]

    category_segments = _segment_metrics(connection, "category", current_start, end, previous_start)
    channel_segments = _segment_metrics(connection, "channel", current_start, end, previous_start)
    revenue_drivers = {
        "category": _revenue_drivers(category_segments, "Category"),
        "channel": _revenue_drivers(channel_segments, "Channel"),
    }
    findings = []

    return_change = (
        current["return_rate"] - previous["return_rate"]
        if current["return_rate"] is not None and previous["return_rate"] is not None
        else None
    )
    if return_change is not None and return_change >= 0.012 and current["orders"] >= 40:
        return_segments = [
            item for item in category_segments
            if item["current_return_rate"] is not None and item["previous_return_rate"] is not None
        ]
        if return_segments:
            top_category = max(
                return_segments,
                key=lambda item: (
                    item["current_return_rate"] - item["previous_return_rate"]
                ) * item["current_orders"],
            )
            category_change = top_category["current_return_rate"] - top_category["previous_return_rate"]
            delivery_change = (
                top_category["current_delivery"] - top_category["previous_delivery"]
                if top_category["current_delivery"] is not None and top_category["previous_delivery"] is not None
                else None
            )
            evidence = [
                {
                    "label": "Overall return rate",
                    "value": f"{previous['return_rate']:.1%} → {current['return_rate']:.1%} ({return_change * 100:+.1f} pp)",
                },
                {
                    "label": f"{top_category['segment']} return rate",
                    "value": f"{top_category['previous_return_rate']:.1%} → {top_category['current_return_rate']:.1%} across {top_category['current_orders']:,} recent orders",
                },
                {
                    "label": f"{top_category['segment']} delivery time",
                    "value": (
                        f"{top_category['previous_delivery']:.1f} → {top_category['current_delivery']:.1f} days ({delivery_change:+.1f} days)"
                        if delivery_change is not None
                        else "Not available"
                    ),
                },
            ]
            explanation = (
                f"{top_category['segment']} has the largest positive segment contribution to the return-rate change "
                f"({category_change * 100:+.1f} pp). "
                + (
                    f"Its average delivery time moved {delivery_change:+.1f} days over the same comparison. "
                    if delivery_change is not None
                    else ""
                )
                + "These changes co-occur; this comparison does not establish that delivery time caused returns."
            )
            findings.append(
                _finding(
                    "returns",
                    "Returns are rising",
                    "Return rate",
                    "High",
                    f"Return rate increased {return_change * 100:.1f} percentage points versus the previous {window_days} days.",
                    explanation,
                    evidence,
                    f"Review {top_category['segment']} shipment performance and sample recent return reasons before changing fulfillment policy. Track return rate and delivery time together over the next {window_days} days.",
                    top_category["segment"],
                )
            )

    aov_change = current["aov"] - previous["aov"]
    aov_change_pct = (aov_change / previous["aov"]) if previous["aov"] else 0
    if aov_change_pct <= -0.05 and current["orders"] >= 40:
        aov_segments = channel_segments or category_segments
        if aov_segments:
            top_channel = min(
                aov_segments,
                key=lambda item: item["current_aov"] - item["previous_aov"],
            )
            channel_change_pct = (
                (top_channel["current_aov"] - top_channel["previous_aov"]) / top_channel["previous_aov"]
                if top_channel["previous_aov"]
                else 0
            )
            findings.append(
                _finding(
                    "basket-value",
                    "Order value is softening",
                    "Average order value",
                    "Medium",
                    f"Average order value is {abs(aov_change_pct):.1%} lower than the previous {window_days} days.",
                    f"{top_channel['segment']} has the largest segment-level AOV decline ({channel_change_pct:.1%}). "
                    + (
                        "Discount depth is shown as context, not proof that discounts caused the change."
                        if top_channel["current_discount"] is not None and top_channel["previous_discount"] is not None
                        else "Discount depth is unavailable in this dataset."
                    ),
                    [
                        {
                            "label": "Overall average order value",
                            "value": f"${previous['aov']:,.2f} → ${current['aov']:,.2f} ({aov_change_pct:.1%})",
                        },
                        {
                            "label": f"{top_channel['segment']} average discount",
                            "value": (
                                f"{top_channel['previous_discount']:.1%} → {top_channel['current_discount']:.1%}"
                                if top_channel["previous_discount"] is not None and top_channel["current_discount"] is not None
                                else "Not available"
                            ),
                        },
                        {
                            "label": f"{top_channel['segment']} orders",
                            "value": f"{top_channel['previous_orders']:,} → {top_channel['current_orders']:,}",
                        },
                    ],
                    f"Compare net revenue per order and order count for {top_channel['segment']} and validate the relevant pricing or mix changes in the source system before changing policy.",
                    top_channel["segment"],
                )
            )

    revenue_change_pct = (
        (current["revenue"] - previous["revenue"]) / previous["revenue"]
        if previous["revenue"]
        else 0
    )
    if revenue_change_pct <= -0.08 and current["orders"] >= 40:
        findings.append(
            _finding(
                "revenue",
                "Revenue is below the prior period",
                "Net revenue",
                "High",
                f"Net revenue decreased {abs(revenue_change_pct):.1%} versus the previous {window_days} days.",
                "Segment comparisons can show where the decrease is concentrated. They cannot establish why it happened without additional operational context.",
                [
                    {
                        "label": "Net revenue",
                        "value": f"${previous['revenue']:,.0f} → ${current['revenue']:,.0f} ({revenue_change_pct:.1%})",
                    },
                    {
                        "label": "Orders",
                        "value": f"{previous['orders']:,} → {current['orders']:,}",
                    },
                    {
                        "label": "Average order value",
                        "value": f"${previous['aov']:,.2f} → ${current['aov']:,.2f}",
                    },
                ],
                "Break down the change by available segments, then validate inventory, campaign, and pricing events in the source system before assigning an owner or changing spend.",
                "All segments",
            )
        )

    if not findings:
        findings.append(
            _finding(
                "steady",
                "No material threshold breach",
                "Period comparison",
                "Monitor",
                f"The tracked changes stayed within the investigation thresholds for this {window_days}-day window.",
                "This is not proof that performance is healthy; small or unmeasured changes may not trigger a finding.",
                [
                    {
                        "label": "Return rate",
                        "value": (
                            f"{previous['return_rate']:.1%} → {current['return_rate']:.1%}"
                            if previous["return_rate"] is not None and current["return_rate"] is not None
                            else "Not available in this dataset"
                        ),
                    },
                    {
                        "label": "Average order value",
                        "value": f"${previous['aov']:,.2f} → ${current['aov']:,.2f}",
                    },
                ],
                "Keep the current baseline and rerun after the next reporting period or when new data is available.",
                "All segments",
            )
        )

    findings.sort(key=lambda finding: {"High": 0, "Medium": 1, "Monitor": 2}[finding["priority"]])
    periods = {
        "current_start": current_start.isoformat(), "current_end": end.isoformat(),
        "previous_start": previous_start.isoformat(), "previous_end": (current_start - timedelta(days=1)).isoformat(),
    }
    traces, recommendations = {}, {}
    for finding in findings:
        recommendations[finding["id"]] = recommend(finding, metrics)
        try:
            traces[finding["id"]] = investigate_finding(connection, finding, periods)
        except (FileNotFoundError, duckdb.Error):
            traces[finding["id"]] = {"trace": [{"step": "Trace", "status": "unavailable", "detail": "Trace database was unavailable."}], "budget": {}}
    deterministic_anomalies = detect_daily_anomalies(connection, as_of=end)
    return {
        "window_days": window_days,
        **periods,
        "metrics": metrics,
        "series": series,
        "forecast": forecast_revenue(connection, end),
        "revenue_drivers": revenue_drivers,
        "findings": findings,
        "anomalies": deterministic_anomalies[:12],
        "investigation_traces": traces,
        "briefing": morning_briefing(findings, recommendations),
        "method": {
            "comparison": f"Most recent {window_days} days versus the immediately preceding {window_days} days.",
            "thresholds": {
                "returns": (
                    "At least +1.2 percentage points and 40 or more recent orders."
                    if current["return_rate"] is not None and previous["return_rate"] is not None
                    else "Disabled because the dataset has no observed return labels."
                ),
                "average_order_value": "At least 5% lower and 40 or more recent orders.",
                "revenue": "At least 8% lower and 40 or more recent orders.",
            },
            "caveat": "Segment differences are descriptive associations. They do not prove causation.",
        },
    }
