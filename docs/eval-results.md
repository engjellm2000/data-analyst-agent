# Evaluation results

Run `python -m evals.run_evals` to run the analytics on a deterministic synthetic incident fixture and a clean control. The UI presents those measured fixture results.

The benchmark checks whether the expected return-rate and average-order-value findings appear, whether the corresponding segment is identified, whether the clean control remains quiet, and the local compute cost (zero external-model spend). The fixture uses generated data with known injected conditions, so it only verifies implementation behavior on those cases.

The 24 entries in `evals/scenarios/scenarios.json` are a scenario catalog and are not currently scored. The fixture benchmark is not an estimate of performance on Olist, live customer data, or production systems. The Olist importer has its own integration tests for supported fields, unsupported metrics, and row filtering; it does not yet have independently labeled real-world incident ground truth.
