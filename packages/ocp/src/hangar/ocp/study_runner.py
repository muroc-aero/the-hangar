"""ocp runner adapter for the SDK study layer.

Registers the ``"ocp"`` runner: a case is a workflow script over the
OpenConcept tool registry (the same ``[{tool, args}]`` steps
``ocp-cli run-script`` executes). See
:mod:`hangar.sdk.study.script_runner` for the case spec shape.

Typical case spec:

.. code-block:: yaml

    defaults:
      runner: ocp
      spec:
        steps:
          - {id: ac, tool: load_aircraft_template, args: {template: kingair}}
          - {id: prop, tool: set_propulsion_architecture, args: {architecture: turboprop}}
          - {id: mission, tool: configure_mission,
             args: {mission_type: basic, cruise_range_nm: 300}}
          - {id: run, tool: run_mission_analysis, args: {}}
    cases:
      - matrix:
          axes: {range: {linspace: [200, 600, 5]}}
          bind:
            range:
              - steps[mission].args.cruise_range_nm
    outputs:
      - {name: fuel_kg, path: "run:results.fuel_burn_kg"}
"""

from __future__ import annotations

from hangar.sdk.study.script_runner import make_script_runner


def _build_registry():
    from hangar.ocp.cli import build_ocp_registry

    return build_ocp_registry()


run_case, generate_case = make_script_runner("ocp", _build_registry)
