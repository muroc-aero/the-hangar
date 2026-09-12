"""Aircraft template registry: shipped Aviary model decks + benchmark decks.

Deck paths are relative to the installed ``aviary`` package and resolved by
``aviary.utils.functions.get_path`` at run time, so this module imports
nothing from aviary and stays importable in the main workspace venv.

``mission_method`` is the equations-of-motion family the deck was calibrated
for (``settings:equations_of_motion`` in the CSV): ``energy_state``
(FLOPS-style height-energy) or ``2DOF`` (GASP-style). The wrapper currently
runs energy_state missions; 2DOF decks are listed for completeness and are
rejected by configure_mission until a two_dof default is wired up.
"""

from __future__ import annotations

AIRCRAFT_TEMPLATES: dict[str, dict] = {
    "advanced_single_aisle": {
        "deck": "models/aircraft/advanced_single_aisle/advanced_single_aisle_FLOPS.csv",
        "description": "Advanced technology single-aisle transport (N3CC-like), "
        "FLOPS mass + aero, energy_state mission. The canonical docs example.",
        "mass_method": "FLOPS",
        "mission_method": "energy_state",
    },
    "large_single_aisle_FLOPS": {
        "deck": "models/aircraft/large_single_aisle_1/large_single_aisle_1_FLOPS.csv",
        "description": "737-800-class large single-aisle transport, FLOPS mass + aero, "
        "energy_state mission.",
        "mass_method": "FLOPS",
        "mission_method": "energy_state",
    },
    "large_single_aisle_2_FLOPS": {
        "deck": "models/aircraft/large_single_aisle_2/large_single_aisle_2_FLOPS.csv",
        "description": "Second large single-aisle variant, FLOPS mass + aero, "
        "energy_state mission.",
        "mass_method": "FLOPS",
        "mission_method": "energy_state",
    },
    "bench_FwFm": {
        "deck": "validation_cases/validation_data/test_models/aircraft_for_bench_FwFm.csv",
        "description": "Upstream benchmark deck: FLOPS mass/aero + energy_state "
        "mission (FwFm). Has published expected values in the Aviary benchmark tests.",
        "mass_method": "FLOPS",
        "mission_method": "energy_state",
    },
    "bench_GwFm": {
        "deck": "validation_cases/validation_data/test_models/aircraft_for_bench_GwFm.csv",
        "description": "Upstream benchmark deck: GASP mass/aero + energy_state "
        "mission (GwFm). GASP aero rejects the default mission's aero options "
        "-- pair with mission_template='GwFm_bench', which needs IPOPT/SNOPT "
        "(SLSQP does not converge it).",
        "mass_method": "GASP",
        "mission_method": "energy_state",
    },
    "bwb_FLOPS": {
        "deck": "models/aircraft/blended_wing_body/bwb_simple_FLOPS.csv",
        "description": "Blended wing body (simple FLOPS deck, ~875 klb class), "
        "energy_state. Pair with mission_template='bwb_bench' (M0.85, 7750 nmi) "
        "-- the default mission's transonic single-aisle profile does not suit "
        "a BWB.",
        "mass_method": "FLOPS",
        "mission_method": "energy_state",
    },
    # GASP 2DOF decks -- listed for discovery; mission wiring is energy_state
    # only for now, so configure_mission rejects these with a clear error.
    "large_single_aisle_GASP": {
        "deck": "models/aircraft/large_single_aisle_1/large_single_aisle_1_GASP.csv",
        "description": "737-800-class large single-aisle, GASP mass + aero, 2DOF "
        "mission (not yet runnable through this server).",
        "mass_method": "GASP",
        "mission_method": "2DOF",
    },
    "small_single_aisle_GASP": {
        "deck": "models/aircraft/small_single_aisle/small_single_aisle_GASP.csv",
        "description": "Small single-aisle, GASP mass + aero, 2DOF mission "
        "(not yet runnable through this server).",
        "mass_method": "GASP",
        "mission_method": "2DOF",
    },
}


def get_template(name: str) -> dict:
    """Return a template entry or raise with the valid names listed."""
    if name not in AIRCRAFT_TEMPLATES:
        valid = ", ".join(sorted(AIRCRAFT_TEMPLATES))
        raise ValueError(f"Unknown aircraft template {name!r}. Valid: {valid}")
    return AIRCRAFT_TEMPLATES[name]
