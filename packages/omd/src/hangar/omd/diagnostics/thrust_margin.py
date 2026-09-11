"""Can the engine deck meet the thrust the mission asks for?

A steady-flight throttle ``BalanceComp`` has a root only where required
thrust lies within what the engine can produce. When it does not, Newton
cannot converge no matter how good the solver is -- the throttle simply
pegs at a bound. That is a mission-definition problem wearing a solver
problem's clothes, and it is what a constant 2000 ft/min climb to FL350
looked like on the three-tool B738: 75 kN demanded at top of climb against
52 kN available.

This check answers it from the deck alone, in milliseconds, before paying
for a coupled solve.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

LBF_TO_KN = 4.44822e-3


@dataclass(frozen=True)
class NodeMargin:
    """Thrust headroom at one mission node."""

    phase: str
    index: int
    alt_ft: float
    MN: float
    required_kN: float
    available_kN: float

    @property
    def margin_kN(self) -> float:
        return self.available_kN - self.required_kN

    @property
    def feasible(self) -> bool:
        # A node demanding negative thrust has no root either: an engine at
        # idle still pushes. That needs drag devices, not a throttle setting.
        return self.required_kN >= 0.0 and self.margin_kN >= 0.0

    def __str__(self) -> str:
        why = ""
        if self.required_kN < 0:
            why = "  (demands negative thrust -- needs drag devices)"
        return (f"{self.phase}[{self.index}] alt={self.alt_ft:.0f}ft "
                f"MN={self.MN:.3f}: required {self.required_kN:.2f} kN, "
                f"available {self.available_kN:.2f} kN, "
                f"margin {self.margin_kN:+.2f} kN{why}")


def max_thrust_surface(deck: dict, n_engines: int = 1):
    """Return ``f(alt_ft, MN) -> installed max thrust in kN``.

    Built from the highest admissible throttle on each (alt, MN) line of the
    deck, interpolated between lines. Only points the deck marks converged
    are used, so a poisoned point cannot inflate the ceiling.
    """
    from scipy.interpolate import griddata

    ok = np.asarray(deck["converged"]).astype(bool)
    alt = np.asarray(deck["alt_ft"], dtype=float)[ok]
    MN = np.asarray(deck["MN"], dtype=float)[ok]
    thr = np.asarray(deck["throttle"], dtype=float)[ok]
    Fn = np.asarray(deck["thrust_lbf"], dtype=float)[ok]

    pts, fmax = [], []
    for a, m in sorted({(float(x), float(y)) for x, y in zip(alt, MN)}):
        sel = (alt == a) & (MN == m)
        if sel.any():
            pts.append((a, m))
            fmax.append(Fn[sel][np.argmax(thr[sel])])
    if not pts:
        raise ValueError("deck has no admissible points")
    pts = np.asarray(pts, dtype=float)
    fmax = np.asarray(fmax, dtype=float)

    def surface(alt_ft: float, mach: float) -> float:
        q = np.array([[float(alt_ft), float(mach)]])
        v = np.nan
        if len(pts) >= 3:
            try:
                v = griddata(pts, fmax, q, method="linear")[0]
            except Exception:
                # Degenerate triangulation (collinear lines, or a deck the
                # admissibility filter thinned to almost nothing). Nearest is
                # crude but it is still an honest bound, and a check that
                # raises here would be worse than one that is approximate.
                v = np.nan
        if np.isnan(v):            # outside the hull, or no triangulation
            v = griddata(pts, fmax, q, method="nearest")[0]
        return float(v) * LBF_TO_KN * n_engines

    return surface


def required_thrust_kN(drag_kN, weight_kg, vs_ms, Utrue_ms) -> np.ndarray:
    """Steady-flight thrust required: drag plus the climb-angle weight term."""
    drag = np.asarray(drag_kN, dtype=float)
    W = np.asarray(weight_kg, dtype=float)
    vs = np.asarray(vs_ms, dtype=float)
    V = np.asarray(Utrue_ms, dtype=float)
    return drag + W * 9.80665 * (vs / np.maximum(np.abs(V), 1e-9)) / 1000.0


def check_mission_thrust(problem, deck: dict, phases=("climb", "cruise", "descent"),
                         n_engines: int = 1) -> list[NodeMargin]:
    """Margin at every node of a set-up OCP mission problem.

    The problem need not be converged -- an unconverged state still gives a
    usable drag and weight estimate, and infeasibility of tens of kN is not
    hidden by that noise.
    """
    surface = max_thrust_surface(deck, n_engines)
    g = lambda path, **kw: np.asarray(problem.get_val(path, **kw)).ravel()

    out: list[NodeMargin] = []
    for phase in phases:
        alt = g(f"{phase}.fltcond|h", units="ft")
        mach = g(f"{phase}.fltcond|M")
        req = required_thrust_kN(
            g(f"{phase}.drag", units="kN"),
            g(f"{phase}.weight", units="kg"),
            g(f"{phase}.fltcond|vs", units="m/s"),
            g(f"{phase}.fltcond|Utrue", units="m/s"),
        )
        for i in range(len(alt)):
            out.append(NodeMargin(phase, i, float(alt[i]), float(mach[i]),
                                  float(req[i]), surface(alt[i], mach[i])))
    return out


def format_margins(margins: list[NodeMargin]) -> str:
    bad = [m for m in margins if not m.feasible]
    head = (f"{len(bad)}/{len(margins)} mission node(s) demand thrust the deck "
            f"cannot supply") if bad else \
           f"all {len(margins)} mission nodes are within the deck's thrust envelope"
    return "\n".join([head] + [f"  - {m}" for m in bad])
