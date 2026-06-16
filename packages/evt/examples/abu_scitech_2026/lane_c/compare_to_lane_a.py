"""Lane C vs Lane A: run the declarative study, check it against ground truth.

Loads ``range_study.yaml``, expands it into cases, and runs each through the
registered ``evt`` study runner (``hangar.evt.study_runner.run_case``) -- the
same runner the ``hangar-study`` orchestrator drives. Then compares each case's
study outputs (sized MTOW, total mission energy) against Lane A (direct evtolpy)
for the same range. Parity is exact to round-off; both lanes run identical
algebra on identical inputs.

    uv run python packages/evt/examples/abu_scitech_2026/lane_c/compare_to_lane_a.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

_LANE_C = Path(__file__).resolve().parent
_EXAMPLE_ROOT = _LANE_C.parent
sys.path.insert(0, str(_EXAMPLE_ROOT))

from shared import TOL  # noqa: E402
from hangar.sdk.study.schema import load_study  # noqa: E402
from hangar.sdk.study.expand import expand_cases  # noqa: E402
from hangar.evt.study_runner import run_case  # noqa: E402

import lane_a.case_study as lane_a  # noqa: E402

_STUDY = _LANE_C / "range_study.yaml"


def run_lane_c(study_path: Path | None = None) -> list[dict]:
    """Run every case in the study and return per-case outputs + status."""
    spec, errors = load_study(study_path or _STUDY)
    if errors:
        raise ValueError(f"invalid study spec: {errors}")
    outputs = spec["outputs"]
    cases = expand_cases(spec)

    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for case in cases:
            ctx = {
                "artifact_dir": str(Path(tmp) / case.case_id),
                "outputs": outputs,
                "case_id": case.case_id,
            }
            result = run_case(case.spec, ctx)
            rows.append({
                "case_id": case.case_id,
                "range_mi": case.params["range_mi"],
                "status": result["status"],
                "outputs": result["outputs"],
                "error": result.get("error"),
            })
    return rows


def main() -> None:
    import numpy as np

    rows = run_lane_c()
    print(f"{'case':18s} {'status':10s} {'E (C)':>10s} {'E (A)':>10s} "
          f"{'MTOW (C)':>10s} {'MTOW (A)':>10s}")
    for row in rows:
        a = lane_a.run_case("archer-midnight", 1500, row["range_mi"])
        e_c = row["outputs"]["total_mission_energy_kw_hr"]
        m_c = row["outputs"]["sized_mtow_kg"]
        print(f"{row['case_id']:18s} {row['status']:10s} "
              f"{e_c:10.4f} {a['total_mission_energy_kw_hr']:10.4f} "
              f"{m_c:10.3f} {a['sized_mtow_kg']:10.3f}")
        np.testing.assert_allclose(
            e_c, a["total_mission_energy_kw_hr"],
            err_msg=f"energy parity C vs A on {row['case_id']}", **TOL)
        np.testing.assert_allclose(
            m_c, a["sized_mtow_kg"],
            err_msg=f"MTOW parity C vs A on {row['case_id']}", **TOL)
    print("\nLane C == Lane A on all cells (to round-off).")


if __name__ == "__main__":
    main()
