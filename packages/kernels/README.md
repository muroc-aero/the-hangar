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

| share (15×3) | where | portable under strategy 2? |
|---|---|---|
| ~2.7 s | `EvalVelMtx.compute` (VLM AIC assembly) — dominated by `np.cross` (30k calls; ~half its cost is numpy's `moveaxis`/`normalize_axis_tuple` axis machinery) + `einsum` | yes — *the apparent target* |
| ~2.7 s | scipy SuperLU `gstrf` + `solve` (FEM/coupled LU) | not via Rust — but a *parallel solver* helps a lot (see below) |
| ~2.0 s | OpenMDAO `subjac._apply_fwd_input` (linear-solve mat-vec) | no — framework |
| — | `VonMisesTube` | not in the top 18 |

At this small mesh `EvalVelMtx` looked like the kernel worth porting (~18%). The
next section **tests that hypothesis at scale — and disproves it.**

## Third kernel: EvalVelMtx (VLM AIC) — tested at tripled mesh sizes

`EvalVelMtx`'s two primal vortex helpers (`_compute_finite_vortex`,
`_compute_semi_infinite_vortex`) are ported to Rust (`vlm_finite_vortex` /
`vlm_semi_infinite_vortex`) and monkeypatched into OAS; `bench_oas_vlm.py`
asserts helper parity vs the OAS originals, then runs the full tube aerostruct
optimization stock vs patched (capped iterations). Results:

| mesh (ny×nx) | panels | stock | rust | **end-to-end speedup** | fuelburn match |
|---|---:|---:|---:|---:|---:|
| 15×4 | 42 | 4.50 s | 3.99 s | **1.13×** | rel 1e-14 |
| 45×6 | 220 | 209 s | 211 s | **0.99×** | rel 7e-10 |

**The speedup *shrinks* as the mesh grows — the opposite of what you'd hope.**
The mechanism is scaling, confirmed by profiling `EvalVelMtx.compute`'s share of
the run vs mesh size:

| mesh | panels | EvalVelMtx.compute % of run |
|---|---:|---:|
| 15×4 | 42 | 11.1% |
| 25×5 | 96 | 6.4% |
| 35×6 | 170 | 1.8% |
| 45×6 | 220 | 2.8% |

The AIC **assembly** is O(panels²), but the dense AIC/coupled **linear solve** is
O(panels³) (LAPACK/SuperLU) and OpenMDAO's derivative machinery scales
super-linearly too. So as the mesh grows the solve and framework overtake the
assembly, and the fraction strategy 2 can touch collapses from ~11% to ~3%.
Amdahl then caps the win: a free assembly at 3% of the run is a 1.03× ceiling.
(75×8 was abandoned as impractically slow — O(N³) — but the trend already
answers the question.)

## Where the time really goes: the sparse solve is NOT optimal

The strategy-2 results above show kernel porting doesn't move the wall clock. So
where *is* the time, and is it actually untouchable? Measuring the coupled
DirectSolver shows OAS factorizes a **large** sparse Jacobian — 55k DOF at 25×5,
**269k DOF at 45×6** — with scipy's `splu` (SuperLU): single-threaded, and a
weaker fill-reducing ordering than modern solvers. That is **not** "already
optimal," and it is the dominant cost.

`bench_pardiso_oas.py` monkeypatches MKL PARDISO into OpenMDAO's DirectSolver
(replaces `scipy.sparse.linalg.splu`) and runs the full tube aerostruct
optimization. `bench_solver.py` is the matching standalone solver microbench
(SuperLU vs PARDISO across system size and thread count). Full-optimization
results (maxiter capped; fuelburn identical to the last digit in every case):

| mesh | coupled DOF | SuperLU | PARDISO ×1 | PARDISO ×4 | algo | threads | **total** |
|---|---:|---:|---:|---:|---:|---:|---:|
| 25×5 | 54,915 | 19.9 s | 16.9 s | 12.0 s | 1.17× | 1.41× | **1.66×** |
| 45×6 | 268,853 | 187 s | 84.8 s | 52.7 s | 2.20× | 1.61× | **3.5×** |

Two separable effects, both real and growing with system size:
- **Algorithm** (PARDISO single-thread vs SuperLU): up to **2.2×** — better
  ordering / supernodal factorization, no parallelism involved.
- **Threading** (PARDISO 4 vs 1 thread): up to **1.6×** on 4 cores — genuine
  multicore scaling, matching the `bench_solver.py` crossover (parallel sparse
  factorization pays above ~16k DOF; OAS is well past it at 55k–269k).

So **a pure-Python solver swap gives 1.7–3.5× on the whole optimization**, scales
with both problem size and core count, and changes no answers — exactly the
multithreading win that kernel porting could not deliver.

## Overall conclusion of the experiment

- **Strategy 2 (Rust kernels under Python OpenMDAO)** wins big in microbenchmarks
  (10–150× isolated; 2.1–2.5× on a component's `compute_totals`), correct to
  machine precision, but **barely moves full-optimization wall-clock** (1.0–1.13×)
  — the portable assembly fraction *shrinks* as problems grow while the sparse
  solve dominates.
- **The dominant cost — the large sparse coupled solve — is the real lever, and
  it is reachable from pure Python**: swapping SuperLU → a parallel solver
  (PARDISO) buys 1.7–3.5×, from a better algorithm *and* true multicore threading.
  This is the answer to "can more cores / better architecture beat the numpy
  core?" — yes, but through the solver library, not through Rust kernels.

Net: for speeding up an OAS optimization, **swap the linear solver first** (huge
ratio of payoff to effort, no new language). Rust kernels are the right tool only
for an expensive leaf component in analysis-mode loops. Beating OpenMDAO's own
framework overhead is a separate, larger question — **strategy 3** (a native MDAO
core) — and is the only place Rust's GIL-free threading would uniquely apply.
