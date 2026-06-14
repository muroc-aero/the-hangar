"""Smoke test for the evtol study runner registration."""

from hangar.evtol.study_runner import generate_case, run_case


def test_study_runner_callables():
    # make_script_runner returns (run_case, generate_case) callables bound to
    # the evtol registry; importing must not raise and both must be callable.
    assert callable(run_case)
    assert callable(generate_case)


def test_registry_builds():
    from hangar.evtol.cli import build_evtol_registry

    reg = build_evtol_registry()
    for required in (
        "load_vehicle_template", "run_mission_analysis", "run_sizing",
        "run_parameter_sweep", "start_session", "export_session_graph",
    ):
        assert required in reg, required
