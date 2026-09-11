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

__all__ = [
    "DeckFinding",
    "UnsolvedBalance",
    "check_deck",
    "find_unsolved_implicit",
    "format_unsolved",
    "physically_converged",
]
