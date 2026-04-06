#!/usr/bin/env bash
# run_study.sh -- Execute the full regional wing optimization study.
#
# Usage:
#   bash run_study.sh [--phase PHASE] [--dry-run]
#
# Phases:
#   all        (default) Run everything in order
#   mesh       Mesh convergence only (02-mesh-*)
#   baseline   Baseline analysis only (01-baseline)
#   optimize   Main optimization only (03-opt-fuelburn)
#   sens       Sensitivity studies only (04-sens-*)
#   robust     Robustness studies only (05-robust-*)
#   plots      Generate plots for all completed runs
#   summary    Print summary table of all results

set -euo pipefail

STUDY_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$STUDY_DIR/../.." && pwd)"
LOG_DIR="$STUDY_DIR/logs"
RESULTS_FILE="$STUDY_DIR/results_summary.txt"

mkdir -p "$LOG_DIR"

# Parse arguments
PHASE="all"
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) PHASE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

run_case() {
    local plan_dir="$1"
    local mode="$2"  # analysis or optimize
    local label
    label="$(basename "$plan_dir")"

    echo ""
    echo "================================================================"
    echo "  $label  ($mode)"
    echo "================================================================"

    local plan_yaml="$plan_dir/plan.yaml"
    local log="$LOG_DIR/${label}.log"

    # Assemble
    echo "  Assembling..."
    omd-cli assemble "$plan_dir" --output "$plan_yaml" 2>&1 | tee "$LOG_DIR/${label}_assemble.log"

    if [[ ! -f "$plan_yaml" ]]; then
        echo "  ERROR: plan.yaml not created for $label"
        return 1
    fi

    # Validate
    echo "  Validating..."
    omd-cli validate "$plan_yaml" 2>&1 | tee -a "$LOG_DIR/${label}_assemble.log"

    if $DRY_RUN; then
        echo "  [DRY RUN] Would run: omd-cli run $plan_yaml --mode $mode"
        return 0
    fi

    # Run
    echo "  Running ($mode)..."
    local start_time
    start_time=$(date +%s)

    if omd-cli run "$plan_yaml" --mode "$mode" 2>&1 | tee "$log"; then
        local end_time
        end_time=$(date +%s)
        local elapsed=$(( end_time - start_time ))
        echo "  COMPLETED in ${elapsed}s"

        # Extract run_id from log
        local run_id
        run_id=$(grep -oP 'run_id[=: ]+\K[a-zA-Z0-9_-]+' "$log" | tail -1 || true)
        if [[ -n "$run_id" ]]; then
            echo "$label|$mode|$run_id|${elapsed}s|OK" >> "$RESULTS_FILE"
            echo "  run_id: $run_id"
        else
            echo "$label|$mode|unknown|${elapsed}s|OK (no run_id captured)" >> "$RESULTS_FILE"
        fi
    else
        local end_time
        end_time=$(date +%s)
        local elapsed=$(( end_time - start_time ))
        echo "  FAILED after ${elapsed}s -- see $log"
        echo "$label|$mode|n/a|${elapsed}s|FAILED" >> "$RESULTS_FILE"
        return 1
    fi
}

plot_case() {
    local run_id="$1"
    local label="$2"

    if [[ "$run_id" == "n/a" || "$run_id" == "unknown" ]]; then
        echo "  Skipping plots for $label (no run_id)"
        return 0
    fi

    echo "  Generating plots for $label (run_id=$run_id)..."
    omd-cli plot "$run_id" --type all 2>&1 | tee "$LOG_DIR/${label}_plot.log" || true
}

print_summary() {
    echo ""
    echo "================================================================"
    echo "  STUDY RESULTS SUMMARY"
    echo "================================================================"
    echo ""
    if [[ -f "$RESULTS_FILE" ]]; then
        printf "%-30s %-10s %-20s %-8s %-8s\n" "Case" "Mode" "Run ID" "Time" "Status"
        printf "%s\n" "$(printf '=%.0s' {1..80})"
        while IFS='|' read -r label mode run_id elapsed status; do
            printf "%-30s %-10s %-20s %-8s %-8s\n" "$label" "$mode" "$run_id" "$elapsed" "$status"
        done < "$RESULTS_FILE"
    else
        echo "  No results found. Run the study first."
    fi
    echo ""
}

query_results() {
    echo ""
    echo "================================================================"
    echo "  DETAILED RESULTS"
    echo "================================================================"
    if [[ -f "$RESULTS_FILE" ]]; then
        while IFS='|' read -r label mode run_id elapsed status; do
            if [[ "$run_id" != "n/a" && "$run_id" != "unknown" && "$status" == *"OK"* ]]; then
                echo ""
                echo "--- $label ($run_id) ---"
                omd-cli results "$run_id" --summary 2>&1 || true
            fi
        done < "$RESULTS_FILE"
    fi
}


# ---------------------------------------------------------------------------
# Study phases
# ---------------------------------------------------------------------------

run_mesh() {
    echo ""
    echo "======== PHASE: MESH CONVERGENCE ========"
    for ny in 07 11 15 21 25; do
        run_case "$STUDY_DIR/02-mesh-ny${ny}" analysis || true
    done
}

run_baseline() {
    echo ""
    echo "======== PHASE: BASELINE ========"
    run_case "$STUDY_DIR/01-baseline" analysis || true
}

run_optimize() {
    echo ""
    echo "======== PHASE: MAIN OPTIMIZATION ========"
    run_case "$STUDY_DIR/03-opt-fuelburn" optimize
}

run_sens() {
    echo ""
    echo "======== PHASE: SENSITIVITY STUDIES ========"
    for d in "$STUDY_DIR"/04-sens-*; do
        [[ -d "$d" ]] && run_case "$d" optimize || true
    done
}

run_robust() {
    echo ""
    echo "======== PHASE: ROBUSTNESS STUDIES ========"
    for d in "$STUDY_DIR"/05-robust-*; do
        [[ -d "$d" ]] && run_case "$d" optimize || true
    done
}

run_plots() {
    echo ""
    echo "======== PHASE: PLOT GENERATION ========"
    if [[ -f "$RESULTS_FILE" ]]; then
        while IFS='|' read -r label mode run_id elapsed status; do
            if [[ "$status" == *"OK"* ]]; then
                plot_case "$run_id" "$label"
            fi
        done < "$RESULTS_FILE"
    else
        echo "  No results to plot. Run the study first."
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

echo "Regional Wing Optimization Study"
echo "  Phase: $PHASE"
echo "  Study dir: $STUDY_DIR"
echo "  Dry run: $DRY_RUN"
echo ""

# Clear results file for fresh run (except for plots/summary phases)
if [[ "$PHASE" != "plots" && "$PHASE" != "summary" ]]; then
    > "$RESULTS_FILE"
fi

case "$PHASE" in
    all)
        run_baseline
        run_mesh
        run_optimize
        run_sens
        run_robust
        run_plots
        print_summary
        query_results
        ;;
    mesh)      run_mesh; print_summary ;;
    baseline)  run_baseline; print_summary ;;
    optimize)  run_optimize; print_summary ;;
    sens)      run_sens; print_summary ;;
    robust)    run_robust; print_summary ;;
    plots)     run_plots ;;
    summary)   print_summary; query_results ;;
    *)         echo "Unknown phase: $PHASE"; exit 1 ;;
esac

echo ""
echo "Study complete. Logs in: $LOG_DIR"
echo "Results summary: $RESULTS_FILE"
