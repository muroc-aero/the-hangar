# Assembled plan snapshots

Tracked snapshots of `omd assemble` output, used as inputs by
`test_graphs.py`. They live here, outside the plan-package directories,
because `packages/omd/.gitignore` ignores every `**/history/` directory:
the per-fixture `history/` dirs accumulate locally on every assemble run
and are never committed, so tests must not reference them.

To refresh one: run `omd-cli assemble` on the fixture's plan package,
copy the new `history/vN.yaml` here under the `<fixture>_vN.yaml` naming
convention, and update the path in `test_graphs.py`.
