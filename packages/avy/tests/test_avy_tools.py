"""Unit tests for the avy tool surface.

Aviary-free tests run anywhere; tests guarded with
``importorskip("aviary")`` need the aviary package (a workspace dependency).
"""

from __future__ import annotations

import importlib.util

import pytest

from hangar.avy.templates import AIRCRAFT_TEMPLATES
from hangar.avy.tools.aircraft import (
    configure_mission,
    define_aircraft,
    list_aircraft_templates,
    load_aircraft_template,
)
from hangar.avy.tools.analysis import run_off_design, run_payload_range, run_sizing
from hangar.avy.tools.session import reset

HAS_AVIARY = importlib.util.find_spec("aviary") is not None


# ---------------------------------------------------------------------------
# Aviary-free tests (run anywhere)
# ---------------------------------------------------------------------------


async def test_list_templates():
    result = await list_aircraft_templates()
    assert result["count"] == len(AIRCRAFT_TEMPLATES)
    assert "advanced_single_aisle" in result["templates"]
    entry = result["templates"]["advanced_single_aisle"]
    assert entry["mass_method"] == "FLOPS"
    assert entry["mission_method"] == "energy_state"
    # deck paths are internal; not exposed in the listing
    assert "deck" not in entry


async def test_load_template_registers_aircraft(single_aisle):
    from hangar.avy.state import sessions

    session = sessions.get("default")
    assert single_aisle in session.aircraft
    cfg = session.aircraft[single_aisle]
    assert cfg["template"] == "advanced_single_aisle"
    assert cfg["overrides"] == {}
    assert cfg["mission"] is None


async def test_load_unknown_template_errors():
    with pytest.raises(ValueError, match="Unknown aircraft template"):
        await load_aircraft_template(template="nonexistent_plane")


async def test_define_aircraft_requires_loaded_aircraft():
    with pytest.raises(ValueError, match="not found"):
        await define_aircraft(aircraft_name="ghost", overrides={})


async def test_run_sizing_requires_loaded_aircraft():
    with pytest.raises(ValueError, match="not found"):
        await run_sizing(aircraft_name="ghost")


async def test_run_sizing_rejects_unknown_optimizer(single_aisle):
    with pytest.raises(ValueError, match="Unknown optimizer"):
        await run_sizing(aircraft_name=single_aisle, optimizer="GRADIENT_DESCENT")


async def test_run_sizing_rejects_bad_max_iter(single_aisle):
    with pytest.raises(ValueError, match="max_iter"):
        await run_sizing(aircraft_name=single_aisle, max_iter=0)


async def test_run_sizing_rejects_2dof_deck():
    await load_aircraft_template(template="large_single_aisle_GASP", name="gasp")
    with pytest.raises(ValueError, match="2DOF"):
        await run_sizing(aircraft_name="gasp")


async def test_run_off_design_requires_loaded_aircraft():
    with pytest.raises(ValueError, match="not found"):
        await run_off_design(aircraft_name="ghost")


async def test_run_off_design_rejects_unknown_mission_type(single_aisle):
    with pytest.raises(ValueError, match="Unknown mission_type"):
        await run_off_design(aircraft_name=single_aisle, mission_type="ferry")


async def test_run_off_design_min_fuel_requires_range(single_aisle):
    with pytest.raises(ValueError, match="mission_range_nm"):
        await run_off_design(aircraft_name=single_aisle, mission_type="min_fuel")


async def test_run_off_design_rejects_negative_range(single_aisle):
    with pytest.raises(ValueError, match="positive"):
        await run_off_design(
            aircraft_name=single_aisle, mission_type="min_fuel", mission_range_nm=-5.0
        )


async def test_run_payload_range_requires_loaded_aircraft():
    with pytest.raises(ValueError, match="not found"):
        await run_payload_range(aircraft_name="ghost")


async def test_run_payload_range_rejects_2dof_deck():
    await load_aircraft_template(template="small_single_aisle_GASP", name="gasp")
    with pytest.raises(ValueError, match="2DOF"):
        await run_payload_range(aircraft_name="gasp")


async def test_configure_mission_rejects_2dof_deck():
    await load_aircraft_template(template="small_single_aisle_GASP", name="gasp")
    with pytest.raises(ValueError, match="2DOF"):
        await configure_mission(aircraft_name="gasp")


async def test_reset_clears_aircraft(single_aisle):
    from hangar.avy.state import sessions

    assert sessions.get("default").aircraft
    await reset()
    assert not sessions.get("default").aircraft


@pytest.mark.skipif(HAS_AVIARY, reason="aviary installed; error path not reachable")
async def test_run_sizing_without_aviary_gives_install_instructions(single_aisle):
    with pytest.raises(RuntimeError, match="dev-setup"):
        await run_sizing(aircraft_name=single_aisle)


@pytest.mark.skipif(HAS_AVIARY, reason="aviary installed; error path not reachable")
async def test_definition_tools_without_aviary_give_install_instructions(single_aisle):
    with pytest.raises(RuntimeError, match="dev-setup"):
        await define_aircraft(
            aircraft_name=single_aisle, overrides={"aircraft:wing:span": 100}
        )
    with pytest.raises(RuntimeError, match="dev-setup"):
        await configure_mission(aircraft_name=single_aisle)


