# Keycloak Setup for Hangar MCP Servers

Keycloak provides OAuth2/OIDC authentication with native Dynamic Client
Registration (DCR), which Claude Code, claude.ai, and Codex require.

This guide sets up a single `hangar` realm shared by all tool servers
(OAS, OCP, etc.), with Google social login for self-registration.

## 1. Environment variables

Add these to `~/hangar/.env` on the VPS:

```bash
# Keycloak admin (only used on first start)
KEYCLOAK_ADMIN=admin
KEYCLOAK_ADMIN_PASSWORD=<strong-random-password>

# Keycloak Postgres
KC_DB_PASSWORD=<strong-random-password>

# Public hostname (must match your Caddy/DNS config)
KC_HOSTNAME=auth.lakesideai.dev

# Shared OIDC issuer (all tools use same realm)
OIDC_ISSUER_URL=https://auth.lakesideai.dev/realms/hangar

# OAS MCP auth
OAS_OIDC_CLIENT_ID=oas-mcp
OAS_OIDC_CLIENT_SECRET=          # fill after step 4b below
OAS_RESOURCE_SERVER_URL=https://mcp.lakesideai.dev/oas

# OCP MCP auth (uncomment when ready)
# OCP_OIDC_CLIENT_ID=ocp-mcp
# OCP_OIDC_CLIENT_SECRET=
# OCP_RESOURCE_SERVER_URL=https://mcp.lakesideai.dev/ocp

# Viewer auth (OIDC session-based login for /viewer, /dashboard, etc.)
# OAS_VIEWER_OIDC_CLIENT_ID=oas-viewer
# OAS_VIEWER_OIDC_CLIENT_SECRET=  # fill after step 4h below
# OAS_VIEWER_SESSION_SECRET=      # generate: python -c "import secrets; print(secrets.token_hex(32))"
```

## 2. Start the stack

```bash
cd ~/hangar
docker compose -f docker-compose.prod.yml up -d
```

Wait for Keycloak to become healthy (~30-45s on first start):

```bash
docker compose -f docker-compose.prod.yml logs keycloak -f
```

Look for: `Keycloak 26.x.x on JVM ... started in XXs`

## 3. Temporarily enable admin console

The Caddyfile blocks `/admin/*` and `/realms/master/*` by default.
To access the admin console:

1. Comment out the `@admin` block in `~/caddy/Caddyfile`:
```
auth.lakesideai.dev {
    # @admin path /admin/* /realms/master/*
    # handle @admin {
    #     respond "Forbidden" 403
    # }
    reverse_proxy keycloak:8080
}
```

2. Reload Caddy:
```bash
cd ~/caddy && docker compose exec caddy caddy reload --config /etc/caddy/Caddyfile
```

3. Open `https://auth.lakesideai.dev/admin/` and log in with admin credentials.

**Remember to re-enable the block and reload Caddy when done.**

## 4. Configure the hangar realm

### 4a. Create realm

1. Click the realm dropdown (top-left, says "Keycloak") -> **Create realm**
2. Name: `hangar`
3. Click **Create**

### 4b. Create OAS MCP client

1. **Clients -> Create client**
2. Client ID: `oas-mcp`
3. Client authentication: **ON** (confidential)
4. Authentication flow: check **Standard flow** + **Service accounts roles**
5. Click **Next**, then **Save**
6. Go to **Credentials** tab -> copy the **Client secret** -> paste into `.env` as `OAS_OIDC_CLIENT_SECRET`

### 4c. Configure redirect URIs (on oas-mcp client)

In the client's **Settings** tab, add these **Valid redirect URIs**:

```
http://localhost:*
http://127.0.0.1:*
https://claude.ai/api/mcp/auth_callback
https://claude.com/api/mcp/auth_callback
```

Set **Valid post logout redirect URIs** to `+` (same as redirect URIs).
Set **Web origins** to `+`.

### 4d. Create mcp:tools scope

