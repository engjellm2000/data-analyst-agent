# Architecture

`Local: synthetic generator or Olist CSV importer → source-aware DuckDB → deterministic detector → bounded investigator → evidence report → UI/evals`

`Cloud demo: Supabase Auth → verified user/workspace context → PostgreSQL with row-level security → Shopify OAuth/API sync + signed webhooks → same deterministic analysis → UI`

The detector uses robust median absolute deviation scores, keeping alerting repeatable and free of model cost. The investigator is deliberately provider-neutral: its planner can be replaced by an LLM, but its queries are always read-only, row-capped, and recorded in a scratchpad. Recommendations use observed-period arithmetic and state their assumptions.

Every root-cause statement remains an association unless an experiment or operational event proves causality.

Investigation results are persisted in the active local database or tenant workspace. The UI lists recent runs, reopens a selected result, and exports its recorded evidence as JSON or CSV. A browser-local threshold monitor evaluates revenue, returns, and delivery changes; unavailable source metrics remain unavailable. A separate 14-day revenue projection fits a linear trend to the preceding 28 calendar days and labels its residual-based planning range as approximate.

The Olist path imports a static public CSV snapshot and records its provenance and quality counts. Unsupported fields remain NULL, so unsupported metrics are not reported as zero. The current import maps one row per delivered order; revenue sums item prices, excludes freight, and assigns multi-category orders to `Mixed`. It is not a live-system connector.

The cloud demo uses Supabase JWT verification and database RLS for workspace isolation. Privileged database operations are limited to server-side workspace creation and Shopify lifecycle operations. Shopify order data is scoped by tenant; customer PII is not stored. Cloud infrastructure and Shopify end-to-end behavior remain unverified without provider projects and a development store. See the [security model](security.md) and [deployment runbook](deployment.md); this is not a production-readiness claim.
