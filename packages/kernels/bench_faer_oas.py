"""Three-way sparse-solver comparison on the real OAS coupled Jacobian.

OpenMDAO's DirectSolver factorizes the coupled aerostructural Jacobian with
scipy.sparse.linalg.splu (SuperLU, single-threaded, BSD). We monkeypatch that
call site to one of three back-ends and run the full tube aerostruct
optimization end to end:

  SOLVER=superlu   scipy SuperLU            (BSD,         1 thread)   -- baseline
  SOLVER=pardiso   MKL PARDISO via pypardiso(proprietary, MKL_NUM_THREADS)
  SOLVER=faer      faer sparse LU via pyo3  (MIT/Apache,  FAER_THREADS)

The faer path is the thesis under test: a permissively-licensed, portable,
parallel sparse direct solver shipped in a wheel. All three solve the *same*
factorization at every Newton/adjoint step, so identical fuelburn is the
correctness check; wall time is the comparison. The coupled system size N is
printed so the result lands on the bench_solver.py crossover curve.

Run one solver per process (env-controlled) so thread pools and first-touch
stay isolated and fair:
  SOLVER=superlu                         python bench_faer_oas.py
  SOLVER=pardiso MKL_NUM_THREADS=1       python bench_faer_oas.py
  SOLVER=pardiso MKL_NUM_THREADS=4       python bench_faer_oas.py
  SOLVER=faer    FAER_THREADS=1          python bench_faer_oas.py
  SOLVER=faer    FAER_THREADS=4          python bench_faer_oas.py
"""
import os
import time
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from bench_oas_aerostruct import build

SOLVER = os.environ.get("SOLVER", "superlu")
MKL_THREADS = os.environ.get("MKL_NUM_THREADS", "?")
FAER_THREADS = int(os.environ.get("FAER_THREADS", "1"))
_orig_splu = spla.splu
_stats = {"N": 0}

if SOLVER == "pardiso":
    from pypardiso import PyPardisoSolver
if SOLVER == "faer":
    import hangar_kernels as rk
    rk.faer_set_threads(FAER_THREADS)


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


class _FaerLU:
    def __init__(self, matrix):
        A = sp.csc_matrix(matrix)
        self.f = rk.FaerLU(A.shape[0], A.shape[1],
                           A.indptr.astype(np.int64),
                           A.indices.astype(np.int64),
                           A.data.astype(np.float64))

    def solve(self, b, trans="N"):
        b = np.ascontiguousarray(b, dtype=float)
        return self.f.solve(b, trans != "N")


def _my_splu(matrix, *a, **k):
    _stats["N"] = max(_stats["N"], matrix.shape[0])
    if SOLVER == "pardiso":
        return _PardisoLU(matrix)
    if SOLVER == "faer":
        return _FaerLU(matrix)
    return _orig_splu(matrix, *a, **k)


spla.splu = _my_splu  # patched for the whole process


def run(num_y, num_x, maxiter):
    prob = build(num_y, num_x)
    prob.driver.options["maxiter"] = maxiter
    t = time.perf_counter()
    prob.run_driver()
    return time.perf_counter() - t, prob.get_val("AS_point_0.fuelburn")[0]


tag = SOLVER
if SOLVER == "pardiso":
    tag = f"pardiso(MKL_NUM_THREADS={MKL_THREADS})"
elif SOLVER == "faer":
    tag = f"faer(FAER_THREADS={FAER_THREADS})"
print(f"SOLVER={tag}")
for num_y, num_x in ((25, 5), (45, 6)):
    dt, fb = run(num_y, num_x, 10)
    print(f"  {num_y}x{num_x}  panels={(num_x-1)*(num_y-1):>4}  coupled_DOF={_stats['N']:>7}  "
          f"time={dt:7.2f}s  fuelburn={fb:.6e}")
