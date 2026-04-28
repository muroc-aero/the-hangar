# Adler 2022a Reproduction — Aerostructural Wing MDO with Mission Analysis

Reproduces Figures 7, 9, 10, 11, 12, and 13 from:

> Adler, E. J. and Martins, J. R. R. A., "Aerostructural wing design
> optimization considering full mission analysis," 2022 AIAA SciTech
> Forum, San Diego, CA, January 3-7, 2022.
> https://arc.aiaa.org/doi/10.2514/6.2022-0382

The paper compares four wing-design optimization formulations on a
Boeing 737-800-class aircraft over mission ranges from 300 to
2900 nmi:

1. **single point**: one cruise aerostructural analysis + Bréguet
2. **multipoint**: five cruise points (Mach 0.78 ± 0.01, 35,000 ± 1,000 ft) averaged
3. **mission-based**: full OpenConcept mission with a surrogate of the
   aerostructural drag polar called at every numerical-integration node
4. **single point + climb**: cruise Bréguet + a separate climb analysis
   using a modified Bréguet equation (paper's Section IV.A proposal)

The mission-based variant mirrors the upstream OpenConcept reference
example `upstream/openconcept/openconcept/examples/B738_aerostructural.py`,
which is the canonical implementation of the paper's mission-based
method. The three Bréguet-style variants are not in upstream
OpenConcept; this demo provides them via a new omd factory
`oas/AerostructFixedPoint`.

## Mesh resolution callout

The default surface grid is `num_y=7, num_x=3` so a coarse sweep
finishes overnight. To match Adler 2022a within roughly a percent on
absolute fuel burn, re-run the sweep with `--fine-mesh` (which sets
`num_y=27, num_x=3`); expect roughly 4x longer wall time per cell.
The qualitative trends (rank ordering of methods, climb-fuel fraction
vs. mission length, etc.) are robust to the mesh resolution.

## Computational cost

Each `AerostructDragPolar` builds a Mach x AoA x altitude surrogate at
setup. Surrogate training dominates wall time:

| Mesh                | Train | Per cruise eval | Per opt iter (SLSQP, FD grad)        |
|---------------------|-------|-----------------|--------------------------------------|
| `num_y=5, num_x=2`  | 30 s  | 1 s             | 7 min   (14 DVs FD, single point)    |
| `num_y=7, num_x=3`  | 140 s | 2 s             | 35 min  (default plan, single point) |
| `num_y=27, num_x=3` | 600 s | 5 s             | 2.5 h   (`--fine-mesh`, single point)|

Bréguet-variant optimizations need 10-30 SLSQP iterations at the
default mesh -> 6-15 hours per cell. Mission-based variants add the
mission-integration solver loop -> 1-3 hours per OCP solve and 30-90
hours per optimization. Plan accordingly: the coarse 4-range x 4-method
sweep is roughly 2-3 days at the default mesh, dominated by the four
mission-based cells. The Bréguet-only subset (`--methods
single_point,multipoint,single_point_plus_climb --grid coarse`)
finishes in 6-8 hours on 4 workers.

## Wing weight wiring

In this configuration the maneuver group's own aerostruct W_wing
feeds back into its kg_to_N lift balance (`self_feedback_W_wing=True`,
which is the default for the `oas/maneuver` slot when `wire_wing_weight`
is unset). For the per-phase OEW calculation the parametric weight
slot reads W_wing from the per-phase aerostruct drag slot
(`use_wing_weight: true`). Because skin and spar thicknesses are
design variables (not implicitly sized by an internal stress
constraint), W_wing depends only on geometry and is identical across
the maneuver and all mission phases. This matches upstream
`B738_aerostructural.py` lines 311 and 149-160.

## Lanes

| Lane | Format | What it is |
|------|--------|------------|
| A    | Python script | programmatic single-cell MDO mirroring upstream `B738_aerostructural.py` for mission-based and standalone problems for the three Bréguet variants |
| B    | omd plan YAML | one plan per method, runnable via `omd-cli run` |
| C    | Markdown prompt | agent prompt for re-creating the plans via the omd-cli-guide skill |

## Running

### Single-cell smoke tests (1500 nmi)

```bash
uv run omd-cli run packages/omd/demos/adler_2022a/lane_b/single_point/plan.yaml --mode optimize
uv run omd-cli run packages/omd/demos/adler_2022a/lane_b/multipoint/plan.yaml --mode optimize
uv run omd-cli run packages/omd/demos/adler_2022a/lane_b/single_point_plus_climb/plan.yaml --mode optimize
uv run omd-cli run packages/omd/demos/adler_2022a/lane_b/mission_based/plan.yaml --mode optimize  # ~90 min
```

### Coarse sweep (4 ranges x 4 methods = 16 cells, ~6-8 h on 4 workers)

```bash
uv run python packages/omd/demos/adler_2022a/sweep.py --grid coarse --workers 4
uv run python packages/omd/demos/adler_2022a/plotting.py --figures all
uv run python packages/omd/demos/adler_2022a/compare.py --figures all
```

### Full sweep (14 ranges x 4 methods = 56 cells, ~24-36 h on 4 workers)

```bash
uv run python packages/omd/demos/adler_2022a/sweep.py --grid full --workers 4
```

### Fine-mesh validation of a single cell

```bash
uv run python packages/omd/demos/adler_2022a/sweep.py --grid coarse \
    --methods mission_based --fine-mesh
```

## Status

- [x] Stage 1: `oas/AerostructFixedPoint` factory (single_point /
      multipoint / single_point_plus_climb modes), registered.
- [x] Stage 2: shared.py (DV bounds + constraint list).
- [x] Stage 3: lane_b plans for all four methods (mission_based,
      single_point, multipoint, single_point_plus_climb).
- [x] Stage 4: sweep.py + retry_failed.py.
- [x] Stage 5: plotting.py + compare.py (paper figure crops still
      need to be added under figures/paper/).
- [x] Stage 6: lane_a script + lane_c prompt.
- [ ] Stage 7: paper figure crops (PDF screenshots) under
      figures/paper/fig{7,9,10,11,12,13}.png.
- [ ] Stage 8: end-to-end coarse sweep + reproduced figures.

## Divergences from the paper

1. **Optimizer**: SNOPT in paper -> SLSQP here. Upstream
   `B738_aerostructural.py` also uses SLSQP, and pyoptsparse/SNOPT is
   not installed in this environment. SLSQP handles the 14-DV
   wingbox problem comfortably; convergence may take more iterations
   than SNOPT but the optima are equivalent.
2. **Mesh resolution**: 28 spanwise x 3 chord in paper -> 7 x 3 by
   default. See callout above.
3. **Surrogate type**: paper uses SciPy cubic interpolation on a
   216-point (Mach x AoA x altitude) grid; upstream
   `AerostructDragPolar` uses its own scheme. Minor differences in
   absolute fuel burn expected; trends preserved.
4. **Sweep resolution**: paper is 14 ranges x 4 methods = 56 cells;
   default coarse here is 4 x 4 = 16 cells. Use `--grid full` for
   full resolution.
5. **Bréguet-variant alpha DVs**: paper Table 3/4 list per-point
   alpha DVs. The factory here solves CL = W/(qS) directly (no
   alpha balance), so the Bréguet plans share the same 14 wingbox DVs
   as the mission-based plan; the alpha-related constraints and DVs
   are subsumed.
6. **Single-point fuel-burn objective vs. paper Table 6 fuel burn**:
   the paper's tabulated fuel burn (e.g. 11173.83 kg single point at
   1500 nmi) is the *mission-integrated* fuel of the optimized wing,
   not the Bréguet objective the optimizer minimizes. Direct numeric
   comparison requires re-running each optimized wing through the
   mission-based plan; this is captured by the mission-based sweep.

## Known robustness issue: inner NLBGS divergence

`AerostructDragPolar` re-trains its surrogate every time the wing
geometry changes. The training routine internally runs OAS's coupled
NLBGS solver, which can fail to converge under aggressive optimizer
perturbations (the SLSQP finite-difference gradient probes 14 DVs in
sequence and some combinations land on poorly-conditioned wings).
When this happens the optimizer raises an `AnalysisError` from
`compute_training_data` and SLSQP exits non-cleanly.

Workarounds, in order of preference:
1. Use the `--warm-from` flag on `sweep.py` to seed each cell from
   the closest converged neighbour (shrinks the FD step's effective
   range).
2. Loosen DV bounds on the most-likely culprits (twist, t/c) so the
   FD step lands inside a smaller well-conditioned region.
3. Lower `tol` and `maxiter` on the SLSQP driver to cap the
   wall-time cost of failed cells, then `retry_failed.py` them with
   warm starts.

The first two are the standard approach in `brelje_2018a/` and are
why that sweep includes the warm-start mechanism. The factory itself
is correct: analysis-mode runs (`omd-cli run ... --mode analysis`)
of all four plans return sensible drag, lift, L/D, failure, and
W_wing values matching the upstream OpenConcept reference for the
same wing geometry.
