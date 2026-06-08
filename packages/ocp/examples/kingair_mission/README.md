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

With all three applied, Lane B reproduces Lane A:

| Metric | Lane A (upstream) | Lane B (OCP) | Δ |
|--------|------:|------:|------:|
| OEW    | 2935.44 kg | 2935.44 kg | exact |
| Fuel burn | 756.02 kg | 756.02 kg | exact |
| TOFL   | 3054.61 ft | 3054.64 ft | 0.001 % |

The TOFL Δ is **not** a model difference. The upstream `run_kingair_analysis`
stops Newton at `atol=rtol=1e-6`; the OCP builder converges to `1e-10`.
Tightening the reference to `1e-10` gives `3054.641429 ft`, which matches Lane B
to machine precision. The 0.03 ft gap is the upstream example under-converging,
not OCP.

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
uv run ocp-cli run-script packages/ocp/examples/kingair_mission/lane_b/full_mission.json --pretty
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
Fuel burn        756.02 kg     756.02 kg     1.54e-08
MTOW               4581 kg       4581 kg     0.00e+00
TOFL            3054.61 ft    3054.64 ft     9.37e-06
================================================================
OEW and fuel match exactly; TOFL matches to solver tolerance.
```

Or run each lane on its own and eyeball the numbers:

```bash
# Lane A (upstream reference) -- prints a JSON dict
uv run python packages/ocp/examples/kingair_mission/lane_a/full_mission.py

# Lane B (OCP MCP tools) -- prints a labelled summary
uv run python packages/ocp/examples/kingair_mission/lane_b/run_all.py
```

> Requires PRs #37 and #40 to be merged. Without them Lane B cannot pass the
> calibration params (#37) and the balanced field runs both engines (#40), so
> the TOFL column will not match until all three fixes are present.

---

## Parity tests

```bash
uv run python -m pytest packages/ocp/examples/kingair_mission/tests/ -v --rootdir=.
```

`test_b_matches_a` asserts Lane B reproduces Lane A within tolerance. Reverting
any of the three fixes makes it fail.
