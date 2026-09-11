"""Cheap structural and data checks that run without the expensive physics.

Coupled multi-tool plans (OCP mission + OAS drag slot + pyCycle propulsion
slot) take tens of minutes end to end, almost all of it in two training
stages: the pyCycle off-design deck and the VLM drag-polar grid. That cost
makes the usual "run it and look at the number" loop useless for debugging
-- and it hides defects that are, in fact, detectable in milliseconds.

This package splits those checks out so each stage can be tested on its own:

``solver_coverage``
    Structural. Given an assembled ``om.Problem``, find every
    ``ImplicitComponent`` that no solver in its ancestry can actually solve.
    Needs no converged physics -- only ``final_setup()``.

``deck_quality``
    Data. Given a pyCycle off-design deck, check that each point is
    physically admissible (it held its commanded T4, its thrust is a sane
    multiple of design thrust, thrust rises with throttle) rather than
    merely non-negative.

``thrust_margin``
    Feasibility. Compare the thrust each mission node requires against what
    the deck can deliver there. A node outside the envelope gives the
    throttle balance no root, so Newton cannot converge -- a mission-
    definition problem that presents as a solver problem.
"""

from hangar.omd.diagnostics.deck_quality import (
    DeckFinding,
    check_deck,
    physically_converged,
)
from hangar.omd.diagnostics.solver_coverage import (
    UnsolvedBalance,
    find_unsolved_implicit,
    format_unsolved,
)
from hangar.omd.diagnostics.thrust_margin import (
    NodeMargin,
    check_mission_thrust,
    format_margins,
    max_thrust_surface,
    required_thrust_kN,
)

__all__ = [
    "DeckFinding",
    "NodeMargin",
    "UnsolvedBalance",
    "check_deck",
    "check_mission_thrust",
    "find_unsolved_implicit",
    "format_margins",
    "format_unsolved",
    "max_thrust_surface",
    "physically_converged",
    "required_thrust_kN",
]
