"""Extract results from solved OpenMDAO problems.

Migrated from: OpenAeroStruct/oas_mcp/core/results.py
"""

from __future__ import annotations

import numpy as np
import openmdao.api as om


def _scalar(val) -> float:
    """Convert numpy scalar / array to plain Python float."""
    arr = np.asarray(val).ravel()
    return float(arr[0])


def _try_get(prob: om.Problem, path: str, units: str | None = None):
    """Return value or None if path doesn't exist."""
    try:
        if units:
            return prob.get_val(path, units=units)
        return prob.get_val(path)
    except Exception:
        return None


def extract_aero_results(prob: om.Problem, surfaces: list[dict], point_name: str = "aero") -> dict:
    """Extract aerodynamic results from a solved AeroPoint problem."""
    CL = _scalar(prob.get_val(f"{point_name}.CL"))
    CD = _scalar(prob.get_val(f"{point_name}.CD"))
    CM_vec = np.asarray(prob.get_val(f"{point_name}.CM")).ravel()
    CM = float(CM_vec[1]) if len(CM_vec) > 1 else float(CM_vec[0])

    results = {
        "CL": CL,
        "CD": CD,
        "CM": CM,
        "L_over_D": CL / CD if CD != 0 else None,
        "surfaces": {},
    }

    for surface in surfaces:
        name = surface["name"]
        perf = f"{point_name}.{name}_perf"
        surf_res = {}
        for key, path in [
            ("CL", f"{perf}.CL"),
            ("CD", f"{perf}.CD"),
            ("CDi", f"{perf}.CDi"),
            ("CDv", f"{perf}.CDv"),
            ("CDw", f"{perf}.CDw"),
        ]:
            v = _try_get(prob, path)
            if v is not None:
                surf_res[key] = float(np.asarray(v).ravel()[0])
        results["surfaces"][name] = surf_res

    return results


def extract_aerostruct_results(
    prob: om.Problem, surfaces: list[dict], point_name: str = "AS_point_0"
) -> dict:
    """Extract coupled aerostructural results from a solved AerostructPoint problem."""
    CL = _scalar(prob.get_val(f"{point_name}.CL"))
    CD = _scalar(prob.get_val(f"{point_name}.CD"))
    CM_vec = np.asarray(prob.get_val(f"{point_name}.CM")).ravel()
    CM = float(CM_vec[1]) if len(CM_vec) > 1 else float(CM_vec[0])

    results = {
        "CL": CL,
        "CD": CD,
        "CM": CM,
        "L_over_D": CL / CD if CD != 0 else None,
        "surfaces": {},
    }

    # Mission / fuel burn
    fuelburn = _try_get(prob, f"{point_name}.fuelburn")
    if fuelburn is not None:
        results["fuelburn"] = _scalar(fuelburn)

    # L=W residual
    lew = _try_get(prob, f"{point_name}.L_equals_W")
    if lew is not None:
        results["L_equals_W"] = _scalar(lew)

    # Per-surface structural and aero outputs
    total_struct_mass = 0.0
    for surface in surfaces:
        name = surface["name"]
        perf = f"{point_name}.{name}_perf"
        surf_res = {}

        # Aero coefficients
        for key, path in [
            ("CL", f"{perf}.CL"),
            ("CD", f"{perf}.CD"),
            ("CDi", f"{perf}.CDi"),
            ("CDv", f"{perf}.CDv"),
            ("CDw", f"{perf}.CDw"),
        ]:
            v = _try_get(prob, path)
            if v is not None:
                surf_res[key] = float(np.asarray(v).ravel()[0])

        # Structural failure metric (works for both isotropic and composite)
        failure = _try_get(prob, f"{perf}.failure")
        if failure is not None:
            surf_res["failure"] = _scalar(failure)

        # Material model and stress metric
        is_composite = surface.get("useComposite", False)
        surf_res["material_model"] = "composite" if is_composite else "isotropic"

        if is_composite:
            # Tsai-Wu strength ratio (composite)
            tsaiwu = _try_get(prob, f"{perf}.tsaiwu_sr")
            if tsaiwu is not None:
                sr_arr = np.asarray(tsaiwu).ravel()
                surf_res["max_tsaiwu_sr"] = float(sr_arr.max())
        else:
            # Von Mises stress (isotropic)
            vonmises = _try_get(prob, f"{perf}.vonmises")
            if vonmises is not None:
                vm_arr = np.asarray(vonmises).ravel()
                surf_res["max_vonmises_Pa"] = float(vm_arr.max())

        # Structural mass from geometry group
        sm = _try_get(prob, f"{name}.structural_mass")
        if sm is not None:
            sm_val = _scalar(sm)
            surf_res["structural_mass_kg"] = sm_val
            total_struct_mass += sm_val

        # Per-surface CG location (from SpatialBeamSetup, model-level)
        cg_loc = _try_get(prob, f"{name}.cg_location")
        if cg_loc is not None:
            surf_res["cg_location"] = [round(float(x), 6) for x in np.asarray(cg_loc).ravel()]

        # Tip deflection — node 0 = tip for symmetric mesh, z is column 2
        disp_val = _try_get(prob, f"{point_name}.coupled.{name}.disp")
        if disp_val is not None:
            disp_arr = np.asarray(disp_val)  # (ny, 6)
            surf_res["tip_deflection_m"] = round(float(disp_arr[0, 2]), 6)

        # Total fuel volume (wingbox with distributed_fuel_weight)
        fv = _try_get(prob, f"{name}.struct_setup.fuel_vols")
        if fv is not None:
            surf_res["total_fuel_volume_m3"] = round(float(np.asarray(fv).ravel().sum()), 6)

        results["surfaces"][name] = surf_res

    if total_struct_mass > 0:
        results["structural_mass"] = total_struct_mass

    # Aircraft CG (promoted from total_perf.CG)
    cg_val = _try_get(prob, f"{point_name}.cg")
    if cg_val is not None:
        results["cg"] = [round(float(x), 6) for x in np.asarray(cg_val).ravel()]

    return results


