"""Sparse direct-solver microbench: SuperLU vs MKL PARDISO across system size.

Answers: does a parallel sparse solver (and more cores) beat scipy's
single-threaded SuperLU -- and at what problem size does it start to matter?
2D 5-point Laplacian as a representative sparse SPD system. Run with
MKL_NUM_THREADS set to control PARDISO threads.
"""
import os
import time
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla
from pypardiso import PyPardisoSolver


def laplacian(n):
    T = sp.diags([-1.0, 2.0, -1.0], [-1, 0, 1], shape=(n, n))
    I = sp.eye(n)
    A = sp.kron(I, T) + sp.kron(T, I) + 1e-6 * sp.eye(n * n)
    return sp.csc_matrix(A)


def t_superlu(A, b, reps):
    A = A.tocsc()
    t = time.perf_counter()
    for _ in range(reps):
        lu = spla.splu(A)
        x = lu.solve(b)
    return (time.perf_counter() - t) / reps, np.linalg.norm(A @ x - b)


def t_pardiso(A, b, reps):
    A = A.tocsr()
    s = PyPardisoSolver()
    t = time.perf_counter()
    for _ in range(reps):
        s.factorize(A)
        x = s.solve(A, b)
    return (time.perf_counter() - t) / reps, np.linalg.norm(A @ x - b)


threads = os.environ.get("MKL_NUM_THREADS", "?")
print(f"MKL_NUM_THREADS={threads}")
print(f"{'N (DOF)':>10}{'nnz':>10}{'SuperLU ms':>13}{'PARDISO ms':>13}{'speedup':>9}")
print("-" * 56)
for n in (32, 64, 128, 200, 300):
    A = laplacian(n)
    N = A.shape[0]
    b = np.random.rand(N)
    reps = 20 if N < 20000 else 5
    su, r1 = t_superlu(A, b, reps)
    pa, r2 = t_pardiso(A, b, reps)
    assert r1 < 1e-6 and r2 < 1e-6, (r1, r2)
    print(f"{N:>10}{A.nnz:>10}{su*1e3:>13.2f}{pa*1e3:>13.2f}{su/pa:>8.2f}x")
