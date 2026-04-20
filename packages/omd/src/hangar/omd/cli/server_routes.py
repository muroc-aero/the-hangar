"""HTTP route handlers for the provenance viewer server and plan detail renderer.

Handlers are registered by viewer_cmd in __init__.py. Two of them
(`_omd_problem_dag_handler`, `_omd_plan_detail_handler`) are also imported by
external deploy scripts, so they stay importable from `hangar.omd.cli` via the
package __init__ re-exports.
"""

from __future__ import annotations


def _omd_provenance_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve the omd provenance DAG as HTML via the SDK viewer server."""
    from hangar.omd.provenance import provenance_dag_html
    from pathlib import Path

    plan_id = (qs.get("plan_id") or [None])[0]
    if not plan_id:
        # Return a simple index listing available plan IDs
        from hangar.omd.db import init_analysis_db, get_db_path
        init_analysis_db()
        import sqlite3
        db = sqlite3.connect(str(get_db_path()))
        rows = db.execute(
            "SELECT DISTINCT plan_id FROM entities WHERE plan_id IS NOT NULL"
        ).fetchall()
        db.close()
        plan_ids = sorted({r[0] for r in rows})
        links = "".join(
            f'<li><a href="/omd-provenance?plan_id={pid}">{pid}</a></li>'
            for pid in plan_ids
        )
        html = (
            "<!DOCTYPE html><html><head><title>omd provenance</title>"
            "<style>"
            "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;"
            "background:#0f1117;color:#e0e0e0;padding:24px;}"
            "h1{font-size:18px;font-weight:600;color:#8eb6ff;margin-bottom:16px;}"
            "ul{list-style:none;padding:0;}"
            "li{margin:6px 0;}"
            "a{color:#8eb6ff;text-decoration:none;font-size:14px;"
            "padding:6px 12px;display:inline-block;border-radius:5px;"
            "border:1px solid #2d3047;background:#1a1d27;}"
            "a:hover{background:#252839;border-color:#4a5070;}"
            "</style></head>"
            f"<body><h1>omd Provenance</h1><ul>{links}</ul></body></html>"
        )
        return 200, "text/html; charset=utf-8", html.encode()

    # Generate the DAG HTML to a temporary path, read it back
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        provenance_dag_html(plan_id, tmp_path)
        body = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    return 200, "text/html; charset=utf-8", body


def _omd_plan_diff_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Return JSON diff between a plan version and its predecessor."""
    import json as _json
    from hangar.omd.provenance import provenance_diff
    from hangar.omd.db import init_analysis_db, query_entity

    plan_id = (qs.get("plan_id") or [None])[0]
    version = (qs.get("version") or [None])[0]
    if not plan_id or not version:
        body = _json.dumps({"error": "Missing plan_id or version"})
        return 400, "application/json", body.encode()

    init_analysis_db()
    ver = int(version)
    if ver <= 1:
        # No prior version -- return the full plan content
        entity = query_entity(f"{plan_id}/v{ver}")
        if entity and entity.get("storage_ref"):
            from pathlib import Path
            import yaml
            plan_path = Path(entity["storage_ref"])
            if plan_path.exists():
                with open(plan_path) as f:
                    plan = yaml.safe_load(f)
                body = _json.dumps({"first_version": True, "plan": plan}, default=str)
                return 200, "application/json", body.encode()
        body = _json.dumps({"first_version": True, "plan": None})
        return 200, "application/json", body.encode()

    result = provenance_diff(plan_id, ver - 1, ver)
    body = _json.dumps(result, default=str)
    return 200, "application/json", body.encode()


