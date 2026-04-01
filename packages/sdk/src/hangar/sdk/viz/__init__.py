"""Visualization subpackage for hangar SDK.

Provides plotting, widget support, provenance viewer, and DAG export.
"""

from hangar.sdk.viz.export import export_session_graph
from hangar.sdk.viz.plotting import (
    PLOT_TYPES,
    N2Result,
    PlotResult,
    generate_n2,
    generate_plot,
)
from hangar.sdk.viz.viewer_server import (
    ANALYSIS_PLOT_TYPES,
    generate_dashboard_html,
    generate_plot_png,
    get_plot_types_for_run,
    register_plot_types,
    start_viewer_server,
)
from hangar.sdk.viz.widget import DASHBOARD_HTML, extract_plot_data

__all__ = [
    "ANALYSIS_PLOT_TYPES",
    "DASHBOARD_HTML",
    "N2Result",
    "PLOT_TYPES",
    "PlotResult",
    "export_session_graph",
    "extract_plot_data",
    "generate_dashboard_html",
    "generate_n2",
    "generate_plot",
    "generate_plot_png",
    "get_plot_types_for_run",
    "register_plot_types",
    "start_viewer_server",
]
