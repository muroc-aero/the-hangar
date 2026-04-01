"""Tests for pyCycle visualization plots."""

import pytest

from hangar.pyc.viz.plotting import (
    PYC_PLOT_TYPES,
    generate_pyc_plot,
    plot_component_bars,
    plot_design_vs_offdesign,
    plot_performance_summary,
    plot_station_properties,
    plot_ts_diagram,
)
from hangar.sdk.viz.plotting import PlotResult


# ---------------------------------------------------------------------------
# Synthetic test data
# ---------------------------------------------------------------------------

_FLOW_STATIONS = {
    "fc.Fl_O": {
        "tot:P": 14.696, "tot:T": 518.67, "tot:h": 124.0, "tot:S": 1.635,
        "stat:P": 14.696, "stat:W": 100.0, "stat:MN": 0.0001, "stat:V": 0.1,
        "stat:area": 2000.0,
    },
    "inlet.Fl_O": {
        "tot:P": 14.696, "tot:T": 518.67, "tot:h": 124.0, "tot:S": 1.636,
        "stat:P": 12.0, "stat:W": 100.0, "stat:MN": 0.4, "stat:V": 400.0,
        "stat:area": 800.0,
    },
    "comp.Fl_O": {
        "tot:P": 198.4, "tot:T": 1100.0, "tot:h": 265.0, "tot:S": 1.640,
        "stat:P": 190.0, "stat:W": 100.0, "stat:MN": 0.3, "stat:V": 350.0,
        "stat:area": 150.0,
    },
    "burner.Fl_O": {
        "tot:P": 192.4, "tot:T": 2370.0, "tot:h": 600.0, "tot:S": 1.820,
        "stat:P": 185.0, "stat:W": 102.0, "stat:MN": 0.2, "stat:V": 300.0,
        "stat:area": 200.0,
    },
    "turb.Fl_O": {
        "tot:P": 30.0, "tot:T": 1500.0, "tot:h": 370.0, "tot:S": 1.830,
        "stat:P": 28.0, "stat:W": 102.0, "stat:MN": 0.5, "stat:V": 700.0,
        "stat:area": 400.0,
    },
    "nozz.Fl_O": {
        "tot:P": 30.0, "tot:T": 1500.0, "tot:h": 370.0, "tot:S": 1.835,
        "stat:P": 14.696, "stat:W": 102.0, "stat:MN": 1.0, "stat:V": 1500.0,
        "stat:area": 350.0,
    },
}

_PERFORMANCE = {
    "Fn": 11800.0,
    "Fg": 13500.0,
    "TSFC": 1.12,
    "OPR": 13.5,
    "Wfuel": 3.67,
    "ram_drag": 1700.0,
    "mass_flow": 100.0,
}

_COMPONENTS = {
    "comp": {"PR": 13.5, "eff": 0.83, "Wc": 100.0, "Nc": 8070.0, "pwr": -5500.0, "trq": 3600.0, "map_RlineMap": 2.0},
    "turb": {"PR": 6.6, "eff": 0.86, "Wp": 15.0, "Np": 100.0, "pwr": 5500.0, "trq": 3600.0},
    "burner": {"FAR": 0.023, "Wfuel": 3.67, "dPqP": 0.03},
    "shaft": {"Nmech": 8070.0, "pwr_net": 0.001},
    "nozz": {"Fg": 13500.0, "PR": 2.04, "Cv": 0.99, "throat_area": 350.0},
}

_RESULTS = {
    "performance": _PERFORMANCE,
    "flow_stations": _FLOW_STATIONS,
    "components": _COMPONENTS,
}

_DESIGN_PERF = {
    "Fn": 11800.0,
    "Fg": 13500.0,
    "TSFC": 1.12,
    "OPR": 13.5,
    "Wfuel": 3.67,
    "ram_drag": 1700.0,
    "mass_flow": 100.0,
}

_OFF_DESIGN_RESULTS = {
    "performance": {
        "Fn": 8000.0,
        "Fg": 9200.0,
        "TSFC": 1.25,
        "OPR": 11.2,
        "Wfuel": 2.78,
        "ram_drag": 1200.0,
        "mass_flow": 85.0,
    },
    "flow_stations": _FLOW_STATIONS,
    "components": _COMPONENTS,
    "design_point": _DESIGN_PERF,
}


RUN_ID = "test-run-001"


# ---------------------------------------------------------------------------
# Plot function tests
# ---------------------------------------------------------------------------

def _assert_png(result: PlotResult):
    """Check that result is a valid PlotResult with PNG data."""
    assert isinstance(result, PlotResult)
    assert result.image is not None
    # Check PNG magic bytes
    assert result.image.data[:4] == b"\x89PNG"
    assert result.metadata["plot_type"] is not None
    assert result.metadata["run_id"] == RUN_ID


def test_plot_station_properties():
    result = plot_station_properties(RUN_ID, _RESULTS)
    _assert_png(result)
    assert result.metadata["plot_type"] == "station_properties"


def test_plot_ts_diagram():
    result = plot_ts_diagram(RUN_ID, _RESULTS)
    _assert_png(result)
    assert result.metadata["plot_type"] == "ts_diagram"


def test_plot_performance_summary():
    result = plot_performance_summary(RUN_ID, _RESULTS)
    _assert_png(result)
    assert result.metadata["plot_type"] == "performance_summary"


def test_plot_component_bars():
    result = plot_component_bars(RUN_ID, _RESULTS)
    _assert_png(result)
    assert result.metadata["plot_type"] == "component_bars"


def test_plot_design_vs_offdesign():
    result = plot_design_vs_offdesign(RUN_ID, _OFF_DESIGN_RESULTS)
    _assert_png(result)
    assert result.metadata["plot_type"] == "design_vs_offdesign"


def test_plot_design_vs_offdesign_requires_design_point():
    with pytest.raises(ValueError, match="design_point"):
        plot_design_vs_offdesign(RUN_ID, _RESULTS)


# ---------------------------------------------------------------------------
# Dispatcher tests
# ---------------------------------------------------------------------------

def test_dispatcher_routes_all_types():
    for plot_type in PYC_PLOT_TYPES:
        if plot_type == "design_vs_offdesign":
            result = generate_pyc_plot(plot_type, RUN_ID, _OFF_DESIGN_RESULTS)
        else:
            result = generate_pyc_plot(plot_type, RUN_ID, _RESULTS)
        _assert_png(result)


def test_dispatcher_rejects_unknown_type():
    with pytest.raises(ValueError, match="Unknown pyc plot_type"):
        generate_pyc_plot("nonexistent_plot", RUN_ID, _RESULTS)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_station_properties_no_data():
    with pytest.raises(ValueError, match="No flow_stations"):
        plot_station_properties(RUN_ID, {"performance": {}})


def test_ts_diagram_no_data():
    with pytest.raises(ValueError, match="No flow_stations"):
        plot_ts_diagram(RUN_ID, {"performance": {}})


def test_component_bars_no_data():
    with pytest.raises(ValueError, match="No components"):
        plot_component_bars(RUN_ID, {"performance": {}})


def test_pyc_plot_types_frozenset():
    assert isinstance(PYC_PLOT_TYPES, frozenset)
    assert len(PYC_PLOT_TYPES) == 5
