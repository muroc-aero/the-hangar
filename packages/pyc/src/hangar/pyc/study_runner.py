"""pyc runner adapter for the SDK study layer.

Registers the ``"pyc"`` runner: a case is a workflow script over the
pyCycle tool registry (the same ``[{tool, args}]`` steps
``pyc-cli run-script`` executes). See
:mod:`hangar.sdk.study.script_runner` for the case spec shape.

Typical case spec:

.. code-block:: yaml

    defaults:
      runner: pyc
      spec:
        steps:
          - {id: engine, tool: create_engine,
             args: {name: tj, archetype: turbojet}}
          - {id: design, tool: run_design_point, args: {engine_name: tj}}
    cases:
      - matrix:
          axes: {T4: {linspace: [2800, 3400, 4]}}
          bind:
            T4:
              - steps[design].args.T4_target
    outputs:
      - {name: TSFC, path: "design:results.performance.TSFC"}
"""

from __future__ import annotations

from hangar.sdk.study.script_runner import make_script_runner


def _build_registry():
    from hangar.pyc.cli import build_pyc_registry

    return build_pyc_registry()


run_case, generate_case = make_script_runner("pyc", _build_registry)
