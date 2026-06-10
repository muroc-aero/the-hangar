# Multi-tenant identity seam

Status: implemented 2026-06-10 (PR #53). Retained as the rationale record
for the per-user keying of `SessionManager` and the active provenance
session; the design below matches what landed. Two-user isolation tests
live in `packages/sdk/tests/test_multiuser.py`.

## Decision

Multi-user hosting over the HTTP transport is supported. That is the
deployment model for the hosted servers, and the artifact store, viewer
routes, and (as of this note) all three servers' artifact tools are already
scoped by the authenticated user. The remaining unscoped state is in-process:
the active provenance session id and the `SessionManager` registry. Both must
be keyed by `(user, session_id)`.

## Identity source

`hangar.sdk.auth.get_current_user()` is the single identity seam and already
behaves correctly per transport:

- HTTP + OIDC: a request-scoped ContextVar set by
  `OIDCTokenVerifier.verify_token()` on every validated JWT, reset at the
  start of each request.
- stdio: falls back to `HANGAR_USER`, then the OS login name. One user per
  process by construction.

All scoping below derives the user from this function. Nothing else should
read the ContextVar directly.

## What was broken (fixed in PR #53)

1. **Active provenance session** (`sdk/provenance/middleware.py`).
   `_server_session_id` is a module-level global with a ContextVar override
   reserved for test isolation. On a shared HTTP server, user A calling
   `start_session` repoints the global, so user B's subsequent tool calls are
   recorded into A's session until B calls `start_session` themselves.

2. **Tool-container sessions** (`sdk/session/manager.py`).
   `SessionManager._sessions` is keyed by the bare session name, and every
   tool defaults to `session_id="default"`. Two users on one server share
   surfaces, engines, requirements, pins, and cached problems; either user's
   `reset()` clears the other's state.

## Target design

### SessionManager: key by (user, session_id)

Change the internal dict key from `session_id` to
`(get_current_user(), session_id)`, resolved inside `SessionManager.get()`.
Tool signatures do not change; callers keep passing the short session name.
`reset()` clears only the calling user's sessions. The `"default"` session
becomes per-user automatically.

### Provenance: per-user active-session map

Replace the single `_server_session_id` global with a per-user map plus the
existing ContextVar override:

```python
_active_sessions: dict[str, str] = {}          # user -> session_id
_process_default: str = "default"              # seeded by main() auto-session

def _get_session_id() -> str:
    ctx = _prov_session_id.get()               # tests only
    if ctx:
        return ctx
    return _active_sessions.get(get_current_user(), _process_default)

def set_server_session_id(session_id: str) -> None:
    _active_sessions[get_current_user()] = session_id
```

The map is process-level rather than request-scoped on purpose: a user's
`start_session` must stick across subsequent HTTP requests on other
connections. The per-server `auto-xxxx` session created in `main()` becomes
`_process_default`, the landing spot for tool calls from users who never
called `start_session`; on stdio (single user) this reproduces today's
behavior exactly.

### Demotions, not removals

The module-level fallbacks stay as the stdio path. No flag distinguishes the
transports; per-user keying simply degrades to a single key when only one
identity exists.

## Consequences and follow-ups

- Cross-tool session join (`start_session(session_id=...)` on a second
  server) is unaffected: the joined id is recorded under the joining user.
- Both registries grow per user without bound. Acceptable at current scale;
  add an LRU cap on `SessionManager` and `_active_sessions` if hosted usage
  grows.
- `_next_seq` in `sdk/provenance/db.py` already notes a multi-process race;
  per-user keying does not change it.
- Tests: add a two-user interleaving test (set the identity ContextVar per
  call) asserting that sessions, engines, and provenance session ids do not
  cross between users.

## Out of scope

- Artifact store: already keyed by user/project/session on disk.
- Auth boundary: JWT validation and scope checks live in
  `sdk/auth/oidc.py` and are tested in `packages/sdk/tests/test_auth.py`.
- Viewer: the HTTP viewer routes scope by user; the stdio daemon viewer
  refuses non-loopback binds unless explicitly opted in.
