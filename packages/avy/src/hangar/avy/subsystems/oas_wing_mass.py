"""OAS wingbox wing mass as an Aviary external subsystem.

Wraps upstream Aviary's own OpenAeroStruct integration
(``aviary.models.external_subsystems.open_aero_struct``): a pre-mission
component whose ``compute()`` runs a nested OAS wingbox sub-optimization
(cruise + 2.5g maneuver, strength + fuel-volume constraints) and promotes
the optimized ``wing_mass`` onto ``Aircraft.Wing.MASS``, overriding the
empirical FLOPS wing weight.

What this module adds over upstream:

- a JSON config dict -> ``IndepVarComp`` wiring, replacing the upstream
  example's post-``setup()`` ``set_val()`` block (our one-shot
  ``run_aviary`` path has no post-setup hook);
- strict config validation with typo suggestions (missions.py contract);
- default values resampled when ``num_box_cp`` / ``num_twist_cp`` shrink
  (the smoke config), so a coarser wingbox needs no hand-typed arrays;
- nested-driver knobs (``sub_opt_tol`` / ``sub_opt_max_iter``): the
  upstream component hardcodes its inner SLSQP settings mid-``compute()``,
  so they are applied through a surgical ``Problem.run_driver`` seam
  rather than a fork of the 567-line component.

The upstream wing mesh is hard-coded to the advanced-single-aisle
planform (``user_mesh()``); this subsystem is only physically meaningful
on that aircraft until the mesh is deck-driven. See ``SUPPORTED_DECKS``.

Everything that imports aviary/openaerostruct lives inside functions --
the module stays importable in the main workspace venv.
"""

from __future__ import annotations

import contextlib
import copy
import difflib
from typing import Any

import numpy as np

SUPPORTED_DECKS = ("advanced_single_aisle", "bench_FwFm")

# Upstream example values (run_OAS_wing_mass_example.py, advanced single
# aisle). Typed literally -- NOT via linspace -- so Lane B reproduces the
# upstream Lane A inputs bit-for-bit.
# fmt: off
_BOX_X_51 = [
    0.1, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.2, 0.21, 0.22,
    0.23, 0.24, 0.25, 0.26, 0.27, 0.28, 0.29, 0.3, 0.31, 0.32, 0.33, 0.34, 0.35,
    0.36, 0.37, 0.38, 0.39, 0.4, 0.41, 0.42, 0.43, 0.44, 0.45, 0.46, 0.47, 0.48,
    0.49, 0.5, 0.51, 0.52, 0.53, 0.54, 0.55, 0.56, 0.57, 0.58, 0.59, 0.6,
]
_BOX_UPPER_Y_51 = [
    0.0447, 0.046, 0.0472, 0.0484, 0.0495, 0.0505, 0.0514, 0.0523, 0.0531, 0.0538,
    0.0545, 0.0551, 0.0557, 0.0563, 0.0568, 0.0573, 0.0577, 0.0581, 0.0585, 0.0588,
    0.0591, 0.0593, 0.0595, 0.0597, 0.0599, 0.06, 0.0601, 0.0602, 0.0602, 0.0602,
    0.0602, 0.0602, 0.0601, 0.06, 0.0599, 0.0598, 0.0596, 0.0594, 0.0592, 0.0589,
    0.0586, 0.0583, 0.058, 0.0576, 0.0572, 0.0568, 0.0563, 0.0558, 0.0553, 0.0547,
    0.0541,
]
_BOX_LOWER_Y_51 = [
    -0.0447, -0.046, -0.0473, -0.0485, -0.0496, -0.0506, -0.0515, -0.0524, -0.0532,
    -0.054, -0.0547, -0.0554, -0.056, -0.0565, -0.057, -0.0575, -0.0579, -0.0583,
    -0.0586, -0.0589, -0.0592, -0.0594, -0.0595, -0.0596, -0.0597, -0.0598, -0.0598,
    -0.0598, -0.0598, -0.0597, -0.0596, -0.0594, -0.0592, -0.0589, -0.0586, -0.0582,
    -0.0578, -0.0573, -0.0567, -0.0561, -0.0554, -0.0546, -0.0538, -0.0529, -0.0519,
    -0.0509, -0.0497, -0.0485, -0.0472, -0.0458, -0.0444,
]
# fmt: on

