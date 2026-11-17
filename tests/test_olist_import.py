import csv
from datetime import date
import json

import pytest

from app.analytics import investigate
from app.db import connect
from app.import_olist import import_olist


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


def test_olist_import_preserves_missing_metrics_and_reports_quality(tmp_path):
    source = tmp_path / "olist"
    source.mkdir()
    orders = []
    items = []
    customers = []
    products = [{"product_id": "p1", "product_category_name": "bed_bath_table"}]
    sequence = 0
    for day in range(1, 16):
        for _ in range(3):
            sequence += 1
            order_id = f"o{sequence}"
            orders.append({
                "order_id": order_id,
                "order_status": "delivered",
                "order_purchase_timestamp": f"2026-01-{day:02d} 10:00:00",
                "order_delivered_customer_date": f"2026-01-{day:02d} 12:00:00",
                "customer_id": f"c{sequence}",
            })
            items.append({
                "order_id": order_id,
                "order_item_id": "1",
                "product_id": "p1",
                "price": "25.00",
            })
            customers.append({"customer_id": f"c{sequence}", "customer_state": "SP"})
    orders.append({
        "order_id": "canceled",
        "order_status": "canceled",
        "order_purchase_timestamp": "2026-01-15 10:00:00",
        "order_delivered_customer_date": "",
        "customer_id": "canceled-customer",
    })
    items.append({"order_id": "canceled", "order_item_id": "1", "product_id": "p1", "price": "999.00"})
    customers.append({"customer_id": "canceled-customer", "customer_state": "SP"})

    _write_csv(source / "olist_orders_dataset.csv", orders)
    _write_csv(source / "olist_order_items_dataset.csv", items)
    _write_csv(source / "olist_products_dataset.csv", products)
    _write_csv(source / "olist_customers_dataset.csv", customers)
    _write_csv(source / "product_category_name_translation.csv", [{
        "product_category_name": "bed_bath_table",
        "product_category_name_english": "bed_bath_table",
    }])

    database = tmp_path / "olist.duckdb"
    metadata = import_olist(source, database)
    assert metadata["quality"]["included_delivered_orders"] == 45
    assert metadata["quality"]["excluded_non_delivered_orders"] == 1

    with connect(database) as connection:
        result = investigate(connection, window_days=7, as_of=date(2026, 1, 15))
        assert result["metrics"]["current"]["orders"] == 21
        assert result["metrics"]["current"]["revenue"] == 525.0
        assert result["metrics"]["current"]["return_rate"] is None
        assert result["metrics"]["current"]["delivery_days"] == 0.08
        assert result["revenue_drivers"]["channel"] == []
        assert result["method"]["thresholds"]["returns"].startswith("Disabled")
        assert "returns" not in {finding["id"] for finding in result["findings"]}
        direct_revenue, direct_order_count = connection.execute(
            "SELECT SUM(net_revenue), COUNT(*) FROM orders WHERE order_date BETWEEN DATE '2026-01-09' AND DATE '2026-01-15'"
        ).fetchone()
        assert result["metrics"]["current"]["revenue"] == direct_revenue
        assert result["metrics"]["current"]["orders"] == direct_order_count

        stored_metadata = json.loads(connection.execute("SELECT metadata_json FROM dataset_metadata").fetchone()[0])
        assert stored_metadata["label"] == "Brazilian E-Commerce Public Dataset by Olist"


def test_olist_import_refuses_to_overwrite_an_existing_database(tmp_path):
    source = tmp_path / "olist"
    source.mkdir()
    database = tmp_path / "existing.duckdb"
    database.touch()
    with pytest.raises(FileExistsError, match="Choose a new output path"):
        import_olist(source, database)
