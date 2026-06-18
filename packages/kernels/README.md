# hangar-kernels — native Rust hot kernels (proof of concept)

A small, self-contained experiment: take the hottest numerical kernels in the
OAS path and reimplement them in Rust behind pyo3, then prove each is a true
drop-in inside an OpenMDAO `ExplicitComponent`. Two kernels so far:

- **`EvalVelMtx`** — the N×N aerodynamic influence-coefficient (AIC) matrix
  (Biot–Savart from every ring vortex onto every collocation point).
- **`VonMisesTube`** — per-element FEM beam stress (local-frame transform +
  cross products + axial/torsional stress for each of ny−1 elements).

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

## Second kernel: VonMisesTube (FEM stress) — and a sharp lesson

`VonMisesTube` is a per-element Python loop (`for ielem in range(ny-1)`), so the
primal is a textbook ≥5× target. The kernel (`vonmises_tube` / `..._cs`) is
generic over the scalar type, same as the AIC kernel, so complex-step runs
through Rust. Crucially, upstream OAS **ships hand-coded analytic partials** for
this component — so `tests/test_vonmises_parity.py` validates against the *real*
OAS component as golden reference: the Rust primal matches OAS's `compute`, and
the complex-step-through-Rust Jacobian matches OAS's analytic `compute_partials`
to a relative error < 1e-7.

Three drop-in variants are measured (`bench_vonmises.py`) against the upstream
OAS component, which uses hand-coded analytic partials:

| ny | elems | `compute` (primal) | `compute_totals` — **rust-cs** | `compute_totals` — **rust-analytic** |
|---:|---:|---:|---:|---:|
| 21 | 20 | **22.6×** | 1.1× | **2.5×** |
| 51 | 50 | **46.3×** | 1.0× | **2.3×** |
| 101 | 100 | **93.3×** | 0.7× | **2.2×** |
| 201 | 200 | **156.9×** | 0.6× | **2.1×** |

**The lesson — and it refines the AIC story.** The primal is a huge win (20–150×,
growing with element count). But end-to-end *derivatives* depend entirely on how
you compute them:

- **`rust-cs`** (Rust primal, derivatives via OpenMDAO global complex-step) is a
  net **loss** (0.6–1.1×). Complex-step re-runs the primal once per input
  direction (nodes+radius+disp ≈ 10·ny ≈ 2000 at ny=201), while upstream gets the
  whole Jacobian in one analytic pass. A 100×-faster primal can't outrun 2000
  complex evaluations vs one analytic sweep.
- **`rust-analytic`** (Rust primal **+ Rust sparse Jacobian**) is a **2.1–2.5×
  win** over upstream's already-analytic partials, validated to rel error < 1e-7.

How the Rust Jacobian is built without hand-transcribing 160 lines of chain rule:
each element's two stresses depend on only **19 local inputs** (2 nodes, 1 radius,
2×6 disp), so `vonmises_tube_jac` complex-steps those 19 *inside Rust* per element
and emits the block-sparse data arrays matching the rows/cols the component
declares. Exact to machine precision, fully native, no pyo3 boundary per
perturbation and no OpenMDAO global complex-step.

Why "only" ~2.3× end-to-end (not 20×)? Because `compute_totals` also pays
OpenMDAO's framework overhead — linearization bookkeeping and the
unified-derivatives solve over the sparse Jacobian — which strategy 2 leaves in
Python. The kernel math is now a small fraction of the total, so that framework
cost is the ceiling. 2.3× over an *already-analytic* upstream is the honest,
real win.

Takeaways that generalize:
- **Analysis mode (no gradients):** porting the primal alone → 20–150×.
- **Gradient-based optimization:** port the analytic Jacobian too; complex-step
  through a fast primal is a trap when upstream already differentiates analytically.

## Reality check: time impact in a *full* OAS optimization

The component microbenchmarks above are real but in isolation. The honest
question is what a kernel does to a whole run. `bench_oas_aerostruct.py` runs the
canonical tube-model aerostruct optimization (DVs: twist, thickness, alpha;
objective: fuelburn) stock vs. with `VonMisesTube` monkeypatched to the Rust
kernels, and profiles the stock run.

| mesh (ny×nx) | elems | stock | rust | speedup | **VonMises % of run** | fuelburn match |
|---|---:|---:|---:|---:|---:|---:|
| 5×2 | 4 | 3.35 s | 3.25 s | 1.03× | **1.19%** | rel 2e-15 |
| 15×3 | 14 | 11.98 s | 11.44 s | 1.05× | **2.34%** | rel 6e-15 |
| 25×5 | 24 | 112.2 s | 115.6 s | 0.97× | **0.58%** | rel 4e-14 |

Two results, and the second is the point:

1. **Correctness holds inside a real coupled optimization** — the optimized
   fuelburn is identical to machine precision (rel 1e-14…1e-15) with the kernels
   swapped in. The drop-in is faithful, not just in a unit test.
2. **A 2.3× component speedup is invisible end-to-end** (1.0–1.05×), because
   `VonMisesTube` is only **0.6–2.3% of the run**. Amdahl's law in its cruelest
   form: making 1% of the work 2.3× faster moves the total by ~0.5%. The
   microbenchmarks weren't wrong — the component just doesn't dominate the clock.

**So: profile the full run *before* picking a kernel.** `VonMisesTube` was the
right choice to *prove the technique* (cleanest loop, the analytic-Jacobian
lesson) and the wrong choice to *move the wall clock*. The stock profile (15×3)
shows where the time actually goes:

| share | where | portable under strategy 2? |
|---|---|---|
| ~2.7 s | `EvalVelMtx.compute` (VLM AIC assembly) — dominated by `np.cross` (30k calls; ~half its cost is numpy's `moveaxis`/`normalize_axis_tuple` axis machinery) + `einsum` | **yes — the real target** |
| ~2.7 s | scipy SuperLU `gstrf` + `solve` (FEM/coupled LU) | no — already optimal C |
| ~2.0 s | OpenMDAO `subjac._apply_fwd_input` (linear-solve mat-vec) | no — framework |
| — | `VonMisesTube` | not in the top 18 |

The actionable conclusion: the kernel worth porting for wall-clock is
**`EvalVelMtx`** (the VLM AIC / Biot–Savart assembly) — ~18%+ of the run, much of
it pure `np.cross` overhead a native loop erases — and its primal already lives
in this package (`assemble_aic`). The remaining time is the sparse LU solve and
OpenMDAO's own machinery, neither of which strategy 2 touches.
