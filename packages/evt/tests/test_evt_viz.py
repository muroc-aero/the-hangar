"""Tests for evt plot generation."""

import pytest

from hangar.evt.tools.analysis import run_mission_analysis, run_sizing
from hangar.evt.tools.sweep import run_parameter_sweep
from hangar.evt.viz.plotting import EVT_PLOT_TYPES, generate_evt_plot


async def test_mission_plots(loaded_vehicle, tmp_path):
    results = (await run_mission_analysis())["results"]
    for plot_type in ("segment_energy", "segment_power", "mass_breakdown"):
        res = generate_evt_plot(plot_type, "run1", results, save_dir=str(tmp_path))
        assert res.metadata is not None


async def test_sizing_plot(loaded_vehicle, tmp_path):
    results = (await run_sizing())["results"]
    res = generate_evt_plot("mtow_convergence", "run2", results, save_dir=str(tmp_path))
    assert res.metadata is not None


async def test_sweep_plot(loaded_vehicle, tmp_path):
    results = (await run_parameter_sweep(
        param="mission.cruise_s", values=[600.0, 660.0, 720.0],
        metric="total_mission_energy_kw_hr",
    ))["results"]
    res = generate_evt_plot("sweep", "run3", results, save_dir=str(tmp_path))
    assert res.metadata is not None


def test_unknown_plot_type():
    with pytest.raises(ValueError, match="Unknown evt plot_type"):
        generate_evt_plot("nope", "r", {})


def test_plot_type_set():
    assert "segment_energy" in EVT_PLOT_TYPES
    assert len(EVT_PLOT_TYPES) == 5
