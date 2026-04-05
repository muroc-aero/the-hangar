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
        eid = entity["entity_id"]
        # Build a compact label: show the short id or version info
        if etype == "plan":
            version = entity.get("version")
            label = f"v{version}" if version else eid.split("/")[-1]
        elif etype == "run_record":
            # Show just the timestamp portion of the run id
            label = eid.replace("run-", "")[:15]
        else:
            label = etype
        nodes.append({
            "data": {
                "id": eid,
                "label": label,
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
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>omd Provenance: {plan_id}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f1117; color: #e0e0e0;
    height: 100vh; display: flex; flex-direction: column; overflow: hidden;
  }}

  #toolbar {{
    display: flex; align-items: center; gap: 10px;
    padding: 8px 14px; background: #1a1d27;
    border-bottom: 1px solid #2d3047; flex-shrink: 0;
  }}
  #toolbar h1 {{ font-size: 15px; font-weight: 600; color: #8eb6ff; }}
  #toolbar .plan-id {{ font-size: 13px; color: #6080b0; margin-left: 4px; }}
  .btn {{
    padding: 5px 12px; border-radius: 5px; border: 1px solid #3a3e54;
    background: #252839; color: #c0c8e8; cursor: pointer; font-size: 12px;
  }}
  .btn:hover {{ background: #2e3245; }}

  #legend {{
    display: flex; gap: 14px; font-size: 11px; color: #888; align-items: center;
  }}
  .legend-item {{ display: flex; align-items: center; gap: 4px; }}
  .legend-dot {{
    width: 10px; height: 10px; border-radius: 2px; display: inline-block;
  }}

  #main {{ display: flex; flex: 1; min-height: 0; }}

  #cy-container {{ flex: 1; position: relative; min-width: 0; }}
  #cy {{ width: 100%; height: 100%; }}

  #panel {{
    width: 320px; background: #1a1d27; border-left: 1px solid #2d3047;
    display: flex; flex-direction: column; overflow: hidden; flex-shrink: 0;
  }}
  #panel-header {{
    padding: 10px 14px; font-size: 12px; font-weight: 600; color: #8eb6ff;
    border-bottom: 1px solid #2d3047; background: #1e2130;
  }}
  #panel-body {{
    flex: 1; overflow-y: auto; padding: 12px 14px; font-size: 12px; line-height: 1.6;
  }}
  #panel-body h3 {{ font-size: 13px; color: #9cb8ff; margin: 10px 0 6px 0; }}
  #panel-body h3:first-child {{ margin-top: 0; }}
  .kv {{ margin-bottom: 4px; }}
  .kv .key {{ color: #888; font-size: 11px; }}
  .kv .val {{ color: #d0d8f0; word-break: break-word; }}
  .badge {{
    display: inline-block; padding: 2px 7px; border-radius: 10px;
    font-size: 10px; font-weight: 600; text-transform: uppercase;
  }}
  .badge-plan       {{ background: #1a2a4a; color: #8eb6ff; }}
  .badge-run        {{ background: #102a3a; color: #5ac8fa; }}
  .badge-assessment {{ background: #1a3a2a; color: #4cdf88; }}
  .badge-activity   {{ background: #1a2030; color: #7aa0d0; }}
  .badge-completed  {{ background: #1a3a2a; color: #4cdf88; }}
  .badge-failed     {{ background: #4a1a1a; color: #ff6b6b; }}
  .mono {{ font-family: monospace; font-size: 10px; color: #a0a8c0; }}

  #empty-state {{
    position: absolute; inset: 0; display: flex; flex-direction: column;
    align-items: center; justify-content: center; color: #555; pointer-events: none;
  }}
  #empty-state p {{ font-size: 14px; }}
</style>
</head>
<body>

<div id="toolbar">
  <h1>omd Provenance</h1>
  <span class="plan-id">{plan_id}</span>
  <div style="flex:1"></div>
  <div id="legend">
    <span class="legend-item"><span class="legend-dot" style="background:#4a9eff"></span> Plan</span>
    <span class="legend-item"><span class="legend-dot" style="background:#3ac8fa"></span> Run</span>
    <span class="legend-item"><span class="legend-dot" style="background:#5a8abf"></span> Activity</span>
    <span class="legend-item"><span class="legend-dot" style="background:#2ad0a0"></span> Assessment</span>
  </div>
  <button class="btn" id="btn-fit">Fit</button>
</div>

<div id="main">
  <div id="cy-container">
    <div id="cy"></div>
  </div>
  <div id="panel">
    <div id="panel-header">Node Details</div>
    <div id="panel-body"><p style="color:#666;font-size:12px">Click a node to inspect it.</p></div>
  </div>
</div>

<script>
cytoscape.use(cytoscapeDagre);

var cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: {elements_json},
  style: [
    /* Plan entities: bright electric blue */
    {{ selector: 'node[entity_type="plan"]',
       style: {{
         'shape': 'round-rectangle', 'width': 140, 'height': 40,
         'background-color': '#0d1f3c', 'border-width': 2, 'border-color': '#4a9eff',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#a0ccff', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '130px',
       }} }},
    /* Run record entities: cyan-blue */
    {{ selector: 'node[entity_type="run_record"]',
       style: {{
         'shape': 'round-rectangle', 'width': 140, 'height': 40,
         'background-color': '#0a1e2e', 'border-width': 2, 'border-color': '#3ac8fa',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#80d8ff', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '130px',
       }} }},
    /* Assessment: teal-green */
    {{ selector: 'node[entity_type="assessment"]',
       style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 36,
         'background-color': '#0a2a20', 'border-width': 2, 'border-color': '#2ad0a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#70e8c0', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '110px',
       }} }},
    /* Validation report: slate blue */
    {{ selector: 'node[entity_type="validation_report"]',
       style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 36,
         'background-color': '#141a2e', 'border-width': 2, 'border-color': '#6080c0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#90a8d0', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '110px',
       }} }},
    /* Fallback entity */
    {{ selector: 'node[type="entity"]',
       style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 36,
         'background-color': '#111828', 'border-width': 1, 'border-color': '#3a4a6a',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#8898b8', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '110px',
       }} }},
    /* Activities: steel blue diamonds */
    {{ selector: 'node[type="activity"]',
       style: {{
         'shape': 'diamond', 'width': 110, 'height': 60,
         'background-color': '#0e1a2e', 'border-width': 2, 'border-color': '#5a8abf',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#90b0d8', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '90px',
       }} }},
    /* Failed activities: red border */
    {{ selector: 'node[status="failed"]',
       style: {{ 'border-width': 3, 'border-color': '#ff4a4a', 'background-color': '#2a0a0a' }} }},
    /* Selected node highlight */
    {{ selector: 'node:selected',
       style: {{ 'border-width': 3, 'border-color': '#9ab0ff' }} }},
    /* Edges: default */
    {{ selector: 'edge',
       style: {{
         'width': 2, 'line-color': '#2a3a5a', 'target-arrow-color': '#2a3a5a',
         'target-arrow-shape': 'triangle', 'curve-style': 'taxi',
         'arrow-scale': 1.2, 'label': 'data(label)',
         'font-size': 9, 'color': '#4a6080', 'text-rotation': 'autorotate',
       }} }},
    /* wasGeneratedBy: bright blue */
    {{ selector: 'edge[relation="wasGeneratedBy"]',
       style: {{ 'line-color': '#3080d0', 'target-arrow-color': '#3080d0' }} }},
    /* used: teal */
    {{ selector: 'edge[relation="used"]',
       style: {{ 'line-color': '#2a90a0', 'target-arrow-color': '#2a90a0' }} }},
    /* wasDerivedFrom: dashed light blue */
    {{ selector: 'edge[relation="wasDerivedFrom"]',
       style: {{
         'line-style': 'dashed', 'line-dash-pattern': [6, 3],
         'line-color': '#5a80c0', 'target-arrow-color': '#5a80c0', 'width': 2.5,
       }} }},
  ],
  layout: {{ name: 'dagre', rankDir: 'TB', nodeSep: 40, rankSep: 80, edgeSep: 10 }},
}});

cy.fit(30);

/* Fit button */
document.getElementById('btn-fit').addEventListener('click', function() {{ cy.fit(30); }});

/* Click handler: show details in side panel */
function escHtml(s) {{
  if (s == null) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}}

cy.on('tap', 'node', function(evt) {{
  var d = evt.target.data();
  var body = document.getElementById('panel-body');
  var html = '';

  if (d.type === 'entity') {{
    var etype = d.entity_type || 'entity';
    var badgeClass = etype === 'plan' ? 'badge-plan'
                   : etype === 'run_record' ? 'badge-run'
                   : etype === 'assessment' ? 'badge-assessment'
                   : 'badge-activity';
    html += '<h3>' + escHtml(etype) + ' <span class="badge ' + badgeClass + '">' + escHtml(etype) + '</span></h3>';
    html += '<div class="kv"><span class="key">id </span><span class="val mono">' + escHtml(d.id) + '</span></div>';
    if (d.created_at)   html += '<div class="kv"><span class="key">created_at </span><span class="val">' + escHtml(d.created_at) + '</span></div>';
    if (d.created_by)   html += '<div class="kv"><span class="key">created_by </span><span class="val">' + escHtml(d.created_by) + '</span></div>';
    if (d.version)      html += '<div class="kv"><span class="key">version </span><span class="val">' + escHtml(d.version) + '</span></div>';
    if (d.content_hash) html += '<div class="kv"><span class="key">content_hash </span><span class="val mono">' + escHtml(d.content_hash) + '</span></div>';
    if (d.storage_ref)  html += '<div class="kv"><span class="key">storage_ref </span><span class="val mono">' + escHtml(d.storage_ref) + '</span></div>';
  }} else {{
    var status = d.status || 'unknown';
    var statusClass = status === 'completed' ? 'badge-completed' : status === 'failed' ? 'badge-failed' : 'badge-activity';
    html += '<h3>' + escHtml((d.activity_type || 'activity').toUpperCase()) + ' <span class="badge ' + statusClass + '">' + escHtml(status) + '</span></h3>';
    html += '<div class="kv"><span class="key">id </span><span class="val mono">' + escHtml(d.id) + '</span></div>';
    if (d.agent)        html += '<div class="kv"><span class="key">agent </span><span class="val">' + escHtml(d.agent) + '</span></div>';
    if (d.started_at)   html += '<div class="kv"><span class="key">started_at </span><span class="val">' + escHtml(d.started_at) + '</span></div>';
    if (d.completed_at) html += '<div class="kv"><span class="key">completed_at </span><span class="val">' + escHtml(d.completed_at) + '</span></div>';
  }}

  /* Show connected edges */
  var conns = evt.target.connectedEdges();
  if (conns.length > 0) {{
    html += '<h3>Edges</h3>';
    conns.forEach(function(e) {{
      var ed = e.data();
      var direction = ed.source === d.id ? 'out' : 'in';
      var other = direction === 'out' ? ed.target : ed.source;
      var arrow = direction === 'out' ? '&rarr;' : '&larr;';
      html += '<div class="kv"><span class="key">' + escHtml(ed.relation) + ' ' + arrow + ' </span><span class="val mono">' + escHtml(other) + '</span></div>';
    }});
  }}

  body.innerHTML = html;
}});

cy.on('tap', function(evt) {{
  if (evt.target === cy) {{
    document.getElementById('panel-body').innerHTML = '<p style="color:#666;font-size:12px">Click a node to inspect it.</p>';
  }}
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
