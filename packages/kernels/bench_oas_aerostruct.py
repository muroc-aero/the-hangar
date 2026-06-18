"""Full OAS aerostruct optimization: time impact of the Rust VonMisesTube.

Runs the canonical tube-model aerostruct optimization (DVs: twist, thickness,
alpha; objective: fuelburn) stock vs. with VonMisesTube monkeypatched to the
Rust kernels (primal + sparse analytic Jacobian). Verifies identical optimum,
times both, and profiles what fraction of the run VonMisesTube actually is --
the number that decides whether a component-level speedup matters end to end.
"""
import time
import cProfile
import pstats
import io
import numpy as np
import openmdao.api as om
from openaerostruct.meshing.mesh_generator import generate_mesh
from openaerostruct.integration.aerostruct_groups import AerostructGeometry, AerostructPoint
from openaerostruct.utils.constants import grav_constant
from openaerostruct.structures import vonmises_tube as vmt
import hangar_kernels as rk

_orig_compute = vmt.VonMisesTube.compute
_orig_partials = vmt.VonMisesTube.compute_partials


def _rust_compute(self, inputs, outputs):
    n = np.ascontiguousarray(inputs["nodes"])
    r = np.ascontiguousarray(inputs["radius"])
    d = np.ascontiguousarray(inputs["disp"])
    if self.under_complex_step:
        outputs["vonmises"] = rk.vonmises_tube_cs(n, r, d, self.E, self.G)
    else:
        outputs["vonmises"] = rk.vonmises_tube(n, r, d, self.E, self.G)


def _rust_compute_partials(self, inputs, partials):
    jn, jr, jd = rk.vonmises_tube_jac(
        np.ascontiguousarray(inputs["nodes"]),
        np.ascontiguousarray(inputs["radius"]),
        np.ascontiguousarray(inputs["disp"]),
        self.E, self.G)
    partials["vonmises", "nodes"] = jn
    partials["vonmises", "radius"] = jr
    partials["vonmises", "disp"] = jd


def patch(on):
    vmt.VonMisesTube.compute = _rust_compute if on else _orig_compute
    vmt.VonMisesTube.compute_partials = _rust_compute_partials if on else _orig_partials


