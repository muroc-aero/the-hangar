"""Slot provider registry for composable tool integration.

Maps provider names (e.g., "oas/vlm") to callable factory functions that
build substitute OpenMDAO components for specific "slots" in the OCP
aircraft model (drag, propulsion, weight, etc.).

Provider callable signature:
    provider(nn: int, flight_phase: str, config: dict)
        -> (om.Component, promotes_inputs: list, promotes_outputs: list)

Providers also carry metadata attributes:
    provider.slot_name       -- which slot this fills ("drag", "propulsion", etc.)
    provider.removes_fields  -- DictIndepVarComp fields to skip when this provider is active
    provider.adds_fields     -- dict of {field_name: {"value": ..., "units": ...}} to add
"""

from __future__ import annotations

import logging
from typing import Callable

import numpy as np
import openmdao.api as om

logger = logging.getLogger(__name__)

_PROVIDERS: dict[str, Callable] = {}
_initialized = False


def register_slot_provider(name: str, provider: Callable) -> None:
    """Register a slot provider by name."""
    _PROVIDERS[name] = provider
    logger.debug("Registered slot provider: %s", name)


def get_slot_provider(name: str) -> Callable:
    """Look up a registered slot provider."""
    _ensure_builtins()
    if name not in _PROVIDERS:
        available = ", ".join(sorted(_PROVIDERS.keys())) or "(none)"
        raise KeyError(
            f"No slot provider registered for '{name}'. Available: {available}"
        )
    return _PROVIDERS[name]


def list_slot_providers() -> list[str]:
    """Return sorted list of registered provider names."""
    _ensure_builtins()
    return sorted(_PROVIDERS.keys())


def _ensure_builtins() -> None:
    """Register built-in providers on first access."""
    global _initialized
    if _initialized:
        return
    _initialized = True
    _register_builtins()


def _register_builtins() -> None:
    """Register built-in slot providers."""
    try:
        from openconcept.aerodynamics import VLMDragPolar  # noqa: F401
        register_slot_provider("oas/vlm", _oas_vlm_drag_provider)
    except ImportError:
        logger.info("OpenAeroStruct/VLMDragPolar not available, oas/vlm slot not registered")

    try:
        from openconcept.aerodynamics.openaerostruct.aerostructural import (
            AerostructDragPolar,  # noqa: F401
        )
        register_slot_provider("oas/aerostruct", _oas_aerostruct_drag_provider)
    except ImportError:
        logger.info("AerostructDragPolar not available, oas/aerostruct slot not registered")

    try:
        from openconcept.aerodynamics.openaerostruct.drag_polar import VLM  # noqa: F401
        register_slot_provider("oas/vlm-direct", _oas_vlm_direct_drag_provider)
    except ImportError:
        logger.info("VLM not available, oas/vlm-direct slot not registered")

    try:
        from hangar.omd.pyc.archetypes import Turbojet  # noqa: F401
        register_slot_provider("pyc/turbojet", _pyc_turbojet_propulsion_provider)
        register_slot_provider("pyc/hbtf", _pyc_hbtf_propulsion_provider)
        register_slot_provider("pyc/surrogate", _pyc_surrogate_propulsion_provider)
    except ImportError:
        logger.info("pyCycle not available, pyCycle slots not registered")

    # Weight slot (no external dependencies)
    register_slot_provider("ocp/parametric-weight", _parametric_weight_provider)


# ---------------------------------------------------------------------------
# OAS VLM drag provider
# ---------------------------------------------------------------------------


def _oas_vlm_drag_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    """Build a VLMDragPolar component for the drag slot."""
    from openconcept.aerodynamics import VLMDragPolar

    num_x = config.get("num_x", 2)
    num_y = config.get("num_y", 6)
    num_twist = config.get("num_twist", 4)
    surf_options = config.get("surf_options", {})

    component = VLMDragPolar(
        num_nodes=nn,
        num_x=num_x,
        num_y=num_y,
        num_twist=num_twist,
        surf_options=surf_options,
    )

    promotes_inputs = [
        "fltcond|CL",
        "fltcond|M",
        "fltcond|h",
        "fltcond|q",
        "ac|geom|wing|S_ref",
        "ac|geom|wing|AR",
        "ac|geom|wing|taper",
        "ac|geom|wing|c4sweep",
        "ac|geom|wing|twist",
        "ac|aero|CD_nonwing",
    ]
    promotes_outputs = ["drag"]

    return component, promotes_inputs, promotes_outputs


_oas_vlm_drag_provider.slot_name = "drag"
_oas_vlm_drag_provider.removes_fields = [
    "ac|aero|polar|e",
    "ac|aero|polar|CD0_TO",
    "ac|aero|polar|CD0_cruise",
]
_oas_vlm_drag_provider.design_variables = {
    "twist_cp": "ac|geom|wing|twist",
}
_oas_vlm_drag_provider.result_paths = {
    "drag": "drag",
}
_oas_vlm_drag_provider.adds_fields = {
    "ac|aero|CD_nonwing": {"value": 0.0145},
}


# ---------------------------------------------------------------------------
# OAS Aerostructural drag provider (placeholder for future use)
# ---------------------------------------------------------------------------


