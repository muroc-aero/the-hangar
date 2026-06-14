"""MCP prompts for guided evtol workflows."""

from __future__ import annotations

from mcp.server.fastmcp.prompts import base


def prompt_mission_analysis(
    template: str = "test_all",
) -> list[base.Message]:
    """Guided mission-energy analysis workflow."""
    return [
        base.UserMessage(
            content=(
                f"Analyse the mission energy, power, and mass breakdown of the "
                f"'{template}' eVTOL.\n\n"
                "Steps:\n"
                "1. start_session(notes='eVTOL mission analysis')\n"
                f"2. load_vehicle_template(template='{template}')\n"
                "3. log_decision(decision_type='architecture_choice', reasoning='...')\n"
                "4. run_mission_analysis()\n"
                "5. log_decision(decision_type='result_interpretation', "
                "reasoning='...', prior_call_id=...)\n"
                "6. visualize(run_id, 'segment_energy')\n"
                "7. export_session_graph()\n\n"
                "Interpret the cruise vs hover energy split, the total mission "
                "energy, and any validation warnings."
            )
        ),
    ]


def prompt_sizing_study(
    template: str = "test_all",
) -> list[base.Message]:
    """Guided MTOW sizing workflow."""
    return [
        base.UserMessage(
            content=(
                f"Size the '{template}' eVTOL by converging its MTOW.\n\n"
                "Steps:\n"
                "1. start_session(notes='MTOW sizing')\n"
                f"2. load_vehicle_template(template='{template}')\n"
                "3. run_sizing()\n"
                "4. visualize(run_id, 'mtow_convergence')\n"
                "5. log_decision(decision_type='result_interpretation', "
                "reasoning='MTOW grew from initial to sized because ...')\n"
                "6. export_session_graph()\n\n"
                "Report the converged MTOW, iteration count, and the empty/"
                "battery/payload mass split."
            )
        ),
    ]


def prompt_battery_sweep(
    spec_energy_low: float = 200.0,
    spec_energy_high: float = 320.0,
) -> list[base.Message]:
    """Guided battery specific-energy sensitivity sweep."""
    return [
        base.UserMessage(
            content=(
                f"Study how battery specific energy from {spec_energy_low:.0f} to "
                f"{spec_energy_high:.0f} Wh/kg affects sized MTOW.\n\n"
                "Steps:\n"
                "1. start_session(notes='Battery specific-energy sweep')\n"
                "2. load_vehicle_template(template='test_all')\n"
                "3. run_parameter_sweep(param='power.batt_spec_energy_w_h_p_kg', "
                f"values=[{spec_energy_low}, ..., {spec_energy_high}], "
                "metric='sized_mtow_kg')\n"
                "4. visualize(run_id, 'sweep')\n"
                "5. log_decision(decision_type='result_interpretation', reasoning='...')\n"
                "6. export_session_graph()\n\n"
                "Explain the MTOW sensitivity and any points that failed to size."
            )
        ),
    ]
