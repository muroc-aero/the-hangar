"""Engine definition tool — create_engine."""

from __future__ import annotations

from typing import Annotated, Any

from hangar.pyc.state import sessions as _sessions

from hangar.pyc.archetypes import get_archetype, ARCHETYPES
from hangar.pyc.validators import (
    validate_archetype,
    validate_thermo_method,
)


async def create_engine(
    archetype: Annotated[
        str,
        "Engine architecture type. Valid: "
        + ", ".join(sorted(ARCHETYPES.keys()))
        + ". Each defines the element topology, flow connections, and balance strategy.",
    ],
    name: Annotated[str, "Name for this engine (used in subsequent analysis calls)"] = "engine",
    comp_PR: Annotated[float | None, "Compressor pressure ratio (turbojet)"] = None,
    comp_eff: Annotated[float | None, "Compressor isentropic efficiency"] = None,
    turb_eff: Annotated[float | None, "Turbine isentropic efficiency"] = None,
    Nmech: Annotated[float | None, "Shaft speed (rpm)"] = None,
    burner_dPqP: Annotated[float | None, "Combustor fractional pressure loss"] = None,
    nozz_Cv: Annotated[float | None, "Nozzle velocity coefficient"] = None,
    thermo_method: Annotated[
        str,
        "Thermodynamic package: 'TABULAR' (fast, recommended) or 'CEA' (accurate, slower)",
    ] = "TABULAR",
    overrides: Annotated[
        dict[str, Any] | None,
        "Advanced: arbitrary cycle parameter overrides as {path: value} dict. "
        "These are applied directly to the OpenMDAO problem after setup.",
    ] = None,
    session_id: Annotated[str, "Session ID for state management"] = "default",
) -> dict:
    """Define an engine from a predefined archetype and configurable parameters.

    The engine topology (elements, flow connections, balance equations) is fixed
    by the archetype. You configure performance parameters like pressure ratios,
    efficiencies, and shaft speeds.

    The engine is stored in the session and referenced by ``name`` in subsequent
    ``run_design_point`` and ``run_off_design`` calls.

    Returns ``{engine_name, archetype, params, elements, status}``.
    """
    validate_archetype(archetype)
    validate_thermo_method(thermo_method)

    arch = get_archetype(archetype)

    # Build param dict from non-None arguments
    params: dict[str, Any] = {"thermo_method": thermo_method}
    for key, val in [
        ("comp_PR", comp_PR),
        ("comp_eff", comp_eff),
        ("turb_eff", turb_eff),
        ("Nmech", Nmech),
        ("burner_dPqP", burner_dPqP),
        ("nozz_Cv", nozz_Cv),
    ]:
        if val is not None:
            params[key] = val

    if overrides:
        params["_overrides"] = overrides

    # Store engine config in session
    session = _sessions.get(session_id)
    session.engines[name] = {
        "archetype": archetype,
        "params": params,
        "design_solved": False,
    }

    return {
        "engine_name": name,
        "archetype": archetype,
        "description": arch["description"],
        "elements": arch["elements"],
        "params": {k: v for k, v in params.items() if k != "_overrides"},
        "valid_design_vars": arch.get("valid_design_vars", []),
        "status": f"Engine '{name}' created with {archetype} archetype. "
                  f"Call run_design_point to size it.",
    }
