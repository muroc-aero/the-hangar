#!/bin/bash
# Full dev environment setup.
#
# uv sync alone does not reinstall editable workspace packages when their
# console_scripts shims are missing (it checks dist-info, not the actual
# files).  This script forces a reinstall of every workspace member that
# declares [project.scripts] so the shims are always created.

set -e
cd "$(dirname "$0")/.."

echo "Syncing workspace..."
uv sync

echo "Reinstalling workspace packages (ensures console_scripts shims exist)..."
for pkg_dir in packages/*/; do
    if grep -q '^\[project\.scripts\]' "$pkg_dir/pyproject.toml" 2>/dev/null; then
        name=$(grep '^name' "$pkg_dir/pyproject.toml" | head -1 | sed 's/.*"\(.*\)".*/\1/')
        echo "  $name"
        uv sync --reinstall-package "$name"
    fi
done

echo "Done. All CLI entry points are installed."
