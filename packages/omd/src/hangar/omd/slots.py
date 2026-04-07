"""Slot provider registry for composable tool integration.

Maps provider names (e.g., "oas/vlm") to callable factory functions that
build substitute OpenMDAO components for specific "slots" in the OCP
aircraft model (drag, propulsion, weight, etc.).

Provider callable signature:
    provider(nn: int, flight_phase: str, config: dict)
        -> (om.Component, promotes_inputs: list, promotes_outputs: list)

Providers also carry metadata attributes:
    provider.slot_name       -- which slot this fills ("drag", "propulsion", etc.)
    provider.removes_fields  -- DictIndepVarComp fields to skip when this provider is active
    provider.adds_fields     -- dict of {field_name: {"value": ..., "units": ...}} to add
"""

from __future__ import annotations

import logging
from typing import Callable

import openmdao.api as om

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, Callable] = {}
_initialized = False


def register_slot_provider(name: str, provider: Callable) -> None:
    """Register a slot provider by name."""
    _PROVIDERS[name] = provider
    logger.debug("Registered slot provider: %s", name)


def get_slot_provider(name: str) -> Callable:
    """Look up a registered slot provider."""
    _ensure_builtins()
    if name not in _PROVIDERS:
        available = ", ".join(sorted(_PROVIDERS.keys())) or "(none)"
        raise KeyError(
            f"No slot provider registered for '{name}'. Available: {available}"
        )
    return _PROVIDERS[name]


def list_slot_providers() -> list[str]:
    """Return sorted list of registered provider names."""
    _ensure_builtins()
    return sorted(_PROVIDERS.keys())


def _ensure_builtins() -> None:
    """Register built-in providers on first access."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    _register_builtins()


def _register_builtins() -> None:
    """Register built-in slot providers."""
    try:
        from openconcept.aerodynamics import VLMDragPolar  # noqa: F401
        register_slot_provider("oas/vlm", _oas_vlm_drag_provider)
    except ImportError:
        logger.info("OpenAeroStruct/VLMDragPolar not available, oas/vlm slot not registered")

    try:
        from openconcept.aerodynamics.openaerostruct.aerostructural import (
            AerostructDragPolar,  # noqa: F401
        )
        register_slot_provider("oas/aerostruct", _oas_aerostruct_drag_provider)
    except ImportError:
        logger.info("AerostructDragPolar not available, oas/aerostruct slot not registered")


# ---------------------------------------------------------------------------
# OAS VLM drag provider
# ---------------------------------------------------------------------------


def _oas_vlm_drag_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    """Build a VLMDragPolar component for the drag slot."""
    from openconcept.aerodynamics import VLMDragPolar

    num_x = config.get("num_x", 2)
    num_y = config.get("num_y", 6)
    num_twist = config.get("num_twist", 4)
    surf_options = config.get("surf_options", {})

    component = VLMDragPolar(
        num_nodes=nn,
        num_x=num_x,
        num_y=num_y,
        num_twist=num_twist,
        surf_options=surf_options,
    )

    promotes_inputs = [
        "fltcond|CL",
        "fltcond|M",
        "fltcond|h",
        "fltcond|q",
        "ac|geom|wing|S_ref",
        "ac|geom|wing|AR",
        "ac|geom|wing|taper",
        "ac|geom|wing|c4sweep",
        "ac|geom|wing|twist",
        "ac|aero|CD_nonwing",
    ]
    promotes_outputs = ["drag"]

    return component, promotes_inputs, promotes_outputs


_oas_vlm_drag_provider.slot_name = "drag"
_oas_vlm_drag_provider.removes_fields = [
    "ac|aero|polar|e",
    "ac|aero|polar|CD0_TO",
    "ac|aero|polar|CD0_cruise",
]
_oas_vlm_drag_provider.adds_fields = {
    "ac|aero|CD_nonwing": {"value": 0.0145},
}


# ---------------------------------------------------------------------------
# OAS Aerostructural drag provider (placeholder for future use)
# ---------------------------------------------------------------------------


def _oas_aerostruct_drag_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    """Build an AerostructDragPolar component for the drag slot."""
    from openconcept.aerodynamics.openaerostruct.aerostructural import (
        AerostructDragPolar,
    )

    num_x = config.get("num_x", 2)
    num_y = config.get("num_y", 6)
    num_twist = config.get("num_twist", 4)
    num_toverc = config.get("num_toverc", 4)
    num_skin = config.get("num_skin", 4)
    num_spar = config.get("num_spar", 4)
    surf_options = config.get("surf_options", {})

    component = AerostructDragPolar(
        num_nodes=nn,
        num_x=num_x,
        num_y=num_y,
        num_twist=num_twist,
        num_toverc=num_toverc,
        num_skin=num_skin,
        num_spar=num_spar,
        surf_options=surf_options,
    )

    promotes_inputs = [
        "fltcond|CL",
        "fltcond|M",
        "fltcond|h",
        "fltcond|q",
        "ac|geom|wing|S_ref",
        "ac|geom|wing|AR",
        "ac|geom|wing|taper",
        "ac|geom|wing|c4sweep",
        "ac|geom|wing|twist",
        "ac|geom|wing|toverc",
        "ac|geom|wing|skin_thickness",
        "ac|geom|wing|spar_thickness",
        "ac|aero|CD_nonwing",
    ]
    promotes_outputs = [
        "drag",
        ("ac|weights|W_wing", "ac|weights|W_wing"),
        "failure",
    ]

    return component, promotes_inputs, promotes_outputs


_oas_aerostruct_drag_provider.slot_name = "drag"
_oas_aerostruct_drag_provider.removes_fields = [
    "ac|aero|polar|e",
    "ac|aero|polar|CD0_TO",
    "ac|aero|polar|CD0_cruise",
]
_oas_aerostruct_drag_provider.adds_fields = {
    "ac|aero|CD_nonwing": {"value": 0.0145},
}
