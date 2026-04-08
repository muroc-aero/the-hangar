"""Component factory registry for plan materialization.

Maps component type strings (e.g., "oas/AerostructPoint") to factory
functions that build OpenMDAO problems from plan YAML configs.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

_FACTORIES: dict[str, Callable] = {}
_PLOT_PROVIDERS: dict[str, dict[str, Callable]] = {}
_GENERIC_PLOTS: dict[str, Callable] = {}
_initialized = False


def register_factory(
    component_type: str,
    factory: Callable,
    plot_provider: dict[str, Callable] | None = None,
) -> None:
    """Register a factory function for a component type.

    Args:
        component_type: Type string matching plan component entries
            (e.g., "oas/AerostructPoint").
        factory: Callable(component_config, operating_points) -> (problem, metadata).
        plot_provider: Optional dict mapping plot type names to callables.
            Each callable has signature (recorder_path, **kwargs) -> Figure.
    """
    _FACTORIES[component_type] = factory
    if plot_provider:
        _PLOT_PROVIDERS[component_type] = plot_provider
    logger.debug("Registered factory for %s", component_type)


def register_generic_plots(plots: dict[str, Callable]) -> None:
    """Register plot types that work for any OpenMDAO problem.

    Args:
        plots: Dict mapping plot type names to callables.
    """
    _GENERIC_PLOTS.update(plots)


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


def get_plot_provider(component_type: str | None = None) -> dict[str, Callable]:
    """Get merged plot provider for a component type.

    Returns generic plots merged with type-specific plots. Type-specific
    plots take precedence over generic ones with the same name.

    Args:
        component_type: Component type string. If None, returns only
            generic plots.

    Returns:
        Dict mapping plot type names to callables.
    """
    _ensure_builtins()
    merged = dict(_GENERIC_PLOTS)
    if component_type and component_type in _PLOT_PROVIDERS:
        merged.update(_PLOT_PROVIDERS[component_type])
    return merged


def get_all_plot_providers() -> dict[str, Callable]:
    """Get all registered plot types merged together.

    Used as fallback when component type is unknown (e.g., old runs
    without metadata). Generic plots are included; on name collisions,
    the last registered provider wins.

    Returns:
        Dict mapping plot type names to callables.
    """
    _ensure_builtins()
    merged = dict(_GENERIC_PLOTS)
    for provider in _PLOT_PROVIDERS.values():
        merged.update(provider)
    return merged


def list_plot_types(component_type: str | None = None) -> list[str]:
    """Return sorted list of available plot types.

    Args:
        component_type: If given, returns types for this component.
            If None, returns all registered types.
    """
    if component_type:
        return sorted(get_plot_provider(component_type).keys())
    return sorted(get_all_plot_providers().keys())


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
    # Generic plots: always available
    from hangar.omd.plotting.generic import GENERIC_PLOTS
    register_generic_plots(GENERIC_PLOTS)

    # Paraboloid: pure OpenMDAO, always available (uses generic plots only)
    from hangar.omd.factories.paraboloid import build_paraboloid
    register_factory("paraboloid/Paraboloid", build_paraboloid)

    # OAS factories: optional, require openaerostruct
    try:
        from hangar.omd.factories.oas import (
            build_oas_aerostruct,
            build_oas_aerostruct_multipoint,
        )
        from hangar.omd.factories.oas_aero import build_oas_aeropoint
        from hangar.omd.plotting.oas import OAS_AEROSTRUCT_PLOTS, OAS_AERO_PLOTS
        register_factory("oas/AerostructPoint", build_oas_aerostruct,
                         plot_provider=OAS_AEROSTRUCT_PLOTS)
        register_factory("oas/AerostructMultipoint",
                         build_oas_aerostruct_multipoint,
                         plot_provider=OAS_AEROSTRUCT_PLOTS)
        register_factory("oas/AeroPoint", build_oas_aeropoint,
                         plot_provider=OAS_AERO_PLOTS)
    except ImportError:
        logger.info("OpenAeroStruct not available, OAS factories not registered")

    # OCP factories: optional, require openconcept
    try:
        from hangar.omd.factories.ocp import (
            build_ocp_basic_mission,
            build_ocp_full_mission,
            build_ocp_mission_with_reserve,
        )
        from hangar.omd.plotting.ocp import OCP_MISSION_PLOTS
        register_factory("ocp/BasicMission", build_ocp_basic_mission,
                         plot_provider=OCP_MISSION_PLOTS)
        register_factory("ocp/FullMission", build_ocp_full_mission,
                         plot_provider=OCP_MISSION_PLOTS)
        register_factory("ocp/MissionWithReserve", build_ocp_mission_with_reserve,
                         plot_provider=OCP_MISSION_PLOTS)
    except ImportError:
        logger.info("OpenConcept not available, OCP factories not registered")

    # pyCycle factories: optional, require pycycle
    try:
        from hangar.omd.factories.pyc import (
            build_pyc_turbojet_design,
            build_pyc_turbojet_multipoint,
            build_pyc_hbtf_design,
            build_pyc_ab_turbojet_design,
            build_pyc_single_turboshaft_design,
            build_pyc_multi_turboshaft_design,
            build_pyc_mixedflow_design,
        )
        register_factory("pyc/TurbojetDesign", build_pyc_turbojet_design)
        register_factory("pyc/TurbojetMultipoint", build_pyc_turbojet_multipoint)
        register_factory("pyc/HBTFDesign", build_pyc_hbtf_design)
        register_factory("pyc/ABTurbojetDesign", build_pyc_ab_turbojet_design)
        register_factory("pyc/SingleTurboshaftDesign", build_pyc_single_turboshaft_design)
        register_factory("pyc/MultiTurboshaftDesign", build_pyc_multi_turboshaft_design)
        register_factory("pyc/MixedFlowDesign", build_pyc_mixedflow_design)
    except ImportError:
        logger.info("pyCycle not available, pyCycle factories not registered")
