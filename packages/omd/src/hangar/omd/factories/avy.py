"""Aviary sizing component factory (``avy/Sizing``) -- subprocess black box.

Aviary >=1.0 requires openmdao>=3.43 (numpy>=2) and cannot be imported in
the main workspace venv (the openconcept pin caps numpy<2), so this factory
wraps each run as a **subprocess into the isolated Aviary venv**
(``.venv-avy``, created by ``scripts/setup-avy-venv.sh``): the component's
``compute`` writes a JSON spec, executes ``avy_worker.py`` with the venv's
interpreter, and reads the results back. The same external-solver pattern
the hangar-vsp plan uses for VSPAERO.

Design notes:

- Aviary owns its own driver/DVs/objective -- every run IS an optimization
  (dymos collocation + SLSQP by default), so the component is
  **self-driving**: plan ``mode: analysis`` runs the embedded optimization.
- Plan-level DV use is possible only over ``target_range_nm`` (exposed as
  an input when configured) with finite-difference partials, at ~20 s per
  FD evaluation -- intended for sweeps/DOE via the study layer, not
  gradient optimization.
- ``converged`` (1.0/0.0) mirrors the evt black box: Aviary's optimizer
  non-convergence does not raise, so always check it.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import openmdao.api as om

from hangar.omd.factory_metadata import FactoryMetadata

_WORKER = Path(__file__).with_name("avy_worker.py")

_OUTPUT_NAMES = (
    "gross_mass_lbm",
    "total_fuel_mass_lbm",
    "operating_mass_lbm",
    "wing_mass_lbm",
    "range_nmi",
    "final_time_min",
    "converged",
)

DEFAULT_PHASE_INFO_MODULE = "aviary.models.missions.energy_state_default"


def _default_interpreter() -> Path:
    """Resolve the isolated Aviary venv's python.

    ``AVY_PYTHON`` overrides; otherwise ``.venv-avy`` relative to the cwd
    (omd runs from the repo root by convention -- same rule as the plans'
    repo-root-relative ``config_dir`` paths).
    """
    env = os.environ.get("AVY_PYTHON")
    if env:
        return Path(env)
    # absolute(), NOT resolve(): the venv python is a symlink to the base
    # interpreter, and following it would bypass the venv's site-packages.
    return Path(".venv-avy/bin/python").absolute()


class AviarySizingComp(om.ExplicitComponent):
    """Coupled aircraft-sizing + mission optimization via the avy venv."""

    def initialize(self) -> None:
        self.options.declare("deck", types=str)
        self.options.declare(
            "phase_info_module", types=str, default=DEFAULT_PHASE_INFO_MODULE
        )
        self.options.declare("target_range_nm", default=None, allow_none=True)
        self.options.declare("overrides", types=dict, default={})
        # [{"name": "oas_wing_mass", "config": {...}}]; names/configs are
        # validated in the worker (hangar.avy's registry lives in .venv-avy,
        # not here) -- only the shape is checked at build time.
        self.options.declare("external_subsystems", types=list, default=[])
        # {input_name: {"var": "aircraft:wing:mass", "units": "lbm",
        #  "initial": 15000.0}} -- each entry becomes an OpenMDAO *input*
        # whose value is written into the deck overrides per compute, so
        # another component's output (e.g. an OAS wingbox structural mass)
        # can drive an Aviary deck variable through a plan connection.
        # Units convert on the OpenMDAO connection (declare the deck
        # variable's units here); 'initial' is required because an
        # unconnected input would otherwise silently override with 0.
        self.options.declare("override_inputs", types=dict, default={})
        self.options.declare("optimizer", types=str, default="SLSQP")
        self.options.declare("max_iter", types=int, default=50)
        self.options.declare("avy_python", default=None, allow_none=True)
        self.options.declare("run_timeout_s", types=(int, float), default=900)

    def setup(self) -> None:
        if self.options["target_range_nm"] is not None:
            self.add_input(
                "target_range_nm", val=float(self.options["target_range_nm"])
            )
        for name, entry in self.options["override_inputs"].items():
            self.add_input(name, val=float(entry["initial"]), units=entry["units"])
        for name in _OUTPUT_NAMES:
            self.add_output(name, val=0.0)
        fd_inputs = list(self.options["override_inputs"])
        if self.options["target_range_nm"] is not None:
            fd_inputs.append("target_range_nm")
        if fd_inputs:
            # Each FD step is a full Aviary optimization (~20 s): fine for
            # sweeps/DOE, punishing for gradient optimization.
            self.declare_partials(
                [n for n in _OUTPUT_NAMES if n != "converged"],
                fd_inputs,
                method="fd",
            )

    def _interpreter(self) -> Path:
        python = self.options["avy_python"]
        python = Path(python) if python else _default_interpreter()
        if not python.exists():
            raise RuntimeError(
                f"Aviary venv interpreter not found at {python}. The avy/Sizing "
                "factory runs Aviary in the isolated .venv-avy (aviary needs "
                "numpy>=2 and cannot share the main venv): run "
                "`bash scripts/setup-avy-venv.sh` from the repo root, or point "
                "the component's 'avy_python' config (or $AVY_PYTHON) at it."
            )
        return python

    def compute(self, inputs, outputs) -> None:
        python = self._interpreter()

        overrides = dict(self.options["overrides"])
        for name, entry in self.options["override_inputs"].items():
            # [value, units] pair -- the worker applies it as-is, and the
            # value arrived already converted to entry['units'] by the
            # OpenMDAO connection.
            overrides[entry["var"]] = [float(inputs[name][0]), entry["units"]]

        spec: dict[str, Any] = {
            "deck": self.options["deck"],
            "phase_info_module": self.options["phase_info_module"],
            "overrides": overrides,
            "external_subsystems": self.options["external_subsystems"],
            "optimizer": self.options["optimizer"],
            "max_iter": self.options["max_iter"],
        }
        if self.options["target_range_nm"] is not None:
            spec["target_range_nm"] = float(inputs["target_range_nm"][0])

        with tempfile.TemporaryDirectory(prefix="omd_avy_") as tmp:
            spec["workdir"] = str(Path(tmp) / "run")
            spec_path = Path(tmp) / "spec.json"
            out_path = Path(tmp) / "out.json"
            spec_path.write_text(json.dumps(spec), encoding="utf-8")

            proc = subprocess.run(
                [str(python), str(_WORKER), str(spec_path), str(out_path)],
                capture_output=True,
                text=True,
                timeout=self.options["run_timeout_s"],
            )
            if proc.returncode != 0:
                tail = "\n".join(proc.stderr.strip().splitlines()[-15:])
                raise RuntimeError(
                    f"Aviary worker failed (exit {proc.returncode}). "
                    f"stderr tail:\n{tail}"
                )
            result = json.loads(out_path.read_text(encoding="utf-8"))

        for name in _OUTPUT_NAMES:
            if name == "converged":
                outputs["converged"] = 1.0 if result["success"] else 0.0
            else:
                outputs[name] = result[name]


def build_avy_sizing(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, FactoryMetadata]:
    """Build an Aviary sizing problem from plan config (``avy/Sizing``).

    Config keys: ``deck`` (required; aviary-relative CSV path),
    ``phase_info_module``, ``target_range_nm``, ``overrides``,
    ``external_subsystems`` ([{"name": ..., "config": {...}}] resolved by
    hangar.avy's registry inside the worker -- e.g. ``oas_wing_mass`` adds
    a ~40 s nested OAS wingbox sub-optimization), ``override_inputs``
    ({input_name: {var, units, initial}} -- OpenMDAO inputs whose values
    are written into the deck overrides per compute, so another
    component's output can drive an Aviary deck variable through a plan
    connection), ``optimizer``, ``max_iter``, ``avy_python``,
    ``run_timeout_s``. The operating point may override
    ``target_range_nm``.

    Returns (problem, metadata). Problem has setup NOT called.
    """
    if "deck" not in component_config:
        raise ValueError(
            "avy/Sizing requires a 'deck' config key (aviary-relative CSV "
            "path, e.g. 'models/aircraft/advanced_single_aisle/"
            "advanced_single_aisle_FLOPS.csv')."
        )
    subsystem_specs = component_config.get("external_subsystems", [])
    for entry in subsystem_specs:
        if not isinstance(entry, dict) or "name" not in entry:
            raise ValueError(
                "avy/Sizing external_subsystems entries must be dicts with a "
                f"'name' key (optional 'config'), got {entry!r}."
            )
    override_inputs = component_config.get("override_inputs", {})
    for name, entry in override_inputs.items():
        if name in _OUTPUT_NAMES:
            raise ValueError(
                f"avy/Sizing override_inputs name {name!r} collides with a "
                f"component output; pick another (e.g. '{name.replace('_lbm', '')}"
                "_override_lbm')."
            )
        missing = {"var", "units", "initial"} - set(entry if isinstance(entry, dict) else ())
        if missing:
            raise ValueError(
                f"avy/Sizing override_inputs[{name!r}] must be a dict with "
                f"'var', 'units', and 'initial' keys; missing {sorted(missing)}. "
                "'initial' is required -- an unconnected input would "
                "otherwise silently override the deck variable with 0."
            )

    target_range_nm = operating_points.get(
        "target_range_nm", component_config.get("target_range_nm")
    )

    comp = AviarySizingComp(
        deck=component_config["deck"],
        phase_info_module=component_config.get(
            "phase_info_module", DEFAULT_PHASE_INFO_MODULE
        ),
        target_range_nm=target_range_nm,
        overrides=component_config.get("overrides", {}),
        external_subsystems=list(subsystem_specs),
        override_inputs=dict(override_inputs),
        optimizer=component_config.get("optimizer", "SLSQP"),
        max_iter=int(component_config.get("max_iter", 50)),
        avy_python=component_config.get("avy_python"),
        run_timeout_s=component_config.get("run_timeout_s", 900),
    )

    prob = om.Problem(reports=False)
    prob.model.add_subsystem("aviary", comp, promotes=["*"])

    var_paths = {name: name for name in _OUTPUT_NAMES}
    initial_values: dict[str, Any] = {}
    if target_range_nm is not None:
        var_paths["target_range_nm"] = "target_range_nm"
        initial_values["target_range_nm"] = float(target_range_nm)
    for name in override_inputs:
        var_paths[name] = name

    metadata: FactoryMetadata = {
        "point_name": "aviary",
        "output_names": list(_OUTPUT_NAMES),
        "var_paths": var_paths,
        "initial_values": initial_values,
        "component_family": "avy",
    }
    return prob, metadata
