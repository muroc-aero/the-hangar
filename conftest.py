"""Repo-wide pytest configuration."""

import pytest


@pytest.fixture(scope="session", autouse=True)
def _openmdao_workdir(tmp_path_factory):
    """Send OpenMDAO problem-output directories to pytest's temp area.

    OpenMDAO creates ``<problem-name>_out/`` under ``OPENMDAO_WORKDIR``
    (falling back to the process cwd) for every Problem; under pytest the
    default problem name derives from the running script, so test runs
    would litter the repo root with a ``pytest_out/`` directory. OpenMDAO
    special-cases testflo via TESTFLO_RUNNING but not pytest, so do the
    equivalent here. pytest prunes its own temp area (keeps the last few
    runs), so nothing needs manual cleanup.
    """
    mp = pytest.MonkeyPatch()
    mp.setenv("OPENMDAO_WORKDIR", str(tmp_path_factory.mktemp("openmdao_workdir")))
    yield
    mp.undo()
