# Boeing 737-800 Reserve Mission: Three-Lane Comparison

This directory runs one OpenConcept mission analysis three different ways and
checks that they agree (approximately).

| Step | Approach | Files |
|------|----------|-------|
| **Original example** | Upstream OpenConcept script (as-is) | `openconcept/examples/B738.py` |
| **Lane A** | Upstream example wrapped in an importable `run()` (the reference) | `lane_a/*.py` |
| **Lane B** | MCP tools via `ocp-cli` | `lane_b/*.json` |
| **Lane C** | Claude Code agent with MCP server | `lane_c/*.prompt.md` |

The analysis: **Boeing 737-800, twin turbofan, `with_reserve` mission** ---
climb/cruise/descent + reserve climb/cruise/descent + loiter, 2050 NM at FL330
with a reserve diversion at FL150. This mirrors the upstream
`run_738_analysis`.

---

## Why this example exists

The other OCP demonstrations are all propeller aircraft on short GA missions:

| Demo | Aircraft | Architecture | Mission |
|------|----------|--------------|---------|
| `caravan_mission` | Cessna 208 / hybrid twin | turboprop, twin_series_hybrid | basic / full / hybrid |
| `kingair_mission` | King Air C90GT | twin_turboprop | full (balanced-field takeoff) |
| **`b738_mission`** | **Boeing 737-800** | **twin_turbofan** | **with_reserve** |

This one is deliberately the **most different** OCP example we can build with
the supported tooling:

- a **transonic jet airliner** (~79 t MTOW) instead of a GA prop,
- the **`twin_turbofan`** architecture, which routes through OpenConcept's
  **CFM56** surrogate and the **`IntegratorGroup`** code path -- a different
  branch of the OCP builder (`is_cfm56`) from every other example here,
- a **`with_reserve`** mission (reserve diversion + loiter), which neither
  other demo exercises.

---

## Prerequisites

```bash
# From the workspace root
cd /path/to/the-hangar
uv sync
uv run python -c "import openconcept; print('OpenConcept OK')"
uv run python -c "import hangar.ocp; print('hangar-ocp OK')"
```

---

## Step 0: Run the Original Example

```bash
uv run python upstream/openconcept/openconcept/examples/B738.py
```

> Generates an `*_out/` report directory and opens matplotlib plots. Lane A
> suppresses both.

---

## Step 1: Run Lane A (reference)

Lane A wraps `run_738_analysis` in an importable `run()` that returns a
structured dict.

```bash
uv run python packages/ocp/examples/b738_mission/lane_a/reserve_mission.py
```

---

## Step 2: Run Lane B (MCP tools)

```bash
uv run ocp-cli --pretty run-script packages/ocp/examples/b738_mission/lane_b/reserve_mission.json
# or, all-in-one summary:
uv run python packages/ocp/examples/b738_mission/lane_b/run_all.py
```

---

## Step 3: Run Lane C (agent prompts)

See `lane_c/README.md`. Paste `lane_c/reserve_mission.prompt.md` into Claude
Code with the OpenConcept MCP server connected.

---

## See the lanes side by side

```bash
uv run python packages/ocp/examples/b738_mission/compare.py
```

---

## Where the lanes differ

This is the important part, and the reason this demo is **not** a bit-for-bit
parity harness like `kingair_mission`. Two structural differences between the
upstream script and the MCP `configure_mission` API are responsible.

### 1. Ramped vs constant speed schedules

`B738.py` ramps the airspeed and vertical speed across every phase with
`np.linspace`:

| Phase | Upstream (ramped) | Lane B (constant) |
|-------|-------------------|-------------------|
| climb vs | 2300 -> 600 ft/min | 1450 ft/min |
| climb Ueas | 230 -> 220 kn | 225 kn |
| cruise Ueas | 265 -> 258 kn | 261 kn |
| descent vs | -1000 -> -150 ft/min | -575 ft/min |
| descent Ueas | 250 kn | 250 kn |

`configure_mission` exposes only a single constant value per phase, so Lane B
flies the means of the upstream ramp endpoints. The block-fuel difference from
this is a few percent.

### 2. Reserve-phase speeds are not exposed

`configure_mission` lets you set the reserve **altitude** (and range / loiter
time) but **not** the reserve climb/cruise/descent/loiter **speeds**. The OCP
builder defaults those to King-Air values:

| Reserve phase | Upstream B738 | OCP builder default |
|---------------|---------------|---------------------|
| reserve climb Ueas | 230 kn | 124 kn |
| reserve cruise Ueas | 250 kn | 170 kn |
| reserve descent Ueas | 250 kn | 140 kn |
| loiter Ueas | 200 kn | 200 kn |

So the **reserve + loiter fuel diverges more than the block fuel**. This is a
real limitation of the current `configure_mission` API for jet reserve
missions, not a solver problem -- it would make a good follow-up issue (expose
reserve-phase speeds, the way `kingair_mission` motivated exposing
`structural_fudge` / `takeoff_throttle`).

### What still matches closely

- **MTOW** -- a direct passthrough from the shared aircraft data dict.
- **OEW** -- the CFM56 path uses a constant OEW from the same data dict.
- **Block fuel** -- within a few percent (the main mission flies the same
  range/altitude; only the speed schedule shape differs).

---

## Parity tests

```bash
uv run python -m pytest packages/ocp/examples/b738_mission/tests/ -v --rootdir=.
```

`test_b_approximates_a` asserts Lane B reproduces Lane A's block fuel within a
loose tolerance (`shared.TOL_BLOCK_FUEL`) and OEW/MTOW closely. The reserve
total is intentionally not asserted -- see "Where the lanes differ". All tests
are marked `slow` (they build and solve a full OpenMDAO problem).

---

## Parameter Reference

All shared parameters live in `shared.py`, mapped from the upstream example:

| Analysis | Upstream Example | Template | Architecture | Mission |
|----------|-----------------|----------|--------------|---------|
| Reserve mission | `B738.py` (`run_738_analysis`) | b738 | twin_turbofan | with_reserve |
