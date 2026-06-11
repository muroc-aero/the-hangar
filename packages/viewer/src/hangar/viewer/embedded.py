"""Embedded (in-process) plot rendering entry point.

The boundary doc's target contract for the range-safety dashboard's plot
adapter is ``hangar.viewer.embedded.generate_plot_png``; the adapter
already probes this module first and falls back to ``hangar.sdk.viz``.
Today the implementation lives in ``hangar.sdk.viz.viewer_server``;
re-export it here so the contract import path works ahead of the full
viewer split (the deferred sdk/viz relocation noted in the repo review).
"""

from __future__ import annotations

from hangar.sdk.viz.viewer_server import generate_plot_png

__all__ = ["generate_plot_png"]
