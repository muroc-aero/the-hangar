"""pyCycle archetype classes for omd.

Each archetype is a pyc.Cycle subclass with hardcoded element topology,
flow connections, and balance equations. Configurable via a flat params dict.
"""

import openmdao.api as om
import pycycle.api as pyc

from hangar.omd.pyc.defaults import (
    DEFAULT_TURBOJET_PARAMS,
    DEFAULT_TURBOJET_DESIGN_GUESSES,
    DEFAULT_TURBOJET_OD_GUESSES,
    TURBOJET_META,
)
from hangar.omd.pyc.hbtf import HBTF, MPHbtf, HBTF_META
from hangar.omd.pyc.ab_turbojet import ABTurbojet, AB_TURBOJET_META
from hangar.omd.pyc.turboshaft import (
    SingleSpoolTurboshaft, SINGLE_SPOOL_TURBOSHAFT_META,
    MultiSpoolTurboshaft, MULTI_SPOOL_TURBOSHAFT_META,
)
from hangar.omd.pyc.mixedflow_turbofan import MixedFlowTurbofan, MIXEDFLOW_TURBOFAN_META


class Turbojet(pyc.Cycle):
    """Single-spool turbojet cycle.

    Elements: fc -> inlet -> comp -> burner -> turb -> nozz
    Plus shaft (2-port) and perf.

    Parameters are passed via the ``params`` option dict, with keys
    matching ``DEFAULT_TURBOJET_PARAMS``.
    """

    def initialize(self):
        self.options.declare("params", default={}, types=dict)
        super().initialize()

    def setup(self):
        params = {**DEFAULT_TURBOJET_PARAMS, **self.options["params"]}
        design = self.options["design"]

        # Thermo selection
        thermo_method = params.get("thermo_method", "TABULAR")
        if thermo_method == "TABULAR":
            self.options["thermo_method"] = "TABULAR"
            self.options["thermo_data"] = pyc.AIR_JETA_TAB_SPEC
            fuel_type = "FAR"
        else:
            self.options["thermo_method"] = "CEA"
            self.options["thermo_data"] = pyc.species_data.janaf
            fuel_type = "Jet-A(g)"

        # Elements
        self.add_subsystem("fc", pyc.FlightConditions())
        self.add_subsystem("inlet", pyc.Inlet())
        self.add_subsystem(
            "comp",
            pyc.Compressor(map_data=pyc.AXI5, map_extrap=True),
            promotes_inputs=["Nmech"],
        )
        self.add_subsystem("burner", pyc.Combustor(fuel_type=fuel_type))
        self.add_subsystem(
            "turb",
            pyc.Turbine(map_data=pyc.LPT2269),
            promotes_inputs=["Nmech"],
        )
        self.add_subsystem("nozz", pyc.Nozzle(nozzType="CD", lossCoef="Cv"))
        self.add_subsystem(
            "shaft", pyc.Shaft(num_ports=2), promotes_inputs=["Nmech"]
        )
        self.add_subsystem("perf", pyc.Performance(num_nozzles=1, num_burners=1))

        # Flow connections
        self.pyc_connect_flow("fc.Fl_O", "inlet.Fl_I", connect_w=False)
        self.pyc_connect_flow("inlet.Fl_O", "comp.Fl_I")
        self.pyc_connect_flow("comp.Fl_O", "burner.Fl_I")
        self.pyc_connect_flow("burner.Fl_O", "turb.Fl_I")
        self.pyc_connect_flow("turb.Fl_O", "nozz.Fl_I")

        # Mechanical connections
        self.connect("comp.trq", "shaft.trq_0")
        self.connect("turb.trq", "shaft.trq_1")

        # Nozzle exhaust pressure
        self.connect("fc.Fl_O:stat:P", "nozz.Ps_exhaust")

        # Performance connections
        self.connect("inlet.Fl_O:tot:P", "perf.Pt2")
        self.connect("comp.Fl_O:tot:P", "perf.Pt3")
        self.connect("burner.Wfuel", "perf.Wfuel_0")
        self.connect("inlet.F_ram", "perf.ram_drag")
        self.connect("nozz.Fg", "perf.Fg_0")

        # Balances
        balance = self.add_subsystem("balance", om.BalanceComp())
        if design:
            balance.add_balance(
                "W", units="lbm/s", eq_units="lbf", rhs_name="Fn_target"
            )
            self.connect("balance.W", "inlet.Fl_I:stat:W")
            self.connect("perf.Fn", "balance.lhs:W")

            balance.add_balance(
                "FAR", eq_units="degR", lower=1e-4, val=0.017, rhs_name="T4_target"
            )
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR")

            balance.add_balance(
                "turb_PR", val=1.5, lower=1.001, upper=8, eq_units="hp", rhs_val=0.0
            )
            self.connect("balance.turb_PR", "turb.PR")
            self.connect("shaft.pwr_net", "balance.lhs:turb_PR")
        else:
            balance.add_balance(
                "FAR", eq_units="lbf", lower=1e-4, val=0.3, rhs_name="Fn_target"
            )
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("perf.Fn", "balance.lhs:FAR")

            balance.add_balance(
                "Nmech", val=1.5, units="rpm", lower=500.0, eq_units="hp", rhs_val=0.0
            )
            self.connect("balance.Nmech", "Nmech")
            self.connect("shaft.pwr_net", "balance.lhs:Nmech")

            balance.add_balance("W", val=168.0, units="lbm/s", eq_units="inch**2")
            self.connect("balance.W", "inlet.Fl_I:stat:W")
            self.connect("nozz.Throat:stat:area", "balance.lhs:W")

        # Solver
        newton = self.nonlinear_solver = om.NewtonSolver()
        newton.options["atol"] = 1e-6
        newton.options["rtol"] = 1e-6
        newton.options["iprint"] = params.get("solver_iprint", -1)
        newton.options["maxiter"] = 15
        newton.options["solve_subsystems"] = True
        newton.options["max_sub_solves"] = 100
        newton.options["reraise_child_analysiserror"] = False

        self.linear_solver = om.DirectSolver()

        # Store params for guess_nonlinear
        self._params = params

        super().setup()

    def guess_nonlinear(self, inputs, outputs, residuals):
        """Apply Newton initial guesses at the start of every solve.

        When this Cycle is embedded inside an outer Newton (e.g. OCP
        mission solver), a one-time set_val before run_model gets
        overwritten by the outer solver before the inner Newton
        converges. This method runs at the start of every Newton solve
        loop, ensuring the balance variables start from good values.

        The FlightConditions balance variables (Pt, Tt) are critical --
        without them the FC sub-solver diverges, which cascades into
        wrong flow station values for the rest of the cycle.
        """
        design = self.options["design"]
        if design:
            outputs["balance.FAR"] = DEFAULT_TURBOJET_DESIGN_GUESSES["FAR"]
            outputs["balance.W"] = DEFAULT_TURBOJET_DESIGN_GUESSES["W"]
            outputs["balance.turb_PR"] = DEFAULT_TURBOJET_DESIGN_GUESSES["turb_PR"]
            outputs["fc.balance.Pt"] = DEFAULT_TURBOJET_DESIGN_GUESSES["fc_Pt"]
            outputs["fc.balance.Tt"] = DEFAULT_TURBOJET_DESIGN_GUESSES["fc_Tt"]
        else:
            outputs["balance.FAR"] = DEFAULT_TURBOJET_OD_GUESSES["FAR"]
            outputs["balance.W"] = DEFAULT_TURBOJET_OD_GUESSES["W"]
            outputs["balance.Nmech"] = DEFAULT_TURBOJET_OD_GUESSES["Nmech"]
            outputs["fc.balance.Pt"] = DEFAULT_TURBOJET_OD_GUESSES["fc_Pt"]
            outputs["fc.balance.Tt"] = DEFAULT_TURBOJET_OD_GUESSES["fc_Tt"]


