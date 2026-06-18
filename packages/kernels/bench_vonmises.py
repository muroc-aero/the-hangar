"""Benchmark the Rust VonMisesTube kernel vs the upstream OAS component.

Primal (compute) and end-to-end derivatives (compute_totals): the rust path
uses complex-step through the kernel; OAS uses its hand-coded analytic
partials -- so this compares the rust drop-in against upstream's best case.
"""
import time
import numpy as np
import openmdao.api as om
import hangar_kernels as rk
from tests.test_vonmises_parity import (
    VonMisesTubeRust, make_case, _build_oas, _set, E_AL, G_AL,
)


def timeit(fn, *a, reps=200):
    fn(*a)
    t = time.perf_counter()
    for _ in range(reps):
        fn(*a)
    return (time.perf_counter() - t) / reps * 1e3


print(f"{'ny':>6}{'elems':>7}  | {'compute (ms)':^26} | {'compute_totals (ms)':^26}")
print(f"{'':>6}{'':>7}  | {'OAS':>8}{'rust':>9}{'x':>8} | {'OAS-analytic':>13}{'rust-cs':>8}{'x':>6}")
print("-" * 78)
for ny in (21, 51, 101, 201):
    nodes, radius, disp = make_case(ny)

    p_oas = _build_oas(ny); _set(p_oas, nodes, radius, disp); p_oas.run_model()
    p_rust = om.Problem()
    p_rust.model.add_subsystem("vm", VonMisesTubeRust(ny=ny), promotes=["*"])
    p_rust.setup(force_alloc_complex=True)
    _set(p_rust, nodes, radius, disp); p_rust.run_model()

    c_oas = timeit(p_oas.run_model)
    c_rust = timeit(p_rust.run_model)
    wrt = ["nodes", "radius", "disp"]
    t_oas = timeit(lambda: p_oas.compute_totals(of=["vonmises"], wrt=wrt), reps=50)
    t_rust = timeit(lambda: p_rust.compute_totals(of=["vonmises"], wrt=wrt), reps=50)

    print(f"{ny:>6}{ny-1:>7}  | {c_oas:>8.3f}{c_rust:>9.3f}{c_oas/c_rust:>7.1f}x | "
          f"{t_oas:>13.3f}{t_rust:>8.3f}{t_oas/t_rust:>5.1f}x")
