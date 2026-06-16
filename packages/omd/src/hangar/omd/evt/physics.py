"""The feed-forward evtolpy physics as one reusable OpenMDAO group.

``EvtolPhysicsGroup`` chains the five domain components at a *given* MTOW:

    geometry -> propulsion -> aero -> mission energy -> mass buildup

Everything is promoted (``promotes=["*"]``), so each domain output feeds the
next by name and the shared config scalars (and ``max_takeoff_mass_kg``) resolve
to a single source. The chain is acyclic -- the only feedback in the full model
is MTOW closure, which lives one level up in ``EvtolSizingGroup``. Components are
added in dependency order so the default ``NonlinearRunOnce`` evaluates them
correctly in a single pass.

The group is used twice by the sizing group: once at the as-configured MTOW
(reporting) and once at the balance-driven MTOW (sizing). See ``sizing.py``.
"""

from __future__ import annotations

import openmdao.api as om

from hangar.omd.evt.aero import AeroComp
from hangar.omd.evt.geometry import GeometryComp
from hangar.omd.evt.mass import MassBuildupComp
from hangar.omd.evt.mission import MissionEnergyComp
from hangar.omd.evt.propulsion import PropulsionComp


class EvtolPhysicsGroup(om.Group):
    """Feed-forward eVTOL physics at a fixed MTOW (no mass-closure loop)."""

    def initialize(self) -> None:
        self.options.declare("rotor_count", types=int)
        self.options.declare("lift_rotor_count", types=int)
        self.options.declare("tilt_rotor_count", types=int)
        self.options.declare("pusher_rotor_count", types=int, default=0)

    def setup(self) -> None:
        counts = {
            "rotor_count": self.options["rotor_count"],
            "lift_rotor_count": self.options["lift_rotor_count"],
            "tilt_rotor_count": self.options["tilt_rotor_count"],
            "pusher_rotor_count": self.options["pusher_rotor_count"],
        }
        prop_counts = {
            "rotor_count": counts["rotor_count"],
            "pusher_rotor_count": counts["pusher_rotor_count"],
        }

        # Dependency order: geometry -> propulsion -> aero -> mission -> mass.
        self.add_subsystem("geometry", GeometryComp(), promotes=["*"])
        self.add_subsystem("propulsion", PropulsionComp(**prop_counts), promotes=["*"])
        self.add_subsystem("aero", AeroComp(), promotes=["*"])
        self.add_subsystem("mission", MissionEnergyComp(**counts), promotes=["*"])
        self.add_subsystem("mass", MassBuildupComp(**counts), promotes=["*"])


# Cached list of the group's genuine *external* inputs (config + MTOW): the
# component inputs that are not produced by an upstream component within the
# group. The 15 internal intermediates (wing_area_m2, total_mission_energy_kw_hr,
# ...) are excluded -- they must stay internally connected, so a parent must
# promote only this list, never "*", when reusing the group twice (see sizing.py).
_EXTERNAL_INPUTS: list[str] | None = None


def external_inputs() -> list[str]:
    """External (config + MTOW) input names of ``EvtolPhysicsGroup``."""
    global _EXTERNAL_INPUTS
    if _EXTERNAL_INPUTS is None:
        probe = om.Problem(reports=False)
        probe.model.add_subsystem(
            "g",
            EvtolPhysicsGroup(rotor_count=2, lift_rotor_count=1,
                              tilt_rotor_count=1, pusher_rotor_count=1),
            promotes=["*"],
        )
        probe.setup()
        ins = {m["prom_name"]
               for _, m in probe.model.g.list_inputs(out_stream=None,
                                                      prom_name=True, val=False)}
        outs = {m["prom_name"]
                for _, m in probe.model.g.list_outputs(out_stream=None,
                                                       prom_name=True, val=False)}
        _EXTERNAL_INPUTS = sorted(ins - outs)
    return list(_EXTERNAL_INPUTS)
