"""End-to-end test for ``omd-cli summary``."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from hangar.omd.cli import cli


def _prepare_run(tmp_path: Path, monkeypatch) -> str:
    """Assemble and run a tiny paraboloid fixture; return the run_id."""
    monkeypatch.setenv("OMD_DATA_ROOT", str(tmp_path / "hangar_data" / "omd"))
    # Re-import so the env var takes effect
    from hangar.omd import db as db_mod
    db_mod._DATA_ROOT = None  # type: ignore[attr-defined]
    if hasattr(db_mod, "_CONN"):
        db_mod._CONN = None  # type: ignore[attr-defined]

    runner = CliRunner()
    fixture = Path(__file__).parent / "fixtures" / "paraboloid_analysis"
    plan_out = tmp_path / "plan.yaml"
    r = runner.invoke(cli, ["assemble", str(fixture), "-o", str(plan_out)])
    assert r.exit_code == 0, r.output

    r = runner.invoke(cli, ["run", str(plan_out), "--quiet"])
    assert r.exit_code == 0, r.output
    # The stdout contains "Run complete: <run_id>"
    for line in r.output.splitlines():
        if line.startswith("Run complete:"):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"no run_id in output:\n{r.output}")


def test_summary_command_produces_html(tmp_path, monkeypatch):
    run_id = _prepare_run(tmp_path, monkeypatch)

    runner = CliRunner()
    out_html = tmp_path / "summary.html"
    r = runner.invoke(cli, ["summary", run_id, "--output", str(out_html)])
    assert r.exit_code == 0, r.output
    assert out_html.exists()
    body = out_html.read_text()

    # Structural assertions — section headers and the run_id
    assert "<h1>" in body
    assert run_id in body
    assert "<h2>Design variables" in body
    assert "<h2>Constraints" in body
    assert "<h2>Plots" in body
