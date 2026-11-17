# Free cloud demo deployment

This runbook deploys a **portfolio/demo environment only**. It is not suitable for real customer data or production operations. Free plans and quotas change; check the linked provider pages before creating resources.

## Services and constraints

- **Render Free web service:** runs the FastAPI Docker image; it sleeps after 15 minutes without traffic, has an ephemeral filesystem, and Render explicitly says Free instances should not be used for production. The application stores no cloud data on that filesystem.
- **Supabase Free:** provides Auth and PostgreSQL for the demo. The current plan lists a 500 MB database and can pause projects after one week of inactivity. It does not provide production uptime guarantees.
- **Sentry Developer (optional):** error reporting only, with the current free-plan quotas. Events are configured without default PII and request URL/query/body/header data is scrubbed.

Provider references: [Render free instances](https://render.com/docs/free), [Supabase pricing](https://supabase.com/pricing), [Sentry pricing](https://sentry.io/pricing/).

## Set up Supabase

1. Create a Supabase project on its free plan and enable email/password sign-in in **Authentication → Providers**.
2. In the SQL editor, run `supabase/migrations/202611090001_multitenant_shopify.sql`.
3. Copy the project URL and public anon/publishable key. The public key is intended for browser use; **never use a service-role key in the browser**.
4. Copy a server-side PostgreSQL connection string from the project database settings. Store it only as `BI_AGENT_DATABASE_URL` in the Render service. Use TLS and keep the database password private.

## Deploy the app on Render Free

Create a Web Service from this repository and choose the Docker runtime. Add these environment variables in the Render dashboard:

| Variable | Value |
|---|---|
| `APP_ENV` | `cloud-demo` |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase public anon/publishable key |
| `BI_AGENT_DATABASE_URL` | Server-side PostgreSQL URL (secret) |
| `METRICS_BEARER_TOKEN` | A long random value; protect `/metrics` |
| `SENTRY_DSN` | Optional Sentry project DSN |
| `SHOPIFY_CLIENT_ID` | Shopify app client ID, once configured |
| `SHOPIFY_CLIENT_SECRET` | Shopify app secret, secret |
| `SHOPIFY_REDIRECT_URI` | `https://<render-host>/api/shopify/callback` |
| `SHOPIFY_WEBHOOK_BASE_URL` | `https://<render-host>` |
| `SHOPIFY_TOKEN_ENCRYPTION_KEY` | Fernet key generated below |
| `SHOPIFY_SCOPES` | `read_orders,read_products` |
| `SHOPIFY_API_VERSION` | Pinned Shopify Admin API version |

Generate secret values locally in PowerShell; do not commit them:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
.\.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set Render's health-check path to `/api/health/ready`. The lightweight liveness endpoint is `/api/health`. `/metrics` requires the bearer token if configured.

## Register Shopify

1. Create an app in Shopify's Dev Dashboard and a development store you control. No store credentials are included in this repository.
2. Set the app URL to the Render HTTPS URL, and register the exact redirect URL `/api/shopify/callback`.
3. Request only `read_orders,read_products`. The connector does not request or persist customer names, email addresses, addresses, or phone numbers.
4. Add `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`, webhook base URL, and encryption key in Render. Restart/redeploy.
5. Sign in, create a workspace, connect the `.myshopify.com` domain, approve the Shopify authorization prompt, then choose **Sync recent orders**.

Each workspace can connect one Shopify store. OAuth creates subscriptions for order create/update/cancel, app uninstall, shop redaction, and customer privacy events. The sync fetches at most 1,000 orders from the recent 60-day window; webhooks keep subsequent order changes current. Analysis windows over 30 days are disabled because a 60-day history cannot support a longer current-plus-previous comparison.

The code can be unit-tested without a store, but installation, callback, API scope approval, and webhook delivery have **not** been end-to-end verified until tested against a development store. Check webhook delivery health in Shopify's app dashboard.

## Monitoring

- `GET /api/health` is liveness; `GET /api/health/ready` checks database readiness.
- `GET /metrics` exposes request counts and latency by route template, method, and status—never tenant IDs.
- Structured logs include a generated request ID, route template, status, and duration. Uvicorn access logs are disabled to avoid logging Shopify OAuth callback query parameters.
- Optional Sentry captures errors only (`traces_sample_rate=0`); request data, cookies, headers, and query strings are removed before sending.

The free host may sleep, free projects may pause, and no alerting/uptime SLA is included. This is observability for a demo, not staffed production monitoring.

## Local production-mode smoke check

Keep the normal synthetic quickstart separate. For a cloud-demo run, set the Supabase/PostgreSQL variables above plus `APP_ENV=cloud-demo`; startup intentionally fails closed if auth or the database is missing. Run the tests with `python -m pytest -q`. The test suite verifies JWT handling, tenant-scope setup, Shopify signature checks, event field mapping, encryption, and local analytics. It does not replace a real Supabase/Shopify integration test.
