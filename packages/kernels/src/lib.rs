// VLM kernels with a generic scalar so complex-step differentiation runs
// *through* Rust: the same source is monomorphized for f64 (primal) and
// Complex64 (the imaginary-perturbation pass OpenMDAO uses for method="cs").
use num_complex::Complex64;
use numpy::ndarray::Array2;
use numpy::{
    IntoPyArray, PyArray1, PyArray2, PyReadonlyArray1, PyReadonlyArray2, PyReadonlyArray3,
};
use pyo3::prelude::*;
use rayon::prelude::*;

const INV_4PI: f64 = 0.079_577_471_545_947_67; // 1/(4*pi)
const EPS: f64 = 1e-12;

/// Minimal scalar interface the kernel needs. Implemented for the real type
/// and the complex-step type. `re()` exposes the real part *only* for the
/// singularity branch -- branching on the real part keeps the function locally
/// analytic, which is what makes complex step valid.
trait Scalar:
    Copy
    + std::ops::Add<Output = Self>
    + std::ops::Sub<Output = Self>
    + std::ops::Mul<Output = Self>
    + std::ops::Div<Output = Self>
{
    fn sqrt(self) -> Self;
    fn re(self) -> f64;
    fn splat(x: f64) -> Self;
    const ZERO: Self;
}
impl Scalar for f64 {
    #[inline] fn sqrt(self) -> Self { f64::sqrt(self) }
    #[inline] fn re(self) -> f64 { self }
    #[inline] fn splat(x: f64) -> Self { x }
    const ZERO: Self = 0.0;
}
impl Scalar for Complex64 {
    #[inline] fn sqrt(self) -> Self { Complex64::sqrt(self) }
    #[inline] fn re(self) -> f64 { self.re }
    #[inline] fn splat(x: f64) -> Self { Complex64::new(x, 0.0) }
    const ZERO: Self = Complex64::new(0.0, 0.0);
}

#[inline]
fn cross<T: Scalar>(a: [T; 3], b: [T; 3]) -> [T; 3] {
    [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]
}
#[inline]
fn dot<T: Scalar>(a: [T; 3], b: [T; 3]) -> T {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

/// Induced velocity at p from a straight vortex filament a->b, unit circulation.
#[inline]
fn seg_vel<T: Scalar>(p: [T; 3], a: [T; 3], b: [T; 3]) -> [T; 3] {
    let r1 = [p[0] - a[0], p[1] - a[1], p[2] - a[2]];
    let r2 = [p[0] - b[0], p[1] - b[1], p[2] - b[2]];
    let r0 = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
    let cr = cross(r1, r2);
    let cr_sq = dot(cr, cr);
    if cr_sq.re() < EPS {
        return [T::ZERO, T::ZERO, T::ZERO]; // on the filament -> singular
    }
    let r1n = dot(r1, r1).sqrt();
    let r2n = dot(r2, r2).sqrt();
    let k = T::splat(INV_4PI) * (dot(r0, r1) / r1n - dot(r0, r2) / r2n) / cr_sq;
    [k * cr[0], k * cr[1], k * cr[2]]
}

/// Generic AIC assembly shared by the real and complex entry points.
fn aic_generic<T: Scalar>(
    coll: &[[T; 3]],
    normals: &[[T; 3]],
    corners: &[[[T; 3]; 4]],
) -> Vec<T> {
    let n = coll.len();
    let mut out = vec![T::ZERO; n * n];
    for i in 0..n {
        let p = coll[i];
        let nrm = normals[i];
        for j in 0..n {
            let r = corners[j];
            let mut v = [T::ZERO; 3];
            for s in 0..4 {
                let seg = seg_vel(p, r[s], r[(s + 1) % 4]);
                v[0] = v[0] + seg[0];
                v[1] = v[1] + seg[1];
                v[2] = v[2] + seg[2];
            }
            out[i * n + j] = dot(v, nrm);
        }
    }
    out
}

// ---------- helpers: numpy array <-> Vec<[T;3]> ----------
fn rows3<T: numpy::Element + Copy>(a: &numpy::ndarray::ArrayView2<T>) -> Vec<[T; 3]> {
    (0..a.shape()[0]).map(|i| [a[[i, 0]], a[[i, 1]], a[[i, 2]]]).collect()
}
fn rings<T: numpy::Element + Copy>(a: &numpy::ndarray::ArrayView3<T>) -> Vec<[[T; 3]; 4]> {
    (0..a.shape()[0])
        .map(|j| {
            let c = |k: usize| [a[[j, k, 0]], a[[j, k, 1]], a[[j, k, 2]]];
            [c(0), c(1), c(2), c(3)]
        })
        .collect()
}

// ---------- Tier 0 / 1 (unchanged, f64) ----------
#[pyfunction]
fn vec_add<'py>(
    py: Python<'py>,
    a: PyReadonlyArray1<'py, f64>,
    b: PyReadonlyArray1<'py, f64>,
) -> Bound<'py, PyArray1<f64>> {
    (&a.as_array() + &b.as_array()).into_pyarray_bound(py)
}

