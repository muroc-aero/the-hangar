"""Study state on disk.

Layout (tool-independent; per-tool run provenance stays in each tool's
own store and is referenced by ``run_ref``):

.. code-block:: text

    {studies_root}/{study_id}/
      study.yaml          -- latest spec copy
      v{N}/study.yaml     -- spec snapshot per version
      state.json          -- per-case status, run refs, outputs
      cases.csv           -- spreadsheet export, regenerated on update
      cases/{case_id}/    -- runner-written case artifacts (e.g. omd plans)

``state.json`` is keyed by ``case_key`` so resume survives case-id renames
and spec edits re-run exactly the cases they touched. Only the orchestrator
process writes state; workers return results to it.
"""

from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from hangar.sdk.study.expand import StudyCase


def studies_root() -> Path:
    """Root directory for study state.

    ``HANGAR_STUDY_DIR`` env var, or ``{HANGAR_DATA_DIR}/studies`` (default
    ``./hangar_data/studies``).
    """
    from hangar.sdk.env import _hangar_env

    env = os.environ.get("HANGAR_STUDY_DIR")
    if env:
        return Path(env)
    data_dir = _hangar_env("HANGAR_DATA_DIR", "OAS_DATA_DIR", default="./hangar_data")
    return Path(data_dir) / "studies"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class StudyStore:
    """Filesystem-backed state for one study."""

    def __init__(self, study_id: str, root: Path | None = None) -> None:
        if any(c in study_id for c in "/\\") or ".." in study_id:
            raise ValueError(f"unsafe study_id {study_id!r}")
        self.study_id = study_id
        self.dir = (root or studies_root()) / study_id
        self.state_path = self.dir / "state.json"
        self.csv_path = self.dir / "cases.csv"

    # -- spec ---------------------------------------------------------------

    def save_spec(self, spec_text: str, version: int) -> Path:
        """Persist the spec text as the latest copy and a version snapshot."""
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "study.yaml").write_text(spec_text)
        snap_dir = self.dir / f"v{version}"
        snap_dir.mkdir(parents=True, exist_ok=True)
        snap = snap_dir / "study.yaml"
        snap.write_text(spec_text)
        return snap

    def case_artifact_dir(self, case_id: str) -> Path:
        """Directory for runner-written artifacts of one case."""
        safe = case_id.replace("/", "_").replace("\\", "_")
        path = self.dir / "cases" / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- state --------------------------------------------------------------

    def load_state(self) -> dict:
        if not self.state_path.exists():
            return {"study_id": self.study_id, "version": None, "owner": "",
                    "created_at": _now(), "updated_at": _now(), "cases": {}}
        return json.loads(self.state_path.read_text())

    def set_owner_if_absent(self, owner: str | None) -> None:
        """Stamp the study's owner once, at creation.

        Sourced from ``get_current_user()`` by the orchestrator (the MCP
        request user, or the OS/``HANGAR_USER`` login for CLI runs). Used by
        the dashboard to scope the study list per user; admins see all.
        Never overwrites an existing owner, so a later run by a different
        user does not reassign ownership.
        """
        if not owner:
            return
        state = self.load_state()
        if state.get("owner"):
            return
        state["owner"] = owner
        self._write_state(state)

    def _write_state(self, state: dict) -> None:
        state["updated_at"] = _now()
        self.dir.mkdir(parents=True, exist_ok=True)
        # Atomic replace so a crash mid-write cannot corrupt resume state.
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".state.tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(state, f, indent=2, default=str)
            os.replace(tmp, self.state_path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def sync_cases(self, cases: list[StudyCase], version: int) -> dict:
        """Merge the expanded case list into state, preserving completions.

        New case keys enter as ``pending``; existing keys keep their status
        and results. Keys no longer produced by the spec are kept but
        flagged ``in_spec: false`` so their history is not lost.
        """
        state = self.load_state()
        state["version"] = version
        existing = state["cases"]
        current_keys = set()
        for case in cases:
            current_keys.add(case.case_key)
            entry = existing.get(case.case_key)
            if entry is None:
                existing[case.case_key] = {
                    "case_id": case.case_id,
                    "runner": case.runner,
                    "params": case.params,
                    "source": case.source,
                    "status": "pending",
                    "run_ref": None,
                    "outputs": {},
                    "error": None,
                    "wall_time_s": None,
                    "attempts": [],
                    "in_spec": True,
                }
            else:
                entry["case_id"] = case.case_id
                entry["in_spec"] = True
        for key, entry in existing.items():
            if key not in current_keys:
                entry["in_spec"] = False
        self._write_state(state)
        return state

    def update_case(self, case_key: str, **fields) -> dict:
        """Update one case entry and rewrite state + csv."""
        state = self.load_state()
        entry = state["cases"].get(case_key)
        if entry is None:
            raise KeyError(f"unknown case_key {case_key!r} in study {self.study_id!r}")
        entry.update(fields)
        self._write_state(state)
        self.export_csv(state)
        return entry

    # -- projections ----------------------------------------------------------

    def status_summary(self, state: dict | None = None) -> dict:
        """Progress counts and mean wall time over completed cases."""
        state = state or self.load_state()
        cases = [c for c in state["cases"].values() if c.get("in_spec", True)]
        counts: dict[str, int] = {}
        walls: list[float] = []
        for c in cases:
            counts[c["status"]] = counts.get(c["status"], 0) + 1
            if c.get("wall_time_s"):
                walls.append(float(c["wall_time_s"]))
        done = sum(v for k, v in counts.items() if k not in ("pending", "running"))
        return {
            "study_id": self.study_id,
            "version": state.get("version"),
            "owner": state.get("owner", ""),
            "total": len(cases),
            "done": done,
            "counts": counts,
            "mean_case_wall_s": (sum(walls) / len(walls)) if walls else None,
            "updated_at": state.get("updated_at"),
        }

    def export_csv(self, state: dict | None = None) -> Path:
        """Write the spreadsheet-style case table.

        Columns: case_id, params (one column per key), status, runner,
        run_ref, outputs (one column per key), wall_time_s, error.
        """
        state = state or self.load_state()
        cases = [c for c in state["cases"].values() if c.get("in_spec", True)]
        param_keys: list[str] = []
        output_keys: list[str] = []
        for c in cases:
            for k in c.get("params", {}):
                if k not in param_keys:
                    param_keys.append(k)
            for k in c.get("outputs", {}) or {}:
                if k not in output_keys:
                    output_keys.append(k)
        header = (["case_id"] + param_keys
                  + ["status", "runner", "run_ref"]
                  + output_keys + ["wall_time_s", "error"])
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(header)
            for c in sorted(cases, key=lambda c: c["case_id"]):
                row = [c["case_id"]]
                row += [c.get("params", {}).get(k, "") for k in param_keys]
                row += [c["status"], c.get("runner", ""), c.get("run_ref") or ""]
                row += [(c.get("outputs") or {}).get(k, "") for k in output_keys]
                row += [c.get("wall_time_s") or "", c.get("error") or ""]
                writer.writerow(row)
        return self.csv_path


def list_studies(root: Path | None = None) -> list[dict]:
    """Summaries of all studies under the root, newest update first."""
    base = root or studies_root()
    if not base.exists():
        return []
    out = []
    for child in sorted(base.iterdir()):
        if not (child / "state.json").exists():
            continue
        try:
            store = StudyStore(child.name, root=base)
            out.append(store.status_summary())
        except Exception:
            continue
    out.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
    return out
