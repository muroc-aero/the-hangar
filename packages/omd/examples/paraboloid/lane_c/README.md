# Lane C: Agent Task Prompts

These markdown files are analysis task descriptions for an AI agent.
The agent receives the task, uses `/omd-cli-guide` (or `omd-cli --help`)
to learn how to author plan YAML files, creates the plan, runs it, and
reports results.

The prompts describe *what* to do, not *how*. The agent figures out the
plan structure, component types, and CLI commands from the skills and
documentation.

## Prompts

- `analysis.prompt.md` -- evaluate the paraboloid at a point
- `optimization.prompt.md` -- find the minimum
- `all.prompt.md` -- both tasks in sequence

## Usage

```bash
claude
# Then paste the contents of any prompt file
```

Results should match Lane A and Lane B.
