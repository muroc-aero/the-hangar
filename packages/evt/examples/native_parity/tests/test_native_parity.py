"""Native-evt parity suite: hangar.omd.evt vs the evtolpy black box (oracle).

Two layers:

* component parity -- each native component, fed the oracle's values for its
  upstream inputs, reproduces the corresponding evtolpy properties to floating
  point, across the test_all baseline and the AIAA case configs;
* full-sizing parity -- the assembled sizing group reproduces the black box's
  segment tables, totals, peak power, and masses; sized MTOW matches to the
  sizing tolerance (the native loop converges tighter than evtolpy's loose
  |delta| < 1e-3 kg stop).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import openmdao.api as om
import pytest

pytest.importorskip("evtol")

import oracle  # noqa: E402  (conftest puts the example root on sys.path)

from hangar.omd.evt.aero import AeroComp  # noqa: E402
from hangar.omd.evt.builders import build_problem  # noqa: E402
from hangar.omd.evt.config import flatten_config  # noqa: E402
from hangar.omd.evt.geometry import GeometryComp  # noqa: E402
from hangar.omd.evt.labels import SEGMENT_KEYS  # noqa: E402
from hangar.omd.evt.mass import MassBuildupComp  # noqa: E402
from hangar.omd.evt.mission import MissionEnergyComp  # noqa: E402
from hangar.omd.evt.propulsion import PropulsionComp  # noqa: E402

_CFG_DIR = Path(__file__).resolve().parents[2] / "abu_scitech_2026/cfg"
_AIAA = ["archer-midnight-1500-30", "supernal-1500-45", "joby-s4-1500-30"]
_TOL = 1e-9          # component / energy / mass parity: floating point
_MTOW_RTOL = 1e-5    # sized MTOW: native converges tighter than the 1e-3 stop


def _cfg(name: str) -> dict:
    if name == "test_all":
        return oracle.baseline_config()
    with open(_CFG_DIR / f"{name}.json") as fh:
        return json.load(fh)


def _counts(flat: dict) -> dict:
    return {k: int(flat.get(k, 0)) for k in ("rotor_count", "lift_rotor_count",
                                             "tilt_rotor_count", "pusher_rotor_count")}


def _drive(comp, flat: dict, ac) -> om.Problem:
    """Run a single component, feeding inputs from the oracle."""
    p = om.Problem()
    p.model.add_subsystem("c", comp, promotes=["*"])
    p.setup(force_alloc_complex=True)
    for _, m in p.model.c.list_inputs(out_stream=None, prom_name=True, val=False):
        name = m["prom_name"]
        if name in flat:
            p.set_val(name, flat[name])
        elif name.endswith("_in") and name[:-3] in flat:
            p.set_val(name, flat[name[:-3]])
        elif name == "disk_area_m2":
            p.set_val(name, float(ac.propulsion.disk_area_m2))
        else:
            try:
                p.set_val(name, float(getattr(ac, name)))
            except (AttributeError, TypeError):
                # pusher inputs absent for non-pusher vehicles -- unused when
                # pusher_rotor_count == 0, so leaving the default is harmless.
                pass
    p.run_model()
    return p


@pytest.mark.parametrize("cfg_name", ["test_all", *_AIAA])
def test_component_parity(cfg_name):
    cfg = _cfg(cfg_name)
    ac = oracle.build(cfg)
    flat = flatten_config(cfg)
    counts = _counts(flat)
    prop_counts = {k: counts[k] for k in ("rotor_count", "pusher_rotor_count")}

    p = _drive(GeometryComp(), flat, ac)
    for k, gv in oracle.geometry(ac).items():
        assert float(p.get_val(k)[0]) == pytest.approx(gv, rel=_TOL, abs=_TOL)

    p = _drive(PropulsionComp(**prop_counts), flat, ac)
    for k, gv in oracle.propulsion(ac).items():
        assert float(p.get_val(k)[0]) == pytest.approx(gv, rel=_TOL, abs=_TOL)

    p = _drive(AeroComp(), flat, ac)
    for k, gv in oracle.aero(ac).items():
        assert float(p.get_val(k)[0]) == pytest.approx(gv, rel=_TOL, abs=_TOL)

    p = _drive(MissionEnergyComp(**counts), flat, ac)
    se, sp = p.get_val("segment_energy_kw_hr"), p.get_val("segment_power_kw")
    oe, opw = oracle.segment_energy(ac), oracle.segment_power(ac)
    for i, key in enumerate(SEGMENT_KEYS):
        assert float(se[i]) == pytest.approx(oe[key], rel=_TOL, abs=_TOL)
        assert float(sp[i]) == pytest.approx(opw[key], rel=_TOL, abs=_TOL)

    p = _drive(MassBuildupComp(**counts), flat, ac)
    for k, gv in oracle.masses(ac).items():
        assert float(p.get_val(k)[0]) == pytest.approx(gv, rel=_TOL, abs=_TOL)
    for k in ("empty_mass_kg", "battery_mass_kg"):
        assert float(p.get_val(k)[0]) == pytest.approx(
            float(getattr(ac, k)), rel=_TOL, abs=_TOL)


@pytest.mark.parametrize("solver", ["gs", "newton"])
def test_full_sizing_parity(solver):
    """Assembled sizing group vs the black box at the test_all baseline."""
    from hangar.evt.results import run_mtow_iteration

    cfg = oracle.baseline_config()
    # run_mtow_iteration sizes the aircraft in place, so read the as-configured
    # segment tables from a separate, unsized aircraft.
    sized = run_mtow_iteration(oracle.build(cfg))
    oe = oracle.segment_energy(oracle.build(cfg))

    prob, meta = build_problem(cfg, mode="sizing", solver=solver)
    prob.setup(force_alloc_complex=True)
    for name, val in meta["initial_values"].items():
        prob.set_val(name, val)
    prob.run_model()

    assert float(prob.get_val("converged")[0]) == 1.0
    assert float(prob.get_val("sized_mtow_kg")[0]) == pytest.approx(
        sized["sized_mtow_kg"], rel=_MTOW_RTOL)
    # segment tables/totals/peak are read at the as-configured MTOW (bit-exact)
    energy = np.atleast_1d(prob.get_val("segment_energy_kw_hr"))
    for i, key in enumerate(SEGMENT_KEYS):
        assert float(energy[i]) == pytest.approx(oe[key], rel=_TOL, abs=_TOL)


def test_gs_and_newton_agree():
    """The two MTOW-closure solvers converge to the same sized MTOW."""
    cfg = oracle.baseline_config()
    vals = {}
    for solver in ("gs", "newton"):
        prob, meta = build_problem(cfg, mode="sizing", solver=solver)
        prob.setup(force_alloc_complex=True)
        for name, val in meta["initial_values"].items():
            prob.set_val(name, val)
        prob.run_model()
        vals[solver] = float(prob.get_val("sized_mtow_kg")[0])
    assert vals["gs"] == pytest.approx(vals["newton"], rel=1e-4)
