# Migration Guide: Single-Tool OAS -> Multi-Tool Hangar

Step-by-step instructions for migrating the VPS from the current single-tool
OAS deployment (`~/oas/` with `oas` realm) to the multi-tool Hangar deployment
(`~/hangar/` with `hangar` realm).

## Current state

```
~/oas/
  docker-compose.prod.yml   # oas-mcp + keycloak + postgres
  .env                      # OIDC_ISSUER_URL=.../realms/oas
  oas_data/                 # artifacts

~/caddy/
  Caddyfile                 # mcp.lakesideai.dev -> oas-mcp:8000 (no path prefix)
```

## Target state

```
~/hangar/
  docker-compose.prod.yml   # oas-mcp + (ocp-mcp) + keycloak + postgres
  .env                      # OIDC_ISSUER_URL=.../realms/hangar
  hangar_data/oas/          # OAS artifacts
  hangar_data/ocp/          # OCP artifacts (when ready)

~/caddy/
  Caddyfile                 # mcp.lakesideai.dev/oas/* -> oas-mcp:8000
                            # mcp.lakesideai.dev/ocp/* -> ocp-mcp:8000
```

## Pre-flight

Before starting, note the current state:

```bash
# Check what's running
cd ~/oas && docker compose -f docker-compose.prod.yml ps

# Back up the Keycloak database (in case you need to roll back)
cd ~/oas && docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U keycloak keycloak > ~/keycloak_backup_$(date +%Y%m%d).sql

# Back up artifacts
cp -r ~/oas/oas_data ~/oas_data_backup_$(date +%Y%m%d)

# Note current .env values
cat ~/oas/.env
```

## Phase 1: Set up the new hangar directory

```bash
# Clone the-hangar repo on the VPS
mkdir -p ~/hangar
git clone https://github.com/muroc-aero/the-hangar.git ~/hangar/repo

# Copy deploy files to ~/hangar/ (compose references ./repo as build context)
cp ~/hangar/repo/deploy/docker-compose.prod.yml ~/hangar/
cp ~/hangar/repo/deploy/.env.example ~/hangar/.env
```

## Phase 2: Create the .env file

```bash
cd ~/hangar
cp .env.example .env
```

Fill in `.env` using values from `~/oas/.env` where applicable:

```bash
# These carry over from the old setup:
KC_DB_PASSWORD=<same as before>
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=<same as before>
KC_HOSTNAME=auth.lakesideai.dev

# NEW: shared issuer points to hangar realm (not oas)
OIDC_ISSUER_URL=https://auth.lakesideai.dev/realms/hangar

# OAS: client secret will be NEW (from the new realm's client)
OAS_OIDC_CLIENT_ID=oas-mcp
OAS_OIDC_CLIENT_SECRET=             # fill after Keycloak setup
OAS_RESOURCE_SERVER_URL=https://mcp.lakesideai.dev/oas
```

## Phase 3: Migrate Keycloak to hangar realm

The old `oas` realm stays intact until the new one is verified. Both
realms can coexist in the same Keycloak instance.

### 3a. Start Keycloak from the new stack

The new compose file reuses the same Postgres volume, so Keycloak will
see the existing `oas` realm plus any users.

```bash
cd ~/hangar

# Copy OAS artifact data to the new location
mkdir -p ~/hangar/hangar_data
cp -r ~/oas/oas_data ~/hangar/hangar_data/oas

# Stop the OLD stack's oas-mcp (but keep keycloak + postgres running)
cd ~/oas && docker compose -f docker-compose.prod.yml stop oas-mcp

# Start the NEW stack (keycloak will reuse the postgres volume)
cd ~/hangar && docker compose -f docker-compose.prod.yml up -d postgres keycloak
```

Wait for Keycloak to be healthy:

```bash
docker compose -f docker-compose.prod.yml logs keycloak -f
```

### 3b. Create the hangar realm

Follow [keycloak-setup.md](keycloak-setup.md) steps 3 through 5:

1. Temporarily enable the admin console (step 3)
2. Create the `hangar` realm (step 4a)
3. Create the `oas-mcp` client in the new realm (step 4b)
4. Configure redirect URIs (step 4c)
5. Create the `mcp:tools` scope (step 4d)
6. Remove DCR policies (step 4e)
7. Create audience mapper (step 4f)
8. Add username mapper (step 4g)
9. Optionally create the viewer client (step 4h) and admin role (step 4i)
10. Configure Google social login (step 5)

### 3c. Migrate existing users

If you have existing users in the `oas` realm that need to be in `hangar`:

**Option A: Manual recreation (few users)**

