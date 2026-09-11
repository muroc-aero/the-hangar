"""Find implicit components that no solver in their ancestry can solve.

OpenMDAO will happily run a model containing unsolved ``BalanceComp``s and
report success. ``NonlinearBlockGS`` and the default ``NonlinearRunOnce``
only *call* each subsystem's ``_solve_nonlinear``; an ``ImplicitComponent``
that defines no ``solve_nonlinear`` of its own treats that call as a no-op,
so its outputs keep their initial values and its residuals are never driven
to zero. The run then "converges" in a handful of iterations on a model
that was never solved, and the reported numbers are the initial guesses
propagated through the explicit components.

Only a residual-driving solver -- Newton, Broyden, or a nonlinear Schur --
actually closes such a balance. This module walks an assembled model and
reports every implicit component that has none above it.

Cost: one ``final_setup()``. No converged physics, no training stages.
"""

from __future__ import annotations

from dataclasses import dataclass

import openmdao.api as om

# Solvers that drive residuals to zero. NonlinearBlockGS / NonlinearBlockJac /
# NonlinearRunOnce iterate or sequence subsystems but never solve a balance
# that has no solve_nonlinear of its own.
_RESIDUAL_SOLVERS: tuple[type, ...] = tuple(
    s for s in (
        getattr(om, "NewtonSolver", None),
        getattr(om, "BroydenSolver", None),
        getattr(om, "NonlinearSchurSolver", None),
    )
    if s is not None
)


@dataclass(frozen=True)
class UnsolvedBalance:
    """One implicit component that nothing in its ancestry can solve."""

    path: str               # e.g. "analysis.cruise.steadyflt"
    kind: str               # component class name, e.g. "BalanceComp"
    solver_chain: str       # ancestry, innermost first, with each solver named

    def __str__(self) -> str:
        return f"{self.path} ({self.kind}) -- solver chain: {self.solver_chain}"


def _solver_name(system) -> str:
    nl = system._nonlinear_solver
    return type(nl).__name__ if nl is not None else "None(RunOnce)"


def _ancestors(model, path: str):
    """Yield ``system`` for each ancestor of ``path``, innermost first."""
    parts = path.split(".") if path else []
    for k in range(len(parts) - 1, -1, -1):
        anc = model._get_subsystem(".".join(parts[:k])) if k else model
        if anc is not None:
            yield anc


def find_unsolved_implicit(problem_or_model) -> list[UnsolvedBalance]:
    """Return every implicit component no ancestor solver can solve.

    ``problem_or_model`` may be an ``om.Problem`` (``final_setup()`` is called
    for you) or an already-set-up model ``om.Group``. An empty list means every
    balance in the tree is reachable by a residual-driving solver.
    """
    if isinstance(problem_or_model, om.Problem):
        problem_or_model.final_setup()
        model = problem_or_model.model
    else:
        model = problem_or_model

    unsolved: list[UnsolvedBalance] = []
    for comp in model.system_iter(include_self=True, recurse=True):
        if not isinstance(comp, om.ImplicitComponent):
            continue
        # A component that solves itself, or carries its own solver, is fine.
        if getattr(comp, "_has_solve_nl", False) is True:
            continue
        if comp._nonlinear_solver is not None:
            continue
        if any(
            isinstance(anc._nonlinear_solver, _RESIDUAL_SOLVERS)
            for anc in _ancestors(model, comp.pathname)
        ):
            continue
        chain = " <- ".join(
            f"{anc.pathname or '<root>'}={_solver_name(anc)}"
            for anc in _ancestors(model, comp.pathname)
        )
        unsolved.append(
            UnsolvedBalance(comp.pathname, type(comp).__name__, chain)
        )
    return unsolved


def format_unsolved(findings: list[UnsolvedBalance]) -> str:
    """Render findings as a pytest-friendly multi-line message."""
    if not findings:
        return "no unsolved implicit components"
    head = (
        f"{len(findings)} implicit component(s) have no residual-driving "
        f"solver above them; their outputs keep their initial values and the "
        f"run will report success without solving:"
    )
    return "\n".join([head] + [f"  - {f}" for f in findings])