# config key -> (component input name, units, default). Array defaults are
# the num_box_cp=51 / num_twist_cp=4 upstream values; ``resolve_config``
# resamples them when the counts change. ``fuel_lbm`` may be set to None
# to fall back to upstream's deck-driven promotion (see build()).
CONFIG_INPUTS: dict[str, tuple[str, str, Any]] = {
    "box_upper_x": ("box_upper_x", "unitless", _BOX_X_51),
    "box_lower_x": ("box_lower_x", "unitless", _BOX_X_51),
    "box_upper_y": ("box_upper_y", "unitless", _BOX_UPPER_Y_51),
    "box_lower_y": ("box_lower_y", "unitless", _BOX_LOWER_Y_51),
    "twist_cp": ("twist_cp", "deg", [-6.0, -6.0, -4.0, 0.0]),
    "spar_thickness_cp": ("spar_thickness_cp", "m", [0.004, 0.005, 0.008, 0.01]),
    "skin_thickness_cp": ("skin_thickness_cp", "m", [0.005, 0.01, 0.015, 0.025]),
    "t_over_c_cp": ("t_over_c_cp", "unitless", [0.08, 0.08, 0.10, 0.08]),
    "airfoil_t_over_c": ("airfoil_t_over_c", "unitless", 0.12),
    "fuel_lbm": ("fuel", "lbm", 40044.0),
    "fuel_reserve_lbm": ("fuel_reserve", "lbm", 3000.0),
    "CL0": ("CL0", "unitless", 0.0),
    "CD0": ("CD0", "unitless", 0.0078),
    "cruise_mach": ("cruise_Mach", "unitless", 0.785),
    "cruise_altitude_m": ("cruise_altitude", "m", 11303.682962301647),
    "cruise_range_nmi": ("cruise_range", "nmi", 3500.0),
    "cruise_SFC_1_per_s": ("cruise_SFC", "1/s", 0.53 / 3600),
    "engine_mass_lbm": ("engine_mass", "lbm", 7400.0),
    "engine_location_m": ("engine_location", "m", [25.0, -10.0, 0.0]),
}

_BOX_KEYS = ("box_upper_x", "box_lower_x", "box_upper_y", "box_lower_y")
_CP_KEYS = ("twist_cp", "spar_thickness_cp", "skin_thickness_cp", "t_over_c_cp")

# config key -> default for component options and nested-driver knobs.
CONFIG_OPTIONS: dict[str, Any] = {
    "wing_weight_ratio": 1.0,
    "num_twist_cp": 4,
    "num_box_cp": 51,
    # Nested sub-optimization knobs. Upstream hardcodes tol=1e-8 and leaves
    # maxiter at the scipy default; None means "upstream behavior".
    "sub_opt_tol": None,
    "sub_opt_max_iter": None,
    # Wing planform source (WP4): None = upstream's hard-coded
    # advanced-single-aisle mesh; "deck" = simple trapezoid derived from
    # Aircraft.Wing.{SPAN, AREA, TAPER_RATIO, SWEEP}; or a dict of
    # explicit planform keys (see wing_mesh.PLANFORM_KEYS) merged onto the
    # upstream constants.
    "planform": None,
    "kink_eta": 0.3,
}

VALID_CONFIG_KEYS = tuple(CONFIG_INPUTS) + tuple(CONFIG_OPTIONS)


def _suggest(key: str, valid) -> str:
    close = difflib.get_close_matches(key, list(valid), n=1)
    return f" Did you mean {close[0]!r}?" if close else ""


