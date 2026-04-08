"""Turboshaft archetypes.

Single-spool and multi-spool turboshaft engines ported from upstream
pyCycle example_cycles/.
"""

import openmdao.api as om
import pycycle.api as pyc

from hangar.omd.pyc.defaults import DEFAULT_TURBOJET_PARAMS


# ---------------------------------------------------------------------------
# Single-spool turboshaft
# ---------------------------------------------------------------------------

class SingleSpoolTurboshaft(pyc.Cycle):
    """Single-spool turboshaft with free power turbine.

    HP spool: comp + turb. LP spool: power turbine (pt) only.
    Elements: fc -> inlet -> comp -> burner -> turb -> pt -> nozz
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
            fuel_type = "JP-7"

        self.add_subsystem("fc", pyc.FlightConditions())
        self.add_subsystem("inlet", pyc.Inlet())
        self.add_subsystem("comp", pyc.Compressor(map_data=pyc.AXI5,
                           map_extrap=True),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("burner", pyc.Combustor(fuel_type=fuel_type))
        self.add_subsystem("turb", pyc.Turbine(map_data=pyc.LPT2269,
                           map_extrap=True),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("pt", pyc.Turbine(map_data=pyc.LPT2269,
                           map_extrap=True),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("nozz", pyc.Nozzle(nozzType="CV", lossCoef="Cv"))
        self.add_subsystem("HP_shaft", pyc.Shaft(num_ports=2),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("LP_shaft", pyc.Shaft(num_ports=1),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("perf", pyc.Performance(num_nozzles=1, num_burners=1))

        # Flow connections
        self.pyc_connect_flow("fc.Fl_O", "inlet.Fl_I", connect_w=False)
        self.pyc_connect_flow("inlet.Fl_O", "comp.Fl_I")
        self.pyc_connect_flow("comp.Fl_O", "burner.Fl_I")
        self.pyc_connect_flow("burner.Fl_O", "turb.Fl_I")
        self.pyc_connect_flow("turb.Fl_O", "pt.Fl_I")
        self.pyc_connect_flow("pt.Fl_O", "nozz.Fl_I")

        # Shaft connections
        self.connect("comp.trq", "HP_shaft.trq_0")
        self.connect("turb.trq", "HP_shaft.trq_1")
        self.connect("pt.trq", "LP_shaft.trq_0")
        self.connect("fc.Fl_O:stat:P", "nozz.Ps_exhaust")

        # Performance connections
        self.connect("inlet.Fl_O:tot:P", "perf.Pt2")
        self.connect("comp.Fl_O:tot:P", "perf.Pt3")
        self.connect("burner.Wfuel", "perf.Wfuel_0")
        self.connect("inlet.F_ram", "perf.ram_drag")
        self.connect("nozz.Fg", "perf.Fg_0")
        self.connect("LP_shaft.pwr_net", "perf.power")

        # Balances
        balance = self.add_subsystem("balance", om.BalanceComp())
        if design:
            balance.add_balance("W", val=27.0, units="lbm/s",
                                eq_units=None, rhs_name="nozz_PR_target")
            self.connect("balance.W", "inlet.Fl_I:stat:W")
            self.connect("nozz.PR", "balance.lhs:W")

            balance.add_balance("FAR", eq_units="degR", lower=1e-4,
                                val=0.017, rhs_name="T4_target")
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR")

            balance.add_balance("turb_PR", val=3.0, lower=1.001, upper=8,
                                eq_units="hp", rhs_val=0.0)
            self.connect("balance.turb_PR", "turb.PR")
            self.connect("HP_shaft.pwr_net", "balance.lhs:turb_PR")

            balance.add_balance("pt_PR", val=3.0, lower=1.001, upper=8,
                                eq_units="hp", rhs_name="pwr_target")
            self.connect("balance.pt_PR", "pt.PR")
            self.connect("LP_shaft.pwr_net", "balance.lhs:pt_PR")
        else:
            balance.add_balance("FAR", eq_units="hp", lower=1e-4,
                                val=0.3, rhs_name="pwr_target")
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("LP_shaft.pwr_net", "balance.lhs:FAR")

            balance.add_balance("HP_Nmech", val=1.5, units="rpm",
                                lower=500.0, eq_units="hp", rhs_val=0.0)
            self.connect("balance.HP_Nmech", "HP_Nmech")
            self.connect("HP_shaft.pwr_net", "balance.lhs:HP_Nmech")

            balance.add_balance("W", val=27.0, units="lbm/s",
                                eq_units="inch**2")
            self.connect("balance.W", "inlet.Fl_I:stat:W")
            self.connect("nozz.Throat:stat:area", "balance.lhs:W")

        self.set_order(["fc", "inlet", "comp", "burner", "turb", "pt",
                         "nozz", "HP_shaft", "LP_shaft", "perf", "balance"])

        newton = self.nonlinear_solver = om.NewtonSolver()
        newton.options["atol"] = 1e-6
        newton.options["rtol"] = 1e-6
        newton.options["iprint"] = params.get("solver_iprint", -1)
        newton.options["maxiter"] = 25
        newton.options["solve_subsystems"] = True
        newton.options["max_sub_solves"] = 100
        newton.options["reraise_child_analysiserror"] = False
        newton.linesearch = om.ArmijoGoldsteinLS()
        newton.linesearch.options["iprint"] = -1
        newton.linesearch.options["maxiter"] = 3
        newton.linesearch.options["rho"] = 0.75

        self.linear_solver = om.DirectSolver()

        super().setup()


SINGLE_SPOOL_TURBOSHAFT_META = {
    "description": "Single-spool turboshaft with free power turbine",
    "elements": ["fc", "inlet", "comp", "burner", "turb", "pt", "nozz",
                 "HP_shaft", "LP_shaft", "perf"],
    "flow_stations": [
        "fc.Fl_O", "inlet.Fl_O", "comp.Fl_O", "burner.Fl_O",
        "turb.Fl_O", "pt.Fl_O", "nozz.Fl_O",
    ],
    "compressors": ["comp"],
    "turbines": ["turb", "pt"],
    "burners": ["burner"],
    "shafts": ["HP_shaft", "LP_shaft"],
    "nozzles": ["nozz"],
}


# ---------------------------------------------------------------------------
# Multi-spool turboshaft
# ---------------------------------------------------------------------------

class MultiSpoolTurboshaft(pyc.Cycle):
    """Three-spool turboshaft: LP (PT), IP (LPC+LPT), HP (2xHPC+HPT).

    Elements: fc -> inlet -> duct1 -> lpc -> icduct -> hpc_axi -> bld25 ->
              hpc_centri -> bld3 -> duct6 -> burner -> hpt -> duct43 ->
              lpt -> itduct -> pt -> duct12 -> nozzle
    """

    def initialize(self):
        self.options.declare("params", default={}, types=dict)
        self.options.declare("maxiter", default=10)
        super().initialize()

    def setup(self):
        params = self.options["params"]
        design = self.options["design"]
        maxiter = self.options["maxiter"]

        self.options["thermo_method"] = "CEA"
        self.options["thermo_data"] = pyc.species_data.janaf

        self.add_subsystem("fc", pyc.FlightConditions())
        self.add_subsystem("inlet", pyc.Inlet())
        self.add_subsystem("duct1", pyc.Duct())
        self.add_subsystem("lpc", pyc.Compressor(map_data=pyc.LPCMap),
                           promotes_inputs=[("Nmech", "IP_Nmech")])
        self.add_subsystem("icduct", pyc.Duct())
        self.add_subsystem("hpc_axi", pyc.Compressor(map_data=pyc.HPCMap),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("bld25", pyc.BleedOut(bleed_names=["cool1", "cool2"]))
        self.add_subsystem("hpc_centri", pyc.Compressor(map_data=pyc.HPCMap),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("bld3", pyc.BleedOut(bleed_names=["cool3", "cool4"]))
        self.add_subsystem("duct6", pyc.Duct())
        self.add_subsystem("burner", pyc.Combustor(fuel_type="Jet-A(g)"))
        self.add_subsystem("hpt", pyc.Turbine(map_data=pyc.HPTMap,
                           bleed_names=["cool3", "cool4"]),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("duct43", pyc.Duct())
        self.add_subsystem("lpt", pyc.Turbine(map_data=pyc.LPTMap,
                           bleed_names=["cool1", "cool2"]),
                           promotes_inputs=[("Nmech", "IP_Nmech")])
        self.add_subsystem("itduct", pyc.Duct())
        self.add_subsystem("pt", pyc.Turbine(map_data=pyc.LPTMap),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("duct12", pyc.Duct())
        self.add_subsystem("nozzle", pyc.Nozzle(nozzType="CV", lossCoef="Cv"))

        self.add_subsystem("lp_shaft", pyc.Shaft(num_ports=1),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("ip_shaft", pyc.Shaft(num_ports=2),
                           promotes_inputs=[("Nmech", "IP_Nmech")])
        self.add_subsystem("hp_shaft", pyc.Shaft(num_ports=3),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("perf", pyc.Performance(num_nozzles=1, num_burners=1))

        # Performance connections
        self.connect("duct1.Fl_O:tot:P", "perf.Pt2")
        self.connect("hpc_centri.Fl_O:tot:P", "perf.Pt3")
        self.connect("burner.Wfuel", "perf.Wfuel_0")
        self.connect("inlet.F_ram", "perf.ram_drag")
        self.connect("nozzle.Fg", "perf.Fg_0")
        self.connect("lp_shaft.pwr_in", "perf.power")

        # Shaft connections
        self.connect("pt.trq", "lp_shaft.trq_0")
        self.connect("lpc.trq", "ip_shaft.trq_0")
        self.connect("lpt.trq", "ip_shaft.trq_1")
        self.connect("hpc_axi.trq", "hp_shaft.trq_0")
        self.connect("hpc_centri.trq", "hp_shaft.trq_1")
        self.connect("hpt.trq", "hp_shaft.trq_2")
        self.connect("fc.Fl_O:stat:P", "nozzle.Ps_exhaust")

        # Balances
        balance = self.add_subsystem("balance", om.BalanceComp())
        if design:
            balance.add_balance("W", units="lbm/s", eq_units=None)
            self.connect("balance.W", "inlet.Fl_I:stat:W")
            self.connect("nozzle.PR", "balance.lhs:W")

            balance.add_balance("FAR", eq_units="degR", lower=1e-4, val=0.017)
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR")

            balance.add_balance("lpt_PR", val=1.5, lower=1.001, upper=8,
                                eq_units="hp", rhs_val=0.0)
            self.connect("balance.lpt_PR", "lpt.PR")
            self.connect("ip_shaft.pwr_net", "balance.lhs:lpt_PR")

            balance.add_balance("hpt_PR", val=1.5, lower=1.001, upper=8,
                                eq_units="hp", rhs_val=0.0)
            self.connect("balance.hpt_PR", "hpt.PR")
            self.connect("hp_shaft.pwr_net", "balance.lhs:hpt_PR")

            balance.add_balance("pt_PR", val=1.5, lower=1.001, upper=8,
                                eq_units="hp", rhs_val=0.0)
            self.connect("balance.pt_PR", "pt.PR")
            self.connect("lp_shaft.pwr_net", "balance.lhs:pt_PR")
        else:
            balance.add_balance("FAR", eq_units="hp", lower=1e-4, val=0.017)
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("lp_shaft.pwr_net", "balance.lhs:FAR")

            balance.add_balance("W", units="lbm/s", eq_units="inch**2")
            self.connect("balance.W", "inlet.Fl_I:stat:W")
            self.connect("nozzle.Throat:stat:area", "balance.lhs:W")

            balance.add_balance("IP_Nmech", val=12000.0, units="rpm",
                                lower=1.001, eq_units="hp", rhs_val=0.0)
            self.connect("balance.IP_Nmech", "IP_Nmech")
            self.connect("ip_shaft.pwr_net", "balance.lhs:IP_Nmech")

            balance.add_balance("HP_Nmech", val=14800.0, units="rpm",
                                lower=1.001, eq_units="hp", rhs_val=0.0)
            self.connect("balance.HP_Nmech", "HP_Nmech")
            self.connect("hp_shaft.pwr_net", "balance.lhs:HP_Nmech")

        # Flow connections
        self.pyc_connect_flow("fc.Fl_O", "inlet.Fl_I", connect_w=False)
        self.pyc_connect_flow("inlet.Fl_O", "duct1.Fl_I")
        self.pyc_connect_flow("duct1.Fl_O", "lpc.Fl_I")
        self.pyc_connect_flow("lpc.Fl_O", "icduct.Fl_I")
        self.pyc_connect_flow("icduct.Fl_O", "hpc_axi.Fl_I")
        self.pyc_connect_flow("hpc_axi.Fl_O", "bld25.Fl_I")
        self.pyc_connect_flow("bld25.Fl_O", "hpc_centri.Fl_I")
        self.pyc_connect_flow("hpc_centri.Fl_O", "bld3.Fl_I")
        self.pyc_connect_flow("bld3.Fl_O", "duct6.Fl_I")
        self.pyc_connect_flow("duct6.Fl_O", "burner.Fl_I")
        self.pyc_connect_flow("burner.Fl_O", "hpt.Fl_I")
        self.pyc_connect_flow("hpt.Fl_O", "duct43.Fl_I")
        self.pyc_connect_flow("duct43.Fl_O", "lpt.Fl_I")
        self.pyc_connect_flow("lpt.Fl_O", "itduct.Fl_I")
        self.pyc_connect_flow("itduct.Fl_O", "pt.Fl_I")
        self.pyc_connect_flow("pt.Fl_O", "duct12.Fl_I")
        self.pyc_connect_flow("duct12.Fl_O", "nozzle.Fl_I")

        # Bleed flows
        self.pyc_connect_flow("bld25.cool1", "lpt.cool1", connect_stat=False)
        self.pyc_connect_flow("bld25.cool2", "lpt.cool2", connect_stat=False)
        self.pyc_connect_flow("bld3.cool3", "hpt.cool3", connect_stat=False)
        self.pyc_connect_flow("bld3.cool4", "hpt.cool4", connect_stat=False)

        # Solver
        newton = self.nonlinear_solver = om.NewtonSolver()
        newton.options["atol"] = 1e-6
        newton.options["rtol"] = 1e-6
        newton.options["iprint"] = params.get("solver_iprint", -1)
        newton.options["maxiter"] = maxiter
        newton.options["solve_subsystems"] = True
        newton.options["max_sub_solves"] = 100
        newton.options["reraise_child_analysiserror"] = False
        newton.linesearch = om.BoundsEnforceLS()
        newton.linesearch.options["bound_enforcement"] = "scalar"
        newton.linesearch.options["iprint"] = -1

        self.linear_solver = om.DirectSolver()

        super().setup()


MULTI_SPOOL_TURBOSHAFT_META = {
    "description": "Three-spool turboshaft (LP/PT, IP, HP)",
    "elements": ["fc", "inlet", "duct1", "lpc", "icduct", "hpc_axi",
                 "bld25", "hpc_centri", "bld3", "duct6", "burner", "hpt",
                 "duct43", "lpt", "itduct", "pt", "duct12", "nozzle",
                 "lp_shaft", "ip_shaft", "hp_shaft", "perf"],
    "flow_stations": [
        "fc.Fl_O", "inlet.Fl_O", "duct1.Fl_O", "lpc.Fl_O",
        "icduct.Fl_O", "hpc_axi.Fl_O", "bld25.Fl_O",
        "hpc_centri.Fl_O", "bld3.Fl_O", "duct6.Fl_O",
        "burner.Fl_O", "hpt.Fl_O", "duct43.Fl_O", "lpt.Fl_O",
        "itduct.Fl_O", "pt.Fl_O", "duct12.Fl_O", "nozzle.Fl_O",
    ],
    "compressors": ["lpc", "hpc_axi", "hpc_centri"],
    "turbines": ["hpt", "lpt", "pt"],
    "burners": ["burner"],
    "shafts": ["lp_shaft", "ip_shaft", "hp_shaft"],
    "nozzles": ["nozzle"],
}
