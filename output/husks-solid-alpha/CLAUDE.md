# Project conventions — Husks

This project uses **Husks** for any task that produces artifacts: code
generation, scaffolding, content, multi-step builds. Do not run as an unbounded
agent loop. Use the `husks` skill — decompose the task into a `design.json` build
graph, then check, show, and run it.

## Workflow
- Write `design.json` first. No exploring or running commands before that.
- `check` then `show` the design. **Wait for approval before `run`.**
- Run `--stub` first when the shape is new; go live only after the stub commits.
- On `run`: the CLI prints a structured Report (status, root, fuel, cost, delta,
  per-node table, diagnosis). Use `--json` for machine-readable output.

## Two forms to start
- Use `action` (deterministic) and `oracle` (one bounded model call).
- The JSON IR also supports `let`, `cond`, and `trial`, but start with
  `action` + `oracle` until the simpler forms are routine.

## Recipes must be portable
The `.husk` is permanent and meant to verify and re-run anywhere. Action `run`
commands therefore must not bake in machine-specific state:
- **No absolute paths** (no `/home/<user>/...`). A leaked path lives in the seal forever.
- **Do not activate a venv inside `run`** (`source .../activate`). The build already
  runs in your environment; `source` is also non-portable under `/bin/sh`. Call
  tools directly: `python -m pytest -q > test-results.txt 2>&1`.

## Validation is a deterministic action, never an oracle
- Oracles produce; actions verify. Never let a model grade its own output.
- Gate on **exit code**, not fragile text matches. A nonzero `run` halts the build,
  so `python -m pytest ...` already fails the build on a test failure. Avoid
  `grep -q passed` style checks — they pass on "1 passed, 3 failed".

## Spec independence (correctness-critical builds)
Do not let the test oracle read the implementation it is testing — that verifies
self-consistency, not correctness. Declare the spec as its own artifact and give
the **same** spec to both the implementation oracle and the test oracle as input,
so the tests check the spec, not whatever the implementation happened to do.
