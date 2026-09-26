// Sparse LU direct solver exposed to Python via pyo3, backed by `faer`
// (pure-Rust, MIT/Apache, multithreaded). The point of this module is the
// licensing/portability thesis: it is a parallel sparse direct solver with a
// permissive license, so -- unlike MKL PARDISO (proprietary) or SuiteSparse
// (GPL) -- it can be shipped in a wheel and dropped into OpenMDAO's
// DirectSolver in place of scipy's single-threaded SuperLU.
//
// Contract mirrors the _PardisoLU wrapper used in the PARDISO bench:
//   FaerLU(nrows, ncols, indptr, indices, data)   # from a scipy CSC matrix
//   .solve(b, transpose)                           # transpose=True -> A^T x = b
//
// The matrix is taken in CSC form (scipy's native splu input), which is also
// faer's native column-major sparse layout, so no transpose/copy is needed to
// factorize. indptr/indices are passed as int64 from Python to dodge scipy's
// int32/int64 ambiguity.
use faer::prelude::{Par, Solve};
use faer::sparse::linalg::solvers::Lu;
use faer::sparse::{SparseColMat, SymbolicSparseColMat};
use faer::Mat;
use numpy::{IntoPyArray, PyArray1, PyReadonlyArray1};
use pyo3::prelude::*;

/// Set faer's global parallelism. n<=1 -> sequential (matches a single-threaded
/// SuperLU baseline); n>1 -> rayon with n threads (the multicore comparison).
#[pyfunction]
pub fn faer_set_threads(n: usize) {
    if n <= 1 {
        faer::set_global_parallelism(Par::Seq);
    } else {
        faer::set_global_parallelism(Par::rayon(n));
    }
}

/// A factorized sparse matrix: holds faer's LU factors (owned, the source
/// matrix can be dropped) and answers repeated solves.
#[pyclass]
pub struct FaerLU {
    lu: Lu<usize, f64>,
    n: usize,
}

#[pymethods]
impl FaerLU {
    #[new]
    fn new(
        nrows: usize,
        ncols: usize,
        indptr: PyReadonlyArray1<i64>,
        indices: PyReadonlyArray1<i64>,
        data: PyReadonlyArray1<f64>,
    ) -> PyResult<Self> {
        let col_ptr: Vec<usize> = indptr.as_slice()?.iter().map(|&x| x as usize).collect();
        let row_idx: Vec<usize> = indices.as_slice()?.iter().map(|&x| x as usize).collect();
        let val: Vec<f64> = data.as_slice()?.to_vec();
        let symbolic = SymbolicSparseColMat::new_checked(nrows, ncols, col_ptr, None, row_idx);
        let mat = SparseColMat::new(symbolic, val);
        let lu = mat
            .sp_lu()
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("faer sp_lu: {e:?}")))?;
        Ok(Self { lu, n: nrows })
    }

    /// Solve A x = b (or A^T x = b if transpose) for a single right-hand side.
    fn solve<'py>(
        &self,
        py: Python<'py>,
        b: PyReadonlyArray1<f64>,
        transpose: bool,
    ) -> PyResult<Bound<'py, PyArray1<f64>>> {
        let b = b.as_slice()?;
        let rhs = Mat::from_fn(self.n, 1, |i, _| b[i]);
        let x = if transpose {
            self.lu.solve_transpose(&rhs)
        } else {
            self.lu.solve(&rhs)
        };
        let out: Vec<f64> = (0..self.n).map(|i| x[(i, 0)]).collect();
        Ok(out.into_pyarray_bound(py))
    }
}
