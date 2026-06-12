"""Tool-independent study layer: many analysis cases under one spec.

A *study* groups many sub-analysis cases. Each case is executed by a
*runner* (e.g. the omd plan runner); different cases in one study may use
different runners. The study core here owns everything tool-agnostic:

- ``schema``  -- study.yaml validation
- ``expand``  -- case expansion (matrix axes, explicit/manual cases)
- ``review``  -- case-count / compute / wall-time estimate (blowup guard)
- ``store``   -- study state on disk under ``hangar_data/studies/``
- ``orchestrate`` -- worker pool, incremental batches, resume, multistart

Runners register via :func:`register_runner` and are discovered lazily
through the ``hangar.study_runners`` entry-point group (each tool package
advertises its adapter module, e.g. ``hangar.omd.study_runner`` for "omd").
Tools whose CLI is built on :mod:`hangar.sdk.cli` get a runner almost for
free via :func:`make_script_runner`. This package must not import OpenMDAO
or any tool package at module level.
"""

from hangar.sdk.study.expand import StudyCase, expand_cases, set_by_path
from hangar.sdk.study.orchestrate import (
    SUCCESS_STATUSES,
    StudyGuardError,
    get_runner,
    list_available_runners,
    register_runner,
    run_study,
)
from hangar.sdk.study.review import review_study
from hangar.sdk.study.schema import load_study, validate_study
from hangar.sdk.study.script_runner import make_script_runner
from hangar.sdk.study.store import StudyStore, studies_root

__all__ = [
    "StudyCase",
    "StudyGuardError",
    "StudyStore",
    "SUCCESS_STATUSES",
    "expand_cases",
    "get_runner",
    "list_available_runners",
    "load_study",
    "make_script_runner",
    "register_runner",
    "review_study",
    "run_study",
    "set_by_path",
    "studies_root",
    "validate_study",
]