def _oas_aerostruct_drag_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    """Build an AerostructDragPolar component for the drag slot."""
    from openconcept.aerodynamics.openaerostruct.aerostructural import (
        AerostructDragPolar,
    )

    num_x = config.get("num_x", 2)
    num_y = config.get("num_y", 6)
    num_twist = config.get("num_twist", 4)
    num_toverc = config.get("num_toverc", 4)
    num_skin = config.get("num_skin", 4)
    num_spar = config.get("num_spar", 4)
    surf_options = config.get("surf_options", {})

    component = AerostructDragPolar(
        num_nodes=nn,
        num_x=num_x,
        num_y=num_y,
        num_twist=num_twist,
        num_toverc=num_toverc,
        num_skin=num_skin,
        num_spar=num_spar,
        surf_options=surf_options,
    )

    promotes_inputs = [
        "fltcond|CL",
        "fltcond|M",
        "fltcond|h",
        "fltcond|q",
        "ac|geom|wing|S_ref",
        "ac|geom|wing|AR",
        "ac|geom|wing|taper",
        "ac|geom|wing|c4sweep",
        "ac|geom|wing|twist",
        "ac|geom|wing|toverc",
        "ac|geom|wing|skin_thickness",
        "ac|geom|wing|spar_thickness",
        "ac|aero|CD_nonwing",
    ]
    promotes_outputs = [
        "drag",
        ("ac|weights|W_wing", "ac|weights|W_wing"),
        "failure",
    ]

    return component, promotes_inputs, promotes_outputs


_oas_aerostruct_drag_provider.slot_name = "drag"
_oas_aerostruct_drag_provider.removes_fields = [
    "ac|aero|polar|e",
    "ac|aero|polar|CD0_TO",
    "ac|aero|polar|CD0_cruise",
    "ac|geom|wing|toverc",
]
_oas_aerostruct_drag_provider.design_variables = {
    "twist_cp": "ac|geom|wing|twist",
    "toverc_cp": "ac|geom|wing|toverc",
    "skin_thickness_cp": "ac|geom|wing|skin_thickness",
    "spar_thickness_cp": "ac|geom|wing|spar_thickness",
}
_oas_aerostruct_drag_provider.result_paths = {
    "drag": "drag",
    "W_wing": "ac|weights|W_wing",
    "failure": "failure",
}
_oas_aerostruct_drag_provider.adds_fields = {
    "ac|aero|CD_nonwing": {"value": 0.0145},
    "ac|geom|wing|twist": {"value": [-2.0, 0.0, 2.0], "units": "deg"},
    "ac|geom|wing|toverc": {"value": [0.12, 0.12, 0.12]},
    "ac|geom|wing|skin_thickness": {"value": [0.005, 0.010, 0.015], "units": "m"},
    "ac|geom|wing|spar_thickness": {"value": [0.005, 0.0075, 0.010], "units": "m"},
}


# ---------------------------------------------------------------------------
# Helper components for per-node vectorization
# ---------------------------------------------------------------------------


class _NodeSlicer(om.ExplicitComponent):
    """Extract element at *index* from an (nn,) vector.

    Provides analytic partials (sparse identity row).
    """

    def initialize(self):
        self.options.declare("nn", types=int)
        self.options.declare("index", types=int)
        self.options.declare("units", default=None, allow_none=True)

    def setup(self):
        nn = self.options["nn"]
        units = self.options["units"]
        self.add_input("vec_in", shape=(nn,), units=units)
        self.add_output("scalar_out", units=units)
        idx = self.options["index"]
        self.declare_partials("scalar_out", "vec_in", rows=[0], cols=[idx], val=1.0)

    def compute(self, inputs, outputs):
        outputs["scalar_out"] = inputs["vec_in"][self.options["index"]]


class _NodeGatherer(om.ExplicitComponent):
    """Gather *nn* scalar inputs into an (nn,) vector.

    Provides analytic partials (sparse identity column per input).
    """

    def initialize(self):
        self.options.declare("nn", types=int)
        self.options.declare("units", default=None, allow_none=True)

    def setup(self):
        nn = self.options["nn"]
        units = self.options["units"]
        for i in range(nn):
            self.add_input(f"in_{i}", units=units)
        self.add_output("vec_out", shape=(nn,), units=units)
        for i in range(nn):
            self.declare_partials("vec_out", f"in_{i}", rows=[i], cols=[0], val=1.0)

    def compute(self, inputs, outputs):
        for i in range(self.options["nn"]):
            outputs["vec_out"][i] = inputs[f"in_{i}"]


# ---------------------------------------------------------------------------
# Direct-coupled OAS VLM drag provider
# ---------------------------------------------------------------------------


