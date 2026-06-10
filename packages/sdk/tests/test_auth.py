"""Tests for the OIDC auth boundary (hangar.sdk.auth.oidc).

Covers the JWT validation path with a locally generated RSA keypair and a
fake JWKS client, so no network or identity provider is needed:
signature rejection, audience/issuer mismatch, missing exp, missing
mcp:tools scope, contextvar reset on failed requests, and the
build_token_verifier env contract.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from hangar.sdk.auth.oidc import (
    OIDCTokenVerifier,
    _current_user_ctx,
    build_token_verifier,
    get_current_user,
)

ISSUER = "https://auth.example.com/application/o/hangar"
CLIENT_ID = "hangar-mcp"


@pytest.fixture(scope="module")
def rsa_keys():
    """One RSA keypair for the whole module (generation is slow)."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture
def verifier(rsa_keys):
    """Verifier wired to a fake JWKS client that returns our public key."""
    _, public_key = rsa_keys
    v = OIDCTokenVerifier(issuer_url=ISSUER, client_id=CLIENT_ID)
    v._jwks_client = SimpleNamespace(
        get_signing_key_from_jwt=lambda token: SimpleNamespace(key=public_key)
    )
    return v


@pytest.fixture(autouse=True)
def reset_user_ctx():
    token = _current_user_ctx.set("")
    yield
    _current_user_ctx.reset(token)


def make_token(private_key, **overrides) -> str:
    """Mint a valid token, with per-test claim overrides (None deletes)."""
    claims = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "exp": int(time.time()) + 3600,
        "sub": "user-sub-1",
        "preferred_username": "alice",
        "scope": "openid mcp:tools",
    }
    for key, value in overrides.items():
        if value is None:
            claims.pop(key, None)
        else:
            claims[key] = value
    return jwt.encode(claims, private_key, algorithm="RS256")


# ---------------------------------------------------------------------------
# verify_token
# ---------------------------------------------------------------------------


async def test_valid_token_accepted(verifier, rsa_keys):
    private_key, _ = rsa_keys
    token = make_token(private_key)
    access = await verifier.verify_token(token)
    assert access is not None
    assert "mcp:tools" in access.scopes
    assert get_current_user() == "alice"


async def test_bad_signature_rejected(verifier, rsa_keys):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = make_token(other_key)
    assert await verifier.verify_token(token) is None


async def test_garbage_token_rejected(verifier):
    assert await verifier.verify_token("not-a-jwt") is None


async def test_wrong_audience_rejected(verifier, rsa_keys):
    private_key, _ = rsa_keys
    token = make_token(private_key, aud="some-other-client")
    assert await verifier.verify_token(token) is None


async def test_wrong_issuer_rejected(verifier, rsa_keys):
    private_key, _ = rsa_keys
    token = make_token(private_key, iss="https://evil.example.com")
    assert await verifier.verify_token(token) is None


async def test_expired_token_rejected(verifier, rsa_keys):
    private_key, _ = rsa_keys
    token = make_token(private_key, exp=int(time.time()) - 60)
    assert await verifier.verify_token(token) is None


async def test_missing_exp_rejected(verifier, rsa_keys):
    """A token minted without exp must not be treated as never-expiring."""
    private_key, _ = rsa_keys
    token = make_token(private_key, exp=None)
    assert await verifier.verify_token(token) is None


async def test_missing_mcp_tools_scope_rejected(verifier, rsa_keys):
    private_key, _ = rsa_keys
    token = make_token(private_key, scope="openid profile")
    assert await verifier.verify_token(token) is None


async def test_failed_request_resets_user_context(verifier, rsa_keys):
    """A previously authenticated identity must not leak into a failing request."""
    private_key, _ = rsa_keys
    good = make_token(private_key)
    assert await verifier.verify_token(good) is not None
    assert get_current_user() == "alice"

    bad = make_token(private_key, scope="openid")  # missing mcp:tools
    assert await verifier.verify_token(bad) is None
    assert get_current_user() != "alice"


async def test_username_falls_back_to_sub_without_userinfo(verifier, rsa_keys, monkeypatch):
    """Tokens without preferred_username resolve via userinfo, falling back to sub."""
    private_key, _ = rsa_keys
    # Block the userinfo network path so the fallback branch is exercised.
    monkeypatch.setattr(verifier, "_userinfo_endpoint", "")
    token = make_token(private_key, preferred_username=None, username=None)
    access = await verifier.verify_token(token)
    assert access is not None
    assert get_current_user() == "user-sub-1"


# ---------------------------------------------------------------------------
# build_token_verifier env contract
# ---------------------------------------------------------------------------


def test_build_token_verifier_disabled_without_issuer(monkeypatch):
    for var in ("OIDC_ISSUER_URL", "KEYCLOAK_ISSUER_URL"):
        monkeypatch.delenv(var, raising=False)
    assert build_token_verifier() is None


def test_build_token_verifier_refuses_missing_client_id(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER_URL", ISSUER)
    for var in ("OIDC_CLIENT_ID", "KEYCLOAK_CLIENT_ID"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(RuntimeError, match="OIDC_CLIENT_ID"):
        build_token_verifier()


def test_build_token_verifier_configured(monkeypatch):
    monkeypatch.setenv("OIDC_ISSUER_URL", ISSUER)
    monkeypatch.setenv("OIDC_CLIENT_ID", CLIENT_ID)
    v = build_token_verifier()
    assert isinstance(v, OIDCTokenVerifier)
    assert v._client_id == CLIENT_ID
