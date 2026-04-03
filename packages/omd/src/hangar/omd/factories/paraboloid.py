"""Paraboloid component factory.

Builds the classic OpenMDAO paraboloid test problem:
    f(x, y) = (x - 3)^2 + x*y + (y + 4)^2 - 3

Analytic minimum at x = 20/3, y = -22/3, f = -82/3.
"""

from __future__ import annotations

from typing import Any

import openmdao.api as om


class _Paraboloid(om.ExplicitComponent):
    """Standard OpenMDAO paraboloid with analytic partials."""

    def setup(self) -> None:
        self.add_input("x", val=0.0)
        self.add_input("y", val=0.0)
        self.add_output("f_xy", val=0.0)
        self.declare_partials("*", "*")

    def compute(self, inputs, outputs) -> None:
        x = inputs["x"]
        y = inputs["y"]
        outputs["f_xy"] = (x - 3.0) ** 2 + x * y + (y + 4.0) ** 2 - 3.0

    def compute_partials(self, inputs, J) -> None:
        x = inputs["x"]
        y = inputs["y"]
        J["f_xy", "x"] = 2.0 * x - 6.0 + y
        J["f_xy", "y"] = 2.0 * y + 8.0 + x


def build_paraboloid(
    component_config: dict,
    operating_points: dict,
) -> tuple[om.Problem, dict[str, Any]]:
    """Build a paraboloid problem from plan config.

    Args:
        component_config: Component config dict (currently unused,
            reserved for future extensions like scaling).
        operating_points: Dict that may contain initial "x" and "y" values.

    Returns:
        Tuple of (problem, metadata). Problem has setup NOT called.
    """
    prob = om.Problem(reports=False)

    prob.model.add_subsystem("paraboloid", _Paraboloid(), promotes=["*"])

    metadata: dict[str, Any] = {
        "point_name": "paraboloid",
        "output_names": ["paraboloid.f_xy"],
        "initial_values": {},
    }

    # Capture initial values from operating_points
    if "x" in operating_points:
        metadata["initial_values"]["x"] = float(operating_points["x"])
    if "y" in operating_points:
        metadata["initial_values"]["y"] = float(operating_points["y"])

    return prob, metadata
