"""Full OAS aerostruct optimization: time impact of the Rust VLM vortex kernel.

Ports the two primal vortex helpers in OAS's EvalVelMtx (the AIC assembly, the
~18% hot spot the profile identified) to Rust and monkeypatches them, then runs
the canonical tube aerostruct optimization stock vs patched at TRIPLED mesh
sizes. Optimizer iterations are capped (identical both ways) so the large
meshes stay tractable; the comparison stays fair and correctness is checked via
the optimized fuelburn.
"""
import time
import cProfile
import pstats
import io
import numpy as np
import openmdao.api as om
from openaerostruct.aerodynamics import eval_mtx as EM
import hangar_kernels as rk
# reuse the problem builder from the VonMises full-run bench
from bench_oas_aerostruct import build

_orig_fin = EM._compute_finite_vortex
_orig_semi = EM._compute_semi_infinite_vortex
asc = np.ascontiguousarray


def _fin(r1, r2):
    if np.iscomplexobj(r1) or np.iscomplexobj(r2):
        return _orig_fin(r1, r2)  # alpha complex-step -> numpy
    sh = r1.shape
    return rk.vlm_finite_vortex(asc(r1).reshape(-1, 3), asc(r2).reshape(-1, 3)).reshape(sh)


def _semi(u, r):
    if np.iscomplexobj(u) or np.iscomplexobj(r):
        return _orig_semi(u, r)
    u2, r2 = np.broadcast_arrays(u, r)
    sh = u2.shape
    return rk.vlm_semi_infinite_vortex(asc(u2).reshape(-1, 3), asc(r2).reshape(-1, 3)).reshape(sh)


def patch(on):
    EM._compute_finite_vortex = _fin if on else _orig_fin
    EM._compute_semi_infinite_vortex = _semi if on else _orig_semi


# ---- 1) helper correctness vs OAS originals ----
rng = np.random.default_rng(0)
r1 = rng.standard_normal((1, 3, 7, 3)) + 2.0
r2 = rng.standard_normal((1, 3, 7, 3)) + 2.0
u = rng.standard_normal((1, 1, 7, 3)); rr = rng.standard_normal((1, 1, 7, 3)) + 3.0
assert np.allclose(_fin(r1, r2), _orig_fin(r1, r2), atol=1e-14), "finite vortex mismatch"
assert np.allclose(_semi(u, rr), _orig_semi(u, rr), atol=1e-14), "semi-infinite mismatch"
print("helper parity vs OAS: OK")


def run(num_y, num_x, on, maxiter):
    patch(on)
    prob = build(num_y, num_x)
    prob.driver.options["maxiter"] = maxiter
    t = time.perf_counter()
    prob.run_driver()
    dt = time.perf_counter() - t
    fb = prob.get_val("AS_point_0.fuelburn")[0]
    patch(False)
    return dt, fb


def evalmtx_fraction(num_y, num_x, maxiter):
    patch(False)
    prob = build(num_y, num_x)
    prob.driver.options["maxiter"] = maxiter
    pr = cProfile.Profile(); pr.enable(); prob.run_driver(); pr.disable()
    st = pstats.Stats(pr, stream=io.StringIO())
    frac = 0.0
    for (fn, _ln, name), val in st.stats.items():
        if fn.endswith("eval_mtx.py") and name == "compute":
            frac += val[3]
    return st.total_tt, frac


# ---- 2) tripled meshes, capped optimization ----
MAXITER = 15
print(f"\n{'mesh (ny x nx)':>15}{'panels':>8} | {'stock (s)':>10}{'rust (s)':>10}{'speedup':>9} |"
      f"{'fuelburn match':>16}")
print("-" * 74)
for num_y, num_x in ((15, 4), (45, 6), (75, 8)):
    t_stock, fb_s = run(num_y, num_x, False, MAXITER)
    t_rust, fb_r = run(num_y, num_x, True, MAXITER)
    panels = (num_x - 1) * (num_y - 1)
    print(f"{f'{num_y} x {num_x}':>15}{panels:>8} | {t_stock:>10.2f}{t_rust:>10.2f}"
          f"{t_stock/t_rust:>8.2f}x |{abs(fb_s-fb_r)/abs(fb_s):>13.1e}")

tot, frac = evalmtx_fraction(45, 6, MAXITER)
print(f"\nEvalVelMtx.compute share of run (45x6): {100*frac/tot:.1f}%  (was ~18% at 15x3)")