#[pyfunction]
fn segment_vel<'py>(
    py: Python<'py>,
    pts: PyReadonlyArray2<'py, f64>,
    a: [f64; 3],
    b: [f64; 3],
) -> Bound<'py, PyArray2<f64>> {
    let pts = pts.as_array();
    let m = pts.shape()[0];
    let mut out = Array2::<f64>::zeros((m, 3));
    for i in 0..m {
        let v = seg_vel([pts[[i, 0]], pts[[i, 1]], pts[[i, 2]]], a, b);
        out[[i, 0]] = v[0]; out[[i, 1]] = v[1]; out[[i, 2]] = v[2];
    }
    out.into_pyarray_bound(py)
}

// ---------- Tier 2: real primal ----------
#[pyfunction]
fn assemble_aic<'py>(
    py: Python<'py>,
    coll: PyReadonlyArray2<'py, f64>,
    normals: PyReadonlyArray2<'py, f64>,
    corners: PyReadonlyArray3<'py, f64>,
) -> Bound<'py, PyArray2<f64>> {
    let c = rows3(&coll.as_array());
    let nm = rows3(&normals.as_array());
    let rg = rings(&corners.as_array());
    let n = c.len();
    let data = aic_generic(&c, &nm, &rg);
    Array2::from_shape_vec((n, n), data).unwrap().into_pyarray_bound(py)
}

// ---------- Tier 2b: parallel real primal ----------
#[pyfunction]
fn assemble_aic_par<'py>(
    py: Python<'py>,
    coll: PyReadonlyArray2<'py, f64>,
    normals: PyReadonlyArray2<'py, f64>,
    corners: PyReadonlyArray3<'py, f64>,
) -> Bound<'py, PyArray2<f64>> {
    let c = rows3(&coll.as_array());
    let nm = rows3(&normals.as_array());
    let rg = rings(&corners.as_array());
    let n = c.len();
    let mut data = vec![0.0f64; n * n];
    data.par_chunks_mut(n).enumerate().for_each(|(i, row)| {
        let p = c[i];
        let nrm = nm[i];
        for j in 0..n {
            let r = rg[j];
            let mut v = [0.0f64; 3];
            for s in 0..4 {
                let seg = seg_vel(p, r[s], r[(s + 1) % 4]);
                v[0] += seg[0]; v[1] += seg[1]; v[2] += seg[2];
            }
            row[j] = dot(v, nrm);
        }
    });
    Array2::from_shape_vec((n, n), data).unwrap().into_pyarray_bound(py)
}

// ---------- Tier 2c: COMPLEX-STEP path (same generic code, Complex64) ----------
#[pyfunction]
fn assemble_aic_cs<'py>(
    py: Python<'py>,
    coll: PyReadonlyArray2<'py, Complex64>,
    normals: PyReadonlyArray2<'py, Complex64>,
    corners: PyReadonlyArray3<'py, Complex64>,
) -> Bound<'py, PyArray2<Complex64>> {
    let c = rows3(&coll.as_array());
    let nm = rows3(&normals.as_array());
    let rg = rings(&corners.as_array());
    let n = c.len();
    let data = aic_generic(&c, &nm, &rg);
    Array2::from_shape_vec((n, n), data).unwrap().into_pyarray_bound(py)
}

