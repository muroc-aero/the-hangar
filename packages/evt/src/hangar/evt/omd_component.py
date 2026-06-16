"""OpenMDAO wrapper for evtolpy, for use as an omd factory component.

evtolpy is a plain-Python sizing library with no OpenMDAO and no gradients: its
only entry point is ``Aircraft(json_path)`` and sizing is a fixed-point loop
(``_iterate_mtow``). To make it usable from omd's declarative OpenMDAO plan
runner, this module wraps the whole sizing call inside a single
``ExplicitComponent``: inputs are a curated subset of config keys, ``compute``
rebuilds the aircraft and runs the existing evt result extraction, and outputs
are the sized masses, mission energy, and per-segment tables.

This is a *black box*: there are no analytic partials, so the component declares
finite-difference partials. Each FD perturbation re-runs the (cheap) fixed-point
sizing loop. That is acceptable for the small design-variable counts evt studies
use; a gradient-friendly native rewrite is tracked separately (see
``docs/native-openmdao-rewrite-upstream-plan.md``).

Units note: evtolpy bakes units into key/attribute names (``_kg``, ``_kw``,
``_m_p_s`` ...), so exposed inputs/outputs are declared ``units=None``. The
numeric values are in evtolpy's native units. Real OpenMDAO unit metadata is
only needed for cross-tool connection/auto-composition, which is deferred.
"""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import openmdao.api as om

from hangar.evt import builders, results
from hangar.evt.config.defaults import SECTIONS

# Default set of config keys exposed as OpenMDAO inputs. Each entry maps a
# short OpenMDAO name to the (section, key) it overrides in the evtolpy config.
# Chosen to cover the design variables evt studies actually sweep (battery
# energy, payload, wing/rotor sizing, cruise duration as a range proxy).
DEFAULT_INPUT_SPECS: list[dict[str, str]] = [
    {"name": "batt_spec_energy_w_h_p_kg", "section": "power", "key": "batt_spec_energy_w_h_p_kg"},
    {"name": "payload_kg", "section": "aircraft", "key": "payload_kg"},
    {"name": "wingspan_m", "section": "aircraft", "key": "wingspan_m"},
    {"name": "stall_speed_m_p_s", "section": "aircraft", "key": "stall_speed_m_p_s"},
    {"name": "rotor_diameter_m", "section": "propulsion", "key": "rotor_diameter_m"},
    {"name": "tip_mach", "section": "propulsion", "key": "tip_mach"},
    {"name": "cruise_s", "section": "mission", "key": "cruise_s"},
]

# Scalar outputs, in declaration order. ``converged`` and ``sized_mtow_kg`` are
# only meaningful in sizing mode but are always present for a stable schema.
SCALAR_OUTPUTS: tuple[str, ...] = (
    "sized_mtow_kg",
    "max_takeoff_mass_kg",
    "empty_mass_kg",
    "battery_mass_kg",
    "total_mission_energy_kw_hr",
    "total_reserve_mission_energy_kw_hr",
    "payload_mass_frac",
    "peak_power_kw",
    "disk_loading_kg_p_m2",
    "converged",
)

N_SEGMENTS = len(results.SEGMENT_KEYS)
N_MASSES = len(results.MASS_COMPONENTS)


