# Commands & Parameters Reference

Run `oas-cli <subcommand> --help` for the complete, auto-generated parameter
list for any tool. This file documents key parameters and gotchas.

## Common parameters

Most analysis tools accept these shared parameters:

| Parameter | CLI flag | Default | Notes |
|-----------|----------|---------|-------|
| `session_id` | `--session-id` | `"default"` | Groups related analyses; controls problem cache |
| `run_name` | `--run-name` | `None` | Optional label for identification in `list-runs`/`show` |

---

## Analysis tools

### create-surface

Define a lifting surface. Must be called before any analysis.

**Key geometry parameters:**
- `--name NAME` (default: "wing")
- `--wing-type TYPE` — `"rect"`, `"CRM"`, or `"uCRM_based"` (default: "rect")
- `--span SPAN` — full wingspan in m (default: 10.0)
- `--root-chord CHORD` — root chord in m (default: 1.0)
- `--taper RATIO` — tip/root chord ratio (default: 1.0)
- `--sweep DEG` — leading-edge sweep angle (default: 0.0)
- `--dihedral DEG` (default: 0.0)
- `--num-x N` — chordwise mesh nodes, >= 2 (default: 2)
- `--num-y N` — spanwise mesh nodes, **must be ODD** >= 3 (default: 7)
- `--symmetry` / `--no-symmetry` (default: True)
- `--span-cos-spacing F` — spanwise blending (default: 0.0)
- `--chord-cos-spacing F` — chordwise blending (default: 0.0)

**Shape control points** (JSON arrays, root-to-tip):
- `--twist-cp`, `--chord-cp`, `--t-over-c-cp`
- `--num-twist-cp N` — auto-generates twist CPs for CRM/uCRM

**Aerodynamic parameters:**
- `--CL0` — lift coefficient at alpha=0 (default: 0.0)
- `--CD0` — zero-lift drag coefficient (default: 0.015)
- `--with-viscous` / `--no-with-viscous` (default: True)
- `--with-wave` / `--no-with-wave` (default: False)
- `--S-ref-type TYPE` — `"wetted"` or `"projected"` (default: "wetted")

**Structural parameters** (required for aerostruct):
- `--fem-model-type TYPE` — `"tube"` or `"wingbox"` (None for aero-only)
- `--E`, `--G`, `--yield-stress`, `--mrho` — material properties
- `--safety-factor` (default: 2.5)
- `--thickness-cp JSON` — tube wall thickness, root-to-tip (tube only)
- `--spar-thickness-cp JSON`, `--skin-thickness-cp JSON` (wingbox only)
- `--original-wingbox-airfoil-t-over-c` (default: 0.12)

**Composite laminate** (set `--use-composite`):
- `--ply-angles JSON`, `--ply-fractions JSON`
- `--E1`, `--E2`, `--nu12`, `--G12` — composite moduli
- `--sigma-t1`, `--sigma-c1`, `--sigma-t2`, `--sigma-c2`, `--sigma-12max` — strengths

**Fuel / weight** (multipoint optimization):
- `--c-max-t` (default: 0.303), `--wing-weight-ratio` (default: 2.0)
- `--struct-weight-relief` / `--no-struct-weight-relief`
- `--distributed-fuel-weight` / `--no-distributed-fuel-weight`
- `--fuel-density` (default: 803 kg/m^3), `--Wf-reserve` (default: 15000 kg)
- `--n-point-masses N` (default: 0)

**Special:**
- `--groundplane` / `--no-groundplane` — ground effect (requires `symmetry=True`, incompatible with `beta != 0`)
- `--offset JSON` — `[x, y, z]` origin offset in m

### run-aero-analysis

Single-point VLM aerodynamic analysis.

- `--surfaces JSON` — list of surface names (required)
- `--velocity`, `--alpha`, `--Mach-number`, `--reynolds-number`, `--density`
- `--cg JSON` — center of gravity `[x, y, z]` (default: `[0, 0, 0]`)
- `--beta` — sideslip angle, deg (default: 0.0; incompatible with groundplane)
- `--height-agl` — height above ground, m (default: 8000; only active with groundplane)
- `--omega JSON` — angular velocity `[p, q, r]`, deg/s (None = no rotation; changes model topology on first use)

### run-aerostruct-analysis

Coupled aero + structural analysis. Surfaces must have `fem_model_type` set.

- All aero params from `run-aero-analysis` (except `--cg`, `--beta`)
- `--load-factor` (default: 1.0) — scales L=W trim weight, NOT aerodynamic loads
- `--W0` — aircraft empty weight, kg (default: 120000)
- `--speed-of-sound` (default: 295.4 m/s)
- `--CT` — thrust-specific fuel consumption, 1/s (default: 1.67e-4)
- `--R` — range, m (default: 11165000)