class _DirectVLMDragGroup(om.Group):
    """Direct-coupled OAS VLM drag group.

    Runs the full VLM solver at every Newton iteration for each of *nn*
    flight-condition nodes.  Unlike VLMDragPolar (surrogate-coupled),
    this gives exact VLM results and analytic partials through the
    aerodynamic analysis at the cost of higher per-iteration expense.

    Performance scales as O(nn * num_panels) per Newton iteration.
    Use coarse meshes (num_y <= 7) for practical runtimes.
    """

    def initialize(self):
        self.options.declare("nn", types=int, desc="Number of flight condition nodes")
        self.options.declare("num_x", types=int, default=2)
        self.options.declare("num_y", types=int, default=5)
        self.options.declare("num_twist", types=int, default=4)
        self.options.declare("surf_options", types=dict, default=None, allow_none=True)

    def setup(self):
        nn = self.options["nn"]
        nx = self.options["num_x"]
        ny = self.options["num_y"]
        n_twist = self.options["num_twist"]
        surf_options = self.options["surf_options"]
        ny_coords = ny + 1  # coordinate count = panels + 1

        from openconcept.aerodynamics.openaerostruct import (
            TrapezoidalPlanformMesh,
            ThicknessChordRatioInterp,
        )
        from openconcept.aerodynamics.openaerostruct.drag_polar import VLM
        from openaerostruct.geometry.geometry_mesh_transformations import Rotate

        # =============================================================
        #  Shared mesh generation (wing geometry is the same at all nn)
        # =============================================================
        self.add_subsystem(
            "gen_mesh",
            TrapezoidalPlanformMesh(num_x=nx, num_y=ny),
            promotes_inputs=[
                ("S", "ac|geom|wing|S_ref"),
                ("AR", "ac|geom|wing|AR"),
                ("taper", "ac|geom|wing|taper"),
                ("sweep", "ac|geom|wing|c4sweep"),
            ],
        )

        twist_comp = self.add_subsystem(
            "twist_bsp",
            om.SplineComp(
                method="bsplines",
                x_interp_val=np.linspace(0, 1, ny_coords),
                num_cp=n_twist,
                interp_options={"order": min(n_twist, 4)},
            ),
            promotes_inputs=[("twist_cp", "ac|geom|wing|twist")],
        )
        twist_comp.add_spline(
            y_cp_name="twist_cp", y_interp_name="twist", y_units="deg",
        )
        self.set_input_defaults(
            "ac|geom|wing|twist", np.zeros(n_twist), units="deg",
        )

        self.add_subsystem(
            "twist_mesh",
            Rotate(
                val=np.zeros(ny_coords),
                mesh_shape=(nx + 1, ny_coords, 3),
                symmetry=True,
            ),
        )
        self.connect("gen_mesh.mesh", "twist_mesh.in_mesh")
        self.connect("twist_bsp.twist", "twist_mesh.twist")

        self.add_subsystem(
            "toverc_interp",
            ThicknessChordRatioInterp(num_y=ny, num_sections=2),
            promotes_inputs=[("section_toverc", "ac|geom|wing|toverc")],
        )

        # =============================================================
        #  Demux (nn,) flight conditions to per-node scalars
        # =============================================================
        for i in range(nn):
            self.add_subsystem(
                f"slice_h_{i}",
                _NodeSlicer(nn=nn, index=i, units="m"),
                promotes_inputs=[("vec_in", "fltcond|h")],
            )
            self.add_subsystem(
                f"slice_M_{i}",
                _NodeSlicer(nn=nn, index=i),
                promotes_inputs=[("vec_in", "fltcond|M")],
            )

        # =============================================================
        #  CL-alpha balance (nn residuals solved by parent Newton)
        # =============================================================
        self.add_subsystem(
            "alpha_bal",
            om.BalanceComp(
                "alpha",
                eq_units=None,
                lhs_name="CL_VLM",
                rhs_name="CL_target",
                val=np.ones(nn) * 5.0,
                units="deg",
            ),
            promotes_inputs=[("CL_target", "fltcond|CL")],
        )

        # Demux alpha from the balance to per-node scalars
        for i in range(nn):
            self.add_subsystem(
                f"slice_alpha_{i}",
                _NodeSlicer(nn=nn, index=i, units="deg"),
            )
            self.connect("alpha_bal.alpha", f"slice_alpha_{i}.vec_in")

        # =============================================================
        #  Per-node VLM instances (atmosphere + AeroPoint each)
        # =============================================================
        for i in range(nn):
            vlm_name = f"vlm_{i}"
            self.add_subsystem(
                vlm_name,
                VLM(num_x=nx, num_y=ny, surf_options=surf_options),
            )
            # Shared mesh and t/c
            self.connect("twist_mesh.mesh", f"{vlm_name}.ac|geom|wing|OAS_mesh")
            self.connect(
                "toverc_interp.panel_toverc",
                f"{vlm_name}.ac|geom|wing|toverc",
            )
            # Per-node flight conditions
            self.connect(f"slice_h_{i}.scalar_out", f"{vlm_name}.fltcond|h")
            self.connect(f"slice_M_{i}.scalar_out", f"{vlm_name}.fltcond|M")
            self.connect(f"slice_alpha_{i}.scalar_out", f"{vlm_name}.fltcond|alpha")

        # =============================================================
        #  Gather per-node CL and CD into (nn,) vectors
        # =============================================================
        self.add_subsystem("gather_CL", _NodeGatherer(nn=nn))
        self.add_subsystem("gather_CD", _NodeGatherer(nn=nn))
        for i in range(nn):
            self.connect(f"vlm_{i}.fltcond|CL", f"gather_CL.in_{i}")
            self.connect(f"vlm_{i}.fltcond|CD", f"gather_CD.in_{i}")

        # Feed gathered CL back to the balance
        self.connect("gather_CL.vec_out", "alpha_bal.CL_VLM")

        # =============================================================
        #  Drag force = q * S_ref * (CD_wing + CD_nonwing)
        # =============================================================
        self.add_subsystem(
            "drag_calc",
            om.ExecComp(
                "drag = q * S * (CD_wing + CD_nonwing)",
                drag={"units": "N", "shape": (nn,)},
                q={"units": "Pa", "shape": (nn,)},
                S={"units": "m**2"},
                CD_wing={"shape": (nn,)},
                CD_nonwing={"val": 0.0},
                has_diag_partials=True,
            ),
            promotes_inputs=[
                ("q", "fltcond|q"),
                ("S", "ac|geom|wing|S_ref"),
                ("CD_nonwing", "ac|aero|CD_nonwing"),
            ],
            promotes_outputs=["drag"],
        )
        self.connect("gather_CD.vec_out", "drag_calc.CD_wing")

        # Defaults
        self.set_input_defaults("ac|geom|wing|S_ref", 1.0, units="m**2")
        self.set_input_defaults(
            "ac|geom|wing|toverc", np.array([0.12, 0.12]),
        )


