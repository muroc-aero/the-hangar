"""Component factory registry for plan materialization.

Maps component type strings (e.g., "oas/AerostructPoint") to factory
functions that build OpenMDAO problems from plan YAML configs.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

_FACTORIES: dict[str, Callable] = {}
_initialized = False


def register_factory(component_type: str, factory: Callable) -> None:
    """Register a factory function for a component type.

    Args:
        component_type: Type string matching plan component entries
            (e.g., "oas/AerostructPoint").
        factory: Callable(component_config, operating_points) -> (problem, metadata).
    """
    _FACTORIES[component_type] = factory
    logger.debug("Registered factory for %s", component_type)


def get_factory(component_type: str) -> Callable:
    """Look up a registered factory.

    Args:
        component_type: Type string to look up.

    Returns:
        The factory callable.

    Raises:
        KeyError: If no factory is registered for this type.
    """
    _ensure_builtins()
    if component_type not in _FACTORIES:
        available = ", ".join(sorted(_FACTORIES.keys())) or "(none)"
        raise KeyError(
            f"No factory registered for component type '{component_type}'. "
            f"Available: {available}"
        )
    return _FACTORIES[component_type]


def list_factories() -> list[str]:
    """Return sorted list of registered component types."""
    _ensure_builtins()
    return sorted(_FACTORIES.keys())


def _ensure_builtins() -> None:
    """Register built-in factories on first access."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    _register_builtins()


def _register_builtins() -> None:
    """Register all built-in factories.

    Uses try/except so omd core works even without optional
    upstream packages installed.
    """
    # Paraboloid: pure OpenMDAO, always available
    from hangar.omd.factories.paraboloid import build_paraboloid
    register_factory("paraboloid/Paraboloid", build_paraboloid)

    # OAS factories: optional, require openaerostruct
    try:
        from hangar.omd.factories.oas import build_oas_aerostruct
        from hangar.omd.factories.oas_aero import build_oas_aeropoint
        register_factory("oas/AerostructPoint", build_oas_aerostruct)
        register_factory("oas/AeroPoint", build_oas_aeropoint)
    except ImportError:
        logger.info("OpenAeroStruct not available, OAS factories not registered")
