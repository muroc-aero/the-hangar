#!/usr/bin/env bash
# sync-skills.sh — Copy skills (directories) and commands (.md files) from
# each package and the root skills/ dir into .claude/skills/ and .claude/commands/.
#
# Skills  = subdirectories containing a SKILL.md  → .claude/skills/<name>/
# Commands = top-level .md files                   → .claude/commands/<name>.md
#
# Package items get a <pkg>- prefix unless the name already starts with it:
#   packages/oas/skills/foo.md       → .claude/commands/oas-foo.md
#   packages/oas/skills/oas-bar/     → .claude/skills/oas-bar/   (no double prefix)
#   skills/baz.md  (root)            → .claude/commands/baz.md
#
# Safe to re-run — cleans managed targets before copying.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_DIR="$REPO_ROOT/.claude"
SKILLS_DST="$CLAUDE_DIR/skills"
COMMANDS_DST="$CLAUDE_DIR/commands"

# Marker file so we only delete what we previously synced
MARKER=".synced-by-sync-skills"

# --- Clean previously synced items ---
clean_synced() {
    local dir="$1"
    [[ -d "$dir" ]] || return 0
    # Remove files and dirs that contain our marker
    find "$dir" -maxdepth 1 -name "$MARKER" -exec dirname {} \; | while read -r d; do
        echo "  clean: $d"
        rm -rf "$d"
    done
    # Remove marked files (commands)
    find "$dir" -maxdepth 1 -name "*.md" | while read -r f; do
        if head -1 "$f" 2>/dev/null | grep -q "synced-by-sync-skills"; then
            echo "  clean: $f"
            rm -f "$f"
        fi
    done
}

echo "Cleaning previously synced items..."
clean_synced "$SKILLS_DST"
clean_synced "$COMMANDS_DST"

mkdir -p "$SKILLS_DST" "$COMMANDS_DST"

synced_commands=0
synced_skills=0

# --- prefixed_name <pkg> <name> ---
# Adds <pkg>- prefix only if <name> doesn't already start with it.
# When pkg is empty, returns name unchanged.
prefixed_name() {
    local pkg="$1" name="$2"
    if [[ -z "$pkg" ]] || [[ "$name" == "${pkg}-"* ]]; then
        echo "$name"
    else
        echo "${pkg}-${name}"
    fi
}

# --- sync_source <source_dir> <pkg> ---
# pkg is "" for root skills/, package name for packages
sync_source() {
    local src_dir="$1"
    local pkg="$2"

    [[ -d "$src_dir" ]] || return 0

    # Top-level .md files → commands
    for f in "$src_dir"/*.md; do
        [[ -f "$f" ]] || continue
        local base dst_name
        base="$(basename "$f")"
        dst_name="$(prefixed_name "$pkg" "$base")"
        local dst="$COMMANDS_DST/$dst_name"
        # Prepend marker comment so we can clean it later
        printf '%s\n' "<!-- synced-by-sync-skills from ${f#"$REPO_ROOT"/} -->" > "$dst"
        cat "$f" >> "$dst"
        echo "  command: $dst_name"
        synced_commands=$((synced_commands + 1))
    done

    # Subdirectories → skills
    for d in "$src_dir"/*/; do
        [[ -d "$d" ]] || continue
        local base dst_name
        base="$(basename "$d")"
        dst_name="$(prefixed_name "$pkg" "$base")"
        local dst="$SKILLS_DST/$dst_name"
        cp -r "$d" "$dst"
        # Drop a marker so we can clean on next run
        touch "$dst/$MARKER"
        echo "  skill:   $dst_name/"
        synced_skills=$((synced_skills + 1))
    done
}

# --- Sync from each package ---
echo "Syncing from packages..."
for pkg_dir in "$REPO_ROOT"/packages/*/; do
    [[ -d "$pkg_dir" ]] || continue
    pkg_name="$(basename "$pkg_dir")"
    sync_source "$pkg_dir/skills" "$pkg_name"
done

# --- Sync from root skills/ ---
echo "Syncing from root skills/..."
sync_source "$REPO_ROOT/skills" ""

echo ""
echo "Done: $synced_commands command(s), $synced_skills skill(s) synced."
