"""Benchmark the Rust VonMisesTube kernels vs the upstream OAS component.

Three drop-in variants vs OAS (which uses hand-coded analytic partials):
  - rust-cs        : Rust primal, derivatives via OpenMDAO global complex-step
  - rust-analytic  : Rust primal + Rust sparse Jacobian (per-element local CS)
The analytic variant is the apples-to-apples comparison to upstream.
"""
import time
import numpy as np
import openmdao.api as om
import hangar_kernels as rk
from tests.test_vonmises_parity import (
    VonMisesTubeRust, VonMisesTubeRustAnalytic, make_case, _build_oas, _set,
)


def timeit(fn, *a, reps=100):
    fn(*a)
    t = time.perf_counter()
    for _ in range(reps):
        fn(*a)
    return (time.perf_counter() - t) / reps * 1e3


def build(cls, ny, cs):
    p = om.Problem()
    p.model.add_subsystem("vm", cls(ny=ny), promotes=["*"])
    p.setup(force_alloc_complex=cs)
    return p


print(f"{'ny':>5}{'elems':>6}  | {'compute (ms)':^18} | {'compute_totals (ms): OAS-analytic vs rust':^52}")
print(f"{'':>5}{'':>6}  | {'OAS':>8}{'rust':>9} | {'OAS':>9}{'rust-cs':>10}{'x':>6}{'rust-analytic':>15}{'x':>6}")
print("-" * 92)
for ny in (21, 51, 101, 201):
    nodes, radius, disp = make_case(ny)
    p_oas = _build_oas(ny); _set(p_oas, nodes, radius, disp); p_oas.run_model()
    p_cs = build(VonMisesTubeRust, ny, True); _set(p_cs, nodes, radius, disp); p_cs.run_model()
    p_an = build(VonMisesTubeRustAnalytic, ny, False); _set(p_an, nodes, radius, disp); p_an.run_model()

    c_oas = timeit(p_oas.run_model)
    c_rust = timeit(p_an.run_model)
    wrt = ["nodes", "radius", "disp"]
    t_oas = timeit(lambda: p_oas.compute_totals(of=["vonmises"], wrt=wrt), reps=40)
    t_cs = timeit(lambda: p_cs.compute_totals(of=["vonmises"], wrt=wrt), reps=40)
    t_an = timeit(lambda: p_an.compute_totals(of=["vonmises"], wrt=wrt), reps=40)

    print(f"{ny:>5}{ny-1:>6}  | {c_oas:>8.3f}{c_rust:>9.3f} | "
          f"{t_oas:>9.3f}{t_cs:>10.3f}{t_oas/t_cs:>5.1f}x{t_an:>15.3f}{t_oas/t_an:>5.1f}x")