1. **Client scopes** (left sidebar) -> **Create client scope**
2. Name: `mcp:tools`
3. Type: **Default**
4. Protocol: **OpenID Connect**
5. **Include in token scope**: **ON** (critical -- without this the scope won't
   appear in the access token's `scope` claim)
6. Click **Save**

Assign it to the `oas-mcp` client:
1. Go to **Clients -> oas-mcp -> Client scopes** tab
2. Click **Add client scope** -> select `mcp:tools` -> Add as **Default**

### 4e. Remove restrictive DCR policies

Keycloak's default anonymous access policies block DCR requests from
Claude Code, claude.ai, and Codex. Two policies must be deleted:

1. **Clients** (left sidebar) -> **Client registration** tab (top of the page)
2. Under **Anonymous access policies**, delete both:
   - **Trusted Hosts** -- blocks DCR from non-whitelisted hosts
   - **Allowed Client Scopes** -- blocks the custom `mcp:tools` scope
3. Click the trash icon on each

> Removing these policies allows any client to register via DCR. This is
> safe because the MCP server validates every token independently -- DCR
> registration alone grants no access.

Verify DCR works:

```bash
curl -s https://auth.lakesideai.dev/realms/hangar/.well-known/openid-configuration \
  | jq .registration_endpoint
```

Should return: `https://auth.lakesideai.dev/realms/hangar/clients-registrations/openid-connect`

### 4f. Audience mapper

By default, Keycloak doesn't include the tool client ID in the token's
`aud` claim. Without this, JWT audience validation fails.

1. **Client scopes** (left sidebar) -> **mcp:tools** -> **Mappers** tab -> **Configure a new mapper**
2. Choose **Audience**
3. Name: `oas-mcp-audience`
4. Included Client Audience: `oas-mcp`
5. Add to access token: **ON**
6. Click **Save**

> When adding more tools: create additional audience mappers in the same
> `mcp:tools` scope for each tool client (e.g., `ocp-mcp-audience` pointing
> to `ocp-mcp`). Alternatively, create per-tool client scopes.

### 4g. Ensure username in access tokens

DCR-registered clients (Claude Code, claude.ai, Codex) may not include
`preferred_username` in access tokens by default. The MCP server works around
this by calling the OIDC userinfo endpoint, but adding the mapper avoids
the extra HTTP call.

1. **Client scopes** (left sidebar) -> **profile** -> **Mappers** tab
2. Find the **username** mapper (or create one):
   - Mapper type: **User Property**
   - Property: `username`
   - Token Claim Name: `preferred_username`
3. Ensure **Add to access token** is **ON**
4. Click **Save**

### 4h. Create viewer client (optional)

If you want the provenance viewer/dashboard with per-user artifact scoping:

1. **Clients -> Create client**
2. Client ID: `oas-viewer`
3. Client authentication: **ON** (confidential)
4. Authentication flow: check **Standard flow** only
5. Click **Next**, then **Save**
6. Go to **Credentials** tab -> copy the **Client secret** -> paste into `.env` as `OAS_VIEWER_OIDC_CLIENT_SECRET`

In the client's **Settings** tab:

- **Valid redirect URIs**: `https://mcp.lakesideai.dev/oas/viewer/callback`
- **Valid post logout redirect URIs**: `https://mcp.lakesideai.dev/oas/viewer`
- **Web origins**: `https://mcp.lakesideai.dev`

### 4i. Create admin role for the viewer

1. **Realm roles** (left sidebar) -> **Create role**
2. Name: `oas-admin`
3. Click **Save**
4. Assign to admin users:
   - **Users** -> select the user -> **Role mappings** tab -> **Assign role**
   - Change filter from **Filter by clients** to **Filter by realm roles**
   - Select `oas-admin` -> click **Assign**

## 5. Configure Google social login (self-registration)

This lets new users sign up with their Google account without needing
an admin to create their account manually.

### 5a. Google Cloud Console setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/) -> **APIs & Services -> Credentials**
2. Click **Create Credentials -> OAuth client ID**
3. Application type: **Web application**
4. Name: `Hangar Keycloak`
5. **Authorized redirect URIs**: `https://auth.lakesideai.dev/realms/hangar/broker/google/endpoint`
6. **Authorized JavaScript origins**: `https://auth.lakesideai.dev`
7. Click **Create** and note the Client ID and Client Secret

### 5b. Keycloak identity provider setup

1. In the `hangar` realm, go to **Identity providers** (left sidebar)
2. Click **Add provider -> Google**
3. Fill in:
   - **Client ID**: from Google Cloud Console
   - **Client Secret**: from Google Cloud Console
   - **Default Scopes**: `openid email profile`
4. Under **Advanced settings**:
   - **Trust email**: ON (Google emails are verified)
   - **First login flow**: `first broker login` (default)
5. Click **Save**

### 5c. Realm login settings

1. **Realm settings** (left sidebar) -> **Login** tab
2. **User registration**: ON (allows the Keycloak form as fallback)
3. **Login with email**: ON
4. **Duplicate emails**: OFF
5. **Verify email**: ON (recommended for non-Google registrations)

### 5d. Verify social login

1. Open an incognito browser window
2. Navigate to `https://auth.lakesideai.dev/realms/hangar/account/`
3. You should see a "Sign in with Google" button on the login page
4. Click it, sign in with a Google account
5. Verify the user appears in **Users** in the Keycloak admin console

New users automatically get `default-roles-hangar` (basic access, NOT admin).
Admin viewer access must be granted manually (step 4i).

## 6. Adding a new tool (e.g., OCP)

When adding a new MCP tool server to the hangar:

### 6a. Create the OIDC client

1. **Clients -> Create client** in the `hangar` realm
2. Client ID: `ocp-mcp` (or whatever matches the tool's `OIDC_CLIENT_ID`)
3. Client authentication: **ON**, Standard flow + Service accounts
4. Configure redirect URIs (same pattern as step 4c)
5. Copy client secret to `.env` as `OCP_OIDC_CLIENT_SECRET`

### 6b. Add audience mapper

1. **Client scopes -> mcp:tools -> Mappers -> Configure a new mapper**
2. Choose **Audience**
3. Name: `ocp-mcp-audience`
4. Included Client Audience: `ocp-mcp`
5. Add to access token: **ON**
6. Click **Save**

### 6c. Assign scope to client

1. **Clients -> ocp-mcp -> Client scopes** tab
2. **Add client scope** -> `mcp:tools` -> Add as **Default**

### 6d. Update deployment

1. Uncomment (or add) the service in `docker-compose.prod.yml`
2. Add `handle_path /ocp/*` route to the Caddyfile
3. Reload Caddy and restart the stack

## 7. Restart and verify

```bash
cd ~/hangar
docker compose -f docker-compose.prod.yml restart oas-mcp
```

Check the logs:

```bash
docker compose -f docker-compose.prod.yml logs oas-mcp --tail 20
```

You should see:
```
OAS MCP -- HTTP transport  |  auth: OIDC (https://auth.lakesideai.dev/realms/hangar)
```

Verify:

```bash
# OIDC discovery
curl -s https://auth.lakesideai.dev/realms/hangar/.well-known/openid-configuration \
  | jq '{issuer, registration_endpoint, authorization_endpoint, token_endpoint}'

# Protected resource metadata (served by MCP server)
curl -s https://mcp.lakesideai.dev/oas/.well-known/oauth-protected-resource | jq .

# Unauthenticated request -> 401
curl -s -o /dev/null -w '%{http_code}' -X POST https://mcp.lakesideai.dev/oas/mcp
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Token rejected: missing required scope 'mcp:tools'` | Scope not in token | Check **Include in token scope** is ON in the `mcp:tools` scope settings |
| `Policy 'Trusted Hosts' rejected request` | DCR blocked | Delete the Trusted Hosts policy (step 4e) |
| `Policy 'Allowed Client Scopes' rejected request` | DCR blocked | Delete the Allowed Client Scopes policy (step 4e) |
| JWT audience validation fails | Missing audience mapper | Add audience mapper to `mcp:tools` scope (step 4f) |
| `password authentication failed` on Keycloak start | Stale Postgres volume | `docker volume rm <project>_postgres_data` and restart |
| Viewer callback fails | Wrong redirect URI | Verify viewer client has `https://mcp.lakesideai.dev/oas/viewer/callback` |
| Artifacts stored under UUID | DCR token missing username | Add username mapper to profile scope (step 4g) |
| `OIDC_CLIENT_ID is not set` warning | Missing env var | Each tool needs its own `OIDC_CLIENT_ID` in the compose environment |