// ======================================================================
// VonMisesTube -- OAS structures/vonmises_tube.py. Per-element FEM stress:
// build the local frame, rotate the end displacements/rotations into it,
// and form the axial + torsional von Mises stress at each element end.
// Generic over scalar so complex-step runs through Rust (the upstream
// `compute` flips to complex via `under_complex_step`).
// ======================================================================
#[inline]
fn unit<T: Scalar>(v: [T; 3]) -> [T; 3] {
    let n = dot(v, v).sqrt();
    [v[0] / n, v[1] / n, v[2] / n]
}

fn rows6<T: numpy::Element + Copy>(a: &numpy::ndarray::ArrayView2<T>) -> Vec<[T; 6]> {
    (0..a.shape()[0])
        .map(|i| [a[[i, 0]], a[[i, 1]], a[[i, 2]], a[[i, 3]], a[[i, 4]], a[[i, 5]]])
        .collect()
}

fn vm_element<T: Scalar>(
    p0: [T; 3],
    p1: [T; 3],
    rad: T,
    d0: [T; 6],
    d1: [T; 6],
    e_mod: f64,
    g_mod: f64,
) -> [T; 2] {
    let x_gl = [T::splat(1.0), T::ZERO, T::ZERO];
    let e = T::splat(e_mod);
    let g = T::splat(g_mod);
    let three = T::splat(3.0);

    let d = [p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]];
    let l = dot(d, d).sqrt();
    let x_loc = unit(d);
    let y_loc = unit(cross(x_loc, x_gl));
    let z_loc = unit(cross(x_loc, y_loc));

    let u0 = [d0[0], d0[1], d0[2]];
    let r0 = [d0[3], d0[4], d0[5]];
    let u1 = [d1[0], d1[1], d1[2]];
    let r1 = [d1[3], d1[4], d1[5]];

    let u0x = dot(x_loc, u0);
    let u1x = dot(x_loc, u1);
    let r0x = dot(x_loc, r0);
    let r0y = dot(y_loc, r0);
    let r0z = dot(z_loc, r0);
    let r1x = dot(x_loc, r1);
    let r1y = dot(y_loc, r1);
    let r1z = dot(z_loc, r1);

    let dy = r1y - r0y;
    let dz = r1z - r0z;
    let tmp = (dy * dy + dz * dz).sqrt();
    let sxx0 = e * (u1x - u0x) / l + e * rad / l * tmp;
    let sxx1 = e * (u0x - u1x) / l + e * rad / l * tmp;
    let sxt = g * rad * (r1x - r0x) / l;
    [
        (sxx0 * sxx0 + three * sxt * sxt).sqrt(),
        (sxx1 * sxx1 + three * sxt * sxt).sqrt(),
    ]
}

fn vonmises_tube_generic<T: Scalar>(
    nodes: &[[T; 3]],
    radius: &[T],
    disp: &[[T; 6]],
    e_mod: f64,
    g_mod: f64,
) -> Vec<T> {
    let num_elems = nodes.len() - 1;
    let mut out = vec![T::ZERO; num_elems * 2];
    for i in 0..num_elems {
        let vm = vm_element(nodes[i], nodes[i + 1], radius[i], disp[i], disp[i + 1], e_mod, g_mod);
        out[2 * i] = vm[0];
        out[2 * i + 1] = vm[1];
    }
    out
}

#[pyfunction]
fn vonmises_tube<'py>(
    py: Python<'py>,
    nodes: PyReadonlyArray2<'py, f64>,
    radius: PyReadonlyArray1<'py, f64>,
    disp: PyReadonlyArray2<'py, f64>,
    e_mod: f64,
    g_mod: f64,
) -> Bound<'py, PyArray2<f64>> {
    let nd = rows3(&nodes.as_array());
    let rad = radius.as_array().to_vec();
    let dp = rows6(&disp.as_array());
    let ne = nd.len() - 1;
    let data = vonmises_tube_generic(&nd, &rad, &dp, e_mod, g_mod);
    Array2::from_shape_vec((ne, 2), data).unwrap().into_pyarray_bound(py)
}

