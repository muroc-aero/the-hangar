# Hangar MCP Servers -- User Guide

This guide explains how to connect to the Hangar engineering analysis
tools from Claude Code, claude.ai, and OpenAI Codex.

## Available tools

| Tool | URL | Description |
|------|-----|-------------|
| OAS (OpenAeroStruct) | `https://mcp.lakesideai.dev/oas/mcp` | Aerostructural analysis and optimization |

More tools will be added over time. Each tool gets its own URL path.

## Creating an account

### Option A: Google sign-in (recommended)

No setup needed. The first time you connect from any client, you'll be
redirected to a login page. Click **Sign in with Google** and use your
Google account. Your account is created automatically.

### Option B: Username/password

Ask an admin to create your account in Keycloak. They'll give you a
username and password. Use those when prompted to log in.

## Connecting from Claude Code (CLI)

### Add the MCP server

```bash
claude mcp add --transport http oas https://mcp.lakesideai.dev/oas/mcp
```

This is a one-time setup. The server config is saved in your Claude Code
settings.

### Use it

Start a Claude Code session. The first time you use an OAS tool, your
browser will open for login. Sign in with Google or your credentials.
After authenticating, all OAS tools are available automatically.

Example prompts:
- "Create a rectangular wing with 10m span and analyze it at Mach 0.3"
- "Run a drag polar sweep from -2 to 10 degrees angle of attack"
- "Optimize the wing twist for minimum drag at CL=0.5"

### Managing MCP servers

```bash
# List configured servers
claude mcp list

# Remove a server
claude mcp remove oas

# Re-add with a different name
claude mcp add --transport http my-oas https://mcp.lakesideai.dev/oas/mcp
```

## Connecting from claude.ai (web)

1. Go to [claude.ai](https://claude.ai)
2. Open **Settings** (gear icon) -> **Integrations** -> **Add MCP Server**
3. Enter URL: `https://mcp.lakesideai.dev/oas/mcp`
4. You'll be redirected to sign in (Google or username/password)
5. The OAS tools appear in your conversation

## Connecting from OpenAI Codex (CLI)

### Add the MCP server

```bash
codex mcp add oas --url https://mcp.lakesideai.dev/oas/mcp
```

### Authenticate

```bash
codex mcp login oas --scopes mcp:tools
```

Your browser will open for login. Sign in with Google or your credentials.

### Use it

Start a Codex session -- the OAS tools will be available.

### Alternative: config file

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.oas]
url = "https://mcp.lakesideai.dev/oas/mcp"
scopes = ["mcp:tools"]
```

Then authenticate: `codex mcp login oas`

## Connecting multiple tools

Each tool has its own URL. Add them separately:

```bash
# Claude Code
claude mcp add --transport http oas https://mcp.lakesideai.dev/oas/mcp
claude mcp add --transport http ocp https://mcp.lakesideai.dev/ocp/mcp

# Codex
codex mcp add oas --url https://mcp.lakesideai.dev/oas/mcp
codex mcp add ocp --url https://mcp.lakesideai.dev/ocp/mcp
```

You authenticate once per tool (same Google account / credentials work
for all tools since they share the same Keycloak realm).

## Viewing results

After running an analysis, you'll get a `run_id` in the response. View
results in the browser:

- **Dashboard**: `https://mcp.lakesideai.dev/oas/dashboard?run_id=<run_id>`
- **Provenance graph**: `https://mcp.lakesideai.dev/oas/viewer?session_id=<session_id>`

You'll be prompted to log in with the same credentials. You can only
see your own analysis results (admins can see all users' results).

## Troubleshooting

### "Browser didn't open for login"

If the browser doesn't open automatically:
1. Check the terminal output for a URL
2. Copy and paste it into your browser manually
3. After logging in, return to the terminal

### "Token rejected" or authentication errors

Your token may have expired. Try:
```bash
# Claude Code: remove and re-add the server
claude mcp remove oas
claude mcp add --transport http oas https://mcp.lakesideai.dev/oas/mcp

# Codex: re-login
codex mcp login oas --scopes mcp:tools
```

### "Connection refused" or timeout

The server may be restarting. Wait a minute and try again. If the
problem persists, contact an admin.

### Tools not appearing in claude.ai

1. Check that the MCP server is listed in Settings -> Integrations
2. Try removing and re-adding it
3. Refresh the page and start a new conversation
