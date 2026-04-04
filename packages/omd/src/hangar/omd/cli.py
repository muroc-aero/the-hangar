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
@click.option("--type", "plot_type",
              type=click.Choice(["all", "planform", "lift", "struct",
                                 "convergence", "twist", "thickness"]),
              default="all", help="Plot type(s) to generate")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output directory for PNGs")
@click.option("--recorder-db", type=click.Path(exists=True), default=None,
              help="Direct path to recorder .sql/.db file")
@click.option("--surface", default=None, help="Surface name filter")
def plot_cmd(run_id: str | None, plot_type: str, output: str | None,
             recorder_db: str | None, surface: str | None) -> None:
    """Generate analysis plots from a completed run.

    Provide either a RUN_ID (resolved from omd recordings) or
    --recorder-db for a direct recorder file path.
    """
    from hangar.omd.db import recordings_dir
    from hangar.omd.plotting import generate_plots, PLOT_TYPES

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
        types = list(PLOT_TYPES.keys())
    else:
        types = [plot_type]

    saved = generate_plots(
        rec_path,
        plot_types=types,
        surface_name=surface,
        output_dir=out_dir,
    )

    if saved:
        click.echo(f"Plots saved to {out_dir}/")
        for ptype, path in saved.items():
            click.echo(f"  {path.name}")
    else:
        click.echo("No plots generated (data may not be available for requested types)")


def main() -> None:
    """Entry point for omd-cli."""
    cli()
