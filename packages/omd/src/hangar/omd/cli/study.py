"""omd-cli study subcommands.

Thin wrappers over the tool-independent study core in
:mod:`hangar.sdk.study`; importing :mod:`hangar.omd.study_runner` here is
what makes the ``omd`` runner available. The intended workflow is
review-first and incremental:

.. code-block:: bash

    omd-cli study validate study.yaml
    omd-cli study review study.yaml          # case count + compute estimate
    omd-cli study generate study.yaml        # write case plans, no compute
    omd-cli study run study.yaml --max-cases 4   # pilot batch
    omd-cli study status <study_id>          # progress so far
    omd-cli study run study.yaml --yes       # commit to the rest
    omd-cli study results <study_id>         # spreadsheet-style case table
    omd-cli study plot <study_id>            # 2-axis trade-grid figure
"""

from __future__ import annotations

import json
from pathlib import Path

import click

from hangar.omd.cli import cli


@cli.group("study")
def study_group() -> None:
    """Author, review, and run multi-case studies."""


def _load_or_die(study_path: str) -> dict:
    from hangar.sdk.study import load_study

    spec, errors = load_study(Path(study_path))
    if errors:
        click.echo("Study validation errors:", err=True)
        for err in errors:
            click.echo(f"  {err['path']}: {err['message']}", err=True)
        raise SystemExit(1)
    return spec


@study_group.command("validate")
@click.argument("study_path", type=click.Path(exists=True))
def study_validate(study_path: str) -> None:
    """Validate a study YAML (schema + expansion preflight)."""
    from hangar.sdk.study import expand_cases

    spec = _load_or_die(study_path)
    try:
        cases = expand_cases(spec)
    except ValueError as exc:
        click.echo(f"Expansion error: {exc}", err=True)
        raise SystemExit(1)
    click.echo(f"Study is valid: {len(cases)} cases.")


@study_group.command("review")
@click.argument("study_path", type=click.Path(exists=True))
@click.option("--json", "as_json", is_flag=True, default=False,
              help="Emit the raw review payload as JSON.")
def study_review(study_path: str, as_json: bool) -> None:
    """Review case count, compute, and wall-time estimate before running."""
    from hangar.sdk.study import StudyStore, expand_cases, review_study

    spec = _load_or_die(study_path)
    try:
        cases = expand_cases(spec)
    except ValueError as exc:
        click.echo(f"Expansion error: {exc}", err=True)
        raise SystemExit(1)

    state = None
    try:
        state = StudyStore(spec["metadata"]["id"]).load_state()
    except Exception:
        pass
    rev = review_study(spec, cases, state=state)

    if as_json:
        click.echo(json.dumps(rev, indent=2, default=str))
        return

    click.echo(f"Study: {rev['study_id']}")
    click.echo(f"  Cases: {rev['n_cases']} total, {rev['n_pending']} pending, "
               f"{rev['n_done']} done")
    click.echo(f"  Runners: {rev['by_runner']}")
    if rev["matrix_axes"]:
        for axes in rev["matrix_axes"]:
            dims = " x ".join(f"{k}({v})" for k, v in axes.items())
            click.echo(f"  Matrix: {dims}")
    if rev["n_presets"] > 1:
        click.echo(f"  Multistart: {rev['n_presets']} presets -> "
                   f"{rev['n_runs_pending']} runs pending")
    est = rev["est_wall_human"]
    if est:
        click.echo(f"  Estimated wall time: {est} on {rev['workers']} worker(s) "
                   f"(per-case {rev['est_case_seconds']:.0f} s, {rev['est_source']})")
    for warning in rev["warnings"]:
        click.echo(f"  WARNING: {warning}")
    click.echo("  First cases:")
    for c in rev["case_preview"]:
        click.echo(f"    {c['case_id']}  [{c['source']}/{c['runner']}]  {c['params']}")


@study_group.command("generate")
@click.argument("study_path", type=click.Path(exists=True))
def study_generate(study_path: str) -> None:
    """Write every case's plan artifact for review (no compute)."""
    import hangar.omd.study_runner  # noqa: F401  (registers the omd runner)
    from hangar.sdk.study.orchestrate import generate_study

    try:
        result = generate_study(Path(study_path))
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    click.echo(f"Generated {len(result['generated'])} case plan(s) under "
               f"{result['study_dir']}/cases/")
    for item in result["generated"]:
        click.echo(f"  {item['case_id']}: {item['artifact']}")
    for item in result["skipped"]:
        click.echo(f"  skipped {item['case_id']} ({item['reason']})")


@study_group.command("run")
@click.argument("study_path", type=click.Path(exists=True))
@click.option("--max-cases", type=int, default=None,
              help="Run at most N pending cases, then stop (pilot batch).")
@click.option("--workers", type=int, default=None,
              help="Worker processes (default: execution.workers).")
@click.option("--yes", "confirm", is_flag=True, default=False,
              help="Confirm running more cases than the review threshold.")
@click.option("--retry-failed", is_flag=True, default=False,
              help="Also re-run previously failed/errored cases.")
