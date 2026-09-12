#!/bin/bash
# Launch the Aviary MCP server from the isolated venv (.venv-avy).
#
# .mcp.json points the "Aviary" server here instead of at
# .venv-avy/bin/python directly, so a fresh clone (where the venv does not
# exist yet) fails with the setup instruction instead of a bare ENOENT.
# Aviary cannot run from the main venv (numpy 2 vs the openconcept pin);
# see packages/avy/CLAUDE.md.

cd "$(dirname "$0")/.." || exit 1

if [ ! -x .venv-avy/bin/python ]; then
    echo "hangar-avy: .venv-avy not found at $PWD/.venv-avy." >&2
    echo "Create it with:  bash scripts/setup-avy-venv.sh" >&2
    exit 1
fi

exec .venv-avy/bin/python -m hangar.avy.server "$@"
