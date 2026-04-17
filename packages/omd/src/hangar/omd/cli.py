"""Click CLI for hangar-omd.

Provides subcommands: assemble, validate, run, results, export, provenance.
"""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group()
def cli() -> None:
    """omd -- MDAO analysis plan server."""


@cli.command()
@click.argument("plan_dir", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output path for assembled plan (default: <plan_dir>/plan.yaml)")
def assemble(plan_dir: str, output: str | None) -> None:
    """Assemble modular YAML files into a canonical plan."""
    from hangar.omd.assemble import assemble_plan

    out_path = Path(output) if output else None
    result = assemble_plan(Path(plan_dir), output=out_path)

    if result["errors"]:
        click.echo("Validation errors:", err=True)
        for err in result["errors"]:
            click.echo(f"  {err['path']}: {err['message']}", err=True)
        raise SystemExit(1)

    click.echo(f"Assembled plan v{result['version']}")
    click.echo(f"  Hash: {result['content_hash'][:16]}...")
    click.echo(f"  Output: {result['output_path']}")


@cli.command()
@click.argument("plan_path", type=click.Path(exists=True))
def validate(plan_path: str) -> None:
    """Validate an assembled plan YAML."""
    from hangar.omd.plan_schema import load_and_validate

    plan, errors = load_and_validate(Path(plan_path))
    if errors:
        click.echo("Validation errors:", err=True)
        for err in errors:
            click.echo(f"  {err['path']}: {err['message']}", err=True)
        raise SystemExit(1)

    click.echo("Plan is valid.")


@cli.command("results")
@click.argument("run_id")
@click.option("--variables", "-v", multiple=True, help="Variables to include")
@click.option("--summary/--no-summary", default=False, help="Summary only")
@click.option("--db", "db_path", type=click.Path(), default=None)
def results_cmd(run_id: str, variables: tuple, summary: bool,
                db_path: str | None) -> None:
    """Query results for a completed run."""
    from hangar.omd.results import get_results

    var_list = list(variables) if variables else None
    db = Path(db_path) if db_path else None
    result = get_results(run_id, variables=var_list, summary=summary, db_path=db)

    if "error" in result:
        click.echo(f"Error: {result['error']}", err=True)
        raise SystemExit(1)

    click.echo(json.dumps(result, indent=2, default=str))


@cli.command("export")
@click.argument("plan_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), required=True,
              help="Output Python script path")
def export_cmd(plan_path: str, output: str) -> None:
    """Export a plan to a standalone Python script."""
    from hangar.omd.export import export_plan_to_script

    export_plan_to_script(Path(plan_path), Path(output))
    click.echo(f"Exported to {output}")


@cli.command("provenance")
@click.argument("plan_id")
@click.option("--format", "fmt", type=click.Choice(["text", "html"]),
              default="text", help="Output format")
@click.option("--diff", "diff_versions", nargs=2, type=int, default=None,
              help="Compare two versions (e.g., --diff 1 2)")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output file path (required for html)")
@click.option("--db", "db_path", type=click.Path(), default=None)
def provenance_cmd(plan_id: str, fmt: str, diff_versions: tuple | None,
                   output: str | None, db_path: str | None) -> None:
    """View provenance for a plan."""
    from hangar.omd.provenance import (
        provenance_timeline,
        provenance_dag_html,
        provenance_diff,
    )

    db = Path(db_path) if db_path else None

    if diff_versions:
        result = provenance_diff(plan_id, diff_versions[0], diff_versions[1],
                                 db_path=db)
        click.echo(json.dumps(result, indent=2, default=str))
    elif fmt == "html":
        if output is None:
            output = f"{plan_id}_provenance.html"
        path = provenance_dag_html(plan_id, Path(output), db_path=db)
        click.echo(f"DAG visualization written to: {path}")
    else:
        text = provenance_timeline(plan_id, db_path=db)
        click.echo(text)


@cli.command("run")
@click.argument("plan_path", type=click.Path(exists=True))
@click.option("--mode", type=click.Choice(["analysis", "optimize"]),
              default="analysis", help="Execution mode")
@click.option("--recording-level",
              type=click.Choice(["minimal", "driver", "solver", "full"]),
              default="driver", help="Recording verbosity")
@click.option("--db", "db_path", type=click.Path(), default=None,
              help="Path to analysis database")
@click.option("--quiet", is_flag=True, default=False,
              help="Suppress convergence table output")
@click.option("--timeout", type=int, default=None,
              help="Wallclock timeout in seconds (aborts run if exceeded)")
@click.option("--stability", is_flag=True, default=False,
              help="Compute stability derivatives after analysis")
def run_cmd(plan_path: str, mode: str, recording_level: str,
            db_path: str | None, quiet: bool, timeout: int | None,
            stability: bool) -> None:
    """Materialize and run an analysis plan."""
    from hangar.omd.run import run_plan, format_convergence_table

    db = Path(db_path) if db_path else None
    result = run_plan(Path(plan_path), mode=mode,
                      recording_level=recording_level, db_path=db,
                      timeout_seconds=timeout, compute_stab=stability)

    if result["errors"]:
        click.echo("Run failed:", err=True)
        for err in result["errors"]:
            click.echo(f"  {err['path']}: {err['message']}", err=True)
        raise SystemExit(1)

    click.echo(f"Run complete: {result['run_id']}")
    click.echo(f"  Status: {result['status']}")
    summary = result.get("summary", {})
    if "CL" in summary:
        click.echo(f"  CL: {summary['CL']:.6f}")
    if "CD" in summary:
        click.echo(f"  CD: {summary['CD']:.6f}")
    if "L_over_D" in summary:
        click.echo(f"  L/D: {summary['L_over_D']:.2f}")
    rec = summary.get("recording", {})
    if rec:
        click.echo(
            f"  Recording: {rec.get('case_count', 0)} cases, "
            f"{rec.get('storage_bytes', 0) / 1024:.1f} KB"
        )

    # Print stability derivatives
    stab = summary.get("stability")
    if stab:
        sm = stab.get("static_margin")
        sm_str = f"{sm * 100:.1f}%" if sm is not None else "N/A"
        click.echo(f"  Stability: CL_alpha={stab['CL_alpha_per_rad']:.2f}/rad, "
                    f"CM_alpha={stab['CM_alpha_per_rad']:.2f}/rad, SM={sm_str}")

    # Print convergence table for optimization runs
    if mode == "optimize" and not quiet:
        from hangar.omd.db import recordings_dir
        rec_path = recordings_dir() / f"{result['run_id']}.sql"
        if rec_path.exists():
            table = format_convergence_table(rec_path)
            if table:
                click.echo()
                click.echo(table)


@cli.command("polar")
@click.argument("plan_path", type=click.Path(exists=True))
@click.option("--alpha-start", type=float, default=-5.0,
              help="Starting angle of attack in degrees")
@click.option("--alpha-end", type=float, default=15.0,
              help="Ending angle of attack in degrees")
@click.option("--num", type=int, default=21,
              help="Number of alpha points to evaluate")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output JSON file path")
def polar_cmd(plan_path: str, alpha_start: float, alpha_end: float,
              num: int, output: str | None) -> None:
    """Compute a drag polar by sweeping angle of attack."""
    from hangar.omd.polar import run_polar

    result = run_polar(
        Path(plan_path),
        alpha_start=alpha_start,
        alpha_end=alpha_end,
        num_alpha=num,
    )

    if output:
        out_path = Path(output)
        out_path.write_text(json.dumps(result, indent=2))
        click.echo(f"Polar written to {out_path}")
    else:
        best = result["best_L_over_D"]
        click.echo(f"Drag polar: {num} points, alpha {alpha_start} to {alpha_end} deg")
        click.echo(f"  Best L/D: {best['L_over_D']:.2f} at alpha={best['alpha_deg']:.1f} deg "
                    f"(CL={best['CL']:.4f}, CD={best['CD']:.6f})")

        # Print table
        click.echo()
        click.echo(f"  {'alpha':>8s}  {'CL':>10s}  {'CD':>10s}  {'L/D':>10s}")
        click.echo(f"  {'-----':>8s}  {'-----':>10s}  {'-----':>10s}  {'-----':>10s}")
        for a, cl, cd, ld in zip(result["alpha_deg"], result["CL"],
                                  result["CD"], result["L_over_D"]):
            ld_str = f"{ld:.2f}" if ld is not None else "N/A"
            click.echo(f"  {a:8.2f}  {cl:10.6f}  {cd:10.6f}  {ld_str:>10s}")


@cli.command("plot")
@click.argument("run_id", required=False, default=None)
@click.option("--type", "plot_type", default="all",
              help="Plot type to generate (or 'all')")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output directory for PNGs")
@click.option("--recorder-db", type=click.Path(exists=True), default=None,
              help="Direct path to recorder .sql/.db file")
@click.option("--surface", default=None, help="Surface name filter")
@click.option("--list-types", is_flag=True, default=False,
              help="List available plot types for this run, then exit")
def plot_cmd(run_id: str | None, plot_type: str, output: str | None,
             recorder_db: str | None, surface: str | None,
             list_types: bool) -> None:
    """Generate analysis plots from a completed run.

    Provide either a RUN_ID (resolved from omd recordings) or
    --recorder-db for a direct recorder file path.
    """
    import json as _json
    from hangar.omd.db import recordings_dir, init_analysis_db, query_entity
    from hangar.omd.plotting import generate_plots
    from hangar.omd.registry import (
        get_plot_provider, get_plot_provider_with_slots, get_all_plot_providers,
    )

    # Look up component type from DB if we have a run_id
    component_type = None
    component_types = None
    slot_providers = None
    if run_id:
        try:
            init_analysis_db()
            entity = query_entity(run_id)
            if entity and entity.get("metadata"):
                meta = _json.loads(entity["metadata"])
                component_type = meta.get("component_type")
                component_types = meta.get("component_types")
                slot_providers = meta.get("slot_providers")
        except Exception:
            pass

    # Handle --list-types
    if list_types:
        if component_types and len(component_types) > 1:
            click.echo("Plot types for composite problem:")
            for comp_id, ctype in component_types.items():
                provider = get_plot_provider(ctype)
                click.echo(f"  {comp_id} ({ctype}):")
                for name in sorted(provider.keys()):
                    click.echo(f"    {name}")
            return
        if component_type:
            provider = get_plot_provider_with_slots(component_type, slot_providers)
            click.echo(f"Plot types for {component_type}:")
        else:
            provider = get_all_plot_providers()
            click.echo("All registered plot types:")
        for name in sorted(provider.keys()):
            click.echo(f"  {name}")
        return

    # Resolve recorder path
    if recorder_db:
        rec_path = Path(recorder_db)
    elif run_id:
        rec_dir = recordings_dir()
        rec_path = rec_dir / f"{run_id}.sql"
        if not rec_path.exists():
            click.echo(f"Recorder not found: {rec_path}", err=True)
            raise SystemExit(1)
    else:
        click.echo("Provide either a RUN_ID or --recorder-db", err=True)
        raise SystemExit(1)

    # Resolve output directory
    if output:
        out_dir = Path(output)
    elif run_id:
        from hangar.omd.db import omd_data_root
        out_dir = omd_data_root() / "plots" / run_id
    else:
        out_dir = Path(".")

    # Determine plot types
    if plot_type == "all":
        types = None  # generate_plots will use registry
    else:
        types = [plot_type]

    saved = generate_plots(
        rec_path,
        plot_types=types,
        surface_name=surface,
        output_dir=out_dir,
        component_type=component_type,
        component_types=component_types,
        slot_providers=slot_providers,
    )

    if saved:
        click.echo(f"Plots saved to {out_dir}/")
        for ptype, path in saved.items():
            click.echo(f"  {path.name}")
    else:
        click.echo("No plots generated (data may not be available for requested types)")


def _omd_provenance_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve the omd provenance DAG as HTML via the SDK viewer server."""
    from hangar.omd.provenance import provenance_dag_html
    from pathlib import Path

    plan_id = (qs.get("plan_id") or [None])[0]
    if not plan_id:
        # Return a simple index listing available plan IDs
        from hangar.omd.db import init_analysis_db, get_db_path
        init_analysis_db()
        import sqlite3
        db = sqlite3.connect(str(get_db_path()))
        rows = db.execute(
            "SELECT DISTINCT plan_id FROM entities WHERE plan_id IS NOT NULL"
        ).fetchall()
        db.close()
        plan_ids = sorted({r[0] for r in rows})
        links = "".join(
            f'<li><a href="/omd-provenance?plan_id={pid}">{pid}</a></li>'
            for pid in plan_ids
        )
        html = (
            "<!DOCTYPE html><html><head><title>omd provenance</title>"
            "<style>"
            "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            "background:#0f1117;color:#e0e0e0;padding:24px;}"
            "h1{font-size:18px;font-weight:600;color:#8eb6ff;margin-bottom:16px;}"
            "ul{list-style:none;padding:0;}"
            "li{margin:6px 0;}"
            "a{color:#8eb6ff;text-decoration:none;font-size:14px;"
            "padding:6px 12px;display:inline-block;border-radius:5px;"
            "border:1px solid #2d3047;background:#1a1d27;}"
            "a:hover{background:#252839;border-color:#4a5070;}"
            "</style></head>"
            f"<body><h1>omd Provenance</h1><ul>{links}</ul></body></html>"
        )
        return 200, "text/html; charset=utf-8", html.encode()

    # Generate the DAG HTML to a temporary path, read it back
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        provenance_dag_html(plan_id, tmp_path)
        body = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    return 200, "text/html; charset=utf-8", body


def _omd_plan_diff_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Return JSON diff between a plan version and its predecessor."""
    import json as _json
    from hangar.omd.provenance import provenance_diff
    from hangar.omd.db import init_analysis_db, query_entity

    plan_id = (qs.get("plan_id") or [None])[0]
    version = (qs.get("version") or [None])[0]
    if not plan_id or not version:
        body = _json.dumps({"error": "Missing plan_id or version"})
        return 400, "application/json", body.encode()

    init_analysis_db()
    ver = int(version)
    if ver <= 1:
        # No prior version -- return the full plan content
        entity = query_entity(f"{plan_id}/v{ver}")
        if entity and entity.get("storage_ref"):
            from pathlib import Path
            import yaml
            plan_path = Path(entity["storage_ref"])
            if plan_path.exists():
                with open(plan_path) as f:
                    plan = yaml.safe_load(f)
                body = _json.dumps({"first_version": True, "plan": plan}, default=str)
                return 200, "application/json", body.encode()
        body = _json.dumps({"first_version": True, "plan": None})
        return 200, "application/json", body.encode()

    result = provenance_diff(plan_id, ver - 1, ver)
    body = _json.dumps(result, default=str)
    return 200, "application/json", body.encode()


def _omd_plots_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Generate plots for a run and return list of available filenames."""
    import json as _json
    from pathlib import Path
    from hangar.omd.db import init_analysis_db, omd_data_root, query_entity

    run_id = (qs.get("run_id") or [None])[0]
    if not run_id:
        return 400, "application/json", b'{"error":"Missing run_id"}'

    init_analysis_db()
    plots_dir = omd_data_root() / "plots" / run_id

    # Generate plots on demand if they don't exist
    if not plots_dir.exists() or not list(plots_dir.glob("*.png")):
        try:
            from hangar.omd.plotting import generate_plots
            rec_path = omd_data_root() / "recordings" / f"{run_id}.sql"
            if not rec_path.exists():
                return 404, "application/json", b'{"error":"Recording not found"}'

            # Get component type from run entity metadata
            entity = query_entity(run_id)
            component_type = None
            component_types = None
            if entity and entity.get("metadata"):
                import json
                meta = json.loads(entity["metadata"])
                component_type = meta.get("component_type")
                component_types = meta.get("component_types")

            generate_plots(
                recorder_path=rec_path,
                plot_types=None,
                surface_name="wing",
                output_dir=plots_dir,
                component_type=component_type,
                component_types=component_types,
            )
        except Exception as exc:
            body = _json.dumps({"error": str(exc)})
            return 500, "application/json", body.encode()

    # List available plot files
    files = sorted(p.name for p in plots_dir.glob("*.png"))
    body = _json.dumps({"run_id": run_id, "plots": files})
    return 200, "application/json", body.encode()


def _omd_plot_img_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve a specific plot PNG for a run."""
    from pathlib import Path
    from hangar.omd.db import omd_data_root

    run_id = (qs.get("run_id") or [None])[0]
    name = (qs.get("name") or [None])[0]
    if not run_id or not name:
        return 400, "application/json", b'{"error":"Missing run_id or name"}'

    # Sanitize name to prevent path traversal
    from pathlib import PurePosixPath
    if ".." in name or "/" in name or "\\" in name:
        return 400, "application/json", b'{"error":"Invalid name"}'

    img_path = omd_data_root() / "plots" / run_id / name
    if not img_path.exists():
        return 404, "application/json", b'{"error":"Plot not found"}'

    return 200, "image/png", img_path.read_bytes()


def _omd_n2_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve the N2 diagram HTML for a run."""
    from pathlib import Path
    from hangar.omd.db import omd_data_root

    run_id = (qs.get("run_id") or [None])[0]
    if not run_id:
        return 400, "application/json", b'{"error":"Missing run_id"}'

    n2_path = omd_data_root() / "n2" / f"{run_id}.html"
    if not n2_path.exists():
        return 404, "application/json", b'{"error":"N2 not found"}'

    return 200, "text/html; charset=utf-8", n2_path.read_bytes()


def _omd_problem_dag_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve a discipline-level analysis flow DAG."""
    import json as _json
    from hangar.omd.db import init_analysis_db, query_entity

    run_id = (qs.get("run_id") or [None])[0]
    if not run_id:
        return 400, "application/json", b'{"error":"Missing run_id"}'

    init_analysis_db()
    entity = query_entity(f"{run_id}/n2")
    if not entity or not entity.get("metadata"):
        return 404, "application/json", b'{"error":"Model structure not found"}'

    try:
        meta = _json.loads(entity["metadata"])
    except Exception:
        return 500, "application/json", b'{"error":"Invalid model data"}'

    # Use the discipline graph if available, otherwise fall back
    dgraph = meta.get("discipline_graph")
    if not dgraph:
        # Old data format -- rebuild from component type
        from hangar.omd.discipline_graph import build_discipline_graph
        ctype = meta.get("component_type", "")
        dgraph = build_discipline_graph(ctype)

    # Enrich discipline nodes with slot results and run summary
    slot_results = meta.get("slot_results", {})
    run_summary = meta.get("run_summary", {})
    _SLOT_TO_NODE = {
        "drag": "aero",
        "propulsion": "propulsion",
        "weight": "weight",
    }
    # Build available plots list by checking disk
    from hangar.omd.db import omd_data_root
    # pyCycle station/efficiency plots only valid for direct-coupled providers
    _prop_provider = slot_results.get("propulsion", {}).get("provider", "")
    _pyc_direct = _prop_provider in ("pyc/turbojet", "pyc/hbtf")
    _DISCIPLINE_PLOTS: dict[str, list] = {
        "aero": [("planform", "Planform"), ("lift", "Lift Distribution"),
                 ("twist", "Twist")],
        "struct": [("struct", "Deformation"), ("thickness", "Thickness"),
                   ("vonmises", "Von Mises")],
        "mission": [("mission_profile", "Mission Profile"),
                    ("weight_breakdown", "Weight Breakdown"),
                    ("performance_summary", "Performance Summary")],
        "geometry": [("planform", "Planform"), ("mesh_3d", "3D Mesh")],
        "perf": [("convergence", "Convergence")],
    }
    if _pyc_direct:
        _DISCIPLINE_PLOTS["propulsion"] = [
            ("station_properties", "Station Properties"),
            ("component_efficiency", "Component Efficiency"),
        ]
    existing_plots = set()
    pdir = omd_data_root() / "plots" / run_id
    if pdir.exists():
        existing_plots = {p.stem for p in pdir.glob("*.png")}

    for node in dgraph.get("nodes", []):
        props = node.get("properties", {})
        nid = node["id"]

        # Inject slot result values
        result_values = {}
        for slot_name, node_id in _SLOT_TO_NODE.items():
            if nid == node_id and slot_name in slot_results:
                sr = slot_results[slot_name]
                for k, v in sr.items():
                    if k == "provider":
                        continue
                    if isinstance(v, float):
                        result_values[k] = f"{v:.4g}"
                    else:
                        result_values[k] = str(v)

        # Mission node gets run summary values
        if nid == "mission" and run_summary:
            for k, v in run_summary.items():
                if isinstance(v, float):
                    result_values[k] = f"{v:.4g}"
                else:
                    result_values[k] = str(v)

        if result_values:
            props["result_values"] = result_values

        # Inject available plot links
        discipline_plots = _DISCIPLINE_PLOTS.get(nid, [])
        available_plots = [
            {"type": pt, "label": label}
            for pt, label in discipline_plots
            if pt in existing_plots
        ]
        if available_plots:
            props["available_plots"] = available_plots

        node["properties"] = props

    # Convert to Cytoscape elements
    cy_elements = []
    for node in dgraph.get("nodes", []):
        props_json = _json.dumps(node.get("properties", {}), default=str)
        cy_elements.append({"data": {
            "id": node["id"],
            "label": node["label"],
            "node_type": node["type"],
            "properties": props_json,
        }})

    for edge in dgraph.get("edges", []):
        props = edge.get("properties", {})
        variables = props.get("variables", [])
        label = ", ".join(variables[:3])
        if len(variables) > 3:
            label += f" +{len(variables) - 3}"
        cy_elements.append({"data": {
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge.get("relation", "provides"),
            "label": label,
            "variables": _json.dumps(variables),
        }})

    elements_json = _json.dumps(cy_elements)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Analysis Flow: {run_id}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }}
  #toolbar {{ display: flex; align-items: center; gap: 10px; padding: 8px 14px;
              background: #1a1d27; border-bottom: 1px solid #2d3047; }}
  #toolbar h1 {{ font-size: 15px; font-weight: 600; color: #8eb6ff; }}
  #toolbar .sub {{ font-size: 13px; color: #6080b0; margin-left: 4px; }}
  .btn {{ padding: 5px 12px; border-radius: 5px; border: 1px solid #3a3e54;
          background: #252839; color: #c0c8e8; cursor: pointer; font-size: 12px; }}
  .btn:hover {{ background: #2e3245; }}
  #main {{ display: flex; flex: 1; min-height: 0; }}
  #cy {{ flex: 1; }}
  #panel {{ width: 320px; background: #1a1d27; border-left: 1px solid #2d3047;
            overflow-y: auto; padding: 12px; font-size: 12px; line-height: 1.6; }}
  #panel h3 {{ font-size: 13px; color: #9cb8ff; margin: 8px 0 4px; }}
  #panel h3:first-child {{ margin-top: 0; }}
  .kv {{ margin-bottom: 3px; }}
  .kv .key {{ color: #888; font-size: 11px; }}
  .kv .val {{ color: #d0d8f0; word-break: break-word; }}
  .mono {{ font-family: monospace; font-size: 10px; color: #a0a8c0; }}
  .var-tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px;
              font-size: 10px; background: #1a2030; color: #6090b0; margin: 1px;
              font-family: monospace; }}
  .result {{ color: #50d8a0; font-family: monospace; font-weight: 600; }}
  .plot-btn {{ display: inline-block; padding: 3px 10px; border-radius: 4px;
               font-size: 11px; background: #0a2028; border: 1px solid #30a0b0;
               color: #60d0e0; margin: 2px; cursor: pointer; text-decoration: none; }}
  .plot-btn:hover {{ background: #0e2838; border-color: #50c0d0; }}
</style>
</head>
<body>
<div id="toolbar">
  <h1>Analysis Flow</h1>
  <span class="sub">{run_id}</span>
  <div style="flex:1"></div>
  <button class="btn" id="btn-fit">Fit</button>
</div>
<div id="main">
  <div id="cy"></div>
  <div id="panel">
    <p style="color:#666;font-size:12px">Click a node or edge to inspect it.</p>
  </div>
</div>
<script>
cytoscape.use(cytoscapeDagre);
var cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: {elements_json},
  style: [
    /* Discipline nodes by ID for specific coloring */
    {{ selector: 'node[node_type="discipline"]', style: {{
         'shape': 'round-rectangle', 'width': 170, 'height': 50,
         'background-color': '#0d1f3c', 'border-width': 2, 'border-color': '#4a9eff',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 11,
         'color': '#a0ccff', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '160px',
    }} }},
    {{ selector: 'node#geometry', style: {{ 'border-color': '#4a9eff', 'background-color': '#0d1f3c' }} }},
    {{ selector: 'node#aero', style: {{ 'border-color': '#40c0e0', 'background-color': '#0a1828' }} }},
    {{ selector: 'node#struct', style: {{ 'border-color': '#5080a0', 'background-color': '#0e1820' }} }},
    {{ selector: 'node#perf', style: {{ 'border-color': '#30c090', 'background-color': '#0a2018' }} }},
    /* Coupling loop node */
    {{ selector: 'node[node_type="coupling_loop"]', style: {{
         'shape': 'round-rectangle', 'width': 180, 'height': 56,
         'background-color': '#141020', 'border-width': 3, 'border-color': '#7060b0',
         'border-style': 'double',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 11,
         'color': '#b0a0d8', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '170px',
    }} }},
    {{ selector: 'node:selected', style: {{ 'border-width': 3, 'border-color': '#9ab0ff' }} }},
    /* Flow edges */
    {{ selector: 'edge[relation="provides"]', style: {{
         'width': 2.5, 'line-color': '#2a80a0', 'target-arrow-color': '#2a80a0',
         'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
         'label': 'data(label)', 'font-size': 8, 'color': '#4a7090',
         'text-rotation': 'autorotate', 'text-background-opacity': 0.7,
         'text-background-color': '#0f1117', 'text-background-padding': '2px',
    }} }},
    /* Coupling edges */
    {{ selector: 'edge[relation="couples"]', style: {{
         'width': 3, 'line-color': '#7060b0', 'target-arrow-color': '#7060b0',
         'target-arrow-shape': 'triangle',
         'source-arrow-shape': 'triangle', 'source-arrow-color': '#7060b0',
         'curve-style': 'bezier',
         'label': 'data(label)', 'font-size': 8, 'color': '#8070c0',
         'text-rotation': 'autorotate', 'text-background-opacity': 0.7,
         'text-background-color': '#0f1117', 'text-background-padding': '2px',
         'line-style': 'dashed', 'line-dash-pattern': [8, 4],
    }} }},
  ],
  layout: {{ name: 'dagre', rankDir: 'TB', nodeSep: 60, rankSep: 90 }},
}});
cy.fit(40);
document.getElementById('btn-fit').addEventListener('click', function() {{ cy.fit(40); }});

function escHtml(s) {{ return s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
var runId = '{run_id}';

/* Node click: show discipline details */
cy.on('tap', 'node', function(evt) {{
  var d = evt.target.data();
  var panel = document.getElementById('panel');
  var html = '<h3>' + escHtml(d.label.split('\\n')[0]) + '</h3>';
  html += '<div class="kv"><span class="key">type </span><span class="val">' + escHtml(d.node_type) + '</span></div>';

  if (d.properties) {{
    try {{
      var props = JSON.parse(d.properties);
      if (props.description) html += '<div class="kv"><span class="val" style="color:#8898b8">' + escHtml(props.description) + '</span></div>';
      if (props.physics) html += '<div class="kv"><span class="key">physics </span><span class="val">' + escHtml(props.physics) + '</span></div>';
      if (props.method) html += '<div class="kv"><span class="key">method </span><span class="val">' + escHtml(props.method) + '</span></div>';
      if (props.fem_type) html += '<div class="kv"><span class="key">FEM type </span><span class="val">' + escHtml(props.fem_type) + '</span></div>';
      if (props.solver) html += '<div class="kv"><span class="key">solver </span><span class="val">' + escHtml(props.solver) + '</span></div>';
      if (props.iterations != null) html += '<div class="kv"><span class="key">iterations </span><span class="val">' + escHtml(props.iterations) + '</span></div>';
      if (props.convergence_status) html += '<div class="kv"><span class="key">status </span><span class="val">' + escHtml(props.convergence_status) + '</span></div>';

      /* Input/output variable lists */
      if (props.inputs && props.inputs.length) {{
        html += '<h3>Inputs</h3>';
        for (var i = 0; i < props.inputs.length; i++) html += '<span class="var-tag">' + escHtml(props.inputs[i]) + '</span>';
      }}
      if (props.outputs && props.outputs.length) {{
        html += '<h3>Outputs</h3>';
        for (var i = 0; i < props.outputs.length; i++) html += '<span class="var-tag">' + escHtml(props.outputs[i]) + '</span>';
      }}

      /* Flight conditions for aero */
      if (props.flight_conditions) {{
        html += '<h3>Flight Conditions</h3>';
        for (var k in props.flight_conditions) {{
          html += '<div class="kv"><span class="key">' + escHtml(k) + ' </span><span class="val">' + escHtml(props.flight_conditions[k]) + '</span></div>';
        }}
      }}

      /* Material properties for struct */
      for (var mk of ['E', 'G', 'yield_stress', 'mrho']) {{
        if (props[mk] != null) html += '<div class="kv"><span class="key">' + escHtml(mk) + ' </span><span class="val">' + escHtml(props[mk]) + '</span></div>';
      }}

      /* Surfaces */
      if (props.surfaces) {{
        html += '<div class="kv"><span class="key">surfaces </span><span class="val">' + escHtml(props.surfaces.join(', ')) + '</span></div>';
      }}

      /* Coupling exchanges */
      if (props.disciplines) {{
        html += '<div class="kv"><span class="key">coupled </span><span class="val">' + escHtml(props.disciplines.join(' + ')) + '</span></div>';
      }}

      /* Result values from slot extraction */
      if (props.result_values) {{
        html += '<h3>Results</h3>';
        for (var rk in props.result_values) {{
          html += '<div class="kv"><span class="key">' + escHtml(rk) + ' </span><span class="result">' + escHtml(props.result_values[rk]) + '</span></div>';
        }}
      }}

      /* Plot links */
      if (props.available_plots && props.available_plots.length) {{
        html += '<h3>Plots</h3>';
        for (var pi = 0; pi < props.available_plots.length; pi++) {{
          var pt = props.available_plots[pi];
          html += '<a class="plot-btn" href="/omd-plot-img?run_id=' + encodeURIComponent(runId) + '&name=' + encodeURIComponent(pt.type + '.png') + '" target="_blank">' + escHtml(pt.label) + '</a>';
        }}
      }}
    }} catch(e) {{}}
  }}

  panel.innerHTML = html;
}});

/* Edge click: show variables being transferred */
cy.on('tap', 'edge', function(evt) {{
  var d = evt.target.data();
  var panel = document.getElementById('panel');
  var html = '<h3>Data Transfer</h3>';
  html += '<div class="kv"><span class="key">from </span><span class="val">' + escHtml(d.source) + '</span></div>';
  html += '<div class="kv"><span class="key">to </span><span class="val">' + escHtml(d.target) + '</span></div>';
  html += '<div class="kv"><span class="key">relation </span><span class="val">' + escHtml(d.relation) + '</span></div>';
  if (d.variables) {{
    try {{
      var vars = JSON.parse(d.variables);
      html += '<h3>Variables</h3>';
      for (var i = 0; i < vars.length; i++) html += '<span class="var-tag">' + escHtml(vars[i]) + '</span>';
    }} catch(e) {{}}
  }}
  panel.innerHTML = html;
}});

cy.on('tap', function(evt) {{
  if (evt.target === cy) {{
    document.getElementById('panel').innerHTML = '<p style="color:#666;font-size:12px">Click a node or edge to inspect it.</p>';
  }}
}});
</script>
</body>
</html>"""
    return 200, "text/html; charset=utf-8", html.encode()


def _omd_plan_detail_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve a plan detail page as a knowledge graph."""
    import json as _json
    import yaml
    from pathlib import Path
    from hangar.omd.db import init_analysis_db, query_entity, _get_conn
    from hangar.omd.plan_graph import build_plan_graph

    plan_id = (qs.get("plan_id") or [None])[0]
    version = (qs.get("version") or [None])[0]
    if not plan_id:
        return 400, "application/json", b'{"error":"Missing plan_id"}'

    init_analysis_db()
    conn = _get_conn()

    # Get all plan versions
    rows = conn.execute(
        "SELECT entity_id, version, content_hash, storage_ref, created_at "
        "FROM entities WHERE plan_id = ? AND entity_type = 'plan' "
        "ORDER BY version ASC",
        (plan_id,),
    ).fetchall()
    versions = [dict(r) for r in rows]

    if version:
        ver = int(version)
    elif versions:
        ver = versions[-1]["version"]
    else:
        return 404, "application/json", b'{"error":"Plan not found"}'

    entity = query_entity(f"{plan_id}/v{ver}")
    plan = None
    if entity and entity.get("storage_ref"):
        plan_path = Path(entity["storage_ref"])
        if plan_path.exists():
            with open(plan_path) as f:
                plan = yaml.safe_load(f)

    if not plan:
        return 404, "application/json", b'{"error":"Plan YAML not found"}'

    # Build knowledge graph via the modular builder
    graph = build_plan_graph(plan, plan_id, ver)

    # Convert to Cytoscape elements
    cy_elements = []
    for node in graph["nodes"]:
        props_json = _json.dumps(node["properties"], default=str)
        cy_elements.append({"data": {
            "id": node["id"],
            "label": node["label"],
            "node_type": node["type"],
            "properties": props_json,
        }})
    for edge in graph["edges"]:
        cy_elements.append({"data": {
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge["relation"],
        }})

    elements_json = _json.dumps(cy_elements)

    # Version timeline
    ver_html = ""
    for v in versions:
        vnum = v["version"]
        active = " style='background:#2a4a7f;border-color:#4a6fa8;color:#fff'" if vnum == ver else ""
        ver_html += (
            f'<a href="/omd-plan-detail?plan_id={plan_id}&version={vnum}" '
            f'class="btn"{active}>v{vnum}</a> '
        )

    html = _render_plan_detail_html(plan_id, ver, elements_json, ver_html)
    return 200, "text/html; charset=utf-8", html.encode()


def _render_plan_detail_html(
    plan_id: str, ver: int, elements_json: str, ver_html: str,
) -> str:
    """Render the plan detail Cytoscape.js HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Plan: {plan_id} v{ver}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }}
  #toolbar {{ display: flex; align-items: center; gap: 10px; padding: 8px 14px;
              background: #1a1d27; border-bottom: 1px solid #2d3047; flex-wrap: wrap; }}
  #toolbar h1 {{ font-size: 15px; font-weight: 600; color: #8eb6ff; }}
  #toolbar .sub {{ font-size: 13px; color: #6080b0; margin-left: 4px; }}
  .btn {{ padding: 5px 12px; border-radius: 5px; border: 1px solid #3a3e54;
          background: #252839; color: #c0c8e8; cursor: pointer; font-size: 12px; text-decoration: none; }}
  .btn:hover {{ background: #2e3245; }}
  #versions {{ display: flex; gap: 4px; align-items: center; }}
  #versions .label {{ font-size: 11px; color: #888; }}
  #main {{ display: flex; flex: 1; min-height: 0; }}
  #cy {{ flex: 1; }}
  #panel {{ width: 320px; background: #1a1d27; border-left: 1px solid #2d3047;
            overflow-y: auto; padding: 12px; font-size: 12px; line-height: 1.6; }}
  #panel h3 {{ font-size: 13px; color: #9cb8ff; margin: 8px 0 4px; }}
  #panel h3:first-child {{ margin-top: 0; }}
  .kv {{ margin-bottom: 3px; }}
  .kv .key {{ color: #888; font-size: 11px; }}
  .kv .val {{ color: #d0d8f0; word-break: break-word; }}
  .mono {{ font-family: monospace; font-size: 10px; color: #a0a8c0; }}
  .edge-tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px;
               font-size: 10px; background: #1a2030; color: #6090b0; margin: 1px; }}
</style>
</head>
<body>
<div id="toolbar">
  <h1>Plan Knowledge Graph</h1>
  <span class="sub">{plan_id} v{ver}</span>
  <div style="flex:1"></div>
  <div id="versions"><span class="label">Versions:</span> {ver_html}</div>
  <button class="btn" id="btn-fit">Fit</button>
</div>
<div id="main">
  <div id="cy"></div>
  <div id="panel">
    <p style="color:#666;font-size:12px">Click a node to inspect its properties.</p>
  </div>
</div>
<script>
cytoscape.use(cytoscapeDagre);
var cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: {elements_json},
  style: [
    {{ selector: 'node[node_type="plan"]', style: {{
         'shape': 'round-rectangle', 'width': 160, 'height': 44,
         'background-color': '#0d1f3c', 'border-width': 2, 'border-color': '#4a9eff',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 11,
         'color': '#a0ccff', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="surface"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 36,
         'background-color': '#0a1828', 'border-width': 2, 'border-color': '#70b8ff',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#90ccff', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="material"]', style: {{
         'shape': 'round-rectangle', 'width': 110, 'height': 32,
         'background-color': '#1a1028', 'border-width': 2, 'border-color': '#a080c0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#c0a0e0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="fem_model"]', style: {{
         'shape': 'round-rectangle', 'width': 100, 'height': 28,
         'background-color': '#101820', 'border-width': 2, 'border-color': '#5080a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80a0c0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="mesh"]', style: {{
         'shape': 'round-rectangle', 'width': 100, 'height': 28,
         'background-color': '#0e1828', 'border-width': 2, 'border-color': '#6090b0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80b0d0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="flight_condition"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#0a1820', 'border-width': 2, 'border-color': '#50c0f0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80d8ff', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="solver"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#101820', 'border-width': 2, 'border-color': '#5080a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80a0c0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="linear_solver"]', style: {{
         'shape': 'round-rectangle', 'width': 100, 'height': 28,
         'background-color': '#101820', 'border-width': 2, 'border-color': '#406080',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#6090b0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="objective"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 32,
         'background-color': '#0a1820', 'border-width': 2, 'border-color': '#40d0e0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#70e0f0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="design_variable"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 32,
         'background-color': '#0a1828', 'border-width': 2, 'border-color': '#50a0f0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80c0ff', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="constraint"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 32,
         'background-color': '#0a2018', 'border-width': 2, 'border-color': '#30c090',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#60e0b0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="decision"]', style: {{
         'shape': 'hexagon', 'width': 110, 'height': 55,
         'background-color': '#1a1808', 'border-width': 2, 'border-color': '#d0a030',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#e0c060', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '90px',
    }} }},
    {{ selector: 'node[node_type="requirement"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 32,
         'background-color': '#1a0a20', 'border-width': 2, 'border-color': '#a060c0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#c080e0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="aircraft_config"]', style: {{
         'shape': 'round-rectangle', 'width': 140, 'height': 40,
         'background-color': '#0a1a1a', 'border-width': 2, 'border-color': '#40b0a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#70d8c8', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="mission_profile"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#0a1820', 'border-width': 2, 'border-color': '#40b8d0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#70d0e8', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="propulsion_architecture"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 32,
         'background-color': '#1a1408', 'border-width': 2, 'border-color': '#c08830',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#e0a850', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="slot_provider"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#14081a', 'border-width': 2, 'border-color': '#9060c0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#b080e0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="engine_config"]', style: {{
         'shape': 'round-rectangle', 'width': 150, 'height': 44,
         'background-color': '#1a1008', 'border-width': 2, 'border-color': '#d09030',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#e8b050', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="engine_element"]', style: {{
         'shape': 'round-rectangle', 'width': 110, 'height': 30,
         'background-color': '#1a1408', 'border-width': 2, 'border-color': '#b8a040',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#d8c060', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="surrogate_deck"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#081a1a', 'border-width': 2, 'border-color': '#3090a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#60b8c8', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node:selected', style: {{ 'border-width': 3, 'border-color': '#9ab0ff' }} }},
    /* Edge styles by relation type */
    {{ selector: 'edge', style: {{
         'width': 2, 'line-color': '#2a3a5a', 'target-arrow-color': '#2a3a5a',
         'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
         'label': 'data(relation)', 'font-size': 8, 'color': '#3a5070',
         'text-rotation': 'autorotate',
    }} }},
    {{ selector: 'edge[relation="has_geometry"], edge[relation="has_material"], edge[relation="has_fem"]',
       style: {{ 'line-color': '#3a5a7a', 'target-arrow-color': '#3a5a7a' }} }},
    {{ selector: 'edge[relation="acts_on"]',
       style: {{ 'width': 3, 'line-color': '#50a0f0', 'target-arrow-color': '#50a0f0' }} }},
    {{ selector: 'edge[relation="bounds"]',
       style: {{ 'line-color': '#30c090', 'target-arrow-color': '#30c090' }} }},
    {{ selector: 'edge[relation="justifies"]',
       style: {{ 'line-style': 'dashed', 'line-color': '#d0a030', 'target-arrow-color': '#d0a030' }} }},
    {{ selector: 'edge[relation="traces_to"]',
       style: {{ 'line-style': 'dotted', 'line-color': '#a060c0', 'target-arrow-color': '#a060c0' }} }},
    {{ selector: 'edge[relation="flow_to"]',
       style: {{ 'width': 3, 'line-color': '#c09030', 'target-arrow-color': '#c09030' }} }},
    {{ selector: 'edge[relation="has_architecture"]',
       style: {{ 'line-color': '#c08830', 'target-arrow-color': '#c08830' }} }},
    {{ selector: 'edge[relation="provides"]',
       style: {{ 'line-color': '#9060c0', 'target-arrow-color': '#9060c0' }} }},
    {{ selector: 'edge[relation="couples"]',
       style: {{ 'line-style': 'dashed', 'line-color': '#b8a040', 'target-arrow-color': '#b8a040' }} }},
    {{ selector: 'edge[relation="configures"]',
       style: {{ 'line-style': 'dotted', 'line-color': '#40b0a0', 'target-arrow-color': '#40b0a0' }} }},
    {{ selector: 'edge[relation="generates"]',
       style: {{ 'line-color': '#3090a0', 'target-arrow-color': '#3090a0' }} }},
  ],
  layout: {{ name: 'dagre', rankDir: 'TB', nodeSep: 40, rankSep: 70, edgeSep: 10 }},
}});
cy.fit(30);
document.getElementById('btn-fit').addEventListener('click', function() {{ cy.fit(30); }});

function escHtml(s) {{ return s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

cy.on('tap', 'node', function(evt) {{
  var d = evt.target.data();
  var panel = document.getElementById('panel');
  var html = '<h3>' + escHtml(d.node_type) + '</h3>';
  html += '<div class="kv"><span class="key">id </span><span class="val mono">' + escHtml(d.id) + '</span></div>';

  /* Render all properties from the graph data */
  if (d.properties) {{
    try {{
      var props = JSON.parse(d.properties);
      for (var key in props) {{
        var val = props[key];
        if (val == null) continue;
        var display = (typeof val === 'object') ? JSON.stringify(val) : String(val);
        html += '<div class="kv"><span class="key">' + escHtml(key) + ' </span><span class="val">' + escHtml(display) + '</span></div>';
      }}
    }} catch(e) {{}}
  }}

  /* Show connected edges with relation types */
  var conns = evt.target.connectedEdges();
  if (conns.length > 0) {{
    html += '<h3>Relationships</h3>';
    conns.forEach(function(e) {{
      var ed = e.data();
      var direction = ed.source === d.id ? 'out' : 'in';
      var other = direction === 'out' ? ed.target : ed.source;
      var arrow = direction === 'out' ? '&rarr;' : '&larr;';
      html += '<div class="kv"><span class="edge-tag">' + escHtml(ed.relation) + '</span> ' + arrow + ' <span class="val mono">' + escHtml(other) + '</span></div>';
    }});
  }}

  panel.innerHTML = html;
}});

cy.on('tap', function(evt) {{
  if (evt.target === cy) {{
    document.getElementById('panel').innerHTML = '<p style="color:#666;font-size:12px">Click a node to inspect its properties.</p>';
  }}
}});
</script>
</body>
</html>"""


@cli.command("viewer")
@click.option("--port", type=int, default=7654,
              help="Port for viewer server")
@click.option("--db", "db_path", type=click.Path(), default=None,
              help="Path to SDK provenance database")
def viewer_cmd(port: int, db_path: str | None) -> None:
    """Start the provenance DAG viewer server.

    Serves the SDK provenance viewer at http://localhost:PORT/viewer
    and the omd plan/analysis provenance DAG at
    http://localhost:PORT/omd-provenance.
    """
    import os
    import signal
    import threading

    # Allow port override via env var (consistent with SDK convention)
    os.environ.setdefault("HANGAR_PROV_PORT", str(port))
    if db_path:
        os.environ["HANGAR_PROV_DB"] = db_path

    from hangar.sdk.viz.viewer_server import register_viewer_route, start_viewer_server

    register_viewer_route("/omd-provenance", _omd_provenance_handler)
    register_viewer_route("/omd-plan-diff", _omd_plan_diff_handler)
    register_viewer_route("/omd-plots", _omd_plots_handler)
    register_viewer_route("/omd-plot-img", _omd_plot_img_handler)
    register_viewer_route("/omd-n2", _omd_n2_handler)
    register_viewer_route("/omd-problem-dag", _omd_problem_dag_handler)
    register_viewer_route("/omd-plan-detail", _omd_plan_detail_handler)

    actual_port = start_viewer_server()
    if actual_port is None:
        click.echo(f"Failed to start viewer (port {port} may be in use)", err=True)
        raise SystemExit(1)

    click.echo(f"SDK viewer:       http://localhost:{actual_port}/viewer")
    click.echo(f"omd provenance:   http://localhost:{actual_port}/omd-provenance")
    click.echo("Press Ctrl+C to stop.")

    # Block until interrupted -- the server runs in a daemon thread
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()


@cli.group("plan")
def plan_group() -> None:
    """Plan authoring commands (init, add-*, set-*, review)."""


# ---------------------------------------------------------------------------
# Plan authoring helpers
# ---------------------------------------------------------------------------

def _plan_error_exit(exc: Exception) -> None:
    """Print a UserInputError and exit(1)."""
    click.echo(f"Error: {exc}", err=True)
    raise SystemExit(1)


def _prompt(value, label: str, *, cast=str, default=None):
    """Click prompt if the current value is None, else pass through."""
    if value is not None:
        return value
    if default is None:
        return click.prompt(label, type=cast)
    return click.prompt(label, type=cast, default=default)


def _require_interactive_rationale(rationale: str | None) -> str:
    """Under --interactive, the user must supply a non-empty rationale."""
    if rationale is None:
        rationale = click.prompt("Rationale", default="", show_default=False)
    if not rationale.strip():
        click.echo(
            "Error: --interactive requires a non-empty rationale.",
            err=True,
        )
        raise SystemExit(1)
    return rationale


@plan_group.command("review")
@click.argument("plan_path", type=click.Path(exists=True))
@click.option("--format", "fmt", type=click.Choice(["text", "json"]),
              default="text", help="Output format")
def plan_review_cmd(plan_path: str, fmt: str) -> None:
    """Review an assembled plan (or plan directory) for completeness.

    Emits WARN / MISSING / ERROR findings covering requirements,
    decisions, analysis_plan, rationale, and graph completeness. Exit
    code is always 0 -- the checker is advisory. Use ``--format json``
    for machine-readable output.
    """
    from hangar.omd.plan_review import (
        format_findings_json,
        format_findings_text,
        review_plan_file,
    )

    plan, findings = review_plan_file(Path(plan_path))
    if fmt == "json":
        click.echo(format_findings_json(plan, findings))
    else:
        click.echo(format_findings_text(plan, findings))


# ---------------------------------------------------------------------------
# Plan authoring subcommands (init / add-* / set-*)
# ---------------------------------------------------------------------------

@plan_group.command("init")
@click.argument("plan_dir", type=click.Path(file_okay=False))
@click.option("--id", "plan_id", default=None, help="Plan id")
@click.option("--name", default=None, help="Plan name")
@click.option("--description", default=None, help="Optional description")
@click.option("--interactive", "-i", is_flag=True)
def plan_init_cmd(
    plan_dir: str,
    plan_id: str | None,
    name: str | None,
    description: str | None,
    interactive: bool,
) -> None:
    """Scaffold a plan directory with metadata.yaml only."""
    from hangar.omd.plan_mutate import init_plan
    from hangar.sdk.errors import UserInputError

    if interactive:
        plan_id = _prompt(plan_id, "Plan id")
        name = _prompt(name, "Plan name")
        if description is None:
            description = click.prompt(
                "Description", default="", show_default=False,
            ) or None
    if not plan_id or not name:
        _plan_error_exit(
            UserInputError("--id and --name are required "
                           "(or pass --interactive)"),
        )
    try:
        init_plan(
            Path(plan_dir),
            plan_id=plan_id,
            name=name,
            description=description,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Initialized plan at {plan_dir} (id={plan_id})")


@plan_group.command("add-component")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--id", "comp_id", default=None, help="Component id")
@click.option("--type", "comp_type", default=None,
              help="Component type (e.g. oas/AerostructPoint)")
@click.option("--config-file", type=click.Path(exists=True, dir_okay=False),
              default=None, help="YAML file with the component config")
@click.option("--rationale", default=None,
              help="Why (captured to decisions.yaml)")
@click.option("--interactive", "-i", is_flag=True)
@click.option("--replace", is_flag=True)
def plan_add_component_cmd(
    plan_dir: str,
    comp_id: str | None,
    comp_type: str | None,
    config_file: str | None,
    rationale: str | None,
    interactive: bool,
    replace: bool,
) -> None:
    """Add a component to the plan.

    Non-interactive use requires --config-file. Interactive use prompts
    for a curated field list when --type is oas/AerostructPoint, and
    otherwise opens $EDITOR for paste-in YAML.
    """
    import yaml

    from hangar.omd.plan_mutate import add_component
    from hangar.sdk.errors import UserInputError

    if interactive:
        comp_id = _prompt(comp_id, "Component id")
        comp_type = _prompt(
            comp_type, "Component type", default="oas/AerostructPoint",
        )
        rationale = _require_interactive_rationale(rationale)
        config = _prompt_component_config(comp_type, config_file)
    else:
        if not comp_id or not comp_type:
            _plan_error_exit(
                UserInputError(
                    "--id and --type are required (or pass --interactive)"
                )
            )
        if not config_file:
            _plan_error_exit(
                UserInputError(
                    "--config-file is required in non-interactive mode"
                )
            )
        config = yaml.safe_load(Path(config_file).read_text())
        if not isinstance(config, dict):
            _plan_error_exit(
                UserInputError("config-file must contain a YAML mapping")
            )

    try:
        add_component(
            Path(plan_dir),
            comp_id=comp_id,
            comp_type=comp_type,
            config=config,
            rationale=rationale,
            replace=replace,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Added component {comp_id} ({comp_type})")


def _prompt_component_config(comp_type: str, config_file: str | None) -> dict:
    """Return a component config dict for interactive add-component."""
    import yaml

    if config_file:
        data = yaml.safe_load(Path(config_file).read_text())
        if isinstance(data, dict):
            return data
    if comp_type == "oas/AerostructPoint":
        surface_name = click.prompt("Surface name", default="wing")
        wing_type = click.prompt(
            "wing_type", default="rect",
            type=click.Choice(["rect", "CRM"], case_sensitive=False),
        )
        num_x = click.prompt("num_x", type=int, default=2)
        num_y = click.prompt("num_y (odd integer)", type=int, default=7)
        span = click.prompt("span", type=float, default=10.0)
        root_chord = click.prompt("root_chord", type=float, default=1.0)
        symmetry = click.confirm("symmetry?", default=True)
        fem_model_type = click.prompt(
            "fem_model_type", default="tube",
            type=click.Choice(["tube", "wingbox"], case_sensitive=False),
        )
        E = click.prompt("E (Young's modulus, Pa)", type=float, default=7.0e10)
        G = click.prompt("G (shear modulus, Pa)", type=float, default=3.0e10)
        yield_stress = click.prompt(
            "yield_stress (Pa)", type=float, default=5.0e8,
        )
        mrho = click.prompt(
            "mrho (material density, kg/m^3)", type=float, default=3000.0,
        )
        return {
            "surfaces": [{
                "name": surface_name,
                "wing_type": wing_type,
                "num_x": num_x,
                "num_y": num_y,
                "span": span,
                "root_chord": root_chord,
                "symmetry": symmetry,
                "fem_model_type": fem_model_type,
                "E": E,
                "G": G,
                "yield_stress": yield_stress,
                "mrho": mrho,
            }],
        }
    # Unknown type: fall back to edit-in-editor
    template = "# Paste the component config YAML below\n"
    edited = click.edit(template)
    if not edited:
        raise click.ClickException("No config provided")
    data = yaml.safe_load(edited)
    if not isinstance(data, dict):
        raise click.ClickException("Edited config must be a YAML mapping")
    return data


@plan_group.command("add-requirement")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--id", "req_id", default=None)
@click.option("--text", default=None)
@click.option("--type", "req_type", default=None,
              help="performance/structural/stability/constraint/objective")
@click.option("--priority", default=None,
              type=click.Choice(["primary", "secondary", "goal"]))
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
@click.option("--replace", is_flag=True)
def plan_add_requirement_cmd(
    plan_dir: str,
    req_id: str | None,
    text: str | None,
    req_type: str | None,
    priority: str | None,
    rationale: str | None,
    interactive: bool,
    replace: bool,
) -> None:
    """Append a requirement to requirements.yaml."""
    from hangar.omd.plan_mutate import add_requirement
    from hangar.sdk.errors import UserInputError

    if interactive:
        req_id = _prompt(req_id, "Requirement id (e.g. R1)")
        text = _prompt(text, "Text")
        if req_type is None:
            req_type = click.prompt(
                "Type",
                default="",
                show_default=False,
            ) or None
        if priority is None:
            priority = click.prompt(
                "Priority",
                default="",
                show_default=False,
            ) or None
        rationale = _require_interactive_rationale(rationale)
    if not req_id or not text:
        _plan_error_exit(
            UserInputError(
                "--id and --text are required (or pass --interactive)"
            )
        )

    req: dict = {"id": req_id, "text": text}
    if req_type:
        req["type"] = req_type
    if priority:
        req["priority"] = priority
    try:
        add_requirement(
            Path(plan_dir), req=req, rationale=rationale, replace=replace,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Added requirement {req_id}")


@plan_group.command("add-dv")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--name", default=None, help="DV short or prefixed name")
@click.option("--lower", type=float, default=None)
@click.option("--upper", type=float, default=None)
@click.option("--scaler", type=float, default=None)
@click.option("--units", default=None)
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
@click.option("--replace", is_flag=True)
def plan_add_dv_cmd(
    plan_dir: str,
    name: str | None,
    lower: float | None,
    upper: float | None,
    scaler: float | None,
    units: str | None,
    rationale: str | None,
    interactive: bool,
    replace: bool,
) -> None:
    """Add a design variable to optimization.yaml."""
    from hangar.omd.plan_mutate import _collect_var_paths, add_dv
    from hangar.sdk.errors import UserInputError

    if interactive:
        allowed = sorted(_collect_var_paths(Path(plan_dir)))
        if allowed:
            click.echo(f"Allowed DV short names: {', '.join(allowed)}")
        else:
            click.echo(
                "No components declared yet — "
                "DV names will not be strictly validated.",
            )
        name = _prompt(name, "DV name")
        lower = _prompt(lower, "Lower bound", cast=float)
        upper = _prompt(upper, "Upper bound", cast=float)
        rationale = _require_interactive_rationale(rationale)
    if name is None or lower is None or upper is None:
        _plan_error_exit(
            UserInputError(
                "--name, --lower, --upper are required "
                "(or pass --interactive)"
            )
        )
    try:
        add_dv(
            Path(plan_dir),
            name=name, lower=lower, upper=upper,
            scaler=scaler, units=units,
            rationale=rationale, replace=replace,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Added DV {name}: [{lower}, {upper}]")


@plan_group.command("set-objective")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--name", default=None)
@click.option("--scaler", type=float, default=None)
@click.option("--units", default=None)
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_set_objective_cmd(
    plan_dir: str,
    name: str | None,
    scaler: float | None,
    units: str | None,
    rationale: str | None,
    interactive: bool,
) -> None:
    """Set the optimization objective."""
    from hangar.omd.plan_mutate import _collect_var_paths, set_objective
    from hangar.sdk.errors import UserInputError

    if interactive:
        allowed = sorted(_collect_var_paths(Path(plan_dir)))
        if allowed:
            click.echo(f"Allowed objective names: {', '.join(allowed)}")
        else:
            click.echo(
                "No components declared yet — "
                "objective name will not be strictly validated.",
            )
        name = _prompt(name, "Objective name")
        if scaler is None:
            scaler_input = click.prompt(
                "Scaler (blank for none)",
                default="", show_default=False,
            )
            scaler = float(scaler_input) if scaler_input.strip() else None
        rationale = _require_interactive_rationale(rationale)
    if name is None:
        _plan_error_exit(
            UserInputError("--name is required (or pass --interactive)")
        )
    try:
        set_objective(
            Path(plan_dir),
            name=name, scaler=scaler, units=units, rationale=rationale,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Objective: {name}")


@plan_group.command("add-decision")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--id", "dec_id", default=None, help="Decision id (auto if omitted)")
@click.option("--stage", default=None,
              help="One of the recommended stages; off-list emits a warning")
@click.option("--decision", "decision_text", default=None,
              help="What was decided")
@click.option("--rationale", default=None, help="Why")
@click.option("--element-path", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_add_decision_cmd(
    plan_dir: str,
    dec_id: str | None,
    stage: str | None,
    decision_text: str | None,
    rationale: str | None,
    element_path: str | None,
    interactive: bool,
) -> None:
    """Append a hand-authored decision entry."""
    from hangar.omd.plan_mutate import add_decision
    from hangar.omd.plan_schema import RECOMMENDED_DECISION_STAGES
    from hangar.sdk.errors import UserInputError

    if interactive:
        click.echo(
            "Recommended stages: " + ", ".join(RECOMMENDED_DECISION_STAGES)
        )
        stage = _prompt(stage, "Stage")
        decision_text = _prompt(decision_text, "Decision")
        rationale = _require_interactive_rationale(rationale)
        if element_path is None:
            element_path = click.prompt(
                "Element path (blank for none)",
                default="", show_default=False,
            ) or None
    if not stage or not decision_text:
        _plan_error_exit(
            UserInputError(
                "--stage and --decision are required (or pass --interactive)"
            )
        )
    if stage not in RECOMMENDED_DECISION_STAGES:
        click.echo(
            f"Warning: stage '{stage}' is not in RECOMMENDED_DECISION_STAGES "
            "(plan review will flag it).",
            err=True,
        )

    entry: dict = {"stage": stage, "decision": decision_text}
    if dec_id:
        entry["id"] = dec_id
    if rationale:
        entry["rationale"] = rationale
    if element_path:
        entry["element_path"] = element_path

    try:
        written = add_decision(Path(plan_dir), decision=entry)
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Added decision {written.get('id')}")


@plan_group.command("set-operating-point")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--mach", type=float, default=None, help="Mach_number")
@click.option("--alpha", type=float, default=None, help="Angle of attack (deg)")
@click.option("--velocity", type=float, default=None, help="Velocity (m/s)")
@click.option("--altitude", type=float, default=None, help="Altitude (m or ft per --units)")
@click.option("--re", "reynolds", type=float, default=None, help="Reynolds number")
@click.option("--rho", type=float, default=None, help="Density (kg/m^3)")
@click.option("--units", type=click.Choice(["SI", "imperial"]),
              default="SI", help="Altitude units only: m (SI) or ft (imperial)")
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_set_operating_point_cmd(
    plan_dir: str,
    mach: float | None,
    alpha: float | None,
    velocity: float | None,
    altitude: float | None,
    reynolds: float | None,
    rho: float | None,
    units: str,
    rationale: str | None,
    interactive: bool,
) -> None:
    """Merge operating-point fields into operating_points.yaml."""
    from hangar.omd.plan_mutate import set_operating_point
    from hangar.sdk.errors import UserInputError

    if interactive:
        if mach is None:
            mach_in = click.prompt(
                "Mach_number", default="", show_default=False,
            )
            mach = float(mach_in) if mach_in.strip() else None
        if alpha is None:
            alpha_in = click.prompt(
                "alpha (deg)", default="", show_default=False,
            )
            alpha = float(alpha_in) if alpha_in.strip() else None
        if velocity is None:
            v_in = click.prompt(
                "velocity (m/s, blank for none)",
                default="", show_default=False,
            )
            velocity = float(v_in) if v_in.strip() else None
        if altitude is None:
            alt_in = click.prompt(
                f"altitude ({'m' if units == 'SI' else 'ft'}, blank for none)",
                default="", show_default=False,
            )
            altitude = float(alt_in) if alt_in.strip() else None
        rationale = _require_interactive_rationale(rationale)

    fields: dict = {}
    if mach is not None:
        fields["Mach_number"] = mach
    if alpha is not None:
        fields["alpha"] = alpha
    if velocity is not None:
        fields["velocity"] = velocity
    if altitude is not None:
        alt_units = "m" if units == "SI" else "ft"
        fields["altitude"] = {"value": altitude, "units": alt_units}
    if reynolds is not None:
        fields["re"] = reynolds
    if rho is not None:
        fields["rho"] = rho

    if not fields:
        _plan_error_exit(
            UserInputError("no fields provided (pass at least one of "
                           "--mach, --alpha, --velocity, --altitude, "
                           "--re, --rho)")
        )
    try:
        set_operating_point(
            Path(plan_dir), fields=fields, rationale=rationale,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Updated operating point: {sorted(fields)}")


@plan_group.command("set-solver")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--nonlinear", default=None, help="e.g. NewtonSolver")
@click.option("--linear", default=None, help="e.g. DirectSolver")
@click.option("--nonlinear-maxiter", type=int, default=None)
@click.option("--nonlinear-atol", type=float, default=None)
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_set_solver_cmd(
    plan_dir: str,
    nonlinear: str | None,
    linear: str | None,
    nonlinear_maxiter: int | None,
    nonlinear_atol: float | None,
    rationale: str | None,
    interactive: bool,
) -> None:
    """Set the nonlinear / linear solver types for solvers.yaml."""
    from hangar.omd.plan_mutate import set_solver
    from hangar.sdk.errors import UserInputError

    if interactive:
        nonlinear = _prompt(
            nonlinear, "Nonlinear solver", default="NewtonSolver",
        ) or None
        linear = _prompt(linear, "Linear solver", default="DirectSolver") or None
        rationale = _require_interactive_rationale(rationale)

    nl_options: dict = {}
    if nonlinear_maxiter is not None:
        nl_options["maxiter"] = nonlinear_maxiter
    if nonlinear_atol is not None:
        nl_options["atol"] = nonlinear_atol

    try:
        set_solver(
            Path(plan_dir),
            nonlinear=nonlinear,
            linear=linear,
            nonlinear_options=nl_options or None,
            rationale=rationale,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    parts = []
    if nonlinear:
        parts.append(f"nonlinear={nonlinear}")
    if linear:
        parts.append(f"linear={linear}")
    click.echo("Solvers: " + ", ".join(parts))


@plan_group.command("set-analysis-strategy")
@click.argument("plan_dir", type=click.Path(exists=True, file_okay=False))
@click.option("--phases", type=int, default=None,
              help="Number of phases to scaffold")
@click.option("--phase-id-prefix", default="p",
              help="Prefix for phase ids (default: p)")
@click.option("--rationale", default=None)
@click.option("--interactive", "-i", is_flag=True)
def plan_set_analysis_strategy_cmd(
    plan_dir: str,
    phases: int | None,
    phase_id_prefix: str,
    rationale: str | None,
    interactive: bool,
) -> None:
    """Scaffold analysis_plan.yaml with N empty phases (user fills in)."""
    from hangar.omd.plan_mutate import set_analysis_strategy
    from hangar.sdk.errors import UserInputError

    if interactive:
        phases = _prompt(phases, "Number of phases", cast=int, default=2)
        rationale = _require_interactive_rationale(rationale)
    if phases is None:
        _plan_error_exit(
            UserInputError("--phases is required (or pass --interactive)")
        )
    try:
        set_analysis_strategy(
            Path(plan_dir),
            phases=phases,
            phase_id_prefix=phase_id_prefix,
            rationale=rationale,
        )
    except UserInputError as exc:
        _plan_error_exit(exc)
    click.echo(f"Scaffolded {phases} phases "
               f"({phase_id_prefix}1..{phase_id_prefix}{phases})")


def main() -> None:
    """Entry point for omd-cli."""
    cli()
