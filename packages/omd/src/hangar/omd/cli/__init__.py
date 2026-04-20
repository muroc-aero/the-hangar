"""Click CLI for hangar-omd.

Provides subcommands: assemble, validate, run, results, export, provenance,
polar, plot, viewer, plan.
"""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group()
def cli() -> None:
    """omd -- MDAO analysis plan server."""


# Viewer route handlers are defined in server_routes; imported here so the
# viewer_cmd below can reference them and so external callers (deploy scripts)
# can still `from hangar.omd.cli import _omd_problem_dag_handler`.
from hangar.omd.cli.server_routes import (  # noqa: E402
    _omd_provenance_handler,
    _omd_plan_diff_handler,
    _omd_plots_handler,
    _omd_plot_img_handler,
    _omd_n2_handler,
    _omd_problem_dag_handler,
    _omd_plan_detail_handler,
)


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
@click.option("--no-semantic", is_flag=True, default=False,
              help="Skip semantic checks (DV/constraint name resolution).")
def validate(plan_path: str, no_semantic: bool) -> None:
    """Validate an assembled plan YAML (schema + var-path resolution)."""
    from hangar.omd.plan_schema import load_and_validate
    from hangar.omd.plan_validate import validate_plan_semantic
    from hangar.omd.registry import list_factories

    plan, errors = load_and_validate(Path(plan_path))
    if errors:
        click.echo("Schema validation errors:", err=True)
        for err in errors:
            click.echo(f"  {err['path']}: {err['message']}", err=True)
        raise SystemExit(1)

    if not no_semantic and plan is not None:
        registry_types = set(list_factories())
        findings = validate_plan_semantic(plan, registry_types=registry_types)
        if findings:
            click.echo("Semantic validation errors:", err=True)
            for f in findings:
                hint = f" (did you mean: {', '.join(f.suggestions)}?)" if f.suggestions else ""
                click.echo(f"  {f.path}: {f.message}{hint}", err=True)
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
    from hangar.omd.plan_schema import load_and_validate
    from hangar.omd.plan_validate import validate_plan_semantic
    from hangar.omd.registry import list_factories

    # Pre-flight semantic check so typos fail fast with a suggestion
    plan, _errs = load_and_validate(Path(plan_path))
    if plan is not None:
        findings = validate_plan_semantic(plan, registry_types=set(list_factories()))
        if findings:
            click.echo("Plan validation errors (run aborted):", err=True)
            for f in findings:
                hint = f" (did you mean: {', '.join(f.suggestions)}?)" if f.suggestions else ""
                click.echo(f"  {f.path}: {f.message}{hint}", err=True)
            raise SystemExit(1)

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




# Import plan subcommands so their @plan_group.command decorators register.
from hangar.omd.cli import plan as _plan  # noqa: E402, F401
# Import summary subcommand so its @cli.command decorator registers.
from hangar.omd.cli import summary as _summary  # noqa: E402, F401


def main() -> None:
    """Entry point for omd-cli."""
    cli()
