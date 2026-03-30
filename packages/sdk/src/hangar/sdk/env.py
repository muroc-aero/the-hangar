"""Shared environment variable helpers for Hangar SDK.

Provides a unified lookup that reads ``HANGAR_*`` canonical names first,
then falls back to legacy ``OAS_*`` / ``KEYCLOAK_*`` names for backward
compatibility during the migration from single-tool to multi-tool deployment.
"""

from __future__ import annotations

import os


def _hangar_env(canonical: str, *legacy: str, default: str = "") -> str:
    """Read *canonical* env var, falling back through *legacy* names.

    >>> os.environ["HANGAR_USER"] = "alice"
    >>> _hangar_env("HANGAR_USER", "OAS_USER", default="anon")
    'alice'
    """
    for name in (canonical, *legacy):
        val = os.environ.get(name)
        if val:
            return val
    return default
