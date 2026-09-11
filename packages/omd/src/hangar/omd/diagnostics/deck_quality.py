"""Physics admissibility checks for a pyCycle off-design deck.

``generate_deck`` marks a point converged when ``thrust > 0 and fuel > 0``.
That test never consults the solver and never consults physics, so an
off-design solve that walked off to a spurious root is kept and fed to the
Kriging fit. Because ``KrigingSurrogate`` normalizes by the training
standard deviation, a single runaway point flattens every real point into
numerical noise and the surrogate degenerates to a near-constant -- which is
then far from anything the engine can actually do.

The checks here are the ones that catch such a point:

* ``t4_held``      -- the OD balance is commanded to a T4; it must hold it.
* ``thrust_range`` -- net thrust must lie within a sane band around design.
* ``monotonic``    -- along one (alt, MN) line, thrust must rise with throttle.
* ``coverage``     -- every (alt, MN) line must retain enough points to fit.

Cost: milliseconds on a saved ``.npz``. The deck itself is the expensive
stage; these run on the artifact, not the physics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

# An OD point is expected to hold its commanded T4 to this relative tolerance.
T4_RTOL = 1.0e-3
# Net thrust beyond this multiple of design thrust is a diverged solve, not an
# engine. Real off-design thrust at sea level runs ~2x the cruise design point.
THRUST_MAX_FACTOR = 7.5
# Minimum converged points per (alt, MN) line for that line to be usable.
MIN_POINTS_PER_LINE = 2


@dataclass
class DeckFinding:
    """One rejected point or failed line check."""

    check: str
    index: int | None
    detail: str

    def __str__(self) -> str:
        where = "" if self.index is None else f"[{self.index}] "
        return f"{self.check}: {where}{self.detail}"


@dataclass
class DeckReport:
    n_points: int
    shipped_ok: np.ndarray          # the deck's own "converged" mask
    physics_ok: np.ndarray          # the mask these checks would keep
    findings: list[DeckFinding] = field(default_factory=list)

    @property
    def rejected(self) -> np.ndarray:
        """Points the deck keeps that the physics checks reject."""
        return np.where(self.shipped_ok & ~self.physics_ok)[0]

    def summary(self) -> str:
        lines = [
            f"deck points {self.n_points}: deck-converged "
            f"{int(self.shipped_ok.sum())}, physics-admissible "
            f"{int(self.physics_ok.sum())}, "
            f"kept-but-inadmissible {len(self.rejected)}"
        ]
        lines += [f"  - {f}" for f in self.findings]
        return "\n".join(lines)


def commanded_t4(throttle: np.ndarray, design_T4: float,
                 idle_T4: float = 1800.0) -> np.ndarray:
    """T4 the deck generator commands for a throttle fraction.

    Mirrors the linear idle->design mapping in ``surrogate._run_hbtf_deck``.
    """
    return idle_T4 + np.asarray(throttle, dtype=float) * (design_T4 - idle_T4)


def physically_converged(
    deck: dict, design_Fn: float, design_T4: float,
    idle_T4: float = 1800.0,
    t4_rtol: float = T4_RTOL,
    thrust_max_factor: float = THRUST_MAX_FACTOR,
) -> np.ndarray:
    """Boolean mask of points that are admissible Kriging training data."""
    Fn = np.asarray(deck["thrust_lbf"], dtype=float)
    Wf = np.asarray(deck["fuel_flow_lbm_s"], dtype=float)
    T4 = np.asarray(deck["T4_degR"], dtype=float)
    thr = np.asarray(deck["throttle"], dtype=float)

    want = commanded_t4(thr, design_T4, idle_T4)
    with np.errstate(invalid="ignore", divide="ignore"):
        t4_err = np.abs(T4 - want) / np.maximum(np.abs(want), 1e-12)
    return (
        np.isfinite(Fn) & np.isfinite(Wf) & np.isfinite(T4)
        & (Fn > 0) & (Wf > 0)
        & (t4_err < t4_rtol)
        & (Fn < thrust_max_factor * design_Fn)
    )


def check_deck(deck: dict, design_Fn: float, design_T4: float,
               idle_T4: float = 1800.0) -> DeckReport:
    """Run every admissibility check and return a report.

    ``deck`` is the dict produced by ``surrogate.generate_deck`` (or loaded
    from its ``.npz``): arrays ``alt_ft``, ``MN``, ``throttle``,
    ``thrust_lbf``, ``fuel_flow_lbm_s``, ``T4_degR``, ``converged``.
    """
    alt = np.asarray(deck["alt_ft"], dtype=float)
    MN = np.asarray(deck["MN"], dtype=float)
    thr = np.asarray(deck["throttle"], dtype=float)
    Fn = np.asarray(deck["thrust_lbf"], dtype=float)
    T4 = np.asarray(deck["T4_degR"], dtype=float)
    shipped = np.asarray(deck["converged"]).astype(bool)

    physics = physically_converged(deck, design_Fn, design_T4, idle_T4)
    report = DeckReport(len(alt), shipped, physics)
    want = commanded_t4(thr, design_T4, idle_T4)

    for i in np.where(shipped & ~physics)[0]:
        if not np.isfinite(Fn[i]) or Fn[i] >= THRUST_MAX_FACTOR * design_Fn:
            report.findings.append(DeckFinding(
                "thrust_range", int(i),
                f"alt={alt[i]:.0f}ft MN={MN[i]:.2f} thr={thr[i]:.2f}: "
                f"Fn={Fn[i]:.4g} lbf vs design {design_Fn:.0f} lbf"))
        else:
            report.findings.append(DeckFinding(
                "t4_held", int(i),
                f"alt={alt[i]:.0f}ft MN={MN[i]:.2f} thr={thr[i]:.2f}: "
                f"T4={T4[i]:.1f} degR, commanded {want[i]:.1f} degR"))

    # Only (alt, MN) pairs the deck actually contains -- a grid need not be a
    # full outer product, and a pair that was never flown is not a gap.
    for a, m in sorted({(float(x), float(y)) for x, y in zip(alt, MN)}):
        sel = (alt == a) & (MN == m) & physics
        n = int(sel.sum())
        if n < MIN_POINTS_PER_LINE:
            report.findings.append(DeckFinding(
                "coverage", None,
                f"alt={a:.0f}ft MN={m:.2f}: only {n} admissible point(s)"))
            continue
        order = np.argsort(thr[sel])
        f = Fn[sel][order]
        if np.any(np.diff(f) <= 0):
            report.findings.append(DeckFinding(
                "monotonic", None,
                f"alt={a:.0f}ft MN={m:.2f}: thrust not increasing with "
                f"throttle: {np.round(f, 1).tolist()}"))
    return report
