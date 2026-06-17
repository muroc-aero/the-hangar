# hangar-kernels — native Rust hot kernels (proof of concept)

A small, self-contained experiment: take the single hottest numerical kernel in
the OAS VLM path — assembling the N×N aerodynamic influence-coefficient (AIC)
matrix (Biot–Savart from every ring vortex onto every collocation point, OAS's
`EvalVelMtx`) — and reimplement it in Rust behind pyo3, then prove it is a true
drop-in inside an OpenMDAO `ExplicitComponent`.

This is **strategy 2** from the omd→Rust discussion: keep OpenMDAO and all of
omd's internals in Python, rewrite only the hot inner kernels in Rust. The
package exists to make that trade measurable and to hold the parity contract.

## Status: opt-in, not wired into the default build

`hangar-kernels` is **excluded from the uv workspace** (`[tool.uv.workspace]
exclude` in the root `pyproject.toml`) so a normal `uv sync` / CI run needs no
Rust toolchain. The parity suite is **not** in the root `testpaths`; run it
explicitly. Only contributors who want to build/measure the kernel need cargo.

## Build & test

```bash
# one-time: Rust toolchain via https://rustup.rs, plus maturin
pip install maturin

cd packages/kernels
maturin develop --release          # compiles + installs `hangar_kernels`

pip install -e '.[test]'           # openmdao + pytest for the drop-in test
pytest tests -q                    # parity + complex-step contract
python bench.py                    # the three-tier microbenchmark table
```

The tests `pytest.importorskip("hangar_kernels")`, so a checkout that never ran
`maturin develop` skips them cleanly rather than failing.

## What's inside

- `src/lib.rs` — the kernel, written **generic over the scalar type** (`Scalar`
  trait implemented for `f64` and `num_complex::Complex64`). One source is
  monomorphized into:
  - `assemble_aic` — real primal (`f64`)
  - `assemble_aic_par` — same, parallel over collocation rows (rayon)
  - `assemble_aic_cs` — the **complex-step** path (`Complex64`)
  Plus `vec_add` / `segment_vel` for the lower benchmark tiers.
- `tests/test_parity.py` — builds a real VLM `ExplicitComponent` whose AIC
  assembly is the Rust kernel, with a camber design variable (`gscale`) that
  forces complex numbers *through* Rust under `method="cs"`. Asserts bit-parity
  vs numpy, complex-step-vs-FD derivatives, rust-vs-numpy jacobian parity, and a
  clean `check_partials`.
- `bench.py` — three tiers: trivial add (numpy already optimal), single-filament
  Biot–Savart, and the full AIC assembly swept over mesh size.

## Why generic-over-scalar matters

OAS components declare `declare_partials(method="cs")` — OpenMDAO differentiates
by calling `compute` with a tiny imaginary perturbation and reading the
imaginary part out. If the kernel only accepted `f64`, moving `compute` into
Rust would break differentiation. Writing it once against the `Scalar` trait
gives both the primal and the complex-step pass from the same code. The one
discipline required: the singularity guard branches on the **real part**
(`cr_sq.re() < EPS`), which keeps the function locally analytic — the Rust
mirror of the Python rule "never use `np.linalg.norm`/`np.abs` under complex
step."

## Measured results (4-core dev box, f64)

Microbenchmark (`bench.py`), Rust vs numpy:

| kernel | numpy | rust (1 thread) | rust (4 threads) |
|---|---:|---:|---:|
| `vec_add` (1e6) — one ufunc | 1.35 ms | 1.10 ms (≈tie) | — |
| `segment_vel` (2e5 pts) | 24.9 ms | 1.81 ms (~14×) | — |
| `assemble_aic` N=640 | 270 ms | 17.0 ms (~16×) | 4.96 ms (~54×) |
| `assemble_aic` N=1200 | 1.26 s | 63.7 ms (~20×) | 27.5 ms (~46×) |

End-to-end through OpenMDAO (`compute_totals` = primal + 2 complex-step passes,
i.e. what an optimizer pays per iteration):

| N panels | numpy | rust | speedup |
|---:|---:|---:|---:|
| 200 | 159 ms | 25 ms | 6.4× |
| 640 | 1537 ms | 236 ms | 6.5× |
| 1200 | 7513 ms | 905 ms | 8.3× |

## Honest caveats

- The end-to-end speedup (6–8×) is **lower** than the kernel microbench (10–60×)
  by design: `compute_totals` also runs the geometry recompute (numpy) and the
  dense linear solve (BLAS, identical in both). Rust only accelerates the
  assembly, so Amdahl's law caps the realized gain.
- Trivial / single-ufunc work (`vec_add`) ties numpy — don't port it. The win is
  specifically in branchy pairwise loops that numpy can only express by
  materializing big temporaries.
- This is a standalone reconstruction of the OAS kernel for measurement, not yet
  wired into upstream `openaerostruct`. Doing that — replacing `EvalVelMtx`'s
  body with a call here — is the natural next step the numbers justify.