def _resample(values, n: int) -> list[float]:
    """Linearly resample a control-point array to n points."""
    values = np.asarray(values, dtype=float)
    if len(values) == n:
        return values.tolist()
    old_x = np.linspace(0.0, 1.0, len(values))
    new_x = np.linspace(0.0, 1.0, n)
    return np.interp(new_x, old_x, values).tolist()


def resolve_config(config: dict | None) -> dict:
    """Validate and resolve an oas_wing_mass config dict.

    Returns a flat dict with every ``VALID_CONFIG_KEYS`` entry populated:
    defaults applied, array defaults resampled to the requested
    ``num_box_cp`` / ``num_twist_cp``, explicit values shape-checked.
    Raises ``ValueError`` on unknown keys or malformed values. Pure
    (no aviary import) so the tools can validate in any venv.
    """
    config = dict(config or {})
    for key in config:
        if key not in VALID_CONFIG_KEYS:
            raise ValueError(
                f"Unknown oas_wing_mass config key {key!r}. Valid keys: "
                f"{sorted(VALID_CONFIG_KEYS)}.{_suggest(key, VALID_CONFIG_KEYS)}"
            )

    from hangar.avy.subsystems.wing_mesh import PLANFORM_KEYS

    resolved: dict[str, Any] = {}
    for key, default in CONFIG_OPTIONS.items():
        value = config.get(key, default)
        if key in ("num_twist_cp", "num_box_cp"):
            if not isinstance(value, int) or isinstance(value, bool) or value < 2:
                raise ValueError(f"{key} must be an integer >= 2, got {value!r}")
        elif key == "sub_opt_max_iter" and value is not None:
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"sub_opt_max_iter must be a positive integer, got {value!r}")
        elif key in ("wing_weight_ratio", "kink_eta") or (
            key == "sub_opt_tol" and value is not None
        ):
            if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{key} must be a positive number, got {value!r}")
        elif key == "planform" and value is not None:
            if isinstance(value, dict):
                unknown = set(value) - set(PLANFORM_KEYS)
                if unknown:
                    raise ValueError(
                        f"Unknown planform keys {sorted(unknown)}. "
                        f"Valid: {sorted(PLANFORM_KEYS)}."
                    )
                for pf_key, pf_val in value.items():
                    if not isinstance(pf_val, (int, float)) or isinstance(pf_val, bool):
                        raise ValueError(f"planform.{pf_key} must be a number, got {pf_val!r}")
            elif value != "deck":
                raise ValueError(
                    f"planform must be None, 'deck', or a dict of planform "
                    f"keys, got {value!r}"
                )
        resolved[key] = value

    n_box = resolved["num_box_cp"]
    n_cp = resolved["num_twist_cp"]
    for key, (_input, _units, default) in CONFIG_INPUTS.items():
        if key in config:
            value = config[key]
            if key == "fuel_lbm" and value is None:
                resolved[key] = None  # deck-driven (see build())
                continue
            if key in _BOX_KEYS + _CP_KEYS or key == "engine_location_m":
                want = n_box if key in _BOX_KEYS else (n_cp if key in _CP_KEYS else 3)
                arr = np.asarray(value, dtype=float)
                if arr.shape != (want,):
                    raise ValueError(
                        f"{key} must be a flat array of length {want} "
                        f"(num_box_cp={n_box}, num_twist_cp={n_cp}), got shape {arr.shape}"
                    )
                resolved[key] = arr.tolist()
            else:
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    raise ValueError(f"{key} must be a number, got {value!r}")
                resolved[key] = float(value)
        else:
            if key in _BOX_KEYS:
                resolved[key] = _resample(default, n_box)
            elif key in _CP_KEYS:
                resolved[key] = _resample(default, n_cp)
            else:
                resolved[key] = copy.copy(default)
    return resolved