### compute-drag-polar

Sweep alpha and return arrays of [alpha, CL, CD, CM, L/D].

- `--alpha-start` (default: -5), `--alpha-end` (default: 15), `--num-alpha` (default: 21)
- Standard aero params: `--surfaces`, `--velocity`, `--Mach-number`, `--density`, `--reynolds-number`
- `--beta`, `--cg`

### compute-stability-derivatives

Compute CL_alpha, CM_alpha, static margin.

- `--alpha` — linearization angle (default: 5)
- Standard aero params: `--surfaces`, `--velocity`, `--Mach-number`, `--density`, `--reynolds-number`
- `--beta`, `--cg`

### run-optimization

Single-point or multipoint design optimization.

- `--surfaces JSON` (required)
- `--analysis-type` — `"aero"` or `"aerostruct"` (default: "aero")
- `--objective` — `"CD"`, `"fuelburn"`, or `"structural_mass"` (default: "CD")
- `--design-variables JSON` — list of dicts: `[{"name": "twist", "lower": -10, "upper": 10, "n_cp": 3}]`
- `--constraints JSON` — list of dicts: `[{"name": "CL", "equals": 0.5}]` (optional `"point": int` for multipoint)
- Standard aero/struct params
- `--objective-scaler` — scaler for objective function (default: 1.0)
- `--tolerance` — optimizer convergence tolerance (default: 1e-6)
- `--max-iterations` — maximum iterations (default: 200)
- `--capture-solver-iters` — capture solver residual history (default: False)
- `--flight-points JSON` — enables multipoint optimization; list of dicts with `velocity`, `Mach_number`, `density`, `reynolds_number`, `speed_of_sound`, `load_factor`

### reset

Clear all session state (surfaces, cached problems). In one-shot mode, also
clears the workspace state file.

---

## Observability tools

### visualize

Generate a plot for a completed run.

- `--run-id` — supports `"latest"` / `"last"` (default: "latest")
- `--plot-type` — `lift_distribution`, `drag_polar`, `stress_distribution`, `convergence`, `planform`, `opt_history`, `opt_dv_evolution`, `opt_comparison`, `deflection_profile`, `weight_breakdown`, `failure_heatmap`, `twist_chord_overlay`, `mesh_3d`, `multipoint_comparison`, `n2`
- `--output` — `"inline"` (base64 PNG), `"file"` (save to disk), `"url"` (dashboard links)
- `--case-name` — optional label for output filename

**Important:** `visualize` returns a **list**, not a dict. First element is metadata; second (if present) is image content.

### get-run

Full manifest for a run: inputs, outputs, validation, cache state.

- `--run-id` (supports "latest")

### get-detailed-results

Sectional/spanwise data. Detail level: "standard" or "full".

- `--run-id`, `--detail-level`

### configure-session

Set per-session defaults.

- `--visualization-output` — `"inline"`, `"file"`, or `"url"` (session-wide default)
- `--detail-level`, `--auto-plots`

### Other observability tools

- `pin-run` / `unpin-run` — prevent/release OpenMDAO problem eviction
- `get-n2-html` — fetch N2/DSM diagram HTML
- `get-last-logs` — server-side log records for debugging
- `set-requirements` — automatic validation checks on all results

---

## Artifact tools

- `list-artifacts` — browse saved runs (filterable by analysis type)
- `get-artifact` — fetch full result + metadata by run_id
- `get-artifact-summary` — metadata only (lightweight)
- `delete-artifact` — remove a saved artifact

---

## Convenience commands

These are built-in shortcuts, not tool subcommands:

### list-tools

```bash
oas-cli list-tools    # print all available tool names
```

### list-runs

```bash
oas-cli list-runs                      # show last 10 runs
oas-cli list-runs --limit 5            # show last 5 runs
oas-cli list-runs --analysis-type aero # filter by type
```

### show

```bash
oas-cli show                  # show latest run (default)
oas-cli show latest           # same thing
oas-cli show 20240315T143022_a1b2c3   # specific run
```

### plot

```bash
oas-cli plot latest lift_distribution              # saves to auto-named file
oas-cli plot latest drag_polar -o polar.png        # custom output path
oas-cli plot 20240315T143022_a1b2c3 stress_distribution
```

### viewer

Start the provenance/dashboard viewer server on localhost.

```bash
oas-cli viewer                          # default port 7654
oas-cli viewer --port 8080              # custom port
oas-cli viewer --db /path/to/sessions.db  # custom DB path
```

Access at:
- Dashboard: `http://localhost:7654/dashboard?run_id=<id>`
- Provenance: `http://localhost:7654/viewer?session_id=<id>`
