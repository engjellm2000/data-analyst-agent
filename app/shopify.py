"""Shopify OAuth, webhook verification, order normalization, and API helpers."""
from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import math
import os
import re
from typing import Any
from urllib.parse import quote, urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken


SHOP_DOMAIN = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
WEBHOOK_TOPICS = (
    "ORDERS_CREATE",
    "ORDERS_UPDATED",
    "ORDERS_CANCELLED",
    "APP_UNINSTALLED",
    "CUSTOMERS_DATA_REQUEST",
    "CUSTOMERS_REDACT",
    "SHOP_REDACT",
)


def valid_shop_domain(shop: str) -> bool:
    return bool(SHOP_DOMAIN.fullmatch(shop.lower()))


def verify_oauth_hmac(query: dict[str, str], secret: str) -> bool:
    supplied = query.get("hmac", "")
    if not secret or not supplied or not re.fullmatch(r"[0-9a-fA-F]{64}", supplied):
        return False
    message = urlencode(sorted(
        (key, value) for key, value in query.items()
        if key not in {"hmac", "signature"}
    ), quote_via=quote, safe="~")
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


def verify_webhook_hmac(body: bytes, supplied: str, secret: str) -> bool:
    if not secret or not supplied:
        return False
    expected = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return hmac.compare_digest(expected, supplied)


