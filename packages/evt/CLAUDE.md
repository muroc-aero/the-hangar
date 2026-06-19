# hangar-evt -- evtolpy MCP Server

This package wraps [evtolpy](https://github.com/starbelt/evtolpy) as an MCP
tool server for electric VTOL aircraft sizing and mission-energy analysis.

## Key constraints

- evtolpy's only entry point is `Aircraft(path_to_json)`. The builder serializes
  the session config to a temp JSON file and constructs from it. Construction is
  cheap; physics runs lazily on property access. A fresh `Aircraft` is built per
  analysis call -- never cache and reuse one, because `_iterate_mtow` mutates
  `max_takeoff_mass_kg` in place.
- A config must be **complete** (all five sections) before building -- the
  upstream constructor indexes keys directly and `KeyError`s on a missing one.
  `load_vehicle_template` seeds a complete baseline; setters only override keys.
- evtolpy **silently ignores unrecognized config keys**, so the setters and the
  sweep validator reject unknown keys up front (with a typo suggestion). This is
  the same failure class as OAS silently dropping unknown DV names.
- `run_mission_analysis` reads an **unsized** aircraft (as-configured MTOW),
  matching upstream's `log_mission_segment_*` / `log_mass_breakdown` scripts.
  `run_sizing` runs the MTOW iteration (`log_mtow_iteration`). They are separate.
- The MTOW iteration raises `ValueError` on divergence (upstream safeguard);
  `run_sizing` surfaces it as a tool error, and a non-converged-but-returned
  result is flagged as a failed `mtow.converged` finding -- never a silent pass.
- Units are baked into key/attribute names (`_kg`, `_kw`, `_kw_hr`, `_m`,
  `_m_p_s`, `_s`); never convert implicitly.
- ABU (Autonomous Battery Unit) analysis is **out of scope for v1**.

## Vehicle templates

- `test_all` -- lift+cruise eVTOL reference (6 lift + 6 tilt rotors + 1 pusher,
  3175 kg initial MTOW); the upstream `test-all.json` baseline used for parity.
- `archer_midnight` -- Archer Midnight-class (vectored thrust, 6 tilt + 6 lift,
  no pusher; ~30 mi / 1500 ft mission), vendored from the AIAA SciTech 2026
  case-study config. Native `evt/Sizing` closes it to ~2020 kg sized MTOW. A
  faithful named baseline that ships in the package, so it is reachable on a
  deployed server with no filesystem config; override sections to customize.

## Native OpenMDAO model (omd integration)

The omd `evt/Sizing` and `evt/Mission` factories build a **native** OpenMDAO
formulation of evtolpy that lives in `hangar.omd.evt` (not in this package), so
eVTOL sizing runs with analytic (complex-step) gradients and can be coupled into
a single converged solver. It is a faithful transcription of upstream evtolpy
and matches this package's black box (`omd_component.EvtolSizingComp`) to
floating point. The black box stays as `evt/SizingFD` (FD fallback / parity
oracle). The MCP tools and CLI in this package still use the black box directly.
See `docs/native-openmdao-rewrite-implementation-plan.md` and the parity suite
`examples/native_parity/`.

## Upstream packaging

evtolpy ships no `pyproject.toml`. `scripts/evtolpy-packaging.patch` adds one to
the pinned clone so it installs as an editable package; `setup-upstream.sh`
applies it (reverse-applies before a pin bump). Pin lives in
`scripts/upstream-pins.env` (`EVTOL_REF`). Drop the patch once upstream packages.

## Ports

oas=8000, ocp=8001, pyc=8002, omd=8003, evt=8004 (native defaults;
docker-compose maps the same host ports onto in-container port 8000).

## Testing

```bash
uv run pytest packages/evt/tests/ -m "not slow"
# parity suites (per-directory; each sets up its own sys.path):
uv run pytest packages/evt/examples/mission_segments/tests/
uv run pytest packages/evt/examples/abu_scitech_2026/tests/   # AIAA SciTech 2026 case study
```

## Examples

- `examples/mission_segments/` -- three-lane parity (energy/power/weight) vs
  the direct evtolpy API at the `test_all` baseline.
- `examples/abu_scitech_2026/` -- non-ABU reproduction of the AIAA SciTech 2026
  case study (3 vehicles x 2 altitudes x 3 ranges = 18 cases) in lane A/B/C
  form. Energy reproduces the paper exactly; sized MTOW shows a documented
  upstream resizing-loop drift (and two Joby S4 60-mile divergences). See its
  README for the fidelity table.
