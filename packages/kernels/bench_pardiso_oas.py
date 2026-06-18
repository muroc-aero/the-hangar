"""Swap MKL PARDISO for scipy SuperLU in OAS's DirectSolver, measure impact.

OpenMDAO's DirectSolver factorizes the coupled Jacobian with
scipy.sparse.linalg.splu (SuperLU, single-threaded). We monkeypatch that to a
PARDISO-backed factorization (MKL, multithreaded) and run the full tube
aerostruct optimization, capturing the actual coupled-system size so we can
place it on the solver crossover curve.
"""
import time
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from pypardiso import PyPardisoSolver
from bench_oas_aerostruct import build

_orig_splu = spla.splu
_max_N = [0]


class _PardisoLU:
    def __init__(self, matrix, **kwargs):
        self.A = sp.csr_matrix(matrix)
        _max_N[0] = max(_max_N[0], self.A.shape[0])
        self.sN = PyPardisoSolver(); self.sN.factorize(self.A)
        self.sT = None; self.AT = None

    def solve(self, b, trans="N"):
        b = np.ascontiguousarray(b, dtype=float)
        if trans == "N":
            return self.sN.solve(self.A, b)
        if self.sT is None:
            self.AT = sp.csr_matrix(self.A.T)
            self.sT = PyPardisoSolver(); self.sT.factorize(self.AT)
        return self.sT.solve(self.AT, b)


def patch(on):
    spla.splu = _PardisoLU if on else _orig_splu


def run(num_y, num_x, on, maxiter):
    patch(on)
    _max_N[0] = 0
    prob = build(num_y, num_x)
    prob.driver.options["maxiter"] = maxiter
    t = time.perf_counter()
    prob.run_driver()
    dt = time.perf_counter() - t
    fb = prob.get_val("AS_point_0.fuelburn")[0]
    patch(False)
    return dt, fb, _max_N[0]


MAXITER = 10
print(f"{'mesh':>9}{'panels':>8}{'coupled DOF':>13} | {'SuperLU s':>11}{'PARDISO s':>11}{'speedup':>9}"
      f"{'  fuelburn match':>17}")
print("-" * 80)
for num_y, num_x in ((25, 5), (45, 6)):
    t_su, fb_su, N = run(num_y, num_x, False, MAXITER)
    t_pa, fb_pa, _ = run(num_y, num_x, True, MAXITER)
    panels = (num_x - 1) * (num_y - 1)
    print(f"{f'{num_y}x{num_x}':>9}{panels:>8}{N:>13} | {t_su:>11.2f}{t_pa:>11.2f}"
          f"{t_su/t_pa:>8.2f}x{abs(fb_su-fb_pa)/abs(fb_su):>16.1e}")
