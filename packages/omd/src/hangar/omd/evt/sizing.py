"""The MTOW-closure sizing group: the one feedback loop in the model.

evtolpy's only coupling is mass closure: ``MTOW = empty + payload + battery``,
where empty/battery depend on MTOW. ``EvtolSizingGroup`` closes it, and
reproduces the black box's two-MTOW reporting convention faithfully.

The black box (``hangar.evt.omd_component``) reports, in one sizing call:

* at the **as-configured** MTOW: the segment energy/power tables, total/reserve
  energy, peak power, disk loading, and ``max_takeoff_mass_kg``;
* at the **converged** MTOW: ``sized_mtow_kg``, empty/battery mass, the 15-way
  ``mass_breakdown_kg``, and ``payload_mass_frac``.

So the group instantiates the physics twice: a ``report`` instance at the input
MTOW, and a ``sized`` instance whose MTOW is the cycle state. The cycle
``mtow_closed -> mtow_iterate`` is driven by either ``NonlinearBlockGS`` (mirrors
evtolpy's fixed-point substitution step for step -- used to validate parity and
the iteration history) or ``NewtonSolver`` + ``DirectSolver`` (quadratic
convergence and clean total derivatives for gradient-based use).

``mission`` mode skips the loop: one physics instance at the as-configured MTOW,
with masses reported there (matching evtolpy ``run_mission_analysis``).
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om

from hangar.omd.evt.labels import MASS_KEYS
from hangar.omd.evt.physics import EvtolPhysicsGroup, external_inputs

# Outputs the *reporting* (as-configured MTOW) instance owns in sizing mode.
_REPORT_OUTPUTS = [
    "segment_energy_kw_hr",
    "segment_power_kw",
    "total_mission_energy_kw_hr",
    "total_reserve_mission_energy_kw_hr",
    "peak_power_kw",
    "disk_loading_kg_p_m2",
]

# Default MTOW-closure convergence tolerance, in kg. Matches the black box's
# fixed-point exit criterion (|delta| < 1e-3 kg) so iteration counts align.
DEFAULT_CONV_TOL = 1.0e-3


class _Collector(om.ExplicitComponent):
    """Assemble the contract outputs from the sized physics + cycle state.

    Produces ``sized_mtow_kg``, ``payload_mass_frac``, ``mass_breakdown_kg`` (the
    15 component masses as a vector), and a ``converged`` flag. ``converged``
    compares the closed MTOW against the MTOW that was fed to the physics; after
    the solver converges they agree to ``conv_tol`` and it reads 1.0, otherwise
    0.0 (matching the black box's divergence handling at the outcome level).
    """

    def initialize(self) -> None:
        self.options.declare("conv_tol", default=DEFAULT_CONV_TOL)

    def setup(self) -> None:
        self.add_input("mtow_closed", val=1.0, units="kg")
        self.add_input("mtow_iterate", val=1.0, units="kg")
        self.add_input("payload_kg", val=1.0, units="kg")
        for name in MASS_KEYS:
            self.add_input(name, val=1.0, units="kg")

        self.add_output("sized_mtow_kg", val=1.0, units="kg")
        self.add_output("payload_mass_frac", val=0.1)
        self.add_output("converged", val=1.0)
        self.add_output("mass_breakdown_kg", val=np.ones(len(MASS_KEYS)), units="kg")

        # converged is a non-smooth flag; leave its partials at zero (nothing
        # differentiates through it). The smooth outputs get complex step.
        self.declare_partials("sized_mtow_kg", "mtow_closed", val=1.0)
        self.declare_partials("payload_mass_frac", ["payload_kg", "mtow_closed"],
                              method="cs")
        self.declare_partials("mass_breakdown_kg", MASS_KEYS, method="cs")

    def compute(self, inputs, outputs) -> None:
        mtow = inputs["mtow_closed"]
        outputs["sized_mtow_kg"] = mtow
        outputs["payload_mass_frac"] = inputs["payload_kg"] / mtow
        gap = np.abs(mtow - inputs["mtow_iterate"])
        outputs["converged"] = np.where(gap < self.options["conv_tol"], 1.0, 0.0)
        outputs["mass_breakdown_kg"] = np.array(
            [inputs[name][0] for name in MASS_KEYS]
        )


class _MissionCollector(om.ExplicitComponent):
    """Contract outputs for mission mode (no sizing): masses at as-configured MTOW."""

    def setup(self) -> None:
        self.add_input("max_takeoff_mass_kg", val=1.0, units="kg")
        self.add_input("payload_kg", val=1.0, units="kg")
        for name in MASS_KEYS:
            self.add_input(name, val=1.0, units="kg")
        self.add_output("sized_mtow_kg", val=1.0, units="kg")
        self.add_output("payload_mass_frac", val=0.1)
        self.add_output("converged", val=1.0)
        self.add_output("mass_breakdown_kg", val=np.ones(len(MASS_KEYS)), units="kg")
        self.declare_partials("sized_mtow_kg", "max_takeoff_mass_kg", val=1.0)
        self.declare_partials("payload_mass_frac",
                              ["payload_kg", "max_takeoff_mass_kg"], method="cs")
        self.declare_partials("mass_breakdown_kg", MASS_KEYS, method="cs")

    def compute(self, inputs, outputs) -> None:
        mtow = inputs["max_takeoff_mass_kg"]
        outputs["sized_mtow_kg"] = mtow
        outputs["payload_mass_frac"] = inputs["payload_kg"] / mtow
        outputs["converged"] = 1.0
        outputs["mass_breakdown_kg"] = np.array(
            [inputs[name][0] for name in MASS_KEYS]
        )


class _MtowBalance(om.ImplicitComponent):
    """Implicit MTOW state with residual ``mtow - (empty + payload + battery)``.

    Used by the Newton variant. The state carries a positive lower bound so the
    linesearch cannot drive MTOW non-physical (the physics has ``sqrt`` terms
    that go non-finite for a runaway/negative MTOW). The state output is named
    ``mtow_iterate`` so it feeds the sized physics directly by promotion.
    """

    def setup(self) -> None:
        self.add_input("mtow_target", val=3000.0, units="kg")
        self.add_output("mtow_iterate", val=3000.0, units="kg", lower=1.0)
        self.declare_partials("mtow_iterate", "mtow_iterate", val=1.0)
        self.declare_partials("mtow_iterate", "mtow_target", val=-1.0)

    def apply_nonlinear(self, inputs, outputs, residuals) -> None:
        residuals["mtow_iterate"] = outputs["mtow_iterate"] - inputs["mtow_target"]


class EvtolSizingGroup(om.Group):
    """eVTOL sizing (MTOW closure) or mission analysis as one OpenMDAO group."""

    def initialize(self) -> None:
        self.options.declare("rotor_count", types=int)
        self.options.declare("lift_rotor_count", types=int)
        self.options.declare("tilt_rotor_count", types=int)
        self.options.declare("pusher_rotor_count", types=int, default=0)
        self.options.declare("mode", default="sizing", values=("sizing", "mission"))
        self.options.declare("solver", default="newton", values=("newton", "gs"))
        self.options.declare("conv_tol", default=DEFAULT_CONV_TOL)
        self.options.declare("maxiter", default=200, types=int)

    def _counts(self) -> dict:
        return {
            "rotor_count": self.options["rotor_count"],
            "lift_rotor_count": self.options["lift_rotor_count"],
            "tilt_rotor_count": self.options["tilt_rotor_count"],
            "pusher_rotor_count": self.options["pusher_rotor_count"],
        }

    def setup(self) -> None:
        counts = self._counts()

        external = external_inputs()
        # Promote the genuine external (config + MTOW) inputs only; the group's
        # internal intermediates must stay internally connected, so never "*".
        sized_inputs = [("max_takeoff_mass_kg", "mtow_iterate") if n ==
                        "max_takeoff_mass_kg" else n for n in external]

        if self.options["mode"] == "mission":
            self.add_subsystem(
                "report", EvtolPhysicsGroup(**counts),
                promotes_inputs=external, promotes_outputs=["*"],
            )
            self.add_subsystem(
                "collector", _MissionCollector(),
                promotes_inputs=["max_takeoff_mass_kg", "payload_kg", *MASS_KEYS],
                promotes_outputs=["sized_mtow_kg", "payload_mass_frac",
                                  "converged", "mass_breakdown_kg"],
            )
            return

        # --- sizing mode: report instance (as-configured) + sized instance (loop) ---
        self.add_subsystem(
            "report", EvtolPhysicsGroup(**counts),
            promotes_inputs=external,          # mtow = max_takeoff_mass_kg (as configured)
            promotes_outputs=_REPORT_OUTPUTS,  # segment tables, totals, peak, disk loading
        )
        self.add_subsystem(
            "sized", EvtolPhysicsGroup(**counts),
            promotes_inputs=sized_inputs,
            promotes_outputs=["empty_mass_kg", "battery_mass_kg", *MASS_KEYS],
        )
        # Mass closure: mtow_closed = empty + payload + battery.
        self.add_subsystem(
            "closure",
            om.ExecComp(
                "mtow_closed = empty_mass_kg + payload_kg + battery_mass_kg",
                mtow_closed={"units": "kg"}, empty_mass_kg={"units": "kg"},
                payload_kg={"units": "kg"}, battery_mass_kg={"units": "kg"},
            ),
            promotes=["*"],
        )
        # Close the loop. GS substitutes mtow_closed straight back into the sized
        # physics (mirrors evtolpy). Newton drives an implicit, lower-bounded
        # MTOW state so the linesearch cannot run the physics non-finite.
        if self.options["solver"] == "gs":
            self.connect("mtow_closed", "mtow_iterate")
        else:
            self.add_subsystem("balance", _MtowBalance(), promotes=["mtow_iterate"])
            self.connect("mtow_closed", "balance.mtow_target")

        self.add_subsystem(
            "collector", _Collector(conv_tol=self.options["conv_tol"]),
            promotes_inputs=["mtow_closed", "mtow_iterate", "payload_kg", *MASS_KEYS],
            promotes_outputs=["sized_mtow_kg", "payload_mass_frac",
                              "converged", "mass_breakdown_kg"],
        )

        # MTOW-closure solver.
        if self.options["solver"] == "gs":
            # Fixed-point substitution: mirror the black box exactly, including
            # its loose |delta| < conv_tol (1e-3 kg) exit so iteration counts and
            # the sized MTOW match step for step.
            nl = self.nonlinear_solver = om.NonlinearBlockGS()
            nl.options["use_aitken"] = False
            nl.options["atol"] = self.options["conv_tol"]
            nl.options["rtol"] = 1.0e-99
        else:
            # Newton over the implicit MTOW balance. solve_subsystems=True runs
            # the explicit physics chains each iteration so only the MTOW state is
            # driven by Newton (otherwise every explicit output is treated as a
            # state starting at 1.0, giving a catastrophic first step). The Armijo
            # linesearch + the state's lower bound keep MTOW physical.
            nl = self.nonlinear_solver = om.NewtonSolver(solve_subsystems=True)
            nl.options["max_sub_solves"] = 10
            nl.linesearch = om.ArmijoGoldsteinLS(maxiter=20, bound_enforcement="vector")
            self.linear_solver = om.DirectSolver()
            nl.options["atol"] = 1.0e-9
            nl.options["rtol"] = 1.0e-12
        nl.options["maxiter"] = self.options["maxiter"]
        nl.options["err_on_non_converge"] = False  # diverged -> converged flag = 0
        nl.options["iprint"] = 0