def test_design_point_finding_failure_is_error():
    from hangar.avy.validation import design_point_finding

    finding = design_point_finding(False)
    assert not finding.passed
    assert finding.severity == "error"
    assert design_point_finding(True).passed


def test_payload_range_findings_partial_diagram_fails():
    from hangar.avy.validation import payload_range_findings

    partial = {"points": [{"label": "max_payload"}, {"label": "design_mission"}],
               "off_design_success": []}
    finding = payload_range_findings(partial)
    assert not finding.passed
    assert finding.severity == "error"

    complete = {
        "points": [{"label": l} for l in
                   ("max_payload", "design_mission", "max_fuel_plus_payload", "ferry_range")],
        "off_design_success": [True, True],
    }
    assert payload_range_findings(complete).passed


# ---------------------------------------------------------------------------
# Tests that need aviary (workspace venv)
# ---------------------------------------------------------------------------


async def test_define_aircraft_validates_names(single_aisle):
    pytest.importorskip("aviary")
    with pytest.raises(ValueError, match="Unknown Aviary variable"):
        await define_aircraft(
            aircraft_name=single_aisle,
            overrides={"aircraft:wing:aspect_ratioo": 11.0},
        )


async def test_define_aircraft_accumulates_overrides(single_aisle):
    pytest.importorskip("aviary")
    await define_aircraft(
        aircraft_name=single_aisle,
        overrides={"aircraft:wing:aspect_ratio": 11.0},
    )
    result = await define_aircraft(
        aircraft_name=single_aisle,
        overrides={"aircraft:design:gross_mass": [150000, "lbm"]},
    )
    assert result["overrides"] == {
        "aircraft:wing:aspect_ratio": 11.0,
        "aircraft:design:gross_mass": [150000, "lbm"],
    }


async def test_define_aircraft_rejects_bad_units_spec(single_aisle):
    pytest.importorskip("aviary")
    with pytest.raises(ValueError, match="value, units"):
        await define_aircraft(
            aircraft_name=single_aisle,
            overrides={"aircraft:wing:aspect_ratio": [11.0, 12.0, 13.0]},
        )


async def test_configure_mission_defaults(single_aisle):
    pytest.importorskip("aviary")
    result = await configure_mission(aircraft_name=single_aisle)
    assert result["mission_method"] == "energy_state"
    assert set(result["phases"]) >= {"climb", "cruise", "descent"}


async def test_configure_mission_target_range(single_aisle):
    pytest.importorskip("aviary")
    await configure_mission(aircraft_name=single_aisle, target_range_nm=2500.0)
    from hangar.avy.state import sessions

    mission = sessions.get("default").aircraft[single_aisle]["mission"]
    post = mission["phase_info"]["post_mission"]
    assert post["constrain_range"] is True
    assert post["target_range"] == (2500.0, "nmi")


async def test_configure_mission_phase_options(single_aisle):
    pytest.importorskip("aviary")
    await configure_mission(
        aircraft_name=single_aisle,
        phase_options={"cruise": {"num_segments": 3, "mach_final": 0.75}},
    )
    from hangar.avy.state import sessions

    mission = sessions.get("default").aircraft[single_aisle]["mission"]
    user = mission["phase_info"]["cruise"]["user_options"]
    assert user["num_segments"] == 3
    # bare value wraps with the default's units
    assert user["mach_final"] == (0.75, "unitless")


async def test_configure_mission_rejects_unknown_phase(single_aisle):
    pytest.importorskip("aviary")
    with pytest.raises(ValueError, match="Unknown phase"):
        await configure_mission(
            aircraft_name=single_aisle, phase_options={"cruize": {"num_segments": 3}}
        )


async def test_configure_mission_rejects_unknown_option(single_aisle):
    pytest.importorskip("aviary")
    with pytest.raises(ValueError, match="Unknown option"):
        await configure_mission(
            aircraft_name=single_aisle,
            phase_options={"cruise": {"num_segmentz": 3}},
        )


async def test_configure_mission_rejects_unknown_template(single_aisle):
    pytest.importorskip("aviary")
    with pytest.raises(ValueError, match="Unknown mission_template"):
        await configure_mission(
            aircraft_name=single_aisle, mission_template="bwb_fixd"
        )


async def test_configure_mission_bwb_fixed_template():
    """The bwb_fixed template loads and has the fixed-profile adaptation applied."""
    pytest.importorskip("aviary")
    await load_aircraft_template(template="bwb_FLOPS", name="bwb")
    result = await configure_mission(aircraft_name="bwb", mission_template="bwb_fixed")
    from hangar.avy.state import sessions

    mission = sessions.get("default").aircraft["bwb"]["mission"]
    assert mission["mission_template"] == "bwb_fixed"
    climb = mission["phase_info"]["climb"]["user_options"]
    assert climb["mach_optimize"] is False
    assert climb["mach_final"] == (0.85, "unitless")
    assert result["phases"]["cruise"]["mach_initial"] == [0.85, "unitless"]


