"""evtolpy (eVTOL sizing) component factories for omd plan materialization.

These factories build a **native OpenMDAO** formulation of evtolpy
(``hangar.omd.evt``): idiomatic components with complex-step partials and a
real MTOW-closure solver, so sizing runs with analytic gradients and can be
coupled into a single converged solver. The native model reproduces upstream
evtolpy to floating point (parity suite:
``packages/evt/examples/native_parity``).

Registered factory types:
  * ``evt/Sizing``   -- native MTOW-closure sizing (sized MTOW + masses).
  * ``evt/Mission``  -- native as-configured mission energy (no sizing).
  * ``evt/SizingFD`` -- the legacy black-box wrapper (``hangar.evt``'s
    ``EvtolSizingComp``) with finite-difference partials, kept as a fallback for
    configs that exercise a non-smooth branch the native gradient path cannot
    cross.

Config resolution (most specific wins):
  * ``config_path`` (+ optional ``config_dir``) -- load a complete evtolpy JSON.
  * ``template`` (default ``"test_all"``) -- seed from a named vehicle template.
  Then inline per-section overrides (``aircraft``/``mission``/``power``/
  ``propulsion``/``environ``) and any ``operating_points`` are merged in.
  ``solver`` (``"newton"`` default, or ``"gs"``) selects the native MTOW-closure
  solver; ``native: false`` forces the black-box path for that component.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import openmdao.api as om

from hangar.omd.factory_metadata import FactoryMetadata
from hangar.omd.evt.builders import build_problem as build_native_problem, SCALAR_OUTPUTS

# Only the pure-data config schema is imported at module level (no evtolpy
# dependency), so the native ``evt/Sizing`` / ``evt/Mission`` factories register
# and run wherever ``hangar-evt`` is installed -- even without the evtolpy
# upstream lib (e.g. the deployed omd image). The evtolpy-backed black box is
# imported lazily inside ``_build_evt`` so only ``evt/SizingFD`` requires it.
from hangar.evt.config.defaults import SECTIONS, SECTION_SCHEMA, get_template

# Outputs surfaced into the run summary (scalars; vectors go via the evt
# result-extraction branch in run.py). The native builders expose the same
# black-box SCALAR_OUTPUTS contract.
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


def _resolve_with_operating_points(component_config: dict,
                                   operating_points: dict) -> dict:
    """Resolve the base config and merge operating-point overrides into it."""
    base_config = _resolve_base_config(component_config)
    if operating_points:
        _route_overrides(base_config, dict(operating_points))
    return base_config


def _build_evt_native(
    component_config: dict,
    operating_points: dict,
    mode: str,
) -> tuple[om.Problem, FactoryMetadata]:
    """Native-OpenMDAO evt factory (default path)."""
    base_config = _resolve_with_operating_points(component_config, operating_points)
    solver = component_config.get("solver", "newton")
    prob, metadata = build_native_problem(base_config, mode=mode, solver=solver)
    return prob, metadata  # type: ignore[return-value]


def _build_evt(
    component_config: dict,
    operating_points: dict,
    mode: str,
) -> tuple[om.Problem, FactoryMetadata]:
    """Black-box (FD) builder for the legacy evt path.

    Imports the evtolpy-backed black box lazily: the native path needs no
    evtolpy, so deferring this import keeps ``evt/Sizing`` / ``evt/Mission``
    usable where evtolpy is absent. Only this FD fallback requires it. evtolpy
    itself is imported lazily inside the black box (at compute), so probe for it
    up front to fail at plan-build time with a clear message rather than
    cryptically mid-run.
    """
    import importlib.util

    if importlib.util.find_spec("evtol") is None:
        raise ImportError(
            "evt/SizingFD (the evtolpy black box) requires the evtolpy upstream "
            "library, which is not installed here. Use the native evt/Sizing or "
            "evt/Mission factory (the default native path) instead, or install "
            "evtolpy."
        )
    from hangar.evt.omd_component import EvtolSizingComp, DEFAULT_INPUT_SPECS

    base_config = _resolve_with_operating_points(component_config, operating_points)

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
    """Build a sized-MTOW evt problem (native MTOW-closure; FD if native=false)."""
    if component_config.get("native", True):
        return _build_evt_native(component_config, operating_points, mode="sizing")
    return _build_evt(component_config, operating_points, mode="sizing")


def build_evt_mission(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build an as-configured (unsized) evt mission problem (native; FD if native=false)."""
    if component_config.get("native", True):
        return _build_evt_native(component_config, operating_points, mode="mission")
    return _build_evt(component_config, operating_points, mode="mission")


def build_evt_sizing_fd(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build the legacy black-box (FD) sized-MTOW evt problem (``evt/SizingFD``)."""
    return _build_evt(component_config, operating_points, mode="sizing")