def _oas_vlm_direct_drag_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    """Build a direct-coupled VLM drag group for the drag slot.

    Unlike ``oas/vlm`` (surrogate-coupled via VLMDragPolar), this
    provider runs the full OAS VLM solver at every Newton iteration,
    giving exact aerodynamic coefficients and analytic partials.
    """
    num_x = config.get("num_x", 2)
    num_y = config.get("num_y", 5)
    num_twist = config.get("num_twist", 4)
    surf_options = config.get("surf_options", None)

    component = _DirectVLMDragGroup(
        nn=nn,
        num_x=num_x,
        num_y=num_y,
        num_twist=num_twist,
        surf_options=surf_options,
    )

    promotes_inputs = [
        "fltcond|CL",
        "fltcond|M",
        "fltcond|h",
        "fltcond|q",
        "ac|geom|wing|S_ref",
        "ac|geom|wing|AR",
        "ac|geom|wing|taper",
        "ac|geom|wing|c4sweep",
        "ac|geom|wing|twist",
        "ac|aero|CD_nonwing",
    ]
    promotes_outputs = ["drag"]

    return component, promotes_inputs, promotes_outputs


_oas_vlm_direct_drag_provider.slot_name = "drag"
_oas_vlm_direct_drag_provider.removes_fields = [
    "ac|aero|polar|e",
    "ac|aero|polar|CD0_TO",
    "ac|aero|polar|CD0_cruise",
]
_oas_vlm_direct_drag_provider.design_variables = {
    "twist_cp": "ac|geom|wing|twist",
}
_oas_vlm_direct_drag_provider.result_paths = {
    "drag": "drag",
}
_oas_vlm_direct_drag_provider.adds_fields = {
    "ac|aero|CD_nonwing": {"value": 0.0145},
}


# ---------------------------------------------------------------------------
# pyCycle turbojet propulsion provider (surrogate-coupled)
# ---------------------------------------------------------------------------


