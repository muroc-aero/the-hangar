# Lane C: Claude Code Agent Prompts

These markdown files are natural-language prompts designed for use with Claude
Code (CLI) or claude.ai connected to the OpenConcept MCP server. The agent reads
the prompt and calls the same MCP tools as Lane B.

## Quick Start

```bash
# From the workspace root (MCP server auto-discovered)
claude

# Then paste the contents of any prompt file, e.g.:
# basic_mission.prompt.md
# full_mission.prompt.md
# hybrid_mission.prompt.md
# all_analyses.prompt.md   (runs all three in sequence)
```

Results should match Lane A and Lane B within floating-point tolerance.
