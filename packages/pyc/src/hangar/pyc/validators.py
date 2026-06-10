"""Input validation for pyCycle MCP tools.

Raises ValueError with clear messages for invalid inputs.
"""

from __future__ import annotations

from hangar.pyc.archetypes import ARCHETYPES


def validate_archetype(name: str) -> None:
    """Raise ValueError if archetype name is unknown."""
    if name not in ARCHETYPES:
        valid = ", ".join(sorted(ARCHETYPES))
        raise ValueError(f"Unknown archetype {name!r}. Valid: {valid}")


def validate_flight_conditions(
    alt: float,
    MN: float,
) -> None:
    """Validate flight condition inputs."""
    if alt < -1000:
        raise ValueError(f"Altitude must be >= -1000 ft (got {alt})")
    if alt > 100000:
        raise ValueError(f"Altitude must be <= 100000 ft (got {alt})")
    if MN < 0:
        raise ValueError(f"Mach number must be >= 0 (got {MN})")
    if MN > 5.0:
        raise ValueError(f"Mach number must be <= 5.0 (got {MN})")


def validate_thrust_target(Fn_target: float) -> None:
    """Validate thrust target."""
    if Fn_target <= 0:
        raise ValueError(f"Fn_target must be positive (got {Fn_target})")


def validate_T4_target(T4_target: float) -> None:
    """Validate turbine inlet temperature target."""
    if T4_target <= 0:
        raise ValueError(f"T4_target must be positive (got {T4_target})")
    if T4_target > 4500:
        raise ValueError(
            f"T4_target={T4_target} degR exceeds material limits (max ~4500 degR)"
        )


def validate_design_variables(
    design_variables: list[dict],
    archetype_name: str,
) -> None:
    """Validate that design variables are valid for the given archetype."""
    arch = ARCHETYPES.get(archetype_name)
    if arch is None:
        raise ValueError(f"Unknown archetype {archetype_name!r}")
    valid_dvs = set(arch.get("valid_design_vars", []))
    for dv in design_variables:
        name = dv.get("name")
        if name and name not in valid_dvs:
            raise ValueError(
                f"Design variable {name!r} not valid for {archetype_name}. "
                f"Valid: {sorted(valid_dvs)}"
            )


def validate_engine_exists(session, engine_name: str) -> dict:
    """Validate engine exists in session, return its config."""
    engines = session.engines
    if engine_name not in engines:
        available = list(engines.keys())
        raise ValueError(
            f"Engine {engine_name!r} not found. "
            f"Available engines: {available}. "
            f"Call create_engine first."
        )
    return engines[engine_name]


def validate_thermo_method(method: str) -> None:
    """Validate thermodynamic method selection."""
    valid = {"CEA", "TABULAR"}
    if method not in valid:
        raise ValueError(f"thermo_method must be one of {valid} (got {method!r})")
