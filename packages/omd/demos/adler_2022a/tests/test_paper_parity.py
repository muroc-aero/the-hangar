"""Compare converged optima from a sweep run against PAPER_TABLES.

Slow integration test: requires `results/per_design/{rng}/{method}.json`
files produced by a real sweep. Skips a (rng, method) cell if its JSON
is absent, or if the paper transcription has `None` for the field
being checked.

Tolerances:
    - Smoke / coarse-mesh runs: pass `--paper-rel-tol 0.20` (20 %).
    - Paper-spec / full-mesh:  pass `--paper-rel-tol 0.05` (5 %).
The default is `0.20` (smoke); the `--paper-rel-tol` pytest CLI flag
overrides it.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from paper_data import PAPER_TABLES

DEMO_DIR = Path(__file__).resolve().parent.parent
PER_DESIGN_DIR = DEMO_DIR / "results" / "per_design"


@pytest.fixture(scope="module")
def rel_tol(request) -> float:
    return float(request.config.getoption("--paper-rel-tol"))


def _per_design_json(rng: int, method: str) -> dict | None:
    path = PER_DESIGN_DIR / str(rng) / f"{method}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _close(actual: float | None, target: float | None, rel: float) -> bool:
    if target is None or actual is None:
        return True  # skip-equivalent
    if target == 0.0:
        return abs(actual) < rel
    return abs(actual - target) / abs(target) <= rel


CASES = [
    (rng, mth)
    for rng in PAPER_TABLES
    for mth in PAPER_TABLES[rng]
]


@pytest.mark.slow
@pytest.mark.parametrize("rng,method", CASES)
def test_paper_scalars(rng: int, method: str, rel_tol: float) -> None:
    """AR, taper, c4sweep_deg within rel_tol of paper Tables 5-7."""
    data = _per_design_json(rng, method)
    if data is None:
        pytest.skip(f"no per_design dump for {rng}/{method}")
    paper = PAPER_TABLES[rng][method]
    for field in ("AR", "taper", "c4sweep_deg"):
        target = paper.get(field)
        if target is None:
            continue  # paper transcription incomplete for this cell
        actual = data.get(field)
        assert actual is not None, f"{rng}/{method}: missing {field} in JSON"
        assert _close(actual, target, rel_tol), (
            f"{rng}/{method} {field}: actual={actual!r} paper={target!r} "
            f"(rel_tol={rel_tol})"
        )


@pytest.mark.slow
@pytest.mark.parametrize("rng,method", CASES)
def test_paper_vectors(rng: int, method: str, rel_tol: float) -> None:
    """twist_cp_deg / toverc_cp / spar / skin element-wise within rel_tol."""
    data = _per_design_json(rng, method)
    if data is None:
        pytest.skip(f"no per_design dump for {rng}/{method}")
    paper = PAPER_TABLES[rng][method]

    # paper key -> json key, optional unit factor (json -> paper units)
    fields = [
        ("twist_cp_deg", "twist_cp_deg", 1.0),
        ("toverc_cp",    "toverc_cp",    1.0),
        ("spar_cp_mm",   "spar_cp_m",    1000.0),  # m -> mm
        ("skin_cp_mm",   "skin_cp_m",    1000.0),
    ]
    for paper_key, json_key, factor in fields:
        target = paper.get(paper_key)
        if target is None:
            continue
        actual_raw = data.get(json_key)
        assert actual_raw is not None, f"{rng}/{method}: missing {json_key} in JSON"
        actual = [v * factor for v in actual_raw]
        assert len(actual) == len(target), (
            f"{rng}/{method} {paper_key}: length actual={len(actual)} "
            f"paper={len(target)}"
        )
        for i, (a, t) in enumerate(zip(actual, target)):
            if t is None:
                continue
            assert _close(a, t, rel_tol), (
                f"{rng}/{method} {paper_key}[{i}]: actual={a!r} paper={t!r} "
                f"(rel_tol={rel_tol})"
            )
