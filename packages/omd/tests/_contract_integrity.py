"""Helpers for Fix 3 factory-contract integrity tests.

``validate_contract_integrity`` runs a factory with its minimal default
config, completes ``setup()`` + ``final_setup()``, and compares the
declared ``FactoryContract.produces`` against the OpenMDAO model's
actual promoted inputs. A second pass exercises ``skip_fields`` to
confirm each declared-produced name falls off the internal IVC when
requested.

Only used in pytest. Not part of the public omd API.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import openmdao.api as om


@dataclass
class IntegrityReport:
    declared_but_absent: list[str] = field(default_factory=list)
    absent_but_present: list[str] = field(default_factory=list)
    units_mismatch: list[tuple[str, str | None, str | None]] = field(
        default_factory=list,
    )
    shape_mismatch: list[tuple[str, tuple | None, tuple | None]] = field(
        default_factory=list,
    )
    skip_fields_not_honored: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(
            self.declared_but_absent
            or self.units_mismatch
            or self.shape_mismatch
            or self.skip_fields_not_honored
        )

    def summary(self) -> str:
        lines: list[str] = []
        if self.declared_but_absent:
            lines.append(
                f"declared-but-absent: {self.declared_but_absent}"
            )
        if self.absent_but_present:
            lines.append(
                f"absent-but-present: {self.absent_but_present}"
            )
        if self.units_mismatch:
            lines.append(
                f"units mismatch: {self.units_mismatch}"
            )
        if self.shape_mismatch:
            lines.append(
                f"shape mismatch: {self.shape_mismatch}"
            )
        if self.skip_fields_not_honored:
            lines.append(
                f"skip_fields not honored: {self.skip_fields_not_honored}"
            )
        return "\n".join(lines) or "ok"


def _promoted_root_metadata(prob: om.Problem) -> dict[str, dict]:
    """Return {promoted_name: {units, shape, kind}} for root-promoted vars.

    ``kind`` is ``"output"`` for IVC-driven (internally produced) vars,
    or ``"input"`` for undriven promoted inputs. Names containing a
    dot are scoped below subsystems and excluded.
    """
    result: dict[str, dict] = {}
    outputs = prob.model.list_outputs(
        val=True,
        units=True,
        shape=True,
        prom_name=True,
        out_stream=None,
        return_format="list",
    )
    for _abs_path, meta in outputs:
        prom = meta.get("prom_name", "")
        if not isinstance(prom, str) or "." in prom:
            continue
        if prom in result:
            continue
        result[prom] = {
            "units": meta.get("units"),
            "shape": (
                tuple(meta.get("shape"))
                if meta.get("shape") is not None else None
            ),
            "kind": "output",
        }

    inputs = prob.model.list_inputs(
        val=True,
        units=True,
        shape=True,
        prom_name=True,
        out_stream=None,
        return_format="list",
    )
    for _abs_path, meta in inputs:
        prom = meta.get("prom_name", "")
        if not isinstance(prom, str) or "." in prom:
            continue
        if prom in result:
            continue
        result[prom] = {
            "units": meta.get("units"),
            "shape": (
                tuple(meta.get("shape"))
                if meta.get("shape") is not None else None
            ),
            "kind": "input",
        }
    return result


def _promoted_input_sources(prob: om.Problem) -> dict[str, str]:
    """Return {promoted_input: absolute_source_output} from model conns."""
    try:
        conns = prob.model._conn_global_abs_in2out
    except AttributeError:
        return {}
    model = prob.model
    sources: dict[str, str] = {}
    for tgt_abs, src_abs in conns.items():
        try:
            tgt_prom = model._var_abs2prom["input"].get(tgt_abs)
        except AttributeError:
            tgt_prom = None
        if not isinstance(tgt_prom, str) or "." in tgt_prom:
            continue
        sources[tgt_prom] = src_abs
    return sources


def validate_contract_integrity(
    factory_fn,
    default_config: dict,
    default_operating_points: dict,
) -> IntegrityReport:
    """Check a factory's declared FactoryContract against its actual model.

    ``default_config`` and ``default_operating_points`` are the minimal
    args the factory needs to succeed at ``setup()``. They are mutated
    locally (``_defer_setup`` is injected) but the caller's objects are
    not touched.

    Returns an :class:`IntegrityReport` which is truthy iff any failure
    was detected. Shape `(1,)` and an unset declared shape are treated
    as compatible (OpenMDAO infers `(1,)` for scalar outputs).
    """
    contract = getattr(factory_fn, "contract", None)
    if contract is None:
        raise RuntimeError(
            f"Factory {factory_fn.__name__} has no .contract attribute"
        )

    report = IntegrityReport()

    # Pass 1: factory with its declared defaults -- compare promoted
    # inputs vs declared produces.
    cfg = dict(default_config)
    prob, _meta = factory_fn(cfg, dict(default_operating_points))
    try:
        prob.setup(check=False, mode="fwd")
        prob.final_setup()
        prom_vars = _promoted_root_metadata(prob)

        for name, spec in contract.produces.items():
            if name not in prom_vars:
                report.declared_but_absent.append(name)
                continue
            actual = prom_vars[name]
            declared_units = spec.units
            actual_units = actual["units"]
            # Only check units when the contract declares one; a
            # declared value of ``None`` means "template-dependent".
            if declared_units is not None and declared_units != actual_units:
                report.units_mismatch.append(
                    (name, declared_units, actual_units)
                )
            declared_shape = spec.shape
            actual_shape = actual["shape"]
            # `(1,)` == unset scalar (OpenMDAO infers this shape).
            declared_norm = declared_shape or (1,)
            if actual_shape is not None and declared_norm != actual_shape:
                report.shape_mismatch.append(
                    (name, declared_shape, actual_shape)
                )
    finally:
        prob.cleanup()

    # Pass 2: rerun the factory ONCE PER declared produced name with
    # that name in skip_fields. Per-name avoids the OpenMDAO "empty
    # IVC" error that triggers when *every* field is skipped (OAS
    # builds a single ``prob_vars`` IVC that must contain at least
    # one output).
    for name in contract.produces:
        cfg = dict(default_config)
        existing = list(cfg.get("skip_fields") or [])
        cfg["skip_fields"] = existing + [name]
        try:
            prob2, _meta2 = factory_fn(cfg, dict(default_operating_points))
        except Exception:  # noqa: BLE001
            # A factory that crashes when asked to skip a field it
            # declared is drift; treat as not-honored.
            report.skip_fields_not_honored.append(name)
            continue
        try:
            try:
                prob2.setup(check=False, mode="fwd")
                prob2.final_setup()
            except RuntimeError as exc:
                # Skipping a name from the internal IVC leaves it as
                # an undriven promoted input. If multiple downstream
                # subsystems promote the same name with different
                # default metadata, OpenMDAO raises an "ambiguity"
                # RuntimeError. This is EXPECTED -- the shared IVC
                # resolves it at runtime. If we see this specific
                # error for the skipped name, treat it as honored.
                msg = str(exc)
                if (
                    "are connected but their metadata entries" in msg
                    and f"promoted to '{name}'" in msg
                ):
                    continue
                raise
            sources = _promoted_input_sources(prob2)
            src = sources.get(name)
            # When skip_fields drops a name from the internal IVC
            # and no external source is wired up, the input either
            # has no source or points to OpenMDAO's ``_auto_ivc``
            # placeholder -- both are "factory honored the skip".
            if src is None or "_auto_ivc" in src:
                pass
            else:
                report.skip_fields_not_honored.append(name)
        finally:
            prob2.cleanup()

    return report


__all__ = ["IntegrityReport", "validate_contract_integrity"]
