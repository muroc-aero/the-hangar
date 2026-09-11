"""Run the cheap diagnostics from the command line.

    python -m hangar.omd.diagnostics solver <plan.yaml>
    python -m hangar.omd.diagnostics deck <deck.npz> [--design-fn F] [--design-t4 T]

Both answer in seconds on plans whose full run takes an hour, because
neither needs converged physics: ``solver`` stops at ``final_setup()`` and
``deck`` reads a saved array.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _audit_solver(plan_path: Path) -> int:
    import numpy as np

    from hangar.omd.diagnostics import find_unsolved_implicit, format_unsolved

    # Training stages don't affect model structure; stub them so the audit
    # costs a second instead of the full run.
    import hangar.omd.pyc.surrogate as surrogate

    n = 8
    r = np.linspace(0.0, 1.0, n)
    stub = {
        "alt_ft": r * 40000.0, "MN": 0.2 + r * 0.65, "throttle": 0.15 + r * 0.85,
        "thrust_lbf": 2000.0 + r * 8000.0, "fuel_flow_lbm_s": 0.4 + r * 1.6,
        "T4_degR": 1800.0 + r * 1057.0, "converged": np.ones(n, dtype=bool),
    }
    surrogate.generate_deck = lambda **kw: {k: v.copy() for k, v in stub.items()}
    try:
        from openconcept.aerodynamics.openaerostruct import drag_polar

        def _cheap(self, inputs, outputs):
            outputs["CL_train"][:] = 0.5
            outputs["CD_train"][:] = 0.02

        drag_polar.VLMDataGen.compute = _cheap
    except ImportError:
        pass

    from hangar.omd.materializer import materialize
    from hangar.omd.plan_schema import load_and_validate

    plan, issues = load_and_validate(plan_path)
    for issue in issues:
        print(f"  plan warning: {issue}")
    prob, _meta = materialize(plan, recording_level="minimal")
    findings = find_unsolved_implicit(prob)
    print(f"{plan_path}:")
    print(format_unsolved(findings))
    return 1 if findings else 0


def _audit_deck(deck_path: Path, design_fn: float, design_t4: float) -> int:
    from hangar.omd.diagnostics import check_deck
    from hangar.omd.pyc.surrogate import load_deck

    report = check_deck(load_deck(deck_path), design_fn, design_t4)
    print(f"{deck_path}:")
    print(report.summary())
    return 1 if len(report.rejected) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hangar.omd.diagnostics",
                                 description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("solver", help="find balances no solver can reach")
    s.add_argument("plan", type=Path)

    d = sub.add_parser("deck", help="check a pyCycle deck for bad points")
    d.add_argument("deck", type=Path)
    d.add_argument("--design-fn", type=float, default=5900.0)
    d.add_argument("--design-t4", type=float, default=2857.0)

    args = ap.parse_args(argv)
    if args.cmd == "solver":
        return _audit_solver(args.plan)
    return _audit_deck(args.deck, args.design_fn, args.design_t4)


if __name__ == "__main__":
    sys.exit(main())
