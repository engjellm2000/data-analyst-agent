from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
import jwt
import pytest

import app.auth as auth
import app.db as db


def test_supabase_access_tokens_require_valid_signature_and_claims(monkeypatch):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(
        auth,
        "_jwks_client",
        lambda _: SimpleNamespace(get_signing_key_from_jwt=lambda _token: SimpleNamespace(key=public_key)),
    )
    now = int(datetime.now(timezone.utc).timestamp())
    claims = {
        "iss": "https://example.supabase.co/auth/v1",
        "aud": "authenticated",
        "sub": "feaf0e06-9d5a-4a81-91da-a6f594a1c505",
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")

    assert auth.verify_access_token(token)["sub"] == claims["sub"]

    with pytest.raises(HTTPException) as error:
        auth.verify_access_token(token + "tampered")
    assert error.value.status_code == 401


def test_cloud_database_requires_tenant_scope(monkeypatch):
    monkeypatch.setenv("BI_AGENT_DATABASE_URL", "postgresql://not-used")
    with pytest.raises(PermissionError, match="verified user and tenant"):
        db.connect()


def test_cloud_database_sets_verified_claims_before_checking_membership(monkeypatch):
    class FakeConnection:
        def __init__(self):
            self.queries = []
            self.closed = False

        def execute(self, query, parameters=None):
            self.queries.append((query, parameters))
            return SimpleNamespace(fetchone=lambda: (1,))

        def rollback(self):
            pass

        def close(self):
            self.closed = True

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.closed = True

    fake = FakeConnection()
    monkeypatch.setenv("BI_AGENT_DATABASE_URL", "postgresql://not-used")
    monkeypatch.setattr(db.psycopg, "connect", lambda *_, **__: fake)
    claims = {"sub": "user-uuid", "role": "authenticated", "aud": "authenticated"}

    with db.connect(user_id="user-uuid", tenant_id="tenant-uuid", jwt_claims=claims) as connection:
        assert connection.execute("SELECT 1").fetchone() == (1,)

    assert fake.queries[0][0] == "SET LOCAL ROLE authenticated"
    assert fake.queries[1][0].startswith("SELECT set_config('request.jwt.claims'")
    assert fake.queries[4][0].startswith("SELECT 1 FROM tenant_memberships")
    assert fake.closed


def test_cloud_database_rejects_non_member(monkeypatch):
    class FakeConnection:
        def execute(self, *_):
            return SimpleNamespace(fetchone=lambda: None)

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    fake = FakeConnection()
    monkeypatch.setenv("BI_AGENT_DATABASE_URL", "postgresql://not-used")
    monkeypatch.setattr(db.psycopg, "connect", lambda *_, **__: fake)

    with pytest.raises(PermissionError, match="not a member"):
        db.connect(user_id="user-uuid", tenant_id="other-tenant", jwt_claims={"sub": "user-uuid"})
    assert fake.closed
