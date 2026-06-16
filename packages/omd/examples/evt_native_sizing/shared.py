"""Shared constants for the native-evt eVTOL sizing example.

The three lanes all size the same Archer Midnight lift+cruise eVTOL from the
AIAA SciTech 2026 vendored config grid (the same ``cfg/`` files the evt
``abu_scitech_2026`` example uses), through the native OpenMDAO formulation of
evtolpy (``hangar.omd.evt`` / the ``evt/Sizing`` factory).
"""

from __future__ import annotations

from pathlib import Path

# Repo-root-relative config (the factory resolves ``config_dir/config_name``
# the same way; Lane A loads the JSON directly). Run omd from the repo root.
CONFIG_DIR = "packages/evt/examples/abu_scitech_2026/cfg"
CONFIG_NAME = "archer-midnight-1500-30"

# Absolute path for Lane A's direct JSON load (independent of cwd).
_REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_PATH = _REPO_ROOT / CONFIG_DIR / f"{CONFIG_NAME}.json"

# Native MTOW-closure solver: "newton" (gradient-friendly default) or "gs".
SOLVER = "newton"

# Golden sized values, pinned from the native model at this config (which
# matches upstream evtolpy to floating point). A 1e-4 anchor catches physics
# drift on an upstream pin bump without tripping on platform float noise.
GOLDEN = dict(
    sized_mtow_kg=2019.475,
    total_mission_energy_kw_hr=65.9496,
    peak_power_kw=846.521,
)
# Tolerance dicts are consumed by ``pytest.approx`` (rel/abs keys).
TOL_GOLDEN = dict(rel=1e-4)

# Lane-to-lane parity: the plan pipeline (Lane B) and the MCP tool surface
# (Lane C) drive the *same* native problem Lane A builds, so they must agree to
# round-off, not just to engineering tolerance.
TOL_PARITY = dict(rel=1e-9, abs=1e-9)

# Analytic-vs-FD check for the gradient demo (the native model's headline
# capability the black box lacks). CS-exact totals vs a coarse forward
# difference agree to a few parts in 1e4.
TOL_GRADIENT = dict(rel=2e-3)
