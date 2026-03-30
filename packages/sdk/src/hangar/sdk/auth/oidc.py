"""OIDC JWT authentication for MCP tool servers.

Migrated from: OpenAeroStruct/oas_mcp/core/auth.py
"""

from __future__ import annotations

import contextvars
import getpass
import json
import os
import threading
import urllib.request
from typing import Any

from hangar.sdk.env import _hangar_env
from hangar.sdk.telemetry import logger

# Contextvar that holds the authenticated username for the current async request.
# Set by OIDCTokenVerifier.verify_token() on each successful JWT validation.
_current_user_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "_current_user_ctx", default=""
)

# Environment variables are read inside build_auth_settings() / build_token_verifier()
# so that changes made after module import (e.g., in test fixtures) are picked up.


def _env(name: str, legacy_name: str, default: str = "") -> str:
    """Read *name* from env, falling back to *legacy_name* (Keycloak compat).

    .. deprecated:: Use :func:`hangar.sdk.env._hangar_env` for new code.
    """
    return os.environ.get(name) or os.environ.get(legacy_name, default)


def _discover_jwks_uri(issuer_url: str) -> str:
    """Fetch ``jwks_uri`` from the issuer's OIDC discovery document."""
    discovery_url = f"{issuer_url.rstrip('/')}/.well-known/openid-configuration"
    with urllib.request.urlopen(discovery_url, timeout=10) as resp:
        doc = json.loads(resp.read())
    jwks_uri = doc.get("jwks_uri")
    if not jwks_uri:
        raise ValueError(f"No jwks_uri in OIDC discovery document at {discovery_url}")
    return jwks_uri


class OIDCTokenVerifier:
    """Validates RS256 JWTs from any OIDC-compliant provider.

    Discovers the JWKS URI from the issuer's
    ``/.well-known/openid-configuration`` on first use and caches the
    signing key.  The ``PyJWT[crypto]`` package must be installed
    (``pip install 'openaerostruct[http]'``).

    Parameters
    ----------
    issuer_url:
        OIDC issuer URL, e.g.
        ``https://auth.example.com/application/o/my-app/``.
    client_id:
        OAuth2 audience / client ID that tokens must be issued for.
    client_secret:
        Optional client secret.
    """

    def __init__(
        self,
        issuer_url: str,
        client_id: str,
        client_secret: str = "",
    ) -> None:
        self._issuer_url = issuer_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._jwks_client: Any = None  # jwt.PyJWKClient, imported lazily
        self._jwks_lock = threading.Lock()
        self._userinfo_endpoint: str | None = None  # lazily discovered
        # sub → preferred_username cache (DCR tokens lack preferred_username)
        self._username_cache: dict[str, str] = {}

    def _get_jwks_client(self) -> Any:
        with self._jwks_lock:
            if self._jwks_client is None:
                try:
                    import jwt  # PyJWT
                except ImportError as exc:
                    raise ImportError(
                        "PyJWT[crypto] is required for OIDC auth. "
                        "Install it with: pip install 'openaerostruct[http]'"
                    ) from exc
                jwks_uri = _discover_jwks_uri(self._issuer_url)
                logger.info("OIDC JWKS URI discovered: %s", jwks_uri)
                self._jwks_client = jwt.PyJWKClient(jwks_uri)
        return self._jwks_client

    def _resolve_username(self, token: str, claims: dict[str, Any]) -> str:
        """Return a human-readable username from JWT claims.

        DCR-registered clients (e.g. Claude Code) often don't include
        ``preferred_username`` in access tokens.  When it's missing, we
        call the OIDC userinfo endpoint to retrieve it, caching the
        result by ``sub``.
        """
        username = claims.get("preferred_username") or claims.get("username")
        if username:
            return username

        sub = claims.get("sub", "")
        if not sub:
            return ""

        # Check cache first
        cached = self._username_cache.get(sub)
        if cached:
            return cached

        # Discover and call the userinfo endpoint
        try:
            if self._userinfo_endpoint is None:
                discovery_url = f"{self._issuer_url}/.well-known/openid-configuration"
                with urllib.request.urlopen(discovery_url, timeout=10) as resp:
                    doc = json.loads(resp.read())
                self._userinfo_endpoint = doc.get("userinfo_endpoint", "")

            if self._userinfo_endpoint:
                req = urllib.request.Request(
                    self._userinfo_endpoint,
                    headers={"Authorization": f"Bearer {token}"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    userinfo = json.loads(resp.read())
                username = (
                    userinfo.get("preferred_username")
                    or userinfo.get("username")
                    or sub
                )
                self._username_cache[sub] = username
                logger.info(
                    "Resolved username via userinfo: sub=%s → %s", sub, username
                )
                return username
        except Exception as exc:
            logger.warning("Userinfo lookup failed for sub=%s: %s", sub, exc)

        # Final fallback: use sub
        return sub

    def verify(self, token: str) -> dict[str, Any]:
        """Validate *token* and return the decoded JWT claims.

        Raises ``jwt.exceptions.InvalidTokenError`` (or a subclass) on
        any validation failure.
        """
        import jwt  # PyJWT

        client = self._get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)
        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self._client_id,
            issuer=self._issuer_url,
        )
        return payload

    # ------------------------------------------------------------------
    # MCP TokenVerifier protocol
    # ------------------------------------------------------------------

    async def verify_token(self, token: str) -> "AccessToken | None":
        """Validate *token* and return an :class:`AccessToken`, or ``None`` on failure."""
        import asyncio
        from mcp.server.auth.provider import AccessToken

        # Reset contextvar at the start of each request so a previously
        # authenticated identity never leaks into a subsequent failing request.
        _current_user_ctx.set("")

        try:
            claims = await asyncio.to_thread(self.verify, token)
        except Exception as exc:
            logger.warning("Token verification failed: %s", type(exc).__name__)
            return None

        # Scope check: reject tokens that don't include the required mcp:tools scope.
        token_scopes = claims.get("scope", "").split()
        if "mcp:tools" not in token_scopes:
            logger.warning(
                "Token rejected: missing required scope 'mcp:tools' (got: %r)",
                token_scopes,
            )
            return None

        # Store the username in the contextvar so get_current_user() can read it
        # within the same async request lifecycle.  For DCR tokens that lack
        # preferred_username, _resolve_username falls back to the userinfo
        # endpoint (cached) so artifacts are stored under a human-readable name.
        username = await asyncio.to_thread(self._resolve_username, token, claims)
        _current_user_ctx.set(username)

        return AccessToken(
            token=token,
            client_id=claims.get("azp") or claims.get("client_id", self._client_id),
            scopes=token_scopes,
            expires_at=claims.get("exp"),
        )


