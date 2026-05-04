#!/usr/bin/env bash
# Reproduces the grid Brelje 2018a actually published in Figs 5 & 6:
# 11x12 = 132 cells, design_range in [300, 800] nmi, spec_energy in
# [250, 800] Wh/kg.  Counted from the paper's pixelated panels (the
# upstream openconcept HybridTwin.py:354-355 commented sweep stops at
# range=700 but the paper figures clearly extend to 800).
#
# Sequentially: fig5 sweep -> fig5 retry -> fig6 sweep (warm-from fig5)
# -> fig6 retry -> contour plots -> paper-style pcolormesh plots ->
# side-by-side compare.  All output is tee'd to a timestamped log under
# results/.
#
# 2 workers (WSL memory headroom).  Estimated wall time:
#   default      :  ~5 h    (single-shot, 132 cells, ~150 s/cell on 2 workers)
#   --multistart :  ~9 h    (2 starts/cell for fig5, fig6 single-shot)
#
# Usage:
#   bash packages/omd/demos/brelje_2018a/run_paper_grid.sh
#   bash packages/omd/demos/brelje_2018a/run_paper_grid.sh --resume
#   bash packages/omd/demos/brelje_2018a/run_paper_grid.sh --multistart

set -uo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$DEMO_DIR/../../../.." && pwd)"
RESULTS_DIR="$DEMO_DIR/results"
TS="$(date +%Y%m%dT%H%M%S)"
LOG="$RESULTS_DIR/paper_grid_${TS}.log"

WORKERS=2
GRID="11x12"
RANGE_BOUNDS="300,800"
ENERGY_BOUNDS="250,800"
SWEEP_MODE="--fresh"
FIG5_STARTS=""
for arg in "$@"; do
    case "$arg" in
        --resume)     SWEEP_MODE="--resume" ;;
        --fresh)      SWEEP_MODE="--fresh" ;;
        --multistart) FIG5_STARTS="--starts low,high" ;;
        *)
            echo "Unknown arg: $arg"
            echo "Usage: $0 [--resume|--fresh] [--multistart]"
            exit 2
            ;;
    esac
done

cd "$REPO_ROOT"

run_step() {
    local label="$1"; shift
    local t0 ts_str
    t0=$(date +%s)
    ts_str=$(date -Iseconds)
    echo "" | tee -a "$LOG"
    echo "================================================================" | tee -a "$LOG"
    echo "[$ts_str] STEP: $label" | tee -a "$LOG"
    echo "  cmd: $*" | tee -a "$LOG"
    echo "================================================================" | tee -a "$LOG"
    "$@" 2>&1 | tee -a "$LOG"
    local rc=${PIPESTATUS[0]}
    local elapsed=$(( $(date +%s) - t0 ))
    echo "[$(date -Iseconds)] STEP DONE: $label (rc=$rc, elapsed=${elapsed}s)" | tee -a "$LOG"
    return $rc
}

echo "Brelje 2018a PAPER-GRID (11x12) run starting at $(date -Iseconds)" | tee -a "$LOG"
echo "  workers       : $WORKERS" | tee -a "$LOG"
echo "  grid          : $GRID" | tee -a "$LOG"
echo "  range bounds  : $RANGE_BOUNDS nmi" | tee -a "$LOG"
echo "  energy bounds : $ENERGY_BOUNDS Wh/kg" | tee -a "$LOG"
echo "  mode          : $SWEEP_MODE" | tee -a "$LOG"
echo "  fig5 starts   : ${FIG5_STARTS:-(default single-shot)}" | tee -a "$LOG"
echo "  log           : $LOG" | tee -a "$LOG"
echo "  pid           : $$" | tee -a "$LOG"

# 1. Fig 5 (fuel) sweep on paper-exact axes
run_step "fig5 sweep (11x12 paper grid)" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/sweep.py \
        --objective fuel --grid "$GRID" --workers "$WORKERS" $SWEEP_MODE \
        --range-bounds "$RANGE_BOUNDS" --energy-bounds "$ENERGY_BOUNDS" \
        $FIG5_STARTS
FIG5_RC=$?

# 2. Fig 5 retry pass (no-op if zero failures)
run_step "fig5 retry-failed" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/retry_failed.py --objective fuel
FIG5_RETRY_RC=$?

# 3. Fig 6 (cost) sweep on paper-exact axes, warm-from fig5
run_step "fig6 sweep (11x12 paper grid, warm-from fig5)" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/sweep.py \
        --objective cost --grid "$GRID" --workers "$WORKERS" $SWEEP_MODE \
        --range-bounds "$RANGE_BOUNDS" --energy-bounds "$ENERGY_BOUNDS" \
        --warm-from "$RESULTS_DIR/fig5_grid.csv"
FIG6_RC=$?

# 4. Fig 6 retry, warm-from fig5
run_step "fig6 retry-failed (warm-from fig5)" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/retry_failed.py \
        --objective cost --warm-from "$RESULTS_DIR/fig5_grid.csv"
FIG6_RETRY_RC=$?

# 5. Render reproduced figures in BOTH styles
run_step "plot fig5 (contour)" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/plotting.py --figure 5 --style contour
run_step "plot fig5 (paper style)" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/plotting.py --figure 5 --style paper
run_step "plot fig6 (contour)" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/plotting.py --figure 6 --style contour
run_step "plot fig6 (paper style)" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/plotting.py --figure 6 --style paper

# 6. Side-by-side comparison vs paper crops (uses paper-style render)
run_step "compare fig5" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/compare.py --figure 5
run_step "compare fig6" \
    uv run python packages/omd/demos/brelje_2018a/pipeline/compare.py --figure 6

echo "" | tee -a "$LOG"
echo "================================================================" | tee -a "$LOG"
echo "FINAL SUMMARY [$(date -Iseconds)]" | tee -a "$LOG"
echo "================================================================" | tee -a "$LOG"
for csv in "$RESULTS_DIR/fig5_grid.csv" "$RESULTS_DIR/fig6_grid.csv"; do
    if [[ -f "$csv" ]]; then
        n_total=$(($(wc -l < "$csv") - 1))
        n_ok=$(awk -F, 'NR>1 && tolower($3)=="true" {n++} END {print n+0}' "$csv")
        echo "  $(basename "$csv"): $n_ok/$n_total converged" | tee -a "$LOG"
    fi
done
echo "  log: $LOG" | tee -a "$LOG"
echo "  exit codes: fig5_sweep=$FIG5_RC fig5_retry=$FIG5_RETRY_RC fig6_sweep=$FIG6_RC fig6_retry=$FIG6_RETRY_RC" | tee -a "$LOG"

[[ $FIG5_RC -le 1 && $FIG6_RC -le 1 ]] && exit 0 || exit 1
