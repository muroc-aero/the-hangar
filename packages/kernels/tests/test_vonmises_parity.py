"""Parity tests for the Rust VonMisesTube kernel as an OpenMDAO drop-in.

VonMisesTube (OAS structures/vonmises_tube.py) is a per-element FEM loop:
local-frame transform + cross products + axial/torsional stress algebra for
each of ny-1 beam elements. Upstream ships hand-coded analytic partials, so
this is the strongest possible check: the Rust primal is validated against
OAS's own `compute`, and the complex-step-through-Rust Jacobian is validated
against OAS's own analytic `compute_partials`.

Kernel built with `maturin develop`; OAS golden tests skip if openaerostruct
is absent. Run explicitly:

    cd packages/kernels && maturin develop --release && pip install -e '.[test]'
    pytest packages/kernels/tests/test_vonmises_parity.py -q
"""
import numpy as np
import pytest

rk = pytest.importorskip("hangar_kernels")
om = pytest.importorskip("openmdao.api")

E_AL, G_AL = 70e9, 30e9


# -------------------- faithful numpy replica (no OAS needed) --------------------
def vm_tube_numpy(nodes, radius, disp, E, G):
    ny = nodes.shape[0]
    out = np.zeros((ny - 1, 2), dtype=nodes.dtype)
    x_gl = np.array([1.0, 0.0, 0.0], dtype=nodes.dtype)

    def norm(v):
        return np.sqrt(np.sum(v * v))

    def unit(v):
        return v / norm(v)

    for i in range(ny - 1):
        P0, P1 = nodes[i], nodes[i + 1]
        L = norm(P1 - P0)
        x_loc = unit(P1 - P0)
        y_loc = unit(np.cross(x_loc, x_gl))
        z_loc = unit(np.cross(x_loc, y_loc))
        T = np.vstack([x_loc, y_loc, z_loc])
        u0 = T.dot(disp[i, :3]); r0 = T.dot(disp[i, 3:])
        u1 = T.dot(disp[i + 1, :3]); r1 = T.dot(disp[i + 1, 3:])
        u0x, u1x = u0[0], u1[0]
        r0x, r0y, r0z = r0
        r1x, r1y, r1z = r1
        tmp = np.sqrt((r1y - r0y) ** 2 + (r1z - r0z) ** 2)
        sxx0 = E * (u1x - u0x) / L + E * radius[i] / L * tmp
        sxx1 = E * (u0x - u1x) / L + E * radius[i] / L * tmp
        sxt = G * radius[i] * (r1x - r0x) / L
        out[i, 0] = np.sqrt(sxx0 ** 2 + 3 * sxt ** 2)
        out[i, 1] = np.sqrt(sxx1 ** 2 + 3 * sxt ** 2)
    return out


def make_case(ny, seed=0):
    rng = np.random.default_rng(seed)
    y = np.linspace(0.0, 5.0, ny)
    nodes = np.column_stack([0.2 + 0.1 * y, y, 0.02 * y])           # swept/dihedral spar
    radius = 0.05 + 0.01 * rng.random(ny - 1)
    disp = 1e-3 * rng.standard_normal((ny, 6))                       # nonzero -> tmp > 0
    return nodes, radius, disp


# ------------------------------ rust component ------------------------------
class VonMisesTubeRust(om.ExplicitComponent):
    def initialize(self):
        self.options.declare("ny")
        self.options.declare("E", default=E_AL)
        self.options.declare("G", default=G_AL)

    def setup(self):
        ny = self.options["ny"]
        self.add_input("nodes", val=np.zeros((ny, 3)))
        self.add_input("radius", val=np.zeros(ny - 1))
        self.add_input("disp", val=np.zeros((ny, 6)))
        self.add_output("vonmises", val=np.zeros((ny - 1, 2)))
        self.declare_partials("vonmises", ["nodes", "radius", "disp"], method="cs")

    def compute(self, inputs, outputs):
        n = np.ascontiguousarray(inputs["nodes"])
        r = np.ascontiguousarray(inputs["radius"])
        d = np.ascontiguousarray(inputs["disp"])
        E, G = self.options["E"], self.options["G"]
        if self.under_complex_step:
            outputs["vonmises"] = rk.vonmises_tube_cs(n, r, d, E, G)
        else:
            outputs["vonmises"] = rk.vonmises_tube(n, r, d, E, G)