def study_run(study_path: str, max_cases: int | None, workers: int | None,
              confirm: bool, retry_failed: bool) -> None:
    """Run a study (or its next batch). Resumes automatically."""
    import hangar.omd.study_runner  # noqa: F401  (registers the omd runner)
    from hangar.sdk.study import StudyGuardError, run_study

    def _progress(done: dict, summary: dict) -> None:
        result = done["result"]
        ok = result.get("status") in ("converged", "completed")
        click.echo(f"  [{summary['done']}/{summary['total']}] "
                   f"{done['case_id']}  "
                   f"{'OK  ' if ok else 'FAIL'} "
                   f"wall={done['wall_time_s']:.1f}s"
                   + (f"  error={result.get('error')}" if not ok else ""))

    try:
        result = run_study(
            Path(study_path),
            max_cases=max_cases,
            workers=workers,
            confirm=confirm,
            retry_failed=retry_failed,
            on_case_done=_progress,
        )
    except StudyGuardError as exc:
        rev = exc.review
        click.echo(f"Refusing to run: {exc}", err=True)
        click.echo(f"  Pending: {rev['n_pending']} cases, est wall "
                   f"{rev['est_wall_human'] or 'unknown'}", err=True)
        click.echo("  Use 'omd-cli study review' to inspect, then re-run "
                   "with --yes or --max-cases N.", err=True)
        raise SystemExit(2)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)

    batch = result["batch"]
    click.echo(f"Batch done: {batch['succeeded']}/{batch['ran']} succeeded, "
               f"{result['remaining']} case(s) remaining.")
    click.echo(f"  Case table: {result['cases_csv']}")
    if result["remaining"]:
        click.echo("  Review the results, then continue with "
                   "'omd-cli study run' (resumes automatically).")


@study_group.command("status")
@click.argument("study_id")
def study_status(study_id: str) -> None:
    """Progress counts for a study."""
    from hangar.sdk.study import StudyStore

    store = StudyStore(study_id)
    if not store.state_path.exists():
        click.echo(f"No state for study {study_id!r} under {store.dir}", err=True)
        raise SystemExit(1)
    summary = store.status_summary()
    click.echo(f"Study {study_id} (spec v{summary['version']}): "
               f"{summary['done']}/{summary['total']} done")
    for status, count in sorted(summary["counts"].items()):
        click.echo(f"  {status}: {count}")
    if summary["mean_case_wall_s"]:
        click.echo(f"  Mean case wall time: {summary['mean_case_wall_s']:.1f} s")


@study_group.command("results")
@click.argument("study_id")
@click.option("--csv", "as_csv", is_flag=True, default=False,
              help="Print the cases.csv path instead of the table.")
@click.option("--failed", "only_failed", is_flag=True, default=False,
              help="Show only failed/errored cases.")
def study_results(study_id: str, as_csv: bool, only_failed: bool) -> None:
    """Spreadsheet-style case table for a study."""
    from hangar.sdk.study import StudyStore

    store = StudyStore(study_id)
    if not store.state_path.exists():
        click.echo(f"No state for study {study_id!r} under {store.dir}", err=True)
        raise SystemExit(1)
    state = store.load_state()
    path = store.export_csv(state)
    if as_csv:
        click.echo(str(path))
        return

    import csv as _csv

    with open(path) as f:
        rows = list(_csv.reader(f))
    if not rows:
        click.echo("No cases.")
        return
    header, body = rows[0], rows[1:]
    if only_failed:
        status_idx = header.index("status")
        body = [r for r in body if r[status_idx] not in ("converged", "completed")]
    widths = [max(len(h), *(len(r[i]) for r in body)) if body else len(h)
              for i, h in enumerate(header)]
    click.echo("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    for row in body:
        click.echo("  ".join(c.ljust(w) for c, w in zip(row, widths)))


@study_group.command("plot")
@click.argument("study_id")
@click.option("--style", type=click.Choice(["paper", "contour"]),
              default="paper", show_default=True,
              help="paper: pcolormesh per-cell rectangles; contour: smooth "
                   "contourf.")
@click.option("--type", "plot_types", multiple=True,
              help="Provider plot name(s) to render (default: all). Repeatable.")
@click.option("--out", "out_dir", type=click.Path(), default=None,
              help="Output directory (default: studies/<id>/plots).")
def study_plot(study_id: str, style: str, plot_types: tuple[str, ...],
               out_dir: str | None) -> None:
    """Render a study's 2-axis trade-grid figure(s) from its cases.csv.

    Requires a study with exactly two numeric axes. OCP mission studies get
    the Brelje Fig 5/6 four-panel layout; other component types fall back to
    one panel per numeric output column.
    """
    import hangar.omd.study_runner  # noqa: F401  (registers the omd runner)
    from hangar.omd.study_plots import plot_study

    try:
        result = plot_study(
            study_id,
            plot_types=list(plot_types) or None,
            style=style,
            out_dir=Path(out_dir) if out_dir else None,
        )
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)

    if not result["saved"]:
        click.echo("No plots produced (see warnings above).", err=True)
        raise SystemExit(1)
    click.echo(f"Study {study_id} ({result['component_type'] or 'generic'}), "
               f"axes {result['axes'][0]} x {result['axes'][1]}:")
    for name, path in result["saved"].items():
        click.echo(f"  {name}: {path}")
