"""Single source of truth for the mission-segments parity example.

Both Lane A (direct evtolpy API) and Lane B (hangar-evt MCP tools) build from
the same ``CONFIG`` dict, so any difference between the lanes is a wrapper bug
(config translation, unit handling, result harvest) rather than a difference in
inputs. ``CONFIG`` is the upstream ``sample-inputs/test-all.json`` baseline at the
pinned evtolpy ref -- the same data the ``test_all`` template ships.
"""

from __future__ import annotations

import json
from pathlib import Path

_CFG_PATH = Path(__file__).resolve().parent / "cfg" / "test-all.json"

with open(_CFG_PATH, encoding="utf-8") as _f:
    CONFIG: dict = json.load(_f)

CONFIG_PATH = str(_CFG_PATH)

# 18 mission segment attribute stems, in upstream CSV order.
SEGMENT_KEYS = [
    "depart_taxi", "hover_climb", "trans_climb", "depart_proc", "accel_climb",
    "cruise", "decel_descend", "arrive_proc", "trans_descend", "hover_descend",
    "arrive_taxi", "reserve_hover_climb", "reserve_trans_climb",
    "reserve_accel_climb", "reserve_cruise", "reserve_decel_descend",
    "reserve_trans_descend", "reserve_hover_descend",
]

# Component mass attributes (upstream mass-breakdown order).
MASS_ATTRS = [
    "wing_mass_kg", "horiz_tail_mass_kg", "vert_tail_mass_kg", "fuselage_mass_kg",
    "boom_mass_kg", "landing_gear_mass_kg", "epu_mass_kg", "lift_rotor_hub_mass_kg",
    "tilt_rotor_mass_kg", "actuator_mass_kg", "furnishings_mass_kg",
    "environmental_control_system_mass_kg", "avionics_mass_kg",
    "hivolt_power_dist_mass_kg", "lovolt_power_coms_mass_kg",
]

# Both lanes run the same pure-Python algebra, so parity should be exact to
# floating-point round-off; a tight tolerance catches any wrapper drift.
TOL = dict(rtol=1e-9, atol=1e-9)
