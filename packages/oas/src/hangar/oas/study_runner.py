"""oas runner adapter for the SDK study layer.

Registers the ``"oas"`` runner: a case is a workflow script over the OAS
tool registry (the same ``[{tool, args}]`` steps ``oas-cli run-script``
executes). See :mod:`hangar.sdk.study.script_runner` for the case spec
shape (``script``/``steps``, ``set`` patches, ``success_when``, outputs as
``"step_ref:dotted.path"``).

Typical case spec:

.. code-block:: yaml

    defaults:
      runner: oas
      spec:
        script: scripts/aero.json     # create_surface + run_aero_analysis
        success_when: {step: analyze, path: "validation.passed"}
    cases:
      - matrix:
          axes: {alpha: {linspace: [0, 8, 5]}}
          bind:
            alpha:
              - steps[analyze].args.alpha
    outputs:
      - {name: CL, path: "analyze:results.CL"}
"""

from __future__ import annotations

from hangar.sdk.study.script_runner import make_script_runner


def _build_registry():
    from hangar.oas.cli import build_oas_registry

    return build_oas_registry()


run_case, generate_case = make_script_runner("oas", _build_registry)
