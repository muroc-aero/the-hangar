"""MCP prompts for guided Aviary workflows."""

from __future__ import annotations

from mcp.server.fastmcp.prompts import base


def prompt_sizing_study(
    template: str = "advanced_single_aisle",
    target_range_nm: float = 1906.0,
) -> list[base.Message]:
    """Guided aircraft sizing workflow."""
    return [
        base.UserMessage(
            content=(
                f"Size the '{template}' aircraft for a {target_range_nm:.0f} nmi "
                "design mission.\n\n"
                "Steps:\n"
                "1. start_session(notes='Aviary sizing study')\n"
                f"2. load_aircraft_template(template='{template}')\n"
                "3. log_decision(decision_type='architecture_choice', reasoning='...')\n"
                f"4. configure_mission(target_range_nm={target_range_nm})\n"
                "5. run_sizing(optimizer='SLSQP')\n"
                "6. Check validation.checks for 'optimizer.success' BEFORE "
                "interpreting the numbers\n"
                "7. log_decision(decision_type='result_interpretation', "
                "reasoning='...', prior_call_id=...)\n"
                "8. visualize(run_id, 'mission_profile')\n"
                "9. export_session_graph()\n\n"
                "Interpret gross mass, fuel burn, and any validation warnings."
            )
        ),
    ]


def prompt_range_sensitivity(
    template: str = "advanced_single_aisle",
    range_a_nm: float = 1500.0,
    range_b_nm: float = 2500.0,
) -> list[base.Message]:
    """Two-point design-range sensitivity workflow."""
    return [
        base.UserMessage(
            content=(
                f"Compare the '{template}' aircraft sized for {range_a_nm:.0f} nmi "
                f"vs {range_b_nm:.0f} nmi design range.\n\n"
                "Steps:\n"
                "1. start_session(notes='Design-range sensitivity')\n"
                f"2. load_aircraft_template(template='{template}', name='short')\n"
                f"3. load_aircraft_template(template='{template}', name='long')\n"
                f"4. configure_mission(aircraft_name='short', target_range_nm={range_a_nm})\n"
                f"5. configure_mission(aircraft_name='long', target_range_nm={range_b_nm})\n"
                "6. run_sizing(aircraft_name='short', run_name='short range')\n"
                "7. run_sizing(aircraft_name='long', run_name='long range')\n"
                "8. Compare gross mass and fuel; visualize(run_id, 'mass_breakdown') for each\n"
                "9. log_decision(decision_type='result_interpretation', reasoning='...')\n"
                "10. export_session_graph()"
            )
        ),
    ]


def prompt_deck_override_study(
    template: str = "advanced_single_aisle",
    aspect_ratio: float = 12.0,
) -> list[base.Message]:
    """Deck-variable override sizing workflow."""
    return [
        base.UserMessage(
            content=(
                f"Resize the '{template}' aircraft with wing aspect ratio "
                f"{aspect_ratio}.\n\n"
                "Steps:\n"
                "1. start_session(notes='Aspect-ratio override study')\n"
                f"2. load_aircraft_template(template='{template}')\n"
                f"3. define_aircraft(overrides={{'aircraft:wing:aspect_ratio': {aspect_ratio}}})\n"
                "4. run_sizing()\n"
                "5. Compare against a baseline run without the override\n"
                "6. log_decision(decision_type='result_interpretation', reasoning='...')\n"
                "7. export_session_graph()"
            )
        ),
    ]