def _fernet() -> Fernet:
    key = os.environ.get("SHOPIFY_TOKEN_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("Shopify token encryption is not configured.")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as error:
        raise RuntimeError("SHOPIFY_TOKEN_ENCRYPTION_KEY must be a URL-safe Fernet key.") from error


def encrypt_token(token: str) -> str:
    return _fernet().encrypt(token.encode()).decode()


def decrypt_token(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as error:
        raise RuntimeError("Stored Shopify token could not be decrypted.") from error


def normalize_shopify_order(order: dict[str, Any]) -> dict[str, Any]:
    order_id = order.get("id")
    created_at = order.get("created_at") or order.get("createdAt")
    if order_id is None or not created_at:
        raise ValueError("Shopify order is missing its ID or creation timestamp.")
    timestamp = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    line_items = order.get("line_items")
    if line_items is None:
        line_items = order.get("lineItems", {}).get("nodes", [])
    units = 0
    categories = set()
    for item in line_items or []:
        quantity = int(item.get("quantity") or 0)
        if quantity < 0:
            raise ValueError("Shopify order item quantity cannot be negative.")
        units += quantity
        category = item.get("product_type") or item.get("product", {}).get("productType")
        if category:
            categories.add(str(category))
    category = next(iter(categories)) if len(categories) == 1 else ("Mixed" if categories else None)

    subtotal = order.get("current_subtotal_price") or order.get("subtotal_price")
    currency = order.get("currency")
    if isinstance(subtotal, dict):
        currency = subtotal.get("currencyCode") or currency
        subtotal = subtotal.get("amount")
    if subtotal is None:
        shop_money = (
            order.get("currentSubtotalPriceSet", {})
            .get("shopMoney", {})
        )
        subtotal = shop_money.get("amount")
        currency = shop_money.get("currencyCode") or currency
    if subtotal is None or not currency:
        raise ValueError("Shopify order is missing its subtotal or currency.")
    revenue = float(subtotal)
    currency = str(currency).upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("Shopify order currency must be a three-letter ISO code.")
    if not math.isfinite(revenue) or revenue < 0:
        raise ValueError("Shopify order subtotal must be finite and non-negative.")
    gross = order.get("subtotal_price") or order.get("subtotalPriceSet", {}).get("shopMoney", {}).get("amount") or revenue
    discounts = order.get("total_discounts") or order.get("currentTotalDiscountsSet", {}).get("shopMoney", {}).get("amount") or 0
    gross = float(gross)
    discounts = float(discounts)
    if not math.isfinite(gross) or not math.isfinite(discounts) or gross < 0 or discounts < 0:
        raise ValueError("Shopify order totals must be finite and non-negative.")
    discount_rate = discounts / (gross + discounts) if gross + discounts > 0 else None

    return {
        "order_id": str(order_id),
        "order_date": timestamp.date(),
        "channel": order.get("source_name") or order.get("sourceName"),
        "category": category,
        "device": None,
        "region": None,
        "warehouse": None,
        "units": units,
        "net_revenue": round(revenue, 2),
        "discount_rate": round(discount_rate, 6) if discount_rate is not None else None,
        "delivery_days": None,
        "returned": None,
        "marketing_spend": None,
        "customer_id": None,
        "currency": currency,
        "cancelled": bool(order.get("cancelled_at") or order.get("cancelledAt")),
    }


async def exchange_code(shop: str, code: str) -> dict[str, Any]:
    client_id = os.environ["SHOPIFY_CLIENT_ID"]
    client_secret = os.environ["SHOPIFY_CLIENT_SECRET"]
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={"client_id": client_id, "client_secret": client_secret, "code": code},
        )
    response.raise_for_status()
    result = response.json()
    if not result.get("access_token") or not result.get("scope"):
        raise ValueError("Shopify OAuth response did not contain an access token and scopes.")
    return result


def _api_version() -> str:
    return os.environ.get("SHOPIFY_API_VERSION", "2026-10")


async def _graphql(shop: str, token: str, query: str, variables: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=25) as client:
        response = await client.post(
            f"https://{shop}/admin/api/{_api_version()}/graphql.json",
            headers={"X-Shopify-Access-Token": token},
            json={"query": query, "variables": variables},
        )
    response.raise_for_status()
    payload = response.json()
    if payload.get("errors"):
        raise ValueError("Shopify Admin API returned a GraphQL error.")
    return payload["data"]


async def subscribe_webhooks(shop: str, token: str) -> None:
    callback = os.environ.get("SHOPIFY_WEBHOOK_BASE_URL", "").rstrip("/") + "/api/shopify/webhooks"
    if not callback.startswith("https://"):
        raise RuntimeError("SHOPIFY_WEBHOOK_BASE_URL must be an HTTPS URL.")
    mutation = """
      mutation CreateWebhook($topic: WebhookSubscriptionTopic!, $url: URL!) {
        webhookSubscriptionCreate(
          topic: $topic,
          webhookSubscription: {callbackUrl: $url, format: JSON}
        ) {
          userErrors { field message }
        }
      }
    """
    for topic in WEBHOOK_TOPICS:
        data = await _graphql(shop, token, mutation, {"topic": topic, "url": callback})
        errors = data["webhookSubscriptionCreate"]["userErrors"]
        if errors:
            raise ValueError(f"Shopify webhook subscription failed for {topic}.")


async def fetch_recent_orders(shop: str, token: str, max_orders: int = 1000) -> list[dict[str, Any]]:
    query = """
      query RecentOrders($cursor: String, $filter: String!) {
        orders(first: 100, after: $cursor, sortKey: CREATED_AT, query: $filter) {
          nodes {
            id
            createdAt
            cancelledAt
            sourceName
            currentSubtotalPriceSet { shopMoney { amount currencyCode } }
            subtotalPriceSet { shopMoney { amount } }
            currentTotalDiscountsSet { shopMoney { amount } }
            lineItems(first: 100) {
              nodes { quantity product { productType } }
            }
          }
          pageInfo { hasNextPage endCursor }
        }
      }
    """
    filter_value = "created_at:>=-60d"
    cursor = None
    orders = []
    while len(orders) < max_orders:
        result = await _graphql(shop, token, query, {"cursor": cursor, "filter": filter_value})
        page = result["orders"]
        orders.extend(page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
        if not cursor:
            raise ValueError("Shopify pagination returned no continuation cursor.")
    return orders[:max_orders]
