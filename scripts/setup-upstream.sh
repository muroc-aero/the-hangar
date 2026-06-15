#!/bin/bash
# Clone upstream engineering tool repos and check out the pinned refs.
#
# The clones are .gitignore'd -- not part of the hangar repo -- but three of
# them (OpenAeroStruct, openconcept, pyCycle) are required by uv sync: the
# per-package [tool.uv.sources] entries point at upstream/ paths as editable
# installs. The pins live in scripts/upstream-pins.env (one place).
#
# Flags:
#   --required   Only sync the three repos required by uv sync (skips the
#                reference-only OpenMDAO and AeroSandbox clones). Used by
#                dev-setup.sh and CI.
#
# Behavior per repo:
#   - missing            -> clone, check out the pinned ref
#   - present, at pin    -> left alone
#   - present, not at pin -> fetch + detached checkout of the pin
#   - present, dirty     -> warned and skipped (never discards local edits);
#                           the managed pyCycle patch is reverse-applied
#                           first so it does not count as dirt

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UPSTREAM_DIR="$SCRIPT_DIR/../upstream"
mkdir -p "$UPSTREAM_DIR"

# shellcheck source=upstream-pins.env
source "$SCRIPT_DIR/upstream-pins.env"

REQUIRED_ONLY=false
for arg in "$@"; do
    case "$arg" in
        --required) REQUIRED_ONLY=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 2 ;;
    esac
done

PYCYCLE_PATCH="$SCRIPT_DIR/pycycle-numpy2.patch"
EVTOLPY_PATCH="$SCRIPT_DIR/evtolpy-packaging.patch"

# sync_repo <dir-name> <clone-url> <ref>
sync_repo() {
    local name="$1" url="$2" ref="$3"
    local dir="$UPSTREAM_DIR/$name"

    echo "Syncing $name @ $ref..."
    if [ ! -d "$dir/.git" ]; then
        git clone "$url" "$dir"
    fi

    if [ "$(git -C "$dir" rev-parse HEAD)" = "$ref" ]; then
        echo "  Already at pin."
        return 0
    fi

    if [ -n "$(git -C "$dir" status --porcelain --untracked-files=no)" ]; then
        echo "  WARNING: $name has local modifications; skipping checkout." >&2
        echo "  Stash or revert them, then re-run this script." >&2
        return 0
    fi

    # The pin may not be reachable from the default branch's history that an
    # old clone fetched; fetch the ref explicitly as a fallback.
    git -C "$dir" fetch --quiet origin || true
    if ! git -C "$dir" cat-file -e "$ref^{commit}" 2>/dev/null; then
        git -C "$dir" fetch --quiet origin "$ref"
    fi
    git -C "$dir" checkout --quiet --detach "$ref"
    echo "  Checked out $ref."
}

# pyCycle carries a managed numpy 2.x compatibility patch (tracks
# OpenMDAO/pyCycle#116; remove once merged upstream). Reverse-apply it
# before syncing so a patched-but-otherwise-clean tree can move pins,
# and reapply it after.
pycycle_unpatch() {
    local dir="$UPSTREAM_DIR/pyCycle"
    [ -d "$dir/.git" ] && [ -f "$PYCYCLE_PATCH" ] || return 0
    if git -C "$dir" apply -R --check "$PYCYCLE_PATCH" 2>/dev/null; then
        git -C "$dir" apply -R "$PYCYCLE_PATCH"
        echo "  Reverse-applied numpy2 patch ahead of sync."
    fi
}

pycycle_patch() {
    local dir="$UPSTREAM_DIR/pyCycle"
    [ -d "$dir/.git" ] && [ -f "$PYCYCLE_PATCH" ] || return 0
    if git -C "$dir" apply --check "$PYCYCLE_PATCH" 2>/dev/null; then
        git -C "$dir" apply "$PYCYCLE_PATCH"
        echo "  Applied numpy 2.x compat patch."
    else
        echo "  numpy2 patch already applied or upstream fixed -- skipping."
    fi
}

# evtolpy ships no packaging metadata; evtolpy-packaging.patch adds a
# pyproject.toml so it installs as an editable package (uv sources point at
# upstream/evtolpy). The added file is untracked, so sync_repo's dirty check
# (--untracked-files=no) ignores it; reverse-apply removes it before a sync so
# pin bumps are not blocked, and reapply restores it afterward.
evtolpy_unpatch() {
    local dir="$UPSTREAM_DIR/evtolpy"
    [ -d "$dir/.git" ] && [ -f "$EVTOLPY_PATCH" ] || return 0
    if git -C "$dir" apply -R --check "$EVTOLPY_PATCH" 2>/dev/null; then
        git -C "$dir" apply -R "$EVTOLPY_PATCH"
        echo "  Reverse-applied packaging patch ahead of sync."
    fi
}

evtolpy_patch() {
    local dir="$UPSTREAM_DIR/evtolpy"
    [ -d "$dir/.git" ] && [ -f "$EVTOLPY_PATCH" ] || return 0
    if git -C "$dir" apply --check "$EVTOLPY_PATCH" 2>/dev/null; then
        git -C "$dir" apply "$EVTOLPY_PATCH"
        echo "  Applied packaging patch (adds pyproject.toml)."
    else
        echo "  packaging patch already applied or upstream packaged -- skipping."
    fi
}

# Required by uv sync ([tool.uv.sources] editable installs)
sync_repo OpenAeroStruct https://github.com/mdolab/OpenAeroStruct "$OAS_REF"
sync_repo openconcept    https://github.com/mdolab/openconcept    "$OCP_REF"
pycycle_unpatch
sync_repo pyCycle        https://github.com/OpenMDAO/pyCycle      "$PYC_REF"
pycycle_patch
evtolpy_unpatch
sync_repo evtolpy        https://github.com/starbelt/evtolpy      "$EVTOL_REF"
evtolpy_patch

# Reference-only clones for reading upstream source
if [ "$REQUIRED_ONLY" = false ]; then
    sync_repo OpenMDAO    https://github.com/OpenMDAO/OpenMDAO        "$OM_REF"
    sync_repo AeroSandbox https://github.com/peterdsharpe/AeroSandbox "$ASB_REF"
fi

echo "Done. Upstream repos are in upstream/ (git-ignored), pinned by scripts/upstream-pins.env."
