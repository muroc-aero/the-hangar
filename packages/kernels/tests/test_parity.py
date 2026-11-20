"""Parity + complex-step tests for the Rust VLM kernels as an OpenMDAO drop-in.

These guard the claim that the native kernel is a true replacement for the
numpy assembly: identical results, and complex-step derivatives that survive
the trip through Rust. The kernel module is built with `maturin develop`; the
test skips cleanly when it (or openmdao) is absent so a Rust-free checkout still
collects.

Run explicitly (not in the default `uv run pytest` surface):

    cd packages/kernels && maturin develop --release
    pytest packages/kernels/tests -q
"""
import numpy as np
import pytest

rk = pytest.importorskip("hangar_kernels")
om = pytest.importorskip("openmdao.api")

INV_4PI = 1.0 / (4.0 * np.pi)


# --------------------------- reference numpy paths ---------------------------
def cs_normalize(v):
    return v / np.sqrt((v * v).sum(axis=-1, keepdims=True))


def geom_from_corners(corners):
    c0, c1, c2, c3 = corners[:, 0], corners[:, 1], corners[:, 2], corners[:, 3]
    coll = 0.75 * 0.5 * (c3 + c2) + 0.25 * 0.5 * (c0 + c1)
    normals = cs_normalize(np.cross(c2 - c0, c3 - c1))
    return coll, normals


def assemble_numpy(coll, normals, corners):
    P = coll[:, None, :]
    v = np.zeros((coll.shape[0], coll.shape[0], 3), dtype=coll.dtype)
    for s in range(4):
        A = corners[:, s, :][None, :, :]
        B = corners[:, (s + 1) % 4, :][None, :, :]
        r1, r2, r0 = P - A, P - B, B - A
        cr = np.cross(r1, r2)
        cr_sq = (cr * cr).sum(-1)
        r1n = np.sqrt((r1 * r1).sum(-1))
        r2n = np.sqrt((r2 * r2).sum(-1))
        k = INV_4PI * ((r0 * r1).sum(-1) / r1n - (r0 * r2).sum(-1) / r2n) / cr_sq
        seg = cr * k[:, :, None]
        seg = np.where((cr_sq.real < 1e-12)[:, :, None], 0.0, seg)
        v += seg
    return np.einsum("ijk,ik->ij", v, normals)


def make_corners(nx, ny):
    xs = np.linspace(0.0, 1.0, nx + 1)
    ys = np.linspace(-2.0, 2.0, ny + 1)
    grid = np.zeros((nx + 1, ny + 1, 3))
    grid[..., 0] = xs[:, None]
    grid[..., 1] = ys[None, :]
    grid[..., 2] = 0.05 * np.sin(np.pi * xs)[:, None]
    corners = []
    for i in range(nx):
        for j in range(ny):
            corners.append([grid[i, j], grid[i, j + 1], grid[i + 1, j + 1], grid[i + 1, j]])
    return np.ascontiguousarray(corners)


# ------------------------------- component ----------------------------------
class VLMComp(om.ExplicitComponent):
    def initialize(self):
        self.options.declare("corners0")
        self.options.declare("Vinf", default=50.0)
        self.options.declare("Sref", default=8.0)
        self.options.declare("backend", default="rust")
        self.cs_hits = 0

    def setup(self):
        self.add_input("alpha", val=3.0 * np.pi / 180.0)
        self.add_input("gscale", val=1.0)
        self.add_output("CL", val=0.0)
        self.declare_partials("CL", ["alpha", "gscale"], method="cs")

    def compute(self, inputs, outputs):
        alpha, gscale = inputs["alpha"], inputs["gscale"]
        complexify = np.iscomplexobj(alpha) or np.iscomplexobj(gscale)
        dt = complex if complexify else float
        corners = self.options["corners0"].astype(dt).copy()
        corners[:, :, 2] = corners[:, :, 2] * gscale
        coll, normals = geom_from_corners(corners)
        if self.options["backend"] == "rust":
            if complexify:
                self.cs_hits += 1
                aic = rk.assemble_aic_cs(np.ascontiguousarray(coll),
                                         np.ascontiguousarray(normals),
                                         np.ascontiguousarray(corners))
            else:
                aic = rk.assemble_aic(np.ascontiguousarray(coll),
                                      np.ascontiguousarray(normals),
                                      np.ascontiguousarray(corners))
        else:
            aic = assemble_numpy(coll, normals, corners)
        V = self.options["Vinf"] * np.array([np.cos(alpha), 0.0 * alpha, np.sin(alpha)]).reshape(3)
        rhs = -(normals @ V)
        gamma = np.linalg.solve(aic, rhs)
        outputs["CL"] = (2.0 / (self.options["Vinf"] * self.options["Sref"])) * gamma.sum()