def require_oas_subsystem():
    """Import-check everything the OAS wing-mass subsystem needs."""
    from hangar.avy.runner import require_aviary

    require_aviary()
    try:
        import ambiance  # noqa: F401
        import openaerostruct  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "The OAS wing-mass subsystem needs 'openaerostruct' and "
            "'ambiance' in the Aviary venv. Re-run `bash "
            "scripts/setup-avy-venv.sh` (they were added to it alongside "
            "aviary), or rebuild the hangar-avy Docker image."
        ) from exc


@contextlib.contextmanager
def _nested_driver_knobs(tol, max_iter):
    """Apply sub-opt driver settings through the ScipyOptimizeDriver.run seam.

    The upstream component hardcodes its nested SLSQP settings inside
    ``compute()``, so the knobs are applied by patching the *class* method
    the nested driver resolves at call time. ``Problem.run_driver`` is not
    usable for this -- OpenMDAO's hooks system binds it per instance --
    but ``Driver.run`` stays class-resolved. The patch window only affects
    drivers whose ``run()`` *starts* inside it: the outer Aviary driver is
    already executing when the component's compute fires, so only the
    nested sub-opt driver is touched. Scoped strictly to the enclosing
    run -- the runner holds the process lock, and the omd worker is a
    single-threaded subprocess.
    """
    import openmdao.api as om

    if tol is None and max_iter is None:
        yield
        return

    orig = om.ScipyOptimizeDriver.run

    def patched(self):
        if tol is not None:
            self.options["tol"] = tol
        if max_iter is not None:
            self.options["maxiter"] = max_iter
        return orig(self)

    om.ScipyOptimizeDriver.run = patched
    try:
        yield
    finally:
        om.ScipyOptimizeDriver.run = orig


def mesh_source(config: dict | None) -> str:
    """Which mesh a config resolves to (for findings/telemetry)."""
    planform = (config or {}).get("planform")
    if planform is None:
        return "upstream-hardcoded"
    if planform == "deck":
        return "deck-derived"
    return "config"


@contextlib.contextmanager
def _mesh_patch(mesh):
    """Serve a parametric mesh through the module-level user_mesh seam.

    ``OAStructures.compute`` calls the module function ``user_mesh()``
    directly, so a deck-driven planform is delivered by patching that
    name for the duration of the compute -- same scoping argument as
    ``_nested_driver_knobs``.
    """
    if mesh is None:
        yield
        return

    import aviary.models.external_subsystems.open_aero_struct.OAS_wing_mass_analysis as _mod

    orig = _mod.user_mesh
    _mod.user_mesh = lambda: mesh
    try:
        yield
    finally:
        _mod.user_mesh = orig


def run_wing_mass_sub_opt(config: dict | None = None, aviary_values=None) -> float:
    """Run one standalone nested sub-optimization; return wing mass in lbm.

    The precompute-mode workhorse: the same builder/group as the coupled
    path, executed once in a throwaway problem instead of inside Aviary's
    pre-mission. ``fuel_lbm`` must be resolvable to a number (the caller
    supplies the deck capacity when config leaves it deck-driven), and
    ``aviary_values`` must carry the deck when ``planform="deck"``.
    Caller must hold the runner's scratch context -- OAS writes report
    files cwd-relative like Aviary does.
    """
    resolved = resolve_config(config)
    if resolved["fuel_lbm"] is None:
        raise ValueError(
            "run_wing_mass_sub_opt needs a concrete fuel_lbm; resolve the "
            "deck's wing fuel capacity before calling (the runner does this)."
        )
    builder = build_oas_wing_mass(config)

    import aviary.api as av
    import openmdao.api as om

    prob = om.Problem()
    prob.model.add_subsystem(
        "wing_mass",
        builder.build_pre_mission(aviary_values or av.AviaryValues()),
        promotes=["*"],
    )
    with _suppress_stdout():
        prob.setup()
        prob.run_model()
    return float(prob.get_val(av.Aircraft.Wing.MASS, units="lbm").item())


