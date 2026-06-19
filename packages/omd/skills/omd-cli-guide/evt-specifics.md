# evt-Specific Notes

Deep-dive companion to `SKILL.md` covering the eVTOL (evtolpy) factories:
config resolution, the three component types, native analytic gradients,
and the plot types that only apply to evt runs.

The evt factories build a **native OpenMDAO** formulation of evtolpy
(`hangar.omd.evt`): idiomatic components with complex-step partials and a
real MTOW-closure solver, so sizing runs with analytic gradients and can be
optimized or coupled into a single converged solver. The native model
reproduces upstream evtolpy to floating point (parity suite:
`packages/evt/examples/native_parity`). A worked three-lane example lives in
`packages/omd/examples/evt_native_sizing/`.

## Component types

| Type | Mode | What it computes |
|------|------|------------------|
| `evt/Sizing` | sizing | Closes the MTOW fixed point (battery + structure mass scale with MTOW, which scales energy, which scales battery). Outputs the *sized* MTOW and mass breakdown. |
| `evt/Mission` | mission | Mission energy/power at the **as-configured** MTOW (no closure loop). Use when you want energy for a fixed vehicle, not a sized one. |
| `evt/SizingFD` | sizing | Same sizing result via the legacy evtolpy **black box** with finite-difference partials. Fallback for a config that exercises a non-smooth branch the native gradient path cannot cross. No analytic gradients. |

`evt/Sizing` and `evt/Mission` default to the native path. Setting
`native: false` on either forces the black box (equivalent to `evt/SizingFD`
for the sizing case). Prefer the native path; reach for FD only when the
native solver fails to converge on a config that the black box handles.

## Config resolution

The factory builds a complete evtolpy config from the component `config`
block. Most specific wins:

1. **`config_path`** (+ optional `config_dir`) -- load a full evtolpy JSON.
   `config_dir` is prepended when `config_path` is relative.
2. **`config_name`** -- a stem (no extension); `.json` is appended, then
   joined with `config_dir`. This is the study-friendly form: a matrix axis
   binds the bare case name here.
3. **`template`** (default `"test_all"`) -- seed from a named vehicle
   template when no path/name is given.

> **Portable vs filesystem.** `config_path` / `config_name` read a file from
> the server's filesystem -- fine for a local server run from the repo root,
> but the deployed image does **not** ship the example config dirs, so those
> forms fail there. **`template` needs no filesystem and works on any server
> (local or deployed/remote claude.ai).** Prefer `template` + overrides for
> portable, MCP-only work; use `config_path`/`config_name` for local studies
> over a directory of JSONs.

### Built-in vehicle templates (ship in the evt package)

| Template | Vehicle | Native `evt/Sizing` result |
|----------|---------|----------------------------|
| `test_all` | Lift+cruise reference: 6 lift + 6 tilt + 1 pusher, 3175 kg initial MTOW. The parity baseline. | -- |
| `archer_midnight` | Archer Midnight-class: vectored thrust, 6 tilt + 6 lift, no pusher; ~30 mi / 1500 ft mission. | sized MTOW ~2020 kg, battery ~288 kg, energy ~66 kWh |