def extract_standard_detail(
    prob: om.Problem,
    surfaces: list[dict],
    analysis_type: str,
    point_name: str,
) -> dict:
    """Extract 'standard' detail level data at run time.

    This data is persisted in the artifact store and survives cache eviction,
    unlike 'full' detail which requires the live om.Problem.

    Returns a dict with:
      - ``sectional_data``: per-surface spanwise distributions
      - ``mesh_snapshot``: leading/trailing edge coordinates of undeformed mesh
    """
    standard: dict = {"sectional_data": {}, "mesh_snapshot": {}}

    # Determine the coupling prefix for aerostruct vs aero-only paths.
    # Aerostruct: sec_forces at {pt}.coupled.aero_states.{name}_sec_forces
    # Aero-only:  sec_forces at {pt}.aero_states.{name}_sec_forces
    coupled_prefix = (
        f"{point_name}.coupled." if analysis_type == "aerostruct" else f"{point_name}."
    )

    for surface in surfaces:
        name = surface["name"]
        perf = f"{point_name}.{name}_perf"
        sect: dict = {}

        # Spanwise panel y-stations from mesh (normalised 0→1)
        # Prefer the optimized mesh from the problem state (reflects chord/twist
        # changes from optimization). Fall back to the static surface dict mesh.
        mesh = _try_get(prob, f"{name}.mesh")
        if mesh is not None:
            mesh = np.asarray(mesh)
        else:
            mesh = surface.get("mesh")
        ny = None
        if mesh is not None:
            ny = int(mesh.shape[1])
            y_coords = np.asarray(mesh[0, :, 1]).ravel()
            # OAS symmetric meshes span y ∈ [-b/2, 0] (left half-span), so
            # node 0 is the TIP and node ny-1 is the ROOT.  Using |y|/max(|y|)
            # gives η=0 at root and η=1 at tip, matching the axis label.
            y_abs = np.abs(y_coords)
            span_half = max(float(y_abs.max()), 1e-12)
            y_norm = (y_abs / span_half).tolist()
            # Sort ascending so η goes 0 (root) → 1 (tip) for plotting.
            # The original OAS ordering is tip-first (descending); reverse it.
            y_norm_sorted = sorted(y_norm)
            sect["y_span_norm"] = y_norm_sorted

            # Mesh snapshot: full mesh for 3D wireframe + LE/TE for 2D fallback
            le = np.asarray(mesh[0, :, :]).tolist()
            te = np.asarray(mesh[-1, :, :]).tolist()
            standard["mesh_snapshot"][name] = {
                "leading_edge": le,
                "trailing_edge": te,
                "mesh": np.asarray(mesh).tolist(),
                "nx": int(mesh.shape[0]),
                "ny": ny,
            }

            # Chord distribution from mesh geometry
            le_x = np.asarray(mesh[0, :, 0])
            te_x = np.asarray(mesh[-1, :, 0])
            chord_arr = te_x - le_x
            sect["chord_m"] = chord_arr[::-1].tolist()   # root-to-tip

            # Twist from OpenMDAO variable (mesh z-coords are zero for CRM)
            # Aerostruct: {name}.geometry.twist; aero-only: {name}.twist
            twist_val = None
            if analysis_type == "aerostruct":
                twist_val = _try_get(prob, f"{name}.geometry.twist")
            if twist_val is None:
                twist_val = _try_get(prob, f"{name}.twist")
            if twist_val is not None:
                twist_arr = np.asarray(twist_val).ravel()
                sect["twist_deg"] = twist_arr[::-1].tolist()  # root-to-tip
            else:
                # Fallback: compute from mesh z-coords (non-zero for custom meshes)
                le_z = np.asarray(mesh[0, :, 2])
                te_z = np.asarray(mesh[-1, :, 2])
                twist_arr = np.degrees(np.arctan2(te_z - le_z, chord_arr))
                sect["twist_deg"] = twist_arr[::-1].tolist()  # root-to-tip

            # Structural FEM data for 3D visualisation
            snap = standard["mesh_snapshot"][name]
            snap["fem_origin"] = surface.get("fem_origin", 0.35)
            snap["fem_model_type"] = surface.get("fem_model_type")
            # Tube model: radius and thickness per element (ny-1)
            radius_val = _try_get(prob, f"{name}.radius")
            if radius_val is not None:
                snap["radius"] = np.squeeze(np.asarray(radius_val)).tolist()
            thickness_val = _try_get(prob, f"{name}.thickness")
            if thickness_val is not None:
                snap["thickness"] = np.asarray(thickness_val).ravel().tolist()
            # Wingbox model: spar and skin thickness per element
            for wb_key in ("spar_thickness", "skin_thickness"):
                wb_val = _try_get(prob, f"{name}.{wb_key}")
                if wb_val is not None:
                    snap[wb_key] = np.asarray(wb_val).ravel().tolist()

        # Sectional CL (panel-level) — path varies by OAS version
        for cl_path in [
            f"{point_name}.{name}_perf.Cl",
            f"{point_name}.aero_states.{name}_sec_forces",
        ]:
            cl_val = _try_get(prob, cl_path)
            if cl_val is not None:
                cl_arr = np.asarray(cl_val).ravel()
                if len(cl_arr) > 1:
                    # Reverse to match sorted y_span_norm (root→tip order)
                    sect["Cl"] = cl_arr[::-1].tolist()
                break

        # -------------------------------------------------------------------
        # Lift loading & elliptical overlay (matches plot_wing.py logic)
        # -------------------------------------------------------------------
        sf_path = f"{coupled_prefix}aero_states.{name}_sec_forces"
        w_path = f"{coupled_prefix}{name}.widths"
        sec_forces_val = _try_get(prob, sf_path)
        widths_val = _try_get(prob, w_path)

        if sec_forces_val is not None and widths_val is not None and mesh is not None:
            sec_forces = np.asarray(sec_forces_val)
            widths = np.asarray(widths_val).ravel()
            alpha_deg = _scalar(prob.get_val("alpha"))
            alpha_rad = alpha_deg * np.pi / 180.0
            cosa = np.cos(alpha_rad)
            sina = np.sin(alpha_rad)
            rho = _scalar(prob.get_val("rho"))
            v = _scalar(prob.get_val("v"))

            # Sum chordwise forces, compute lift loading (force/span / q)
            # This matches plot_wing.py: lift = (-Fx*sin(α) + Fz*cos(α)) / widths / (0.5*ρ*V²)
            forces = np.sum(sec_forces, axis=0)  # (ny-1, 3)
            lift_loading = (
                (-forces[:, 0] * sina + forces[:, 2] * cosa)
                / widths / 0.5 / rho / v**2
            )
            # Reverse to match sorted y_span_norm (root→tip)
            sect["lift_loading"] = lift_loading[::-1].tolist()

            # Elliptical overlay for half-span display.
            # y_span_norm (sorted) goes from η=0 (root) to η=1 (tip).
            # The ideal elliptical distribution is l(η) = l_0 * sqrt(1 - η²),
            # which peaks at the root (η=0) and drops to zero at the tip (η=1).
            eta = np.array(y_norm_sorted)  # [0, ..., 1] root→tip
            # Element midpoints for lift loading (same as panel midpoints)
            eta_mid = (eta[:-1] + eta[1:]) / 2.0
            lift_sorted = np.array(sect["lift_loading"])  # root→tip order
            lift_area_half = float(np.sum(lift_sorted * (eta[1:] - eta[:-1])))
            # l_0 = 4 * A_half / π  (integral of l_0*sqrt(1-η²) from 0 to 1 = l_0*π/4)
            lift_ell = (4 * lift_area_half / np.pi) * np.sqrt(
                np.clip(1 - eta**2, 0, None)
            )
            sect["lift_elliptical"] = lift_ell.tolist()

        # -------------------------------------------------------------------
        # Spanwise stress / strength (aerostruct only)
        # -------------------------------------------------------------------
        if analysis_type == "aerostruct":
            is_composite = surface.get("useComposite", False)
            sect["material_model"] = "composite" if is_composite else "isotropic"
            safety_factor = surface.get("safety_factor", 2.5)
            sect["safety_factor"] = safety_factor

            if is_composite:
                # Tsai-Wu strength ratio — shape (ny-1, 4*num_plies)
                sr_path = f"{perf}.tsaiwu_sr"
                sr_val = _try_get(prob, sr_path)
                if sr_val is not None:
                    sr_2d = np.asarray(sr_val)
                    # Max over plies & critical points per element
                    if sr_2d.ndim >= 2:
                        sr_per_elem = sr_2d.max(axis=-1).ravel()
                    else:
                        sr_per_elem = sr_2d.ravel()
                    if len(sr_per_elem) > 1:
                        sect["tsaiwu_sr_max"] = sr_per_elem[::-1].tolist()

                # Failure index: SR * safety_factor - 1  (>0 = failed)
                if "tsaiwu_sr_max" in sect:
                    sect["failure_index"] = [
                        sr * safety_factor - 1.0 for sr in sect["tsaiwu_sr_max"]
                    ]
            else:
                # Von Mises stress (isotropic)
                vm_path = f"{perf}.vonmises"
                vm_val = _try_get(prob, vm_path)
                if vm_val is not None:
                    vm_2d = np.asarray(vm_val)
                    # vonmises shape: (ny-1, 2) for tube, (ny-1, 4) for wingbox.
                    if vm_2d.ndim >= 2:
                        vm_per_elem = vm_2d.max(axis=-1).ravel()
                    else:
                        vm_per_elem = vm_2d.ravel()
                    if len(vm_per_elem) > 1:
                        sect["vonmises_MPa"] = (vm_per_elem[::-1] / 1e6).tolist()

                yield_stress = surface.get("yield", 500e6)
                sect["yield_stress_MPa"] = yield_stress / 1e6

                # Failure index distribution (per element)
                fi_path = f"{perf}.failure"
                fi_val = _try_get(prob, fi_path)
                if fi_val is not None:
                    fi_arr = np.asarray(fi_val).ravel()
                    if len(fi_arr) > 1:
                        sect["failure_index"] = fi_arr[::-1].tolist()
                    elif "vonmises_MPa" in sect:
                        # FailureKS returns a scalar; derive per-element
                        sigma_allow = yield_stress / safety_factor
                        vm_pa = np.array(sect["vonmises_MPa"]) * 1e6
                        sect["failure_index"] = (vm_pa / sigma_allow - 1.0).tolist()

            # Deformed mesh for 3D overlay (aerostruct only)
            def_mesh_path = f"{point_name}.coupled.{name}.def_mesh"
            def_mesh_val = _try_get(prob, def_mesh_path)
            if def_mesh_val is not None and name in standard["mesh_snapshot"]:
                standard["mesh_snapshot"][name]["def_mesh"] = (
                    np.asarray(def_mesh_val).tolist()
                )

            # Z-deflection distribution (vertical displacement per span node)
            disp_val = _try_get(prob, f"{point_name}.coupled.{name}.disp")
            if disp_val is not None:
                z_defl = np.asarray(disp_val)[:, 2]  # (ny,) vertical
                sect["deflection_m"] = [round(float(v), 6) for v in z_defl[::-1]]

            # Element mass distribution (from geometry group, model-level)
            em_val = _try_get(prob, f"{name}.element_mass")
            if em_val is not None:
                em_arr = np.asarray(em_val).ravel()
                if len(em_arr) > 1:
                    sect["element_mass_kg"] = [round(float(v), 6) for v in em_arr[::-1]]

            # Fuel volume distribution (wingbox only)
            fv_val = _try_get(prob, f"{name}.struct_setup.fuel_vols")
            if fv_val is not None:
                fv_arr = np.asarray(fv_val).ravel()
                if len(fv_arr) > 1:
                    sect["fuel_vols_m3"] = [round(float(v), 6) for v in fv_arr[::-1]]

        standard["sectional_data"][name] = sect

    return standard