def _omd_plots_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Generate plots for a run and return list of available filenames."""
    import json as _json
    from pathlib import Path
    from hangar.omd.db import init_analysis_db, omd_data_root, query_entity

    run_id = (qs.get("run_id") or [None])[0]
    if not run_id:
        return 400, "application/json", b'{"error":"Missing run_id"}'

    init_analysis_db()
    plots_dir = omd_data_root() / "plots" / run_id

    # Generate plots on demand if they don't exist
    if not plots_dir.exists() or not list(plots_dir.glob("*.png")):
        try:
            from hangar.omd.plotting import generate_plots
            rec_path = omd_data_root() / "recordings" / f"{run_id}.sql"
            if not rec_path.exists():
                return 404, "application/json", b'{"error":"Recording not found"}'

            # Get component type from run entity metadata
            entity = query_entity(run_id)
            component_type = None
            component_types = None
            if entity and entity.get("metadata"):
                import json
                meta = json.loads(entity["metadata"])
                component_type = meta.get("component_type")
                component_types = meta.get("component_types")

            generate_plots(
                recorder_path=rec_path,
                plot_types=None,
                surface_name="wing",
                output_dir=plots_dir,
                component_type=component_type,
                component_types=component_types,
            )
        except Exception as exc:
            body = _json.dumps({"error": str(exc)})
            return 500, "application/json", body.encode()

    # List available plot files
    files = sorted(p.name for p in plots_dir.glob("*.png"))
    body = _json.dumps({"run_id": run_id, "plots": files})
    return 200, "application/json", body.encode()


def _omd_plot_img_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve a specific plot PNG for a run."""
    from pathlib import Path
    from hangar.omd.db import omd_data_root

    run_id = (qs.get("run_id") or [None])[0]
    name = (qs.get("name") or [None])[0]
    if not run_id or not name:
        return 400, "application/json", b'{"error":"Missing run_id or name"}'

    # Sanitize name to prevent path traversal
    from pathlib import PurePosixPath
    if ".." in name or "/" in name or "\\" in name:
        return 400, "application/json", b'{"error":"Invalid name"}'

    img_path = omd_data_root() / "plots" / run_id / name
    if not img_path.exists():
        return 404, "application/json", b'{"error":"Plot not found"}'

    return 200, "image/png", img_path.read_bytes()


