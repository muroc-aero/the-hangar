#!/usr/bin/env python3
"""Patch a provenance DAG HTML for static serving.

Rewrites JavaScript in the generated DAG HTML so that:
- Plot buttons load images from a relative `plots/` directory instead of
  fetching from /omd-plots and /omd-plot-img API endpoints.
- N2 links point to a sibling `n2.html` instead of /omd-n2?run_id=X.
- Problem DAG links point to `problem-dag.html` instead of /omd-problem-dag.
- Plan detail links point to `plan-detail.html` instead of /omd-plan-detail.
- Plan diff fetch is replaced with inline "Initial plan creation" (v1 only).

Usage:
    python3 deploy/scripts/patch-dag-static.py INPUT.html OUTPUT.html
"""

import re
import sys


def patch(html: str) -> str:
    # 1. Replace plan detail links:
    #    href="/omd-plan-detail?plan_id=..." -> href="plan-detail.html"
    html = re.sub(
        r"""href="/omd-plan-detail\?plan_id='[^"]*""",
        'href="plan-detail.html',
        html,
    )
    # Handle the JS-concatenated version:
    #   '<a class="n2-btn" href="/omd-plan-detail?plan_id=' + encodeURIComponent(planId) + '&version=' + ver + '" target="_blank">Open Plan Detail</a>'
    html = re.sub(
        r"""'<a class="n2-btn" href="/omd-plan-detail\?plan_id=' \+ encodeURIComponent\(planId\) \+ '&version=' \+ ver \+ '"([^>]*)>Open Plan Detail</a>'""",
        r"""'<a class="n2-btn" href="plan-detail.html"\1>Open Plan Detail</a>'""",
        html,
    )

    # 2. Replace problem DAG links (various quoting patterns):
    html = re.sub(
        r"""href="/omd-problem-dag\?run_id=' \+ encodeURIComponent\(d\.id\) \+ '""",
        'href="problem-dag.html',
        html,
    )

    # 3. Replace N2 links:
    #   '<a class="n2-btn" href="/omd-n2?run_id=' + encodeURIComponent(d.id) + '" target="_blank">Full N2</a>'
    html = re.sub(
        r"""'<a class="n2-btn" href="/omd-n2\?run_id=' \+ encodeURIComponent\(d\.id\) \+ '"([^>]*)>Full N2</a>'""",
        r"""'<a class="n2-btn" href="n2.html"\1>Full N2</a>'""",
        html,
    )
    # Also the model_structure version:
    #   '<a class="n2-btn" href="/omd-n2?run_id=' + encodeURIComponent(rid) + '" target="_blank">Open N2 Diagram</a>'
    html = re.sub(
        r"""'<a class="n2-btn" href="/omd-n2\?run_id=' \+ encodeURIComponent\(rid\) \+ '"([^>]*)>Open N2 Diagram</a>'""",
        r"""'<a class="n2-btn" href="n2.html"\1>Open N2 Diagram</a>'""",
        html,
    )

    # 4. Replace the plan diff fetch with inline first-version response.
    # Original:
    #   fetch('/omd-plan-diff?plan_id=' + ...).then(function(r) { return r.json(); }).then(function(data) { ... })
    # Replace with immediate resolution using the same data format.
    old_diff = (
        "fetch('/omd-plan-diff?plan_id=' + encodeURIComponent(planId) + '&version=' + ver)\n"
        "        .then(function(r) { return r.json(); })\n"
        "        .then(function(data) {"
    )
    new_diff = (
        "Promise.resolve({first_version: true})\n"
        "        .then(function(data) {"
    )
    html = html.replace(old_diff, new_diff)

    # 5. Replace the plot button click handler to load from relative paths.
    # Original fetches /omd-plots then loads /omd-plot-img.
    # New: directly set img src to plots/{plotName}.
    old_plot_handler = """  /* First ensure plots are generated */
  fetch('/omd-plots?run_id=' + encodeURIComponent(runId))
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) {
        display.innerHTML = '<span class="plot-error">' + escHtml(data.error) + '</span>';
        return;
      }
      if (data.plots && data.plots.indexOf(plotName) >= 0) {
        display.innerHTML = '<img src="/omd-plot-img?run_id=' + encodeURIComponent(runId) +
                           '&name=' + encodeURIComponent(plotName) + '" alt="' + escHtml(plotName) + '">';
      } else {
        display.innerHTML = '<span class="plot-error">Plot not available for this run</span>';
      }
    })
    .catch(function(err) {
      display.innerHTML = '<span class="plot-error">Failed: ' + escHtml(err.message) + '</span>';
    });"""

    new_plot_handler = """  /* Static mode: load plot directly from relative path */
  var img = new Image();
  img.onload = function() {
    display.innerHTML = '';
    display.appendChild(img);
  };
  img.onerror = function() {
    display.innerHTML = '<span class="plot-error">Plot not available</span>';
  };
  img.alt = plotName;
  img.style.cssText = 'width:100%;border-radius:4px;margin-top:6px';
  img.src = 'plots/' + plotName;"""

    html = html.replace(old_plot_handler, new_plot_handler)

    return html


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} INPUT.html OUTPUT.html", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2]

    with open(input_path) as f:
        html = f.read()

    patched = patch(html)

    with open(output_path, "w") as f:
        f.write(patched)

    # Report what was patched
    changes = 0
    for label, old_str in [
        ("plan-detail links", "/omd-plan-detail"),
        ("problem-dag links", "/omd-problem-dag"),
        ("n2 links", "/omd-n2"),
        ("plan-diff fetch", "/omd-plan-diff"),
        ("plot-img fetch", "/omd-plot-img"),
    ]:
        old_count = html.count(old_str)
        new_count = patched.count(old_str)
        if old_count != new_count:
            print(f"  Patched {old_count - new_count} {label}")
            changes += old_count - new_count

    remaining = patched.count("/omd-")
    if remaining > 0:
        print(f"  WARNING: {remaining} unpatched /omd- references remain")
    else:
        print(f"  All /omd- references patched ({changes} total)")


if __name__ == "__main__":
    main()
