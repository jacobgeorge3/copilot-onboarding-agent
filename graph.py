"""
graph.py — Microsoft Graph API client for the Onboarding Agent API.

Implements the On-Behalf-Of (OBO) flow:
  1. Receives the user's Bearer token (already validated by auth.py).
  2. Exchanges it at the Entra ID token endpoint for a new token scoped to
     Microsoft Graph, using the app's own client credentials as proof that
     this API is trusted to make the exchange.
  3. Uses the Graph token to call /v1.0/me and /v1.0/me/manager to fetch
     the signed-in user's real directory profile.

This module is intentionally self-contained — it has no imports from app.py
or auth.py, so it can be tested and reasoned about in isolation.

Required env vars (all set in Azure App Service):
    ENTRA_TENANT_ID       Directory (tenant) ID GUID
    ENTRA_CLIENT_ID       Application (client) ID of this app registration
    ENTRA_CLIENT_SECRET   Client secret for the OBO exchange (Graph OBO secret)

Returns None on any failure — callers should fall back to the database record.
Never raises — all errors are caught and logged.
"""

import logging
import os

import msal
import requests

logger = logging.getLogger(__name__)

# Graph base URL and the fields we want from the user profile.
_GRAPH_BASE = "https://graph.microsoft.com/v1.0"
_USER_SELECT = "displayName,givenName,surname,department,jobTitle,officeLocation,mail,userPrincipalName"

# MSAL ConfidentialClientApplication is safe to reuse across requests —
# it caches tokens internally and handles refresh automatically.
_msal_app = None


def _get_msal_app():
    """Return a cached MSAL ConfidentialClientApplication, or None if unconfigured."""
    global _msal_app
    if _msal_app is not None:
        return _msal_app

    tenant_id = os.environ.get("ENTRA_TENANT_ID", "").strip()
    client_id = os.environ.get("ENTRA_CLIENT_ID", "").strip()
    client_secret = os.environ.get("ENTRA_CLIENT_SECRET", "").strip()

    if not all([tenant_id, client_id, client_secret]):
        logger.warning("Graph OBO skipped — ENTRA_TENANT_ID, ENTRA_CLIENT_ID, or ENTRA_CLIENT_SECRET not set.")
        return None

    try:
        _msal_app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
        )
        logger.info("MSAL ConfidentialClientApplication initialised.")
        return _msal_app
    except Exception as exc:
        logger.error(f"Failed to initialise MSAL app: {exc}")
        return None


def _acquire_graph_token(user_bearer_token: str) -> str | None:
    """
    Exchange the user's incoming Bearer token for a Graph-scoped token via OBO.

    Returns the Graph access token string on success, None on any failure.
    """
    app = _get_msal_app()
    if not app:
        return None

    try:
        result = app.acquire_token_on_behalf_of(
            user_assertion=user_bearer_token,
            scopes=["https://graph.microsoft.com/User.Read"],
        )

        if "access_token" in result:
            logger.debug("OBO token exchange succeeded.")
            return result["access_token"]

        # MSAL returns an error dict when the exchange fails.
        error = result.get("error", "unknown")
        desc = result.get("error_description", "")
        logger.warning(f"OBO token exchange failed — {error}: {desc}")
        return None

    except Exception as exc:
        logger.error(f"OBO token exchange raised an exception: {exc}")
        return None


def get_graph_user(user_bearer_token: str) -> dict | None:
    """
    Fetch the signed-in user's profile from Microsoft Graph.

    Uses the OBO flow to exchange the incoming token for a Graph-scoped token,
    then calls /v1.0/me and /v1.0/me/manager.

    Returns a dict with these keys on success:
        full_name     (str)       e.g. "Jacob George"
        first_name    (str)       e.g. "Jacob"
        department    (str|None)  e.g. "Engineering"
        job_title     (str|None)  e.g. "Cloud Solution Architect"
        office        (str|None)  e.g. "Seattle"
        email         (str|None)  e.g. "jacob@jacobcsa.onmicrosoft.com"
        upn           (str|None)  User principal name (same as email in most tenants)
        manager       (str|None)  Manager's display name, or None if no manager set

    Returns None on any failure — caller should fall back to the database record.
    """
    graph_token = _acquire_graph_token(user_bearer_token)
    if not graph_token:
        return None

    headers = {"Authorization": f"Bearer {graph_token}"}

    # --- Fetch user profile ---
    try:
        resp = requests.get(
            f"{_GRAPH_BASE}/me",
            headers=headers,
            params={"$select": _USER_SELECT},
            timeout=5,
        )
        resp.raise_for_status()
        user = resp.json()
    except Exception as exc:
        logger.warning(f"Graph /me call failed: {exc}")
        return None

    # --- Fetch manager (best-effort — not all users have one) ---
    manager_name = None
    try:
        mgr_resp = requests.get(
            f"{_GRAPH_BASE}/me/manager",
            headers=headers,
            params={"$select": "displayName"},
            timeout=5,
        )
        if mgr_resp.status_code == 200:
            manager_name = mgr_resp.json().get("displayName")
        # 404 means no manager set — that's fine, leave manager_name as None.
    except Exception as exc:
        logger.debug(f"Graph /me/manager call failed (non-fatal): {exc}")

    return {
        "full_name": user.get("displayName") or "",
        "first_name": user.get("givenName") or (user.get("displayName") or "").split()[0],
        "department": user.get("department"),
        "job_title": user.get("jobTitle"),
        "office": user.get("officeLocation"),
        "email": user.get("mail") or user.get("userPrincipalName"),
        "upn": user.get("userPrincipalName"),
        "manager": manager_name,
    }
