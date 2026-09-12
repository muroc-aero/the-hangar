#!/usr/bin/env python
"""Render the paper's lane-parity and sandboxed-eval tables.

Inputs (all optional except the first):
  paper/results/lane_parity.jsonl   -- written by paper/run_lanes.py
  ../hangar-evals/results/*.jsonl -- per-seed records; the Lane C (agent)
      column is read from these, so one arm fills both tables
  ../hangar-evals/results/regraded/*_summary.json -- sandboxed evals
      (falls back to results/ if not regraded yet; override with --evals-dir)

Outputs:
  paper/tables/lane_parity.{csv,md,tex}
  paper/tables/sandboxed_evals.{csv,md,tex}   (when eval summaries exist)

Usage (from the repo root):

    uv run python paper/make_tables.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

PAPER_DIR = Path(__file__).resolve().parent
REPO_ROOT = PAPER_DIR.parent
RESULTS_DIR = PAPER_DIR / "results"
TABLES_DIR = PAPER_DIR / "tables"
_EVALS_ROOT = REPO_ROOT.parent / "hangar-evals" / "results"
# Prefer the REGRADED summaries: they carry n_ambiguous / n_report_disagrees,
# the two counts that say whether a Passed cell can be read at face value.
# Defaulting to the raw directory meant a bare `make_tables.py` silently
# overwrote a table that had those columns with one that did not.
DEFAULT_EVALS_DIR = (_EVALS_ROOT / "regraded" if (_EVALS_ROOT / "regraded").is_dir()
                     else _EVALS_ROOT)

# Presentation order, short description, and the metrics worth printing
# for each parity case (case slugs match the `case=` tags in
# packages/omd/examples/tests/test_parity*.py).
CASE_INFO: dict[str, dict] = {
    "paraboloid_analysis": {
        "title": "Paraboloid analysis",
        "tools": "OpenMDAO",
        "metrics": ["x", "y", "f_xy"],
    },
    "paraboloid_optimization": {
        "title": "Paraboloid optimization",
        "tools": "OpenMDAO/SLSQP",
        "metrics": ["x", "y", "f_xy"],
    },
    "oas_aero_rect": {
        "title": "Rect wing VLM analysis",
        "tools": "OAS",
        "metrics": ["CL", "CD"],
    },
    "oas_aerostruct_rect": {
        "title": "Rect wing aerostructural",
        "tools": "OAS (tube FEM)",
        "metrics": ["CL", "CD"],
    },
    "ocp_caravan_basic": {
        "title": "Caravan 3-phase mission",
        "tools": "OCP",
        "metrics": ["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
    },
    "ocp_caravan_full": {
        "title": "Caravan full mission (BFL)",
        "tools": "OCP",
        "metrics": ["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
    },
    "ocp_hybrid_twin": {
        "title": "King Air series-hybrid mission",
        "tools": "OCP",
        "metrics": ["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
    },
    "oas_ocp_combined": {
        "title": "Wing + mission, uncoupled composite",
        "tools": "OAS + OCP",
        "metrics": ["wing_CL", "wing_CD", "fuel_burn_kg", "OEW_kg", "MTOW_kg"],
    },
    "ocp_oas_coupled": {
        "title": "Mission w/ VLM drag slot",
        "tools": "OCP + OAS",
        "metrics": ["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
    },
    "ocp_oas_direct": {
        "title": "Mission w/ direct-coupled VLM drag",
        "tools": "OCP + OAS",
        "metrics": ["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
    },
    "ocp_pyc_coupled": {
        "title": "Mission w/ turbojet surrogate",
        "tools": "OCP + pyCycle",
        "metrics": ["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
    },
    "pyc_turbojet": {
        "title": "Turbojet design point",
        "tools": "pyCycle",
        "metrics": ["Fn", "TSFC", "OPR"],
    },
    "evt_native_sizing": {
        "title": "Archer Midnight eVTOL sizing",
        "tools": "evt (native)",
        "metrics": ["sized_mtow_kg", "total_mission_energy_kw_hr",
                    "peak_power_kw"],
    },
    "ocp_three_tool": {
        "title": "B738 three-tool mission",
        "tools": "OCP + OAS + pyCycle",
        "metrics": ["fuel_burn_kg", "OEW_kg", "MTOW_kg"],
    },
}

# Agent-eval case/metric names -> (parity case slug, metric key).
AGENT_METRIC_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("paraboloid", "analysis_f_xy"): ("paraboloid_analysis", "f_xy"),
    ("paraboloid", "opt_f_xy"): ("paraboloid_optimization", "f_xy"),
    ("paraboloid", "opt_x"): ("paraboloid_optimization", "x"),
    ("paraboloid", "opt_y"): ("paraboloid_optimization", "y"),
}
for _case in ("ocp_caravan_basic", "ocp_caravan_full", "ocp_hybrid_twin",
              "ocp_oas_coupled", "ocp_oas_direct", "ocp_three_tool"):
    for _m in ("fuel_burn_kg", "OEW_kg", "MTOW_kg"):
        AGENT_METRIC_MAP[(_case, _m)] = (_case, _m)
for _case in ("oas_aero_rect", "oas_aerostruct_rect"):
    for _m in ("CL", "CD"):
        AGENT_METRIC_MAP[(_case, _m)] = (_case, _m)
for _m in ("wing_CL", "wing_CD", "fuel_burn_kg", "OEW_kg", "MTOW_kg"):
    AGENT_METRIC_MAP[("oas_ocp_combined", _m)] = ("oas_ocp_combined", _m)
for _m in ("Fn", "TSFC", "OPR"):
    AGENT_METRIC_MAP[("pyc_turbojet", _m)] = ("pyc_turbojet", _m)
for _m in ("sized_mtow_kg", "total_mission_energy_kw_hr", "peak_power_kw"):
    AGENT_METRIC_MAP[("evt_open_sizing", _m)] = ("evt_native_sizing", _m)
    AGENT_METRIC_MAP[("evt_native_sizing", _m)] = ("evt_native_sizing", _m)


def _fmt(v: float | None) -> str:
    if v is None:
        return "--"
    return f"{v:.6g}"


def _fmt_rel(ref: float | None, val: float | None) -> str:
    if ref is None or val is None:
        return "--"
    if ref == 0:
        return "--"
    rel = abs(val - ref) / abs(ref)
    return "0" if rel == 0 else f"{rel:.1e}"


def load_parity(jsonl_path: Path) -> dict[str, dict]:
    """case slug -> {"lane_a": {...}, "B": {...}, "C": {...}}."""
    cases: dict[str, dict] = {}
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        entry = cases.setdefault(row["case"], {"lane_a": {}})
        # Lane A values from later suites overwrite earlier ones; they are
        # the same reference scripts, so any drift shows up as a rel diff.
        entry["lane_a"].update(row["lane_a"])
        entry[row["lane"]] = row["values"]
    return cases


def _arm_records(records_dir: Path, harness: str,
                 model: str) -> dict[str, list[dict]]:
    """case -> that case's records from the newest file that HAS this arm.

    Newest-file-per-case alone is not enough: results/ holds every arm side by
    side, so the newest file for a case can easily be a different model's. Walk
    newest-first and take the first file that actually contains the arm asked
    for, which is the same file the arm's own tooling would resume from.
    """
    by_case: dict[str, list[dict]] = {}
    paths = sorted(records_dir.glob("*.jsonl"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for path in paths:
        case = path.stem.split("_2026", 1)[0]
        if case in by_case:
            continue
        latest: dict[tuple, dict] = {}
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            latest[(r["case"], r["harness"], r["model"], r["seed"])] = r
        mine = [r for r in latest.values()
                if r.get("harness") == harness and r.get("model") == model]
        if mine:
            by_case[case] = mine
    return by_case


def load_agent_from_records(records_dir: Path, harness: str,
                            model: str) -> dict[tuple[str, str], dict]:
    """(case slug, metric) -> agent value from the sandboxed arm's records.

    This is the ONLY source for the agent column: one column, one provenance.

    These are EFFECT values -- what the agent's graded run actually produced,
    read from its omd provenance DB -- not the numbers it reported. That is
    the right quantity for a parity claim: the question is whether the lane
    reproduces Lane A, not whether the agent transcribed it correctly.

    Where an arm ran several seeds, the WORST seed per metric is reported, so
    this column bounds agreement rather than flattering it. Per-seed pass
    rates are the other table's job -- see ``sandboxed_evals``.
    """
    best: dict[tuple[str, str], dict] = {}
    for records in _arm_records(records_dir, harness, model).values():
        for r in records:
            for sc in (r.get("scores") or []):
                mapped = AGENT_METRIC_MAP.get((r["case"], sc["key"]))
                if mapped is None or not isinstance(sc.get("agent"), (int, float)):
                    continue
                entry = best.setdefault(
                    mapped, {"agent": None, "lane_a": sc["lane_a"],
                             "source": "arm", "n_seeds": 0, "rel": -1.0})
                entry["n_seeds"] += 1
                rel = abs(sc.get("rel_err") or 0.0)
                if rel > entry["rel"]:
                    entry.update(agent=sc["agent"], lane_a=sc["lane_a"], rel=rel)
    return best


def _with_agent_provenance(note: str, agent: dict, model: str) -> str:
    """Say which arm the agent column is, so the column has one provenance."""
    if not agent:
        return note
    seeds = max((v.get("n_seeds", 1) for v in agent.values()), default=1)
    parts = [note] if note else []
    parts.append(
        f"Lane C (agent): effect-graded values from the sandboxed {model} arm "
        f"over {seeds} seeds, worst seed per metric, so the column bounds "
        f"agreement; per-seed pass rates are in sandboxed_evals. A case the "
        f"arm has not run shows -- rather than a value from another run.")
    return " ".join(parts)


def build_rows(cases: dict, agent: dict) -> tuple[list[str], list[list[str]]]:
    have_agent = bool(agent)
    header = ["Example", "Tools", "Metric", "Lane A", "Lane B", "rel diff B",
              "Lane C (scripted)", "rel diff C"]
    if have_agent:
        header += ["Lane C (agent)", "rel diff agent"]

    ordered = [c for c in CASE_INFO if c in cases]
    ordered += sorted(c for c in cases if c not in CASE_INFO)

    rows: list[list[str]] = []
    for slug in ordered:
        info = CASE_INFO.get(slug, {"title": slug, "tools": "", "metrics": None})
        entry = cases[slug]
        metrics = info["metrics"] or sorted(entry["lane_a"])
        first = True
        for m in metrics:
            a = entry["lane_a"].get(m)
            b = entry.get("B", {}).get(m)
            c = entry.get("C", {}).get(m)
            if not isinstance(a, (int, float)):
                continue
            ag = agent.get((slug, m), {}).get("agent") if have_agent else None
            if b is None and c is None and ag is None:
                continue  # input echoed by Lane A only -- nothing to compare
            row = [
                info["title"] if first else "",
                info["tools"] if first else "",
                m, _fmt(a), _fmt(b), _fmt_rel(a, b), _fmt(c), _fmt_rel(a, c),
            ]
            if have_agent:
                row += [_fmt(ag), _fmt_rel(a, ag)]
            rows.append(row)
            first = False
    return header, rows


def write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def write_md(path: Path, header: list[str], rows: list[list[str]],
             note: str = "") -> None:
    lines = []
    if note:
        lines.append(f"<!-- {note} -->")
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---" for _ in header) + "|")
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    path.write_text("\n".join(lines) + "\n")


def write_tex(path: Path, header: list[str], rows: list[list[str]],
              note: str = "") -> None:
    def esc(s: str) -> str:
        return (s.replace("\\", r"\textbackslash{}").replace("_", r"\_")
                 .replace("%", r"\%").replace("&", r"\&").replace("#", r"\#"))

    colspec = "ll" + "r" * (len(header) - 2)
    lines = []
    if note:
        lines.append(f"% {note}")
    lines.append(r"\begin{tabular}{" + colspec + "}")
    lines.append(r"\toprule")
    lines.append(" & ".join(esc(h) for h in header) + r" \\")
    lines.append(r"\midrule")
    for r in rows:
        if r[0] and lines[-1] != r"\midrule":
            lines.append(r"\addlinespace")
        lines.append(" & ".join(esc(c) for c in r) + r" \\")
    lines.append(r"\bottomrule")
    lines.append(r"\end{tabular}")
    path.write_text("\n".join(lines) + "\n")


def _portable(path: Path) -> str:
    """A path fit to commit: relative to the repo root when it can be.

    The note lands in a tracked file, so an absolute path would bake one
    machine's home directory into the paper's table and make an otherwise
    byte-identical re-render show up as a diff.

    Rendered relative to the repo root, which is also the form you would pass
    back in as ``--evals-dir``.
    """
    try:
        return os.path.relpath(path.resolve(), REPO_ROOT)
    except ValueError:      # different drive on Windows
        return str(path)


def _median_of(block: dict | None, default: str = "--") -> str:
    if not isinstance(block, dict) or "median" not in block:
        return default
    return f"{block['median']:.3g}"


def build_evals_rows(evals_dir: Path) -> tuple[list[str], list[list[str]]]:
    header = ["Case", "Harness", "Model", "Seeds", "Passed", "Failed", "Lost",
              "Review", "Valid-call rate (med)", "Turns (med)",
              "Wall clock s (med)"]
    latest: dict[tuple, tuple[str, dict]] = {}
    for path in sorted(evals_dir.glob("*_summary.json")):
        try:
            records = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for rec in records:
            key = (rec.get("case"), rec.get("harness"), rec.get("model"))
            latest[key] = (path.name, rec)  # sorted glob -> last wins
    rows = []
    for (case, harness, model), (_, rec) in sorted(latest.items()):
        n = rec.get("n_seeds", 0)
        passed = rec.get("n_passed", 0)
        lost = rec.get("n_harness_errors")
        rows.append([
            str(case), str(harness), str(model), str(n),
            f"{passed}/{n}",
            # Failed = ran, was graded, did not pass. Seeds the harness lost
            # were never measured, so they come out of the middle rather than
            # being counted against the agent.
            "--" if lost is None else str(max(0, n - passed - lost)),
            "--" if lost is None else str(lost),
            str(rec.get("n_needs_review", "--")),
            _median_of(rec.get("valid_call_rate")),
            _median_of(rec.get("turns")),
            _median_of(rec.get("wall_clock_s")),
        ])
    return header, rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--evals-dir", type=Path, default=DEFAULT_EVALS_DIR,
                        help="hangar-evals results dir with *_summary.json")
    parser.add_argument("--agent-model", default="claude-opus-5",
                        help="model whose arm feeds the Lane C agent column")
    parser.add_argument("--agent-harness", default="claude",
                        help="harness whose arm feeds the Lane C agent column")
    args = parser.parse_args()

    jsonl = RESULTS_DIR / "lane_parity.jsonl"
    if not jsonl.exists():
        print(f"ERROR: {jsonl} not found -- run paper/run_lanes.py first.")
        return 1

    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    note = ""
    meta_path = RESULTS_DIR / "lane_parity_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        note = (f"generated from {meta.get('results_jsonl')} at "
                f"{meta.get('timestamp_utc')} (git {meta.get('git_sha')}, "
                f"pytest exit {meta.get('pytest_exit_code')})")

    # The agent lane is the sandboxed arm, and only the arm. A case the arm has
    # not run shows "--" rather than a number from some other run: one column,
    # one provenance. (Today that is ocp_three_tool alone.)
    records_dir = args.evals_dir if args.evals_dir.name != "regraded" \
        else args.evals_dir.parent
    agent = (load_agent_from_records(records_dir, args.agent_harness,
                                     args.agent_model)
             if records_dir.is_dir() else {})
    note = _with_agent_provenance(note, agent, args.agent_model)

    cases = load_parity(jsonl)
    header, rows = build_rows(cases, agent)
    write_csv(TABLES_DIR / "lane_parity.csv", header, rows)
    write_md(TABLES_DIR / "lane_parity.md", header, rows, note)
    write_tex(TABLES_DIR / "lane_parity.tex", header, rows, note)
    print(f"Lane parity table: {len(rows)} metric rows across "
          f"{len(cases)} cases -> {TABLES_DIR}/lane_parity.{{csv,md,tex}}")
    if not agent:
        print(f"  (no {args.agent_model} records under {records_dir} -- agent "
              "columns omitted; run an arm with hangar-evals first)")

    if args.evals_dir.is_dir():
        eheader, erows = build_evals_rows(args.evals_dir)
        if erows:
            write_csv(TABLES_DIR / "sandboxed_evals.csv", eheader, erows)
            evals_note = (
                f"source: {_portable(args.evals_dir)} -- Passed/Failed are "
                "results over graded seeds. Lost: seeds the harness never "
                "measured (crash, credential, network); these are not failures "
                "and a nonzero count means the arm needs re-running, not "
                "annotating. Review: seeds whose agent-reported verdict "
                "contradicts the effect grade, awaiting a human look "
                "(`evals review`).")
            write_md(TABLES_DIR / "sandboxed_evals.md", eheader, erows,
                     evals_note)
            write_tex(TABLES_DIR / "sandboxed_evals.tex", eheader, erows,
                      evals_note)
            print(f"Sandboxed evals table: {len(erows)} rows -> "
                  f"{TABLES_DIR}/sandboxed_evals.{{csv,md,tex}}")
        else:
            print(f"No *_summary.json records in {args.evals_dir}")
    else:
        print(f"hangar-evals results dir not found ({args.evals_dir}) -- "
              "skipping sandboxed table")
    return 0


if __name__ == "__main__":
    sys.exit(main())