#[pyfunction]
fn vonmises_tube_cs<'py>(
    py: Python<'py>,
    nodes: PyReadonlyArray2<'py, Complex64>,
    radius: PyReadonlyArray1<'py, Complex64>,
    disp: PyReadonlyArray2<'py, Complex64>,
    e_mod: f64,
    g_mod: f64,
) -> Bound<'py, PyArray2<Complex64>> {
    let nd = rows3(&nodes.as_array());
    let rad = radius.as_array().to_vec();
    let dp = rows6(&disp.as_array());
    let ne = nd.len() - 1;
    let data = vonmises_tube_generic(&nd, &rad, &dp, e_mod, g_mod);
    Array2::from_shape_vec((ne, 2), data).unwrap().into_pyarray_bound(py)
}

/// Exact sparse Jacobian of VonMisesTube via per-element local complex-step,
/// done entirely in Rust (no pyo3 boundary per perturbation, no OpenMDAO
/// global complex-step). Each element's 2 stresses depend on only 19 local
/// inputs, so we complex-step those 19 and emit data arrays matching the
/// sparse rows/cols the OpenMDAO component declares (upstream layout):
///   d/dnodes : 12 per elem  [dvm0/dP0, dvm0/dP1, dvm1/dP0, dvm1/dP1]
///   d/dradius:  2 per elem  [dvm0/drad, dvm1/drad]
///   d/ddisp  : 24 per elem  [dvm0/dd0, dvm0/dd1, dvm1/dd0, dvm1/dd1]
#[pyfunction]
fn vonmises_tube_jac<'py>(
    py: Python<'py>,
    nodes: PyReadonlyArray2<'py, f64>,
    radius: PyReadonlyArray1<'py, f64>,
    disp: PyReadonlyArray2<'py, f64>,
    e_mod: f64,
    g_mod: f64,
) -> (
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray1<f64>>,
    Bound<'py, PyArray1<f64>>,
) {
    let nd = rows3(&nodes.as_array());
    let rad = radius.as_array().to_vec();
    let dp = rows6(&disp.as_array());
    let ne = nd.len() - 1;
    const H: f64 = 1e-30;
    let ih = Complex64::new(0.0, H);
    let cf = |x: f64| Complex64::new(x, 0.0);

    let mut jn = vec![0.0f64; 12 * ne];
    let mut jr = vec![0.0f64; 2 * ne];
    let mut jd = vec![0.0f64; 24 * ne];

    for i in 0..ne {
        let p0 = [cf(nd[i][0]), cf(nd[i][1]), cf(nd[i][2])];
        let p1 = [cf(nd[i + 1][0]), cf(nd[i + 1][1]), cf(nd[i + 1][2])];
        let r = cf(rad[i]);
        let d0 = [cf(dp[i][0]), cf(dp[i][1]), cf(dp[i][2]), cf(dp[i][3]), cf(dp[i][4]), cf(dp[i][5])];
        let d1 = [cf(dp[i + 1][0]), cf(dp[i + 1][1]), cf(dp[i + 1][2]), cf(dp[i + 1][3]), cf(dp[i + 1][4]), cf(dp[i + 1][5])];

        for c in 0..3 {
            let mut pp = p0; pp[c] = pp[c] + ih;
            let vm = vm_element(pp, p1, r, d0, d1, e_mod, g_mod);
            jn[12 * i + c] = vm[0].im / H;
            jn[12 * i + 6 + c] = vm[1].im / H;
        }
        for c in 0..3 {
            let mut pp = p1; pp[c] = pp[c] + ih;
            let vm = vm_element(p0, pp, r, d0, d1, e_mod, g_mod);
            jn[12 * i + 3 + c] = vm[0].im / H;
            jn[12 * i + 9 + c] = vm[1].im / H;
        }
        {
            let vm = vm_element(p0, p1, r + ih, d0, d1, e_mod, g_mod);
            jr[2 * i] = vm[0].im / H;
            jr[2 * i + 1] = vm[1].im / H;
        }
        for c in 0..6 {
            let mut dd = d0; dd[c] = dd[c] + ih;
            let vm = vm_element(p0, p1, r, dd, d1, e_mod, g_mod);
            jd[24 * i + c] = vm[0].im / H;
            jd[24 * i + 12 + c] = vm[1].im / H;
        }
        for c in 0..6 {
            let mut dd = d1; dd[c] = dd[c] + ih;
            let vm = vm_element(p0, p1, r, d0, dd, e_mod, g_mod);
            jd[24 * i + 6 + c] = vm[0].im / H;
            jd[24 * i + 18 + c] = vm[1].im / H;
        }
    }
    (
        jn.into_pyarray_bound(py),
        jr.into_pyarray_bound(py),
        jd.into_pyarray_bound(py),
    )
}