class EvtolSizingComp(om.ExplicitComponent):
    """Black-box evtolpy sizing/mission analysis as one OpenMDAO component.

    Options:
        base_config: complete 5-section evtolpy config dict (seeded by the
            factory from a template or a vendored config file).
        mode: ``"sizing"`` runs the MTOW fixed-point loop; ``"mission"`` reads
            the as-configured aircraft with no sizing.
        input_specs: list of ``{name, section, key}`` dicts naming which config
            keys are exposed as OpenMDAO inputs. Defaults to DEFAULT_INPUT_SPECS.
        record_history: in sizing mode, also expose the MTOW convergence history
            as a padded vector output + iteration count (for the convergence plot).
        max_history: padded length of the recorded MTOW history.
    """

    def initialize(self) -> None:
        self.options.declare("base_config", types=dict)
        self.options.declare("mode", default="sizing", values=("sizing", "mission"))
        self.options.declare("input_specs", default=None, types=list, allow_none=True)
        self.options.declare("record_history", default=True, types=bool)
        self.options.declare("max_history", default=150, types=int)

    def setup(self) -> None:
        specs = self.options["input_specs"]
        if specs is None:
            specs = DEFAULT_INPUT_SPECS
        self._specs = specs

        base = self.options["base_config"]
        for spec in specs:
            section, key = spec["section"], spec["key"]
            if section not in SECTIONS:
                raise ValueError(
                    f"input_spec {spec['name']!r}: unknown section {section!r} "
                    f"(expected one of {SECTIONS})"
                )
            default = float(base.get(section, {}).get(key, 0.0))
            self.add_input(spec["name"], val=default)

        for name in SCALAR_OUTPUTS:
            self.add_output(name, val=0.0)

        self.add_output("segment_energy_kw_hr", val=np.zeros(N_SEGMENTS))
        self.add_output("segment_power_kw", val=np.zeros(N_SEGMENTS))
        self.add_output("mass_breakdown_kg", val=np.zeros(N_MASSES))

        if self.options["mode"] == "sizing" and self.options["record_history"]:
            self.add_output("n_iterations", val=0.0)
            self.add_output("mtow_history_kg", val=np.zeros(self.options["max_history"]))

        # No analytic derivatives in evtolpy -- finite-difference everything.
        self.declare_partials("*", "*", method="fd")

    def _config_with_inputs(self, inputs) -> dict:
        """Deep-copy the base config and apply the exposed inputs."""
        cfg = copy.deepcopy(self.options["base_config"])
        for spec in self._specs:
            cfg.setdefault(spec["section"], {})
            cfg[spec["section"]][spec["key"]] = float(inputs[spec["name"]][0])
        return cfg

    def compute(self, inputs, outputs) -> None:
        cfg = self._config_with_inputs(inputs)
        aircraft = builders.build_aircraft(cfg)

        # Mission energy/power tables are read at the AS-CONFIGURED MTOW in both
        # modes -- this matches evtolpy's own ``log_mission_segment_*`` scripts
        # and the AIAA case study (energy/peak power are reported before sizing,
        # the sized MTOW is computed separately). Must be read BEFORE sizing,
        # which mutates ``max_takeoff_mass_kg`` in place.
        mission = results.extract_mission_results(aircraft)
        propulsion = results.extract_propulsion(aircraft)
        totals = mission["totals"]

        outputs["total_mission_energy_kw_hr"] = totals["total_mission_energy_kw_hr"]
        outputs["total_reserve_mission_energy_kw_hr"] = totals[
            "total_reserve_mission_energy_kw_hr"
        ]
        outputs["peak_power_kw"] = max(mission["avg_electric_power_kw"].values())
        outputs["disk_loading_kg_p_m2"] = propulsion["disk_loading_kg_p_m2"]
        outputs["max_takeoff_mass_kg"] = mission["max_takeoff_mass_kg"]
        outputs["segment_energy_kw_hr"] = np.array(
            [mission["energy_kw_hr"][k] for k in results.SEGMENT_KEYS]
        )
        outputs["segment_power_kw"] = np.array(
            [mission["avg_electric_power_kw"][k] for k in results.SEGMENT_KEYS]
        )

        if self.options["mode"] == "sizing":
            # Run the MTOW fixed-point loop (mutates the aircraft to the sized
            # MTOW). Masses are reported at the converged MTOW.
            sizing = results.run_mtow_iteration(aircraft)
            sized_totals = sizing["totals"]
            sized_mtow = sizing["sized_mtow_kg"]
            outputs["sized_mtow_kg"] = sized_mtow
            outputs["converged"] = 1.0 if sizing["converged"] else 0.0
            outputs["empty_mass_kg"] = sized_totals["empty_mass_kg"]
            outputs["battery_mass_kg"] = sized_totals["battery_mass_kg"]
            outputs["payload_mass_frac"] = (
                sized_totals["payload_kg"] / sized_mtow if sized_mtow else 0.0
            )
            outputs["mass_breakdown_kg"] = np.array(
                [sizing["mass_breakdown_kg"][attr] for attr, _ in results.MASS_COMPONENTS]
            )
            if self.options["record_history"]:
                history = sizing["history"]
                outputs["n_iterations"] = float(len(history))
                maxh = self.options["max_history"]
                hist = np.zeros(maxh)
                mtows = [row["new_mtow_kg"] for row in history][:maxh]
                hist[: len(mtows)] = mtows
                if mtows:
                    hist[len(mtows) :] = mtows[-1]  # pad with converged value
                outputs["mtow_history_kg"] = hist
        else:
            # Mission mode: no sizing. Masses are at the as-configured MTOW.
            outputs["sized_mtow_kg"] = mission["max_takeoff_mass_kg"]
            outputs["converged"] = 1.0
            outputs["empty_mass_kg"] = totals["empty_mass_kg"]
            outputs["battery_mass_kg"] = totals["battery_mass_kg"]
            outputs["payload_mass_frac"] = totals["payload_mass_frac"]
            outputs["mass_breakdown_kg"] = np.array(
                [mission["mass_breakdown_kg"][attr] for attr, _ in results.MASS_COMPONENTS]
            )
