#!/bin/bash
# Full dev environment setup.
#
# uv sync alone does not reinstall editable workspace packages when their
# console_scripts shims are missing (it checks dist-info, not the actual
# files).  This script forces a reinstall of every workspace member that
# declares [project.scripts] so the shims are always created.
#
# Open vs full-stack clones:
#   The committed root pyproject.toml lists only the open packages as
#   dependencies. Closed packages (e.g. hangar-range-safety) live in
#   private git submodules under packages/. When such a submodule is
#   present, this script switches to `uv sync --all-packages` so every
#   workspace member found by the packages/* glob is installed. An
#   open-only clone (no private submodule) syncs just the open packages
#   and stays clean.
#
# Flags:
#   --pypi   Force open-only mode even if private submodules happen to be
#            present (skips --all-packages). Useful for testing that an
#            open-only checkout resolves on its own.

set -e
cd "$(dirname "$0")/.."

PYPI_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --pypi) PYPI_ONLY=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# The workspace's [tool.uv.sources] entries point at editable installs in
# upstream/ (gitignored), so uv sync fails hard on a fresh clone until the
# upstream repos exist. Clone the required ones at their pinned refs first.
NEED_UPSTREAM=false
for d in upstream/OpenAeroStruct upstream/openconcept upstream/pyCycle; do
    if [ ! -f "$d/setup.py" ] && [ ! -f "$d/pyproject.toml" ]; then
        NEED_UPSTREAM=true
    fi
done
if [ "$NEED_UPSTREAM" = true ]; then
    echo "Required upstream clones missing; running scripts/setup-upstream.sh --required..."
    bash scripts/setup-upstream.sh --required
fi

# Initialize any private submodules that are wired up but not yet checked
# out, so their package directories are populated before uv sees them.
if [ "$PYPI_ONLY" = false ] && [ -f .gitmodules ]; then
    echo "Initializing submodules..."
    git submodule update --init --recursive || true
fi

# A closed package is "present" when its directory contains a pyproject.
# (A wired-but-uninitialized submodule is an empty dir, which we skip.)
PRIVATE_PRESENT=false
for closed in packages/range-safety; do
    if [ "$PYPI_ONLY" = false ] && [ -f "$closed/pyproject.toml" ]; then
        PRIVATE_PRESENT=true
    fi
done

SYNC_ARGS=()
if [ "$PRIVATE_PRESENT" = true ]; then
    SYNC_ARGS=(--all-packages)
    echo "Private packages detected: syncing all workspace members."
else
    echo "Open-only sync (no private submodules)."
fi

echo "Syncing workspace..."
uv sync "${SYNC_ARGS[@]}"

echo "Reinstalling workspace packages (ensures console_scripts shims exist)..."
for pkg_dir in packages/*/; do
    if grep -q '^\[project\.scripts\]' "$pkg_dir/pyproject.toml" 2>/dev/null; then
        name=$(grep '^name' "$pkg_dir/pyproject.toml" | head -1 | sed 's/.*"\(.*\)".*/\1/')
        echo "  $name"
        # Carry the same sync scope so non-root members are not dropped.
        uv sync "${SYNC_ARGS[@]}" --reinstall-package "$name"
    fi
done

echo "Done. All CLI entry points are installed."