def extract_multipoint_results(
    prob: om.Problem,
    surfaces: list[dict],
    point_names: list[str],
    roles: list[str] | None = None,
) -> dict:
    """Extract aerostructural results for each flight point in a multipoint optimization.

    Returns a dict keyed by role (e.g. "cruise", "maneuver") mapping to
    the per-point results dict from ``extract_aerostruct_results``.
    """
    if roles is None:
        roles = [f"point_{i}" for i in range(len(point_names))]
    return {
        role: extract_aerostruct_results(prob, surfaces, pt)
        for role, pt in zip(roles, point_names)
    }


def extract_stability_results(prob: om.Problem) -> dict:
    """Extract stability derivative results."""
    results = {}

    for key, path, units in [
        ("CL", "aero_point.CL", None),
        ("CD", "aero_point.CD", None),
        ("CL_alpha", "CL_alpha", "1/deg"),
        ("static_margin", "static_margin", None),
    ]:
        v = _try_get(prob, path, units)
        if v is not None:
            results[key] = float(np.asarray(v).ravel()[0])

    # CM — pitching moment (index 1)
    cm = _try_get(prob, "aero_point.CM")
    if cm is not None:
        cm_arr = np.asarray(cm).ravel()
        results["CM"] = float(cm_arr[1]) if len(cm_arr) > 1 else float(cm_arr[0])

    # CM_alpha — pitching (index 1 of array output)
    cm_alpha = _try_get(prob, "CM_alpha", "1/deg")
    if cm_alpha is not None:
        cm_alpha_arr = np.asarray(cm_alpha).ravel()
        results["CM_alpha"] = float(cm_alpha_arr[1]) if len(cm_alpha_arr) > 1 else float(cm_alpha_arr[0])

    # Stability interpretation
    sm = results.get("static_margin")
    if sm is not None:
        if sm > 0.05:
            results["stability"] = "statically stable (positive static margin)"
        elif sm > 0.0:
            results["stability"] = "marginally stable"
        else:
            results["stability"] = "statically unstable (negative static margin)"

    return results
