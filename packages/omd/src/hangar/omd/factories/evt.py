"""evtolpy (eVTOL sizing) component factories for omd plan materialization.

evtolpy is not OpenMDAO-native (it is a pure-Python fixed-point sizing library),
so these factories wrap it as a single black-box ``ExplicitComponent`` defined in
``hangar.evt.omd_component``. The component runs evtolpy's existing sizing/mission
extraction inside ``compute`` and declares finite-difference partials.

Two factory types are registered:
  * ``evt/Sizing``  -- runs the MTOW fixed-point loop (sized MTOW + masses).
  * ``evt/Mission`` -- reads the as-configured aircraft (no sizing).

Config resolution (most specific wins):
  * ``config_path`` (+ optional ``config_dir``) -- load a complete evtolpy JSON.
  * ``template`` (default ``"test_all"``) -- seed from a named vehicle template.
  Then inline per-section overrides (``aircraft``/``mission``/``power``/
  ``propulsion``/``environ``) and any ``operating_points`` are merged in.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import openmdao.api as om

from hangar.omd.factory_metadata import FactoryMetadata

# evtolpy-backed pieces live in the evt package (which owns the coupling).
from hangar.evt.omd_component import (
    EvtolSizingComp,
    DEFAULT_INPUT_SPECS,
    SCALAR_OUTPUTS,
)
from hangar.evt.config.defaults import SECTIONS, SECTION_SCHEMA, get_template

# Outputs surfaced into the run summary (scalars; vectors go via the evt
# result-extraction branch in run.py).
_OUTPUT_NAMES = list(SCALAR_OUTPUTS)


def _route_overrides(config: dict, flat: dict) -> None:
    """Merge a flat ``{key: value}`` dict into ``config`` by section.

    Each key is routed to the section that owns it (per the evtolpy schema).
    Unknown keys raise -- evtolpy silently ignores them otherwise, which is the
    same footgun the evt setters guard against.
    """
    for key, value in flat.items():
        section = next((s for s, keys in SECTION_SCHEMA.items() if key in keys), None)
        if section is None:
            raise ValueError(
                f"unknown evtolpy config key {key!r}; not a member of any section "
                f"{tuple(SECTION_SCHEMA)}"
            )
        config.setdefault(section, {})[key] = value


def _resolve_base_config(component_config: dict) -> dict:
    """Build the complete evtolpy config from a plan component config block."""
    # ``config_name`` is a stem (no extension); ``.json`` is appended. This is
    # the study-friendly form: a matrix axis binds the bare case name here.
    config_path = component_config.get("config_path")
    config_name = component_config.get("config_name")
    if config_name and not config_path:
        config_path = config_name if config_name.endswith(".json") else f"{config_name}.json"
    if config_path:
        path = Path(config_path)
        config_dir = component_config.get("config_dir")
        if config_dir and not path.is_absolute():
            path = Path(config_dir) / path
        with open(path, encoding="utf-8") as fh:
            config = json.load(fh)
    else:
        config = get_template(component_config.get("template", "test_all"))

    # Inline per-section overrides (a dict per section name).
    for section in SECTIONS:
        if isinstance(component_config.get(section), dict):
            config.setdefault(section, {}).update(component_config[section])

    # Flat overrides routed to their owning section.
    if isinstance(component_config.get("overrides"), dict):
        _route_overrides(config, component_config["overrides"])

    return config


def _build_evt(
    component_config: dict,
    operating_points: dict,
    mode: str,
) -> tuple[om.Problem, FactoryMetadata]:
    """Shared builder for the evt sizing/mission factories."""
    base_config = _resolve_base_config(component_config)

    # Operating points are flat config overrides (e.g. cruise_s, payload_kg).
    if operating_points:
        _route_overrides(base_config, dict(operating_points))

    input_specs = component_config.get("input_specs", DEFAULT_INPUT_SPECS)
    record_history = bool(component_config.get("record_history", True))

    prob = om.Problem(reports=False)
    prob.model.add_subsystem(
        "evtol",
        EvtolSizingComp(
            base_config=base_config,
            mode=mode,
            input_specs=copy.deepcopy(input_specs),
            record_history=record_history,
        ),
        promotes=["*"],
    )

    # promotes=["*"] -> every input/output is addressable by its bare name.
    var_paths: dict[str, str] = {name: name for name in _OUTPUT_NAMES}
    initial_values: dict[str, Any] = {}
    for spec in input_specs:
        var_paths[spec["name"]] = spec["name"]
        section, key = spec["section"], spec["key"]
        if key in base_config.get(section, {}):
            initial_values[spec["name"]] = float(base_config[section][key])

    metadata: FactoryMetadata = {
        "point_name": "evtol",
        "output_names": list(_OUTPUT_NAMES),
        "var_paths": var_paths,
        "initial_values": initial_values,
        "component_family": "evt",
        "evt_mode": mode,
    }
    return prob, metadata


def build_evt_sizing(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build a sized-MTOW evtolpy problem (runs the fixed-point loop)."""
    return _build_evt(component_config, operating_points, mode="sizing")


def build_evt_mission(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build an as-configured (unsized) evtolpy mission problem."""
    return _build_evt(component_config, operating_points, mode="mission")
