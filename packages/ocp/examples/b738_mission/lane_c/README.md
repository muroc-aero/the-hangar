# Lane C: Claude Code Agent Prompts

These markdown files are natural-language prompts designed for use with Claude
Code (CLI) or claude.ai connected to the OpenConcept MCP server. The agent reads
the prompt and calls the same MCP tools as Lane B.

## Quick Start

```bash
# From the workspace root (MCP server auto-discovered)
claude

# Then paste the contents of any prompt file, e.g.:
# reserve_mission.prompt.md
```

The agent calls the same MCP tools as Lane B, so its results match Lane B. They
approximate -- but do not exactly reproduce -- the upstream OpenConcept B738
example (Lane A): the MCP tools fly constant per-phase speeds and use default
reserve-phase speeds, whereas the upstream script ramps every phase. See
`../README.md` ("Where the lanes differ").
