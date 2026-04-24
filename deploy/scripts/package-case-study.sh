#!/usr/bin/env bash
# Package a case study's omd artifacts into a tarball for deployment.
# Run on the dev machine where hangar_data/omd/ contains the analysis outputs.
#
# Usage:
#   ./deploy/scripts/package-case-study.sh [STUDY_ID] [RUN_ID] [--plan-id PLAN_ID] [--version N]
#
# Defaults:
#   STUDY_ID  reg28m-opt-refined
#   RUN_ID    run-20260414T145425-65b0174e
#   PLAN_ID   $STUDY_ID  (pass --plan-id when the omd plan id differs from the study dir name)
#   VERSION   1
#
# Examples:
#   # reg28m (all defaults)
#   ./deploy/scripts/package-case-study.sh
#
#   # brelje (study dir name differs from plan id, plan is at v2)
#   ./deploy/scripts/package-case-study.sh brelje-2018a run-20260423T190235-641af06b \
#       --plan-id brelje-fuel-mdo-lane-c --version 2
#
# Output:
#   deploy/landing/studies/<STUDY_ID>.tar.gz
#
# The tarball contains plots/, n2.html, provenance-dag.html, problem-dag.html, plan-detail.html
# (but NOT index.html -- that file is git-tracked and lives in the study directory already).
# Scp the tarball to the VPS and run unpack-case-study.sh there.

set -euo pipefail

# Parse args: two optional positional (STUDY_ID, RUN_ID) + --plan-id / --version flags.
POSITIONAL=()
PLAN_ID=""
VERSION=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --plan-id) PLAN_ID="$2"; shift 2 ;;
        --version) VERSION="$2"; shift 2 ;;
        -h|--help)
            grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//' | head -30
            exit 0
            ;;
        *) POSITIONAL+=("$1"); shift ;;
    esac
done

STUDY_ID="${POSITIONAL[0]:-reg28m-opt-refined}"
RUN_ID="${POSITIONAL[1]:-run-20260414T145425-65b0174e}"
PLAN_ID="${PLAN_ID:-$STUDY_ID}"
VERSION="${VERSION:-1}"

echo "Packaging case study:"
echo "  STUDY_ID  = ${STUDY_ID}"
echo "  RUN_ID    = ${RUN_ID}"
echo "  PLAN_ID   = ${PLAN_ID}"
echo "  VERSION   = ${VERSION}"
echo ""

# Resolve repo root (script lives in deploy/scripts/)
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OMD_DATA="${REPO_ROOT}/hangar_data/omd"
OUT_DIR="${REPO_ROOT}/deploy/landing/studies"
SCRIPTS="${REPO_ROOT}/deploy/scripts"

# Verify source artifacts exist
if [[ ! -d "${OMD_DATA}/plots/${RUN_ID}" ]]; then
    echo "ERROR: Plot directory not found: ${OMD_DATA}/plots/${RUN_ID}" >&2
    echo "       Run: omd-cli plot ${RUN_ID} --type all" >&2
    exit 1
fi
if [[ ! -f "${OMD_DATA}/n2/${RUN_ID}.html" ]]; then
    echo "ERROR: N2 diagram not found: ${OMD_DATA}/n2/${RUN_ID}.html" >&2
    echo "       N2 is generated at omd-cli run time; re-run the plan." >&2
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

# Generate provenance DAG for this specific plan
echo "Generating provenance DAG for ${PLAN_ID}..."
uv run omd-cli provenance "${PLAN_ID}" --format html \
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
status, ctype, content = _omd_plan_detail_handler({'plan_id': ['${PLAN_ID}'], 'version': ['${VERSION}']})
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
echo "  1. Local preview:"
echo "     tar -xzf ${TARBALL} -C ${OUT_DIR}/"
echo "  2. Deploy:"
echo "     scp ${TARBALL} your-vps:~/"
echo "     # on VPS:"
echo "     cd ~/hangar/repo && git pull"
echo "     ./deploy/scripts/unpack-case-study.sh ~/${STUDY_ID}.tar.gz"
echo ""
