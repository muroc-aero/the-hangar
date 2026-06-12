"""Case expansion: study spec -> normalized list of StudyCase.

Matrix blocks expand as a cartesian product of their axes; case blocks
insert one manual case each. Every case gets a deterministic ``case_key``
(hash of runner + spec + params) used for resume/checkpointing: re-running
a study skips cases whose key already completed, and editing a case's
parameters changes its key so it re-runs.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

from hangar.sdk.study.schema import DEFAULT_GUARD_MAX_CASES

_SELECTOR_RE = re.compile(r"^(?P<key>[^\[\]]+)(?:\[(?P<sel>[^\[\]]+)\])?$")


@dataclass
class StudyCase:
    """One normalized case ready for a runner."""

    case_id: str
    case_key: str
    runner: str
    params: dict = field(default_factory=dict)
    spec: dict = field(default_factory=dict)
    source: str = "matrix"  # "matrix" | "manual"

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "case_key": self.case_key,
            "runner": self.runner,
            "params": self.params,
            "spec": self.spec,
            "source": self.source,
        }


class ExpansionError(ValueError):
    """Raised when a study spec cannot be expanded into cases."""


def set_by_path(obj: Any, path: str, value: Any) -> None:
    """Set a value inside a nested dict/list structure by dotted path.

    Tokens are separated by ``.``; a token may carry an ``[id]`` selector
    that matches a list element whose ``id`` (or ``name``) equals the
    selector, e.g. ``components[mission].config.mission_params.range``.
    Intermediate dicts are created as needed; list selectors must match an
    existing element.
    """
    tokens = path.split(".")
    node = obj
    for i, token in enumerate(tokens):
        m = _SELECTOR_RE.match(token)
        if not m:
            raise ExpansionError(f"bad path token {token!r} in {path!r}")
        key, sel = m.group("key"), m.group("sel")
        last = i == len(tokens) - 1

        if not isinstance(node, dict):
            raise ExpansionError(
                f"cannot descend into non-mapping at {token!r} in {path!r}")
        if sel is None:
            if last:
                node[key] = value
                return
            node = node.setdefault(key, {})
        else:
            seq = node.get(key)
            if not isinstance(seq, list):
                raise ExpansionError(
                    f"{key!r} is not a list (needed for selector [{sel}]) in {path!r}")
            match = next(
                (el for el in seq
                 if isinstance(el, dict) and (el.get("id") == sel or el.get("name") == sel)),
                None,
            )
            if match is None:
                raise ExpansionError(
                    f"no element with id/name {sel!r} under {key!r} in {path!r}")
            if last:
                raise ExpansionError(
                    f"path {path!r} ends on a list selector; add a field to set")
            node = match


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursive dict merge; override wins, lists replace wholesale."""
    out = deepcopy(base)
    for key, val in override.items():
        if isinstance(val, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], val)
        else:
            out[key] = deepcopy(val)
    return out


def _axis_values(axis: dict) -> list:
    if "values" in axis:
        return list(axis["values"])
    start, stop, num = axis["linspace"]
    if num == 1:
        return [float(start)]
    step = (float(stop) - float(start)) / (num - 1)
    return [float(start) + i * step for i in range(num)]


def _fmt_value(val: Any) -> str:
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val).replace(" ", "_")


def _default_case_id(params: dict) -> str:
    return "-".join(f"{k}={_fmt_value(v)}" for k, v in params.items())


def _case_key(runner: str, spec: dict, params: dict) -> str:
    payload = json.dumps(
        {"runner": runner, "spec": spec, "params": params},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:12]


def expand_cases(study: dict) -> list[StudyCase]:
    """Expand a validated study spec into the full normalized case list.

    Raises :class:`ExpansionError` on duplicate case ids/keys or when the
    expansion exceeds ``execution.guard_max_cases`` (hard cap against
    accidental combinatorial blowup; raise the cap in the spec if the size
    is intentional).
    """
    defaults = study.get("defaults") or {}
    default_runner = defaults.get("runner", "omd")
    default_spec = defaults.get("spec") or {}
    guard = (study.get("execution") or {}).get(
        "guard_max_cases", DEFAULT_GUARD_MAX_CASES)

    cases: list[StudyCase] = []
    for i, block in enumerate(study.get("cases") or []):
        kind, body = next(iter(block.items()))
        if kind == "matrix":
            cases.extend(_expand_matrix(body, default_runner, default_spec))
        else:
            cases.append(_expand_manual(body, default_runner, default_spec))
        if len(cases) > guard:
            raise ExpansionError(
                f"expansion exceeded guard_max_cases={guard} at cases[{i}]; "
                "shrink the axes or raise execution.guard_max_cases if "
                "this size is intentional")

    _check_unique(cases)
    return cases


def _expand_matrix(block: dict, default_runner: str, default_spec: dict) -> list[StudyCase]:
    axes = block["axes"]
    bind = block["bind"]
    runner = block.get("runner", default_runner)
    tmpl = block.get("id_template")
    base_spec = _deep_merge(default_spec, block.get("spec") or {})

    names = list(axes)
    grids = [_axis_values(axes[n]) for n in names]
    out: list[StudyCase] = []
    for combo in itertools.product(*grids):
        params = dict(zip(names, combo))
        spec = deepcopy(base_spec)
        # Bindings land in spec["set"]: {spec_path: value}, applied by the
        # runner (for omd, paths navigate the plan dict).
        sets = spec.setdefault("set", {})
        for name, value in params.items():
            for path in bind[name]:
                sets[path] = value
        if tmpl:
            try:
                case_id = tmpl.format(**params)
            except (KeyError, ValueError) as exc:
                raise ExpansionError(f"id_template {tmpl!r} failed: {exc}") from exc
        else:
            case_id = _default_case_id(params)
        out.append(StudyCase(
            case_id=case_id,
            case_key=_case_key(runner, spec, params),
            runner=runner,
            params=params,
            spec=spec,
            source="matrix",
        ))
    return out


def _expand_manual(block: dict, default_runner: str, default_spec: dict) -> StudyCase:
    runner = block.get("runner", default_runner)
    spec = _deep_merge(default_spec, block["spec"])
    params = dict(block.get("params") or {})
    return StudyCase(
        case_id=block["id"],
        case_key=_case_key(runner, spec, params),
        runner=runner,
        params=params,
        spec=spec,
        source="manual",
    )


def _check_unique(cases: list[StudyCase]) -> None:
    seen_ids: dict[str, int] = {}
    seen_keys: dict[str, str] = {}
    for case in cases:
        if case.case_id in seen_ids:
            raise ExpansionError(
                f"duplicate case_id {case.case_id!r}; use id_template or "
                "distinct manual ids")
        seen_ids[case.case_id] = 1
        if case.case_key in seen_keys:
            raise ExpansionError(
                f"cases {seen_keys[case.case_key]!r} and {case.case_id!r} "
                "are identical (same runner, spec, and params)")
        seen_keys[case.case_key] = case.case_id
