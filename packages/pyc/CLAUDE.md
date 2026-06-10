# hangar-pyc -- pyCycle MCP Server

This package wraps pyCycle as an MCP tool server for gas turbine
thermodynamic cycle analysis.

## Key constraints

- `run_design_point` MUST precede `run_off_design`: the design point sizes
  the geometry (areas, map scalars) that off-design holds fixed
- Off-design builds a fresh multipoint problem each call (design point
  re-solves inside it); no live Problem is cached in the session
- SLS conditions use `MN=0.000001` (near-zero), never exactly 0
- `T4_target` should stay below ~3600 degR (material limits)
- `thermo_method="TABULAR"` is ~10x faster than CEA with similar accuracy
  for Jet-A; prefer it unless CEA accuracy is required
- Engine names must match exactly between `create_engine` and analysis calls
- Session state is `hangar.pyc.state.PycSession` (typed `engines` registry);
  the artifact store is the shared SDK singleton

## Archetypes

- `turbojet` -- single-spool turbojet (the only archetype this server
  exposes today; hbtf/turboshaft/mixedflow live in `hangar.omd.pyc`)

## Ports

oas=8000, ocp=8001, pyc=8002 (native defaults; docker-compose maps the same
host ports onto in-container port 8000).

## Testing

```bash
uv run pytest packages/pyc/tests/ -m "not slow"
```
