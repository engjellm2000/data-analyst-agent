"""Supabase access-token verification and tenant request context."""
from __future__ import annotations

from dataclasses import dataclass
import os
from functools import lru_cache
from typing import Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient, PyJWTError


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tenant_id: str
    claims: dict[str, Any]


def cloud_mode() -> bool:
    return os.environ.get("APP_ENV", "local").lower() == "cloud-demo"


@lru_cache(maxsize=4)
def _jwks_client(supabase_url: str) -> PyJWKClient:
    return PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_jwk_set=True)


def verify_access_token(token: str) -> dict[str, Any]:
    supabase_url = os.environ.get("SUPABASE_URL")
    if not supabase_url:
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    try:
        key = _jwks_client(supabase_url).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=f"{supabase_url.rstrip('/')}/auth/v1",
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        if claims.get("role") != "authenticated":
            raise HTTPException(status_code=401, detail="A user access token is required.")
        UUID(claims["sub"])
        return claims
    except (PyJWTError, ValueError, KeyError) as error:
        raise HTTPException(status_code=401, detail="Invalid or expired access token.") from error


async def require_user(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    if not cloud_mode():
        return None
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return verify_access_token(authorization[7:].strip())


async def require_tenant(
    claims: dict[str, Any] | None = Depends(require_user),
    tenant_header: str | None = Header(default=None, alias="X-Tenant-ID"),
) -> AuthContext | None:
    if not cloud_mode():
        return None
    if claims is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if not tenant_header:
        raise HTTPException(status_code=400, detail="Select a workspace before accessing its data.")
    try:
        tenant_id = str(UUID(tenant_header))
        user_id = str(UUID(claims["sub"]))
    except (ValueError, KeyError) as error:
        raise HTTPException(status_code=400, detail="Invalid user or workspace identifier.") from error
    from app.db import connect

    try:
        with connect(user_id=user_id, tenant_id=tenant_id, jwt_claims=claims) as connection:
            membership = connection.execute(
                "SELECT 1 FROM tenant_memberships WHERE user_id = ? AND tenant_id = ? LIMIT 1",
                [user_id, tenant_id],
            ).fetchone()
    except PermissionError as error:
        raise HTTPException(status_code=403, detail="You are not a member of this workspace.") from error
    if membership is None:
        raise HTTPException(status_code=403, detail="You are not a member of this workspace.")
    return AuthContext(user_id=user_id, tenant_id=tenant_id, claims=claims)


def tenant_database_kwargs(context: AuthContext | None) -> dict[str, Any]:
    if context is None:
        return {}
    return {
        "user_id": context.user_id,
        "tenant_id": context.tenant_id,
        "jwt_claims": {
            key: context.claims[key]
            for key in ("sub", "role", "aud", "iss", "exp", "iat")
            if key in context.claims
        },
    }
