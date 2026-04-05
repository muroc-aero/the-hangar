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
def run_cmd(plan_path: str, mode: str, recording_level: str,
            db_path: str | None, quiet: bool) -> None:
    """Materialize and run an analysis plan."""
    from hangar.omd.run import run_plan, format_convergence_table

    db = Path(db_path) if db_path else None
    result = run_plan(Path(plan_path), mode=mode,
                      recording_level=recording_level, db_path=db)

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

    # Print convergence table for optimization runs
    if mode == "optimize" and not quiet:
        from hangar.omd.db import recordings_dir
        rec_path = recordings_dir() / f"{result['run_id']}.sql"
        if rec_path.exists():
            table = format_convergence_table(rec_path)
            if table:
                click.echo()
                click.echo(table)


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
    from hangar.omd.registry import get_plot_provider, get_all_plot_providers

    # Look up component type from DB if we have a run_id
    component_type = None
    if run_id:
        try:
            init_analysis_db()
            entity = query_entity(run_id)
            if entity and entity.get("metadata"):
                meta = _json.loads(entity["metadata"])
                component_type = meta.get("component_type")
        except Exception:
            pass

    # Handle --list-types
    if list_types:
        if component_type:
            provider = get_plot_provider(component_type)
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
            if entity and entity.get("metadata"):
                import json
                meta = json.loads(entity["metadata"])
                component_type = meta.get("component_type")

            generate_plots(
                recorder_path=rec_path,
                plot_types=None,
                surface_name="wing",
                output_dir=plots_dir,
                component_type=component_type,
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


def main() -> None:
    """Entry point for omd-cli."""
    cli()
