"""Mixed-flow turbofan archetype.

Ported from upstream pyCycle example_cycles/mixedflow_turbofan.py.
Dual-spool with mixer, afterburner, and single CD nozzle.
"""

import openmdao.api as om
import pycycle.api as pyc

from hangar.omd.pyc.defaults import DEFAULT_HBTF_PARAMS


class MixedFlowTurbofan(pyc.Cycle):
    """Mixed-flow turbofan with afterburner.

    Core and bypass streams merge in mixer before afterburner/nozzle.
    Dual-spool: LP (fan + LPC + LPT) and HP (HPC + HPT).
    """

    def initialize(self):
        self.options.declare("params", default={}, types=dict)
        super().initialize()

    def setup(self):
        params = {**DEFAULT_HBTF_PARAMS, **self.options["params"]}
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

        # Elements
        self.add_subsystem("fc", pyc.FlightConditions())
        self.add_subsystem("inlet", pyc.Inlet())
        self.add_subsystem("inlet_duct", pyc.Duct())
        self.add_subsystem("fan", pyc.Compressor(map_data=pyc.AXI5,
                           map_extrap=True),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("splitter", pyc.Splitter())
        self.add_subsystem("splitter_core_duct", pyc.Duct())
        self.add_subsystem("lpc", pyc.Compressor(map_data=pyc.LPCMap,
                           map_extrap=True),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("lpc_duct", pyc.Duct())
        self.add_subsystem("hpc", pyc.Compressor(map_data=pyc.HPCMap,
                           bleed_names=["cool1"], map_extrap=True),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("bld3", pyc.BleedOut(bleed_names=["cool3"]))
        self.add_subsystem("burner", pyc.Combustor(fuel_type=fuel_type))
        self.add_subsystem("hpt", pyc.Turbine(map_data=pyc.HPTMap,
                           bleed_names=["cool3"], map_extrap=True),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("hpt_duct", pyc.Duct())
        self.add_subsystem("lpt", pyc.Turbine(map_data=pyc.LPTMap,
                           bleed_names=["cool1"], map_extrap=True),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("lpt_duct", pyc.Duct())
        self.add_subsystem("bypass_duct", pyc.Duct())
        self.add_subsystem("mixer", pyc.Mixer(designed_stream=1))
        self.add_subsystem("mixer_duct", pyc.Duct())
        self.add_subsystem("afterburner", pyc.Combustor(fuel_type=fuel_type))
        self.add_subsystem("mixed_nozz", pyc.Nozzle(nozzType="CD", lossCoef="Cfg"))
        self.add_subsystem("lp_shaft", pyc.Shaft(num_ports=3),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("hp_shaft", pyc.Shaft(num_ports=2),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("perf", pyc.Performance(num_nozzles=1, num_burners=2))

        # Flow connections
        self.pyc_connect_flow("fc.Fl_O", "inlet.Fl_I")
        self.pyc_connect_flow("inlet.Fl_O", "inlet_duct.Fl_I")
        self.pyc_connect_flow("inlet_duct.Fl_O", "fan.Fl_I")
        self.pyc_connect_flow("fan.Fl_O", "splitter.Fl_I")
        self.pyc_connect_flow("splitter.Fl_O1", "splitter_core_duct.Fl_I")
        self.pyc_connect_flow("splitter_core_duct.Fl_O", "lpc.Fl_I")
        self.pyc_connect_flow("lpc.Fl_O", "lpc_duct.Fl_I")
        self.pyc_connect_flow("lpc_duct.Fl_O", "hpc.Fl_I")
        self.pyc_connect_flow("hpc.Fl_O", "bld3.Fl_I")
        self.pyc_connect_flow("bld3.Fl_O", "burner.Fl_I")
        self.pyc_connect_flow("burner.Fl_O", "hpt.Fl_I")
        self.pyc_connect_flow("hpt.Fl_O", "hpt_duct.Fl_I")
        self.pyc_connect_flow("hpt_duct.Fl_O", "lpt.Fl_I")
        self.pyc_connect_flow("lpt.Fl_O", "lpt_duct.Fl_I")
        self.pyc_connect_flow("lpt_duct.Fl_O", "mixer.Fl_I1")
        self.pyc_connect_flow("splitter.Fl_O2", "bypass_duct.Fl_I")
        self.pyc_connect_flow("bypass_duct.Fl_O", "mixer.Fl_I2")
        self.pyc_connect_flow("mixer.Fl_O", "mixer_duct.Fl_I")
        self.pyc_connect_flow("mixer_duct.Fl_O", "afterburner.Fl_I")
        self.pyc_connect_flow("afterburner.Fl_O", "mixed_nozz.Fl_I")

        # Bleed flows
        self.pyc_connect_flow("hpc.cool1", "lpt.cool1", connect_stat=False)
        self.pyc_connect_flow("bld3.cool3", "hpt.cool3", connect_stat=False)

        # Performance connections
        self.connect("inlet.Fl_O:tot:P", "perf.Pt2")
        self.connect("hpc.Fl_O:tot:P", "perf.Pt3")
        self.connect("burner.Wfuel", "perf.Wfuel_0")
        self.connect("afterburner.Wfuel", "perf.Wfuel_1")
        self.connect("inlet.F_ram", "perf.ram_drag")
        self.connect("mixed_nozz.Fg", "perf.Fg_0")

        # Shaft connections
        self.connect("fan.trq", "lp_shaft.trq_0")
        self.connect("lpc.trq", "lp_shaft.trq_1")
        self.connect("lpt.trq", "lp_shaft.trq_2")
        self.connect("hpc.trq", "hp_shaft.trq_0")
        self.connect("hpt.trq", "hp_shaft.trq_1")
        self.connect("fc.Fl_O:stat:P", "mixed_nozz.Ps_exhaust")

        # Balances
        balance = self.add_subsystem("balance", om.BalanceComp())
        if design:
            balance.add_balance("W", lower=1e-3, upper=200.0,
                                units="lbm/s", eq_units="lbf")
            self.connect("balance.W", "fc.W")
            self.connect("perf.Fn", "balance.lhs:W")

            balance.add_balance("BPR", eq_units=None, lower=0.25, val=5.0)
            self.connect("balance.BPR", "splitter.BPR")
            self.connect("mixer.ER", "balance.lhs:BPR")

            balance.add_balance("FAR_core", eq_units="degR", lower=1e-4, val=0.017)
            self.connect("balance.FAR_core", "burner.Fl_I:FAR")
            self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR_core")

            balance.add_balance("FAR_ab", eq_units="degR", lower=1e-4, val=0.017)
            self.connect("balance.FAR_ab", "afterburner.Fl_I:FAR")
            self.connect("afterburner.Fl_O:tot:T", "balance.lhs:FAR_ab")

            balance.add_balance("lpt_PR", val=1.5, lower=1.001, upper=8,
                                eq_units="hp", use_mult=True, mult_val=-1)
            self.connect("balance.lpt_PR", "lpt.PR")
            self.connect("lp_shaft.pwr_in", "balance.lhs:lpt_PR")
            self.connect("lp_shaft.pwr_out", "balance.rhs:lpt_PR")

            balance.add_balance("hpt_PR", val=1.5, lower=1.001, upper=8,
                                eq_units="hp", use_mult=True, mult_val=-1)
            self.connect("balance.hpt_PR", "hpt.PR")
            self.connect("hp_shaft.pwr_in", "balance.lhs:hpt_PR")
            self.connect("hp_shaft.pwr_out", "balance.rhs:hpt_PR")
        else:
            balance.add_balance("W", lower=1e-3, upper=200.0,
                                units="lbm/s", eq_units="inch**2")
            self.connect("balance.W", "fc.W")
            self.connect("mixed_nozz.Throat:stat:area", "balance.lhs:W")

            balance.add_balance("BPR", lower=0.25, upper=5.0, eq_units="psi")
            self.connect("balance.BPR", "splitter.BPR")
            self.connect("mixer.Fl_I1_calc:stat:P", "balance.lhs:BPR")
            self.connect("bypass_duct.Fl_O:stat:P", "balance.rhs:BPR")

            balance.add_balance("FAR_core", eq_units="degR", lower=1e-4,
                                upper=0.06, val=0.017)
            self.connect("balance.FAR_core", "burner.Fl_I:FAR")
            self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR_core")

            balance.add_balance("FAR_ab", eq_units="degR", lower=1e-4,
                                upper=0.06, val=0.017)
            self.connect("balance.FAR_ab", "afterburner.Fl_I:FAR")
            self.connect("afterburner.Fl_O:tot:T", "balance.lhs:FAR_ab")

            balance.add_balance("LP_Nmech", val=1.0, units="rpm", lower=500.0,
                                eq_units="hp", use_mult=True, mult_val=-1)
            self.connect("balance.LP_Nmech", "LP_Nmech")
            self.connect("lp_shaft.pwr_in", "balance.lhs:LP_Nmech")
            self.connect("lp_shaft.pwr_out", "balance.rhs:LP_Nmech")

            balance.add_balance("HP_Nmech", val=1.0, units="rpm", lower=500.0,
                                eq_units="hp", use_mult=True, mult_val=-1)
            self.connect("balance.HP_Nmech", "HP_Nmech")
            self.connect("hp_shaft.pwr_in", "balance.lhs:HP_Nmech")
            self.connect("hp_shaft.pwr_out", "balance.rhs:HP_Nmech")

        # Solver
        newton = self.nonlinear_solver = om.NewtonSolver()
        newton.options["atol"] = 1e-6
        newton.options["rtol"] = 1e-10
        newton.options["iprint"] = params.get("solver_iprint", -1)
        newton.options["maxiter"] = 10
        newton.options["solve_subsystems"] = True
        newton.options["max_sub_solves"] = 100
        newton.options["reraise_child_analysiserror"] = False
        newton.linesearch = om.BoundsEnforceLS()
        newton.linesearch.options["bound_enforcement"] = "scalar"
        newton.linesearch.options["iprint"] = -1

        self.linear_solver = om.DirectSolver(assemble_jac=True)

        super().setup()


MIXEDFLOW_TURBOFAN_META = {
    "description": "Mixed-flow turbofan with afterburner and CD nozzle",
    "elements": ["fc", "inlet", "inlet_duct", "fan", "splitter",
                 "splitter_core_duct", "lpc", "lpc_duct", "hpc", "bld3",
                 "burner", "hpt", "hpt_duct", "lpt", "lpt_duct",
                 "bypass_duct", "mixer", "mixer_duct", "afterburner",
                 "mixed_nozz", "lp_shaft", "hp_shaft", "perf"],
    "flow_stations": [
        "fc.Fl_O", "inlet.Fl_O", "inlet_duct.Fl_O", "fan.Fl_O",
        "splitter.Fl_O1", "splitter.Fl_O2", "splitter_core_duct.Fl_O",
        "lpc.Fl_O", "lpc_duct.Fl_O", "hpc.Fl_O", "bld3.Fl_O",
        "burner.Fl_O", "hpt.Fl_O", "hpt_duct.Fl_O", "lpt.Fl_O",
        "lpt_duct.Fl_O", "bypass_duct.Fl_O", "mixer.Fl_O",
        "mixer_duct.Fl_O", "afterburner.Fl_O", "mixed_nozz.Fl_O",
    ],
    "compressors": ["fan", "lpc", "hpc"],
    "turbines": ["hpt", "lpt"],
    "burners": ["burner", "afterburner"],
    "shafts": ["lp_shaft", "hp_shaft"],
    "nozzles": ["mixed_nozz"],
}
