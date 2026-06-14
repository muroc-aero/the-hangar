"""Tests for run_parameter_sweep."""

import pytest

from hangar.evtol.tools.sweep import run_parameter_sweep


async def test_sweep_energy_metric(loaded_vehicle):
    env = await run_parameter_sweep(
        param="power.batt_spec_energy_w_h_p_kg",
        values=[200.0, 240.0, 280.0],
        metric="total_mission_energy_kw_hr",
    )
    r = env["results"]
    assert len(r["points"]) == 3
    assert r["summary"]["succeeded"] == 3
    # Mission energy does not depend on battery specific energy.
    metrics = [p["metric"] for p in r["points"]]
    assert all(m == pytest.approx(metrics[0]) for m in metrics)


async def test_sweep_sized_mtow_metric(loaded_vehicle):
    env = await run_parameter_sweep(
        param="power.batt_spec_energy_w_h_p_kg",
        values=[200.0, 320.0],
        metric="sized_mtow_kg",
    )
    pts = env["results"]["points"]
    # Higher specific energy -> lighter battery -> lower sized MTOW.
    assert pts[1]["metric"] < pts[0]["metric"]


async def test_sweep_unknown_param(loaded_vehicle):
    with pytest.raises(ValueError, match="Unknown sweep key"):
        await run_parameter_sweep(param="power.nope", values=[1.0])


async def test_sweep_bad_param_format(loaded_vehicle):
    with pytest.raises(ValueError, match="section.key"):
        await run_parameter_sweep(param="batt_spec_energy", values=[1.0])


async def test_sweep_unknown_metric(loaded_vehicle):
    with pytest.raises(ValueError, match="Unknown metric"):
        await run_parameter_sweep(
            param="mission.cruise_s", values=[600.0], metric="nope"
        )


async def test_sweep_records_failed_points(loaded_vehicle):
    # A near-zero battery specific energy will diverge for sized_mtow; the sweep
    # records the failure rather than aborting.
    env = await run_parameter_sweep(
        param="power.batt_spec_energy_w_h_p_kg",
        values=[300.0, 55.0],
        metric="sized_mtow_kg",
    )
    pts = env["results"]["points"]
    assert pts[0]["metric"] is not None
    assert pts[1]["metric"] is None and "error" in pts[1]