class _DirectPyCyclePropGroup(om.Group):
    """Direct-coupled pyCycle turbojet propulsion group.

    Contains a pyCycle ``MPTurbojet`` (1 design + nn off-design points)
    as a native OpenMDAO Group subsystem.  Unlike the earlier
    ``ExplicitComponent`` wrapper, pyCycle's element-level analytic
    partials flow through the linear solver chain, giving the outer
    Newton a clean Jacobian.

    Architecture mirrors ``_DirectVLMDragGroup``: ``_NodeSlicer`` /
    ``_NodeGatherer`` handle (nn,) <-> scalar mapping between OCP's
    vectorized flight conditions and pyCycle's per-point scalars.

    Solver hierarchy (with ``solve_subsystems=True`` on the outer Newton):

    - OCP mission Newton (outer) -- drives throttle / CL
      - _DirectPyCyclePropGroup
        - MPTurbojet (cycle)
          - DESIGN Turbojet Newton -- sizes engine (constant inputs)
          - OD_0 Turbojet Newton  -- node 0 flight condition
          - OD_1 Turbojet Newton  -- node 1
          - ...
    """

    def initialize(self):
        self.options.declare("nn", types=int)
        self.options.declare("design_alt", default=35000.0, desc="Design altitude (ft)")
        self.options.declare("design_MN", default=0.8, desc="Design Mach number")
        self.options.declare("design_Fn", default=11800.0, desc="Design thrust (lbf)")
        self.options.declare("design_T4", default=2370.0, desc="Design T4 (degR)")
        self.options.declare("engine_params", types=dict, default={})
        self.options.declare("thermo_method", default="TABULAR")

    def setup(self):
        nn = self.options["nn"]
        design_Fn = self.options["design_Fn"]
        params = dict(self.options["engine_params"])
        params["thermo_method"] = self.options["thermo_method"]

        from hangar.omd.pyc.archetypes import MPTurbojet
        from hangar.omd.pyc.defaults import (
            DEFAULT_TURBOJET_PARAMS,
            DEFAULT_TURBOJET_DESIGN_GUESSES,
            DEFAULT_TURBOJET_OD_GUESSES,
        )

        merged_params = {**DEFAULT_TURBOJET_PARAMS, **params}

        # Off-design point definitions (initial values; real inputs
        # come from the OCP mission via connections below)
        od_points = [
            {
                "name": f"OD_{i}",
                "MN": self.options["design_MN"],
                "alt": self.options["design_alt"],
                "Fn_target": design_Fn * 0.8,
            }
            for i in range(nn)
        ]

        # ============================================================
        #  Throttle -> Fn_target conversion (must run before cycle)
        # ============================================================
        self.add_subsystem(
            "thr_to_Fn",
            om.ExecComp(
                "Fn_target = throttle * design_Fn",
                throttle={"shape": (nn,)},
                design_Fn={"val": design_Fn, "units": "lbf"},
                Fn_target={"shape": (nn,), "units": "lbf"},
                has_diag_partials=True,
            ),
            promotes_inputs=["throttle"],
        )

        # ============================================================
        #  Slice (nn,) inputs to per-node scalars (must run before cycle)
        # ============================================================
        for i in range(nn):
            # Altitude: OCP provides meters, pyCycle expects feet
            # NodeSlicer outputs in meters; OpenMDAO converts to ft
            self.add_subsystem(
                f"slice_h_{i}",
                _NodeSlicer(nn=nn, index=i, units="m"),
                promotes_inputs=[("vec_in", "fltcond|h")],
            )
            self.add_subsystem(
                f"slice_M_{i}",
                _NodeSlicer(nn=nn, index=i),
                promotes_inputs=[("vec_in", "fltcond|M")],
            )
            self.add_subsystem(
                f"slice_Fn_{i}",
                _NodeSlicer(nn=nn, index=i, units="lbf"),
            )
            self.connect("thr_to_Fn.Fn_target", f"slice_Fn_{i}.vec_in")

        # ============================================================
        #  MPTurbojet: 1 design + nn off-design Turbojet Groups
        #  Added AFTER slicers so flight conditions are computed first
        # ============================================================
        self.add_subsystem(
            "cycle",
            MPTurbojet(params=merged_params, od_points=od_points),
        )

        # Fix design-point inputs (constants, not connected to mission)
        self.set_input_defaults(
            "cycle.DESIGN.fc.alt", self.options["design_alt"], units="ft",
        )
        self.set_input_defaults("cycle.DESIGN.fc.MN", self.options["design_MN"])
        self.set_input_defaults(
            "cycle.DESIGN.balance.Fn_target", design_Fn, units="lbf",
        )
        self.set_input_defaults(
            "cycle.DESIGN.balance.T4_target", self.options["design_T4"], units="degR",
        )
        self.set_input_defaults("cycle.DESIGN.comp.PR", merged_params["comp_PR"])
        self.set_input_defaults("cycle.DESIGN.comp.eff", merged_params["comp_eff"])
        self.set_input_defaults("cycle.DESIGN.turb.eff", merged_params["turb_eff"])

        # Connect slicers to off-design point inputs
        for i in range(nn):
            self.connect(f"slice_h_{i}.scalar_out", f"cycle.OD_{i}.fc.alt")
            self.connect(f"slice_M_{i}.scalar_out", f"cycle.OD_{i}.fc.MN")
            self.connect(
                f"slice_Fn_{i}.scalar_out", f"cycle.OD_{i}.balance.Fn_target",
            )

        # ============================================================
        #  Gather per-node outputs into (nn,) vectors
        # ============================================================
        self.add_subsystem("gather_Fn", _NodeGatherer(nn=nn, units="lbf"))
        self.add_subsystem("gather_Wfuel", _NodeGatherer(nn=nn, units="lbm/s"))
        for i in range(nn):
            self.connect(f"cycle.OD_{i}.perf.Fn", f"gather_Fn.in_{i}")
            # burner.Wfuel is the output; perf.Wfuel_0 is an input
            self.connect(f"cycle.OD_{i}.burner.Wfuel", f"gather_Wfuel.in_{i}")

        # ============================================================
        #  Unit passthrough: declare inputs and outputs in the OCP
        #  interface units (kN, kg/s). OpenMDAO converts automatically
        #  at the connection from gather outputs (lbf, lbm/s).
        # ============================================================
        self.add_subsystem(
            "unit_conv",
            om.ExecComp(
                ["thrust = Fn_in", "fuel_flow = Wfuel_in"],
                Fn_in={"shape": (nn,), "units": "kN"},
                Wfuel_in={"shape": (nn,), "units": "kg/s"},
                thrust={"shape": (nn,), "units": "kN"},
                fuel_flow={"shape": (nn,), "units": "kg/s"},
                has_diag_partials=True,
            ),
            promotes_outputs=["thrust", "fuel_flow"],
        )
        self.connect("gather_Fn.vec_out", "unit_conv.Fn_in")
        self.connect("gather_Wfuel.vec_out", "unit_conv.Wfuel_in")

    def apply_initial_guesses(self, prob):
        """Set pyCycle Newton initial guesses after prob.setup().

        Must be called before run_model() for convergence. The balance
        variables have poor default values (FAR=0.3, Nmech=1.5) that
        will cause divergence without proper initialization.

        Tries both promoted and absolute paths to handle cases where
        the group is promoted (standalone) vs not promoted (embedded).
        """
        from hangar.omd.pyc.defaults import (
            DEFAULT_TURBOJET_DESIGN_GUESSES,
            DEFAULT_TURBOJET_OD_GUESSES,
        )

        nn = self.options["nn"]

        def _try_set(name, val, **kwargs):
            """Try setting value, falling back to prefixed path."""
            abs_name = self.pathname
            for prefix in ["", f"{abs_name}." if abs_name else ""]:
                try:
                    prob.set_val(f"{prefix}{name}", val, **kwargs)
                    return
                except (KeyError, RuntimeError):
                    continue

        # Design-point guesses
        dg = DEFAULT_TURBOJET_DESIGN_GUESSES
        _try_set("cycle.DESIGN.balance.FAR", dg["FAR"])
        _try_set("cycle.DESIGN.balance.W", dg["W"])
        _try_set("cycle.DESIGN.balance.turb_PR", dg["turb_PR"])
        _try_set("cycle.DESIGN.fc.balance.Pt", dg["fc_Pt"])
        _try_set("cycle.DESIGN.fc.balance.Tt", dg["fc_Tt"])

        # Off-design guesses
        og = DEFAULT_TURBOJET_OD_GUESSES
        for i in range(nn):
            pt = f"cycle.OD_{i}"
            _try_set(f"{pt}.balance.W", og["W"])
            _try_set(f"{pt}.balance.FAR", og["FAR"])
            _try_set(f"{pt}.balance.Nmech", og["Nmech"])
            _try_set(f"{pt}.fc.balance.Pt", og["fc_Pt"])
            _try_set(f"{pt}.fc.balance.Tt", og["fc_Tt"])



