"""MCP prompts for guided OpenConcept workflows."""

from __future__ import annotations

from mcp.server.fastmcp.prompts import base


def prompt_mission_analysis(
    aircraft: str = "caravan",
    range_nm: float = 250.0,
    cruise_alt_ft: float = 18000.0,
) -> list[base.Message]:
    """Guided turboprop mission analysis workflow."""
    return [
        base.UserMessage(
            content=(
                f"Analyze a {aircraft} mission: {range_nm} NM at FL{cruise_alt_ft/100:.0f}.\n\n"
                "Steps:\n"
                f"1. start_session(notes='Mission analysis: {aircraft}')\n"
                f"2. load_aircraft_template('{aircraft}')\n"
                "3. set_propulsion_architecture('<default_architecture>')\n"
                f"4. configure_mission(mission_range={range_nm}, cruise_altitude={cruise_alt_ft})\n"
                "5. run_mission_analysis()\n"
                "6. log_decision(decision_type='result_interpretation', reasoning='...')\n"
                "7. export_session_graph()\n\n"
                "Interpret the results: fuel burn, OEW, TOFL, and any validation warnings."
            )
        ),
    ]


def prompt_hybrid_design(
    range_nm: float = 500.0,
    battery_specific_energy: float = 450.0,
) -> list[base.Message]:
    """Series-hybrid electric aircraft trade study workflow."""
    return [
        base.UserMessage(
            content=(
                f"Design a series-hybrid aircraft for {range_nm} NM range "
                f"with {battery_specific_energy} Wh/kg battery technology.\n\n"
                "Steps:\n"
                "1. start_session(notes='Hybrid design study')\n"
                "2. load_aircraft_template('kingair')\n"
                "3. set_propulsion_architecture('twin_series_hybrid', "
                f"battery_specific_energy={battery_specific_energy})\n"
                f"4. configure_mission(cruise_altitude=29000, mission_range={range_nm}, "
                "cruise_hybridization=0.05, payload=1000)\n"
                "5. run_mission_analysis() -- baseline\n"
                "6. run_parameter_sweep(parameter='hybridization', "
                "values=[0.0, 0.05, 0.1, 0.15, 0.2, 0.3])\n"
                "7. log_decision on optimal hybridization fraction\n"
                "8. export_session_graph()\n\n"
                "Compare fuel burn vs hybridization and identify the sweet spot."
            )
        ),
    ]


def prompt_electric_feasibility(
    range_nm: float = 100.0,
    battery_weights: str = "200, 400, 600, 800",
) -> list[base.Message]:
    """All-electric range/battery feasibility study."""
    return [
        base.UserMessage(
            content=(
                f"Assess electric aircraft feasibility for {range_nm} NM range.\n\n"
                "Steps:\n"
                "1. start_session(notes='Electric feasibility')\n"
                "2. load_aircraft_template('tbm850')\n"
                "3. set_propulsion_architecture('series_hybrid', "
                "motor_rating=500, generator_rating=100, battery_weight=400)\n"
                f"4. configure_mission(mission_type='basic', mission_range={range_nm})\n"
                "5. run_parameter_sweep(parameter='battery_weight', "
                f"values=[{battery_weights}])\n"
                "6. Interpret: at what battery weight does SOC remain positive?\n"
                "7. export_session_graph()"
            )
        ),
    ]


def prompt_compare_architectures() -> list[base.Message]:
    """Compare turboprop vs hybrid vs electric for the same mission."""
    return [
        base.UserMessage(
            content=(
                "Compare propulsion architectures for a 250 NM mission.\n\n"
                "Steps:\n"
                "1. start_session(notes='Architecture comparison')\n"
                "2. load_aircraft_template('kingair')\n\n"
                "--- Run A: Twin turboprop baseline ---\n"
                "3. set_propulsion_architecture('twin_turboprop')\n"
                "4. configure_mission(mission_range=250)\n"
                "5. run_mission_analysis(run_name='baseline_turboprop')\n\n"
                "--- Run B: Series hybrid ---\n"
                "6. set_propulsion_architecture('twin_series_hybrid', "
                "battery_specific_energy=400)\n"
                "7. configure_mission(mission_range=250, cruise_hybridization=0.1)\n"
                "8. run_mission_analysis(run_name='hybrid_10pct')\n\n"
                "--- Compare ---\n"
                "9. Compare fuel burn, OEW, and MTOW margin between runs.\n"
                "10. log_decision on which architecture is better and why.\n"
                "11. export_session_graph()"
            )
        ),
    ]
