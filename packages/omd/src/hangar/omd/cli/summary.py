"""``omd-cli summary <run_id>`` — self-contained HTML run summary.

Produces a single HTML page at ``plots/{run_id}/summary.html`` with:
- header: plan metadata, run_id, convergence status
- key results: final objective, constraint values
- plan formulation: DVs, constraints, objective
- plot grid: thumbnails to every .png in the run's plots directory
- links to the N2 HTML and provenance DAG

Uses relative paths so the page works when opened directly from the
filesystem or copied to a deployment directory.
"""

from __future__ import annotations

import json
import shutil
from html import escape
from pathlib import Path

import click
import yaml

from hangar.omd.cli import cli


def _load_plan_for_run(run_id: str) -> tuple[dict | None, str | None, int | None]:
    """Return (plan_dict, plan_id, version) for a run, or (None, None, None)."""
    from hangar.omd.db import init_analysis_db, query_entity, plan_store_dir

    init_analysis_db()
    entity = query_entity(run_id)
    if not entity:
        return None, None, None
    meta = {}
    try:
        meta = json.loads(entity.get("metadata") or "{}")
    except Exception:
        pass

    plan_id = entity.get("plan_id") or meta.get("plan_id")
    version = entity.get("version") or meta.get("version")
    if not plan_id:
        return None, None, None

    # Prefer explicit version; fall back to latest
    plans_dir = plan_store_dir() / plan_id
    if not plans_dir.exists():
        return None, plan_id, None
    if version:
        path = plans_dir / f"v{int(version)}.yaml"
    else:
        versions = sorted(plans_dir.glob("v*.yaml"))
        path = versions[-1] if versions else None
    if not path or not path.exists():
        return None, plan_id, version

    with open(path) as f:
        return yaml.safe_load(f), plan_id, version


def _ensure_plots(run_id: str, plots_dir: Path, component_type: str | None) -> list[Path]:
    """Generate plots if missing, return the list of .png files."""
    if plots_dir.exists() and list(plots_dir.glob("*.png")):
        return sorted(plots_dir.glob("*.png"))

    from hangar.omd.db import recordings_dir
    rec = recordings_dir() / f"{run_id}.sql"
    if not rec.exists():
        return []

    from hangar.omd.plotting import generate_plots
    try:
        generate_plots(
            recorder_path=rec,
            plot_types=None,
            surface_name="wing",
            output_dir=plots_dir,
            component_type=component_type,
        )
    except Exception:
        pass
    return sorted(plots_dir.glob("*.png"))


def _render_dv_rows(plan: dict, final: dict) -> str:
    rows = []
    for dv in plan.get("design_variables") or []:
        name = dv.get("name", "")
        lo = dv.get("lower", "")
        hi = dv.get("upper", "")
        val = final.get(name, "")
        if isinstance(val, float):
            val = f"{val:.6g}"
        rows.append(
            f"<tr><td>{escape(str(name))}</td><td>{escape(str(lo))}</td>"
            f"<td>{escape(str(hi))}</td><td>{escape(str(val))}</td></tr>"
        )
    if not rows:
        return '<tr><td colspan="4" style="color:#777">(none)</td></tr>'
    return "\n".join(rows)


def _render_constraint_rows(plan: dict, final: dict) -> str:
    rows = []
    for c in plan.get("constraints") or []:
        name = c.get("name", "")
        lo = c.get("lower", "")
        hi = c.get("upper", "")
        eq = c.get("equals", "")
        val = final.get(name, "")
        if isinstance(val, float):
            val = f"{val:.6g}"
        bound = eq if eq != "" else f"{lo}..{hi}"
        rows.append(
            f"<tr><td>{escape(str(name))}</td><td>{escape(str(bound))}</td>"
            f"<td>{escape(str(val))}</td></tr>"
        )
    if not rows:
        return '<tr><td colspan="3" style="color:#777">(none)</td></tr>'
    return "\n".join(rows)


