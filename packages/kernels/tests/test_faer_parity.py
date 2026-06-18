"""Parity tests for the faer sparse LU solver exposed via pyo3.

Verifies the FaerLU drop-in matches scipy's SuperLU (splu) to machine precision
on both the normal and transpose solve -- the contract OpenMDAO's DirectSolver
relies on. Performance is a separate question (see bench_faer_oas.py and the
README); these tests only guard correctness so the solver stays a safe drop-in.
"""
import numpy as np
import pytest

rk = pytest.importorskip("hangar_kernels")
sp = pytest.importorskip("scipy.sparse")
spla = pytest.importorskip("scipy.sparse.linalg")


def _faer(A):
    A = sp.csc_matrix(A)
    return rk.FaerLU(A.shape[0], A.shape[1],
                     A.indptr.astype(np.int64),
                     A.indices.astype(np.int64),
                     A.data.astype(np.float64))


def _random_system(n=400, density=0.02, seed=0):
    rng = np.random.default_rng(seed)
    A = sp.random(n, n, density=density, rng=rng, format="csc") + sp.eye(n) * 5.0
    A = sp.csc_matrix(A)
    b = rng.standard_normal(n)
    return A, b


def test_faer_solve_matches_scipy():
    A, b = _random_system()
    x_ref = spla.splu(A).solve(b)
    x = _faer(A).solve(b, False)
    assert np.max(np.abs(x - x_ref)) < 1e-10
    assert np.linalg.norm(A @ x - b) < 1e-9


def test_faer_transpose_solve_matches_scipy():
    A, b = _random_system(seed=1)
    xT_ref = spla.splu(A).solve(b, trans="T")
    xT = _faer(A).solve(b, True)
    assert np.max(np.abs(xT - xT_ref)) < 1e-10
    assert np.linalg.norm(A.T @ xT - b) < 1e-9


def test_faer_set_threads_runs():
    # Setting parallelism must not change the answer.
    A, b = _random_system(seed=2)
    x_ref = spla.splu(A).solve(b)
    for nt in (1, 2, 4):
        rk.faer_set_threads(nt)
        assert np.max(np.abs(_faer(A).solve(b, False) - x_ref)) < 1e-10
    rk.faer_set_threads(1)
