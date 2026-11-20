"""Three-tier numpy-vs-Rust(pyo3) comparison for a VLM influence-matrix kernel."""
import time
import numpy as np
import hangar_kernels as rk

INV_4PI = 1.0 / (4.0 * np.pi)
EPS = 1e-12
rng = np.random.default_rng(0)


def timeit(fn, *a, n=None, **k):
    fn(*a, **k)  # warm
    reps = n or 50
    t = time.perf_counter()
    for _ in range(reps):
        out = fn(*a, **k)
    dt = (time.perf_counter() - t) / reps
    return dt, out


# ---------------- Tier 0: trivial add ----------------
def t0_numpy(a, b):
    return a + b


# ---------------- Tier 1: Biot-Savart, one filament -> M points ----------------
def seg_vel_numpy(pts, a, b):
    r1 = pts - a
    r2 = pts - b
    r0 = b - a
    cr = np.cross(r1, r2)
    cr_sq = np.einsum("ij,ij->i", cr, cr)
    r1n = np.linalg.norm(r1, axis=1)
    r2n = np.linalg.norm(r2, axis=1)
    k = INV_4PI * (np.einsum("j,ij->i", r0, r1) / r1n
                   - np.einsum("j,ij->i", r0, r2) / r2n) / cr_sq
    out = cr * k[:, None]
    out[cr_sq < EPS] = 0.0
    return out


# ---------------- Tier 2: full AIC matrix (the hot kernel) ----------------
def seg_vel_pairs(P, A, B):
    # P (N,1,3) collocation, A/B (1,N,3) filament endpoints -> (N,N,3)
    r1 = P - A
    r2 = P - B
    r0 = B - A
    cr = np.cross(r1, r2)
    cr_sq = np.einsum("ijk,ijk->ij", cr, cr)
    r1n = np.sqrt(np.einsum("ijk,ijk->ij", r1, r1))
    r2n = np.sqrt(np.einsum("ijk,ijk->ij", r2, r2))
    k = INV_4PI * (np.einsum("ijk,ijk->ij", r0, r1) / r1n
                   - np.einsum("ijk,ijk->ij", r0, r2) / r2n) / cr_sq
    v = cr * k[:, :, None]
    v[cr_sq < EPS] = 0.0
    return v


def assemble_aic_numpy(coll, normals, corners):
    P = coll[:, None, :]            # (N,1,3)
    v = np.zeros((coll.shape[0], coll.shape[0], 3))
    for s in range(4):
        A = corners[:, s, :][None, :, :]        # (1,N,3)
        B = corners[:, (s + 1) % 4, :][None, :, :]
        v += seg_vel_pairs(P, A, B)
    return np.einsum("ijk,ik->ij", v, normals)   # dot with normal_i


def make_mesh(nx, ny):
    """Flat plate split into nx*ny panels; collocation pts, normals, ring corners."""
    xs = np.linspace(0.0, 1.0, nx + 1)
    ys = np.linspace(-2.0, 2.0, ny + 1)
    grid = np.zeros((nx + 1, ny + 1, 3))
    grid[..., 0] = xs[:, None]
    grid[..., 1] = ys[None, :]
    grid[..., 2] = 0.05 * np.sin(xs)[:, None]  # slight camber so it's non-degenerate
    coll, normals, corners = [], [], []
    for i in range(nx):
        for j in range(ny):
            c0, c1 = grid[i, j], grid[i, j + 1]
            c2, c3 = grid[i + 1, j + 1], grid[i + 1, j]
            corners.append([c0, c1, c2, c3])
            coll.append(0.75 * (c3 + c2) / 2 + 0.25 * (c0 + c1) / 2)  # 3/4-chord
            nrm = np.cross(c2 - c0, c3 - c1)
            normals.append(nrm / np.linalg.norm(nrm))
    return (np.array(coll), np.array(normals), np.ascontiguousarray(corners))


print(f"{'tier / case':<34}{'numpy (ms)':>13}{'rust (ms)':>13}{'speedup':>10}  match")
print("-" * 84)

# Tier 0
for size in (1_000, 1_000_000):
    a = rng.random(size); b = rng.random(size)
    tn, on = timeit(t0_numpy, a, b, n=200)
    tr, orr = timeit(rk.vec_add, a, b, n=200)
    ok = np.allclose(on, orr)
    print(f"{'T0 vec_add  N=' + str(size):<34}{tn*1e3:>13.4f}{tr*1e3:>13.4f}{tn/tr:>9.2f}x  {ok}")

# Tier 1
for M in (2_000, 200_000):
    pts = rng.random((M, 3)) + np.array([0.0, 0.0, 1.0])
    A = np.array([0.0, -1.0, 0.0]); B = np.array([0.0, 1.0, 0.0])
    tn, on = timeit(seg_vel_numpy, pts, A, B, n=100)
    tr, orr = timeit(rk.segment_vel, pts, A, B, n=100)
    ok = np.allclose(on, orr)
    print(f"{'T1 segment_vel  M=' + str(M):<34}{tn*1e3:>13.4f}{tr*1e3:>13.4f}{tn/tr:>9.2f}x  {ok}")

# Tier 2 -- the hot kernel, swept over mesh size (N panels)
for (nx, ny) in ((6, 10), (10, 20), (16, 40), (20, 60)):
    coll, normals, corners = make_mesh(nx, ny)
    N = coll.shape[0]
    reps = 20 if N < 800 else 5
    tn, on = timeit(assemble_aic_numpy, coll, normals, corners, n=reps)
    tr, orr = timeit(rk.assemble_aic, coll, normals, corners, n=reps)
    ok = np.allclose(on, orr, atol=1e-10)
    print(f"{'T2 assemble_aic  N=' + str(N):<34}{tn*1e3:>13.4f}{tr*1e3:>13.4f}{tn/tr:>9.2f}x  {ok}")
