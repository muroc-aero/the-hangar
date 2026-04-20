"""Typed contract for metadata dicts returned by component factories.

Factories return ``(om.Problem, metadata)``. The materializer, run pipeline,
stability module, discipline-graph builder, and plotting all read keys from
this dict. This file codifies which keys are legal and what they mean.

Usage in factories::

    from hangar.omd.factory_metadata import FactoryMetadata

    def build_my_thing(config, operating_points) -> tuple[om.Problem, FactoryMetadata]:
        ...
        metadata: FactoryMetadata = {"point_name": "pt0", "var_paths": {...}}
        return prob, metadata

Because ``FactoryMetadata`` is a ``TypedDict(total=False)``, factories can
supply only the subset of keys they care about.  It is fully compatible
with existing dict-based call sites; no runtime behavior changes.
"""

from __future__ import annotations

from typing import Any, TypedDict


class FactoryMetadata(TypedDict, total=False):
    # --- Documented in CLAUDE.md lines 147-162 --------------------------------
    point_name: str
    """Single-point subsystem name (e.g. ``aero_point_0``)."""

    point_names: list[str]
    """Multiple points for multipoint analyses."""

    surface_names: list[str]
    """OAS surface identifiers for single-point factories."""

    output_names: list[str]
    """Full OpenMDAO paths the result extractor should pull into the summary."""

    var_paths: dict[str, str]
    """Short-name -> full-path mapping used to resolve DVs/constraints/objectives."""

    initial_values: dict[str, Any]
    """Values applied via ``prob.set_val(name, val)`` after setup."""

    initial_values_with_units: dict[str, dict]
    """Values with units: ``{name: {"val": ..., "units": "..."}}``."""

    _setup_done: bool
    """True when the factory itself already called ``prob.setup()``."""

    _composite: bool
    """True for multi-component plans assembled by the materializer."""

    component_family: str
    """Dispatch key for result extraction (e.g. ``"ocp"`` triggers OCP path)."""

    multipoint: bool
    """Triggers per-point result extraction in run.py."""

    archetype_meta: dict
    """pyCycle archetype metadata for rich result extraction."""

    # --- Additional keys observed in producers / consumers --------------------
    active_slots: dict
    """Active slot config (set by OCP factory when slots were provided)."""

    surfaces: list[dict]
    """OAS raw geometry dicts."""

    flight_conditions: dict
    """Flight condition dict (OAS aero/aerostruct)."""

    point_labels: list[str]
    """Human-readable labels per point (multipoint)."""

    surface_names_list: list[list[str]]
    """Surface names per point (multipoint aerostruct)."""

    architecture: str
    """Propulsion architecture (OCP)."""

    mission_type: str
    """Mission type: 'basic', 'full', or 'with_reserve' (OCP)."""

    phases: list[str]
    """Mission phase names (OCP)."""

    num_nodes: int
    """Simpson's-rule node count per phase (OCP)."""

    has_fuel: bool
    has_battery: bool
    is_hybrid: bool
    has_takeoff: bool
    has_reserve: bool
    declared_slots: dict
    """OCP: default provider per slot."""

    # --- Materializer-injected (not set by factories) -------------------------
    recorder_path: str
    """Path to the SqliteRecorder .sql file."""

    component_ids: list[str]
    """Composite: list of child component IDs."""

    component_types: dict[str, str]
    """Composite: {comp_id: component_type}."""

    component_metadata: dict[str, dict]
    """Composite: per-component metadata nested under its comp_id."""


__all__ = ["FactoryMetadata"]
