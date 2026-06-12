"""Study spec validation.

A study.yaml declares many analysis cases over a shared default runner:

.. code-block:: yaml

    metadata:
      id: brelje-2018a-fig5
      name: "Brelje 2018a Fig 5 grid"
      version: 1

    defaults:
      runner: omd                  # default runner for every case
      spec:                        # runner-specific defaults merged into cases
        plan: lane_b/fuel_mdo/plan.yaml
        mode: optimize

    cases:
      - matrix:                    # DOE-style cartesian expansion
          id_template: "r{design_range_nm:g}-e{spec_energy_whkg:g}"
          axes:
            design_range_nm:  {linspace: [300, 800, 11]}
            spec_energy_whkg: {values: [250, 300, 400]}
          bind:                    # every axis must bind to >=1 spec path
            design_range_nm:
              - components[mission].config.mission_params.mission_range_NM
            spec_energy_whkg:
              - components[mission].config.mission_params.battery_specific_energy
      - case:                      # manual insertion of an arbitrary case
          id: paper-ref-500-250
          params: {design_range_nm: 500, spec_energy_whkg: 250}
          spec: {plan: lane_c/ref_500_250/plan.yaml}

    multistart:                    # optional: N variants per case, keep best
      presets:
        low:  {initial: {"cruise.hybridization": 0.05}}
        high: {initial: {"cruise.hybridization": 0.95}}
      pick: {output: objective_value, mode: min}

    execution:
      workers: 4
      est_case_seconds: 120        # seeds the review-time estimate
      review_threshold: 50         # run() refuses more pending cases than
                                   # this without confirm/max_cases
      guard_max_cases: 1000        # expansion hard cap

    outputs:                       # case-table columns (paths are
      - {name: MTOW_kg, path: "ac|weights|MTOW"}   # runner-interpreted)

Validation is hand-rolled (the spec is small) so the SDK does not grow a
jsonschema dependency. Errors are ``{path, message}`` dicts matching the
omd plan validator's shape.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# Statuses a case can carry in the study state. SUCCESS_STATUSES lives in
# orchestrate.py; listed here for reference only.
_PICK_MODES = ("min", "max")

DEFAULT_REVIEW_THRESHOLD = 50
DEFAULT_GUARD_MAX_CASES = 1000


def _err(path: str, message: str) -> dict:
    return {"path": path, "message": message}


def _check_metadata(spec: dict, errors: list[dict]) -> None:
    meta = spec.get("metadata")
    if not isinstance(meta, dict):
        errors.append(_err("metadata", "required and must be a mapping"))
        return
    sid = meta.get("id")
    if not sid or not isinstance(sid, str):
        errors.append(_err("metadata.id", "required non-empty string"))
    elif any(c in sid for c in "/\\") or ".." in sid:
        errors.append(_err("metadata.id", f"unsafe characters in {sid!r}"))
    if not meta.get("name") or not isinstance(meta.get("name"), str):
        errors.append(_err("metadata.name", "required non-empty string"))
    version = meta.get("version", 1)
    if not isinstance(version, int) or version < 1:
        errors.append(_err("metadata.version", "must be an integer >= 1"))


def _check_axis(name: str, axis: Any, path: str, errors: list[dict]) -> None:
    if not isinstance(axis, dict):
        errors.append(_err(path, "axis must be a mapping with 'values' or 'linspace'"))
        return
    has_values = "values" in axis
    has_linspace = "linspace" in axis
    if has_values == has_linspace:
        errors.append(_err(path, "axis needs exactly one of 'values' or 'linspace'"))
        return
    if has_values:
        vals = axis["values"]
        if not isinstance(vals, list) or not vals:
            errors.append(_err(f"{path}.values", "must be a non-empty list"))
    else:
        ls = axis["linspace"]
        if (not isinstance(ls, list) or len(ls) != 3
                or not all(isinstance(v, (int, float)) for v in ls)
                or not isinstance(ls[2], int) or ls[2] < 2):
            errors.append(_err(
                f"{path}.linspace",
                "must be [start, stop, num] with integer num >= 2"))


def _check_matrix_block(block: dict, path: str, errors: list[dict]) -> None:
    axes = block.get("axes")
    if not isinstance(axes, dict) or not axes:
        errors.append(_err(f"{path}.axes", "required non-empty mapping"))
        axes = {}
    for name, axis in axes.items():
        _check_axis(name, axis, f"{path}.axes.{name}", errors)

    # Every axis must bind to at least one spec path -- an unbound axis
    # would silently produce identical cases (the same failure mode as
    # OAS silently ignoring unknown DV names).
    bind = block.get("bind")
    if not isinstance(bind, dict):
        errors.append(_err(f"{path}.bind", "required mapping of axis -> spec path list"))
        bind = {}
    for name in axes:
        paths = bind.get(name)
        if not isinstance(paths, list) or not paths:
            errors.append(_err(
                f"{path}.bind.{name}",
                f"axis {name!r} has no bind paths; every axis must bind "
                "to at least one spec path"))
    for name in bind:
        if name not in axes:
            errors.append(_err(f"{path}.bind.{name}", f"bind for unknown axis {name!r}"))

    tmpl = block.get("id_template")
    if tmpl is not None and not isinstance(tmpl, str):
        errors.append(_err(f"{path}.id_template", "must be a string"))


def _check_case_block(block: dict, path: str, errors: list[dict]) -> None:
    if not block.get("id") or not isinstance(block.get("id"), str):
        errors.append(_err(f"{path}.id", "required non-empty string"))
    if not isinstance(block.get("spec"), dict) or not block["spec"]:
        errors.append(_err(f"{path}.spec", "required non-empty mapping (runner payload)"))
    params = block.get("params")
    if params is not None and not isinstance(params, dict):
        errors.append(_err(f"{path}.params", "must be a mapping"))


def _check_cases(spec: dict, errors: list[dict]) -> None:
    cases = spec.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append(_err("cases", "required non-empty list of matrix/case blocks"))
        return
    for i, block in enumerate(cases):
        path = f"cases[{i}]"
        if not isinstance(block, dict) or len(block) != 1:
            errors.append(_err(path, "each entry must be a single-key mapping: "
                                     "'matrix' or 'case'"))
            continue
        kind, body = next(iter(block.items()))
        if kind == "matrix":
            _check_matrix_block(body or {}, f"{path}.matrix", errors)
        elif kind == "case":
            _check_case_block(body or {}, f"{path}.case", errors)
        else:
            errors.append(_err(path, f"unknown case block kind {kind!r} "
                                     "(expected 'matrix' or 'case')"))


def _check_multistart(spec: dict, errors: list[dict]) -> None:
    ms = spec.get("multistart")
    if ms is None:
        return
    if not isinstance(ms, dict):
        errors.append(_err("multistart", "must be a mapping"))
        return
    presets = ms.get("presets")
    if not isinstance(presets, dict) or not presets:
        errors.append(_err("multistart.presets", "required non-empty mapping"))
    else:
        for name, payload in presets.items():
            if not isinstance(payload, dict):
                errors.append(_err(f"multistart.presets.{name}",
                                   "preset payload must be a mapping"))
    pick = ms.get("pick")
    if not isinstance(pick, dict) or not pick.get("output"):
        errors.append(_err("multistart.pick",
                           "required mapping with 'output' (and optional "
                           "'mode': min|max)"))
    elif pick.get("mode", "min") not in _PICK_MODES:
        errors.append(_err("multistart.pick.mode", f"must be one of {_PICK_MODES}"))


def _check_execution(spec: dict, errors: list[dict]) -> None:
    ex = spec.get("execution")
    if ex is None:
        return
    if not isinstance(ex, dict):
        errors.append(_err("execution", "must be a mapping"))
        return
    for key in ("workers", "review_threshold", "guard_max_cases"):
        val = ex.get(key)
        if val is not None and (not isinstance(val, int) or val < 1):
            errors.append(_err(f"execution.{key}", "must be an integer >= 1"))
    est = ex.get("est_case_seconds")
    if est is not None and (not isinstance(est, (int, float)) or est <= 0):
        errors.append(_err("execution.est_case_seconds", "must be a positive number"))


def _check_outputs(spec: dict, errors: list[dict]) -> None:
    outs = spec.get("outputs")
    if outs is None:
        return
    if not isinstance(outs, list):
        errors.append(_err("outputs", "must be a list of {name, path} mappings"))
        return
    seen: set[str] = set()
    for i, out in enumerate(outs):
        if not isinstance(out, dict) or not out.get("name") or not out.get("path"):
            errors.append(_err(f"outputs[{i}]", "must have 'name' and 'path'"))
            continue
        if out["name"] in seen:
            errors.append(_err(f"outputs[{i}].name", f"duplicate output {out['name']!r}"))
        seen.add(out["name"])


def _check_defaults(spec: dict, errors: list[dict]) -> None:
    defaults = spec.get("defaults")
    if defaults is None:
        return
    if not isinstance(defaults, dict):
        errors.append(_err("defaults", "must be a mapping"))
        return
    runner = defaults.get("runner")
    if runner is not None and (not runner or not isinstance(runner, str)):
        errors.append(_err("defaults.runner", "must be a non-empty string"))
    dspec = defaults.get("spec")
    if dspec is not None and not isinstance(dspec, dict):
        errors.append(_err("defaults.spec", "must be a mapping"))


_KNOWN_TOP_KEYS = {
    "metadata", "defaults", "cases", "multistart", "execution", "outputs",
}


def validate_study(spec: dict) -> list[dict]:
    """Validate a study spec dict. Returns a list of {path, message} errors."""
    errors: list[dict] = []
    if not isinstance(spec, dict):
        return [_err("", "study spec must be a mapping")]
    for key in spec:
        if key not in _KNOWN_TOP_KEYS:
            errors.append(_err(key, f"unknown top-level key {key!r} "
                                    f"(expected one of {sorted(_KNOWN_TOP_KEYS)})"))
    _check_metadata(spec, errors)
    _check_defaults(spec, errors)
    _check_cases(spec, errors)
    _check_multistart(spec, errors)
    _check_execution(spec, errors)
    _check_outputs(spec, errors)
    return errors


def load_study(path: Path | str) -> tuple[dict | None, list[dict]]:
    """Load and validate a study.yaml. Returns (spec, errors).

    On schema errors spec is still returned (when parseable) so callers
    can show partial context; treat any non-empty errors as fatal.
    """
    path = Path(path)
    try:
        spec = yaml.safe_load(path.read_text())
    except Exception as exc:
        return None, [_err(str(path), f"failed to parse YAML: {exc}")]
    errors = validate_study(spec if isinstance(spec, dict) else {})
    return (spec if isinstance(spec, dict) else None), errors
