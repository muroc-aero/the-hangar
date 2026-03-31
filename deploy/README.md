# Hangar Production Deployment

Multi-tool MCP server deployment with shared Keycloak auth.

## Architecture

```
                         ┌─────────────────────────────────────┐
    Clients              │  Caddy (~/caddy/)                   │
    (Claude Code,        │                                     │
     claude.ai,          │  mcp.lakesideai.dev                 │
     Codex)              │    /oas/*  -> oas-mcp:8000          │
         |               │    /ocp/*  -> ocp-mcp:8000          │
         v               │                                     │
    +-----------+        │  auth.lakesideai.dev                │
    |TLS + Route|--------│    /*     -> keycloak:8080          │
    +-----------+        └─────────────────────────────────────┘
                                        |
                         ┌──────────────|──────────────────────┐
                         │  Hangar (~/hangar/)                  │
                         │                                     │
                         │  +---------+  +---------+           │
                         │  | oas-mcp |  | ocp-mcp |  ...     │
                         │  +---------+  +---------+           │
                         │       |              |              │
                         │  +---------+  +---------+           │
                         │  |Keycloak |--|Postgres |           │
                         │  +---------+  +---------+           │
                         └─────────────────────────────────────┘
```

## Documentation

| Doc | Purpose |
|-----|---------|
| [keycloak-setup.md](keycloak-setup.md) | Full Keycloak configuration from scratch (realm, clients, scopes, Google login) |
| [migration-from-oas.md](migration-from-oas.md) | Step-by-step migration from the old single-tool `~/oas/` deployment |
| [user-guide.md](user-guide.md) | Instructions to send new users for connecting their clients |

## Quick start (fresh install)

1. Clone the repo on the VPS:
   ```bash
   mkdir -p ~/hangar
   git clone https://github.com/muroc-aero/the-hangar.git ~/hangar/repo
   ```
2. Set up env and compose:
   ```bash
   cp ~/hangar/repo/deploy/docker-compose.prod.yml ~/hangar/
   cp ~/hangar/repo/deploy/.env.example ~/hangar/.env
   # Edit ~/hangar/.env and fill in secrets
   ```
3. Merge `Caddyfile.example` routes into `~/caddy/Caddyfile`
4. Start the stack:
   ```bash
   cd ~/hangar
   docker compose -f docker-compose.prod.yml up -d
   ```
5. Configure Keycloak: follow [keycloak-setup.md](keycloak-setup.md)

## Migrating from the old OAS setup

If you currently have `~/oas/` with the `oas` realm, follow
[migration-from-oas.md](migration-from-oas.md) instead.

## Updating a tool

```bash
cd ~/hangar/repo && git pull
cd ~/hangar
docker compose -f docker-compose.prod.yml build --no-cache oas-mcp
docker compose -f docker-compose.prod.yml up -d oas-mcp
```

## Adding a new tool

1. Uncomment (or add) the tool service in `docker-compose.prod.yml`
2. Create an OIDC client in the Keycloak `hangar` realm (see [keycloak-setup.md, section 6](keycloak-setup.md#6-adding-a-new-tool-eg-ocp))
3. Add `<TOOL>_OIDC_CLIENT_SECRET` to `.env`
4. Add `handle_path /<tool>/*` route to the Caddyfile
5. Reload Caddy:
   ```bash
   cd ~/caddy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
   ```
6. Start the new service:
   ```bash
   docker compose -f docker-compose.prod.yml up -d <tool>-mcp
   ```

## Keycloak admin console

The Caddyfile blocks `/admin/*` and `/realms/master/*` on `auth.lakesideai.dev`.
To temporarily re-enable:

1. Comment out the `@admin` block in the Caddyfile
2. Reload Caddy
3. Go to `https://auth.lakesideai.dev/admin/`
4. Uncomment the block and reload Caddy when done
