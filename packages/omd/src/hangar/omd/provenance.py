"""Provenance visualization: timelines, DAG HTML, version diffs.

Provides human-readable and machine-readable views of the PROV-Agent
provenance graph stored in the analysis database.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from hangar.omd.db import (
    init_analysis_db,
    query_provenance_dag,
    query_entity,
)


def provenance_timeline(
    plan_id: str,
    db_path: Path | None = None,
) -> str:
    """Generate a human-readable timeline for a plan's provenance.

    Args:
        plan_id: Plan identifier to query.
        db_path: Path to analysis DB (initializes if needed).

    Returns:
        Formatted text timeline string.
    """
    init_analysis_db(db_path)
    dag = query_provenance_dag(plan_id)

    if not dag["entities"] and not dag["activities"]:
        return f"No provenance found for plan: {plan_id}"

    # Build timeline entries sorted by timestamp
    entries = []

    for entity in dag["entities"]:
        entries.append({
            "timestamp": entity.get("created_at", ""),
            "type": "entity",
            "id": entity["entity_id"],
            "entity_type": entity.get("entity_type", "unknown"),
            "created_by": entity.get("created_by", "unknown"),
            "version": entity.get("version"),
        })

    for activity in dag["activities"]:
        entries.append({
            "timestamp": activity.get("started_at", ""),
            "type": "activity",
            "id": activity["activity_id"],
            "activity_type": activity.get("activity_type", "unknown"),
            "agent": activity.get("agent", "unknown"),
            "status": activity.get("status", "unknown"),
        })

    entries.sort(key=lambda e: e["timestamp"])

    # Format as text
    lines = [f"Provenance timeline for: {plan_id}", "=" * 60]

    for entry in entries:
        ts = entry["timestamp"][:19] if entry["timestamp"] else "?"
        if entry["type"] == "entity":
            version_str = f" v{entry['version']}" if entry["version"] else ""
            lines.append(
                f"  [{ts}] {entry['entity_type']}{version_str}"
                f" ({entry['id']}) by {entry['created_by']}"
            )
        else:
            lines.append(
                f"  [{ts}] {entry['activity_type'].upper()}"
                f" ({entry['id']}) by {entry['agent']}"
                f" -- {entry['status']}"
            )

    # Add edge summary
    if dag["edges"]:
        lines.append("")
        lines.append("Edges:")
        for edge in dag["edges"]:
            lines.append(
                f"  {edge['subject_id']} --{edge['relation']}--> {edge['object_id']}"
            )

    return "\n".join(lines)


def provenance_dag_html(
    plan_id: str,
    output_path: Path,
    db_path: Path | None = None,
) -> Path:
    """Generate an HTML visualization of the provenance DAG.

    Uses Cytoscape.js with dagre layout (top-to-bottom), entity-type
    coloring, click-to-inspect details panel, and dashed wasDerivedFrom
    edges for replan scenarios.

    Args:
        plan_id: Plan identifier.
        output_path: Path to write HTML file.
        db_path: Path to analysis DB.

    Returns:
        Path to the generated HTML file.
    """
    init_analysis_db(db_path)
    dag = query_provenance_dag(plan_id)

    # Build Cytoscape elements with rich data attributes
    nodes = []
    for entity in dag["entities"]:
        etype = entity.get("entity_type", "unknown")
        nodes.append({
            "data": {
                "id": entity["entity_id"],
                "label": f"{etype}\n{entity['entity_id']}",
                "type": "entity",
                "entity_type": etype,
                "created_at": entity.get("created_at", ""),
                "created_by": entity.get("created_by", ""),
                "version": entity.get("version"),
                "content_hash": entity.get("content_hash", ""),
                "storage_ref": entity.get("storage_ref", ""),
            }
        })

    for activity in dag["activities"]:
        status = activity.get("status", "unknown")
        nodes.append({
            "data": {
                "id": activity["activity_id"],
                "label": (
                    f"{activity.get('activity_type', '?').upper()}\n"
                    f"{activity.get('agent', '?')}"
                ),
                "type": "activity",
                "activity_type": activity.get("activity_type", ""),
                "agent": activity.get("agent", ""),
                "started_at": activity.get("started_at", ""),
                "completed_at": activity.get("completed_at", ""),
                "status": status,
            }
        })

    edges = []
    for edge in dag["edges"]:
        relation = edge["relation"]
        edges.append({
            "data": {
                "source": edge["subject_id"],
                "target": edge["object_id"],
                "label": relation,
                "relation": relation,
            }
        })

    elements_json = json.dumps(nodes + edges)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Provenance DAG: {plan_id}</title>
    <script src="https://unpkg.com/cytoscape@3/dist/cytoscape.min.js"></script>
    <script src="https://unpkg.com/dagre@0.8/dist/dagre.min.js"></script>
    <script src="https://unpkg.com/cytoscape-dagre@2/cytoscape-dagre.js"></script>
    <style>
        body {{ margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
               background: #f5f5f5; }}
        #header {{ padding: 12px 20px; background: #fff; border-bottom: 1px solid #ddd;
                   display: flex; align-items: center; gap: 12px; }}
        #header h1 {{ font-size: 16px; color: #333; margin: 0; }}
        #legend {{ font-size: 11px; color: #666; display: flex; gap: 16px; }}
        .legend-item {{ display: flex; align-items: center; gap: 4px; }}
        .legend-dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
        #cy {{ width: 100%; height: calc(100vh - 90px); }}
        #detail-panel {{ position: absolute; bottom: 0; left: 0; right: 0;
                         background: #fff; border-top: 2px solid #ddd;
                         padding: 12px 20px; font-size: 13px; display: none;
                         max-height: 200px; overflow-y: auto; }}
        #detail-panel h3 {{ margin: 0 0 8px 0; font-size: 14px; }}
        #detail-panel .field {{ margin: 2px 0; }}
        #detail-panel .field-label {{ color: #666; }}
    </style>
</head>
<body>
    <div id="header">
        <h1>Provenance DAG: {plan_id}</h1>
        <div id="legend">
            <span class="legend-item"><span class="legend-dot" style="background:#7b2d8e"></span> Plan</span>
            <span class="legend-item"><span class="legend-dot" style="background:#4a90d9"></span> Run</span>
            <span class="legend-item"><span class="legend-dot" style="background:#e6a23c"></span> Activity</span>
            <span class="legend-item"><span class="legend-dot" style="background:#27ae60"></span> Pass</span>
            <span class="legend-item"><span class="legend-dot" style="background:#e74c3c"></span> Fail</span>
        </div>
    </div>
    <div id="cy"></div>
    <div id="detail-panel"></div>
    <script>
        var cy = cytoscape({{
            container: document.getElementById('cy'),
            elements: {elements_json},
            style: [
                /* Plan entities: purple */
                {{ selector: 'node[entity_type="plan"]',
                   style: {{ 'background-color': '#7b2d8e', 'label': 'data(label)',
                            'text-wrap': 'wrap', 'font-size': '10px', 'color': '#333',
                            'text-valign': 'bottom', 'text-margin-y': 5,
                            'width': 36, 'height': 36 }} }},
                /* Run entities: blue */
                {{ selector: 'node[entity_type="run_record"]',
                   style: {{ 'background-color': '#4a90d9', 'label': 'data(label)',
                            'text-wrap': 'wrap', 'font-size': '10px', 'color': '#333',
                            'text-valign': 'bottom', 'text-margin-y': 5,
                            'width': 36, 'height': 36 }} }},
                /* Assessment/validation: green or red by status */
                {{ selector: 'node[entity_type="assessment"]',
                   style: {{ 'background-color': '#27ae60', 'label': 'data(label)',
                            'text-wrap': 'wrap', 'font-size': '10px',
                            'width': 30, 'height': 30 }} }},
                {{ selector: 'node[entity_type="validation_report"]',
                   style: {{ 'background-color': '#e6a23c', 'label': 'data(label)',
                            'text-wrap': 'wrap', 'font-size': '10px',
                            'width': 30, 'height': 30 }} }},
                /* Fallback entity style */
                {{ selector: 'node[type="entity"]',
                   style: {{ 'background-color': '#95a5a6', 'label': 'data(label)',
                            'text-wrap': 'wrap', 'font-size': '10px',
                            'width': 30, 'height': 30 }} }},
                /* Activities: orange diamonds */
                {{ selector: 'node[type="activity"]',
                   style: {{ 'background-color': '#e6a23c', 'shape': 'diamond',
                            'label': 'data(label)', 'text-wrap': 'wrap',
                            'font-size': '10px', 'color': '#333',
                            'text-valign': 'bottom', 'text-margin-y': 5,
                            'width': 32, 'height': 32 }} }},
                /* Failed activities: red border */
                {{ selector: 'node[status="failed"]',
                   style: {{ 'border-width': 3, 'border-color': '#e74c3c' }} }},
                /* Normal edges: solid */
                {{ selector: 'edge',
                   style: {{ 'width': 2, 'line-color': '#999',
                            'target-arrow-color': '#999', 'target-arrow-shape': 'triangle',
                            'curve-style': 'bezier', 'label': 'data(label)',
                            'font-size': '8px', 'color': '#777' }} }},
                /* wasDerivedFrom edges: dashed purple */
                {{ selector: 'edge[relation="wasDerivedFrom"]',
                   style: {{ 'line-style': 'dashed', 'line-color': '#7b2d8e',
                            'target-arrow-color': '#7b2d8e', 'width': 2.5 }} }}
            ],
            layout: {{ name: 'dagre', rankDir: 'TB', padding: 50, spacingFactor: 1.5 }}
        }});

        /* Click handler: show details panel */
        var panel = document.getElementById('detail-panel');
        cy.on('tap', 'node', function(evt) {{
            var d = evt.target.data();
            var html = '<h3>' + d.id + '</h3>';
            var fields = ['entity_type', 'activity_type', 'status', 'agent',
                          'created_at', 'started_at', 'completed_at',
                          'created_by', 'version', 'content_hash', 'storage_ref'];
            for (var i = 0; i < fields.length; i++) {{
                if (d[fields[i]]) {{
                    html += '<div class="field"><span class="field-label">' +
                            fields[i] + ':</span> ' + d[fields[i]] + '</div>';
                }}
            }}
            panel.innerHTML = html;
            panel.style.display = 'block';
        }});
        cy.on('tap', function(evt) {{
            if (evt.target === cy) panel.style.display = 'none';
        }});
    </script>
</body>
</html>"""

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    return output_path


