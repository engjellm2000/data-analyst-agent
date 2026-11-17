# Data sources and metric semantics

## Synthetic demo

`app.seed` creates reproducible order-level data and intentionally injects recent fulfillment and discount patterns. It is useful for repeatable development and controlled tests, but it is not evidence that the app's thresholds generalize to a real business.

## Olist CSV import

`python -m app.import_olist --input-dir <extracted-csv-folder> --database data/olist.duckdb` imports the public Brazilian E-Commerce dataset. The importer requires the orders, order-items, products, and customers CSVs; category translation is optional. It creates a new database and refuses to overwrite an existing path.

| App field | Olist source | Meaning and limitations |
|---|---|---|
| `order_date` | `order_purchase_timestamp` | Purchase calendar date; period windows use this date. |
| `net_revenue` | Sum of item `price` values | Excludes freight; cancellation/non-delivery statuses are excluded. |
| `units` | Number of order-item rows | Olist's order-item export has one row per item. |
| `category` | Product category and optional translation | Single-category orders retain the category; multi-category orders become `Mixed`; missing categories become `Unknown`. |
| `region` | Customer `customer_state` | Brazilian state code; not a warehouse or shipping destination measure. |
| `delivery_days` | Delivered timestamp minus purchase timestamp | Fractional elapsed days; missing delivery timestamps stay NULL. |
| `returned` | Not present | NULL; return counts/rates and return alerts are unavailable. |
| Channel, device, discount, marketing spend | Not present | NULL and excluded from segment output; never interpreted as zero. |

Only records with `order_status=delivered`, a valid purchase timestamp, and at least one item are included. Import metadata records source status counts and excluded/missing field counts. The app does not download the data; users obtain it from the public source and must review the source's current access and use terms.

The importer is an offline batch path, not a connector. Before using an alternative source, define the meaning, currency, timezone, grain, and treatment of refunds, taxes, shipping, partial fulfillment, and duplicate records for every metric.

## Shopify cloud demo connector

The optional cloud-demo connector authenticates a Shopify store with OAuth, fetches up to 1,000 orders in the recent 60-day window, and updates orders through HMAC-verified webhooks. It stores order ID/date, current item subtotal, currency, product type, quantity, channel, and discount rate. Customer identifiers and PII are omitted. Subtotal excludes tax and shipping; canceled orders are excluded from analysis. Only one currency per workspace is supported, and analysis windows are limited to 7, 14, or 30 days.

Returns, device, delivery time, marketing spend, and historical backfill are unavailable. Shopify's real-world OAuth and webhook flow has not been verified without a configured app and development store. The connector is for test-store demo data only; see [free cloud demo deployment](deployment.md).
