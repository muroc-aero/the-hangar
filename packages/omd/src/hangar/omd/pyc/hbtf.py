"""High-bypass turbofan (HBTF) archetype.

Ported from upstream pyCycle example_cycles/high_bypass_turbofan.py.
Dual-spool with fan, LPC, HPC, HPT, LPT, core and bypass nozzles.
"""

import openmdao.api as om
import pycycle.api as pyc

from hangar.omd.pyc.defaults import DEFAULT_HBTF_PARAMS


class HBTF(pyc.Cycle):
    """High-bypass turbofan cycle.

    Dual-spool: LP (fan + LPC + LPT) and HP (HPC + HPT).
    Separate core and bypass nozzles. Bleed cooling from HPC to LPT
    and from BLD3 to HPT.
    """

    def initialize(self):
        self.options.declare("params", default={}, types=dict)
        self.options.declare("throttle_mode", default="T4",
                             values=["T4", "percent_thrust"])
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
        self.add_subsystem("fan", pyc.Compressor(map_data=pyc.FanMap,
                           bleed_names=[], map_extrap=True),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("splitter", pyc.Splitter())
        self.add_subsystem("duct4", pyc.Duct())
        self.add_subsystem("lpc", pyc.Compressor(map_data=pyc.LPCMap,
                           map_extrap=True),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("duct6", pyc.Duct())
        self.add_subsystem("hpc", pyc.Compressor(map_data=pyc.HPCMap,
                           bleed_names=["cool1", "cool2", "cust"],
                           map_extrap=True),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("bld3", pyc.BleedOut(bleed_names=["cool3", "cool4"]))
        self.add_subsystem("burner", pyc.Combustor(fuel_type=fuel_type))
        self.add_subsystem("hpt", pyc.Turbine(map_data=pyc.HPTMap,
                           bleed_names=["cool3", "cool4"], map_extrap=True),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("duct11", pyc.Duct())
        self.add_subsystem("lpt", pyc.Turbine(map_data=pyc.LPTMap,
                           bleed_names=["cool1", "cool2"], map_extrap=True),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("duct13", pyc.Duct())
        self.add_subsystem("core_nozz", pyc.Nozzle(nozzType="CV", lossCoef="Cv"))
        self.add_subsystem("byp_bld", pyc.BleedOut(bleed_names=["bypBld"]))
        self.add_subsystem("duct15", pyc.Duct())
        self.add_subsystem("byp_nozz", pyc.Nozzle(nozzType="CV", lossCoef="Cv"))
        self.add_subsystem("lp_shaft", pyc.Shaft(num_ports=3),
                           promotes_inputs=[("Nmech", "LP_Nmech")])
        self.add_subsystem("hp_shaft", pyc.Shaft(num_ports=2),
                           promotes_inputs=[("Nmech", "HP_Nmech")])
        self.add_subsystem("perf", pyc.Performance(num_nozzles=2, num_burners=1))

        # Performance connections
        self.connect("inlet.Fl_O:tot:P", "perf.Pt2")
        self.connect("hpc.Fl_O:tot:P", "perf.Pt3")
        self.connect("burner.Wfuel", "perf.Wfuel_0")
        self.connect("inlet.F_ram", "perf.ram_drag")
        self.connect("core_nozz.Fg", "perf.Fg_0")
        self.connect("byp_nozz.Fg", "perf.Fg_1")

        # Shaft connections
        self.connect("fan.trq", "lp_shaft.trq_0")
        self.connect("lpc.trq", "lp_shaft.trq_1")
        self.connect("lpt.trq", "lp_shaft.trq_2")
        self.connect("hpc.trq", "hp_shaft.trq_0")
        self.connect("hpt.trq", "hp_shaft.trq_1")

        # Nozzle exhaust
        self.connect("fc.Fl_O:stat:P", "core_nozz.Ps_exhaust")
        self.connect("fc.Fl_O:stat:P", "byp_nozz.Ps_exhaust")

        # Balances
        balance = self.add_subsystem("balance", om.BalanceComp())
        if design:
            balance.add_balance("W", units="lbm/s", eq_units="lbf")
            self.connect("balance.W", "fc.W")
            self.connect("perf.Fn", "balance.lhs:W")
            self.promotes("balance", inputs=[("rhs:W", "Fn_DES")])

            balance.add_balance("FAR", eq_units="degR", lower=1e-4, val=0.017)
            self.connect("balance.FAR", "burner.Fl_I:FAR")
            self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR")
            self.promotes("balance", inputs=[("rhs:FAR", "T4_MAX")])

            balance.add_balance("lpt_PR", val=1.5, lower=1.001, upper=8,
                                eq_units="hp", use_mult=True, mult_val=-1)
            self.connect("balance.lpt_PR", "lpt.PR")
            self.connect("lp_shaft.pwr_in_real", "balance.lhs:lpt_PR")
            self.connect("lp_shaft.pwr_out_real", "balance.rhs:lpt_PR")

            balance.add_balance("hpt_PR", val=1.5, lower=1.001, upper=8,
                                eq_units="hp", use_mult=True, mult_val=-1)
            self.connect("balance.hpt_PR", "hpt.PR")
            self.connect("hp_shaft.pwr_in_real", "balance.lhs:hpt_PR")
            self.connect("hp_shaft.pwr_out_real", "balance.rhs:hpt_PR")
        else:
            if self.options["throttle_mode"] == "T4":
                balance.add_balance("FAR", val=0.017, lower=1e-4, eq_units="degR")
                self.connect("balance.FAR", "burner.Fl_I:FAR")
                self.connect("burner.Fl_O:tot:T", "balance.lhs:FAR")
                self.promotes("balance", inputs=[("rhs:FAR", "T4_MAX")])
            elif self.options["throttle_mode"] == "percent_thrust":
                balance.add_balance("FAR", val=0.017, lower=1e-4,
                                    eq_units="lbf", use_mult=True)
                self.connect("balance.FAR", "burner.Fl_I:FAR")
                self.connect("perf.Fn", "balance.rhs:FAR")
                self.promotes("balance", inputs=[("mult:FAR", "PC"),
                                                 ("lhs:FAR", "Fn_max")])

            balance.add_balance("W", units="lbm/s", lower=10.0, upper=1000.0,
                                eq_units="inch**2")
            self.connect("balance.W", "fc.W")
            self.connect("core_nozz.Throat:stat:area", "balance.lhs:W")

            balance.add_balance("BPR", lower=2.0, upper=10.0, eq_units="inch**2")
            self.connect("balance.BPR", "splitter.BPR")
            self.connect("byp_nozz.Throat:stat:area", "balance.lhs:BPR")

            balance.add_balance("lp_Nmech", val=1.5, units="rpm", lower=500.0,
                                eq_units="hp", use_mult=True, mult_val=-1)
            self.connect("balance.lp_Nmech", "LP_Nmech")
            self.connect("lp_shaft.pwr_in_real", "balance.lhs:lp_Nmech")
            self.connect("lp_shaft.pwr_out_real", "balance.rhs:lp_Nmech")

            balance.add_balance("hp_Nmech", val=1.5, units="rpm", lower=500.0,
                                eq_units="hp", use_mult=True, mult_val=-1)
            self.connect("balance.hp_Nmech", "HP_Nmech")
            self.connect("hp_shaft.pwr_in_real", "balance.lhs:hp_Nmech")
            self.connect("hp_shaft.pwr_out_real", "balance.rhs:hp_Nmech")

        # Flow connections
        self.pyc_connect_flow("fc.Fl_O", "inlet.Fl_I")
        self.pyc_connect_flow("inlet.Fl_O", "fan.Fl_I")
        self.pyc_connect_flow("fan.Fl_O", "splitter.Fl_I")
        self.pyc_connect_flow("splitter.Fl_O1", "duct4.Fl_I")
        self.pyc_connect_flow("duct4.Fl_O", "lpc.Fl_I")
        self.pyc_connect_flow("lpc.Fl_O", "duct6.Fl_I")
        self.pyc_connect_flow("duct6.Fl_O", "hpc.Fl_I")
        self.pyc_connect_flow("hpc.Fl_O", "bld3.Fl_I")
        self.pyc_connect_flow("bld3.Fl_O", "burner.Fl_I")
        self.pyc_connect_flow("burner.Fl_O", "hpt.Fl_I")
        self.pyc_connect_flow("hpt.Fl_O", "duct11.Fl_I")
        self.pyc_connect_flow("duct11.Fl_O", "lpt.Fl_I")
        self.pyc_connect_flow("lpt.Fl_O", "duct13.Fl_I")
        self.pyc_connect_flow("duct13.Fl_O", "core_nozz.Fl_I")
        self.pyc_connect_flow("splitter.Fl_O2", "byp_bld.Fl_I")
        self.pyc_connect_flow("byp_bld.Fl_O", "duct15.Fl_I")
        self.pyc_connect_flow("duct15.Fl_O", "byp_nozz.Fl_I")

        # Bleed flows
        self.pyc_connect_flow("hpc.cool1", "lpt.cool1", connect_stat=False)
        self.pyc_connect_flow("hpc.cool2", "lpt.cool2", connect_stat=False)
        self.pyc_connect_flow("bld3.cool3", "hpt.cool3", connect_stat=False)
        self.pyc_connect_flow("bld3.cool4", "hpt.cool4", connect_stat=False)

        # Solver
        newton = self.nonlinear_solver = om.NewtonSolver()
        newton.options["atol"] = 1e-8
        newton.options["rtol"] = 1e-99
        newton.options["iprint"] = params.get("solver_iprint", -1)
        newton.options["maxiter"] = 50
        newton.options["solve_subsystems"] = True
        newton.options["max_sub_solves"] = 1000
        newton.options["reraise_child_analysiserror"] = False
        ls = newton.linesearch = om.ArmijoGoldsteinLS()
        ls.options["maxiter"] = 3
        ls.options["rho"] = 0.75

        self.linear_solver = om.DirectSolver()

        super().setup()


class MPHbtf(pyc.MPCycle):
    """Multi-point HBTF: design + off-design points."""

    def initialize(self):
        self.options.declare("params", default={}, types=dict)
        self.options.declare("od_points", default=[], types=list)
        super().initialize()

    def setup(self):
        params = {**DEFAULT_HBTF_PARAMS, **self.options["params"]}

        self.pyc_add_pnt("DESIGN", HBTF(params=params))

        self.set_input_defaults("DESIGN.inlet.MN", 0.751)
        self.set_input_defaults("DESIGN.fan.MN", 0.4578)
        self.set_input_defaults("DESIGN.splitter.BPR", params["BPR"])
        self.set_input_defaults("DESIGN.splitter.MN1", 0.3104)
        self.set_input_defaults("DESIGN.splitter.MN2", 0.4518)
        self.set_input_defaults("DESIGN.duct4.MN", 0.3121)
        self.set_input_defaults("DESIGN.lpc.MN", 0.3059)
        self.set_input_defaults("DESIGN.duct6.MN", 0.3563)
        self.set_input_defaults("DESIGN.hpc.MN", 0.2442)
        self.set_input_defaults("DESIGN.bld3.MN", 0.3000)
        self.set_input_defaults("DESIGN.burner.MN", 0.1025)
        self.set_input_defaults("DESIGN.hpt.MN", 0.3650)
        self.set_input_defaults("DESIGN.duct11.MN", 0.3063)
        self.set_input_defaults("DESIGN.lpt.MN", 0.4127)
        self.set_input_defaults("DESIGN.duct13.MN", 0.4463)
        self.set_input_defaults("DESIGN.byp_bld.MN", 0.4489)
        self.set_input_defaults("DESIGN.duct15.MN", 0.4589)
        self.set_input_defaults("DESIGN.LP_Nmech", params["LP_Nmech"], units="rpm")
        self.set_input_defaults("DESIGN.HP_Nmech", params["HP_Nmech"], units="rpm")

        # Cycle parameters
        self.pyc_add_cycle_param("inlet.ram_recovery", params.get("inlet_ram_recovery", 0.9990))
        self.pyc_add_cycle_param("duct4.dPqP", params["duct4_dPqP"])
        self.pyc_add_cycle_param("duct6.dPqP", params["duct6_dPqP"])
        self.pyc_add_cycle_param("burner.dPqP", params["burner_dPqP"])
        self.pyc_add_cycle_param("duct11.dPqP", params["duct11_dPqP"])
        self.pyc_add_cycle_param("duct13.dPqP", params["duct13_dPqP"])
        self.pyc_add_cycle_param("duct15.dPqP", params["duct15_dPqP"])
        self.pyc_add_cycle_param("core_nozz.Cv", params["core_nozz_Cv"])
        self.pyc_add_cycle_param("byp_bld.bypBld:frac_W", 0.005)
        self.pyc_add_cycle_param("byp_nozz.Cv", params["byp_nozz_Cv"])
        self.pyc_add_cycle_param("hpc.cool1:frac_W", params["cool1_frac_W"])
        self.pyc_add_cycle_param("hpc.cool1:frac_P", 0.5)
        self.pyc_add_cycle_param("hpc.cool1:frac_work", 0.5)
        self.pyc_add_cycle_param("hpc.cool2:frac_W", params["cool2_frac_W"])
        self.pyc_add_cycle_param("hpc.cool2:frac_P", 0.55)
        self.pyc_add_cycle_param("hpc.cool2:frac_work", 0.5)
        self.pyc_add_cycle_param("bld3.cool3:frac_W", params["cool3_frac_W"])
        self.pyc_add_cycle_param("bld3.cool4:frac_W", params["cool4_frac_W"])
        self.pyc_add_cycle_param("hpc.cust:frac_P", 0.5)
        self.pyc_add_cycle_param("hpc.cust:frac_work", 0.5)
        self.pyc_add_cycle_param("hpc.cust:frac_W", params["cust_frac_W"])
        self.pyc_add_cycle_param("hpt.cool3:frac_P", 1.0)
        self.pyc_add_cycle_param("hpt.cool4:frac_P", 0.0)
        self.pyc_add_cycle_param("lpt.cool1:frac_P", 1.0)
        self.pyc_add_cycle_param("lpt.cool2:frac_P", 0.0)
        self.pyc_add_cycle_param("hp_shaft.HPX", 250.0, units="hp")

        # Off-design points
        for od in self.options["od_points"]:
            pt = od["name"]
            mode = od.get("throttle_mode", "T4")
            self.pyc_add_pnt(pt, HBTF(design=False, params=params,
                                      throttle_mode=mode))
            self.set_input_defaults(f"{pt}.fc.MN", od["MN"])
            self.set_input_defaults(f"{pt}.fc.alt", od["alt"], units="ft")

        if self.options["od_points"]:
            self.pyc_use_default_des_od_conns()
            self.pyc_connect_des_od("core_nozz.Throat:stat:area", "balance.rhs:W")
            self.pyc_connect_des_od("byp_nozz.Throat:stat:area", "balance.rhs:BPR")

        super().setup()


HBTF_META = {
    "description": "High-bypass turbofan (dual-spool, separate exhaust)",
    "elements": ["fc", "inlet", "fan", "splitter", "duct4", "lpc", "duct6",
                 "hpc", "bld3", "burner", "hpt", "duct11", "lpt", "duct13",
                 "core_nozz", "byp_bld", "duct15", "byp_nozz",
                 "lp_shaft", "hp_shaft", "perf"],
    "flow_stations": [
        "fc.Fl_O", "inlet.Fl_O", "fan.Fl_O", "splitter.Fl_O1",
        "splitter.Fl_O2", "duct4.Fl_O", "lpc.Fl_O", "duct6.Fl_O",
        "hpc.Fl_O", "bld3.Fl_O", "burner.Fl_O", "hpt.Fl_O",
        "duct11.Fl_O", "lpt.Fl_O", "duct13.Fl_O", "core_nozz.Fl_O",
        "byp_bld.Fl_O", "duct15.Fl_O", "byp_nozz.Fl_O",
    ],
    "compressors": ["fan", "lpc", "hpc"],
    "turbines": ["hpt", "lpt"],
    "burners": ["burner"],
    "shafts": ["lp_shaft", "hp_shaft"],
    "nozzles": ["core_nozz", "byp_nozz"],
}
