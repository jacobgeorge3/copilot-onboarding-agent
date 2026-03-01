"""
auth.py — Authentication middleware for the Onboarding Agent API.

Supports two modes simultaneously for a safe, backward-compatible migration:

  Mode 1 — API Key (current connector, unchanged):
    Header: X-API-Key: <value>
    Identity: synthetic user_oid "_api_key" (global completion state)

  Mode 2 — Entra ID Bearer Token (production):
    Header: Authorization: Bearer <JWT>
    Identity: real user oid from token claims (per-user completion state)

Bearer token validation is only active when both env vars are set:
    ENTRA_TENANT_ID   Azure AD tenant/directory ID (GUID)
    ENTRA_CLIENT_ID   Application (client) ID of the app registration

If those vars are missing the app runs in API-key-only mode, exactly as before.
The connector can be migrated to OAuth 2.0 independently of this code change.

Caller identity is stored in Flask's request-scoped `g` object so route
handlers can access it via `get_caller_identity()` without passing it around.
"""

import logging
import os
from functools import wraps
from typing import Optional

from flask import g, jsonify, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JWKS client — lazy-initialised once per process, caches keys for 1 hour
# ---------------------------------------------------------------------------

_jwks_client = None


def _get_jwks_client():
    """Return a PyJWKClient for the configured tenant, or None if unconfigured."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client

    tenant_id = os.environ.get("ENTRA_TENANT_ID", "").strip()
    if not tenant_id:
        return None

    try:
        import jwt  # PyJWT

        jwks_url = (
            f"https://login.microsoftonline.com/{tenant_id}"
            f"/discovery/v2.0/keys"
        )
        _jwks_client = jwt.PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
        logger.info(f"JWKS client initialised for tenant {tenant_id}")
        return _jwks_client
    except Exception as exc:
        logger.error(f"Failed to initialise JWKS client: {exc}")
        return None


# ---------------------------------------------------------------------------
# Token validation
# ---------------------------------------------------------------------------

def _validate_bearer_token(token: str) -> Optional[dict]:
    """
    Validate a JWT Bearer token against the configured Entra ID tenant.

    Returns the decoded claims dict on success, None on any failure.
    Never raises — all errors are caught and logged.
    """
    tenant_id = os.environ.get("ENTRA_TENANT_ID", "").strip()
    client_id = os.environ.get("ENTRA_CLIENT_ID", "").strip()

    if not tenant_id or not client_id:
        logger.debug("Bearer token present but ENTRA config missing — skipping validation.")
        return None

    jwks_client = _get_jwks_client()
    if not jwks_client:
        return None

    try:
        import jwt  # PyJWT

        signing_key = jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=f"https://login.microsoftonline.com/{tenant_id}/v2.0",
        )
        return claims

    except Exception as exc:
        logger.warning(f"Bearer token validation failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Caller identity helpers
# ---------------------------------------------------------------------------

def get_caller_identity() -> dict:
    """
    Return the current caller's identity as populated by require_auth.

    Keys:
        user_oid   (str)  Stable identifier. Real Entra oid (GUID) when using
                          Bearer token; "_api_key" when using API key auth;
                          "_dev" in local dev with no API_KEY set.
        name       (str)  Display name from token, or a synthetic label.
        upn        (str|None) User principal name (email) from token, or None.
        via_entra  (bool) True only when authenticated via a valid Bearer token.
    """
    return getattr(
        g,
        "caller_identity",
        {
            "user_oid": "_api_key",
            "name": "API Key User",
            "upn": None,
            "via_entra": False,
        },
    )


# ---------------------------------------------------------------------------
# Auth decorator
# ---------------------------------------------------------------------------

def require_auth(f):
    """
    Drop-in replacement for the old `require_api_key` decorator.

    Accepts either a valid Bearer token OR a valid X-API-Key header.
    Bearer token is checked first; API key is the fallback for backward compat.

    On success: sets g.caller_identity and calls the route handler.
    On failure: returns a structured 401 JSON error (never HTML).
    """
    @wraps(f)
    def decorated(*args, **kwargs):

        # --- 1. Try Bearer token (Entra ID) ---
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[len("Bearer "):]
            claims = _validate_bearer_token(token)

            if claims:
                g.caller_identity = {
                    "user_oid": claims.get("oid", "_unknown"),
                    "name": claims.get("name") or claims.get("preferred_username", "Unknown User"),
                    "upn": claims.get("preferred_username"),
                    "via_entra": True,
                }
                return f(*args, **kwargs)

            # A Bearer header was sent but validation failed — reject outright.
            # Don't fall through to API key: that would allow token spoofing.
            return _auth_error(
                "INVALID_TOKEN",
                "Bearer token is invalid or expired. "
                "Ensure ENTRA_TENANT_ID and ENTRA_CLIENT_ID are set correctly.",
            )

        # --- 2. Fall back to API key ---
        expected = os.environ.get("API_KEY", "").strip()
        provided = request.headers.get("X-API-Key", "").strip()

        if not expected:
            # Local development: no API_KEY configured — allow through with a warning.
            from flask import current_app
            current_app.logger.warning(
                "API_KEY env var is not set. Auth check skipped (local dev mode)."
            )
            g.caller_identity = {
                "user_oid": "_dev",
                "name": "Dev User",
                "upn": None,
                "via_entra": False,
            }
            return f(*args, **kwargs)

        if provided and provided == expected:
            g.caller_identity = {
                "user_oid": "_api_key",
                "name": "API Key User",
                "upn": None,
                "via_entra": False,
            }
            return f(*args, **kwargs)

        # --- 3. Nothing valid ---
        return _auth_error(
            "UNAUTHORIZED",
            "Authentication required. Provide a Bearer token "
            "(Authorization: Bearer <token>) or an API key (X-API-Key: <key>).",
        )

    return decorated


def _auth_error(code: str, message: str):
    return jsonify({"error": {"code": code, "message": message, "details": None}}), 401
