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
SCRIPTS="${REPO_ROOT}/deploy/scripts"

# Verify source artifacts exist
if [[ ! -d "${OMD_DATA}/plots/${RUN_ID}" ]]; then
    echo "ERROR: Plot directory not found: ${OMD_DATA}/plots/${RUN_ID}" >&2
    exit 1
fi
if [[ ! -f "${OMD_DATA}/n2/${RUN_ID}.html" ]]; then
    echo "ERROR: N2 diagram not found: ${OMD_DATA}/n2/${RUN_ID}.html" >&2
    exit 1
fi

# Stage artifacts in a temp directory
STAGING="$(mktemp -d)"
trap 'rm -rf "${STAGING}"' EXIT

mkdir -p "${STAGING}/${STUDY_ID}/plots"

# Copy plot PNGs
echo "Copying plot PNGs..."
cp "${OMD_DATA}/plots/${RUN_ID}/"*.png "${STAGING}/${STUDY_ID}/plots/"

# Copy N2 diagram
echo "Copying N2 diagram..."
cp "${OMD_DATA}/n2/${RUN_ID}.html" "${STAGING}/${STUDY_ID}/n2.html"

# Generate provenance DAG for this specific plan (not the broader study)
echo "Generating provenance DAG for ${STUDY_ID}..."
uv run omd-cli provenance "${STUDY_ID}" --format html \
    -o "${STAGING}/${STUDY_ID}/provenance-dag-raw.html"

# Patch the DAG HTML for static serving (rewrite API endpoints to relative paths)
echo "Patching DAG for static serving..."
python3 "${SCRIPTS}/patch-dag-static.py" \
    "${STAGING}/${STUDY_ID}/provenance-dag-raw.html" \
    "${STAGING}/${STUDY_ID}/provenance-dag.html"
rm "${STAGING}/${STUDY_ID}/provenance-dag-raw.html"

# Pre-generate the problem DAG (discipline-level analysis flow)
echo "Generating problem DAG..."
python3 -c "
from hangar.omd.cli import _omd_problem_dag_handler
status, ctype, content = _omd_problem_dag_handler({'run_id': ['${RUN_ID}']})
if status != 200:
    raise RuntimeError(f'Problem DAG generation failed: status={status}')
with open('${STAGING}/${STUDY_ID}/problem-dag.html', 'wb') as f:
    f.write(content)
print(f'  problem-dag.html ({len(content)} bytes)')
"

# Pre-generate the plan detail page
echo "Generating plan detail..."
python3 -c "
from hangar.omd.cli import _omd_plan_detail_handler
status, ctype, content = _omd_plan_detail_handler({'plan_id': ['${STUDY_ID}'], 'version': ['1']})
if status != 200:
    raise RuntimeError(f'Plan detail generation failed: status={status}')
with open('${STAGING}/${STUDY_ID}/plan-detail.html', 'wb') as f:
    f.write(content)
print(f'  plan-detail.html ({len(content)} bytes)')
"

# Create tarball
mkdir -p "${OUT_DIR}"
tar -czf "${OUT_DIR}/${STUDY_ID}.tar.gz" -C "${STAGING}" "${STUDY_ID}"

# Summary
TARBALL="${OUT_DIR}/${STUDY_ID}.tar.gz"
SIZE=$(du -h "${TARBALL}" | cut -f1)
FILE_COUNT=$(tar -tzf "${TARBALL}" | wc -l) || true

echo ""
echo "Packaged ${FILE_COUNT} files (${SIZE}) into:"
echo "  ${TARBALL}"
echo ""
echo "Contents:"
tar -tzf "${TARBALL}" | head -25
echo ""
echo "Next steps:"
echo "  1. scp ${TARBALL} your-vps:~/"
echo "  2. On the VPS:"
echo "     cd ~/hangar/repo"
echo "     git pull"
echo "     ./deploy/scripts/unpack-case-study.sh ~/${STUDY_ID}.tar.gz"
echo ""
