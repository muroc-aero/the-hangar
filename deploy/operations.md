# Hangar VPS Operations

## Services

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| oas-mcp | hangar-oas-mcp-1 | 8000 | OpenAeroStruct MCP server |
| ocp-mcp | hangar-ocp-mcp-1 | 8000 | OpenConcept MCP server |
| pyc-mcp | hangar-pyc-mcp-1 | 8000 | pyCycle MCP server |
| viewer | hangar-viewer-1 | 8080 | Unified provenance viewer |
| keycloak | hangar-keycloak-1 | 8080 | OIDC auth provider |
| postgres | hangar-postgres-1 | 5432 | Keycloak database |

## URLs

| URL | What |
|-----|------|
| `https://mcp.lakesideai.dev/oas/mcp` | OAS MCP endpoint |
| `https://mcp.lakesideai.dev/ocp/mcp` | OCP MCP endpoint |
| `https://mcp.lakesideai.dev/pyc/mcp` | PYC MCP endpoint |
| `https://mcp.lakesideai.dev/oas/viewer` | OAS per-tool provenance viewer |
| `https://mcp.lakesideai.dev/ocp/viewer` | OCP per-tool provenance viewer |
| `https://mcp.lakesideai.dev/pyc/viewer` | PYC per-tool provenance viewer |
| `https://mcp.lakesideai.dev/viewer` | Unified cross-tool provenance viewer |
| `https://mcp.lakesideai.dev/` | Landing page |
| `https://auth.lakesideai.dev/` | Keycloak (admin blocked by default) |

## Update a tool after code changes

```bash
cd ~/hangar/repo && git pull
cp ~/hangar/repo/deploy/docker-compose.prod.yml ~/hangar/
cd ~/hangar
docker compose -f docker-compose.prod.yml build --no-cache oas-mcp
docker compose -f docker-compose.prod.yml up -d oas-mcp
```

Replace `oas-mcp` with `ocp-mcp`, `pyc-mcp`, or `viewer` as needed. Build multiple at once:

```bash
docker compose -f docker-compose.prod.yml build --no-cache oas-mcp ocp-mcp pyc-mcp viewer
docker compose -f docker-compose.prod.yml up -d
```

## Update Caddy routing

After editing `~/caddy/Caddyfile`:

```bash
cd ~/caddy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

## Check status

```bash
cd ~/hangar
docker compose -f docker-compose.prod.yml ps
docker compose -f docker-compose.prod.yml logs oas-mcp --tail 10
docker compose -f docker-compose.prod.yml logs ocp-mcp --tail 10
docker compose -f docker-compose.prod.yml logs pyc-mcp --tail 10
docker compose -f docker-compose.prod.yml logs viewer --tail 10
```

Health endpoints (unauthenticated):

```bash
curl -s https://mcp.lakesideai.dev/oas/healthz
curl -s https://mcp.lakesideai.dev/ocp/healthz
curl -s https://mcp.lakesideai.dev/pyc/healthz
curl -s https://mcp.lakesideai.dev/viewer/healthz
```

## Restart a single service

```bash
cd ~/hangar
docker compose -f docker-compose.prod.yml restart oas-mcp
```

Note: `restart` reuses the existing image. If code changed, `build --no-cache` first.

## Stop / start

```bash
# Stop one service
docker compose -f docker-compose.prod.yml stop oas-mcp

# Stop everything (preserves volumes and bind mounts)
docker compose -f docker-compose.prod.yml down

# Start everything
docker compose -f docker-compose.prod.yml up -d
```

## View real-time logs

```bash
cd ~/hangar
docker compose -f docker-compose.prod.yml logs -f oas-mcp
docker compose -f docker-compose.prod.yml logs -f viewer
```

## Provenance viewer

### Per-tool viewers

Each tool serves its own viewer at `/<tool>/viewer`, showing only that tool's provenance data. Controlled by `HANGAR_PROV_VIEWER` in the compose file (enabled by default, set to `"off"` to disable).

### Unified viewer

The unified viewer at `/viewer` reads from all tool databases (mounted read-only) and merges sessions across tools. Sessions that span multiple tools show nodes with tool-colored borders (blue=OAS, orange=OCP, green=PYC) and cross-tool edges as dashed orange lines.

The viewer container needs OIDC credentials (same `hangar-viewer` Keycloak client). If the viewer shows no sessions after a fresh deployment, the provenance databases may not have been created yet -- run an analysis on each tool first.

### Viewer troubleshooting

**No sessions visible:** Check that provenance DBs exist:
```bash
ls -la ~/hangar/hangar_data/*/provenance.db
```

**No tool colors on nodes:** The `tool` column was added in a schema migration. Old sessions created before the migration have empty tool fields. New sessions will have tool labels. To verify the migration ran:
```bash
sqlite3 ~/hangar/hangar_data/oas/provenance.db ".schema sessions" | grep tool
```

**Viewer container not starting:** Check logs and verify OIDC env vars:
```bash
docker compose -f docker-compose.prod.yml logs viewer --tail 20
```

## Keycloak admin console

The admin console is blocked by Caddy by default. To access temporarily:

```bash
# 1. Comment out @admin block in ~/caddy/Caddyfile
# 2. Reload Caddy
cd ~/caddy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
# 3. Open https://auth.lakesideai.dev/admin/
# 4. Uncomment @admin block and reload when done
```

### Keycloak clients

| Client | Purpose |
|--------|---------|
| oas-mcp | OAS tool server MCP auth |
| ocp-mcp | OCP tool server MCP auth |
| pyc-mcp | PYC tool server MCP auth |
| hangar-viewer | Browser-based viewer OIDC login |

All tool clients need:
- `mcp:tools` scope assigned
- An audience mapper in the `mcp:tools` scope (e.g. `oas-mcp-audience` with `aud: oas-mcp`)

The hangar-viewer client needs:
- Valid redirect URIs for all viewer paths (per-tool and unified)
- Post-logout redirect URIs matching

## Fix data directory permissions

If a tool fails with `unable to open database file`:

```bash
sudo chown -R 999:999 ~/hangar/hangar_data/oas/
sudo chown -R 999:999 ~/hangar/hangar_data/ocp/
sudo chown -R 999:999 ~/hangar/hangar_data/pyc/
```

## Back up

```bash
# Keycloak DB
cd ~/hangar
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U keycloak keycloak > ~/keycloak_backup_$(date +%Y%m%d).sql

# Artifacts and provenance
cp -r ~/hangar/hangar_data ~/hangar_data_backup_$(date +%Y%m%d)
```

## Landing page

The landing page at `mcp.lakesideai.dev/` is served by Caddy from static files.
The Caddy container must mount the landing directory from the repo:

```yaml
# In ~/caddy/docker-compose.yml, add to caddy volumes:
- ~/hangar/repo/deploy/landing:/srv/landing:ro
```

After adding the volume:

```bash
cd ~/caddy && docker compose up -d caddy
```

To update the landing page after a `git pull`, no action is needed --
Caddy serves directly from the repo directory.

The landing page JS polls `/oas/healthz`, `/ocp/healthz`, `/pyc/healthz`
every 30 seconds to show live status indicators.

## Nuclear restart (rebuild everything from scratch)

```bash
cd ~/hangar
docker compose -f docker-compose.prod.yml down
cd ~/hangar/repo && git pull
cp ~/hangar/repo/deploy/docker-compose.prod.yml ~/hangar/
cd ~/hangar
docker compose -f docker-compose.prod.yml build --no-cache
docker compose -f docker-compose.prod.yml up -d
```
