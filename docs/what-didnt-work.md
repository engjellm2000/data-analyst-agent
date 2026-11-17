# What didn’t work yet

- A single period-over-period comparison can confuse seasonality with an incident; the robust daily detector is a complementary signal, not a full seasonal model.
- Generated data establishes repeatability, not external validity. Olist should be treated as a separate qualitative case study.
- The current evaluator is a contract benchmark: it defines 24 scenario labels and scoring but does not yet generate a separate DuckDB fixture for each manifest. Its numbers must not be presented as model performance.
- The planner is deterministic in this build. An LLM adapter should be evaluated for accuracy and cost before it becomes the default.