@contextlib.contextmanager
def _suppress_stdout():
    """Silence the component's per-compute timing prints (QUIET contract)."""
    import io

    import contextlib as _ctx

    with _ctx.redirect_stdout(io.StringIO()):
        yield


def build_oas_wing_mass(config: dict | None = None, name: str = "oas_wing_mass"):
    """Build the OAS wing-mass SubsystemBuilder from a config dict."""
    require_oas_subsystem()
    resolved = resolve_config(config)

    import aviary.api as av
    import openmdao.api as om
    from aviary.models.external_subsystems.open_aero_struct.OAS_wing_mass_analysis import (
        OAStructures,
    )

    sub_opt_tol = resolved["sub_opt_tol"]
    sub_opt_max_iter = resolved["sub_opt_max_iter"]

    class _TunedOAStructures(OAStructures):
        """OAStructures with driver knobs + optional parametric mesh."""

        _hangar_mesh = None  # ndarray set by the builder, or None (upstream)

        def compute(self, inputs, outputs):
            with _mesh_patch(self._hangar_mesh):
                with _nested_driver_knobs(sub_opt_tol, sub_opt_max_iter):
                    super().compute(inputs, outputs)

    def _resolve_mesh(aviary_inputs):
        """Planform config -> mesh ndarray (None = upstream hard-coded)."""
        from hangar.avy.subsystems.wing_mesh import (
            UPSTREAM_PLANFORM,
            mesh_sanity_issues,
            parametric_mesh,
            planform_from_deck,
        )

        planform = resolved["planform"]
        if planform is None:
            return None
        if planform == "deck":
            params = planform_from_deck(aviary_inputs, kink_eta=resolved["kink_eta"])
        else:
            params = {**UPSTREAM_PLANFORM, **planform}
        mesh = parametric_mesh(**params)
        issues = mesh_sanity_issues(mesh)
        if issues:
            raise ValueError(
                f"Generated wing mesh failed sanity checks: {'; '.join(issues)}. "
                f"Planform: {params}"
            )
        return mesh

    class _Builder(av.SubsystemBuilder):
        def __init__(self):
            super().__init__(name)
            self.config = resolved

        def build_pre_mission(self, aviary_inputs, subsystem_options=None):
            group = om.Group()

            ivc = om.IndepVarComp()
            connected = []
            for key, (input_name, units, _default) in CONFIG_INPUTS.items():
                value = resolved[key]
                if value is None:
                    continue  # deck-driven; promoted below instead
                ivc.add_output(input_name, val=np.asarray(value, dtype=float), units=units)
                connected.append(input_name)
            group.add_subsystem("inputs", ivc)

            promotes_inputs = []
            if resolved["fuel_lbm"] is None:
                # Upstream behavior: wing fuel loads follow the deck's
                # Aircraft.Fuel.WING_FUEL_MASS_CAPACITY.
                promotes_inputs.append(("fuel", av.Aircraft.Fuel.WING_FUEL_MASS_CAPACITY))

            comp = _TunedOAStructures(
                symmetry=True,
                wing_weight_ratio=resolved["wing_weight_ratio"],
                S_ref_type="projected",
                n_point_masses=1,
                num_twist_cp=resolved["num_twist_cp"],
                num_box_cp=resolved["num_box_cp"],
            )
            comp._hangar_mesh = _resolve_mesh(aviary_inputs)
            group.add_subsystem(
                "aerostructures",
                comp,
                promotes_inputs=promotes_inputs,
                # The whole integration: the optimized wingbox mass lands on
                # Aircraft.Wing.MASS, overriding the FLOPS wing weight.
                promotes_outputs=[("wing_mass", av.Aircraft.Wing.MASS)],
            )
            for input_name in connected:
                group.connect(f"inputs.{input_name}", f"aerostructures.{input_name}")
            return group

    return _Builder()
