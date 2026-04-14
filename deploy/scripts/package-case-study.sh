#!/usr/bin/env bash
# Package reg28m-opt-refined case study artifacts into a tarball.
# Run on the dev machine where hangar_data/omd/ contains the analysis outputs.
#
# Usage:
#   ./deploy/scripts/package-case-study.sh
#
# Output:
#   deploy/landing/studies/reg28m-opt-refined.tar.gz
#
# Then scp the tarball to the VPS and run unpack-case-study.sh there.

set -euo pipefail

STUDY_ID="reg28m-opt-refined"
RUN_ID="run-20260414T145425-65b0174e"

# Resolve repo root (script lives in deploy/scripts/)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OMD_DATA="${REPO_ROOT}/hangar_data/omd"
OUT_DIR="${REPO_ROOT}/deploy/landing/studies"

# Verify source artifacts exist
if [[ ! -d "${OMD_DATA}/plots/${RUN_ID}" ]]; then
    echo "ERROR: Plot directory not found: ${OMD_DATA}/plots/${RUN_ID}" >&2
    exit 1
fi
if [[ ! -f "${OMD_DATA}/n2/${RUN_ID}.html" ]]; then
    echo "ERROR: N2 diagram not found: ${OMD_DATA}/n2/${RUN_ID}.html" >&2
    exit 1
fi
if [[ ! -f "${OMD_DATA}/provenance/plan-regional-wing-opt-dag.html" ]]; then
    echo "ERROR: Provenance DAG not found: ${OMD_DATA}/provenance/plan-regional-wing-opt-dag.html" >&2
    exit 1
fi

# Stage artifacts in a temp directory
STAGING="$(mktemp -d)"
trap 'rm -rf "${STAGING}"' EXIT

mkdir -p "${STAGING}/${STUDY_ID}/plots"

# Copy plot PNGs
cp "${OMD_DATA}/plots/${RUN_ID}/"*.png "${STAGING}/${STUDY_ID}/plots/"

# Copy self-contained HTML artifacts
cp "${OMD_DATA}/n2/${RUN_ID}.html" "${STAGING}/${STUDY_ID}/n2.html"
cp "${OMD_DATA}/provenance/plan-regional-wing-opt-dag.html" "${STAGING}/${STUDY_ID}/provenance-dag.html"

# Create tarball
mkdir -p "${OUT_DIR}"
tar -czf "${OUT_DIR}/${STUDY_ID}.tar.gz" -C "${STAGING}" "${STUDY_ID}"

# Summary
TARBALL="${OUT_DIR}/${STUDY_ID}.tar.gz"
SIZE=$(du -h "${TARBALL}" | cut -f1)
FILE_COUNT=$(tar -tzf "${TARBALL}" | wc -l)

echo ""
echo "Packaged ${FILE_COUNT} files (${SIZE}) into:"
echo "  ${TARBALL}"
echo ""
echo "Next steps:"
echo "  1. scp ${TARBALL} your-vps:~/"
echo "  2. On the VPS:"
echo "     cd ~/hangar/repo"
echo "     git pull"
echo "     ./deploy/scripts/unpack-case-study.sh ~/${STUDY_ID}.tar.gz"
echo ""
