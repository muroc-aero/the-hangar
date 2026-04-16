"""Resolve element_path strings into plan sub-elements.

An element_path addresses a specific sub-element of a plan so that
decisions can point at what they justify, the plan knowledge graph
can emit `justifies` edges with a concrete target, and the plan
review checker can warn when a path fails to resolve.

Supported syntax:

    components[wing]                  bracket-id: match list item by id or name
    components[wing].config.num_y     dot segments: map-key lookup
    design_variables[twist_cp].upper  works on DVs / constraints by name
    connections[0].src                bracket-integer: positional fallback
    requirements[R1]                  requirement by id

Return:

    resolve_element_path(plan, path) -> ResolvedPath | None

where ResolvedPath is a simple structure carrying the resolved value,
its parent dict/list, and a stable entity key usable as a graph-node id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_SEGMENT_RE = re.compile(r"([^.\[\]]+)(?:\[([^\]]+)\])?")


@dataclass
class ResolvedPath:
    """A successfully resolved element path.

    Attributes:
        value: The resolved element (any JSON-compatible type).
        entity_key: A stable identifier suitable as a graph node id,
            e.g. "components[wing].config.num_y".
        entity_kind: Short kind hint for entity typing, e.g.
            "component", "design_variable", "constraint", "requirement",
            "surface", "phase", "scalar", "list", "map".
    """

    value: Any
    entity_key: str
    entity_kind: str


# Segment heads that address known plan sections; used to emit a
# better entity_kind hint when the resolved value is an element of one
# of these arrays.
_KIND_BY_HEAD: dict[str, str] = {
    "components": "component",
    "design_variables": "design_variable",
    "constraints": "constraint",
    "requirements": "requirement",
    "operating_points": "operating_point",
    "connections": "connection",
    "phases": "phase",
    "acceptance_criteria": "acceptance_criterion",
    "surfaces": "surface",
    "flight_points": "flight_point",
}


def _split_on_dots(path: str) -> list[str]:
    """Split on '.' but respect bracketed sections (so [wing.twist_cp] stays one)."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in path:
        if ch == "[":
            depth += 1
            buf.append(ch)
        elif ch == "]":
            if depth == 0:
                raise ValueError(f"unmatched ']' in path: {path!r}")
            depth -= 1
            buf.append(ch)
        elif ch == "." and depth == 0:
            if buf:
                parts.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if depth != 0:
        raise ValueError(f"unmatched '[' in path: {path!r}")
    if buf:
        parts.append("".join(buf))
    return parts


def _parse_segments(path: str) -> list[tuple[str, str | None]]:
    """Split a dotted bracketed path into (head, bracket) segments.

    Examples:
        "components[wing].config.num_y" ->
            [("components", "wing"), ("config", None), ("num_y", None)]
        "design_variables[wing.twist_cp]" ->
            [("design_variables", "wing.twist_cp")]
    """
    segments: list[tuple[str, str | None]] = []
    for raw in _split_on_dots(path):
        if not raw:
            continue
        match = _SEGMENT_RE.fullmatch(raw.strip())
        if not match:
            raise ValueError(f"malformed path segment: {raw!r}")
        segments.append((match.group(1), match.group(2)))
    return segments


def _match_list_item(items: list, key: str) -> tuple[int, Any] | None:
    """Find a list item by id or name, or by integer index.

    Returns (index, item) if found, else None.
    """
    # Integer index fallback
    if key.isdigit() or (key.startswith("-") and key[1:].isdigit()):
        idx = int(key)
        if -len(items) <= idx < len(items):
            return idx % len(items), items[idx]
        return None

    # Id / name match
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if item.get("id") == key or item.get("name") == key:
            return i, item
    return None


def _kind_for(head: str, value: Any) -> str:
    """Best-effort entity_kind hint for a resolved value."""
    if head in _KIND_BY_HEAD:
        return _KIND_BY_HEAD[head]
    if isinstance(value, dict):
        return "map"
    if isinstance(value, list):
        return "list"
    return "scalar"


def resolve_element_path(plan: dict, path: str | None) -> ResolvedPath | None:
    """Resolve an element_path against an assembled plan.

    Args:
        plan: The assembled plan dict.
        path: The element_path string. Empty / None returns None.

    Returns:
        ResolvedPath on success, None if the path fails to resolve or
        is empty. Malformed paths (syntactically invalid) also return
        None so callers can handle them uniformly via the completeness
        checker.
    """
    if not path:
        return None
    try:
        segments = _parse_segments(path)
    except ValueError:
        return None
    if not segments:
        return None

    current: Any = plan
    last_head = segments[-1][0]
    canonical_parts: list[str] = []

    for head, bracket in segments:
        if not isinstance(current, dict):
            return None
        if head not in current:
            return None
        current = current[head]

        if bracket is None:
            canonical_parts.append(head)
            continue

        if not isinstance(current, list):
            return None
        hit = _match_list_item(current, bracket)
        if hit is None:
            return None
        _, current = hit
        canonical_parts.append(f"{head}[{bracket}]")

    entity_key = ".".join(canonical_parts)
    return ResolvedPath(
        value=current,
        entity_key=entity_key,
        entity_kind=_kind_for(last_head, current),
    )


def element_entity_id(plan_entity_id: str, resolved: ResolvedPath) -> str:
    """Construct a stable provenance-entity id for a resolved element.

    The id is rooted at the plan entity so that different plan
    versions produce different element ids and the DAG stays clean.
    """
    return f"{plan_entity_id}/elem/{resolved.entity_key}"