def _omd_n2_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve the N2 diagram HTML for a run."""
    from pathlib import Path
    from hangar.omd.db import omd_data_root

    run_id = (qs.get("run_id") or [None])[0]
    if not run_id:
        return 400, "application/json", b'{"error":"Missing run_id"}'

    n2_path = omd_data_root() / "n2" / f"{run_id}.html"
    if not n2_path.exists():
        return 404, "application/json", b'{"error":"N2 not found"}'

    return 200, "text/html; charset=utf-8", n2_path.read_bytes()


def _omd_problem_dag_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve a discipline-level analysis flow DAG."""
    import json as _json
    from hangar.omd.db import init_analysis_db, query_entity

    run_id = (qs.get("run_id") or [None])[0]
    if not run_id:
        return 400, "application/json", b'{"error":"Missing run_id"}'

    init_analysis_db()
    entity = query_entity(f"{run_id}/n2")
    if not entity or not entity.get("metadata"):
        return 404, "application/json", b'{"error":"Model structure not found"}'

    try:
        meta = _json.loads(entity["metadata"])
    except Exception:
        return 500, "application/json", b'{"error":"Invalid model data"}'

    # Use the discipline graph if available, otherwise fall back
    dgraph = meta.get("discipline_graph")
    if not dgraph:
        # Old data format -- rebuild from component type
        from hangar.omd.discipline_graph import build_discipline_graph
        ctype = meta.get("component_type", "")
        dgraph = build_discipline_graph(ctype)

    # Enrich discipline nodes with slot results and run summary
    slot_results = meta.get("slot_results", {})
    run_summary = meta.get("run_summary", {})
    _SLOT_TO_NODE = {
        "drag": "aero",
        "propulsion": "propulsion",
        "weight": "weight",
    }
    # Build available plots list by checking disk
    from hangar.omd.db import omd_data_root
    # pyCycle station/efficiency plots only valid for direct-coupled providers
    _prop_provider = slot_results.get("propulsion", {}).get("provider", "")
    _pyc_direct = _prop_provider in ("pyc/turbojet", "pyc/hbtf")
    _DISCIPLINE_PLOTS: dict[str, list] = {
        "aero": [("planform", "Planform"), ("lift", "Lift Distribution"),
                 ("twist", "Twist")],
        "struct": [("struct", "Deformation"), ("thickness", "Thickness"),
                   ("vonmises", "Von Mises")],
        "mission": [("mission_profile", "Mission Profile"),
                    ("weight_breakdown", "Weight Breakdown"),
                    ("performance_summary", "Performance Summary")],
        "geometry": [("planform", "Planform"), ("mesh_3d", "3D Mesh")],
        "perf": [("convergence", "Convergence")],
    }
    if _pyc_direct:
        _DISCIPLINE_PLOTS["propulsion"] = [
            ("station_properties", "Station Properties"),
            ("component_efficiency", "Component Efficiency"),
        ]
    existing_plots = set()
    pdir = omd_data_root() / "plots" / run_id
    if pdir.exists():
        existing_plots = {p.stem for p in pdir.glob("*.png")}

    for node in dgraph.get("nodes", []):
        props = node.get("properties", {})
        nid = node["id"]

        # Inject slot result values
        result_values = {}
        for slot_name, node_id in _SLOT_TO_NODE.items():
            if nid == node_id and slot_name in slot_results:
                sr = slot_results[slot_name]
                for k, v in sr.items():
                    if k == "provider":
                        continue
                    if isinstance(v, float):
                        result_values[k] = f"{v:.4g}"
                    else:
                        result_values[k] = str(v)

        # Mission node gets run summary values
        if nid == "mission" and run_summary:
            for k, v in run_summary.items():
                if isinstance(v, float):
                    result_values[k] = f"{v:.4g}"
                else:
                    result_values[k] = str(v)

        if result_values:
            props["result_values"] = result_values

        # Inject available plot links
        discipline_plots = _DISCIPLINE_PLOTS.get(nid, [])
        available_plots = [
            {"type": pt, "label": label}
            for pt, label in discipline_plots
            if pt in existing_plots
        ]
        if available_plots:
            props["available_plots"] = available_plots

        node["properties"] = props

    # Convert to Cytoscape elements
    cy_elements = []
    for node in dgraph.get("nodes", []):
        props_json = _json.dumps(node.get("properties", {}), default=str)
        cy_elements.append({"data": {
            "id": node["id"],
            "label": node["label"],
            "node_type": node["type"],
            "properties": props_json,
        }})

    for edge in dgraph.get("edges", []):
        props = edge.get("properties", {})
        variables = props.get("variables", [])
        label = ", ".join(variables[:3])
        if len(variables) > 3:
            label += f" +{len(variables) - 3}"
        cy_elements.append({"data": {
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge.get("relation", "provides"),
            "label": label,
            "variables": _json.dumps(variables),
        }})

    elements_json = _json.dumps(cy_elements)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Analysis Flow: {run_id}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }}
  #toolbar {{ display: flex; align-items: center; gap: 10px; padding: 8px 14px;
              background: #1a1d27; border-bottom: 1px solid #2d3047; }}
  #toolbar h1 {{ font-size: 15px; font-weight: 600; color: #8eb6ff; }}
  #toolbar .sub {{ font-size: 13px; color: #6080b0; margin-left: 4px; }}
  .btn {{ padding: 5px 12px; border-radius: 5px; border: 1px solid #3a3e54;
          background: #252839; color: #c0c8e8; cursor: pointer; font-size: 12px; }}
  .btn:hover {{ background: #2e3245; }}
  #main {{ display: flex; flex: 1; min-height: 0; }}
  #cy {{ flex: 1; }}
  #panel {{ width: 320px; background: #1a1d27; border-left: 1px solid #2d3047;
            overflow-y: auto; padding: 12px; font-size: 12px; line-height: 1.6; }}
  #panel h3 {{ font-size: 13px; color: #9cb8ff; margin: 8px 0 4px; }}
  #panel h3:first-child {{ margin-top: 0; }}
  .kv {{ margin-bottom: 3px; }}
  .kv .key {{ color: #888; font-size: 11px; }}
  .kv .val {{ color: #d0d8f0; word-break: break-word; }}
  .mono {{ font-family: monospace; font-size: 10px; color: #a0a8c0; }}
  .var-tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px;
              font-size: 10px; background: #1a2030; color: #6090b0; margin: 1px;
              font-family: monospace; }}
  .result {{ color: #50d8a0; font-family: monospace; font-weight: 600; }}
  .plot-btn {{ display: inline-block; padding: 3px 10px; border-radius: 4px;
               font-size: 11px; background: #0a2028; border: 1px solid #30a0b0;
               color: #60d0e0; margin: 2px; cursor: pointer; text-decoration: none; }}
  .plot-btn:hover {{ background: #0e2838; border-color: #50c0d0; }}
</style>
</head>
<body>
<div id="toolbar">
  <h1>Analysis Flow</h1>
  <span class="sub">{run_id}</span>
  <div style="flex:1"></div>
  <button class="btn" id="btn-fit">Fit</button>
</div>
<div id="main">
  <div id="cy"></div>
  <div id="panel">
    <p style="color:#666;font-size:12px">Click a node or edge to inspect it.</p>
  </div>
</div>
<script>
cytoscape.use(cytoscapeDagre);
var cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: {elements_json},
  style: [
    /* Discipline nodes by ID for specific coloring */
    {{ selector: 'node[node_type="discipline"]', style: {{
         'shape': 'round-rectangle', 'width': 170, 'height': 50,
         'background-color': '#0d1f3c', 'border-width': 2, 'border-color': '#4a9eff',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 11,
         'color': '#a0ccff', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '160px',
    }} }},
    {{ selector: 'node#geometry', style: {{ 'border-color': '#4a9eff', 'background-color': '#0d1f3c' }} }},
    {{ selector: 'node#aero', style: {{ 'border-color': '#40c0e0', 'background-color': '#0a1828' }} }},
    {{ selector: 'node#struct', style: {{ 'border-color': '#5080a0', 'background-color': '#0e1820' }} }},
    {{ selector: 'node#perf', style: {{ 'border-color': '#30c090', 'background-color': '#0a2018' }} }},
    /* Coupling loop node */
    {{ selector: 'node[node_type="coupling_loop"]', style: {{
         'shape': 'round-rectangle', 'width': 180, 'height': 56,
         'background-color': '#141020', 'border-width': 3, 'border-color': '#7060b0',
         'border-style': 'double',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 11,
         'color': '#b0a0d8', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '170px',
    }} }},
    {{ selector: 'node:selected', style: {{ 'border-width': 3, 'border-color': '#9ab0ff' }} }},
    /* Flow edges */
    {{ selector: 'edge[relation="provides"]', style: {{
         'width': 2.5, 'line-color': '#2a80a0', 'target-arrow-color': '#2a80a0',
         'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
         'label': 'data(label)', 'font-size': 8, 'color': '#4a7090',
         'text-rotation': 'autorotate', 'text-background-opacity': 0.7,
         'text-background-color': '#0f1117', 'text-background-padding': '2px',
    }} }},
    /* Coupling edges */
    {{ selector: 'edge[relation="couples"]', style: {{
         'width': 3, 'line-color': '#7060b0', 'target-arrow-color': '#7060b0',
         'target-arrow-shape': 'triangle',
         'source-arrow-shape': 'triangle', 'source-arrow-color': '#7060b0',
         'curve-style': 'bezier',
         'label': 'data(label)', 'font-size': 8, 'color': '#8070c0',
         'text-rotation': 'autorotate', 'text-background-opacity': 0.7,
         'text-background-color': '#0f1117', 'text-background-padding': '2px',
         'line-style': 'dashed', 'line-dash-pattern': [8, 4],
    }} }},
  ],
  layout: {{ name: 'dagre', rankDir: 'TB', nodeSep: 60, rankSep: 90 }},
}});
cy.fit(40);
document.getElementById('btn-fit').addEventListener('click', function() {{ cy.fit(40); }});

function escHtml(s) {{ return s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}
var runId = '{run_id}';

/* Node click: show discipline details */
cy.on('tap', 'node', function(evt) {{
  var d = evt.target.data();
  var panel = document.getElementById('panel');
  var html = '<h3>' + escHtml(d.label.split('\\n')[0]) + '</h3>';
  html += '<div class="kv"><span class="key">type </span><span class="val">' + escHtml(d.node_type) + '</span></div>';

  if (d.properties) {{
    try {{
      var props = JSON.parse(d.properties);
      if (props.description) html += '<div class="kv"><span class="val" style="color:#8898b8">' + escHtml(props.description) + '</span></div>';
      if (props.physics) html += '<div class="kv"><span class="key">physics </span><span class="val">' + escHtml(props.physics) + '</span></div>';
      if (props.method) html += '<div class="kv"><span class="key">method </span><span class="val">' + escHtml(props.method) + '</span></div>';
      if (props.fem_type) html += '<div class="kv"><span class="key">FEM type </span><span class="val">' + escHtml(props.fem_type) + '</span></div>';
      if (props.solver) html += '<div class="kv"><span class="key">solver </span><span class="val">' + escHtml(props.solver) + '</span></div>';
      if (props.iterations != null) html += '<div class="kv"><span class="key">iterations </span><span class="val">' + escHtml(props.iterations) + '</span></div>';
      if (props.convergence_status) html += '<div class="kv"><span class="key">status </span><span class="val">' + escHtml(props.convergence_status) + '</span></div>';

      /* Input/output variable lists */
      if (props.inputs && props.inputs.length) {{
        html += '<h3>Inputs</h3>';
        for (var i = 0; i < props.inputs.length; i++) html += '<span class="var-tag">' + escHtml(props.inputs[i]) + '</span>';
      }}
      if (props.outputs && props.outputs.length) {{
        html += '<h3>Outputs</h3>';
        for (var i = 0; i < props.outputs.length; i++) html += '<span class="var-tag">' + escHtml(props.outputs[i]) + '</span>';
      }}

      /* Flight conditions for aero */
      if (props.flight_conditions) {{
        html += '<h3>Flight Conditions</h3>';
        for (var k in props.flight_conditions) {{
          html += '<div class="kv"><span class="key">' + escHtml(k) + ' </span><span class="val">' + escHtml(props.flight_conditions[k]) + '</span></div>';
        }}
      }}

      /* Material properties for struct */
      for (var mk of ['E', 'G', 'yield_stress', 'mrho']) {{
        if (props[mk] != null) html += '<div class="kv"><span class="key">' + escHtml(mk) + ' </span><span class="val">' + escHtml(props[mk]) + '</span></div>';
      }}

      /* Surfaces */
      if (props.surfaces) {{
        html += '<div class="kv"><span class="key">surfaces </span><span class="val">' + escHtml(props.surfaces.join(', ')) + '</span></div>';
      }}

      /* Coupling exchanges */
      if (props.disciplines) {{
        html += '<div class="kv"><span class="key">coupled </span><span class="val">' + escHtml(props.disciplines.join(' + ')) + '</span></div>';
      }}

      /* Result values from slot extraction */
      if (props.result_values) {{
        html += '<h3>Results</h3>';
        for (var rk in props.result_values) {{
          html += '<div class="kv"><span class="key">' + escHtml(rk) + ' </span><span class="result">' + escHtml(props.result_values[rk]) + '</span></div>';
        }}
      }}

      /* Plot links */
      if (props.available_plots && props.available_plots.length) {{
        html += '<h3>Plots</h3>';
        for (var pi = 0; pi < props.available_plots.length; pi++) {{
          var pt = props.available_plots[pi];
          html += '<a class="plot-btn" href="/omd-plot-img?run_id=' + encodeURIComponent(runId) + '&name=' + encodeURIComponent(pt.type + '.png') + '" target="_blank">' + escHtml(pt.label) + '</a>';
        }}
      }}
    }} catch(e) {{}}
  }}

  panel.innerHTML = html;
}});

/* Edge click: show variables being transferred */
cy.on('tap', 'edge', function(evt) {{
  var d = evt.target.data();
  var panel = document.getElementById('panel');
  var html = '<h3>Data Transfer</h3>';
  html += '<div class="kv"><span class="key">from </span><span class="val">' + escHtml(d.source) + '</span></div>';
  html += '<div class="kv"><span class="key">to </span><span class="val">' + escHtml(d.target) + '</span></div>';
  html += '<div class="kv"><span class="key">relation </span><span class="val">' + escHtml(d.relation) + '</span></div>';
  if (d.variables) {{
    try {{
      var vars = JSON.parse(d.variables);
      html += '<h3>Variables</h3>';
      for (var i = 0; i < vars.length; i++) html += '<span class="var-tag">' + escHtml(vars[i]) + '</span>';
    }} catch(e) {{}}
  }}
  panel.innerHTML = html;
}});

cy.on('tap', function(evt) {{
  if (evt.target === cy) {{
    document.getElementById('panel').innerHTML = '<p style="color:#666;font-size:12px">Click a node or edge to inspect it.</p>';
  }}
}});
</script>
</body>
</html>"""
    return 200, "text/html; charset=utf-8", html.encode()


def _omd_plan_detail_handler(
    qs: dict[str, list[str]],
) -> tuple[int, str, bytes]:
    """Serve a plan detail page as a knowledge graph."""
    import json as _json
    import yaml
    from pathlib import Path
    from hangar.omd.db import init_analysis_db, query_entity, _get_conn
    from hangar.omd.plan_graph import build_plan_graph

    plan_id = (qs.get("plan_id") or [None])[0]
    version = (qs.get("version") or [None])[0]
    if not plan_id:
        return 400, "application/json", b'{"error":"Missing plan_id"}'

    init_analysis_db()
    conn = _get_conn()

    # Get all plan versions
    rows = conn.execute(
        "SELECT entity_id, version, content_hash, storage_ref, created_at "
        "FROM entities WHERE plan_id = ? AND entity_type = 'plan' "
        "ORDER BY version ASC",
        (plan_id,),
    ).fetchall()
    versions = [dict(r) for r in rows]

    if version:
        ver = int(version)
    elif versions:
        ver = versions[-1]["version"]
    else:
        return 404, "application/json", b'{"error":"Plan not found"}'

    entity = query_entity(f"{plan_id}/v{ver}")
    plan = None
    if entity and entity.get("storage_ref"):
        plan_path = Path(entity["storage_ref"])
        if plan_path.exists():
            with open(plan_path) as f:
                plan = yaml.safe_load(f)

    if not plan:
        return 404, "application/json", b'{"error":"Plan YAML not found"}'

    # Build knowledge graph via the modular builder
    graph = build_plan_graph(plan, plan_id, ver)

    # Convert to Cytoscape elements
    cy_elements = []
    for node in graph["nodes"]:
        props_json = _json.dumps(node["properties"], default=str)
        cy_elements.append({"data": {
            "id": node["id"],
            "label": node["label"],
            "node_type": node["type"],
            "properties": props_json,
        }})
    for edge in graph["edges"]:
        cy_elements.append({"data": {
            "source": edge["source"],
            "target": edge["target"],
            "relation": edge["relation"],
        }})

    elements_json = _json.dumps(cy_elements)

    # Version timeline
    ver_html = ""
    for v in versions:
        vnum = v["version"]
        active = " style='background:#2a4a7f;border-color:#4a6fa8;color:#fff'" if vnum == ver else ""
        ver_html += (
            f'<a href="/omd-plan-detail?plan_id={plan_id}&version={vnum}" '
            f'class="btn"{active}>v{vnum}</a> '
        )

    html = _render_plan_detail_html(plan_id, ver, elements_json, ver_html)
    return 200, "text/html; charset=utf-8", html.encode()


def _render_plan_detail_html(
    plan_id: str, ver: int, elements_json: str, ver_html: str,
) -> str:
    """Render the plan detail Cytoscape.js HTML page."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Plan: {plan_id} v{ver}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.28.1/cytoscape.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/dagre/0.8.5/dagre.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/cytoscape-dagre@2.5.0/cytoscape-dagre.min.js"></script>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         background: #0f1117; color: #e0e0e0; height: 100vh; display: flex; flex-direction: column; }}
  #toolbar {{ display: flex; align-items: center; gap: 10px; padding: 8px 14px;
              background: #1a1d27; border-bottom: 1px solid #2d3047; flex-wrap: wrap; }}
  #toolbar h1 {{ font-size: 15px; font-weight: 600; color: #8eb6ff; }}
  #toolbar .sub {{ font-size: 13px; color: #6080b0; margin-left: 4px; }}
  .btn {{ padding: 5px 12px; border-radius: 5px; border: 1px solid #3a3e54;
          background: #252839; color: #c0c8e8; cursor: pointer; font-size: 12px; text-decoration: none; }}
  .btn:hover {{ background: #2e3245; }}
  #versions {{ display: flex; gap: 4px; align-items: center; }}
  #versions .label {{ font-size: 11px; color: #888; }}
  #main {{ display: flex; flex: 1; min-height: 0; }}
  #cy {{ flex: 1; }}
  #panel {{ width: 320px; background: #1a1d27; border-left: 1px solid #2d3047;
            overflow-y: auto; padding: 12px; font-size: 12px; line-height: 1.6; }}
  #panel h3 {{ font-size: 13px; color: #9cb8ff; margin: 8px 0 4px; }}
  #panel h3:first-child {{ margin-top: 0; }}
  .kv {{ margin-bottom: 3px; }}
  .kv .key {{ color: #888; font-size: 11px; }}
  .kv .val {{ color: #d0d8f0; word-break: break-word; }}
  .mono {{ font-family: monospace; font-size: 10px; color: #a0a8c0; }}
  .edge-tag {{ display: inline-block; padding: 1px 6px; border-radius: 3px;
               font-size: 10px; background: #1a2030; color: #6090b0; margin: 1px; }}
</style>
</head>
<body>
<div id="toolbar">
  <h1>Plan Knowledge Graph</h1>
  <span class="sub">{plan_id} v{ver}</span>
  <div style="flex:1"></div>
  <div id="versions"><span class="label">Versions:</span> {ver_html}</div>
  <button class="btn" id="btn-fit">Fit</button>
</div>
<div id="main">
  <div id="cy"></div>
  <div id="panel">
    <p style="color:#666;font-size:12px">Click a node to inspect its properties.</p>
  </div>
</div>
<script>
cytoscape.use(cytoscapeDagre);
var cy = cytoscape({{
  container: document.getElementById('cy'),
  elements: {elements_json},
  style: [
    {{ selector: 'node[node_type="plan"]', style: {{
         'shape': 'round-rectangle', 'width': 160, 'height': 44,
         'background-color': '#0d1f3c', 'border-width': 2, 'border-color': '#4a9eff',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 11,
         'color': '#a0ccff', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="surface"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 36,
         'background-color': '#0a1828', 'border-width': 2, 'border-color': '#70b8ff',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#90ccff', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="material"]', style: {{
         'shape': 'round-rectangle', 'width': 110, 'height': 32,
         'background-color': '#1a1028', 'border-width': 2, 'border-color': '#a080c0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#c0a0e0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="fem_model"]', style: {{
         'shape': 'round-rectangle', 'width': 100, 'height': 28,
         'background-color': '#101820', 'border-width': 2, 'border-color': '#5080a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80a0c0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="mesh"]', style: {{
         'shape': 'round-rectangle', 'width': 100, 'height': 28,
         'background-color': '#0e1828', 'border-width': 2, 'border-color': '#6090b0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80b0d0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="flight_condition"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#0a1820', 'border-width': 2, 'border-color': '#50c0f0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80d8ff', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="solver"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#101820', 'border-width': 2, 'border-color': '#5080a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80a0c0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="linear_solver"]', style: {{
         'shape': 'round-rectangle', 'width': 100, 'height': 28,
         'background-color': '#101820', 'border-width': 2, 'border-color': '#406080',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#6090b0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="objective"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 32,
         'background-color': '#0a1820', 'border-width': 2, 'border-color': '#40d0e0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#70e0f0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="design_variable"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 32,
         'background-color': '#0a1828', 'border-width': 2, 'border-color': '#50a0f0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#80c0ff', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="constraint"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 32,
         'background-color': '#0a2018', 'border-width': 2, 'border-color': '#30c090',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#60e0b0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="decision"]', style: {{
         'shape': 'hexagon', 'width': 110, 'height': 55,
         'background-color': '#1a1808', 'border-width': 2, 'border-color': '#d0a030',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#e0c060', 'text-valign': 'center', 'text-halign': 'center',
         'text-max-width': '90px',
    }} }},
    {{ selector: 'node[node_type="requirement"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 32,
         'background-color': '#1a0a20', 'border-width': 2, 'border-color': '#a060c0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#c080e0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="aircraft_config"]', style: {{
         'shape': 'round-rectangle', 'width': 140, 'height': 40,
         'background-color': '#0a1a1a', 'border-width': 2, 'border-color': '#40b0a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#70d8c8', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="mission_profile"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#0a1820', 'border-width': 2, 'border-color': '#40b8d0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#70d0e8', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="propulsion_architecture"]', style: {{
         'shape': 'round-rectangle', 'width': 120, 'height': 32,
         'background-color': '#1a1408', 'border-width': 2, 'border-color': '#c08830',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#e0a850', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="slot_provider"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#14081a', 'border-width': 2, 'border-color': '#9060c0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#b080e0', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="engine_config"]', style: {{
         'shape': 'round-rectangle', 'width': 150, 'height': 44,
         'background-color': '#1a1008', 'border-width': 2, 'border-color': '#d09030',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 10,
         'color': '#e8b050', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="engine_element"]', style: {{
         'shape': 'round-rectangle', 'width': 110, 'height': 30,
         'background-color': '#1a1408', 'border-width': 2, 'border-color': '#b8a040',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#d8c060', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node[node_type="surrogate_deck"]', style: {{
         'shape': 'round-rectangle', 'width': 130, 'height': 36,
         'background-color': '#081a1a', 'border-width': 2, 'border-color': '#3090a0',
         'label': 'data(label)', 'text-wrap': 'wrap', 'font-size': 9,
         'color': '#60b8c8', 'text-valign': 'center', 'text-halign': 'center',
    }} }},
    {{ selector: 'node:selected', style: {{ 'border-width': 3, 'border-color': '#9ab0ff' }} }},
    /* Edge styles by relation type */
    {{ selector: 'edge', style: {{
         'width': 2, 'line-color': '#2a3a5a', 'target-arrow-color': '#2a3a5a',
         'target-arrow-shape': 'triangle', 'curve-style': 'bezier',
         'label': 'data(relation)', 'font-size': 8, 'color': '#3a5070',
         'text-rotation': 'autorotate',
    }} }},
    {{ selector: 'edge[relation="has_geometry"], edge[relation="has_material"], edge[relation="has_fem"]',
       style: {{ 'line-color': '#3a5a7a', 'target-arrow-color': '#3a5a7a' }} }},
    {{ selector: 'edge[relation="acts_on"]',
       style: {{ 'width': 3, 'line-color': '#50a0f0', 'target-arrow-color': '#50a0f0' }} }},
    {{ selector: 'edge[relation="bounds"]',
       style: {{ 'line-color': '#30c090', 'target-arrow-color': '#30c090' }} }},
    {{ selector: 'edge[relation="justifies"]',
       style: {{ 'line-style': 'dashed', 'line-color': '#d0a030', 'target-arrow-color': '#d0a030' }} }},
    {{ selector: 'edge[relation="traces_to"]',
       style: {{ 'line-style': 'dotted', 'line-color': '#a060c0', 'target-arrow-color': '#a060c0' }} }},
    {{ selector: 'edge[relation="flow_to"]',
       style: {{ 'width': 3, 'line-color': '#c09030', 'target-arrow-color': '#c09030' }} }},
    {{ selector: 'edge[relation="has_architecture"]',
       style: {{ 'line-color': '#c08830', 'target-arrow-color': '#c08830' }} }},
    {{ selector: 'edge[relation="provides"]',
       style: {{ 'line-color': '#9060c0', 'target-arrow-color': '#9060c0' }} }},
    {{ selector: 'edge[relation="couples"]',
       style: {{ 'line-style': 'dashed', 'line-color': '#b8a040', 'target-arrow-color': '#b8a040' }} }},
    {{ selector: 'edge[relation="configures"]',
       style: {{ 'line-style': 'dotted', 'line-color': '#40b0a0', 'target-arrow-color': '#40b0a0' }} }},
    {{ selector: 'edge[relation="generates"]',
       style: {{ 'line-color': '#3090a0', 'target-arrow-color': '#3090a0' }} }},
  ],
  layout: {{ name: 'dagre', rankDir: 'TB', nodeSep: 40, rankSep: 70, edgeSep: 10 }},
}});
cy.fit(30);
document.getElementById('btn-fit').addEventListener('click', function() {{ cy.fit(30); }});

function escHtml(s) {{ return s == null ? '' : String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }}

cy.on('tap', 'node', function(evt) {{
  var d = evt.target.data();
  var panel = document.getElementById('panel');
  var html = '<h3>' + escHtml(d.node_type) + '</h3>';
  html += '<div class="kv"><span class="key">id </span><span class="val mono">' + escHtml(d.id) + '</span></div>';

  /* Render all properties from the graph data */
  if (d.properties) {{
    try {{
      var props = JSON.parse(d.properties);
      for (var key in props) {{
        var val = props[key];
        if (val == null) continue;
        var display = (typeof val === 'object') ? JSON.stringify(val) : String(val);
        html += '<div class="kv"><span class="key">' + escHtml(key) + ' </span><span class="val">' + escHtml(display) + '</span></div>';
      }}
    }} catch(e) {{}}
  }}

  /* Show connected edges with relation types */
  var conns = evt.target.connectedEdges();
  if (conns.length > 0) {{
    html += '<h3>Relationships</h3>';
    conns.forEach(function(e) {{
      var ed = e.data();
      var direction = ed.source === d.id ? 'out' : 'in';
      var other = direction === 'out' ? ed.target : ed.source;
      var arrow = direction === 'out' ? '&rarr;' : '&larr;';
      html += '<div class="kv"><span class="edge-tag">' + escHtml(ed.relation) + '</span> ' + arrow + ' <span class="val mono">' + escHtml(other) + '</span></div>';
    }});
  }}

  panel.innerHTML = html;
}});

cy.on('tap', function(evt) {{
  if (evt.target === cy) {{
    document.getElementById('panel').innerHTML = '<p style="color:#666;font-size:12px">Click a node to inspect its properties.</p>';
  }}
}});
</script>
</body>
</html>"""