def _pyc_turbojet_propulsion_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    """Build a direct-coupled pyCycle turbojet for the propulsion slot.

    Adds the pyCycle MPTurbojet as a native OpenMDAO Group so that
    element-level analytic partials flow through the solver chain.
    The outer Newton sees a clean Jacobian (no FD through a nested
    Newton).
    """
    component = _DirectPyCyclePropGroup(
        nn=nn,
        design_alt=config.get("design_alt", 35000.0),
        design_MN=config.get("design_MN", 0.8),
        design_Fn=config.get("design_Fn", 11800.0),
        design_T4=config.get("design_T4", 2370.0),
        engine_params=config.get("engine_params", {}),
        thermo_method=config.get("thermo_method", "TABULAR"),
    )

    promotes_inputs = [
        "fltcond|h",
        "fltcond|M",
        "throttle",
    ]
    promotes_outputs = ["thrust", "fuel_flow"]

    return component, promotes_inputs, promotes_outputs


_pyc_turbojet_propulsion_provider.slot_name = "propulsion"
_pyc_turbojet_propulsion_provider.removes_fields = [
    "ac|propulsion|engine|rating",
    "ac|propulsion|propeller|diameter",
]
_pyc_turbojet_propulsion_provider.design_variables = {
    "comp_PR": "cycle.DESIGN.comp.PR",
    "comp_eff": "cycle.DESIGN.comp.eff",
    "turb_eff": "cycle.DESIGN.turb.eff",
}
_pyc_turbojet_propulsion_provider.result_paths = {
    "thrust": "thrust",
    "fuel_flow": "fuel_flow",
    "TSFC": "cycle.DESIGN.perf.TSFC",
    "Fn": "cycle.DESIGN.perf.Fn",
}
_pyc_turbojet_propulsion_provider.adds_fields = {}


# ---------------------------------------------------------------------------
# pyCycle HBTF propulsion provider (direct-coupled)
# ---------------------------------------------------------------------------