def get_current_user() -> str:
    """Return the authenticated username for the current request.

    In HTTP mode with OIDC, this reads the username stored by
    ``OIDCTokenVerifier.verify_token()`` via a contextvar.

    Falls back to the ``HANGAR_USER`` environment variable (or legacy
    ``OAS_USER``), then to the OS login name (``getpass.getuser()``).
    The stdio transport always uses the fallback since there is no JWT.
    """
    user = _current_user_ctx.get()
    if user:
        return user
    return _hangar_env("HANGAR_USER", "OAS_USER") or getpass.getuser()


def build_auth_settings() -> Any:
    """Return a FastMCP ``AuthSettings`` object configured from env vars.

    Returns ``None`` if neither ``OIDC_ISSUER_URL`` nor the legacy
    ``KEYCLOAK_ISSUER_URL`` is set (auth disabled).
    """
    issuer_url = _env("OIDC_ISSUER_URL", "KEYCLOAK_ISSUER_URL")
    if not issuer_url:
        return None
    try:
        from mcp.server.auth.settings import AuthSettings  # type: ignore[import]
    except ImportError:
        return None
    resource_server_url = os.environ.get("RESOURCE_SERVER_URL", "http://localhost:8000")
    return AuthSettings(
        issuer_url=issuer_url,
        required_scopes=["mcp:tools"],
        resource_server_url=resource_server_url,
    )


def build_token_verifier() -> OIDCTokenVerifier | None:
    """Return an :class:`OIDCTokenVerifier` if ``OIDC_ISSUER_URL`` (or legacy ``KEYCLOAK_ISSUER_URL``) is set."""
    issuer_url = _env("OIDC_ISSUER_URL", "KEYCLOAK_ISSUER_URL")
    if not issuer_url:
        return None
    client_id = _env("OIDC_CLIENT_ID", "KEYCLOAK_CLIENT_ID")
    if not client_id:
        logger.warning(
            "OIDC_ISSUER_URL is set but OIDC_CLIENT_ID is not — "
            "token audience validation will fail. "
            "Set OIDC_CLIENT_ID to the tool's client ID (e.g. 'oas-mcp')."
        )
    return OIDCTokenVerifier(
        issuer_url=issuer_url,
        client_id=client_id,
        client_secret=_env("OIDC_CLIENT_SECRET", "KEYCLOAK_CLIENT_SECRET"),
    )


# Backward-compatible alias so existing imports don't break.
KeycloakTokenVerifier = OIDCTokenVerifier