1. Note usernames/emails from the `oas` realm
2. Create the same users in the `hangar` realm
3. Set passwords (or let them reset via email/Google)

**Option B: Keycloak export/import (many users)**

```bash
# Export from oas realm (admin console -> Realm settings -> Action -> Partial export)
# Check "Include users" -> Export

# Import into hangar realm (Realm settings -> Action -> Partial import)
# Upload the exported JSON
```

### 3d. Copy the new client secret to .env

After creating the `oas-mcp` client in the `hangar` realm, copy its
client secret:

```bash
# In the Keycloak admin: Clients -> oas-mcp -> Credentials -> Client secret
# Paste into ~/hangar/.env as OAS_OIDC_CLIENT_SECRET
```

## Phase 4: Update Caddy routing

The key change: `mcp.lakesideai.dev` now uses path-prefix routing.

Edit `~/caddy/Caddyfile`:

```
auth.lakesideai.dev {
    @admin path /admin/* /realms/master/*
    handle @admin {
        respond "Forbidden" 403
    }
    reverse_proxy keycloak:8080
}

mcp.lakesideai.dev {
    header {
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        -Server
    }

    handle_path /oas/* {
        reverse_proxy oas-mcp:8000
    }

    # Add more tools here:
    # handle_path /ocp/* {
    #     reverse_proxy ocp-mcp:8000
    # }

    handle {
        respond "Not Found" 404
    }
}
```

**Important:** `handle_path` strips the prefix. Requests to
`mcp.lakesideai.dev/oas/mcp` arrive at the container as `/mcp`.

Reload Caddy:

```bash
cd ~/caddy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

## Phase 5: Start oas-mcp on the new stack

```bash
cd ~/hangar
docker compose -f docker-compose.prod.yml up -d oas-mcp
```

Check logs:

```bash
docker compose -f docker-compose.prod.yml logs oas-mcp --tail 20
```

Look for:
```
OAS MCP -- HTTP transport  |  auth: OIDC (https://auth.lakesideai.dev/realms/hangar)
```

## Phase 6: Verify

### 6a. OIDC discovery

```bash
curl -s https://auth.lakesideai.dev/realms/hangar/.well-known/openid-configuration \
  | jq '{issuer, registration_endpoint}'
```

### 6b. Protected resource metadata (path-prefix routing works)

```bash
curl -s https://mcp.lakesideai.dev/oas/.well-known/oauth-protected-resource | jq .
```

The `resource` field should be `https://mcp.lakesideai.dev/oas`.

### 6c. Unauthenticated request returns 401

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST https://mcp.lakesideai.dev/oas/mcp
# Should print: 401
```

### 6d. Old URL returns 404

```bash
curl -s -o /dev/null -w '%{http_code}' -X POST https://mcp.lakesideai.dev/mcp
# Should print: 404
```

### 6e. Claude Code connection

```bash
# Remove old server config
claude mcp remove oas-mcp

# Add with new URL
claude mcp add --transport http oas-mcp https://mcp.lakesideai.dev/oas/mcp
```

Start a Claude Code session and test a tool call. Your browser will open
for Keycloak login (in the new `hangar` realm). If Google social login
was configured, you'll see the "Sign in with Google" button.

### 6f. Google social login

Open an incognito window and navigate to:
```
https://auth.lakesideai.dev/realms/hangar/account/
```

Verify the "Sign in with Google" button appears and works.

## Phase 7: Clean up

Once everything is verified:

```bash
# Stop the old stack entirely
cd ~/oas && docker compose -f docker-compose.prod.yml down

# Optionally delete the oas realm from Keycloak
# (via admin console -> oas realm -> Realm settings -> Action -> Delete)

# Keep the backups for a week, then remove:
# rm ~/keycloak_backup_*.sql
# rm -rf ~/oas_data_backup_*
```

## Rollback

If something goes wrong, roll back to the old setup:

```bash
# Stop the new stack
cd ~/hangar && docker compose -f docker-compose.prod.yml down

# Revert the Caddyfile to the old version (no path prefix)
# Edit ~/caddy/Caddyfile: change handle_path /oas/* back to:
#   reverse_proxy oas-mcp:8000
cd ~/caddy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile

# Restart the old stack
cd ~/oas && docker compose -f docker-compose.prod.yml up -d
```

## Next steps after migration

- [ ] Add OCP (OpenConcept) tool server when `packages/ocp` is ready
- [ ] Set up CI/CD to build and push Docker images on merge to main
- [ ] Add monitoring/alerting for tool server health
- [ ] Consider a shared landing page at `mcp.lakesideai.dev/` listing available tools
