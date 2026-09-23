"""pytest plugin: keep OpenMDAO problem-output directories out of the repo.

OpenMDAO >= 3.35 creates ``<problem-name>_out/`` under ``OPENMDAO_WORKDIR``
(falling back to the process cwd) whenever a Problem needs an output path:
reports, coloring files, a relative recorder path. Under pytest the default
problem name derives from the launching script, so test runs litter the
launch directory with ``pytest_out/``, ``__main__2_out/``, ... OpenMDAO
special-cases testflo (TESTFLO_RUNNING) but not pytest.

A repo-root conftest.py cannot do this reliably: each package and each
per-example parity suite resolves its own pytest rootdir from the nearest
pyproject.toml, and conftest files above the rootdir are never loaded. This
module is registered through hangar-sdk's ``pytest11`` entry point, so it is
active in every pytest invocation inside the workspace venv whatever the
rootdir. An OPENMDAO_WORKDIR already present in the environment is kept.

pytest prunes its own temp area (last few runs), so nothing needs cleanup.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _hangar_openmdao_workdir(tmp_path_factory):
    if os.environ.get("OPENMDAO_WORKDIR"):
        yield
        return
    mp = pytest.MonkeyPatch()
    mp.setenv("OPENMDAO_WORKDIR", str(tmp_path_factory.mktemp("openmdao_workdir")))
    yield
    mp.undo()
