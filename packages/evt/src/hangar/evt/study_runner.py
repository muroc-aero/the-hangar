"""evt runner adapter for the SDK study layer.

Registers the ``"evt"`` runner: a case is a workflow script over the evt
tool registry (the same ``[{tool, args}]`` steps ``evt-cli run-script``
executes). See :mod:`hangar.sdk.study.script_runner` for the case spec shape.

Typical case spec:

.. code-block:: yaml

    defaults:
      runner: evt
      spec:
        steps:
          - {id: load, tool: load_vehicle_template, args: {template: test_all}}
          - {id: mission, tool: run_mission_analysis, args: {}}
    cases:
      - matrix:
          axes: {Eb: {linspace: [200, 320, 4]}}
          bind:
            Eb:
              - steps[load].args  # (illustrative; bind into a set_power step)
    outputs:
      - {name: E_total, path: "mission:results.totals.total_mission_energy_kw_hr"}
"""

from __future__ import annotations

from hangar.sdk.study.script_runner import make_script_runner


def _build_registry():
    from hangar.evt.cli import build_evt_registry

    return build_evt_registry()


run_case, generate_case = make_script_runner("evt", _build_registry)
