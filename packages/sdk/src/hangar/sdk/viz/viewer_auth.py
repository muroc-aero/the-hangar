"""OIDC login flow for the provenance viewer dashboard.

Migrated from: OpenAeroStruct/oas_mcp/core/viewer_auth.py
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from typing import Any

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ViewerOIDCConfig:
    """Holds OIDC settings for the viewer auth flow."""

    issuer_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    session_secret: str
    admin_role: str = "hangar-admin"

    # Populated by discover_oidc_endpoints()
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    end_session_endpoint: str = ""
    jwks_uri: str = ""

    # Lazy-initialised OIDCTokenVerifier for ID-token validation
    _verifier: Any = field(default=None, repr=False)

    def get_verifier(self) -> Any:
        """Return an OIDCTokenVerifier configured for the viewer client."""
        if self._verifier is None:
            from hangar.sdk.auth import OIDCTokenVerifier

            self._verifier = OIDCTokenVerifier(
                issuer_url=self.issuer_url,
                client_id=self.client_id,
                client_secret=self.client_secret,
            )
        return self._verifier


def build_viewer_oidc_config() -> ViewerOIDCConfig | None:
    """Build a :class:`ViewerOIDCConfig` from env vars, or ``None`` if unconfigured."""
    from hangar.sdk.auth import _env
    from hangar.sdk.env import _hangar_env

    issuer_url = _env("OIDC_ISSUER_URL", "KEYCLOAK_ISSUER_URL")
    client_secret = _hangar_env(
        "HANGAR_VIEWER_OIDC_CLIENT_SECRET", "OAS_VIEWER_OIDC_CLIENT_SECRET"
    )
    if not issuer_url or not client_secret:
        return None

    client_id = _hangar_env(
        "HANGAR_VIEWER_OIDC_CLIENT_ID", "OAS_VIEWER_OIDC_CLIENT_ID",
        default="hangar-viewer",
    )
    resource_server_url = os.environ.get(
        "RESOURCE_SERVER_URL", "http://localhost:8000"
    ).rstrip("/")
    redirect_uri = f"{resource_server_url}/viewer/callback"

    session_secret = _hangar_env(
        "HANGAR_VIEWER_SESSION_SECRET", "OAS_VIEWER_SESSION_SECRET"
    )
    if not session_secret:
        session_secret = secrets.token_hex(32)
        logger.warning(
            "HANGAR_VIEWER_SESSION_SECRET is not set — using an auto-generated key. "
            "Sessions will not survive server restarts."
        )

    admin_role = _hangar_env(
        "HANGAR_VIEWER_ADMIN_ROLE", "OAS_VIEWER_ADMIN_ROLE", default="hangar-admin"
    )

    return ViewerOIDCConfig(
        issuer_url=issuer_url.rstrip("/"),
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        session_secret=session_secret,
        admin_role=admin_role,
    )


# ---------------------------------------------------------------------------
# OIDC discovery
# ---------------------------------------------------------------------------

async def discover_oidc_endpoints(config: ViewerOIDCConfig) -> None:
    """Fetch the OIDC discovery document and populate endpoint URLs on *config*.

    Retries up to 3 times with exponential backoff (2/4/8 s) to tolerate
    Keycloak not being ready immediately at container start.
    """
    import asyncio

    import httpx

    discovery_url = f"{config.issuer_url}/.well-known/openid-configuration"
    last_exc: Exception | None = None

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(discovery_url)
                resp.raise_for_status()
                doc = resp.json()
        except Exception as exc:
            last_exc = exc
            delay = 2 ** (attempt + 1)
            logger.warning(
                "OIDC discovery attempt %d failed (%s), retrying in %ds",
                attempt + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
            continue

        config.authorization_endpoint = doc["authorization_endpoint"]
        config.token_endpoint = doc["token_endpoint"]
        config.end_session_endpoint = doc.get("end_session_endpoint", "")
        config.jwks_uri = doc.get("jwks_uri", "")
        logger.info("OIDC discovery complete: auth=%s", config.authorization_endpoint)
        return

    raise RuntimeError(
        f"Failed to discover OIDC endpoints from {discovery_url} "
        f"after 3 attempts: {last_exc}"
    )


# ---------------------------------------------------------------------------
# Login / callback / logout handlers
# ---------------------------------------------------------------------------

def login_redirect(request: Request, config: ViewerOIDCConfig) -> RedirectResponse:
    """Build a redirect to the OIDC authorization endpoint."""
    state = secrets.token_urlsafe(32)
    request.session["oauth_state"] = state

    # Remember where the user wanted to go so we can redirect back after login.
    return_to = str(request.url)
    if return_to.endswith("/viewer/login"):
        return_to = "/viewer"
    request.session["return_to"] = return_to

    params = (
        f"response_type=code"
        f"&client_id={config.client_id}"
        f"&redirect_uri={config.redirect_uri}"
        f"&scope=openid+profile+email"
        f"&state={state}"
    )
    return RedirectResponse(
        url=f"{config.authorization_endpoint}?{params}", status_code=302
    )


async def handle_callback(
    request: Request, config: ViewerOIDCConfig
) -> Response:
    """Exchange the authorization code for tokens and set the session."""
    import httpx

    # --- Validate state (CSRF protection) ---
    state = request.query_params.get("state", "")
    expected_state = request.session.pop("oauth_state", "")
    if not state or not secrets.compare_digest(state, expected_state):
        return Response("Invalid OAuth state", status_code=403, media_type="text/plain")

    code = request.query_params.get("code", "")
    if not code:
        return Response(
            "Missing authorization code", status_code=400, media_type="text/plain"
        )

    # --- Exchange code for tokens ---
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            token_resp = await http.post(
                config.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": config.redirect_uri,
                    "client_id": config.client_id,
                    "client_secret": config.client_secret,
                },
            )
            token_resp.raise_for_status()
            tokens = token_resp.json()
    except Exception as exc:
        logger.error("Token exchange failed: %s", exc)
        return Response(
            "Token exchange failed", status_code=502, media_type="text/plain"
        )

    id_token = tokens.get("id_token", "")
    if not id_token:
        return Response(
            "No id_token in token response", status_code=502, media_type="text/plain"
        )

    # --- Validate ID token ---
    try:
        verifier = config.get_verifier()
        claims = verifier.verify(id_token)
    except Exception as exc:
        logger.error("ID token validation failed: %s", exc)
        return Response(
            "ID token validation failed", status_code=403, media_type="text/plain"
        )

    # --- Extract identity ---
    username = claims.get("preferred_username") or claims.get("sub", "")
    realm_roles = claims.get("realm_access", {}).get("roles", [])
    is_admin = config.admin_role in realm_roles

    # --- Populate session ---
    request.session["username"] = username
    request.session["is_admin"] = is_admin

    return_to = request.session.pop("return_to", "/viewer")
    return RedirectResponse(url=return_to, status_code=302)


async def handle_logout(request: Request, config: ViewerOIDCConfig) -> RedirectResponse:
    """Clear the session and redirect to the OIDC end-session endpoint."""
    request.session.clear()

    if config.end_session_endpoint:
        resource_server_url = os.environ.get(
            "RESOURCE_SERVER_URL", "http://localhost:8000"
        ).rstrip("/")
        post_logout = f"{resource_server_url}/viewer"
        return RedirectResponse(
            url=f"{config.end_session_endpoint}?post_logout_redirect_uri={post_logout}",
            status_code=302,
        )
    return RedirectResponse(url="/viewer", status_code=302)


# ---------------------------------------------------------------------------
# Auth decorator for viewer endpoints
# ---------------------------------------------------------------------------

def require_viewer_oidc(config: ViewerOIDCConfig):
    """Return a decorator that enforces OIDC session auth on viewer endpoints.

    Usage::

        _oidc_auth = require_viewer_oidc(config)

        @_oidc_auth
        async def my_endpoint(request):
            user = get_viewer_user(request)
            ...
    """

    def decorator(handler):
        async def wrapper(request: Request) -> Response:
            username = request.session.get("username")
            if not username:
                return login_redirect(request, config)
            request.state.viewer_user = username
            request.state.viewer_is_admin = request.session.get("is_admin", False)
            return await handler(request)

        return wrapper

    return decorator


def get_viewer_user(request: Request) -> str:
    """Return the authenticated viewer username from request state."""
    return getattr(request.state, "viewer_user", "")


def is_viewer_admin(request: Request) -> bool:
    """Return whether the authenticated viewer user has the admin role."""
    return getattr(request.state, "viewer_is_admin", False)
