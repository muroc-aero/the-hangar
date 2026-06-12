"""Tool-independent study layer: many analysis cases under one spec.

A *study* groups many sub-analysis cases. Each case is executed by a
*runner* (e.g. the omd plan runner); different cases in one study may use
different runners. The study core here owns everything tool-agnostic:

- ``schema``  -- study.yaml validation
- ``expand``  -- case expansion (matrix axes, explicit/manual cases)
- ``review``  -- case-count / compute / wall-time estimate (blowup guard)
- ``store``   -- study state on disk under ``hangar_data/studies/``
- ``orchestrate`` -- worker pool, incremental batches, resume, multistart

Runners register via :func:`register_runner`; the omd adapter lives in
``hangar.omd.study_runner``. This package must not import OpenMDAO or any
tool package.
"""

from hangar.sdk.study.expand import StudyCase, expand_cases, set_by_path
from hangar.sdk.study.orchestrate import (
    SUCCESS_STATUSES,
    StudyGuardError,
    get_runner,
    register_runner,
    run_study,
)
from hangar.sdk.study.review import review_study
from hangar.sdk.study.schema import load_study, validate_study
from hangar.sdk.study.store import StudyStore, studies_root

__all__ = [
    "StudyCase",
    "StudyGuardError",
    "StudyStore",
    "SUCCESS_STATUSES",
    "expand_cases",
    "get_runner",
    "load_study",
    "register_runner",
    "review_study",
    "run_study",
    "set_by_path",
    "studies_root",
    "validate_study",
]
