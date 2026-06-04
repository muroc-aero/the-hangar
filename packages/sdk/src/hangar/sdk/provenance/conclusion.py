"""Conclusion artifacts for the concluding stage (sdk session sources).

The concluding stage is something an agent actively *does*: it picks the run
that answers the study and records what that run means for the requirements.
This module mirrors omd's ``record_conclusion`` (see ``hangar.omd.run``) for the
session-centric sdk servers (oas / ocp / pyc).

The verdict is *auto-derived*: each persisted requirement (``set_requirements`` /
``configure_session``, persisted by #30) is evaluated against the chosen run's
results with the same comparator logic the validation block uses, so the per
requirement verdict cannot drift from the numbers. The agent supplies only the
chosen run and a short narrative.

A conclusion is stored as a ``decision`` row with ``decision_type='conclusion'``
and the payload in ``metadata_json`` (read back by ``db.get_conclusion`` and the
range-safety dashboard's ``SdkSessionSource``).
"""

from __future__ import annotations

import json

from hangar.sdk.provenance import db
from hangar.sdk.validation.requirements import check_requirements


def derive_conclusion(
    requirements: list[dict],
    results: dict,
    narrative: str = "",
) -> dict:
    """Evaluate *requirements* against a run's *results* into a verdict payload.

    Pure (no DB writes). Returns ``{verdict, narrative, metrics, requirements}``
    where ``verdict`` is the overall ``meets`` / ``fails`` / ``partial`` / ``open``
    and ``requirements`` is a per-requirement list shaped like the omd conclusion
    (``id, text, priority, verdict, criteria``) so both sources render the same
    report. A requirement is ``satisfies`` when its assertion passes, ``violates``
    when it fails, and ``open`` when it cannot be evaluated (path missing / type
    mismatch).
    """
    # Optimization envelopes nest the final scalars under ``final_results``
    # (analysis envelopes expose them at the top level). Overlay that sub-dict so
    # requirement paths like ``CL`` / ``CD`` resolve and the metric snapshot is
    # populated for optimization runs too, matching how the result views read them.
    results = results or {}
    final = results.get("final_results")
    if isinstance(final, dict):
        results = {**results, **final}

    checked = check_requirements(requirements or [], results)

    req_results: list[dict] = []
    for outcome in checked.get("results", []):
        evaluable = not outcome.get("error")
        if not evaluable:
            verdict = "open"
        elif outcome.get("passed"):
            verdict = "satisfies"
        else:
            verdict = "violates"
        req_results.append({
            "id": outcome.get("label"),
            "text": outcome.get("label"),
            "priority": None,  # sdk has no priority taxonomy
            "verdict": verdict,
            "criteria": [{
                "metric": outcome.get("path"),
                "comparator": outcome.get("operator"),
                "threshold": outcome.get("target"),
                "actual": outcome.get("actual"),
                "passed": outcome.get("passed") if evaluable else None,
            }],
        })

    verdicts = [r["verdict"] for r in req_results]
    if verdicts and all(v == "satisfies" for v in verdicts):
        overall = "meets"
    elif any(v == "violates" for v in verdicts):
        overall = "fails"
    elif verdicts:
        overall = "partial"  # some open, none violated
    else:
        overall = "open"  # nothing evaluable to judge

    # Snapshot the run's headline scalars so the report's numbers are frozen
    # alongside the verdict (a dict {name: value}; the dashboard formats it).
    metrics = {
        k: v
        for k, v in (results or {}).items()
        if isinstance(v, (int, float)) and not isinstance(v, bool) and not k.startswith("_")
    }

    return {
        "verdict": overall,
        "narrative": narrative,
        "metrics": metrics,
        "requirements": req_results,
    }


def record_conclusion(
    session_id: str,
    run_id: str,
    results: dict,
    narrative: str = "",
    requirements: list[dict] | None = None,
) -> dict:
    """Derive and persist a conclusion for *run_id* under *session_id*.

    Reads the session's persisted requirements (unless *requirements* is passed
    explicitly, mainly for tests), evaluates them against *results*, and writes a
    ``conclusion`` decision row carrying the verdict payload. The decision id is
    ``conclusion-{run_id}`` so re-concluding the same run overwrites in place
    (idempotent, matching omd).

    Returns the payload plus ``conclusion_id`` and ``run_id``.
    """
    if requirements is None:
        requirements = db.get_requirements(session_id)

    payload = derive_conclusion(requirements, results, narrative)
    payload["run_id"] = run_id

    conclusion_id = f"conclusion-{run_id}"
    db.record_decision(
        decision_id=conclusion_id,
        session_id=session_id,
        seq=db._next_seq(session_id),
        decision_type="conclusion",
        reasoning=narrative,
        prior_call_id=run_id,
        selected_action=payload["verdict"],
        confidence="high",
        metadata_json=json.dumps(payload),
    )

    payload["conclusion_id"] = conclusion_id
    return payload
