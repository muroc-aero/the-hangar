"""Tests for plotting functions.

Tests that each plot function returns a matplotlib Figure without errors.
Uses a real OpenMDAO recorder generated from a small aero analysis.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pytest

from hangar.omd.plotting import (
    plot_planform,
    plot_lift_distribution,
    plot_twist,
    plot_thickness,
    plot_convergence,
    plot_structural_deformation,
    generate_plots,
)


@pytest.fixture(scope="module")
def aero_recorder(tmp_path_factory) -> Path:
    """Generate a recorder from a small aero analysis."""
    import openmdao.api as om
    from openaerostruct.meshing.mesh_generator import generate_mesh
    from openaerostruct.geometry.geometry_group import Geometry
    from openaerostruct.aerodynamics.aero_groups import AeroPoint

    mesh_dict = {
        "num_x": 2, "num_y": 5, "wing_type": "rect",
        "symmetry": True, "span": 10.0, "root_chord": 1.0,
    }
    mesh = generate_mesh(mesh_dict)
    if isinstance(mesh, tuple):
        mesh = mesh[0]

    surface = {
        "name": "wing", "mesh": mesh, "symmetry": True,
        "S_ref_type": "wetted", "CL0": 0.0, "CD0": 0.015,
        "k_lam": 0.05, "t_over_c_cp": np.array([0.15]),
        "c_max_t": 0.303, "with_viscous": True,
        "with_wave": False, "twist_cp": np.zeros(3),
    }

    rec_path = tmp_path_factory.mktemp("recorders") / "aero.sql"
    prob = om.Problem(reports=False)
    indep = om.IndepVarComp()
    indep.add_output("v", val=248.136, units="m/s")
    indep.add_output("alpha", val=5.0, units="deg")
    indep.add_output("beta", val=0.0, units="deg")
    indep.add_output("Mach_number", val=0.84)
    indep.add_output("re", val=1e6, units="1/m")
    indep.add_output("rho", val=0.38, units="kg/m**3")
    indep.add_output("cg", val=np.zeros(3), units="m")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])
    prob.model.add_subsystem("wing", Geometry(surface=surface))
    prob.model.add_subsystem(
        "aero", AeroPoint(surfaces=[surface]),
        promotes_inputs=["v", "alpha", "beta", "Mach_number", "re", "rho", "cg"],
    )
    prob.model.connect("wing.mesh", "aero.wing.def_mesh")
    prob.model.connect("wing.mesh", "aero.aero_states.wing_def_mesh")
    prob.model.connect("wing.t_over_c", "aero.wing_perf.t_over_c")

    recorder = om.SqliteRecorder(str(rec_path))
    prob.add_recorder(recorder)
    prob.setup()
    prob.run_model()
    prob.record("final")
    prob.cleanup()

    return rec_path


@pytest.fixture(scope="module")
def opt_recorder(tmp_path_factory) -> Path:
    """Generate a recorder from a small optimization run."""
    import openmdao.api as om
    from openaerostruct.meshing.mesh_generator import generate_mesh
    from openaerostruct.geometry.geometry_group import Geometry
    from openaerostruct.aerodynamics.aero_groups import AeroPoint

    mesh_dict = {
        "num_x": 2, "num_y": 5, "wing_type": "rect",
        "symmetry": True, "span": 10.0, "root_chord": 1.0,
    }
    mesh = generate_mesh(mesh_dict)
    if isinstance(mesh, tuple):
        mesh = mesh[0]

    surface = {
        "name": "wing", "mesh": mesh, "symmetry": True,
        "S_ref_type": "wetted", "CL0": 0.0, "CD0": 0.015,
        "k_lam": 0.05, "t_over_c_cp": np.array([0.15]),
        "c_max_t": 0.303, "with_viscous": True,
        "with_wave": False, "twist_cp": np.zeros(3),
    }

    rec_path = tmp_path_factory.mktemp("recorders") / "opt.sql"
    prob = om.Problem(reports=False)
    indep = om.IndepVarComp()
    indep.add_output("v", val=248.136, units="m/s")
    indep.add_output("alpha", val=5.0, units="deg")
    indep.add_output("beta", val=0.0, units="deg")
    indep.add_output("Mach_number", val=0.84)
    indep.add_output("re", val=1e6, units="1/m")
    indep.add_output("rho", val=0.38, units="kg/m**3")
    indep.add_output("cg", val=np.zeros(3), units="m")
    prob.model.add_subsystem("prob_vars", indep, promotes=["*"])
    prob.model.add_subsystem("wing", Geometry(surface=surface))
    prob.model.add_subsystem(
        "aero", AeroPoint(surfaces=[surface]),
        promotes_inputs=["v", "alpha", "beta", "Mach_number", "re", "rho", "cg"],
    )
    prob.model.connect("wing.mesh", "aero.wing.def_mesh")
    prob.model.connect("wing.mesh", "aero.aero_states.wing_def_mesh")
    prob.model.connect("wing.t_over_c", "aero.wing_perf.t_over_c")

    prob.driver = om.ScipyOptimizeDriver()
    prob.driver.options["optimizer"] = "SLSQP"
    prob.driver.options["maxiter"] = 5
    prob.model.add_design_var("wing.twist_cp", lower=-10.0, upper=15.0)
    prob.model.add_objective("aero.CD")

    recorder = om.SqliteRecorder(str(rec_path))
    prob.driver.add_recorder(recorder)
    prob.add_recorder(recorder)
    prob.setup()
    prob.run_driver()
    prob.record("final")
    prob.cleanup()

    return rec_path


class TestPlotPlanform:
    def test_returns_figure(self, aero_recorder):
        fig = plot_planform(aero_recorder)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)


class TestPlotLiftDistribution:
    def test_returns_figure(self, aero_recorder):
        fig = plot_lift_distribution(aero_recorder)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)


class TestPlotConvergence:
    def test_returns_figure(self, opt_recorder):
        fig = plot_convergence(opt_recorder)
        assert isinstance(fig, plt.Figure)
        plt.close(fig)

    def test_raises_for_single_case(self, aero_recorder):
        """Convergence plot needs multiple driver cases."""
        with pytest.raises(ValueError, match="at least 2"):
            plot_convergence(aero_recorder)


class TestPlotTwist:
    def test_returns_figure(self, aero_recorder):
        fig = plot_twist(aero_recorder, surface_name="wing")
        assert isinstance(fig, plt.Figure)
        plt.close(fig)


class TestGeneratePlots:
    def test_generates_available_plots(self, aero_recorder, tmp_path):
        saved = generate_plots(
            aero_recorder,
            plot_types=["planform", "lift", "twist"],
            output_dir=tmp_path,
        )
        assert "planform" in saved
        assert saved["planform"].exists()

    def test_skips_unavailable_gracefully(self, aero_recorder, tmp_path):
        # convergence needs multiple driver cases, should be skipped
        saved = generate_plots(
            aero_recorder,
            plot_types=["planform", "convergence"],
            output_dir=tmp_path,
        )
        assert "planform" in saved
        assert "convergence" not in saved  # skipped gracefully
