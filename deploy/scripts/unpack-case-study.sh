#!/usr/bin/env bash
# Unpack a case study tarball into deploy/landing/studies/.
# Run on the VPS after git pull (so the index.html template is in place).
#
# Usage:
#   ./deploy/scripts/unpack-case-study.sh /path/to/reg28m-opt-refined.tar.gz
#
# The tarball is extracted alongside the git-tracked index.html.
# Caddy picks up the new files immediately -- no restart needed.

set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <tarball>" >&2
    exit 1
fi

TARBALL="$1"

if [[ ! -f "${TARBALL}" ]]; then
    echo "ERROR: File not found: ${TARBALL}" >&2
    exit 1
fi

# Resolve repo root (script lives in deploy/scripts/)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TARGET="${REPO_ROOT}/deploy/landing/studies"

mkdir -p "${TARGET}"
tar -xzf "${TARBALL}" -C "${TARGET}"

# Identify what was extracted
STUDY_DIR=$(tar -tzf "${TARBALL}" | head -1 | cut -d/ -f1) || true
FILE_COUNT=$(find "${TARGET}/${STUDY_DIR}" -type f | wc -l)

echo ""
echo "Extracted ${FILE_COUNT} files into:"
echo "  ${TARGET}/${STUDY_DIR}/"
echo ""
echo "Verify at: https://mcp.lakesideai.dev/studies/${STUDY_DIR}/"
echo ""
