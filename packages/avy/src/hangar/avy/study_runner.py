"""avy runner adapter for the SDK study layer.

Registers the ``"avy"`` runner: a case is a workflow script over the
Aviary tool registry (the same ``[{tool, args}]`` steps
``avy-cli run-script`` executes). See
:mod:`hangar.sdk.study.script_runner` for the case spec shape.

Typical case spec:

.. code-block:: yaml

    defaults:
      runner: avy
      spec:
        steps:
          - {id: aircraft, tool: load_aircraft_template,
             args: {template: advanced_single_aisle}}
          - {id: mission, tool: configure_mission, args: {target_range_nm: 1906}}
          - {id: sizing, tool: run_sizing, args: {}}
    cases:
      - matrix:
          axes: {range: {linspace: [1200, 2800, 5]}}
          bind:
            range:
              - steps[mission].args.target_range_nm
    outputs:
      - {name: gross_mass_lbm, path: "sizing:results.performance.gross_mass_lbm"}
"""

from __future__ import annotations

from hangar.sdk.study.script_runner import make_script_runner


def _build_registry():
    from hangar.avy.cli import build_avy_registry

    return build_avy_registry()


run_case, generate_case = make_script_runner("avy", _build_registry)
