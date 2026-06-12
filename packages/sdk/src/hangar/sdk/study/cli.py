"""hangar-study: standalone CLI for the tool-independent study layer.

Command-for-command parity with ``omd-cli study`` but with no omd
dependency: runners load lazily through the ``hangar.study_runners``
entry-point group, so any installed tool package (oas, ocp, pyc, omd)
contributes its runner automatically. The intended workflow is
review-first and incremental:

.. code-block:: bash

    hangar-study validate study.yaml
    hangar-study review study.yaml           # case count + compute estimate
    hangar-study generate study.yaml         # write case artifacts, no compute
    hangar-study run study.yaml --max-cases 4    # pilot batch
    hangar-study status <study_id>           # progress so far
    hangar-study run study.yaml --yes        # commit to the rest
    hangar-study results <study_id>          # spreadsheet-style case table
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _die(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


def _load_or_die(study_path: str) -> dict:
    from hangar.sdk.study import load_study

    path = Path(study_path)
    if not path.exists():
        _die(f"Error: study file not found: {study_path}")
    spec, errors = load_study(path)
    if errors:
        print("Study validation errors:", file=sys.stderr)
        for err in errors:
            print(f"  {err['path']}: {err['message']}", file=sys.stderr)
        raise SystemExit(1)
    return spec


def _expand_or_die(spec: dict) -> list:
    from hangar.sdk.study import expand_cases

    try:
        return expand_cases(spec)
    except ValueError as exc:
        _die(f"Expansion error: {exc}")


def cmd_validate(args: argparse.Namespace) -> None:
    spec = _load_or_die(args.study_path)
    cases = _expand_or_die(spec)
    print(f"Study is valid: {len(cases)} cases.")


def cmd_review(args: argparse.Namespace) -> None:
    from hangar.sdk.study import StudyStore, review_study

    spec = _load_or_die(args.study_path)
    cases = _expand_or_die(spec)

    state = None
    try:
        state = StudyStore(spec["metadata"]["id"]).load_state()
    except Exception:
        pass
    rev = review_study(spec, cases, state=state)

    if args.as_json:
        print(json.dumps(rev, indent=2, default=str))
        return

    print(f"Study: {rev['study_id']}")
    print(f"  Cases: {rev['n_cases']} total, {rev['n_pending']} pending, "
          f"{rev['n_done']} done")
    print(f"  Runners: {rev['by_runner']}")
    for axes in rev["matrix_axes"]:
        dims = " x ".join(f"{k}({v})" for k, v in axes.items())
        print(f"  Matrix: {dims}")
    if rev["n_presets"] > 1:
        print(f"  Multistart: {rev['n_presets']} presets -> "
              f"{rev['n_runs_pending']} runs pending")
    if rev["est_wall_human"]:
        print(f"  Estimated wall time: {rev['est_wall_human']} on "
              f"{rev['workers']} worker(s) (per-case "
              f"{rev['est_case_seconds']:.0f} s, {rev['est_source']})")
    for warning in rev["warnings"]:
        print(f"  WARNING: {warning}")
    print("  First cases:")
    for c in rev["case_preview"]:
        print(f"    {c['case_id']}  [{c['source']}/{c['runner']}]  {c['params']}")


def cmd_generate(args: argparse.Namespace) -> None:
    from hangar.sdk.study.orchestrate import generate_study

    _load_or_die(args.study_path)
    try:
        result = generate_study(Path(args.study_path))
    except (ValueError, KeyError) as exc:
        _die(f"Error: {exc}")
    print(f"Generated {len(result['generated'])} case artifact(s) under "
          f"{result['study_dir']}/cases/")
    for item in result["generated"]:
        print(f"  {item['case_id']}: {item['artifact']}")
    for item in result["skipped"]:
        print(f"  skipped {item['case_id']} ({item['reason']})")


def cmd_run(args: argparse.Namespace) -> None:
    from hangar.sdk.study import SUCCESS_STATUSES, StudyGuardError, run_study

    def _progress(done: dict, summary: dict) -> None:
        result = done["result"]
        ok = result.get("status") in SUCCESS_STATUSES
        line = (f"  [{summary['done']}/{summary['total']}] "
                f"{done['case_id']}  "
                f"{'OK  ' if ok else 'FAIL'} "
                f"wall={done['wall_time_s']:.1f}s")
        if not ok:
            line += f"  error={result.get('error')}"
        print(line, flush=True)

    try:
        result = run_study(
            Path(args.study_path),
            max_cases=args.max_cases,
            workers=args.workers,
            confirm=args.confirm,
            retry_failed=args.retry_failed,
            on_case_done=_progress,
        )
    except StudyGuardError as exc:
        rev = exc.review
        print(f"Refusing to run: {exc}", file=sys.stderr)
        print(f"  Pending: {rev['n_pending']} cases, est wall "
              f"{rev['est_wall_human'] or 'unknown'}", file=sys.stderr)
        print("  Use 'hangar-study review' to inspect, then re-run with "
              "--yes or --max-cases N.", file=sys.stderr)
        raise SystemExit(2)
    except (ValueError, KeyError) as exc:
        _die(f"Error: {exc}")

    batch = result["batch"]
    print(f"Batch done: {batch['succeeded']}/{batch['ran']} succeeded, "
          f"{result['remaining']} case(s) remaining.")
    print(f"  Case table: {result['cases_csv']}")
    if result["remaining"]:
        print("  Review the results, then continue with 'hangar-study run' "
              "(resumes automatically).")


def _store_or_die(study_id: str):
    from hangar.sdk.study import StudyStore

    store = StudyStore(study_id)
    if not store.state_path.exists():
        _die(f"No state for study {study_id!r} under {store.dir}")
    return store


def cmd_status(args: argparse.Namespace) -> None:
    store = _store_or_die(args.study_id)
    summary = store.status_summary()
    print(f"Study {args.study_id} (spec v{summary['version']}): "
          f"{summary['done']}/{summary['total']} done")
    for status, count in sorted(summary["counts"].items()):
        print(f"  {status}: {count}")
    if summary["mean_case_wall_s"]:
        print(f"  Mean case wall time: {summary['mean_case_wall_s']:.1f} s")


def cmd_results(args: argparse.Namespace) -> None:
    from hangar.sdk.study import SUCCESS_STATUSES

    store = _store_or_die(args.study_id)
    state = store.load_state()
    path = store.export_csv(state)
    if args.as_csv:
        print(str(path))
        return

    import csv as _csv

    with open(path) as f:
        rows = list(_csv.reader(f))
    if not rows:
        print("No cases.")
        return
    header, body = rows[0], rows[1:]
    if args.only_failed:
        status_idx = header.index("status")
        body = [r for r in body if r[status_idx] not in SUCCESS_STATUSES]
    widths = [max(len(h), *(len(r[i]) for r in body)) if body else len(h)
              for i, h in enumerate(header)]
    print("  ".join(h.ljust(w) for h, w in zip(header, widths)))
    for row in body:
        print("  ".join(c.ljust(w) for c, w in zip(row, widths)))


def cmd_runners(args: argparse.Namespace) -> None:
    from hangar.sdk.study import list_available_runners

    runners = list_available_runners()
    if not runners:
        print("No runners registered or discoverable.")
        return
    for name, source in sorted(runners.items()):
        print(f"  {name}: {source}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hangar-study",
        description="Author, review, and run multi-case studies across "
                    "hangar tools (runners discovered from installed "
                    "packages).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="Schema + expansion preflight")
    p.add_argument("study_path", metavar="STUDY.yaml")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("review", help="Case count, axes, compute estimate")
    p.add_argument("study_path", metavar="STUDY.yaml")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="Emit the raw review payload as JSON")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("generate",
                       help="Write every case's input artifact (no compute)")
    p.add_argument("study_path", metavar="STUDY.yaml")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("run", help="Run a study or its next batch (resumes)")
    p.add_argument("study_path", metavar="STUDY.yaml")
    p.add_argument("--max-cases", type=int, default=None,
                   help="Run at most N pending cases, then stop (pilot batch)")
    p.add_argument("--workers", type=int, default=None,
                   help="Worker processes (default: execution.workers)")
    p.add_argument("--yes", dest="confirm", action="store_true",
                   help="Confirm running more cases than the review threshold")
    p.add_argument("--retry-failed", action="store_true",
                   help="Also re-run previously failed/errored cases")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="Progress counts for a study")
    p.add_argument("study_id")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("results", help="Spreadsheet-style case table")
    p.add_argument("study_id")
    p.add_argument("--csv", dest="as_csv", action="store_true",
                   help="Print the cases.csv path instead of the table")
    p.add_argument("--failed", dest="only_failed", action="store_true",
                   help="Show only failed/errored cases")
    p.set_defaults(func=cmd_results)

    p = sub.add_parser("runners",
                       help="List registered and discoverable runners")
    p.set_defaults(func=cmd_runners)

    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