Overrides **set** keys, they cannot **delete** them: starting from `test_all`
keeps its pusher rotor, and a partial override set leaves ~50 other keys at the
baseline (e.g. `test_all`'s high `landing_gear_drag_area_m2`), giving a heavier,
draggier aircraft. To reproduce a *specific* vehicle faithfully, start from the
matching `template`, not a few overrides on a generic baseline.

Then overrides merge in, in this order:

4. **Inline per-section dicts** -- a dict under any of the five section
   names (`aircraft`, `mission`, `power`, `propulsion`, `environ`).
5. **Flat `overrides`** -- a `{key: value}` dict; each key is routed to the
   section that owns it.
6. **`operating_points`** -- merged the same way as flat overrides.

Unknown override keys **raise** (evtolpy silently ignores them otherwise --
the same footgun the evt setters guard against). Section ownership comes
from the evtolpy schema; common keys: `payload_kg` (aircraft),
`batt_spec_energy_w_h_p_kg` (power), `rotor_diameter_m`/`lift_rotor_count`
(propulsion).

Paths resolve relative to the current working directory, so **run omd-cli
from the repo root** when a config lives under `packages/`.

### Minimal sizing component (portable -- named template, no file)

```yaml
# components/evtol.yaml
id: evtol
type: evt/Sizing
config:
  template: archer_midnight   # faithful Midnight baseline, ships in the package
  solver: newton              # MTOW-closure solver; "newton" (default) or "gs"
```

### Build a vehicle from a template + overrides (no JSON file)

The portable way to set vehicle specs through the MCP: seed a template, then
override only what you change. Each section dict (`aircraft`, `mission`,
`power`, `propulsion`, `environ`) takes any of that section's keys.

```yaml
id: evtol
type: evt/Sizing
config:
  template: archer_midnight
  solver: newton
  mission:  { cruise_s: 900 }                 # retarget range
  power:    { batt_spec_energy_w_h_p_kg: 285 } # higher-energy cell
  aircraft: { payload_kg: 500 }
```

### Local study over a directory of full configs (filesystem)

```yaml
id: evtol
type: evt/Sizing
config:
  config_dir: packages/evt/examples/abu_scitech_2026/cfg
  config_name: archer-midnight-1500-30   # local-only; not on the deployed image
  solver: newton
```

## Sizing solver: newton vs gs

`solver` selects how the MTOW fixed point is closed:

- **`newton`** (default) -- Newton over an implicit lower-bounded MTOW
  state. Gradient-friendly; required if you want analytic totals through the
  loop or you optimize with the loop live. Converges tighter than evtolpy's
  loose 1e-3 kg stop.
- **`gs`** -- `NonlinearBlockGS`, mirroring evtolpy's fixed-point
  substitution. Robust on configs where Newton struggles, but no clean
  analytic path through the iteration.

If a native solve reports `converged = 0` (rather than raising), the config
diverged; try `solver: gs`, or fall back to `evt/SizingFD`.

## Scalar outputs (run summary)

Both modes surface these scalars into the run summary (`omd-cli results
<run_id> --summary`):

`sized_mtow_kg`, `max_takeoff_mass_kg`, `empty_mass_kg`, `battery_mass_kg`,
`total_mission_energy_kw_hr`, `total_reserve_mission_energy_kw_hr`,
`payload_mass_frac`, `peak_power_kw`, `disk_loading_kg_p_m2`, `converged`.

`converged` is `1.0` on success, `0.0` on a diverged solve -- always check
it before trusting the rest. In `evt/Mission` mode `sized_mtow_kg` equals
the as-configured MTOW (no loop runs).

## Native analytic gradients (optimization)

The headline native capability the black box lacks: total derivatives flow
through the MTOW closure analytically (complex-step partials + the implicit
state), instead of finite-differencing the whole loop per design variable.

Any promoted evtolpy input is addressable by its bare name as a design
variable, and the scalar outputs above are usable as objective/constraints.
Example: minimize sized MTOW over battery specific energy.

```bash
omd-cli plan add-dv hangar_studies/evt-opt \
    --name batt_spec_energy_w_h_p_kg --lower 250 --upper 320 \
    --rationale "Cell roadmap envelope"
omd-cli plan set-objective hangar_studies/evt-opt \
    --name sized_mtow_kg --rationale "Lighter sized vehicle"
omd-cli run hangar_studies/evt-opt/plan.yaml --mode optimize
```

Use `evt/Sizing` with `solver: newton` for optimization. `evt/SizingFD`
will optimize too, but every gradient is a finite difference of the full
sizing loop -- far slower and noisier. The materializer allocates complex
vectors automatically for the native path (the factory sets
`force_alloc_complex`); you do not configure this.

## evt plot types

evt runs produce these additional plot types (via `omd-cli plot`):

| Plot | Description |
|------|-------------|
| `segment_energy` | Per-segment mission energy (kWh) bar chart |
| `segment_power` | Per-segment average electric power (kW) bar chart |
| `mass_breakdown` | Component empty-mass breakdown (kg) |
| `mtow_convergence` | MTOW fixed-point sizing history (`evt/SizingFD` only) |

These are in addition to the generic plots (convergence, dv_evolution, n2)
available for all component types.

`mtow_convergence` shows a real per-iteration trace only for `evt/SizingFD`,
which records the padded `mtow_history_kg` / `n_iterations` outputs. The
native `evt/Sizing` (newton/gs) does not record per-iteration MTOW history
yet, so the plot renders an explanatory placeholder there rather than
failing the batch; the same placeholder appears for any `evt/Mission` run
(no loop). Use the generic `convergence` plot to see the native solver drive
the MTOW residual down.
