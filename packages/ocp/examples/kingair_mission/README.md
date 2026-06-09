# King Air C90GT Mission Demonstration: Three-Lane Comparison

This directory runs one OpenConcept mission analysis three different ways and
checks that they agree. It doubles as the verification harness for the
twin-turboprop parity work (issues #36, #38, #39).

| Step | Approach | Files |
|------|----------|-------|
| **Original example** | Upstream OpenConcept script (as-is) | `openconcept/examples/KingAirC90GT.py` |
| **Lane A** | Upstream example wrapped in an importable `run()` (the reference) | `lane_a/*.py` |
| **Lane B** | MCP tools via `ocp-cli` | `lane_b/*.json` |
| **Lane C** | Claude Code agent with MCP server | `lane_c/*.prompt.md` |

The analysis: **King Air C90GT, twin turboprop, full mission** with
balanced-field takeoff + climb/cruise/descent, 1000 NM at FL290, 1000 lb
payload. Calibration matches the upstream example: `structural_fudge = 1.67`,
`takeoff_throttle = 0.75`, prop rpm 1900 (read from the template).

---

## Why this example exists

Running the King Air through the MCP tools used to diverge from the direct
OpenConcept run. Three gaps caused it:

| Issue | Gap | Fix |
|-------|-----|-----|
| #36 | `structural_fudge` / `takeoff_throttle` not exposed in `configure_mission` | PR #37 |
| #38 | twin OEW counted one engine; balanced-field ignored engine-out (`propulsor_active`) | PR #40 |
| #39 | prop rpm hardcoded to 2000; King Air uses 1900 | template-driven rpm |

With all three applied, and both lanes converged to Newton `1e-10`, Lane B
reproduces Lane A to machine precision:

| Metric | Lane A (upstream) | Lane B (OCP) | Δ |
|--------|------:|------:|------:|
| OEW    | 2935.44 kg | 2935.44 kg | exact |
| Fuel burn | 756.02 kg | 756.02 kg | ~1e-13 |
| MTOW   | 4581 kg | 4581 kg | exact |
| TOFL   | 3054.64 ft | 3054.64 ft | ~1e-10 |

Earlier this example showed a ~0.03 ft TOFL gap. That was **not** a model
difference: the upstream `run_kingair_analysis` stops Newton at `atol=rtol=1e-6`,
under-converging the balanced field, while the OCP builder drives to `1e-10`.
Lane A now re-converges the reference to `1e-10` after the upstream run (see
`lane_a/full_mission.py`), so all four metrics agree to machine precision.

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
uv run python upstream/openconcept/openconcept/examples/KingAirC90GT.py
```

> Generates an `*_out/` report directory and opens matplotlib plots. Lane A
> suppresses both.

---

## Step 1: Run Lane A (reference)

Lane A wraps `run_kingair_analysis` in an importable `run()` that returns a
structured dict.

```bash
uv run python packages/ocp/examples/kingair_mission/lane_a/full_mission.py
```

---

## Step 2: Run Lane B (MCP tools)

```bash
uv run ocp-cli --pretty run-script packages/ocp/examples/kingair_mission/lane_b/full_mission.json
# or, all-in-one summary:
uv run python packages/ocp/examples/kingair_mission/lane_b/run_all.py
```

---

## Step 3: Run Lane C (agent prompts)

See `lane_c/README.md`. Paste `lane_c/full_mission.prompt.md` into Claude Code
with the OpenConcept MCP server connected.

---

## See the lanes match (side by side)

One command runs Lane A and Lane B and prints both columns so you can read the
match straight off the terminal:

```bash
uv run python packages/ocp/examples/kingair_mission/compare.py
```

Expected output:

```
King Air C90GT full mission -- Lane A (upstream) vs Lane B (OCP MCP)
================================================================
Metric              Lane A        Lane B     rel. diff
----------------------------------------------------------------
OEW             2935.44 kg    2935.44 kg     0.00e+00
Fuel burn        756.02 kg     756.02 kg     1.69e-13
MTOW               4581 kg       4581 kg     0.00e+00
TOFL            3054.64 ft    3054.64 ft     1.06e-10
================================================================
All four metrics match to machine precision (both lanes at Newton 1e-10).
```

Or run each lane on its own and eyeball the numbers:

```bash
# Lane A (upstream reference) -- prints a JSON dict
uv run python packages/ocp/examples/kingair_mission/lane_a/full_mission.py

# Lane B (OCP MCP tools) -- prints a labelled summary
uv run python packages/ocp/examples/kingair_mission/lane_b/run_all.py
```

> The three fixes (#37, #40, #39) are in `main`. They are what makes the lanes
> agree: without #37 Lane B cannot pass the calibration params, without #40 the
> balanced field runs both engines, and without #39 the prop rpm defaults to
> 2000. Revert any one and the comparison diverges.

---

## Parity tests

```bash
uv run python -m pytest packages/ocp/examples/kingair_mission/tests/ -v --rootdir=.
```

`test_b_matches_a` is the comparison check: it asserts Lane B reproduces Lane A
across all four reported metrics (OEW, fuel, MTOW, TOFL) within tolerance, the
same numbers `compare.py` prints. Reverting any of the three fixes, or removing
Lane A's `1e-10` re-convergence, makes it fail.
