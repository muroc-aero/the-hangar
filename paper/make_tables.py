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
    # Aviary cases (native avy/Sizing factory; run_lanes.py emits them
    # once aviary is installed in the venv)
    "avy_single_aisle": {
        "title": "Single-aisle sizing (Aviary)",
        "tools": "Aviary",
        "metrics": ["gross_mass_lbm", "total_fuel_mass_lbm", "final_time_min"],
    },
    "avy_bwb": {
        "title": "BWB sizing (Aviary)",
        "tools": "Aviary",
        "metrics": ["gross_mass_lbm", "total_fuel_mass_lbm",
                    "operating_mass_lbm", "final_time_min"],
    },
    "avy_oas_wing": {
        "title": "Sizing w/ OAS wingbox in Aviary",
        "tools": "Aviary + OAS",
        "metrics": ["gross_mass_lbm", "total_fuel_mass_lbm", "wing_mass_lbm",
                    "final_time_min"],
    },
    "oas_avy_wing_mass": {
        "title": "OAS wing mass -> Aviary sizing",
        "tools": "OAS + Aviary",
        "metrics": ["wing_mass_lbm", "gross_mass_lbm", "total_fuel_mass_lbm",
                    "final_time_min"],
    },
    "avy_three_tool": {
        "title": "Single-aisle three-tool sizing",
        "tools": "Aviary + OAS + pyCycle",
        "metrics": ["gross_mass_lbm", "total_fuel_mass_lbm", "wing_mass_lbm",
                    "final_time_min", "engine_scale_factor"],
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


# --- LaTeX -----------------------------------------------------------------
#
# The .tex files are pasted into the paper unedited, so each one carries its
# own float, caption and label. The preamble has to provide:
#
#     \usepackage{booktabs,tabularx,multirow}
#     \newcolumntype{Y}{>{\raggedright\arraybackslash}X}
#
# Y is a left-aligned X column: the text columns share whatever width the
# numbers leave and wrap inside it, rather than pushing the table off the
# page. Both tables are two-column floats (table*) at \footnotesize with
# tight column separation -- that is what makes ten-odd columns fit
# \textwidth on one page.

TEX_REQUIRES = (r"needs \usepackage{booktabs,tabularx,multirow} and "
                r"\newcolumntype{Y}{>{\raggedright\arraybackslash}X}")

# Slug -> the name the paper uses. The CSV and Markdown keep the slugs --
# they are how you find the run again -- and the .tex gets prose.
TEX_TITLE = {
    "paraboloid": "Paraboloid",
    "paraboloid_analysis": "Paraboloid analysis",
    "paraboloid_optimization": "Paraboloid optimization",
    "oas_aero_rect": "Rectangular wing VLM analysis",
    "oas_aerostruct_rect": "Rectangular wing aerostructural",
    "ocp_caravan_basic": "Caravan three-phase mission",
    "ocp_caravan_full": "Caravan mission with balanced field length",
    "ocp_hybrid_twin": "King Air series-hybrid mission",
    "oas_ocp_combined": "Wing and mission, uncoupled",
    "ocp_oas_coupled": "Mission with VLM drag surrogate",
    "ocp_oas_direct": "Mission with directly coupled VLM",
    "ocp_pyc_coupled": "Mission with turbojet surrogate",
    "pyc_turbojet": "Turbojet design point",
    "evt_native_sizing": "Archer Midnight eVTOL sizing",
    "evt_open_sizing": "Archer Midnight eVTOL sizing",
    "ocp_three_tool": "737-800 three-tool coupled mission",
    "avy_single_aisle": "Single-aisle sizing and mission",
    "avy_bwb": "Blended-wing-body sizing",
    "avy_oas_wing": "Sizing with OAS wingbox wing mass",
    "oas_avy_wing_mass": "OAS wing mass into Aviary sizing",
    "avy_three_tool": "Single-aisle three-tool coupled sizing",
}

_SLUG_BY_TITLE = {info["title"]: slug for slug, info in CASE_INFO.items()}

# Thin space BEFORE the "+" and an ordinary one after: the plus stays welded
# to the tool it follows, and the line may still break after it. A narrow
# Tools column then wraps as "OCP+ / OAS+ / pyCycle" instead of overflowing.
TEX_TOOLS = {
    "OAS + OCP": r"OAS\,+\ OCP",
    "OCP + OAS": r"OCP\,+\ OAS",
    "OCP + pyCycle": r"OCP\,+\ pyCycle",
    "OCP + OAS + pyCycle": r"OCP\,+\ OAS\,+\ pyCycle",
    "evt (native)": "evtolpy",
    "Aviary + OAS": r"Aviary\,+\ OAS",
    "OAS + Aviary": r"OAS\,+\ Aviary",
    "Aviary + OAS + pyCycle": r"Aviary\,+\ OAS\,+\ pyCycle",
}

# Metric keys are variable names; the paper wants units.
TEX_METRIC = {
    "fuel_burn_kg": "fuel (kg)",
    "OEW_kg": "OEW (kg)",
    "MTOW_kg": "MTOW (kg)",
    "sized_mtow_kg": "MTOW (kg)",
    "total_mission_energy_kw_hr": "energy (kWh)",
    "peak_power_kw": "peak power (kW)",
    "wing_CL": "wing CL",
    "wing_CD": "wing CD",
    "Fn": "Fn (lbf)",
    "gross_mass_lbm": "gross mass (lbm)",
    "total_fuel_mass_lbm": "fuel (lbm)",
    "operating_mass_lbm": "OEW (lbm)",
    "wing_mass_lbm": "wing mass (lbm)",
    "final_time_min": "block time (min)",
    "engine_scale_factor": "engine scale factor",
}

# Column headings have to survive a 3pt-separated numeric column, so the
# qualifiers they carry in the CSV move into the caption instead.
TEX_HEADER = {
    "Lane C (scripted)": "Lane C",
    "Lane C (agent)": "Agent",
    "rel diff B": r"$\Delta$B",
    "rel diff C": r"$\Delta$C",
    "rel diff agent": r"$\Delta$agent",
    "Passed": "Pass",
    "Failed": "Fail",
    "Valid-call rate (med)": "Valid calls",
    "Turns (med)": "Turns",
    "Wall clock s (med)": "Wall (s)",
}

LANE_PARITY_CAPTION = (
    "Three-lane parity: identical results through direct scripts (Lane A), "
    "omd plans (Lane B), and the MCP tool surface (Lane C). The $\\Delta$ "
    "columns are relative differences from Lane A. The abbreviations for the "
    "tools are OpenConcept (OCP) and OpenAeroStruct (OAS).")

LANE_PARITY_AGENT_CAPTION = (
    "Agent is that same MCP surface driven by a blind agent given the "
    "engineering goal alone. Its values are effect-graded -- read from the "
    "run's provenance record rather than from the agent's own report -- and "
    "the worst seed is shown per metric, so the column bounds agreement "
    "rather than averaging it. Per-seed reliability is in "
    "Table~\\ref{tab:sandboxed-evals}.")

EVALS_CAPTION = (
    "Sandboxed agent evals over the MCP tool surface: how reliably each "
    "model and harness reaches the Lane A reference. Pass and Fail count "
    "graded seeds. Lost counts seeds the harness never measured (crash, "
    "credential, network), which are not failures. Review counts seeds whose "
    "self-reported verdict contradicts the effect grade. The last three "
    "columns are medians over the graded seeds.")


def _tex_escape(s: str) -> str:
    return (s.replace("\\", r"\textbackslash{}").replace("_", r"\_")
             .replace("%", r"\%").replace("&", r"\&").replace("#", r"\#"))


def _tex_cell(value: str, display: dict[str, str]) -> str:
    """Literal LaTeX from the display table, else the escaped raw value."""
    if value in display:
        return display[value]
    return _tex_escape(value)


def _tex_groups(rows: list[list[str]]) -> list[list[list[str]]]:
    """One group of rows per example.

    A row opens a group when its first column is non-empty and names something
    other than the open group. Lane parity blanks the repeated example name
    and the evals table repeats it; both group the same way.
    """
    groups: list[list[list[str]]] = []
    for row in rows:
        if not groups or (row[0] and row[0] != groups[-1][0][0]):
            groups.append([])
        groups[-1].append(row)
    return groups


def _tex_span(title: str, n_rows: int) -> str:
    """The example name, spanning its group.

    A one-row group is left as plain text: \\multirow would let a name that
    wraps to two lines run past the single row it was given, whereas tabularx
    simply makes the row taller.
    """
    if n_rows == 1:
        return rf"\textbf{{{title}}}"
    return rf"\multirow{{{n_rows}}}{{\linewidth}}{{\textbf{{{title}}}}}"


def _tex_float(colspec: str, header: list[str], body: list[str], *,
               caption: str, label: str, note: str = "") -> str:
    lines = []
    if note:
        lines.append(f"% {note}")
    lines.append(f"% {TEX_REQUIRES}")
    lines += [
        r"\begin{table*}[htbp]",
        r"\footnotesize",
        r"\setlength{\tabcolsep}{3pt}",
        rf"\caption{{{caption}}}",
        rf"\label{{{label}}}",
        r"\begin{tabularx}{\textwidth}{" + colspec + "}",
        r"\toprule",
        " & ".join(rf"\textbf{{{h}}}" for h in header) + r" \\",
        r"\midrule",
    ]
    lines += body
    lines += [r"\bottomrule", r"\end{tabularx}", r"\end{table*}"]
    return "\n".join(lines) + "\n"


def without_agent_columns(header: list[str],
                          rows: list[list[str]]) -> tuple[list, list]:
    """The eight-column lane parity table: Lanes A, B and scripted C only.

    Dropping the agent pair empties any row whose only comparison was the
    agent's -- the paraboloid design variables, which Lanes B and C never
    report -- so those rows go too, and the example name moves down to
    whichever row now leads the group.
    """
    kept: list[list[str]] = []
    carried: tuple[str, str] | None = None
    for row in rows:
        row = list(row)[:8]
        if row[0]:
            carried = (row[0], row[1])
        if all(c == "--" for c in row[4:]):
            continue
        if carried:
            row[0], row[1] = carried
            carried = None
        kept.append(row)
    return header[:8], kept


def write_lane_parity_tex(path: Path, header: list[str],
                          rows: list[list[str]], note: str = "") -> None:
    colspec = "Y Y l" + " r" * (len(header) - 3)
    body: list[str] = []
    for i, group in enumerate(_tex_groups(rows)):
        if i:
            body.append(r"\midrule")
        for j, row in enumerate(group):
            cells = [_tex_escape(c) for c in row]
            if j == 0:
                title = TEX_TITLE.get(_SLUG_BY_TITLE.get(row[0], ""),
                                      _tex_escape(row[0]))
                cells[0] = _tex_span(title, len(group))
                cells[1] = _tex_cell(row[1], TEX_TOOLS)
            else:
                cells[0] = cells[1] = ""
            cells[2] = _tex_cell(row[2], TEX_METRIC)
            body.append(" & ".join(cells) + r" \\")
    caption = LANE_PARITY_CAPTION
    if "Lane C (agent)" in header:
        caption += " " + LANE_PARITY_AGENT_CAPTION
    path.write_text(_tex_float(
        colspec, [_tex_cell(h, TEX_HEADER) for h in header], body,
        caption=caption, label="tab:lane-parity", note=note))


def write_evals_tex(path: Path, header: list[str], rows: list[list[str]],
                    note: str = "") -> None:
    colspec = "Y l l" + " r" * (len(header) - 3)
    body: list[str] = []
    for i, group in enumerate(_tex_groups(rows)):
        if i:
            body.append(r"\midrule")
        for j, row in enumerate(group):
            cells = [_tex_escape(c) for c in row]
            if j == 0:
                cells[0] = _tex_span(
                    TEX_TITLE.get(row[0], _tex_escape(row[0])), len(group))
            else:
                cells[0] = ""
            body.append(" & ".join(cells) + r" \\")
    path.write_text(_tex_float(
        colspec, [_tex_cell(h, TEX_HEADER) for h in header], body,
        caption=EVALS_CAPTION, label="tab:sandboxed-evals", note=note))


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


# The evals table lists the same examples as the parity table, so it uses the
# same order -- the two tables are two readings of one arm, and they read
# row-group against row-group. Eval case slugs are not always the parity slug.
_EVALS_CASE_ALIAS = {"paraboloid": "paraboloid_analysis",
                     "evt_open_sizing": "evt_native_sizing"}
_CASE_ORDER = {slug: i for i, slug in enumerate(CASE_INFO)}


def _case_rank(case: str) -> tuple[int, str]:
    slug = _EVALS_CASE_ALIAS.get(case, case)
    return (_CASE_ORDER.get(slug, len(_CASE_ORDER)), case)


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
    for (case, harness, model), (_, rec) in sorted(
            latest.items(),
            key=lambda kv: (_case_rank(kv[0][0]), kv[0][1], kv[0][2])):
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
    parser.add_argument("--tex-omit-agent", action="store_true",
                        help="drop the two agent columns from lane_parity.tex "
                             "(the CSV and Markdown keep them) -- for a "
                             "narrower float than \\textwidth")
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
    theader, trows = ((without_agent_columns(header, rows))
                      if args.tex_omit_agent else (header, rows))
    write_lane_parity_tex(TABLES_DIR / "lane_parity.tex", theader, trows, note)
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
            write_evals_tex(TABLES_DIR / "sandboxed_evals.tex", eheader,
                            erows, evals_note)
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
