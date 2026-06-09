"""Tests for unit-tagged operating-point normalization.

Regression context: the plan schema permits {"value": ..., "units": ...}
operating-point entries, but factories injected the raw dict into the
IndepVarComp, corrupting the model. The materializer now normalizes all
operating points before any factory sees them.
"""

from __future__ import annotations

import pytest

from hangar.omd.op_points import normalize_operating_points


class TestNormalizeFlat:
    def test_bare_values_pass_through(self):
        op = {"velocity": 248.136, "alpha": 5.0, "empty_cg": [0.35, 0.0, 0.0]}
        assert normalize_operating_points(op) == op

    def test_value_dict_without_units_unwraps(self):
        out = normalize_operating_points({"velocity": {"value": 248.136}})
        assert out["velocity"] == pytest.approx(248.136)

    def test_value_dict_with_units_converts(self):
        out = normalize_operating_points(
            {"velocity": {"value": 814.0, "units": "ft/s"}}
        )
        assert out["velocity"] == pytest.approx(248.107, abs=0.01)

    def test_pyc_altitude_converts_to_ft(self):
        out = normalize_operating_points(
            {"alt": {"value": 10668.0, "units": "m"}}
        )
        assert out["alt"] == pytest.approx(35000.0, rel=1e-3)

    def test_temperature_converts_with_offset(self):
        out = normalize_operating_points(
            {"T4_target": {"value": 1600.0, "units": "K"}}
        )
        assert out["T4_target"] == pytest.approx(2880.0, rel=1e-6)

    def test_array_value_converts_elementwise(self):
        out = normalize_operating_points(
            {"empty_cg": {"value": [1.0, 0.0, 0.0], "units": "ft"}}
        )
        assert out["empty_cg"] == pytest.approx([0.3048, 0.0, 0.0])

    def test_dimensionless_key_with_units_raises(self):
        with pytest.raises(ValueError, match="dimensionless"):
            normalize_operating_points(
                {"Mach_number": {"value": 0.84, "units": "m/s"}}
            )

    def test_unknown_key_with_units_raises(self):
        with pytest.raises(ValueError, match="canonical units are unknown"):
            normalize_operating_points(
                {"mystery_param": {"value": 1.0, "units": "m"}}
            )

    def test_incompatible_units_raise(self):
        with pytest.raises(ValueError, match="Cannot convert"):
            normalize_operating_points(
                {"velocity": {"value": 1.0, "units": "kg"}}
            )


class TestNormalizeMultipoint:
    def test_flight_points_and_shared_normalized(self):
        op = {
            "flight_points": [
                {"name": "cruise",
                 "velocity": {"value": 814.0, "units": "ft/s"},
                 "Mach_number": 0.84},
                {"name": "maneuver", "velocity": 200.0, "Mach_number": 0.68},
            ],
            "shared": {"R": {"value": 3000.0, "units": "km"}, "CT": 9.81e-6},
        }
        out = normalize_operating_points(op)
        assert out["flight_points"][0]["velocity"] == pytest.approx(248.107, abs=0.01)
        assert out["flight_points"][0]["name"] == "cruise"
        assert out["flight_points"][1]["velocity"] == pytest.approx(200.0)
        assert out["shared"]["R"] == pytest.approx(3.0e6)
        assert out["shared"]["CT"] == pytest.approx(9.81e-6)


class TestThroughOasFactory:
    def _plan(self, operating_points: dict) -> dict:
        return {
            "metadata": {"id": "plan-op-units", "name": "x", "version": 1},
            "components": [{
                "id": "aero",
                "type": "oas/AeroPoint",
                "config": {
                    "surfaces": [{
                        "name": "wing",
                        "wing_type": "rect",
                        "num_x": 2,
                        "num_y": 5,
                        "span": 10.0,
                        "root_chord": 1.0,
                        "symmetry": True,
                    }],
                },
            }],
            "operating_points": operating_points,
        }

    def test_unit_tagged_velocity_reaches_ivc_converted(self):
        """Regression: the raw {value, units} dict used to land in the IVC."""
        from hangar.omd.materializer import materialize

        plan = self._plan({
            "velocity": {"value": 814.0, "units": "ft/s"},
            "alpha": 5.0,
            "Mach_number": 0.84,
            "re": 1.0e6,
            "rho": {"value": 0.38, "units": "kg/m**3"},
        })
        prob, metadata = materialize(plan, recording_level="minimal")
        v = float(prob.get_val("v")[0])
        rho = float(prob.get_val("rho")[0])
        assert v == pytest.approx(248.107, abs=0.01)
        assert rho == pytest.approx(0.38)
        assert metadata["flight_conditions"]["velocity"] == pytest.approx(
            248.107, abs=0.01
        )