class MPTurbojet(pyc.MPCycle):
    """Multi-point turbojet: one design point + N off-design points.

    Options
    -------
    params : dict
        Cycle parameters (merged with defaults).
    od_points : list[dict]
        Off-design points, each with keys: name, MN, alt, Fn_target.
    """

    def initialize(self):
        self.options.declare("params", default={}, types=dict)
        self.options.declare("od_points", default=[], types=list)
        super().initialize()

    def setup(self):
        params = {**DEFAULT_TURBOJET_PARAMS, **self.options["params"]}
        od_points = self.options["od_points"]

        # Design point
        self.pyc_add_pnt("DESIGN", Turbojet(params=params))

        self.set_input_defaults("DESIGN.Nmech", params["Nmech"], units="rpm")
        self.set_input_defaults("DESIGN.inlet.MN", params.get("inlet_MN", 0.60))
        self.set_input_defaults("DESIGN.comp.MN", params.get("comp_MN", 0.02))
        self.set_input_defaults("DESIGN.burner.MN", params.get("burner_MN", 0.02))
        self.set_input_defaults("DESIGN.turb.MN", params.get("turb_MN", 0.4))

        # Cycle parameters (shared design/off-design)
        self.pyc_add_cycle_param("burner.dPqP", params["burner_dPqP"])
        self.pyc_add_cycle_param("nozz.Cv", params["nozz_Cv"])

        # Off-design points
        self.od_pts = []
        for od in od_points:
            pt_name = od["name"]
            self.od_pts.append(pt_name)
            self.pyc_add_pnt(pt_name, Turbojet(design=False, params=params))
            self.set_input_defaults(f"{pt_name}.fc.MN", val=od["MN"])
            self.set_input_defaults(f"{pt_name}.fc.alt", od["alt"], units="ft")
            self.set_input_defaults(
                f"{pt_name}.balance.Fn_target", od["Fn_target"], units="lbf"
            )

        # Standard design -> off-design connections
        self.pyc_use_default_des_od_conns()
        self.pyc_connect_des_od("nozz.Throat:stat:area", "balance.rhs:W")

        super().setup()


# ---------------------------------------------------------------------------
# Archetype registry
# ---------------------------------------------------------------------------

ARCHETYPES = {
    "turbojet": {
        "class": Turbojet,
        "mp_class": MPTurbojet,
        **TURBOJET_META,
    },
    "hbtf": {
        "class": HBTF,
        "mp_class": MPHbtf,
        **HBTF_META,
    },
    "ab_turbojet": {
        "class": ABTurbojet,
        **AB_TURBOJET_META,
    },
    "single_spool_turboshaft": {
        "class": SingleSpoolTurboshaft,
        **SINGLE_SPOOL_TURBOSHAFT_META,
    },
    "multi_spool_turboshaft": {
        "class": MultiSpoolTurboshaft,
        **MULTI_SPOOL_TURBOSHAFT_META,
    },
    "mixedflow_turbofan": {
        "class": MixedFlowTurbofan,
        **MIXEDFLOW_TURBOFAN_META,
    },
}


def get_archetype(name: str) -> dict:
    """Look up an archetype by name, raising ValueError if unknown."""
    if name not in ARCHETYPES:
        valid = ", ".join(sorted(ARCHETYPES))
        raise ValueError(
            f"Unknown archetype {name!r}. Valid archetypes: {valid}"
        )
    return ARCHETYPES[name]
