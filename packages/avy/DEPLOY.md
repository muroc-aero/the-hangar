# Deploying hangar-avy

The avy service follows the standard hangar deployment pattern (see
`skills/new-tool/SKILL.md` step 7). The Docker image pip-installs aviary
(at `AVY_REF`) + hangar-sdk + hangar-avy, mirroring the single workspace
venv used in dev.

## Docker

`packages/avy/Dockerfile`; built by the `avy` service in
`docker/docker-compose.yml` (host port 8005 -> container 8000). The
`ARG AVY_REF` default tracks `scripts/upstream-pins.env`; bump both
together.

```bash
docker compose -f docker/docker-compose.yml up --build avy
```

The viewer service mounts `./hangar_data/avy` read-only and
`HANGAR_VIEWER_DBS` includes `avy=/data/avy/provenance.db`.

The `omd` image also pip-installs aviary, so the native `avy/Sizing`
plan factory (Aviary's group inside the omd problem) runs there too; no
extra service is needed for it.

## Environment variables

| Variable | Value (deployed) | Notes |
|----------|------------------|-------|
| `AVY_TRANSPORT` | `http` | `stdio` for local/MCP-client use |
| `AVY_HOST` | `0.0.0.0` | |
| `AVY_PORT` | `8000` | In-container; native default is 8005 |
| `HANGAR_DATA_DIR` | `/data` | Artifacts + per-run scratch dirs |
| `HANGAR_PROV_DB` | `/data/provenance.db` | |

Auth (OIDC via `hangar.sdk.auth`) uses the same `.env` variables as the
other services (issuer, audience, JWKS URL) -- see `lakesideai-infra`'s
`.env` template.

## Reverse proxy and OIDC client

Both live in the private `lakesideai-infra` repo, not here (see the
Deployment section of the root `CLAUDE.md`): add the per-tool Caddyfile
block from `skills/new-tool/SKILL.md` step 7 with `<pkg>` = `avy`, and
register an `avy` OIDC client mirroring the existing tool clients (same
scopes as oas/ocp/pyc). The `.well-known/oauth-protected-resource`
endpoint is served by the app itself.

## Sizing runs and container resources

Every analysis call is a dymos+SLSQP optimization: ~20 s (sizing) to ~60 s
(payload-range) of single-core CPU with `OMP_NUM_THREADS=1`-style BLAS
settings recommended. Runs are serialized inside the process (a run lock
guards the cwd), so one container handles one analysis at a time; scale
replicas rather than threads if concurrent runs are needed.

The server keeps the last converged sizing per aircraft live in memory
(an AviaryProblem, tens of MB) so off-design and payload-range calls can
fly from it without re-sizing; `reset` releases it. Budget container
memory for one such problem per concurrently active aircraft.
