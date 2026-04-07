"""Engineering heuristic sanity checks.

Checks that DV bounds, operating conditions, and scalers are physically
reasonable based on catalog recommendations and engineering knowledge.
"""

from __future__ import annotations

import logging
from pathlib import Path

from hangar.range_safety.validators.structural import _load_catalog, _default_catalog_dir

logger = logging.getLogger(__name__)

# Physically reasonable operating condition ranges
_OP_RANGES = {
    "Mach_number": (0.0, 5.0),
    "alpha": (-20.0, 30.0),
    "rho": (0.0001, 1.5),  # sea level ~1.225, cruise ~0.38
    "velocity": (0.1, 1000.0),  # m/s
    "re": (1e3, 1e9),  # Reynolds number per unit length
}

# Unit-confusion heuristics: if a value exceeds the threshold, it likely
# uses the wrong unit system.  Key -> (threshold, likely_unit, expected_unit).
_UNIT_CONFUSION_HINTS: dict[str, tuple[float, str, str]] = {
    "velocity": (500.0, "knots", "m/s"),
    "altitude": (50_000.0, "feet", "meters"),
    "cruise_altitude": (50_000.0, "feet", "meters"),
}


def _finding(check: str, severity: str, message: str) -> dict:
    """Build a finding dict."""
    return {"check": check, "severity": severity, "message": message}


def validate_heuristics(
    plan: dict,
    catalog_dir: Path | None = None,
) -> list[dict]:
    """Check that DV bounds and operating conditions are physically reasonable.

    Uses recommended ranges from the component catalog and engineering
    heuristics to flag suspicious values.

    Args:
        plan: Parsed plan dictionary.
        catalog_dir: Path to the catalog directory. Uses default if None.

    Returns:
        List of finding dicts with keys: check, severity, message.
    """
    findings: list[dict] = []

    if catalog_dir is None:
        catalog_dir = _default_catalog_dir()
    catalog = _load_catalog(catalog_dir)

    components = plan.get("components", [])
    design_variables = plan.get("design_variables", [])
    constraints = plan.get("constraints", [])
    objective = plan.get("objective", {})
    operating_points = plan.get("operating_points", {})

    # -- Operating point range checks --
    # Extract numeric value from bare numbers or {value:, units:} objects
    def _op_value(v):
        if isinstance(v, dict):
            return v.get("value")
        return v

    for key, raw_value in operating_points.items():
        value = _op_value(raw_value)
        if not isinstance(value, (int, float)):
            continue
        if key in _OP_RANGES:
            lo, hi = _OP_RANGES[key]
            if value < lo or value > hi:
                findings.append(_finding(
                    "operating_point_range",
                    "warning",
                    f"Operating point '{key}' = {value} is outside "
                    f"typical range [{lo}, {hi}]",
                ))
        # Unit confusion warnings
        if key in _UNIT_CONFUSION_HINTS:
            threshold, likely_unit, expected_unit = _UNIT_CONFUSION_HINTS[key]
            if value > threshold:
                findings.append(_finding(
                    "unit_confusion",
                    "warning",
                    f"Operating point '{key}' = {value} looks like it may "
                    f"be in {likely_unit} rather than {expected_unit}. "
                    f"omd assumes SI units unless explicitly tagged.",
                ))

    # -- DV bounds checks against catalog --
    # Build a lookup of catalog recommended DV ranges
    catalog_dv_ranges: dict[str, dict] = {}
    for comp in components:
        comp_type = comp.get("type", "")
        cat_entry = catalog.get(comp_type, {})
        for rec_dv in cat_entry.get("recommended_dvs", []):
            dv_name = rec_dv.get("name", "")
            if dv_name:
                catalog_dv_ranges[dv_name] = rec_dv

    for dv in design_variables:
        dv_name = dv.get("name", "<unknown>")
        dv_lower = dv.get("lower")
        dv_upper = dv.get("upper")

        # Check against catalog recommended ranges
        cat_dv = catalog_dv_ranges.get(dv_name)
        if cat_dv:
            cat_lower = cat_dv.get("lower")
            cat_upper = cat_dv.get("upper")

            if cat_lower is not None and dv_lower is not None and dv_lower < cat_lower:
                findings.append(_finding(
                    "dv_bounds_catalog",
                    "warning",
                    f"DV '{dv_name}' lower bound {dv_lower} is below "
                    f"catalog recommended minimum {cat_lower}",
                ))

            if cat_upper is not None and dv_upper is not None and dv_upper > cat_upper:
                findings.append(_finding(
                    "dv_bounds_catalog",
                    "warning",
                    f"DV '{dv_name}' upper bound {dv_upper} is above "
                    f"catalog recommended maximum {cat_upper}",
                ))

        # Check for large dynamic range without scaler
        if (
            dv_lower is not None
            and dv_upper is not None
            and dv_lower != 0
            and abs(dv_upper / dv_lower) > 100
            and "scaler" not in dv
            and "ref" not in dv
        ):
            findings.append(_finding(
                "dv_scaler_recommended",
                "warning",
                f"DV '{dv_name}' has large dynamic range "
                f"[{dv_lower}, {dv_upper}] (ratio > 100) "
                f"but no scaler or ref. Consider adding a scaler.",
            ))

    # -- Optimization completeness --
    if objective:
        if not design_variables:
            findings.append(_finding(
                "optimization_has_dvs",
                "error",
                "Objective is specified but no design variables are defined",
            ))
        if not constraints:
            findings.append(_finding(
                "optimization_has_constraints",
                "warning",
                "Objective is specified but no constraints are defined. "
                "Unconstrained optimization may produce physically "
                "unrealistic results.",
            ))

    # -- OCP mission_params unit confusion checks --
    for comp in components:
        config = comp.get("config", {})
        mission_params = config.get("mission_params", {})
        for mp_key, mp_val in mission_params.items():
            if not isinstance(mp_val, (int, float)):
                continue
            # cruise_altitude_ft should be in feet; warn if suspiciously
            # low (someone passing meters)
            if mp_key == "cruise_altitude_ft" and mp_val < 200:
                findings.append(_finding(
                    "unit_confusion",
                    "warning",
                    f"Component '{comp.get('id', '?')}': "
                    f"cruise_altitude_ft = {mp_val} is very low. "
                    f"This parameter expects feet, not meters.",
                ))
            # mission_range_NM should be in nautical miles; warn if very
            # large (someone passing meters or km)
            if mp_key == "mission_range_NM" and mp_val > 10_000:
                findings.append(_finding(
                    "unit_confusion",
                    "warning",
                    f"Component '{comp.get('id', '?')}': "
                    f"mission_range_NM = {mp_val} is very large. "
                    f"This parameter expects nautical miles.",
                ))

    # -- Mesh density for optimization --
    if objective and design_variables:
        for comp in components:
            config = comp.get("config", {})
            for surface in config.get("surfaces", []):
                num_y = surface.get("num_y")
                if num_y is not None and num_y < 5:
                    findings.append(_finding(
                        "mesh_density_optimization",
                        "warning",
                        f"Component '{comp.get('id', '?')}', "
                        f"surface '{surface.get('name', '?')}': "
                        f"num_y={num_y} is very coarse for optimization. "
                        f"Consider num_y >= 5 for meaningful results.",
                    ))

    return findings
