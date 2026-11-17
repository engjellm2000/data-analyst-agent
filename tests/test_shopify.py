import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet
import pytest

from app.shopify import (
    decrypt_token,
    encrypt_token,
    normalize_shopify_order,
    valid_shop_domain,
    verify_oauth_hmac,
    verify_webhook_hmac,
)


def test_shop_domain_validation_is_anchored():
    assert valid_shop_domain("sample-shop.myshopify.com")
    assert not valid_shop_domain("sample-shop.myshopify.com.attacker.test")
    assert not valid_shop_domain("https://sample-shop.myshopify.com")


def test_shopify_oauth_hmac_verifies_sorted_query_and_rejects_tampering():
    secret = "local-test-secret"
    query = {"shop": "sample-shop.myshopify.com", "code": "one-time-code", "state": "random-state"}
    message = urlencode(sorted(query.items()), quote_via=quote, safe="~")
    query["hmac"] = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

    assert verify_oauth_hmac(query, secret)
    assert not verify_oauth_hmac(query, "")
    query["shop"] = "other-shop.myshopify.com"
    assert not verify_oauth_hmac(query, secret)


def test_webhook_hmac_checks_raw_payload_bytes():
    body = json.dumps({"id": 123, "total_price": "10.00"}).encode()
    secret = "webhook-secret"
    signature = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()

    assert verify_webhook_hmac(body, signature, secret)
    assert not verify_webhook_hmac(body, signature, "")
    assert not verify_webhook_hmac(body + b" ", signature, secret)
    assert not verify_webhook_hmac(body, "", secret)


def test_shopify_order_mapping_omits_customer_data_and_keeps_unknowns_null():
    order = normalize_shopify_order({
        "id": 1001,
        "created_at": "2026-11-08T12:30:00Z",
        "source_name": "web",
        "currency": "cad",
        "current_subtotal_price": "42.50",
        "subtotal_price": "50.00",
        "total_discounts": "7.50",
        "line_items": [
            {"quantity": 2, "product_type": "Kitchen"},
            {"quantity": 1, "product_type": "Kitchen"},
        ],
        "customer": {"id": 77, "email": "not-stored@example.test"},
    })

    assert order["order_id"] == "1001"
    assert order["order_date"] == datetime(2026, 11, 8, tzinfo=timezone.utc).date()
    assert order["net_revenue"] == 42.5
    assert order["discount_rate"] == 0.130435
    assert order["currency"] == "CAD"
    assert order["units"] == 3
    assert order["category"] == "Kitchen"
    assert order["returned"] is None
    assert order["delivery_days"] is None
    assert order["customer_id"] is None
    assert "email" not in order


def test_shopify_token_is_encrypted_at_rest(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("SHOPIFY_TOKEN_ENCRYPTION_KEY", key)
    ciphertext = encrypt_token("shpat-example-secret")

    assert ciphertext != "shpat-example-secret"
    assert decrypt_token(ciphertext) == "shpat-example-secret"


@pytest.mark.parametrize(
    ("subtotal", "currency"),
    [("NaN", "USD"), ("Infinity", "USD"), ("10.00", "US")],
)
def test_shopify_order_rejects_invalid_money_values(subtotal, currency):
    with pytest.raises(ValueError):
        normalize_shopify_order({
            "id": 1002,
            "created_at": "2026-11-08T12:30:00Z",
            "currency": currency,
            "current_subtotal_price": subtotal,
            "line_items": [],
        })
