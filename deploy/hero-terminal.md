# Refreshing the hero terminal

The hero terminal on the landing page (`deploy/landing/index.html`, the `.terminal-body` div inside `.terminal`) is hand-formatted HTML with semantic color spans. This guide walks through capturing real output and wrapping it in the span markup.

## The basic shape

The terminal is rendered with `white-space: pre`, so indentation and blank lines are preserved. Each line is typically:

- A shell prompt line: `<span class="prompt">$</span> <span class="cmd">...</span>`
- A comment line: `<span class="comment"># ...</span>`
- A plain output line (uses the default `.terminal-body` color)
- A key-value summary line with `<span class="key">name     </span>: value`

Text coloring is driven by classes applied to inline spans:

| Class | Color | Use for |
|---|---|---|
| `prompt` | amber | the `$` (or `>` inside an agent prompt) |
| `cmd` | foreground | the command text after the prompt |
| `comment` | fg3 (dim) | `#` comments and the agent's in-turn status lines |
| `ok` | green | `[ok]` or `yes` success markers |
| `err` | red | `[error]` or failure markers |
| `key` | accent2 (bright amber) | the left side of a key-value row |
| `str` | foreground (bright) | string values inside key-value rows |

Everything else uses the default terminal body color (`fg2`, a muted warm grey).

## Step 1: capture a real session

Run the session you want to show end-to-end. Keep it short -- under 20 lines fits the hero without scrolling on a 1440px laptop.

Recommended shapes:

```bash
# (a) connect + run
claude mcp add --transport http oas https://mcp.lakesideai.dev/oas/mcp
claude
# (agent prompt and tool use)

# (b) direct CLI
oas-cli compute-drag-polar --alpha-min -2 --alpha-max 10 --count 7
oas-cli visualize --run-id <id> --plot-type polar

# (c) omd plan
omd-cli run plan.yaml --mode optimize
omd-cli results <run_id> --summary
```

Copy the terminal output into a scratch file (`session.txt`). Strip anything client-specific: session IDs inside claude, long OAuth tokens, absolute home paths. Keep real numbers -- you can get them from `omd-cli results <run_id> --summary` or from `hangar_data/omd/analysis.db`.

Keep the prompt character consistent. The current hero uses `$` for shell and no prompt for in-claude content (claude lines are styled as comments). If you want an agent prompt visible, prefix those lines with `>`.

## Step 2: paste into the terminal body

Open `deploy/landing/index.html` and find:

```html
<div class="terminal-body">...</div>
```

Replace its contents with your captured text. Preserve all whitespace; the CSS uses `white-space: pre`, so every space and newline renders literally. Align colons in key-value rows by padding the left side with spaces -- the mono font guarantees the columns line up.

## Step 3: wrap with span classes

Go line by line. Typical transformations:

Raw:
```
$ oas-cli compute-drag-polar --alpha-min -2 --alpha-max 10 --count 7
[ok] converged 7/7 points
CL_max: 1.24   CD_min: 0.0087   K: 0.042
```

Wrapped:
```html
<span class="prompt">$</span> <span class="cmd">oas-cli compute-drag-polar --alpha-min -2 --alpha-max 10 --count 7</span>
<span class="ok">[ok]</span> converged 7/7 points
<span class="key">CL_max </span>: 1.24   <span class="key">CD_min </span>: 0.0087   <span class="key">K      </span>: 0.042
```

Raw agent session:
```
$ claude
# minimize CD at CL=0.5 on a 28m-span wing

-> create_surface(name="wing", span=28.0, ...)
-> run_optimization(dvs=[twist_cp, thickness_cp, alpha])

run_id     : run-20260414T145425-65b0174e
converged  : yes  (28 iters, SLSQP)
```

Wrapped:
```html
<span class="prompt">$</span> <span class="cmd">claude</span>
<span class="comment"># minimize CD at CL=0.5 on a 28m-span wing</span>

<span class="comment">-> create_surface(name="wing", span=28.0, ...)</span>
<span class="comment">-> run_optimization(dvs=[twist_cp, thickness_cp, alpha])</span>

<span class="key">run_id     </span>: <span class="str">run-20260414T145425-65b0174e</span>
<span class="key">converged  </span>: <span class="ok">yes</span>  <span class="comment">(28 iters, SLSQP)</span>
```

## Step 4: sanity check locally

```bash
cd deploy/landing
python3 -m http.server 8765 --bind 127.0.0.1
# open http://127.0.0.1:8765/
```

Health dots will show offline (expected -- no Caddy locally). Everything else renders against the real CSS.

## Rules of thumb

- Keep the total under 20 lines. The hero collapses below ~860px so very wide blocks are also fine on mobile (they scroll horizontally).
- Put real numbers in. Nothing rots like fabricated output.
- Don't put unicode glyphs inside `white-space: pre` unless you render with a font that has them (IBM Plex Mono covers box drawing, but watch for BiDi or private-use chars).
- The header path (`~/projects/e190-wing`) is cosmetic. Pick something that suggests the user is doing real engineering work.
- Comments (`#` lines and `->` tool-use lines) can be grouped -- the agent's tool use reads naturally as a single commented block.

## Optional: scripting the wrap

If you refresh the hero frequently, a small wrapper script can do the obvious cases. Save as `deploy/scripts/wrap-hero-terminal.py`:

```python
#!/usr/bin/env python3
"""Wrap plain terminal output (stdin) with the hero-terminal span classes (stdout)."""
import sys

for line in sys.stdin:
    l = line.rstrip("\n")
    if l.startswith("$ "):
        print(f'<span class="prompt">$</span> <span class="cmd">{l[2:]}</span>')
    elif l.startswith("# ") or l.startswith("-> "):
        print(f'<span class="comment">{l}</span>')
    elif l.startswith("[ok]"):
        print(f'<span class="ok">[ok]</span>{l[4:]}')
    elif l.startswith("[error]") or l.startswith("[err]"):
        tok = l.split()[0]
        print(f'<span class="err">{tok}</span>{l[len(tok):]}')
    elif ":" in l and not l.lstrip().startswith("http"):
        k, _, v = l.partition(":")
        print(f'<span class="key">{k}</span>:<span class="str">{v}</span>')
    else:
        print(l)
```

```bash
cat session.txt | python3 deploy/scripts/wrap-hero-terminal.py > fragment.html
```

Paste `fragment.html` into the `.terminal-body`. Touch up any lines the heuristic mis-wrapped.
