"""Study-level 2-axis trade-grid plots over a study's ``cases.csv``.

This is the study counterpart to per-run :mod:`hangar.omd.plotting`: instead
of rendering one OpenMDAO recorder, it pivots a whole study's case table over
its two numeric grid axes and renders one heatmap panel per output column.
The panel policy is tool-specific and dispatched by the study's
``component_type`` through the study-plot provider registry (see
``register_study_plots`` in :mod:`hangar.omd.registry`); OCP mission studies
get the Brelje 2018a Fig 5/6 four-panel layout. Studies whose component type
has no provider fall back to a generic grid, one panel per numeric output.

Gating condition: the study must have exactly two numeric axes. Anything
else raises ``ValueError`` (the backlog item's contract).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import yaml

from hangar.omd.plotting._common import to_float_array
from hangar.sdk.study import SUCCESS_STATUSES, StudyStore, load_study

logger = logging.getLogger(__name__)

# cases.csv / case-entry columns that are never plottable output values.
_NON_OUTPUT_COLS = {
    "case_id", "case_key", "status", "runner", "run_ref",
    "wall_time_s", "error", "in_spec", "source", "attempts",
}


def _matrix_axes(spec: dict) -> list[str]:
    """Axis names across all matrix blocks, in first-seen order."""
    axes: list[str] = []
    for block in spec.get("cases") or []:
        kind, body = next(iter(block.items()))
        if kind == "matrix":
            for name in (body.get("axes") or {}):
                if name not in axes:
                    axes.append(name)
    return axes


def _resolve_component_type(store: StudyStore) -> str | None:
    """Read the component type from any generated case plan, if present."""
    cases_dir = store.dir / "cases"
    if not cases_dir.is_dir():
        return None
    for plan_path in sorted(cases_dir.glob("*/*.yaml")):
        try:
            doc = yaml.safe_load(plan_path.read_text()) or {}
            components = doc.get("components") or []
            if components:
                ctype = components[0].get("type")
                if ctype:
                    return ctype
        except Exception as exc:
            logger.debug("Could not read component type from %s: %s",
                         plan_path, exc)
    return None


def _build_table(state: dict, axes: list[str]) -> dict:
    """Columnar case table (column -> per-case list), pandas-free.

    Each case contributes its params plus, for converged cases only, the
    recorded outputs. Missing cells are ``None`` so they coerce to NaN (and
    render blank) downstream rather than poisoning a panel.
    """
    rows: list[dict] = []
    for entry in state.get("cases", {}).values():
        if not entry.get("in_spec", True):
            continue
        row: dict = dict(entry.get("params") or {})
        row["status"] = entry.get("status")
        if entry.get("status") in SUCCESS_STATUSES:
            row.update(entry.get("outputs") or {})
        rows.append(row)
    if not rows:
        raise ValueError("study has no in-spec cases to plot")

    columns: list[str] = []
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    table = {col: [row.get(col) for row in rows] for col in columns}

    for axis in axes:
        if axis not in table:
            raise ValueError(f"axis {axis!r} is not a case parameter column")
        if not np.isfinite(to_float_array(table[axis])).any():
            raise ValueError(f"axis {axis!r} is not numeric")
    return table


def _numeric_output_columns(table: dict, axes: list[str]) -> list[str]:
    """Output columns holding at least one finite value (generic fallback)."""
    cols: list[str] = []
    for col in table:
        if col in _NON_OUTPUT_COLS or col in axes:
            continue
        if np.isfinite(to_float_array(table[col])).any():
            cols.append(col)
    return cols


def study_plot_types(study_id: str) -> list[str]:
    """List the study-plot names available for *study_id* (no rendering).

    Resolves the study's two grid axes and component type, then returns the
    study-plot provider's plot names, or ``["grid"]`` for the generic
    per-output-column fallback. Returns ``[]`` (never raises) when the study
    cannot be grid-plotted -- missing state, not exactly two numeric axes, or
    no numeric output columns -- so a caller (the dashboard study panel, the
    MCP surface) can list plots without guarding each failure mode itself.
    """
    from hangar.omd.registry import get_study_plot_provider

    try:
        store = StudyStore(study_id)
        spec_path = store.dir / "study.yaml"
        if not store.state_path.exists() or not spec_path.exists():
            return []
        spec, errors = load_study(spec_path)
        if errors:
            return []
        axes = _matrix_axes(spec)
        if len(axes) != 2:
            return []
        table = _build_table(store.load_state(), axes)
        provider = get_study_plot_provider(_resolve_component_type(store))
        if provider:
            return list(provider.keys())
        return ["grid"] if _numeric_output_columns(table, axes) else []
    except Exception as exc:  # noqa: BLE001 -- listing must never raise
        logger.debug("study_plot_types(%s) unavailable: %s", study_id, exc)
        return []


def plot_study(
    study_id: str,
    *,
    plot_types: list[str] | None = None,
    style: str = "paper",
    out_dir: Path | None = None,
) -> dict:
    """Render a study's 2-axis trade-grid figure(s).

    Args:
        study_id: ``metadata.id`` of the study.
        plot_types: provider plot names to render (default: all the
            provider offers, or the generic grid when no provider exists).
        style: ``"paper"`` (pcolormesh) or ``"contour"``.
        out_dir: output directory (default ``studies/{id}/plots``).

    Returns:
        ``{study_id, component_type, axes, style, saved, out_dir}`` where
        ``saved`` maps plot name to PNG path.

    Raises:
        ValueError: no study state, or not exactly two numeric axes.
    """
    from hangar.omd.plotting import MPL_RENDER_LOCK, atomic_savefig
    from hangar.omd.plotting._common import PanelSpec, render_grid
    from hangar.omd.registry import get_study_plot_provider

    import matplotlib.pyplot as plt

    store = StudyStore(study_id)
    if not store.state_path.exists():
        raise ValueError(f"no state for study {study_id!r} under {store.dir}")

    spec_path = store.dir / "study.yaml"
    if not spec_path.exists():
        raise ValueError(f"no study.yaml snapshot for {study_id!r}")
    spec, errors = load_study(spec_path)
    if errors:
        raise ValueError(f"study spec {study_id!r} is invalid: {errors}")

    axes = _matrix_axes(spec)
    if len(axes) != 2:
        raise ValueError(
            f"study {study_id!r} has {len(axes)} matrix axis/axes "
            f"{axes}; 2-axis grid plots require exactly 2 numeric axes")
    x_axis, y_axis = axes

    state = store.load_state()
    table = _build_table(state, axes)

    component_type = _resolve_component_type(store)
    provider = get_study_plot_provider(component_type)

    out_dir = Path(out_dir) if out_dir else (store.dir / "plots")
    out_dir.mkdir(parents=True, exist_ok=True)

    title = f"{study_id} ({component_type or 'study'})"
    saved: dict[str, Path] = {}

    if provider:
        names = plot_types or list(provider.keys())
        for name in names:
            func = provider.get(name)
            if func is None:
                logger.warning("Unknown study plot type %r for %s",
                               name, component_type)
                continue
            try:
                with MPL_RENDER_LOCK:
                    fig = func(table, x_axis, y_axis, style=style, suptitle=title)
                    try:
                        path = out_dir / f"{name}.png"
                        atomic_savefig(fig, path, dpi=150)
                    finally:
                        plt.close(fig)
                saved[name] = path
            except Exception as exc:
                logger.warning("Skipping study plot %r: %s", name, exc)
    else:
        # Generic fallback: one panel per numeric output column.
        cols = _numeric_output_columns(table, axes)
        if not cols:
            raise ValueError(
                f"study {study_id!r} has no numeric output columns to plot")
        panels = [PanelSpec(col, col) for col in cols]
        with MPL_RENDER_LOCK:
            fig = render_grid(table, x_axis, y_axis, panels, style=style,
                              suptitle=title)
            try:
                path = out_dir / "grid.png"
                atomic_savefig(fig, path, dpi=150)
            finally:
                plt.close(fig)
        saved["grid"] = path

    return {
        "study_id": study_id,
        "component_type": component_type,
        "axes": [x_axis, y_axis],
        "style": style,
        "saved": {k: str(v) for k, v in saved.items()},
        "out_dir": str(out_dir),
    }