def provenance_diff(
    plan_id: str,
    version_a: int,
    version_b: int,
    db_path: Path | None = None,
) -> dict:
    """Compute diff between two plan versions.

    Args:
        plan_id: Plan identifier.
        version_a: First version number.
        version_b: Second version number.
        db_path: Path to analysis DB.

    Returns:
        Dict with version_a, version_b, entity_a, entity_b,
        and diff summary.
    """
    init_analysis_db(db_path)

    entity_a = query_entity(f"{plan_id}/v{version_a}")
    entity_b = query_entity(f"{plan_id}/v{version_b}")

    result: dict = {
        "plan_id": plan_id,
        "version_a": version_a,
        "version_b": version_b,
    }

    # Load plan files if storage_ref points to YAML files
    plan_a = _load_plan_from_entity(entity_a)
    plan_b = _load_plan_from_entity(entity_b)

    if plan_a and plan_b:
        result["changes"] = _compute_plan_diff(plan_a, plan_b)
    else:
        result["changes"] = []

    # Entity metadata diff
    result["entity_a"] = entity_a
    result["entity_b"] = entity_b

    if entity_a and entity_b:
        hash_a = entity_a.get("content_hash", "")
        hash_b = entity_b.get("content_hash", "")
        result["content_changed"] = hash_a != hash_b
    else:
        result["content_changed"] = None

    return result


def _load_plan_from_entity(entity: dict | None) -> dict | None:
    """Try to load plan YAML from entity's storage_ref."""
    if entity is None:
        return None
    ref = entity.get("storage_ref")
    if ref and Path(ref).exists():
        try:
            with open(ref) as f:
                return yaml.safe_load(f)
        except Exception:
            return None
    return None


def _compute_plan_diff(plan_a: dict, plan_b: dict) -> list[dict]:
    """Compute a simple diff between two plan dicts.

    Returns list of change dicts with key, action, old, new.
    """
    changes = []
    all_keys = set(plan_a.keys()) | set(plan_b.keys())

    for key in sorted(all_keys):
        if key == "metadata":
            continue  # Skip metadata (version changes are expected)

        val_a = plan_a.get(key)
        val_b = plan_b.get(key)

        if val_a is None and val_b is not None:
            changes.append({"key": key, "action": "added"})
        elif val_a is not None and val_b is None:
            changes.append({"key": key, "action": "removed"})
        elif val_a != val_b:
            changes.append({"key": key, "action": "modified"})

    return changes
