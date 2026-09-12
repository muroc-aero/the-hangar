"""Fixed-profile adaptation of the upstream BWB benchmark mission.

Derived programmatically from
``aviary.validation_cases.benchmark_tests.test_bwb_FwFm.phase_info`` (the
M0.85 / 7750 nmi transpacific mission) with the mach/altitude optimization
turned off and the climb profile pinned (500 ft / M0.3 -> 35000 ft /
M0.85). The upstream mission needs SNOPT/IPOPT; this fixed-profile variant
converges under SLSQP in ~12 s and lands within ~1.5% of the published
SNOPT benchmark values (gross 782,430 lbm / fuel 239,188 lbm) -- the small
fuel excess is the cost of not optimizing the profile.

Deriving (rather than copying) from the upstream module means an AVY_REF
pin bump flows through automatically; if upstream renames the module this
import fails loudly.
"""

from __future__ import annotations

import copy
import importlib


def _build() -> dict:
    mod = importlib.import_module(
        "aviary.validation_cases.benchmark_tests.test_bwb_FwFm"
    )
    phase_info = copy.deepcopy(mod.phase_info)
    for phase in ("climb", "cruise", "descent"):
        phase_info[phase]["user_options"]["mach_optimize"] = False
        phase_info[phase]["user_options"]["altitude_optimize"] = False
    climb = phase_info["climb"]["user_options"]
    climb["mach_final"] = (0.85, "unitless")
    climb["altitude_final"] = (35000.0, "ft")
    return phase_info


phase_info = _build()