async def test_configure_mission_rejects_units_pair_on_unitless_option(single_aisle):
    pytest.importorskip("aviary")
    with pytest.raises(ValueError, match="does not take units"):
        await configure_mission(
            aircraft_name=single_aisle,
            phase_options={"cruise": {"num_segments": [3, "unitless"]}},
        )


async def test_repeat_runs_use_unmutated_mission(single_aisle):
    """Aviary mutates the phase_info it is given; the session copy must not drift."""
    pytest.importorskip("aviary")
    await configure_mission(aircraft_name=single_aisle, target_range_nm=1500.0)
    from hangar.avy.state import sessions
    from hangar.avy.tools.analysis import _prepare_run

    session = sessions.get("default")
    stored = session.aircraft[single_aisle]["mission"]["phase_info"]
    before = repr(stored)

    _, phase_info, _, _, _ = _prepare_run(session, single_aisle, "SLSQP", 50)
    assert phase_info is not stored
    # mutating the returned copy (as Aviary does in-place) leaves the session intact
    phase_info["cruise"]["user_options"]["num_segments"] = 99
    phase_info["post_mission"]["target_range"] = (9999.0, "nmi")
    assert repr(stored) == before


# ---------------------------------------------------------------------------
# Review follow-ups: off-design contract, precompute feedback, sizing cache
# ---------------------------------------------------------------------------


async def test_run_off_design_rejects_range_for_max_range(single_aisle):
    # Upstream ignores mission_range for max-range missions; silently
    # forwarding it would let a caller believe the range was constrained.
    with pytest.raises(ValueError, match="min_fuel"):
        await run_off_design(
            aircraft_name=single_aisle, mission_type="max_range", mission_range_nm=1500.0
        )


async def test_run_sizing_rejects_unknown_feedback(single_aisle):
    with pytest.raises(ValueError, match="subsystem_feedback"):
        await run_sizing(
            aircraft_name=single_aisle, subsystem_mode="precompute", subsystem_feedback="fuel"
        )


async def test_run_sizing_rejects_feedback_outside_precompute(single_aisle):
    with pytest.raises(ValueError, match="precompute"):
        await run_sizing(
            aircraft_name=single_aisle, subsystem_mode="coupled", subsystem_feedback="mission_fuel"
        )


def test_sizing_fingerprint_tracks_everything_that_changes_the_design():
    from hangar.avy.state import sizing_fingerprint

    cfg = {
        "deck": "models/x.csv",
        "overrides": {"aircraft:wing:aspect_ratio": 11.0},
        "mission": {"phase_info": {"cruise": {"user_options": {"mach": (0.78, "unitless")}}}},
        "external_subsystems": [],
    }
    base = sizing_fingerprint(cfg, "SLSQP", 50)
    assert base == sizing_fingerprint(dict(cfg), "SLSQP", 50)

    variants = [
        {**cfg, "overrides": {"aircraft:wing:aspect_ratio": 12.0}},
        {**cfg, "deck": "models/y.csv"},
        {**cfg, "mission": None},
        {**cfg, "external_subsystems": [{"name": "oas_wing_mass", "config": {}}]},
    ]
    fps = {sizing_fingerprint(v, "SLSQP", 50) for v in variants}
    fps |= {sizing_fingerprint(cfg, "IPOPT", 50), sizing_fingerprint(cfg, "SLSQP", 80)}
    assert base not in fps
    assert len(fps) == 6


async def test_sized_cache_lifecycle(single_aisle):
    from hangar.avy.state import sessions

    session = sessions.get("default")
    session.cache_sized(single_aisle, "run-1", "fp-a", prob=object())
    assert session.aircraft[single_aisle]["sized_run_id"] == "run-1"
    assert session.get_sized(single_aisle, "fp-a").run_id == "run-1"
    # a changed configuration never reuses a stale sizing
    assert session.get_sized(single_aisle, "fp-b") is None

    # reloading the template is a new design
    await load_aircraft_template(template="advanced_single_aisle", name=single_aisle)
    assert session.get_sized(single_aisle, "fp-a") is None
    assert session.aircraft[single_aisle]["sized_run_id"] is None

    session.cache_sized(single_aisle, "run-2", "fp-a", prob=object())
    session.sub_opt_cache["k"] = 1.0
    await reset()
    assert not sessions.get("default").sized
    assert not sessions.get("default").sub_opt_cache


def test_sub_opt_cache_key_is_content_based():
    from hangar.avy.runner import sub_opt_cache_key

    # no deck read when planform is upstream's hard-coded mesh
    k1 = sub_opt_cache_key({"cruise_mach": 0.78, "num_box_cp": 15}, 40000.0, None)
    k2 = sub_opt_cache_key({"num_box_cp": 15, "cruise_mach": 0.78}, 40000.0, None)
    assert k1 == k2
    assert k1 != sub_opt_cache_key({"cruise_mach": 0.78, "num_box_cp": 15}, 41000.0, None)
    assert k1 != sub_opt_cache_key({"cruise_mach": 0.79, "num_box_cp": 15}, 40000.0, None)
