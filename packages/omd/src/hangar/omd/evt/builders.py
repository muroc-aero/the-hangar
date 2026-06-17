"""Assemble an OpenMDAO problem from the native evt sizing group.

The factory (``hangar.omd.factories.evt``) calls ``build_problem`` to get a
problem + the metadata the omd materializer/runner expect. Following the omd
factory contract, the problem is built but NOT set up (the materializer calls
``setup`` after attaching DVs/recorders); initial values are returned in
``metadata["initial_values"]`` and applied post-setup.
"""

from __future__ import annotations

from typing import Any

import openmdao.api as om

from hangar.omd.evt.config import flatten_config
from hangar.omd.evt.labels import MASS_KEYS
from hangar.omd.evt.mass import FIXED_MASS_KEYS
from hangar.omd.evt.sizing import EvtolSizingGroup

POINT_NAME = "evtol"

# Scalar contract outputs (black-box SCALAR_OUTPUTS order).
SCALAR_OUTPUTS = (
    "sized_mtow_kg",
    "max_takeoff_mass_kg",
    "empty_mass_kg",
    "battery_mass_kg",
    "total_mission_energy_kw_hr",
    "total_reserve_mission_energy_kw_hr",
    "payload_mass_frac",
    "peak_power_kw",
    "disk_loading_kg_p_m2",
    "converged",
)


def _counts(flat: dict) -> dict:
    return {
        "rotor_count": int(flat["rotor_count"]),
        "lift_rotor_count": int(flat["lift_rotor_count"]),
        "tilt_rotor_count": int(flat["tilt_rotor_count"]),
        "pusher_rotor_count": int(flat.get("pusher_rotor_count", 0)),
    }


def _make_group(mode: str, solver: str, counts: dict) -> EvtolSizingGroup:
    return EvtolSizingGroup(mode=mode, solver=solver, **counts)


def _promoted_inputs(mode: str, solver: str, counts: dict) -> set[str]:
    """Promoted input names of the assembled model (via a throwaway setup).

    Used to resolve which config keys are real inputs (and whether they take the
    plain name or the ``_in`` form) without setting up the live problem twice.
    """
    probe = om.Problem(reports=False)
    probe.model.add_subsystem(POINT_NAME, _make_group(mode, solver, counts),
                              promotes=["*"])
    probe.setup()
    names = {m["prom_name"]
             for _, m in probe.model.list_inputs(out_stream=None, prom_name=True,
                                                  val=False)}
    return names


def _resolve_initial_values(flat: dict, prom_inputs: set[str], mode: str,
                            solver: str) -> dict:
    """Map config values onto the problem's promoted input names."""
    init: dict[str, Any] = {}
    for key, value in flat.items():
        if key in FIXED_MASS_KEYS:
            name = f"{key}_in"
        else:
            name = key
        if name in prom_inputs:
            init[name] = value
    # Seed the MTOW-closure loop at the as-configured MTOW. For GS, seed the
    # closure output that primes the first substitution; for Newton, seed the
    # implicit ``mtow_iterate`` state directly.
    if mode == "sizing":
        seed = float(flat["max_takeoff_mass_kg"])
        init["mtow_iterate" if solver == "newton" else "mtow_closed"] = seed
    return init


def build_problem(base_config: dict, mode: str = "sizing",
                  solver: str = "newton") -> tuple[om.Problem, dict]:
    """Build a native-evt OpenMDAO problem + omd factory metadata.

    Parameters
    ----------
    base_config : dict
        Complete 5-section evtolpy config.
    mode : {"sizing", "mission"}
        ``sizing`` runs the MTOW-closure loop; ``mission`` reads the
        as-configured aircraft with no sizing.
    solver : {"newton", "gs"}
        MTOW-closure solver (sizing mode only). ``gs`` mirrors evtolpy's
        fixed-point substitution; ``newton`` is the gradient-friendly default.
    """
    flat = flatten_config(base_config)
    counts = _counts(flat)

    prob = om.Problem(reports=False)
    prob.model.add_subsystem(POINT_NAME, _make_group(mode, solver, counts),
                             promotes=["*"])

    prom_inputs = _promoted_inputs(mode, solver, counts)
    initial_values = _resolve_initial_values(flat, prom_inputs, mode, solver)

    var_paths = {name: name for name in (*SCALAR_OUTPUTS, *initial_values,
                                         "segment_energy_kw_hr", "segment_power_kw",
                                         "mass_breakdown_kg")}

    metadata = {
        "point_name": POINT_NAME,
        "output_names": list(SCALAR_OUTPUTS),
        "var_paths": var_paths,
        "initial_values": initial_values,
        "component_family": "evt",
        "evt_mode": mode,
        "native": True,
        # Native components declare complex-step partials; the materializer must
        # allocate complex vectors so Newton/optimization derivatives work.
        "force_alloc_complex": True,
    }
    return prob, metadata