class _DirectPyCycleHBTFPropGroup(om.Group):
    """Direct-coupled pyCycle HBTF propulsion group.

    Same architecture as ``_DirectPyCyclePropGroup`` but wraps an
    ``MPHbtf`` (dual-spool high-bypass turbofan) instead of a turbojet.
    The HBTF is more relevant for transport aircraft missions.

    The HBTF has ``guess_nonlinear`` on the Cycle class, so the inner
    Newton gets good starting values every outer iteration.
    """

    def initialize(self):
        self.options.declare("nn", types=int)
        self.options.declare("design_alt", default=35000.0, desc="Design altitude (ft)")
        self.options.declare("design_MN", default=0.8, desc="Design Mach number")
        self.options.declare("design_Fn", default=5900.0, desc="Design thrust (lbf)")
        self.options.declare("design_T4", default=2857.0, desc="Design T4 (degR)")
        self.options.declare("engine_params", types=dict, default={})
        self.options.declare("thermo_method", default="TABULAR")

    def setup(self):
        nn = self.options["nn"]
        design_Fn = self.options["design_Fn"]
        params = dict(self.options["engine_params"])
        params["thermo_method"] = self.options["thermo_method"]

        from hangar.omd.pyc.archetypes import MPHbtf
        from hangar.omd.pyc.defaults import (
            DEFAULT_HBTF_PARAMS,
            DEFAULT_HBTF_DESIGN_GUESSES,
            DEFAULT_HBTF_OD_GUESSES,
        )

        merged_params = {**DEFAULT_HBTF_PARAMS, **params}

        od_points = [
            {
                "name": f"OD_{i}",
                "MN": self.options["design_MN"],
                "alt": self.options["design_alt"],
                "throttle_mode": "T4",
            }
            for i in range(nn)
        ]

        # Throttle -> T4 target (must run before cycle)
        idle_T4 = 1800.0  # degR, approximate idle
        max_T4 = self.options["design_T4"]
        self.add_subsystem(
            "thr_to_T4",
            om.ExecComp(
                f"T4 = {idle_T4} + throttle * {max_T4 - idle_T4}",
                throttle={"shape": (nn,)},
                T4={"shape": (nn,), "units": "degR"},
                has_diag_partials=True,
            ),
            promotes_inputs=["throttle"],
        )

        # Slice (nn,) inputs to per-node scalars (must run before cycle)
        for i in range(nn):
            self.add_subsystem(
                f"slice_h_{i}",
                _NodeSlicer(nn=nn, index=i, units="m"),
                promotes_inputs=[("vec_in", "fltcond|h")],
            )
            self.add_subsystem(
                f"slice_M_{i}",
                _NodeSlicer(nn=nn, index=i),
                promotes_inputs=[("vec_in", "fltcond|M")],
            )
            self.add_subsystem(
                f"slice_T4_{i}",
                _NodeSlicer(nn=nn, index=i, units="degR"),
            )
            self.connect("thr_to_T4.T4", f"slice_T4_{i}.vec_in")

        # MPHbtf: 1 design + nn off-design (added AFTER slicers)
        self.add_subsystem(
            "cycle",
            MPHbtf(params=merged_params, od_points=od_points),
        )

        # Fix design-point inputs
        self.set_input_defaults(
            "cycle.DESIGN.fc.alt", self.options["design_alt"], units="ft",
        )
        self.set_input_defaults("cycle.DESIGN.fc.MN", self.options["design_MN"])
        self.set_input_defaults(
            "cycle.DESIGN.Fn_DES", design_Fn, units="lbf",
        )
        self.set_input_defaults(
            "cycle.DESIGN.T4_MAX", self.options["design_T4"], units="degR",
        )

        # Connect slicers to off-design inputs
        for i in range(nn):
            self.connect(f"slice_h_{i}.scalar_out", f"cycle.OD_{i}.fc.alt")
            self.connect(f"slice_M_{i}.scalar_out", f"cycle.OD_{i}.fc.MN")
            self.connect(f"slice_T4_{i}.scalar_out", f"cycle.OD_{i}.T4_MAX")

        # Gather per-node outputs
        self.add_subsystem("gather_Fn", _NodeGatherer(nn=nn, units="lbf"))
        self.add_subsystem("gather_Wfuel", _NodeGatherer(nn=nn, units="lbm/s"))
        for i in range(nn):
            self.connect(f"cycle.OD_{i}.perf.Fn", f"gather_Fn.in_{i}")
            self.connect(f"cycle.OD_{i}.burner.Wfuel", f"gather_Wfuel.in_{i}")

        # Unit passthrough (OpenMDAO converts at connection boundary)
        self.add_subsystem(
            "unit_conv",
            om.ExecComp(
                ["thrust = Fn_in", "fuel_flow = Wfuel_in"],
                Fn_in={"shape": (nn,), "units": "kN"},
                Wfuel_in={"shape": (nn,), "units": "kg/s"},
                thrust={"shape": (nn,), "units": "kN"},
                fuel_flow={"shape": (nn,), "units": "kg/s"},
                has_diag_partials=True,
            ),
            promotes_outputs=["thrust", "fuel_flow"],
        )
        self.connect("gather_Fn.vec_out", "unit_conv.Fn_in")
        self.connect("gather_Wfuel.vec_out", "unit_conv.Wfuel_in")

    def apply_initial_guesses(self, prob):
        """Set HBTF Newton initial guesses after prob.setup()."""
        from hangar.omd.pyc.defaults import (
            DEFAULT_HBTF_DESIGN_GUESSES,
            DEFAULT_HBTF_OD_GUESSES,
        )

        nn = self.options["nn"]

        def _try_set(name, val, **kwargs):
            abs_name = self.pathname
            for prefix in ["", f"{abs_name}." if abs_name else ""]:
                try:
                    prob.set_val(f"{prefix}{name}", val, **kwargs)
                    return
                except (KeyError, RuntimeError):
                    continue

        dg = DEFAULT_HBTF_DESIGN_GUESSES
        _try_set("cycle.DESIGN.balance.FAR", dg["FAR"])
        _try_set("cycle.DESIGN.balance.W", dg["W"])
        _try_set("cycle.DESIGN.balance.lpt_PR", dg["lpt_PR"])
        _try_set("cycle.DESIGN.balance.hpt_PR", dg["hpt_PR"])
        _try_set("cycle.DESIGN.fc.balance.Pt", dg["fc_Pt"])
        _try_set("cycle.DESIGN.fc.balance.Tt", dg["fc_Tt"])

        og = DEFAULT_HBTF_OD_GUESSES
        for i in range(nn):
            pt = f"cycle.OD_{i}"
            _try_set(f"{pt}.balance.FAR", og["FAR"])
            _try_set(f"{pt}.balance.W", og["W"])
            _try_set(f"{pt}.balance.BPR", og["BPR"])
            _try_set(f"{pt}.balance.lp_Nmech", og["lp_Nmech"])
            _try_set(f"{pt}.balance.hp_Nmech", og["hp_Nmech"])
            _try_set(f"{pt}.fc.balance.Pt", og.get("fc_Pt", 5.2))
            _try_set(f"{pt}.fc.balance.Tt", og.get("fc_Tt", 440.0))


def _pyc_hbtf_propulsion_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    """Build a direct-coupled pyCycle HBTF for the propulsion slot."""
    component = _DirectPyCycleHBTFPropGroup(
        nn=nn,
        design_alt=config.get("design_alt", 35000.0),
        design_MN=config.get("design_MN", 0.8),
        design_Fn=config.get("design_Fn", 5900.0),
        design_T4=config.get("design_T4", 2857.0),
        engine_params=config.get("engine_params", {}),
        thermo_method=config.get("thermo_method", "TABULAR"),
    )

    promotes_inputs = [
        "fltcond|h",
        "fltcond|M",
        "throttle",
    ]
    promotes_outputs = ["thrust", "fuel_flow"]

    return component, promotes_inputs, promotes_outputs


