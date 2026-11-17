import asyncio
import base64
import hashlib
import hmac
from types import SimpleNamespace
from urllib.parse import quote, urlencode

from fastapi import HTTPException
from starlette.requests import Request

import app.main as main
from app.auth import AuthContext


class FakeConnection:
    def __init__(self, handler):
        self.handler = handler

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, query, parameters=None):
        return self.handler(query, parameters)


def _request(path: str, query: dict[str, str] | None = None, headers: list[tuple[bytes, bytes]] | None = None, body: bytes = b"") -> Request:
    scope = {
        "type": "http",
        "method": "GET" if path.endswith("callback") else "POST",
        "path": path,
        "query_string": urlencode(query or {}).encode(),
        "headers": headers or [],
        "scheme": "https",
        "server": ("example.test", 443),
        "client": ("127.0.0.1", 1234),
        "http_version": "1.1",
    }

    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


def test_metrics_requires_exact_bearer_token(monkeypatch):
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "test-token")

    try:
        main.metrics("Bearer wrong")
    except HTTPException as error:
        assert error.status_code == 401
    else:
        raise AssertionError("Invalid metrics token was accepted.")

    response = main.metrics("Bearer test-token")
    assert response.status_code == 200
    assert b"bi_agent_http_requests_total" in response.body


def test_shopify_callback_uses_one_time_state_without_request_tenant(monkeypatch):
    async def run():
        secret = "shopify-secret"
        monkeypatch.setattr(main, "cloud_mode", lambda: True)
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", secret)
        monkeypatch.setattr(main, "exchange_code", lambda *_: _token_result())
        monkeypatch.setattr(main, "encrypt_token", lambda token: f"encrypted:{token}")
        monkeypatch.setattr(main, "subscribe_webhooks", lambda *_: _completed())

        def handle(query, _parameters):
            if "DELETE FROM shopify_oauth_states" in query:
                return SimpleNamespace(fetchone=lambda: ("tenant-id", "user-id"))
            if "INSERT INTO shopify_stores" in query:
                return SimpleNamespace(fetchone=lambda: ("tenant-id",))
            return SimpleNamespace(fetchone=lambda: None)

        monkeypatch.setattr(main, "connect", lambda **_: FakeConnection(handle))
        params = {
            "shop": "sample-shop.myshopify.com",
            "code": "one-time-code",
            "state": "opaque-state",
            "timestamp": "1794240000",
        }
        signed = urlencode(sorted(params.items()), quote_via=quote, safe="~")
        params["hmac"] = hmac.new(secret.encode(), signed.encode(), hashlib.sha256).hexdigest()

        response = await main.shopify_oauth_callback(_request("/api/shopify/callback", params))

        assert response.status_code == 303
        assert response.headers["location"] == "/?shopify=connected"

    asyncio.run(run())


async def _token_result():
    return {"access_token": "temporary-token", "scope": "read_orders,read_products"}


async def _completed():
    return None


def test_shopify_install_rejects_reusing_a_workspace_or_store(monkeypatch):
    monkeypatch.setattr(main, "cloud_mode", lambda: True)
    monkeypatch.setattr(main, "_require_tenant_owner", lambda _tenant: None)
    for key, value in {
        "SHOPIFY_CLIENT_ID": "client",
        "SHOPIFY_CLIENT_SECRET": "secret",
        "SHOPIFY_REDIRECT_URI": "https://example.test/api/shopify/callback",
        "SHOPIFY_WEBHOOK_BASE_URL": "https://example.test",
        "SHOPIFY_TOKEN_ENCRYPTION_KEY": "configured",
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(
        main,
        "connect",
        lambda **_: FakeConnection(
            lambda *_: SimpleNamespace(fetchone=lambda: ("tenant-id", "other-shop.myshopify.com"))
        ),
    )
    tenant = AuthContext(
        user_id="user-id",
        tenant_id="tenant-id",
        claims={"sub": "user-id"},
    )

    try:
        main.start_shopify_install(main.ShopifyInstallRequest(shop="new-shop.myshopify.com"), tenant)
    except HTTPException as error:
        assert error.status_code == 409
    else:
        raise AssertionError("A workspace was allowed to connect a second Shopify store.")


def test_shopify_webhook_duplicate_is_idempotent(monkeypatch):
    async def run():
        body = b'{"id":123}'
        secret = "shopify-secret"
        signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        monkeypatch.setattr(main, "cloud_mode", lambda: True)
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", secret)
        queries = []

        def handle(query, _parameters):
            queries.append(query)
            if "SELECT tenant_id FROM shopify_stores" in query:
                return SimpleNamespace(fetchone=lambda: ("tenant-id",))
            if "INSERT INTO shopify_webhook_receipts" in query:
                return SimpleNamespace(fetchone=lambda: None)
            return SimpleNamespace(fetchone=lambda: None)

        monkeypatch.setattr(main, "connect", lambda **_: FakeConnection(handle))
        request = _request(
            "/api/shopify/webhooks",
            headers=[
                (b"x-shopify-hmac-sha256", signature.encode()),
                (b"x-shopify-shop-domain", b"sample-shop.myshopify.com"),
                (b"x-shopify-topic", b"orders/create"),
                (b"x-shopify-webhook-id", b"event-id"),
                (b"content-length", str(len(body)).encode()),
            ],
            body=body,
        )

        assert await main.receive_shopify_webhook(request) == {"status": "duplicate"}
        assert not any("INSERT INTO orders" in query for query in queries)

    asyncio.run(run())


def test_shop_redaction_deletes_shop_mapping_and_receipts(monkeypatch):
    async def run():
        body = b'{"shop_id":123}'
        secret = "shopify-secret"
        signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
        monkeypatch.setattr(main, "cloud_mode", lambda: True)
        monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", secret)
        queries = []

        def handle(query, _parameters):
            queries.append(query)
            if "SELECT tenant_id FROM shopify_stores" in query:
                return SimpleNamespace(fetchone=lambda: ("tenant-id",))
            if "INSERT INTO shopify_webhook_receipts" in query:
                return SimpleNamespace(fetchone=lambda: ("event-id",))
            return SimpleNamespace(fetchone=lambda: None)

        monkeypatch.setattr(main, "connect", lambda **_: FakeConnection(handle))
        request = _request(
            "/api/shopify/webhooks",
            headers=[
                (b"x-shopify-hmac-sha256", signature.encode()),
                (b"x-shopify-shop-domain", b"sample-shop.myshopify.com"),
                (b"x-shopify-topic", b"shop/redact"),
                (b"x-shopify-webhook-id", b"event-id"),
                (b"content-length", str(len(body)).encode()),
            ],
            body=body,
        )

        assert await main.receive_shopify_webhook(request) == {"status": "processed"}
        assert any("DELETE FROM shopify_stores" in query for query in queries)
        assert any("DELETE FROM shopify_webhook_receipts" in query for query in queries)

    asyncio.run(run())