def build(num_y, num_x):
    mesh_dict = {"num_y": num_y, "num_x": num_x, "wing_type": "CRM", "symmetry": True, "num_twist_cp": 5}
    mesh, twist_cp = generate_mesh(mesh_dict)
    surface = {
        "name": "wing", "symmetry": True, "S_ref_type": "wetted", "fem_model_type": "tube",
        "thickness_cp": np.array([0.1, 0.2, 0.3]), "twist_cp": twist_cp, "mesh": mesh,
        "CL0": 0.0, "CD0": 0.015, "k_lam": 0.05, "t_over_c_cp": np.array([0.15]), "c_max_t": 0.303,
        "with_viscous": True, "with_wave": False, "E": 70.0e9, "G": 30.0e9, "yield": 500.0e6,
        "safety_factor": 2.5, "mrho": 3.0e3, "fem_origin": 0.35, "wing_weight_ratio": 2.0,
        "struct_weight_relief": False, "distributed_fuel_weight": False, "exact_failure_constraint": False,
    }
    prob = om.Problem(reports=False)
    ivc = om.IndepVarComp()
    ivc.add_output("v", val=248.136, units="m/s"); ivc.add_output("alpha", val=5.0, units="deg")
    ivc.add_output("Mach_number", val=0.84); ivc.add_output("re", val=1.0e6, units="1/m")
    ivc.add_output("rho", val=0.38, units="kg/m**3"); ivc.add_output("CT", val=grav_constant * 17.0e-6, units="1/s")
    ivc.add_output("R", val=11.165e6, units="m"); ivc.add_output("W0", val=0.4 * 3e5, units="kg")
    ivc.add_output("speed_of_sound", val=295.4, units="m/s"); ivc.add_output("load_factor", val=1.0)
    ivc.add_output("empty_cg", val=np.zeros(3), units="m")
    prob.model.add_subsystem("prob_vars", ivc, promotes=["*"])
    prob.model.add_subsystem("wing", AerostructGeometry(surface=surface))
    pt = "AS_point_0"
    prob.model.add_subsystem(pt, AerostructPoint(surfaces=[surface]), promotes_inputs=[
        "v", "alpha", "Mach_number", "re", "rho", "CT", "R", "W0", "speed_of_sound", "empty_cg", "load_factor"])
    com = pt + ".wing_perf"
    prob.model.connect("wing.local_stiff_transformed", pt + ".coupled.wing.local_stiff_transformed")
    prob.model.connect("wing.nodes", pt + ".coupled.wing.nodes")
    prob.model.connect("wing.mesh", pt + ".coupled.wing.mesh")
    prob.model.connect("wing.radius", com + ".radius")
    prob.model.connect("wing.thickness", com + ".thickness")
    prob.model.connect("wing.nodes", com + ".nodes")
    prob.model.connect("wing.cg_location", pt + ".total_perf.wing_cg_location")
    prob.model.connect("wing.structural_mass", pt + ".total_perf.wing_structural_mass")
    prob.model.connect("wing.t_over_c", com + ".t_over_c")
    prob.driver = om.ScipyOptimizeDriver(tol=1e-9, disp=False)
    prob.driver.options["maxiter"] = 200
    prob.model.add_design_var("wing.twist_cp", lower=-10.0, upper=15.0)
    prob.model.add_design_var("wing.thickness_cp", lower=0.01, upper=0.5, scaler=1e2)
    prob.model.add_constraint(pt + ".wing_perf.failure", upper=0.0)
    prob.model.add_constraint(pt + ".wing_perf.thickness_intersects", upper=0.0)
    prob.model.add_design_var("alpha", lower=-10.0, upper=10.0)
    prob.model.add_constraint(pt + ".L_equals_W", equals=0.0)
    prob.model.add_objective(pt + ".fuelburn", scaler=1e-5)
    prob.setup()
    prob.set_solver_print(level=-1)
    return prob


def run_timed(num_y, num_x, on):
    patch(on)
    prob = build(num_y, num_x)
    t = time.perf_counter()
    prob.run_driver()
    dt = time.perf_counter() - t
    fb = prob.get_val("AS_point_0.fuelburn")[0]
    patch(False)
    return dt, fb


def profile_fraction(num_y, num_x):
    """What fraction of a stock run is spent inside VonMisesTube?"""
    patch(False)
    prob = build(num_y, num_x)
    pr = cProfile.Profile()
    pr.enable(); prob.run_driver(); pr.disable()
    st = pstats.Stats(pr, stream=io.StringIO())
    total = st.total_tt
    vm = 0.0
    for (fn, _line, name), val in st.stats.items():
        if "vonmises_tube" in fn and name in ("compute", "compute_partials"):
            vm += val[3]  # cumulative time
    return total, vm


print(f"{'mesh (ny x nx)':>16}{'elems':>7} | {'stock (s)':>10}{'rust (s)':>10}{'speedup':>9} | "
      f"{'VonMises % of run':>18}  fuelburn match")
print("-" * 92)
for num_y, num_x in ((5, 2), (15, 3), (25, 5)):
    t_stock, fb_stock = run_timed(num_y, num_x, False)
    t_rust, fb_rust = run_timed(num_y, num_x, True)
    total, vm = profile_fraction(num_y, num_x)
    match = abs(fb_stock - fb_rust) / abs(fb_stock)
    elems = num_y - 1
    print(f"{f'{num_y} x {num_x}':>16}{elems:>7} | {t_stock:>10.2f}{t_rust:>10.2f}{t_stock/t_rust:>8.2f}x | "
          f"{100*vm/total:>17.2f}%  rel {match:.1e}")
