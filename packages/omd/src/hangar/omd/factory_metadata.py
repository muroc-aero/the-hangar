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

This file also defines ``VarSpec`` and ``FactoryContract`` for the
produces/consumes contract used by the materializer's auto-derivation
of ``shared_vars`` (see ``MULTI_TOOL_COMPOSITION_PLAN.md`` Fix 3).
Factories attach a ``FactoryContract`` to their registered function as
a ``.contract`` attribute; lookups go through
``registry.get_factory_contract``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal, Mapping, TypedDict

SemanticTag = Literal[
    "geometry",
    "flight_condition",
    "material",
    "propulsion",
    "weight",
    "mission_param",
]


@dataclass(frozen=True)
class VarSpec:
    """Declared shape/units/default/semantics for one produced or consumed variable.

    ``shape=None`` means the variable is a scalar and OpenMDAO infers the
    default ``(1,)`` shape. ``default=1.0`` (not ``None``) so downstream
    ``add_output(val=...)`` calls are always well-defined. The plan's
    ``initial_values`` section still overrides IVC values post-setup.
    """

    shape: tuple[int, ...] | None = None
    units: str | None = None
    default: Any = 1.0
    semantic_tag: SemanticTag | None = None
    description: str = ""


@dataclass(frozen=True)
class FactoryContract:
    """Factory-declared produces/consumes surface.

    ``produces`` names the promoted inputs that the factory would drive
    through its own internal IndepVarComp by default. When two components
    in a composite plan declare overlapping ``produces`` names, the
    materializer hoists those names to the root ``shared_ivc`` and adds
    them to each component's ``skip_fields``.

    ``consumes`` names the promoted inputs that the factory expects but
    does not produce. Currently informational; future cross-tool work
    (Phase 3b+) can use it with ``semantic_tag`` to translate names
    across factories.
    """

    produces: Mapping[str, VarSpec] = field(default_factory=dict)
    consumes: Mapping[str, VarSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Freeze mapping values so downstream code cannot mutate a
        # factory's declared contract at runtime.
        object.__setattr__(self, "produces", MappingProxyType(dict(self.produces)))
        object.__setattr__(self, "consumes", MappingProxyType(dict(self.consumes)))


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

    skipped_initial_values: list[dict]
    """Entries the materializer failed to set via ``prob.set_val``.

    Each entry is ``{"name": str, "error": str, "source": str}`` where
    ``source`` is ``"initial_values"`` or ``"initial_values_with_units"``.
    Populated only when at least one assignment failed; consumers should
    treat a missing key as "all assignments succeeded".
    """


__all__ = ["FactoryContract", "FactoryMetadata", "SemanticTag", "VarSpec"]
