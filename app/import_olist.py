"""Import the public Olist CSV export into the application's order schema."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

import duckdb

from app.db import connect, copy_orders


SOURCE_LABEL = "Brazilian E-Commerce Public Dataset by Olist"
SOURCE_URL = "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError as error:
        raise ValueError(f"Invalid Olist timestamp: {value!r}") from error


def _required_csv(input_dir: Path, filename: str) -> list[dict[str, str]]:
    path = input_dir / filename
    if not path.is_file():
        raise FileNotFoundError(f"Required Olist file not found: {path}")
    return _read_csv(path)


def _validate_columns(records: list[dict[str, str]], filename: str, required: set[str]) -> None:
    if records and not required.issubset(records[0]):
        raise ValueError(f"{filename} must contain columns: {', '.join(sorted(required))}")


def import_olist(input_dir: str | Path, database: str | Path) -> dict[str, Any]:
    """Create a new DuckDB file from extracted Olist CSV files.

    Only delivered orders with valid purchase dates are included. Unsupported
    source fields are left NULL rather than represented as observed zeroes.
    """
    source_dir = Path(input_dir).expanduser().resolve()
    database_path = Path(database).expanduser().resolve()
    if not source_dir.is_dir():
        raise NotADirectoryError(f"Olist input directory not found: {source_dir}")
    if database_path.exists():
        raise FileExistsError(
            f"Database already exists: {database_path}. Choose a new output path to avoid overwriting data."
        )

    order_records = _required_csv(source_dir, "olist_orders_dataset.csv")
    item_records = _required_csv(source_dir, "olist_order_items_dataset.csv")
    product_records = _required_csv(source_dir, "olist_products_dataset.csv")
    customer_records = _required_csv(source_dir, "olist_customers_dataset.csv")
    translation_path = source_dir / "product_category_name_translation.csv"
    translations = _read_csv(translation_path) if translation_path.is_file() else []

    _validate_columns(
        order_records,
        "olist_orders_dataset.csv",
        {"order_id", "order_status", "order_purchase_timestamp", "order_delivered_customer_date", "customer_id"},
    )
    _validate_columns(item_records, "olist_order_items_dataset.csv", {"order_id", "product_id", "price"})
    _validate_columns(product_records, "olist_products_dataset.csv", {"product_id", "product_category_name"})
    _validate_columns(customer_records, "olist_customers_dataset.csv", {"customer_id", "customer_state"})

    categories = {
        row["product_id"]: row.get("product_category_name") or "Unknown"
        for row in product_records
    }
    category_names = {
        row.get("product_category_name", ""): row.get("product_category_name_english") or row.get("product_category_name", "")
        for row in translations
    }
    customer_regions = {
        row["customer_id"]: row.get("customer_state") or "Unknown"
        for row in customer_records
    }
    item_groups: dict[str, list[dict[str, str]]] = {}
    for row in item_records:
        item_groups.setdefault(row.get("order_id", ""), []).append(row)

    status_counts: dict[str, int] = {}
    for order in order_records:
        status = order.get("order_status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1

    included = []
    missing_delivery_dates = 0
    missing_category_orders = 0
    missing_region_orders = 0
    mixed_category_orders = 0
    missing_item_orders = 0
    missing_purchase_dates = 0
    for order in order_records:
        if order.get("order_status") != "delivered":
            continue
        order_id = order.get("order_id", "")
        purchased_at = _parse_timestamp(order.get("order_purchase_timestamp"))
        if purchased_at is None:
            missing_purchase_dates += 1
            continue
        items = item_groups.get(order_id, [])
        if not items:
            missing_item_orders += 1
            continue
        try:
            revenue = sum(float(item["price"]) for item in items)
            units = len(items)
        except (KeyError, ValueError) as error:
            raise ValueError(f"Invalid item price for order {order_id}") from error
        if revenue < 0:
            raise ValueError(f"Negative item revenue for order {order_id}")

        order_categories = []
        for item in items:
            raw_category = categories.get(item.get("product_id", ""), "Unknown")
            order_categories.append(category_names.get(raw_category, raw_category) or "Unknown")
        known_categories = sorted(set(order_categories) - {"Unknown"})
        if not known_categories:
            category = "Unknown"
            missing_category_orders += 1
        elif len(known_categories) == 1:
            category = known_categories[0]
        else:
            category = "Mixed"
            mixed_category_orders += 1

        delivered_at = _parse_timestamp(order.get("order_delivered_customer_date"))
        if delivered_at is None:
            delivery_days = None
            missing_delivery_dates += 1
        else:
            delivery_days = round((delivered_at - purchased_at).total_seconds() / 86400, 2)
            if delivery_days < 0:
                raise ValueError(f"Delivery precedes purchase for order {order_id}")

        customer_id = order.get("customer_id", "")
        region = customer_regions.get(customer_id, "Unknown")
        if region == "Unknown":
            missing_region_orders += 1
        included.append(
            (
                order_id, purchased_at.date(), None, category, None,
                region, None, units, round(revenue, 2), None, delivery_days,
                None, None, "",
            )
        )

    if not included:
        raise ValueError("No delivered Olist orders with purchase dates and order items were found.")

    quality = {
        "source_orders": len(order_records),
        "source_status_counts": status_counts,
        "included_delivered_orders": len(included),
        "excluded_non_delivered_orders": len(order_records) - status_counts.get("delivered", 0),
        "delivered_orders_missing_items": missing_item_orders,
        "delivered_orders_missing_purchase_date": missing_purchase_dates,
        "included_orders_missing_delivery_date": missing_delivery_dates,
        "included_orders_missing_category": missing_category_orders,
        "included_orders_with_multiple_categories": mixed_category_orders,
        "included_orders_missing_customer_region": missing_region_orders,
    }
    metadata = {
        "label": SOURCE_LABEL,
        "source_url": SOURCE_URL,
        "source": "Public Olist CSV export; locally imported, not live-connected.",
        "currency": "BRL",
        "quality": quality,
        "supported_metrics": ["order count", "item revenue (excluding freight)", "average order value", "delivery time"],
        "unsupported_metrics": ["returns", "sales channel", "device", "discount rate", "marketing spend"],
        "limitations": [
            "Only delivered orders with item records and a purchase timestamp are included.",
            "Olist does not contain a returns indicator; return-rate findings are disabled.",
            "Olist does not identify sales channel, device, discount rate, or marketing spend.",
            "Revenue sums item prices and excludes freight; multi-category orders are grouped as Mixed.",
            "This is a static public dataset import, not a live store integration.",
        ],
    }

    database_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with connect(database_path) as connection:
            connection.execute(
                """
                CREATE TABLE orders (
                    order_id VARCHAR PRIMARY KEY,
                    order_date DATE NOT NULL,
                    channel VARCHAR,
                    category VARCHAR,
                    device VARCHAR,
                    region VARCHAR,
                    warehouse VARCHAR,
                    units INTEGER NOT NULL,
                    net_revenue DOUBLE NOT NULL,
                    discount_rate DOUBLE,
                    delivery_days DOUBLE,
                    returned BOOLEAN,
                    marketing_spend DOUBLE,
                    customer_id VARCHAR
                )
                """
            )
            copy_orders(connection, included)
            connection.execute("CREATE TABLE dataset_metadata (metadata_json JSON NOT NULL)")
            connection.execute("INSERT INTO dataset_metadata VALUES (?)", [json.dumps(metadata)])
    except duckdb.Error:
        database_path.unlink(missing_ok=True)
        raise
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Import extracted Olist CSV files into a new DuckDB database.")
    parser.add_argument("--input-dir", required=True, help="Directory containing the extracted Olist CSV files")
    parser.add_argument("--database", default="data/olist.duckdb", help="New DuckDB file to create (must not exist)")
    args = parser.parse_args()
    metadata = import_olist(args.input_dir, args.database)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
