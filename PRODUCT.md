# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary users are inferred to be business operators and analysts who need to inspect e-commerce performance and decide what to investigate or do next.

## Product Purpose

Investigate business data, surface notable problems, explain the evidence behind them, and recommend prioritized actions. Success means a user can trace an insight back to measured comparisons and understand its limitations.

## Positioning

A repeatable investigation flow connects detected changes to calculated segment evidence and practical next steps, rather than presenting unexplained alerts or unsupported causal claims.

## Operating Context

The local application is backed by DuckDB and includes a synthetic demo and an offline importer for the public Olist e-commerce CSV snapshot. An optional cloud-demo mode uses Supabase Auth and PostgreSQL row-level security, with a Shopify test-store connector. Cloud mode is scoped to free portfolio hosting with no real customer data or production-readiness claim.

## Capabilities and Constraints

- The app supports a generated synthetic e-commerce dataset and a static Olist CSV import stored in DuckDB, plus an optional Shopify cloud-demo ingestion path.
- Olist analysis includes delivered orders, item-price revenue, order value, category, Brazilian customer state, and elapsed delivery time.
- Metrics absent from Olist (returns, sales channel, device, discount rate, and marketing spend) remain unavailable, not zero.
- Investigations are saved and can be reopened from recent history or exported as JSON and CSV.
- Configurable threshold alerts compare the selected run's current and prior windows; alert rules are saved in the current browser and do not send push or email notifications.
- Revenue forecasts project a 14-day linear trend from 28 calendar days of observed revenue. The approximate planning range is not a guarantee and does not model seasonality, causal drivers, or future events.
- Investigations must be repeatable and ground findings in calculated data.
- Explanations may identify associations and plausible drivers, but must not present correlation as proven causation.
- Recommendations should be prioritized and tied to the evidence.
- The Shopify connector stores limited order fields and does not store customer PII; end-to-end behavior requires a developer app and test store and is not yet verified.
- Cloud hosting uses free plans with no SLA and is for synthetic/test-store portfolio data only, not production or sensitive customer workloads.

## Evidence on Hand

No customer data or verified live-system integration was provided. Synthetic findings must be labeled as synthetic; Olist results must be labeled as analysis of a public static dataset; Shopify support must not be represented as a verified live merchant integration until end-to-end tested.

## Product Principles

- Make each conclusion traceable to a comparison or segment measurement.
- Distinguish observed evidence from hypotheses and recommendations.
- Prefer actionable, prioritized investigations over generic summaries.
- Make synthetic data unmistakable.
- Avoid implying that statistical association establishes causation.
- Label projections as descriptive estimates and keep their assumptions visible.

## Accessibility & Inclusion

Use semantic controls, keyboard-operable interactions, readable contrast, and responsive layouts as baseline web accessibility practices.
