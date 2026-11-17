# Synthetic data generator

The executable generator is [`app/seed.py`](../../app/seed.py). It creates one year of deterministic e-commerce orders and injects two recent incidents: elevated Home fulfillment time/returns and deeper Paid Search discounts. The fixed seed makes the dashboard and tests repeatable.

Scenario definitions for evaluator expansion live in [`evals/scenarios/scenarios.json`](../../evals/scenarios/scenarios.json).