// ======================================================================
// VLM vortex helpers -- OAS aerodynamics/eval_mtx.py inner functions.
// These are where EvalVelMtx (the AIC assembly) spends its time: per-pair
// Biot-Savart over big broadcast arrays, most of numpy's cost being np.cross
// axis machinery. f64 only; OAS's rare complex-step (alpha) falls back to
// numpy in the Python wrapper.
// ======================================================================
const TOL: f64 = 1e-10;

#[pyfunction]
fn vlm_finite_vortex<'py>(
    py: Python<'py>,
    r1: PyReadonlyArray2<'py, f64>,
    r2: PyReadonlyArray2<'py, f64>,
) -> Bound<'py, PyArray2<f64>> {
    let a = rows3(&r1.as_array());
    let b = rows3(&r2.as_array());
    let m = a.len();
    let mut out = Array2::<f64>::zeros((m, 3));
    for k in 0..m {
        let (u, v) = (a[k], b[k]);
        let un = dot(u, u).sqrt();
        let vn = dot(v, v).sqrt();
        let den = un * vn + dot(u, v);
        if den.abs() > TOL {
            let cx = cross(u, v);
            let s = (1.0 / un + 1.0 / vn) * INV_4PI / den;
            out[[k, 0]] = s * cx[0];
            out[[k, 1]] = s * cx[1];
            out[[k, 2]] = s * cx[2];
        }
    }
    out.into_pyarray_bound(py)
}

#[pyfunction]
fn vlm_semi_infinite_vortex<'py>(
    py: Python<'py>,
    u: PyReadonlyArray2<'py, f64>,
    r: PyReadonlyArray2<'py, f64>,
) -> Bound<'py, PyArray2<f64>> {
    let uu = rows3(&u.as_array());
    let rr = rows3(&r.as_array());
    let m = uu.len();
    let mut out = Array2::<f64>::zeros((m, 3));
    for k in 0..m {
        let (uv, rv) = (uu[k], rr[k]);
        let rn = dot(rv, rv).sqrt();
        let den = rn * (rn - dot(uv, rv));
        let cx = cross(uv, rv);
        let s = INV_4PI / den;
        out[[k, 0]] = s * cx[0];
        out[[k, 1]] = s * cx[1];
        out[[k, 2]] = s * cx[2];
    }
    out.into_pyarray_bound(py)
}

#[pymodule]
fn hangar_kernels(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(vec_add, m)?)?;
    m.add_function(wrap_pyfunction!(segment_vel, m)?)?;
    m.add_function(wrap_pyfunction!(vonmises_tube, m)?)?;
    m.add_function(wrap_pyfunction!(vonmises_tube_cs, m)?)?;
    m.add_function(wrap_pyfunction!(vonmises_tube_jac, m)?)?;
    m.add_function(wrap_pyfunction!(vlm_finite_vortex, m)?)?;
    m.add_function(wrap_pyfunction!(vlm_semi_infinite_vortex, m)?)?;
    m.add_function(wrap_pyfunction!(assemble_aic, m)?)?;
    m.add_function(wrap_pyfunction!(assemble_aic_par, m)?)?;
    m.add_function(wrap_pyfunction!(assemble_aic_cs, m)?)?;
    Ok(())
}
