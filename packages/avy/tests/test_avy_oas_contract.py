"""Contract tests for the upstream OAS-in-Aviary external subsystem.

The OAS wing-mass integration imports from
``aviary.models.external_subsystems.open_aero_struct`` -- Aviary's
*example* namespace, which is not API-stable. These tests pin the exact
surface hangar.avy depends on, so an AVY_REF / OAS_REF bump that moves or
reshapes it fails loudly here instead of deep inside a sizing run.

Fast (no sub-optimization runs). Skips in the main venv; run for real via
``.venv-avy/bin/python -m pytest packages/avy/tests/test_avy_oas_contract.py``.
"""

from __future__ import annotations

import inspect

import pytest

pytest.importorskip("aviary")
pytest.importorskip("openaerostruct")
pytest.importorskip("ambiance")


# Inputs the hangar builder config maps onto (name -> units); a rename or
# unit change upstream must be caught at pin-bump time, not at run time.
EXPECTED_INPUTS = {
    "box_upper_x": "unitless",
    "box_lower_x": "unitless",
    "box_upper_y": "unitless",
    "box_lower_y": "unitless",
    "twist_cp": "deg",
    "spar_thickness_cp": "m",
    "skin_thickness_cp": "m",
    "t_over_c_cp": "unitless",
    "airfoil_t_over_c": "unitless",
    "fuel": "kg",
    "fuel_reserve": "kg",
    "CL0": "unitless",
    "CD0": "unitless",
    "cruise_Mach": "unitless",
    "cruise_altitude": "m",
    "cruise_range": "m",
    "cruise_SFC": "1/s",
    "engine_mass": "kg",
    "engine_location": "m",
}

EXPECTED_OUTPUTS = {"wing_mass": "kg", "fuel_burn": "kg"}


def _component_io():
    import openmdao.api as om

    from aviary.models.external_subsystems.open_aero_struct.OAS_wing_mass_analysis import (
        OAStructures,
    )

    prob = om.Problem()
    prob.model.add_subsystem(
        "oas",
        OAStructures(
            symmetry=True,
            wing_weight_ratio=1.0,
            S_ref_type="projected",
            n_point_masses=1,
            num_twist_cp=4,
            num_box_cp=51,
        ),
    )
    prob.setup()
    inputs = {
        meta["prom_name"].split(".")[-1]: meta["units"]
        for _, meta in prob.model.list_inputs(units=True, out_stream=None)
    }
    outputs = {
        meta["prom_name"].split(".")[-1]: meta["units"]
        for _, meta in prob.model.list_outputs(units=True, out_stream=None)
    }
    return inputs, outputs


def test_component_inputs_and_outputs_stable():
    inputs, outputs = _component_io()
    for name, units in EXPECTED_INPUTS.items():
        assert name in inputs, f"OAStructures lost input {name!r}"
        assert inputs[name] == units, (
            f"OAStructures input {name!r} units changed: "
            f"{inputs[name]!r} != {units!r}"
        )
    for name, units in EXPECTED_OUTPUTS.items():
        assert name in outputs, f"OAStructures lost output {name!r}"
        assert outputs[name] == units


def test_builder_contract():
    import aviary.api as av

    from aviary.models.external_subsystems.open_aero_struct.OAS_wing_mass_builder import (
        OASWingMassBuilder,
    )

    builder = OASWingMassBuilder()
    assert isinstance(builder, av.SubsystemBuilder)

    # The whole integration hangs on this promotion: wing_mass must land on
    # Aircraft.Wing.MASS to override the FLOPS wing weight.
    import openmdao.api as om

    prob = om.Problem()
    prob.model.add_subsystem(
        "wing_mass", builder.build_pre_mission(av.AviaryValues()), promotes=["*"]
    )
    prob.setup()
    promoted_outputs = {
        meta["prom_name"]
        for _, meta in prob.model.list_outputs(prom_name=True, out_stream=None)
    }
    assert av.Aircraft.Wing.MASS in promoted_outputs


def test_run_aviary_accepts_subsystems_kwarg():
    from aviary.interface.run_aviary import run_aviary

    assert "subsystems" in inspect.signature(run_aviary).parameters


def test_warm_start_attribute_present():
    """The runtime plan leans on upstream's warm start; pin its existence."""
    from aviary.models.external_subsystems.open_aero_struct.OAS_wing_mass_analysis import (
        OAStructures,
    )

    src = inspect.getsource(OAStructures.compute)
    assert "previous_DV_values" in src