_pyc_hbtf_propulsion_provider.slot_name = "propulsion"
_pyc_hbtf_propulsion_provider.removes_fields = [
    "ac|propulsion|engine|rating",
    "ac|propulsion|propeller|diameter",
]
_pyc_hbtf_propulsion_provider.design_variables = {
    "fan_PR": "cycle.DESIGN.fan.PR",
    "fan_eff": "cycle.DESIGN.fan.eff",
    "hpc_PR": "cycle.DESIGN.hpc.PR",
    "hpc_eff": "cycle.DESIGN.hpc.eff",
}
_pyc_hbtf_propulsion_provider.result_paths = {
    "thrust": "thrust",
    "fuel_flow": "fuel_flow",
    "TSFC": "cycle.DESIGN.perf.TSFC",
    "Fn": "cycle.DESIGN.perf.Fn",
}
_pyc_hbtf_propulsion_provider.adds_fields = {}


# ---------------------------------------------------------------------------
# pyCycle surrogate propulsion provider
# ---------------------------------------------------------------------------


def _pyc_surrogate_propulsion_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.Group, list[str], list[str]]:
    """Build a surrogate-coupled pyCycle propulsion model.

    Uses pre-computed or on-demand generated thrust/fuel_flow decks
    trained via Kriging surrogates from pyCycle off-design sweeps.
    Much faster than direct coupling and no nested Newton convergence
    issues.
    """
    from hangar.omd.pyc.surrogate import PyCycleSurrogateGroup

    component = PyCycleSurrogateGroup(
        nn=nn,
        archetype=config.get("archetype", "turbojet"),
        design_alt=config.get("design_alt", 0.0),
        design_MN=config.get("design_MN", 0.000001),
        design_Fn=config.get("design_Fn", 11800.0),
        design_T4=config.get("design_T4", 2370.0),
        engine_params=config.get("engine_params", {}),
        deck_path=config.get("deck_path", None),
        grid_spec=config.get("grid_spec", None),
    )

    promotes_inputs = [
        "fltcond|h",
        "fltcond|M",
        "throttle",
    ]
    promotes_outputs = ["thrust", "fuel_flow"]

    return component, promotes_inputs, promotes_outputs


_pyc_surrogate_propulsion_provider.slot_name = "propulsion"
_pyc_surrogate_propulsion_provider.removes_fields = [
    "ac|propulsion|engine|rating",
    "ac|propulsion|propeller|diameter",
]
_pyc_surrogate_propulsion_provider.design_variables = {}  # surrogates don't expose internal DVs
_pyc_surrogate_propulsion_provider.result_paths = {
    "thrust": "thrust",
    "fuel_flow": "fuel_flow",
}
_pyc_surrogate_propulsion_provider.adds_fields = {}


# ---------------------------------------------------------------------------
# OCP parametric weight provider
# ---------------------------------------------------------------------------


class _ParametricWeightGroup(om.ExplicitComponent):
    """Parametric weight model: OEW = sum of component weights.

    Accepts optional structural weight from an aerostruct drag slot
    via the ``W_struct`` input. All inputs have configurable defaults.
    """

    def initialize(self):
        self.options.declare("W_struct_default", default=500.0, types=float)
        self.options.declare("W_engine_default", default=200.0, types=float)
        self.options.declare("W_systems_default", default=800.0, types=float)
        self.options.declare("W_payload_equip_default", default=300.0, types=float)

    def setup(self):
        self.add_input("W_struct", val=self.options["W_struct_default"], units="kg")
        self.add_input("W_engine", val=self.options["W_engine_default"], units="kg")
        self.add_input("W_systems", val=self.options["W_systems_default"], units="kg")
        self.add_input("W_payload_equip", val=self.options["W_payload_equip_default"], units="kg")
        self.add_output("OEW", units="kg")
        self.declare_partials("OEW", "*", val=1.0)

    def compute(self, inputs, outputs):
        outputs["OEW"] = (
            inputs["W_struct"]
            + inputs["W_engine"]
            + inputs["W_systems"]
            + inputs["W_payload_equip"]
        )


def _parametric_weight_provider(
    nn: int,
    flight_phase: str,
    config: dict,
) -> tuple[om.ExplicitComponent, list[str], list[str]]:
    """Build a parametric weight model for the weight slot."""
    component = _ParametricWeightGroup(
        W_struct_default=float(config.get("W_struct", 500.0)),
        W_engine_default=float(config.get("W_engine", 200.0)),
        W_systems_default=float(config.get("W_systems", 800.0)),
        W_payload_equip_default=float(config.get("W_payload_equip", 300.0)),
    )

    promotes_inputs = ["W_engine", "W_systems", "W_payload_equip"]
    if config.get("use_wing_weight"):
        # Connect W_struct to the aerostruct drag slot output
        promotes_inputs.append(("W_struct", "ac|weights|W_wing"))
    else:
        promotes_inputs.append("W_struct")

    promotes_outputs = ["OEW"]
    return component, promotes_inputs, promotes_outputs


_parametric_weight_provider.slot_name = "weight"
_parametric_weight_provider.removes_fields = []
_parametric_weight_provider.design_variables = {}
_parametric_weight_provider.result_paths = {
    "OEW": "OEW",
}
_parametric_weight_provider.adds_fields = {}
