"""Swap MKL PARDISO for scipy SuperLU in OAS's DirectSolver, measure impact.

OpenMDAO's DirectSolver factorizes the coupled Jacobian with
scipy.sparse.linalg.splu (SuperLU, single-threaded). We monkeypatch that to a
PARDISO-backed factorization (MKL, multithreaded) and run the full tube
aerostruct optimization.

Controlled by env:
  SOLVER=superlu|pardiso       which factorization to use
  MKL_NUM_THREADS=N            PARDISO thread count (set before launch)
so the algorithm effect (pardiso vs superlu at 1 thread) and the threading
effect (pardiso 1 vs 4 threads) can be separated. Prints the actual coupled
system size so it lands on the bench_solver.py crossover curve.
"""
import os
import time
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from pypardiso import PyPardisoSolver
from bench_oas_aerostruct import build

SOLVER = os.environ.get("SOLVER", "superlu")
THREADS = os.environ.get("MKL_NUM_THREADS", "?")
_orig_splu = spla.splu
_stats = {"N": 0}


class _PardisoLU:
    def __init__(self, matrix):
        self.A = sp.csr_matrix(matrix)
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


def _my_splu(matrix, *a, **k):
    _stats["N"] = max(_stats["N"], matrix.shape[0])
    return _PardisoLU(matrix) if SOLVER == "pardiso" else _orig_splu(matrix, *a, **k)


spla.splu = _my_splu  # patched for the whole process


def run(num_y, num_x, maxiter):
    prob = build(num_y, num_x)
    prob.driver.options["maxiter"] = maxiter
    t = time.perf_counter()
    prob.run_driver()
    return time.perf_counter() - t, prob.get_val("AS_point_0.fuelburn")[0]


print(f"SOLVER={SOLVER}  MKL_NUM_THREADS={THREADS}")
for num_y, num_x in ((25, 5), (45, 6)):
    dt, fb = run(num_y, num_x, 10)
    print(f"  {num_y}x{num_x}  panels={(num_x-1)*(num_y-1):>4}  coupled_DOF={_stats['N']:>7}  "
          f"time={dt:7.2f}s  fuelburn={fb:.6e}")
