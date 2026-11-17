# Security model and limitations

## Authentication

Cloud-demo mode requires Supabase Auth access tokens on workspace and analysis APIs. The backend verifies JWT signature against the project's JWKS, issuer, audience, expiry, user UUID, and `authenticated` role. Tokens remain in browser `sessionStorage` and are sent as bearer headers; they are not stored in cookies or server logs. The public Supabase key is not a secret. The service database URL and Shopify client secret are server-only secrets.

## Tenant isolation

Every tenant-owned table uses PostgreSQL Row Level Security. The server verifies the selected tenant membership, starts a transaction as the non-bypass `authenticated` database role, and installs the verified JWT claims for Supabase's `auth.uid()` policies. Tenant data is keyed by `tenant_id`; workspace creation and Shopify token/webhook operations use server-only privileged connections and derive tenant IDs from verified users or signed provider events, never from webhook payloads.

`supabase/migrations/202611090001_multitenant_shopify.sql` revokes anonymous access, grants only the required authenticated reads and investigation writes, and leaves Shopify token, OAuth-state, and webhook-receipt tables unavailable to browser roles.

## Shopify data handling

- OAuth uses a random, short-lived, one-time state value bound to the authenticated user, workspace, and validated `*.myshopify.com` domain. Callback parameters are HMAC-verified.
- Webhooks are verified against the raw body with Shopify HMAC and deduplicated by provider event ID.
- Offline access tokens are encrypted at rest using `SHOPIFY_TOKEN_ENCRYPTION_KEY`; never log or return them.
- Order ingestion stores only order ID/date, subtotal, currency, product type, quantity, source/channel, and discount rate. Customer PII is not stored. Return labels, device, delivery time, and marketing spend remain unavailable.
- Uninstall events delete the workspace's imported orders, investigations, metadata, and token while retaining only a disconnected shop mapping so a later shop-redaction event can be processed. Shop-redaction deletes that mapping, related webhook receipts and OAuth states, and imported data. Customer privacy events are acknowledged because this connector does not retain customer records.

## Residual risks

This is not a security certification or production-readiness claim. There is no independent penetration test, external secret manager, formal backup/restore test, multi-region design, incident response, abuse/rate-limit policy, or public Shopify app review. The free host and database have no production SLA. Do not expose it to sensitive or real customer workloads. Before production use, obtain a Shopify test store, run end-to-end authorization/webhook tests, review provider terms and app requirements, add managed backups/alerts and rate limits, and commission an independent security review.