def _build(corners0, backend):
    p = om.Problem()
    p.model.add_subsystem("vlm", VLMComp(corners0=corners0, backend=backend), promotes=["*"])
    p.setup(force_alloc_complex=True)
    return p


# --------------------------------- tests ------------------------------------
def test_raw_kernel_matches_numpy():
    """assemble_aic (f64) is bit-for-bit np.allclose to the numpy assembly."""
    corners = make_corners(6, 10)
    coll, normals = geom_from_corners(corners)
    a_rust = rk.assemble_aic(coll, normals, corners)
    a_np = assemble_numpy(coll, normals, corners)
    assert np.allclose(a_rust, a_np, atol=1e-12)


def test_parallel_matches_serial():
    corners = make_corners(8, 16)
    coll, normals = geom_from_corners(corners)
    assert np.allclose(rk.assemble_aic(coll, normals, corners),
                       rk.assemble_aic_par(coll, normals, corners), atol=1e-12)


def test_analysis_parity_rust_vs_numpy():
    """CL from the rust-backed component equals the numpy-backed component."""
    corners0 = make_corners(8, 16)
    pr = _build(corners0, "rust"); pr.run_model()
    pn = _build(corners0, "numpy"); pn.run_model()
    assert pr.get_val("CL")[0] == pytest.approx(pn.get_val("CL")[0], abs=1e-12)


def test_complex_step_through_rust_matches_fd():
    """Complex-step derivatives computed THROUGH the Rust Complex64 kernel
    agree with an independent finite difference, and the complex path was hit."""
    corners0 = make_corners(8, 16)
    pr = _build(corners0, "rust")
    J = pr.compute_totals(of=["CL"], wrt=["alpha", "gscale"])

    # the gscale derivative forces complex numbers through the AIC assembly
    assert pr.model.vlm.cs_hits >= 1

    def CL_at(alpha, gscale):
        p = _build(corners0, "rust")
        p.set_val("alpha", alpha); p.set_val("gscale", gscale); p.run_model()
        return p.get_val("CL")[0]

    h = 1e-6
    a0, g0 = 3.0 * np.pi / 180.0, 1.0
    da_fd = (CL_at(a0 + h, g0) - CL_at(a0 - h, g0)) / (2 * h)
    dg_fd = (CL_at(a0, g0 + h) - CL_at(a0, g0 - h)) / (2 * h)
    assert J["CL", "alpha"][0, 0] == pytest.approx(da_fd, rel=1e-6)
    assert J["CL", "gscale"][0, 0] == pytest.approx(dg_fd, rel=1e-5)


def test_jacobian_parity_rust_vs_numpy():
    """Complex-step jacobian is identical (to ~machine eps) whether the AIC
    assembly is rust or numpy."""
    corners0 = make_corners(8, 16)
    Jr = _build(corners0, "rust").compute_totals(of=["CL"], wrt=["alpha", "gscale"])
    Jn = _build(corners0, "numpy").compute_totals(of=["CL"], wrt=["alpha", "gscale"])
    assert Jr["CL", "alpha"][0, 0] == pytest.approx(Jn["CL", "alpha"][0, 0], abs=1e-12)
    assert Jr["CL", "gscale"][0, 0] == pytest.approx(Jn["CL", "gscale"][0, 0], abs=1e-12)


def test_check_partials_clean():
    """OpenMDAO's own check_partials: declared CS-through-rust vs OpenMDAO FD."""
    corners0 = make_corners(8, 16)
    pr = _build(corners0, "rust"); pr.run_model()
    data = pr.check_partials(method="fd", compact_print=True, out_stream=None)
    for (_of, _wrt), d in data["vlm"].items():
        assert d["rel error"].forward < 1e-5