def _vm_sparse_pattern(ny):
    """Sparse rows/cols for the block-diagonal Jacobian (upstream layout)."""
    row = np.concatenate([np.zeros(6), np.ones(6)])
    n_rows = np.tile(row, ny - 1) + np.repeat(2 * np.arange(ny - 1), 12)
    n_cols = np.tile(np.tile(np.arange(6), 2), ny - 1) + np.repeat(3 * np.arange(ny - 1), 12)
    r_rows = np.arange(2 * (ny - 1))
    r_cols = np.repeat(np.arange(ny - 1), 2)
    row = np.concatenate([np.zeros(12), np.ones(12)])
    d_rows = np.tile(row, ny - 1) + np.repeat(2 * np.arange(ny - 1), 24)
    d_cols = np.tile(np.tile(np.arange(12), 2), ny - 1) + np.repeat(6 * np.arange(ny - 1), 24)
    return (n_rows, n_cols), (r_rows, r_cols), (d_rows, d_cols)


class VonMisesTubeRustAnalytic(om.ExplicitComponent):
    """Fully native: Rust primal + Rust sparse Jacobian (per-element local
    complex-step inside Rust). No OpenMDAO global complex-step."""

    def initialize(self):
        self.options.declare("ny")
        self.options.declare("E", default=E_AL)
        self.options.declare("G", default=G_AL)

    def setup(self):
        ny = self.options["ny"]
        self.add_input("nodes", val=np.zeros((ny, 3)))
        self.add_input("radius", val=np.zeros(ny - 1))
        self.add_input("disp", val=np.zeros((ny, 6)))
        self.add_output("vonmises", val=np.zeros((ny - 1, 2)))
        (nr, nc), (rr, rc), (dr, dc) = _vm_sparse_pattern(ny)
        self.declare_partials("vonmises", "nodes", rows=nr, cols=nc)
        self.declare_partials("vonmises", "radius", rows=rr, cols=rc)
        self.declare_partials("vonmises", "disp", rows=dr, cols=dc)

    def compute(self, inputs, outputs):
        outputs["vonmises"] = rk.vonmises_tube(
            np.ascontiguousarray(inputs["nodes"]),
            np.ascontiguousarray(inputs["radius"]),
            np.ascontiguousarray(inputs["disp"]),
            self.options["E"], self.options["G"])

    def compute_partials(self, inputs, partials):
        jn, jr, jd = rk.vonmises_tube_jac(
            np.ascontiguousarray(inputs["nodes"]),
            np.ascontiguousarray(inputs["radius"]),
            np.ascontiguousarray(inputs["disp"]),
            self.options["E"], self.options["G"])
        partials["vonmises", "nodes"] = jn
        partials["vonmises", "radius"] = jr
        partials["vonmises", "disp"] = jd


def _build_rust(ny):
    p = om.Problem()
    p.model.add_subsystem("vm", VonMisesTubeRust(ny=ny), promotes=["*"])
    p.setup(force_alloc_complex=True)
    return p


def _build_oas(ny):
    oas = pytest.importorskip("openaerostruct.structures.vonmises_tube")
    surface = {"mesh": np.zeros((2, ny, 3)), "E": E_AL, "G": G_AL}
    p = om.Problem()
    p.model.add_subsystem("vm", oas.VonMisesTube(surface=surface), promotes=["*"])
    p.setup(force_alloc_complex=True)
    return p


def _set(p, nodes, radius, disp):
    p.set_val("nodes", nodes); p.set_val("radius", radius); p.set_val("disp", disp)


