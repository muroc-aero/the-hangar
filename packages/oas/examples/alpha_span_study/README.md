# alpha_span_study -- study-layer demos for script runners

Two committed study specs demonstrating the tool-independent study layer
(`hangar.sdk.study`, see `docs/STUDIES.md`) on tools whose runner is the
generic script runner: each case is a workflow script (the same
`[{tool, args}]` steps `oas-cli run-script` executes), patched per case by
the matrix bindings.

## study.yaml -- OAS alpha x span grid

3x3 grid over angle of attack and span on a small rectangular wing, plus
one manually inserted finer-mesh anchor case (`a2-s10-fine`) to check mesh
sensitivity against its matrix twin. `success_when` maps the analysis
envelope's physics validation block to converged/failed.

```bash
hangar-study review  packages/oas/examples/alpha_span_study/study.yaml
hangar-study generate packages/oas/examples/alpha_span_study/study.yaml  # reviewable scripts, no compute
hangar-study run     packages/oas/examples/alpha_span_study/study.yaml --max-cases 2   # pilot
hangar-study run     packages/oas/examples/alpha_span_study/study.yaml --yes           # the rest
hangar-study results oas-alpha-span
```

Expected: 10/10 converged in well under a minute; CL grows with alpha and
span, CL(a2-s10-fine) within a few percent of CL(a2-s10).

## cross_tool_study.yaml -- OAS wings + pyCycle engines in one study

Two matrix blocks with different `runner:` values (oas and pyc). Runners
load from installed packages via the `hangar.study_runners` entry-point
group, so this works from `hangar-study` with no tool imports and no omd
dependency. The case table keeps one schema across tools: each runner
fills the output columns it understands (CL/CD vs TSFC/Fn) and leaves the
rest empty.

```bash
hangar-study run packages/oas/examples/alpha_span_study/cross_tool_study.yaml --yes
hangar-study results aero-engine-cross-tool
```

The pyCycle design points dominate the wall time (about a minute each);
the wing cases are near-instant.
