"""Afterburning turbojet archetype.

Ported from upstream pyCycle example_cycles/afterburning_turbojet.py.
Single-spool with afterburner and CD nozzle.
"""

import openmdao.api as om
import pycycle.api as pyc

from hangar.omd.pyc.defaults import DEFAULT_TURBOJET_PARAMS


class ABTurbojet(pyc.Cycle):
    """Afterburning single-spool turbojet.

    Elements: fc -> inlet -> duct1 -> comp -> burner -> turb -> ab -> nozz
    Plus shaft and perf. Compressor bleeds cool turbine.
    """

    def initialize(self):
        self.options.declare("params", default={}, types=dict)
        super().initialize()

    def setup(self):
        params = {**DEFAULT_TURBOJET_PARAMS, **self.options["params"]}
        design = self.options["design"]

        thermo_method = params.get("thermo_method", "CEA")
        if thermo_method == "TABULAR":
            self.options["thermo_method"] = "TABULAR"
            self.options["thermo_data"] = pyc.AIR_JETA_TAB_SPEC
            fuel_type = "FAR"
        else:
            self.options["thermo_method"] = "CEA"
            self.options["thermo_data"] = pyc.species_data.janaf
            fuel_type = "Jet-A(g)"

        self.add_subsystem("fc", pyc.FlightConditions())
        self.add_subsystem("inlet", pyc.Inlet())
        self.add_subsystem("duct1", pyc.Duct())
        self.add_subsystem("comp", pyc.Compressor(map_data=pyc.AXI5,
                           bleed_names=["cool1", "cool2"], map_extrap=True),
                           promotes_inputs=["Nmech"])
        self.add_subsystem("burner", pyc.Combustor(fuel_type=fuel_type))
        self.add_subsystem("turb", pyc.Turbine(map_data=pyc.LPT2269,
                           bleed_names=["cool1", "cool2"], map_extrap=True),
                           promotes_inputs=["Nmech"])
        self.add_subsystem("ab", pyc.Combustor(fuel_type=fuel_type))
        self.add_subsystem("nozz", pyc.Nozzle(nozzType="CD", lossCoef="Cv",
                           internal_solver=True))
        self.add_subsystem("shaft", pyc.Shaft(num_ports=2),
                           promotes_inputs=["Nmech"])
        self.add_subsystem("perf", pyc.Performance(num_nozzles=1, num_burners=2))

        self.connect("duct1.Fl_O:tot:P", "perf.Pt2")
        self.connect("comp.Fl_O:tot:P", "perf.Pt3")
        self.connect("burner.Wfuel", "perf.Wfuel_0")
        self.connect("ab.Wfuel", "perf.Wfuel_1")
        self.connect("inlet.F_ram", "perf.ram_drag")
        self.connect("nozz.Fg", "perf.Fg_0")

        self.connect("comp.trq", "shaft.trq_0")
        self.connect("turb.trq", "shaft.trq_1")
        self.connect("fc.Fl_O:stat:P", "nozz.Ps_exhaust")

        balance = self.add_subsystem("balance", om.BalanceComp())
        if design:
            balance.add_balance("W", units="lbm/s", eq_units="lbf")
            self.connect("balance.W", "inlet.Fl_I:stat:W")
            self.connect("perf.Fn", "balance.lhs:W")

            balance.add_balance("FAR", eq_units="degR", lower=1e-4, val=0.017)
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR")

            balance.add_balance("turb_PR", val=1.5, lower=1.001, upper=8,
                                eq_units="hp", rhs_val=0.0)
            self.connect("balance.turb_PR", "turb.PR")
            self.connect("shaft.pwr_net", "balance.lhs:turb_PR")

            self.set_order(["fc", "inlet", "duct1", "comp", "burner", "turb",
                            "ab", "nozz", "shaft", "perf", "balance"])
        else:
            balance.add_balance("FAR", eq_units="degR", lower=1e-4, val=0.017)
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR")

            balance.add_balance("Nmech", val=8000.0, units="rpm", lower=500.0,
                                upper=10000.0, eq_units="hp",
                                use_mult=True, mult_val=-1)
            self.connect("balance.Nmech", "Nmech")
            self.connect("shaft.pwr_in", "balance.lhs:Nmech")
            self.connect("shaft.pwr_out", "balance.rhs:Nmech")

            balance.add_balance("W", val=100.0, units="lbm/s",
                                eq_units=None, rhs_val=2.0)
            self.connect("balance.W", "inlet.Fl_I:stat:W")
            self.connect("comp.map.RlineMap", "balance.lhs:W")

            self.set_order(["fc", "inlet", "duct1", "comp", "burner", "turb",
                            "ab", "nozz", "shaft", "perf", "balance"])

        # Flow connections
        self.pyc_connect_flow("fc.Fl_O", "inlet.Fl_I", connect_w=False)
        self.pyc_connect_flow("inlet.Fl_O", "duct1.Fl_I", connect_stat=False)
        self.pyc_connect_flow("duct1.Fl_O", "comp.Fl_I", connect_stat=False)
        self.pyc_connect_flow("comp.Fl_O", "burner.Fl_I", connect_stat=False)
        self.pyc_connect_flow("burner.Fl_O", "turb.Fl_I", connect_stat=False)
        self.pyc_connect_flow("turb.Fl_O", "ab.Fl_I", connect_stat=False)
        self.pyc_connect_flow("ab.Fl_O", "nozz.Fl_I", connect_stat=False)

        self.pyc_connect_flow("comp.cool1", "turb.cool1", connect_stat=False)
        self.pyc_connect_flow("comp.cool2", "turb.cool2", connect_stat=False)

        newton = self.nonlinear_solver = om.NewtonSolver()
        newton.options["atol"] = 1e-6
        newton.options["rtol"] = 1e-6
        newton.options["iprint"] = params.get("solver_iprint", -1)
        newton.options["maxiter"] = 50
        newton.options["solve_subsystems"] = True
        newton.options["max_sub_solves"] = 100
        newton.options["reraise_child_analysiserror"] = False
        newton.linesearch = om.ArmijoGoldsteinLS()
        newton.linesearch.options["rho"] = 0.75
        newton.linesearch.options["iprint"] = -1

        self.linear_solver = om.DirectSolver()

        super().setup()


AB_TURBOJET_META = {
    "description": "Afterburning single-spool turbojet (with CD nozzle)",
    "elements": ["fc", "inlet", "duct1", "comp", "burner", "turb", "ab",
                 "nozz", "shaft", "perf"],
    "flow_stations": [
        "fc.Fl_O", "inlet.Fl_O", "duct1.Fl_O", "comp.Fl_O",
        "burner.Fl_O", "turb.Fl_O", "ab.Fl_O", "nozz.Fl_O",
    ],
    "compressors": ["comp"],
    "turbines": ["turb"],
    "burners": ["burner", "ab"],
    "shafts": ["shaft"],
    "nozzles": ["nozz"],
}