# --------------------------------- tests ------------------------------------
def test_kernel_matches_numpy_replica():
    nodes, radius, disp = make_case(21)
    vm_rust = rk.vonmises_tube(nodes, radius, disp, E_AL, G_AL)
    vm_np = vm_tube_numpy(nodes, radius, disp, E_AL, G_AL)
    assert np.allclose(vm_rust, vm_np, rtol=1e-12, atol=1e-6)


def test_primal_matches_oas_component():
    """Rust primal == upstream OAS VonMisesTube.compute (the golden source)."""
    p_oas = _build_oas(21)
    nodes, radius, disp = make_case(21)
    _set(p_oas, nodes, radius, disp); p_oas.run_model()
    vm_oas = p_oas.get_val("vonmises")
    vm_rust = rk.vonmises_tube(nodes, radius, disp, E_AL, G_AL)
    assert np.allclose(vm_rust, vm_oas, rtol=1e-10, atol=1e-3)


def test_complex_step_jacobian_matches_oas_analytic():
    """Complex-step THROUGH Rust reproduces OAS's hand-coded analytic Jacobian."""
    ny = 21
    nodes, radius, disp = make_case(ny)
    wrt = ["nodes", "radius", "disp"]

    p_rust = _build_rust(ny); _set(p_rust, nodes, radius, disp); p_rust.run_model()
    Jr = p_rust.compute_totals(of=["vonmises"], wrt=wrt)

    p_oas = _build_oas(ny); _set(p_oas, nodes, radius, disp); p_oas.run_model()
    Jo = p_oas.compute_totals(of=["vonmises"], wrt=wrt)

    for k in wrt:
        a, b = Jr["vonmises", k], Jo["vonmises", k]
        rel = np.linalg.norm(a - b) / (np.linalg.norm(b) + 1e-30)
        assert rel < 1e-7, f"{k}: relative jacobian error {rel:.2e}"


def test_native_analytic_jacobian_matches_oas():
    """The fully-native component's Jacobian (Rust local-CS) matches OAS's
    hand-coded analytic compute_partials to machine precision."""
    ny = 21
    nodes, radius, disp = make_case(ny)
    wrt = ["nodes", "radius", "disp"]

    p = om.Problem()
    p.model.add_subsystem("vm", VonMisesTubeRustAnalytic(ny=ny), promotes=["*"])
    p.setup()
    _set(p, nodes, radius, disp); p.run_model()
    Jr = p.compute_totals(of=["vonmises"], wrt=wrt)

    p_oas = _build_oas(ny); _set(p_oas, nodes, radius, disp); p_oas.run_model()
    Jo = p_oas.compute_totals(of=["vonmises"], wrt=wrt)

    for k in wrt:
        a, b = Jr["vonmises", k], Jo["vonmises", k]
        rel = np.linalg.norm(a - b) / (np.linalg.norm(b) + 1e-30)
        assert rel < 1e-7, f"{k}: relative jacobian error {rel:.2e}"


def test_cs_jacobian_matches_numpy_cs():
    """Self-contained (no OAS): complex-step THROUGH Rust matches complex-step
    of the numpy replica to machine precision. (FD is a poor reference here --
    derivatives ~1e11 floor forward-FD at ~1e-3 and central-FD divides by the
    many exact-zero Jacobian entries -- so we use CS for both sides.)"""
    ny = 11
    nodes, radius, disp = make_case(ny)
    p = _build_rust(ny); _set(p, nodes, radius, disp); p.run_model()
    Jr = p.compute_totals(of=["vonmises"], wrt=["nodes", "radius", "disp"])

    h = 1e-30
    for name, arr in (("nodes", nodes), ("radius", radius), ("disp", disp)):
        J = np.zeros((2 * (ny - 1), arr.size))
        for k in range(arr.size):
            n2, r2, d2 = nodes.astype(complex), radius.astype(complex), disp.astype(complex)
            {"nodes": n2, "radius": r2, "disp": d2}[name].reshape(-1)[k] += 1j * h
            J[:, k] = vm_tube_numpy(n2, r2, d2, E_AL, G_AL).ravel().imag / h
        assert np.allclose(Jr["vonmises", name], J, rtol=1e-9, atol=1e-3), name
