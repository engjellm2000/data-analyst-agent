from datetime import date, timedelta
import random

from app.db import connect, copy_orders


CHANNELS = ("Organic", "Paid search", "Email", "Social", "Affiliate")
CATEGORIES = ("Home", "Apparel", "Beauty", "Electronics", "Outdoor")
DEVICES = ("Mobile", "Desktop", "Tablet")
REGIONS = ("Northeast", "Southeast", "Midwest", "Southwest", "West")
WAREHOUSES = ("East hub", "Central hub", "West hub")
PRICE_BY_CATEGORY = {
    "Home": 82,
    "Apparel": 54,
    "Beauty": 36,
    "Electronics": 146,
    "Outdoor": 94,
}


def generate_orders(end_date: date, days: int = 365, seed: int = 2026, inject_incidents: bool = True) -> list[tuple]:
    rng = random.Random(seed)
    rows = []
    sequence = 1

    for day_index in range(days):
        order_date = end_date - timedelta(days=days - day_index - 1)
        recent_period = inject_incidents and day_index >= days - 30
        weekday_factor = 1.16 if order_date.weekday() in (5, 6) else 0.94
        order_count = round(rng.randint(65, 92) * weekday_factor)

        for _ in range(order_count):
            channel = rng.choices(CHANNELS, weights=(30, 25, 18, 17, 10), k=1)[0]
            category = rng.choices(CATEGORIES, weights=(24, 25, 18, 17, 16), k=1)[0]
            device = rng.choices(DEVICES, weights=(59, 34, 7), k=1)[0]
            region = rng.choice(REGIONS)
            warehouse = "East hub" if region in ("Northeast", "Southeast") else ("Central hub" if region == "Midwest" else "West hub")
            units = rng.choices((1, 2, 3), weights=(73, 23, 4), k=1)[0]

            discount = rng.uniform(0.06, 0.22)
            if recent_period and channel == "Paid search":
                discount = rng.uniform(0.38, 0.52)

            base_delivery = rng.choices((2, 3, 4, 5, 6), weights=(12, 28, 32, 19, 9), k=1)[0]
            if recent_period and category == "Home":
                delivery_days = base_delivery + rng.choice((2, 3, 4, 5))
            else:
                delivery_days = base_delivery + (1 if region in ("Southwest", "West") else 0)

            return_probability = {
                "Home": 0.075,
                "Apparel": 0.105,
                "Beauty": 0.055,
                "Electronics": 0.085,
                "Outdoor": 0.07,
            }[category]
            if recent_period and category == "Home":
                return_probability += 0.17
            if delivery_days >= 8:
                return_probability += 0.035
            returned = rng.random() < return_probability

            list_value = PRICE_BY_CATEGORY[category] * units * rng.uniform(0.82, 1.18)
            net_revenue = round(list_value * (1 - discount), 2)
            marketing_spend = round(
                rng.uniform(3.0, 15.0) if channel == "Paid search" else rng.uniform(0.2, 5.0),
                2,
            )
            customer_id = f"C{rng.randint(1, 9000):05d}"
            rows.append(
                (
                    f"O{sequence:07d}",
                    order_date,
                    channel,
                    category,
                    device,
                    region,
                    warehouse,
                    units,
                    net_revenue,
                    round(discount, 4),
                    delivery_days,
                    returned,
                    marketing_spend,
                    customer_id,
                )
            )
            sequence += 1

    return rows


def initialize_database(path: str | None = None, end_date: date | None = None, inject_incidents: bool = True) -> int:
    as_of = end_date or date.today()
    with connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
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
                delivery_days INTEGER,
                returned BOOLEAN,
                marketing_spend DOUBLE,
                customer_id VARCHAR
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info('orders')").fetchall()}
        if "warehouse" not in columns:
            connection.execute("ALTER TABLE orders ADD COLUMN warehouse VARCHAR DEFAULT 'Unknown'")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS investigations (
                investigation_id VARCHAR PRIMARY KEY,
                run_at TIMESTAMP NOT NULL,
                window_days INTEGER NOT NULL,
                result_json JSON NOT NULL
            )
            """
        )
        connection.execute("CREATE TABLE IF NOT EXISTS dataset_metadata (metadata_json JSON NOT NULL)")
        metadata_count = connection.execute("SELECT COUNT(*) FROM dataset_metadata").fetchone()[0]
        if not metadata_count:
            connection.execute(
                "INSERT INTO dataset_metadata VALUES (?)",
                ["""
                {"label":"Generated synthetic e-commerce","source":"Locally generated, deterministic seed; not customer data.","source_url":null,"quality":{},"supported_metrics":["order count","net revenue","average order value","return rate","delivery time","channel","category","region","discount rate","marketing spend"],"unsupported_metrics":[],"limitations":["Synthetic data for demonstration; not evidence of live-system integration or real-world performance."]}
                """],
            )
        existing_count = connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        if existing_count:
            return existing_count

        rows = generate_orders(as_of, days=365, inject_incidents=inject_incidents)
        copy_orders(connection, rows)
        return len(rows)


if __name__ == "__main__":
    count = initialize_database()
    print(f"Initialized synthetic dataset: {count:,} orders in DuckDB.")
