"""Integration tests for the oas script-based study runner.

Runs a tiny alpha sweep through the real OAS aero pipeline via the SDK
study layer (single worker, in-process), so the whole chain is exercised:
spec expansion -> script generation -> registry execution -> output
extraction -> study store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import hangar.oas.study_runner  # noqa: F401  (registers the "oas" runner)
from hangar.sdk.study import run_study
from hangar.sdk.study.orchestrate import generate_study

from oas_surface_defs import SMALL_RECT


@pytest.fixture(autouse=True)
def isolate_prov_env(tmp_path, monkeypatch):
    """Keep the registry builder's init_db() off the real provenance DB.

    build_oas_registry() calls init_db() with no args, which resolves via
    HANGAR_PROV_DB; without this the lazily-built registry would re-point
    provenance at ./hangar_data mid-test.
    """
    monkeypatch.setenv("HANGAR_PROV_DB", str(tmp_path / "prov.db"))


def _study(tmp_path: Path, alphas: list[float]) -> Path:
    steps = [
        {"id": "surf", "tool": "create_surface", "args": dict(SMALL_RECT)},
        {"id": "an", "tool": "run_aero_analysis",
         "args": {"surfaces": ["wing"], "alpha": 0.0}},
    ]
    study = {
        "metadata": {"id": "oas-alpha-smoke", "name": "OAS alpha sweep",
                     "version": 1},
        "defaults": {"runner": "oas", "spec": {"steps": steps}},
        "cases": [
            {"matrix": {
                "id_template": "a{alpha:g}",
                "axes": {"alpha": {"values": alphas}},
                "bind": {"alpha": ["steps[an].args.alpha"]},
            }},
        ],
        "outputs": [
            {"name": "CL", "path": "an:results.CL"},
            {"name": "CD", "path": "an:results.CD"},
        ],
    }
    path = tmp_path / "study.yaml"
    path.write_text(yaml.safe_dump(study))
    return path


def test_generate_writes_reviewable_scripts(tmp_path):
    path = _study(tmp_path, [0.0, 4.0])
    result = generate_study(path, store_root=tmp_path / "store")
    assert len(result["generated"]) == 2
    steps = json.loads(Path(result["generated"][0]["artifact"]).read_text())
    assert steps[0]["tool"] == "create_surface"
    assert steps[1]["args"]["alpha"] in (0.0, 4.0)


def test_generate_rejects_unknown_tool(tmp_path):
    path = _study(tmp_path, [0.0])
    spec = yaml.safe_load(path.read_text())
    spec["defaults"]["spec"]["steps"][1]["tool"] = "run_aero_analsis"  # typo
    path.write_text(yaml.safe_dump(spec))
    with pytest.raises(ValueError, match="run_aero_analsis"):
        generate_study(path, store_root=tmp_path / "store")


@pytest.mark.slow
def test_alpha_sweep_end_to_end(tmp_path):
    path = _study(tmp_path, [0.0, 2.0, 4.0])
    result = run_study(path, workers=1, store_root=tmp_path / "store")

    assert result["batch"] == {"ran": 3, "succeeded": 3, "failed": 0,
                               "requested": 3}
    state = json.loads(
        (tmp_path / "store" / "oas-alpha-smoke" / "state.json").read_text())
    rows = {e["case_id"]: e for e in state["cases"].values()}
    assert set(rows) == {"a0", "a2", "a4"}

    # Real physics: CL increases monotonically with alpha, CD positive.
    CLs = [rows[c]["outputs"]["CL"] for c in ("a0", "a2", "a4")]
    assert CLs[0] < CLs[1] < CLs[2]
    assert all(rows[c]["outputs"]["CD"] > 0 for c in rows)
    # Each case carries the OAS run_id for tracing into the artifact store.
    assert all(rows[c]["run_ref"] for c in rows)
