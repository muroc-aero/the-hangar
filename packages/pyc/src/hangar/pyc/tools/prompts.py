"""MCP prompts for guided pyCycle workflows."""

from __future__ import annotations

from mcp.server.fastmcp.prompts import base


def prompt_design_point(
    Fn_target: float = 11800.0,
    T4_target: float = 2370.0,
    comp_PR: float = 13.5,
) -> list[base.Message]:
    """Guided turbojet design-point sizing workflow."""
    return [
        base.UserMessage(
            content=(
                f"Size a turbojet for {Fn_target:.0f} lbf SLS thrust at "
                f"T4={T4_target:.0f} degR with comp_PR={comp_PR}.\n\n"
                "Steps:\n"
                "1. start_session(notes='Turbojet design point')\n"
                f"2. create_engine(archetype='turbojet', comp_PR={comp_PR})\n"
                "3. log_decision(decision_type='archetype_selection', reasoning='...')\n"
                f"4. run_design_point(alt=0, MN=0.000001, Fn_target={Fn_target}, "
                f"T4_target={T4_target})\n"
                "5. log_decision(decision_type='result_interpretation', "
                "reasoning='...', prior_call_id=...)\n"
                "6. visualize(run_id, 'performance_summary')\n"
                "7. export_session_graph()\n\n"
                "Interpret TSFC, OPR, and any validation warnings."
            )
        ),
    ]


def prompt_off_design_study(
    design_Fn: float = 11800.0,
    cruise_alt: float = 35000.0,
    cruise_MN: float = 0.8,
    cruise_Fn: float = 4000.0,
) -> list[base.Message]:
    """Design + off-design throttle/altitude study workflow."""
    return [
        base.UserMessage(
            content=(
                f"Evaluate a turbojet sized for {design_Fn:.0f} lbf SLS at "
                f"cruise (alt={cruise_alt:.0f} ft, MN={cruise_MN}, "
                f"Fn={cruise_Fn:.0f} lbf).\n\n"
                "Steps:\n"
                "1. start_session(notes='Off-design study')\n"
                "2. create_engine(archetype='turbojet')\n"
                f"3. run_design_point(alt=0, MN=0.000001, Fn_target={design_Fn})\n"
                f"4. run_off_design(alt={cruise_alt}, MN={cruise_MN}, "
                f"Fn_target={cruise_Fn})\n"
                "5. visualize(run_id, 'design_vs_offdesign')\n"
                "6. log_decision(decision_type='result_interpretation', "
                "reasoning='TSFC and OPR shift from design to cruise because ...')\n"
                "7. export_session_graph()\n\n"
                "Compare design vs off-design TSFC and explain the lapse."
            )
        ),
    ]


def prompt_compare_engines(
    comp_PR_a: float = 13.5,
    comp_PR_b: float = 16.0,
) -> list[base.Message]:
    """Two-engine component sensitivity comparison workflow."""
    return [
        base.UserMessage(
            content=(
                f"Compare two turbojets at compressor pressure ratios "
                f"{comp_PR_a} and {comp_PR_b}.\n\n"
                "Steps:\n"
                "1. start_session(notes='comp_PR sensitivity')\n"
                f"2. create_engine(archetype='turbojet', name='baseline', comp_PR={comp_PR_a})\n"
                f"3. create_engine(archetype='turbojet', name='high_pr', comp_PR={comp_PR_b})\n"
                "4. run_design_point(engine_name='baseline', run_name='baseline')\n"
                "5. run_design_point(engine_name='high_pr', run_name='high PR')\n"
                "6. Compare TSFC, OPR, and component data between the two envelopes\n"
                "7. log_decision(decision_type='result_interpretation', reasoning='...')\n"
                "8. export_session_graph()"
            )
        ),
    ]