def _render_html(
    run_id: str,
    plan: dict | None,
    plan_id: str | None,
    version: int | None,
    final: dict,
    convergence_status: str,
    plot_files: list[Path],
    n2_link: str | None,
) -> str:
    meta = (plan or {}).get("metadata", {}) if isinstance(plan, dict) else {}
    plan_name = meta.get("name", plan_id or "(unknown)")
    description = meta.get("description", "")

    obj = (plan or {}).get("objective") or {}
    obj_name = obj.get("name", "")
    obj_val = final.get(obj_name, "")
    if isinstance(obj_val, float):
        obj_val = f"{obj_val:.6g}"

    dv_rows = _render_dv_rows(plan or {}, final)
    con_rows = _render_constraint_rows(plan or {}, final)
    plot_tiles = "\n".join(
        f'<figure><a href="{p.name}"><img src="{p.name}" alt="{escape(p.stem)}"/></a>'
        f'<figcaption>{escape(p.stem)}</figcaption></figure>'
        for p in plot_files
    ) or '<p style="color:#777">No plots available.</p>'

    n2_section = (
        f'<h2>Model structure (N2)</h2>'
        f'<p><a href="{n2_link}" target="_blank" class="n2-link">'
        f'Open N2 diagram in new tab &rarr;</a></p>'
        if n2_link else ""
    )

    status_color = {
        "success": "#50d8a0",
        "converged": "#50d8a0",
        "failed": "#ff6060",
    }.get(convergence_status.lower(), "#d0c060")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>omd summary: {escape(run_id)}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e0e0e0; padding: 24px; margin: 0; }}
  h1 {{ font-size: 20px; font-weight: 600; color: #8eb6ff; margin: 0 0 4px; }}
  h2 {{ font-size: 15px; color: #9cb8ff; margin: 24px 0 8px; }}
  .meta {{ color: #a0a8c0; font-size: 13px; margin-bottom: 16px; }}
  .status {{ display: inline-block; padding: 2px 10px; border-radius: 10px;
             background: {status_color}22; color: {status_color}; font-weight: 600;
             font-size: 12px; margin-left: 8px; }}
  .cards {{ display: flex; gap: 12px; flex-wrap: wrap; margin: 16px 0; }}
  .card {{ background: #1a1d27; padding: 12px 16px; border-radius: 8px;
           border: 1px solid #2d3047; min-width: 160px; }}
  .card .label {{ font-size: 11px; color: #888; text-transform: uppercase;
                  letter-spacing: 0.5px; }}
  .card .val {{ font-size: 18px; color: #e0e8ff; font-family: monospace;
                margin-top: 4px; }}
  table {{ border-collapse: collapse; width: 100%; margin-top: 4px;
           background: #15171f; border-radius: 6px; overflow: hidden; }}
  th, td {{ text-align: left; padding: 6px 10px; font-size: 12px;
            border-bottom: 1px solid #222530; }}
  th {{ background: #1a1d27; color: #888; font-weight: 500; font-size: 11px;
        text-transform: uppercase; letter-spacing: 0.5px; }}
  td {{ font-family: monospace; color: #d0d8f0; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
           gap: 12px; }}
  .grid figure {{ margin: 0; background: #1a1d27; padding: 8px;
                  border: 1px solid #2d3047; border-radius: 6px; }}
  .grid img {{ width: 100%; height: auto; display: block; }}
  .grid figcaption {{ font-size: 11px; color: #8898b8; text-align: center;
                      padding-top: 6px; font-family: monospace; }}
  a {{ color: #8eb6ff; }}
  .n2-link {{ display: inline-block; padding: 8px 16px; border-radius: 6px;
              background: #1a1d27; border: 1px solid #2d3047;
              text-decoration: none; font-size: 13px; }}
  .n2-link:hover {{ background: #252839; border-color: #4a5070; }}
</style>
</head>
<body>
<h1>{escape(plan_name)}<span class="status">{escape(convergence_status)}</span></h1>
<div class="meta">
  run_id: <code>{escape(run_id)}</code>
  {"&nbsp;·&nbsp; plan: <code>" + escape(plan_id) + "</code>" if plan_id else ""}
  {"&nbsp;·&nbsp; v" + str(version) if version else ""}
</div>
{f'<p style="color:#a0a8c0;max-width:800px">{escape(description)}</p>' if description else ""}

<div class="cards">
  <div class="card"><div class="label">objective ({escape(str(obj_name))})</div>
    <div class="val">{escape(str(obj_val))}</div></div>
  <div class="card"><div class="label">design vars</div>
    <div class="val">{len(plan.get("design_variables") or []) if plan else 0}</div></div>
  <div class="card"><div class="label">constraints</div>
    <div class="val">{len(plan.get("constraints") or []) if plan else 0}</div></div>
</div>

<h2>Design variables</h2>
<table><tr><th>name</th><th>lower</th><th>upper</th><th>final</th></tr>
{dv_rows}
</table>

<h2>Constraints</h2>
<table><tr><th>name</th><th>bound</th><th>final</th></tr>
{con_rows}
</table>

<h2>Plots</h2>
<div class="grid">{plot_tiles}</div>

{n2_section}
</body>
</html>
"""


@cli.command("summary")
@click.argument("run_id")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output HTML path (default: plots/{run_id}/summary.html).")
@click.option("--no-plots", is_flag=True, default=False,
              help="Skip on-demand plot generation; only use existing PNGs.")
def summary_cmd(run_id: str, output: str | None, no_plots: bool) -> None:
    """Produce a one-page HTML summary of a completed run."""
    from hangar.omd.db import init_analysis_db, omd_data_root, query_entity, n2_dir
    from hangar.omd.results import get_results

    init_analysis_db()
    entity = query_entity(run_id)
    if entity is None:
        click.echo(f"Run not found: {run_id}", err=True)
        raise SystemExit(1)

    meta: dict = {}
    try:
        meta = json.loads(entity.get("metadata") or "{}")
    except Exception:
        pass
    component_type = meta.get("component_type")
    convergence_status = (
        meta.get("convergence_status")
        or meta.get("status")
        or "unknown"
    )

    plan, plan_id, version = _load_plan_for_run(run_id)

    # Final values
    res = get_results(run_id, summary=True)
    final = res.get("final", {}) if isinstance(res, dict) else {}

    plots_dir = omd_data_root() / "plots" / run_id
    plots_dir.mkdir(parents=True, exist_ok=True)
    if no_plots:
        plot_files = sorted(plots_dir.glob("*.png"))
    else:
        plot_files = _ensure_plots(run_id, plots_dir, component_type)

    # Copy N2 next to summary.html so the relative link works
    out_path = Path(output) if output else plots_dir / "summary.html"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    n2_src = n2_dir() / f"{run_id}.html"
    n2_link: str | None = None
    if n2_src.exists():
        n2_dst = out_path.parent / "n2.html"
        if n2_src != n2_dst:
            shutil.copyfile(n2_src, n2_dst)
        n2_link = "n2.html"

    # Make plot links relative to output location
    rel_plot_files = []
    for p in plot_files:
        try:
            rel_plot_files.append(Path(p.relative_to(out_path.parent)))
        except ValueError:
            # Different directory; copy the PNG alongside the summary
            dst = out_path.parent / p.name
            if p != dst:
                shutil.copyfile(p, dst)
            rel_plot_files.append(Path(p.name))

    html = _render_html(
        run_id=run_id,
        plan=plan,
        plan_id=plan_id,
        version=version,
        final=final,
        convergence_status=str(convergence_status),
        plot_files=rel_plot_files,
        n2_link=n2_link,
    )
    out_path.write_text(html)
    click.echo(f"Summary written to {out_path}")
