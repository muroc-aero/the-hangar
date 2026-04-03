"""Evaluation test: Parity -- direct API vs omd factory (Tier 3).

Verifies omd factories produce identical results to direct
OpenMDAO/OpenAeroStruct API usage.
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om
import pytest

pytestmark = [pytest.mark.eval, pytest.mark.parity]


class TestParaboloidParity:
    """Direct om.ExplicitComponent vs omd paraboloid factory."""

    def test_analysis_parity(self):
        """Results match to machine precision."""
        # Lane A: direct OpenMDAO
        prob_a = om.Problem(reports=False)
        prob_a.model.add_subsystem(
            "p",
            om.ExecComp("f_xy = (x-3)**2 + x*y + (y+4)**2 - 3"),
            promotes=["*"],
        )
        prob_a.setup()
        prob_a.set_val("x", 1.0)
        prob_a.set_val("y", 2.0)
        prob_a.run_model()
        f_a = float(prob_a.get_val("f_xy")[0])

        # Lane B: omd factory
        from hangar.omd.factories.paraboloid import build_paraboloid
        prob_b, _ = build_paraboloid({}, {"x": 1.0, "y": 2.0})
        prob_b.setup()
        prob_b.set_val("x", 1.0)
        prob_b.set_val("y", 2.0)
        prob_b.run_model()
        f_b = float(prob_b.get_val("f_xy")[0])

        assert f_a == pytest.approx(39.0, rel=1e-12)
        assert f_b == pytest.approx(f_a, rel=1e-12)


class TestOASAeroParity:
    """Direct Geometry+AeroPoint vs omd AeroPoint factory."""

    @pytest.mark.slow
    def test_aero_analysis_parity(self):
        """CL/CD match between direct OAS and omd factory."""
        from openaerostruct.meshing.mesh_generator import generate_mesh
        from openaerostruct.geometry.geometry_group import Geometry
        from openaerostruct.aerodynamics.aero_groups import AeroPoint as OASAeroPoint

        # Lane A: direct OAS API
        mesh_dict = {"num_x": 2, "num_y": 7, "wing_type": "rect",
                     "symmetry": True, "span": 10.0, "root_chord": 1.0}
        mesh = generate_mesh(mesh_dict)
        if isinstance(mesh, tuple):
            mesh = mesh[0]

        surface = {
            "name": "wing", "mesh": mesh, "symmetry": True,
            "S_ref_type": "wetted", "CL0": 0.0, "CD0": 0.015,
            "k_lam": 0.05, "t_over_c_cp": np.array([0.15]),
            "c_max_t": 0.303, "with_viscous": True, "with_wave": False,
            "twist_cp": np.zeros(4),
        }

        prob_a = om.Problem(reports=False)
        indep = om.IndepVarComp()
        indep.add_output("v", val=248.136, units="m/s")
        indep.add_output("alpha", val=5.0, units="deg")
        indep.add_output("beta", val=0.0, units="deg")
        indep.add_output("Mach_number", val=0.84)
        indep.add_output("re", val=1.0e6, units="1/m")
        indep.add_output("rho", val=0.38, units="kg/m**3")
        indep.add_output("cg", val=np.zeros(3), units="m")
        prob_a.model.add_subsystem("prob_vars", indep, promotes=["*"])
        prob_a.model.add_subsystem("wing", Geometry(surface=surface))
        aero = OASAeroPoint(surfaces=[surface])
        prob_a.model.add_subsystem(
            "aero", aero,
            promotes_inputs=["v", "alpha", "beta", "Mach_number", "re", "rho", "cg"],
        )
        prob_a.model.connect("wing.mesh", "aero.wing.def_mesh")
        prob_a.model.connect("wing.mesh", "aero.aero_states.wing_def_mesh")
        prob_a.model.connect("wing.t_over_c", "aero.wing_perf.t_over_c")
        prob_a.setup()
        prob_a.run_model()
        cl_a = float(prob_a.get_val("aero.CL")[0])
        cd_a = float(prob_a.get_val("aero.CD")[0])

        # Lane B: omd factory
        from hangar.omd.factories.oas_aero import build_oas_aeropoint
        config = {
            "surfaces": [{
                "name": "wing", "wing_type": "rect", "num_x": 2, "num_y": 7,
                "span": 10.0, "root_chord": 1.0, "symmetry": True,
                "with_viscous": True, "CD0": 0.015, "CL0": 0.0,
            }]
        }
        op = {"velocity": 248.136, "alpha": 5.0, "Mach_number": 0.84,
              "re": 1.0e6, "rho": 0.38}
        prob_b, meta_b = build_oas_aeropoint(config, op)
        prob_b.setup()
        prob_b.run_model()
        cl_b = float(prob_b.get_val("aero_point_0.CL")[0])
        cd_b = float(prob_b.get_val("aero_point_0.CD")[0])

        assert cl_a > 0
        assert cl_b == pytest.approx(cl_a, rel=1e-6), \
            f"CL parity failed: direct={cl_a}, omd={cl_b}"
        assert cd_b == pytest.approx(cd_a, rel=1e-6), \
            f"CD parity failed: direct={cd_a}, omd={cd_b}"


class TestOASAerostructParity:
    """Direct AerostructGeometry+AerostructPoint vs omd factory."""

    @pytest.mark.slow
    def test_aerostruct_analysis_parity(self):
        """CL/CD match between direct OAS and omd factory."""
        from openaerostruct.meshing.mesh_generator import generate_mesh
        from openaerostruct.integration.aerostruct_groups import (
            AerostructGeometry, AerostructPoint,
        )

        mesh_dict = {"num_x": 2, "num_y": 5, "wing_type": "rect",
                     "symmetry": True, "span": 10.0, "root_chord": 1.0}
        mesh = generate_mesh(mesh_dict)
        if isinstance(mesh, tuple):
            mesh = mesh[0]

        surface = {
            "name": "wing", "mesh": mesh, "symmetry": True,
            "S_ref_type": "wetted", "CL0": 0.0, "CD0": 0.015,
            "k_lam": 0.05, "t_over_c_cp": np.array([0.15]),
            "c_max_t": 0.303, "with_viscous": True, "with_wave": False,
            "twist_cp": np.zeros(3), "thickness_cp": np.array([0.05, 0.1, 0.05]),
            "fem_model_type": "tube", "E": 70.0e9, "G": 30.0e9,
            "yield": 500.0e6, "mrho": 3000.0, "fem_origin": 0.35,
            "wing_weight_ratio": 2.0, "struct_weight_relief": False,
            "distributed_fuel_weight": False, "exact_failure_constraint": False,
        }

        prob_a = om.Problem(reports=False)
        indep = om.IndepVarComp()
        indep.add_output("v", val=248.136, units="m/s")
        indep.add_output("alpha", val=5.0, units="deg")
        indep.add_output("beta", val=0.0, units="deg")
        indep.add_output("Mach_number", val=0.84)
        indep.add_output("re", val=1.0e6, units="1/m")
        indep.add_output("rho", val=0.38, units="kg/m**3")
        indep.add_output("CT", val=9.81e-6, units="1/s")
        indep.add_output("R", val=14.3e6, units="m")
        indep.add_output("W0", val=25000.0, units="kg")
        indep.add_output("speed_of_sound", val=295.07, units="m/s")
        indep.add_output("load_factor", val=1.0)
        indep.add_output("empty_cg", val=np.array([0.35, 0.0, 0.0]), units="m")
        prob_a.model.add_subsystem("prob_vars", indep, promotes=["*"])
        prob_a.model.add_subsystem("wing", AerostructGeometry(surface=surface))
        point = AerostructPoint(surfaces=[surface])
        promotes = ["v", "alpha", "beta", "Mach_number", "re", "rho",
                    "CT", "R", "W0", "speed_of_sound", "empty_cg", "load_factor"]
        prob_a.model.add_subsystem("AS_point_0", point, promotes_inputs=promotes)
        # Connections
        prob_a.model.connect("wing.local_stiff_transformed",
                             "AS_point_0.coupled.wing.local_stiff_transformed")
        prob_a.model.connect("wing.nodes", "AS_point_0.coupled.wing.nodes")
        prob_a.model.connect("wing.mesh", "AS_point_0.coupled.wing.mesh")
        prob_a.model.connect("wing.nodes", "AS_point_0.wing_perf.nodes")
        prob_a.model.connect("wing.cg_location",
                             "AS_point_0.total_perf.wing_cg_location")
        prob_a.model.connect("wing.structural_mass",
                             "AS_point_0.total_perf.wing_structural_mass")
        prob_a.model.connect("wing.t_over_c", "AS_point_0.wing_perf.t_over_c")
        prob_a.model.connect("wing.radius", "AS_point_0.wing_perf.radius")
        prob_a.model.connect("wing.thickness", "AS_point_0.wing_perf.thickness")
        prob_a.setup()
        prob_a.run_model()
        cl_a = float(prob_a.get_val("AS_point_0.CL")[0])
        cd_a = float(prob_a.get_val("AS_point_0.CD")[0])

        # Lane B: omd factory
        from hangar.omd.factories.oas import build_oas_aerostruct
        config = {
            "surfaces": [{
                "name": "wing", "wing_type": "rect", "num_x": 2, "num_y": 5,
                "span": 10.0, "root_chord": 1.0, "symmetry": True,
                "fem_model_type": "tube", "E": 70.0e9, "G": 30.0e9,
                "yield_stress": 500.0e6, "mrho": 3000.0,
                "thickness_cp": [0.05, 0.1, 0.05],
                "with_viscous": True, "CD0": 0.015, "CL0": 0.0,
            }]
        }
        op = {"velocity": 248.136, "alpha": 5.0, "Mach_number": 0.84,
              "re": 1.0e6, "rho": 0.38}
        prob_b, meta_b = build_oas_aerostruct(config, op)
        prob_b.setup()
        prob_b.run_model()
        cl_b = float(prob_b.get_val("AS_point_0.CL")[0])
        cd_b = float(prob_b.get_val("AS_point_0.CD")[0])

        assert cl_a > 0
        assert cl_b == pytest.approx(cl_a, rel=1e-6), \
            f"CL parity failed: direct={cl_a}, omd={cl_b}"
        assert cd_b == pytest.approx(cd_a, rel=1e-6), \
            f"CD parity failed: direct={cd_a}, omd={cd_b}"


if __name__ == "__main__":
    """Standalone comparison report."""
    print("=" * 60)
    print("omd Parity Report")
    print("=" * 60)

    t = TestParaboloidParity()
    t.test_analysis_parity()
    print("Paraboloid parity: PASS")

    t2 = TestOASAeroParity()
    t2.test_aero_analysis_parity()
    print("OAS aero parity: PASS")

    t3 = TestOASAerostructParity()
    t3.test_aerostruct_analysis_parity()
    print("OAS aerostruct parity: PASS")

    print("=" * 60)
    print("All parity checks passed.")
