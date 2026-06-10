"""Shared helpers for pyCycle MCP tools."""

from __future__ import annotations

import time

from hangar.sdk.artifacts.store import _make_run_id  # noqa: F401 -- re-export
from hangar.sdk.auth import get_current_user
from hangar.sdk.envelope.response import make_envelope
from hangar.sdk.validation.requirements import requirements_findings
from hangar.sdk.telemetry import make_telemetry
from hangar.pyc.state import artifacts as _artifacts

from hangar.pyc.validation import ValidationFinding, findings_to_dict


async def _finalize_analysis(
    tool_name: str,
    run_id: str,
    session,
    session_id: str,
    engine_name: str,
    analysis_type: str,
    inputs: dict,
    results: dict,
    findings: list[ValidationFinding],
    t0: float,
    cache_hit: bool = False,
    run_name: str | None = None,
) -> dict:
    """Build response envelope, save artifact, validate requirements."""
    # Inject failed requirements as validation findings
    findings.extend(requirements_findings(session.requirements, results))

    validation = findings_to_dict(findings)
    elapsed = time.perf_counter() - t0
    telem = make_telemetry(elapsed, cache_hit, 1, None)

    user = get_current_user()
    _artifacts.save(
        session_id=session_id,
        analysis_type=analysis_type,
        tool_name=tool_name,
        surfaces=[engine_name],
        parameters=inputs,
        results=results,
        user=user,
        project=session.project,
        name=run_name,
        validation=validation,
        telemetry=telem,
        run_id=run_id,
    )

    # Auto-prune
    if session.defaults.retention_max_count is not None:
        _artifacts.cleanup(
            user=user,
            project=session.project,
            session_id=session_id,
            max_count=session.defaults.retention_max_count,
            protected_run_ids=set(session._pinned),
        )

    return make_envelope(tool_name, run_id, inputs, results, validation, telem)
