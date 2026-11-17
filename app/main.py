from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode
from urllib.parse import urlsplit, urlunsplit
import uuid

import duckdb
import httpx
import psycopg
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, Field
import sentry_sdk

from app.analytics import ALLOWED_WINDOWS, investigate
from app.auth import AuthContext, cloud_mode, require_tenant, require_user, tenant_database_kwargs
from app.db import connect, json_parameter
from app.seed import initialize_database
from app.shopify import (
    decrypt_token,
    encrypt_token,
    exchange_code,
    fetch_recent_orders,
    normalize_shopify_order,
    subscribe_webhooks,
    valid_shop_domain,
    verify_oauth_hmac,
    verify_webhook_hmac,
)
from evals.run_evals import run as run_evals


app = FastAPI(title="Business Intelligence Agent", version="1.0.0")
STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger("bi_agent")
REQUESTS = Counter("bi_agent_http_requests_total", "HTTP requests", ("method", "route", "status"))
REQUEST_DURATION = Histogram("bi_agent_http_request_duration_seconds", "HTTP request duration", ("method", "route"))


def _redact_sentry_event(event, hint):
    request_data = event.get("request")
    if request_data:
        request_data.pop("data", None)
        request_data.pop("cookies", None)
        request_data["headers"] = {}
        request_data["query_string"] = ""
        if request_data.get("url"):
            parsed_url = urlsplit(request_data["url"])
            request_data["url"] = urlunsplit((parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", ""))
    return event


if os.environ.get("SENTRY_DSN"):
    sentry_sdk.init(
        dsn=os.environ["SENTRY_DSN"],
        environment=os.environ.get("APP_ENV", "local"),
        send_default_pii=False,
        traces_sample_rate=0,
        before_send=_redact_sentry_event,
    )


@app.middleware("http")
async def assign_request_id(request: Request, call_next):
    request.state.request_id = str(uuid.uuid4())
    return await call_next(request)


@app.middleware("http")
async def observe_requests(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        supabase_origin = os.environ.get("SUPABASE_URL", "")
        connect_sources = f"'self' {supabase_origin}" if supabase_origin else "'self'"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            f"connect-src {connect_sources}; "
            "img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        return response
    finally:
        duration = time.perf_counter() - started
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        method = request.method
        REQUESTS.labels(method, route_path, str(status_code)).inc()
        REQUEST_DURATION.labels(method, route_path).observe(duration)
        logger.info(json.dumps({
            "event": "http_request",
            "request_id": request.state.request_id,
            "method": method,
            "route": route_path,
            "status_code": status_code,
            "duration_ms": round(duration * 1000, 1),
        }))


class InvestigationRequest(BaseModel):
    window_days: int = Field(default=30, description="Current comparison window in days")


class TenantRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class ShopifyInstallRequest(BaseModel):
    shop: str = Field(min_length=1, max_length=255)


def _validate_window(window_days: int) -> None:
    if window_days not in ALLOWED_WINDOWS:
        raise HTTPException(status_code=422, detail=f"window_days must be one of {ALLOWED_WINDOWS}")
    if cloud_mode() and window_days > 30:
        raise HTTPException(status_code=422, detail="Shopify sync currently supplies 60 days of history; select a 7-, 14-, or 30-day window.")


@app.on_event("startup")
def ensure_database() -> None:
    if cloud_mode():
        required = ("SUPABASE_URL", "SUPABASE_ANON_KEY", "BI_AGENT_DATABASE_URL")
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise RuntimeError(f"Missing required cloud-demo configuration: {', '.join(missing)}")
        with connect(privileged=True) as connection:
            connection.execute("SELECT 1 FROM tenant_memberships LIMIT 1")
        return
    initialize_database()


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def home() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
def public_config() -> dict:
    return {
        "auth_enabled": cloud_mode(),
        "supabase_url": os.environ.get("SUPABASE_URL") if cloud_mode() else None,
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY") if cloud_mode() else None,
        "shopify_enabled": bool(os.environ.get("SHOPIFY_CLIENT_ID") and os.environ.get("SHOPIFY_CLIENT_SECRET")),
    }


@app.get("/api/tenants")
def list_tenants(claims: dict | None = Depends(require_user)) -> dict:
    if not cloud_mode():
        return {"tenants": []}
    user_id = claims["sub"]
    with connect(privileged=True) as connection:
        rows = connection.execute(
            """
            SELECT t.tenant_id, t.name, m.role
            FROM tenants t
            JOIN tenant_memberships m ON m.tenant_id = t.tenant_id
            WHERE m.user_id = ?
            ORDER BY t.created_at
            """,
            [user_id],
        ).fetchall()
    return {"tenants": [{"tenant_id": str(row[0]), "name": row[1], "role": row[2]} for row in rows]}


@app.post("/api/tenants", status_code=201)
def create_tenant(payload: TenantRequest, claims: dict | None = Depends(require_user)) -> dict:
    if not cloud_mode():
        raise HTTPException(status_code=404, detail="Workspaces are available in cloud-demo mode only.")
    name = payload.name
    if not name.strip():
        raise HTTPException(status_code=422, detail="Workspace name must be 1 to 120 characters.")
    user_id = claims["sub"]
    with connect(privileged=True) as connection:
        row = connection.execute(
            "INSERT INTO tenants (name) VALUES (?) RETURNING tenant_id",
            [name.strip()],
        ).fetchone()
        tenant_id = str(row[0])
        connection.execute(
            "INSERT INTO tenant_memberships (tenant_id, user_id, role) VALUES (?, ?, 'owner')",
            [tenant_id, user_id],
        )
    return {"tenant_id": tenant_id, "name": name.strip(), "role": "owner"}


@app.get("/api/dashboard")
def dashboard(
    window_days: int = Query(default=30, ge=7, le=90),
    tenant: AuthContext | None = Depends(require_tenant),
) -> dict:
    _validate_window(window_days)
    with connect(**tenant_database_kwargs(tenant)) as connection:
        count, start_date, end_date = connection.execute(
            "SELECT COUNT(*), MIN(order_date), MAX(order_date) FROM orders"
        ).fetchone()
        metadata_row = connection.execute(
            "SELECT metadata_json FROM dataset_metadata"
            + (" WHERE tenant_id = ?" if cloud_mode() else "")
            + " LIMIT 1",
            [tenant.tenant_id] if cloud_mode() else None,
        ).fetchone()
        metadata = _decode_json(metadata_row[0]) if metadata_row else {
            "label": "Unknown dataset",
            "source": "Dataset metadata is not available.",
            "quality": {},
            "limitations": ["Dataset provenance could not be verified."],
        }
        latest = connection.execute(
            """
            SELECT investigation_id, run_at, result_json
            FROM investigations
            WHERE window_days = ?
            """ + (" AND tenant_id = ?" if cloud_mode() else "") + """
            ORDER BY run_at DESC
            LIMIT 1
            """,
            [window_days, tenant.tenant_id] if cloud_mode() else [window_days],
        ).fetchone()
        latest_result = _decode_json(latest[2]) if latest else None
        # Do not render a saved run whose comparison period no longer matches
        # the available dataset. The browser will request a fresh run instead.
        if latest_result and latest_result.get("current_end") != end_date.isoformat():
            latest_result = None
        if latest_result:
            latest_result["investigation_id"] = str(latest[0])
            latest_result["run_at"] = latest[1].isoformat()
        dataset = {
            **metadata,
            "orders": int(count),
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
        }
        return {"dataset": dataset, "investigation": latest_result}


@app.get("/api/investigations")
def list_investigations(
    limit: int = Query(default=20, ge=1, le=100),
    tenant: AuthContext | None = Depends(require_tenant),
) -> dict:
    with connect(**tenant_database_kwargs(tenant)) as connection:
        rows = connection.execute(
            """
            SELECT investigation_id, run_at, window_days, result_json
            FROM investigations
            """ + ("WHERE tenant_id = ? " if cloud_mode() else "") + """
            ORDER BY run_at DESC
            LIMIT ?
            """,
            [tenant.tenant_id, limit] if cloud_mode() else [limit],
        ).fetchall()
    items = []
    for row in rows:
        result = _decode_json(row[3])
        items.append({
            "investigation_id": str(row[0]),
            "run_at": row[1].isoformat(),
            "window_days": int(row[2]),
            "current_start": result.get("current_start"),
            "current_end": result.get("current_end"),
            "finding_count": len(result.get("findings", [])),
        })
    return {
        "investigations": items,
    }


@app.post("/api/investigations", status_code=201)
def run_investigation(
    request: InvestigationRequest,
    tenant: AuthContext | None = Depends(require_tenant),
) -> dict:
    _validate_window(request.window_days)
    started = time.perf_counter()
    with connect(**tenant_database_kwargs(tenant)) as connection:
        if not connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0]:
            raise HTTPException(status_code=409, detail="No orders are available. Connect a data source first.")
        result = investigate(connection, window_days=request.window_days)
        investigation_id = str(uuid.uuid4())
        run_at = datetime.now(timezone.utc)
        connection.execute(
            (
                "INSERT INTO investigations (tenant_id, investigation_id, run_at, window_days, result_json) VALUES (?, ?, ?, ?, ?::jsonb)"
                if cloud_mode()
                else "INSERT INTO investigations VALUES (?, ?, ?, ?)"
            ),
            (
                [tenant.tenant_id, investigation_id, run_at, request.window_days, json_parameter(result)]
                if cloud_mode()
                else [investigation_id, run_at, request.window_days, json.dumps(result)]
            ),
        )
        logger.info(
            "Investigation completed id=%s window_days=%d findings=%d duration_ms=%.1f",
            investigation_id,
            request.window_days,
            len(result["findings"]),
            (time.perf_counter() - started) * 1000,
        )
        return {
            "investigation_id": investigation_id,
            "run_at": run_at.isoformat(),
            **result,
        }


@app.get("/api/investigations/{investigation_id}")
def get_investigation(
    investigation_id: str,
    tenant: AuthContext | None = Depends(require_tenant),
) -> dict:
    with connect(**tenant_database_kwargs(tenant)) as connection:
        row = connection.execute(
            """
            SELECT investigation_id, run_at, result_json
            FROM investigations
            WHERE investigation_id = ?
            """ + (" AND tenant_id = ?" if cloud_mode() else "") + """
            """,
            [investigation_id, tenant.tenant_id] if cloud_mode() else [investigation_id],
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return {
        "investigation_id": row[0],
        "run_at": row[1].isoformat(),
        **_decode_json(row[2]),
    }


@app.post("/api/shopify/install")
def start_shopify_install(
    payload: ShopifyInstallRequest,
    tenant: AuthContext | None = Depends(require_tenant),
) -> dict:
    if not cloud_mode():
        raise HTTPException(status_code=404, detail="Shopify integration is available in cloud-demo mode only.")
    _require_tenant_owner(tenant)
    required = (
        "SHOPIFY_CLIENT_ID",
        "SHOPIFY_CLIENT_SECRET",
        "SHOPIFY_REDIRECT_URI",
        "SHOPIFY_WEBHOOK_BASE_URL",
        "SHOPIFY_TOKEN_ENCRYPTION_KEY",
    )
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise HTTPException(status_code=503, detail=f"Shopify integration is not configured: {', '.join(missing)}")
    shop = payload.shop.strip().lower()
    if not valid_shop_domain(shop):
        raise HTTPException(status_code=422, detail="Enter a valid *.myshopify.com shop domain.")
    with connect(privileged=True) as connection:
        existing = connection.execute(
            "SELECT tenant_id, shop_domain FROM shopify_stores WHERE tenant_id = ? OR shop_domain = ?",
            [tenant.tenant_id, shop],
        ).fetchone()
    if existing and (str(existing[0]) != tenant.tenant_id or existing[1] != shop):
        raise HTTPException(status_code=409, detail="A workspace can connect one Shopify store, and a store can belong to one workspace.")
    state = secrets.token_urlsafe(32)
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    scopes = os.environ.get("SHOPIFY_SCOPES", "read_orders,read_products")
    with connect(privileged=True) as connection:
        connection.execute("DELETE FROM shopify_oauth_states WHERE expires_at <= now()")
        connection.execute(
            """
            INSERT INTO shopify_oauth_states (state_hash, tenant_id, user_id, shop_domain, expires_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [state_hash, tenant.tenant_id, tenant.user_id, shop, datetime.now(timezone.utc) + timedelta(minutes=10)],
        )
    authorization_url = f"https://{shop}/admin/oauth/authorize?" + urlencode({
        "client_id": os.environ["SHOPIFY_CLIENT_ID"],
        "scope": scopes,
        "redirect_uri": os.environ["SHOPIFY_REDIRECT_URI"],
        "state": state,
    })
    return {"authorization_url": authorization_url}


@app.get("/api/shopify/callback", include_in_schema=False)
async def shopify_oauth_callback(request: Request):
    if not cloud_mode():
        raise HTTPException(status_code=404, detail="Shopify integration is unavailable.")
    query_items = list(request.query_params.multi_items())
    query = dict(query_items)
    if len(query_items) != len(query):
        raise HTTPException(status_code=401, detail="Shopify authorization could not be verified.")
    shop = query.get("shop", "").lower()
    state = query.get("state", "")
    code = query.get("code", "")
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
    if not valid_shop_domain(shop) or not code or not state or not verify_oauth_hmac(query, secret):
        raise HTTPException(status_code=401, detail="Shopify authorization could not be verified.")
    state_hash = hashlib.sha256(state.encode()).hexdigest()
    with connect(privileged=True) as connection:
        state_row = connection.execute(
            """
            DELETE FROM shopify_oauth_states
            WHERE state_hash = ? AND shop_domain = ? AND expires_at > now()
            RETURNING tenant_id, user_id
            """,
            [state_hash, shop],
        ).fetchone()
    if state_row is None:
        raise HTTPException(status_code=401, detail="Shopify authorization state expired or was already used.")
    tenant_id, user_id = str(state_row[0]), str(state_row[1])
    try:
        token_data = await exchange_code(shop, code)
    except (httpx.HTTPError, ValueError, KeyError) as error:
        logger.error("Shopify token exchange failed shop=%s error=%s", shop, type(error).__name__)
        raise HTTPException(status_code=502, detail="Shopify token exchange failed; restart the connection flow.") from error
    encrypted_token = encrypt_token(token_data["access_token"])
    try:
        with connect(privileged=True) as connection:
            store = connection.execute(
                """
                INSERT INTO shopify_stores (tenant_id, shop_domain, status, scopes)
                VALUES (?, ?, 'connected', ?)
                ON CONFLICT (shop_domain) DO UPDATE
                  SET status = 'connected', scopes = EXCLUDED.scopes, installed_at = now()
                  WHERE shopify_stores.tenant_id = EXCLUDED.tenant_id
                RETURNING tenant_id
                """,
                [tenant_id, shop, token_data["scope"]],
            ).fetchone()
            if store is None:
                raise HTTPException(status_code=409, detail="This Shopify store is already connected to another workspace.")
            connection.execute(
                """
                INSERT INTO shopify_tokens (tenant_id, shop_domain, encrypted_access_token)
                VALUES (?, ?, ?)
                ON CONFLICT (tenant_id, shop_domain) DO UPDATE
                  SET encrypted_access_token = EXCLUDED.encrypted_access_token, updated_at = now()
                """,
                [tenant_id, shop, encrypted_token],
            )
    except psycopg.errors.UniqueViolation as error:
        raise HTTPException(status_code=409, detail="This workspace already has a Shopify store connected.") from error
    try:
        await subscribe_webhooks(shop, token_data["access_token"])
    except (httpx.HTTPError, ValueError, RuntimeError) as error:
        logger.error("Shopify webhook setup failed shop=%s error=%s", shop, type(error).__name__)
        raise HTTPException(status_code=502, detail="Store connected, but webhook setup failed. Retry after checking app configuration.") from error
    logger.info("Shopify store connected tenant=%s shop=%s user=%s", tenant_id, shop, user_id)
    return RedirectResponse(url="/?shopify=connected", status_code=303)


def _shopify_store_for_tenant(tenant: AuthContext) -> tuple[str, str]:
    with connect(**tenant_database_kwargs(tenant)) as connection:
        store = connection.execute(
            "SELECT shop_domain, currency FROM shopify_stores WHERE tenant_id = ? AND status = 'connected' LIMIT 1",
            [tenant.tenant_id],
        ).fetchone()
    if store is None:
        raise HTTPException(status_code=404, detail="Connect a Shopify store first.")
    with connect(privileged=True) as connection:
        token_row = connection.execute(
            "SELECT encrypted_access_token FROM shopify_tokens WHERE tenant_id = ? AND shop_domain = ?",
            [tenant.tenant_id, store[0]],
        ).fetchone()
    if token_row is None:
        raise HTTPException(status_code=409, detail="Shopify access token is unavailable; reconnect the store.")
    return store[0], decrypt_token(token_row[0])


def _require_tenant_owner(tenant: AuthContext) -> None:
    with connect(**tenant_database_kwargs(tenant)) as connection:
        row = connection.execute(
            "SELECT role FROM tenant_memberships WHERE user_id = ? AND tenant_id = ?",
            [tenant.user_id, tenant.tenant_id],
        ).fetchone()
    if row is None or row[0] != "owner":
        raise HTTPException(status_code=403, detail="Only workspace owners can manage Shopify connections.")


def _save_shopify_order(connection, tenant_id: str, shop: str, order: dict) -> bool:
    if order["cancelled"]:
        connection.execute("DELETE FROM orders WHERE tenant_id = ? AND order_id = ?", [tenant_id, order["order_id"]])
        return False
    store = connection.execute(
        "SELECT currency FROM shopify_stores WHERE tenant_id = ? AND shop_domain = ?",
        [tenant_id, shop],
    ).fetchone()
    if store is None:
        raise ValueError("Shopify store is no longer connected to this workspace.")
    existing_currency = store[0]
    if existing_currency and existing_currency != order["currency"]:
        raise ValueError("Orders with multiple currencies are not supported in one workspace.")
    if not existing_currency:
        connection.execute(
            "UPDATE shopify_stores SET currency = ? WHERE tenant_id = ? AND shop_domain = ?",
            [order["currency"], tenant_id, shop],
        )
    connection.execute(
        """
        INSERT INTO orders (
            tenant_id, order_id, order_date, channel, category, device, region, warehouse,
            units, net_revenue, discount_rate, delivery_days, returned, marketing_spend,
            customer_id, currency
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (tenant_id, order_id) DO UPDATE SET
            order_date = EXCLUDED.order_date,
            channel = EXCLUDED.channel,
            category = EXCLUDED.category,
            units = EXCLUDED.units,
            net_revenue = EXCLUDED.net_revenue,
            discount_rate = EXCLUDED.discount_rate,
            currency = EXCLUDED.currency,
            updated_at = now()
        """,
        [
            tenant_id, order["order_id"], order["order_date"], order["channel"], order["category"],
            order["device"], order["region"], order["warehouse"], order["units"], order["net_revenue"],
            order["discount_rate"], order["delivery_days"], order["returned"], order["marketing_spend"],
            order["customer_id"], order["currency"],
        ],
    )
    return True


def _update_shopify_metadata(connection, tenant_id: str, currency: str | None, order_count: int) -> None:
    metadata = {
        "label": "Shopify store",
        "source": "Live Shopify Admin API and signed webhooks; order-level fields only.",
        "currency": currency,
        "quality": {"included_orders": order_count, "max_orders_per_sync": 1000},
        "supported_metrics": ["order count", "item subtotal after discounts, before tax and shipping", "average order value", "sales channel", "product type", "discount rate"],
        "unsupported_metrics": ["returns", "device", "delivery time", "marketing spend"],
        "limitations": [
            "Revenue uses Shopify current subtotal and excludes shipping and tax.",
            "Only one currency per workspace is supported.",
            "Returns, device, delivery time, and marketing spend are not inferred.",
            "The connector has no historic backfill beyond the recent API sync window.",
            "Each manual sync is capped at the 1,000 most recent matching orders.",
        ],
    }
    connection.execute(
        """
        INSERT INTO dataset_metadata (tenant_id, metadata_json)
        VALUES (?, ?::jsonb)
        ON CONFLICT (tenant_id) DO UPDATE
          SET metadata_json = EXCLUDED.metadata_json, updated_at = now()
        """,
        [tenant_id, json_parameter(metadata)],
    )


@app.get("/api/shopify/status")
def shopify_status(tenant: AuthContext | None = Depends(require_tenant)) -> dict:
    if not cloud_mode():
        return {"connected": False}
    with connect(**tenant_database_kwargs(tenant)) as connection:
        row = connection.execute(
            "SELECT shop_domain, currency, last_webhook_at FROM shopify_stores WHERE tenant_id = ? AND status = 'connected' LIMIT 1",
            [tenant.tenant_id],
        ).fetchone()
    return {
        "connected": row is not None,
        "shop": row[0] if row else None,
        "currency": row[1] if row else None,
        "last_webhook_at": row[2].isoformat() if row and row[2] else None,
    }


@app.post("/api/shopify/sync")
async def sync_shopify_orders(tenant: AuthContext | None = Depends(require_tenant)) -> dict:
    if not cloud_mode():
        raise HTTPException(status_code=404, detail="Shopify integration is unavailable.")
    shop, token = _shopify_store_for_tenant(tenant)
    try:
        source_orders = await fetch_recent_orders(shop, token)
        normalized = [normalize_shopify_order(order) for order in source_orders]
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
        logger.error("Shopify sync failed tenant=%s error=%s", tenant.tenant_id, type(error).__name__)
        raise HTTPException(status_code=502, detail="Shopify sync failed; check the store API access and retry.") from error
    if len({order["currency"] for order in normalized}) > 1:
        raise HTTPException(status_code=422, detail="The selected Shopify period contains multiple currencies.")
    if normalized:
        with connect(privileged=True) as connection:
            store = connection.execute(
                "SELECT currency FROM shopify_stores WHERE tenant_id = ? AND shop_domain = ?",
                [tenant.tenant_id, shop],
            ).fetchone()
        if store and store[0] and store[0] != normalized[0]["currency"]:
            raise HTTPException(status_code=422, detail="The Shopify store currency changed; mixed-currency data is not supported.")
    with connect(privileged=True) as connection:
        written = sum(_save_shopify_order(connection, tenant.tenant_id, shop, order) for order in normalized)
        currency = next(iter({order["currency"] for order in normalized}), None)
        count = connection.execute("SELECT COUNT(*) FROM orders WHERE tenant_id = ?", [tenant.tenant_id]).fetchone()[0]
        _update_shopify_metadata(connection, tenant.tenant_id, currency, int(count))
    logger.info("Shopify sync completed tenant=%s shop=%s fetched=%d written=%d", tenant.tenant_id, shop, len(normalized), written)
    return {"fetched": len(normalized), "active_orders": int(count), "currency": currency}


@app.post("/api/shopify/webhooks")
async def receive_shopify_webhook(request: Request) -> dict:
    if not cloud_mode():
        raise HTTPException(status_code=404, detail="Shopify integration is unavailable.")
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
    body = await request.body()
    if not verify_webhook_hmac(body, request.headers.get("X-Shopify-Hmac-Sha256", ""), secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    shop = request.headers.get("X-Shopify-Shop-Domain", "").lower()
    topic = request.headers.get("X-Shopify-Topic", "").lower()
    event_id = request.headers.get("X-Shopify-Webhook-Id", "")
    if not valid_shop_domain(shop) or not topic or not event_id:
        raise HTTPException(status_code=400, detail="Required Shopify webhook headers are missing.")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=400, detail="Webhook body is not valid JSON.") from error

    with connect(privileged=True) as connection:
        store = connection.execute(
            "SELECT tenant_id FROM shopify_stores WHERE shop_domain = ?",
            [shop],
        ).fetchone()
        if store is None:
            if topic == "shop/redact":
                return {"status": "processed"}
            raise HTTPException(status_code=404, detail="Shopify store is not connected.")
        tenant_id = str(store[0])
        inserted = connection.execute(
            """
            INSERT INTO shopify_webhook_receipts (event_id, tenant_id, shop_domain, topic)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (event_id) DO NOTHING
            RETURNING event_id
            """,
            [event_id, tenant_id, shop, topic],
        ).fetchone()
        if inserted is None:
            return {"status": "duplicate"}
        if topic in {"app/uninstalled", "shop/redact"}:
            connection.execute("DELETE FROM orders WHERE tenant_id = ?", [tenant_id])
            connection.execute("DELETE FROM investigations WHERE tenant_id = ?", [tenant_id])
            connection.execute("DELETE FROM dataset_metadata WHERE tenant_id = ?", [tenant_id])
            connection.execute("DELETE FROM shopify_tokens WHERE tenant_id = ?", [tenant_id])
            if topic == "shop/redact":
                connection.execute("DELETE FROM shopify_oauth_states WHERE tenant_id = ?", [tenant_id])
                connection.execute("DELETE FROM shopify_webhook_receipts WHERE tenant_id = ?", [tenant_id])
                connection.execute(
                    "DELETE FROM shopify_stores WHERE tenant_id = ? AND shop_domain = ?",
                    [tenant_id, shop],
                )
            else:
                connection.execute(
                    "UPDATE shopify_stores SET status = 'disconnected', last_webhook_at = now() WHERE tenant_id = ?",
                    [tenant_id],
                )
            logger.info("Shopify data removed after privacy lifecycle event tenant=%s topic=%s", tenant_id, topic)
            return {"status": "processed"}
        if topic in {"customers/data_request", "customers/redact"}:
            return {"status": "processed"}
        if topic not in {"orders/create", "orders/updated", "orders/cancelled"}:
            raise HTTPException(status_code=400, detail="Unsupported Shopify webhook topic.")
        try:
            order = normalize_shopify_order(payload)
        except (ValueError, TypeError, KeyError) as error:
            raise HTTPException(status_code=422, detail="Shopify order payload is invalid.") from error
        try:
            _save_shopify_order(connection, tenant_id, shop, order)
        except ValueError as error:
            logger.error("Shopify webhook rejected tenant=%s error=%s", tenant_id, type(error).__name__)
            raise HTTPException(status_code=422, detail=str(error)) from error
        count = connection.execute("SELECT COUNT(*) FROM orders WHERE tenant_id = ?", [tenant_id]).fetchone()[0]
        _update_shopify_metadata(connection, tenant_id, order["currency"], int(count))
        connection.execute(
            "UPDATE shopify_stores SET last_webhook_at = now() WHERE tenant_id = ? AND shop_domain = ?",
            [tenant_id, shop],
        )
    return {"status": "processed"}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "mode": "cloud-demo" if cloud_mode() else "local"}


@app.get("/api/health/ready")
def readiness() -> dict:
    try:
        with connect(privileged=cloud_mode()) as connection:
            connection.execute("SELECT 1").fetchone()
    except (duckdb.Error, psycopg.Error, OSError) as error:
        logger.error("Readiness check failed: %s", type(error).__name__)
        raise HTTPException(status_code=503, detail="Database is unavailable.") from error
    return {"status": "ready"}


@app.get("/metrics")
def metrics(authorization: str | None = Header(default=None)) -> Response:
    expected_token = os.environ.get("METRICS_BEARER_TOKEN")
    if expected_token and not secrets.compare_digest(authorization or "", f"Bearer {expected_token}"):
        raise HTTPException(status_code=401, detail="Metrics authorization required.")
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/api/evals")
def evaluation_scoreboard() -> dict:
    result_path = Path(__file__).resolve().parent.parent / "evals" / "results" / "latest.json"
    if result_path.is_file():
        cached = json.loads(result_path.read_text(encoding="utf-8"))
        if cached.get("version") == "v0.3-fixtures":
            return cached
    return run_evals()


def _decode_json(value):
    return json.loads(value) if isinstance(value, str) else value
