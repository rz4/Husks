---
name: husks
description: Decompose a task into a Husks design — a sealed, verifiable build graph with two forms to start.
allowed-tools: Bash(python -m husks.cli *) Bash(python -c *) Bash(./husks *) Bash(cd *) Bash(source *) Read Write
---

You are working with **Husks**, a fuel-bounded build calculus that produces **permanent, verifiable artifacts**. Do not execute tasks as an unbounded agent loop. Decompose the task into a **design**: a machine-checkable build graph with declared inputs, outputs, recipes, and fuel bounds.

**The design is a Husk.** The build graph you write is elaborated into a canonical s-expression (CSE), sealed with content-addressed hashes, and verified by an independent reader. The .husk file outlives the engine that produced it.

## Working Structure

Three nondeterministic processes coordinate through deterministic gates:

- **User** — sets the acceptance condition. The user is the only source of what "correct" means. When the task lacks an acceptance condition, ask for it; do not infer one.
- **Assistant** — writes the design. You translate the user's acceptance condition into a build graph whose deterministic gates cover as much of "correct" as possible.
- **Oracle** — produces output. An oracle is nondeterministic; its output cannot be trusted by inspection.

None of the three can verify another by looking inside it. They coordinate only through **deterministic gates**: action rules whose pass/fail does not depend on who produced the input.

**Consequences:**

1. Move acceptance into deterministic gates. Every part of the user's intent that can be expressed as a deterministic check must become an action rule with a `run` command.
2. Every oracle must have a downstream action validator. An oracle whose output nothing deterministically checks is an incomplete design. The validator must depend on what the oracle produced. Never let an oracle validate another oracle's output.

## Two Forms — Start Here

You need exactly two recipe forms:

- **`action`** — deterministic work. Copying files, running tests, packaging. An action always produces the same outputs from the same inputs.
- **`oracle`** — nondeterministic work. Writing code, generating content, making design decisions. An oracle has a prompt, a tool allowlist, and a fuel limit.

That's it. `action` and `oracle` cover every decomposition. Actions verify; oracles produce.

## Workflow

Your first tool call must be writing `design.json`. No exploring, no reading files, no running commands first.

1. Read the user's task description. Do NOT explore the codebase, read files, search, or run commands. Work only from what the user told you. If you need more information, ask — do not go looking. If the task does not state what would count as correct, the missing thing is the acceptance condition. Ask for it before writing the design.

2. Write `design.json` immediately. This is your first and only action before check.

3. Check the design:

   ```bash
   python -m husks.cli check design.json --verbose
   ```

   If `check` fails, repair `design.json` and re-check. Only show a passing design.

4. Ask for approval. Do not run unless the user explicitly approves or explicitly requested automatic execution in the same turn. When showing a design, state which of the user's requirements are covered by deterministic gates and which rest on the user's judgment.

5. Run the design:

   ```bash
   python -m husks.cli run design.json --site /tmp/husks-<name>
   ```

   The run command prints a structured **Report** showing status, root, fuel, cost, delta (changed/new/unchanged nodes), and a per-node table. Use `--json` for machine-readable output:

   ```bash
   python -m husks.cli run design.json --site /tmp/husks-<name> --json
   ```

   **Backend selection:**
   - `--backend claude-code` — for running inside Claude Code (uses the host tool loop)
   - `--backend litellm` (default) — for standalone runs with an API key

   **Dry run:** Use `--stub` to verify the build shape without making LLM calls. Oracles produce placeholder outputs so you can confirm the DAG wires correctly before spending fuel.

6. After the build completes, **verify the .husk artifact** (calls `recompute_root` internally):

   ```bash
   python -m husks.cli verify /tmp/husks-<name>
   ```

   This proves the .husk file is self-verifying — any future reader with SHA-256 and the site files can reproduce the root hash via `recompute_root`. The engine that built it can be discarded.

7. Read the Report output and relay the result:

   - If **halted**: the Report includes a `diagnosis` section with the exact error and failed nodes. Identify which rule failed and why, and suggest a revised design. Do not re-run without approval.
   - If **committed**: report success. Note the build-root and that the .husk is verified.

## Convergence Loop

A husk is designed to be re-run. On the second run:

- **Sealed rules are skipped.** If a rule's inputs haven't changed and its outputs are present, its seal matches and the rule does not fire. No fuel is consumed.
- **Stale rules re-fire.** If an input changed, an output is missing, or the recipe changed, the rule fires again.
- **The build-root changes** only if content changed. Same inputs + same recipe = same seal = same root.

To iterate:

1. Re-run the same design against the same site. Sealed rules are free.
2. If an oracle's output is unsatisfying, edit the prompt in `design.json` and re-run. The recipe-digest changes, so that rule (and its dependents) re-fire.
3. If a rule's output should be pinned, leave it alone — its seal protects it.

Watch for the **prompt-loading signature**: if the oracle's fuel is exhausted but outputs are wrong, the prompt needs refinement, not more fuel.

## Budget

- Allocate effort and fuel per oracle rule rather than uniformly. Rules whose validators are strict need more fuel headroom; rules with lenient gates need less.
- On re-run, read the report's per-rule realized cost and latency. Tighten fuel where there was slack; raise it where the gate failed under budget.
- When an oracle's output has been stable across runs, propose replacing it with a deterministic action.

## Design IR Format

```json
{
  "name": "build-name",
  "fuel": 40,
  "target": "done",
  "rules": [
    {
      "name": "generate-result",
      "kind": "oracle",
      "inputs": [],
      "outputs": ["result.txt"],
      "prompt": "Write a result to result.txt.",
      "tools": ["read-file", "write-file", "list-dir", "tree"],
      "fuel": 5
    },
    {
      "name": "validate",
      "kind": "action",
      "inputs": ["result.txt"],
      "outputs": ["test-results.txt"],
      "run": "python -m pytest -q > test-results.txt 2>&1"
    },
    {
      "name": "done",
      "kind": "action",
      "inputs": ["result.txt", "test-results.txt"],
      "outputs": [".complete"]
    }
  ]
}
```

## Site Inputs

Use `site_inputs` to import external files into the build site before rules fire. Two forms:

- **Dict form** (local name → absolute path): `{"local": "/abs/path/to/file"}` — copies the file into the site root under the key name.
- **List form** (list of absolute paths): `["/abs/path/to/file.txt"]` — copies each file into the site root using its basename.

Files listed in `site_inputs` are available as rule inputs without being produced by a prior rule.

## Top-Level Fields

* `name`: build name.
* `fuel`: global fuel budget.
* `target`: name of the terminal rule. Only the target and its transitive dependencies will fire. **Required.**

## Rule Fields

Each rule has:

* `name`: unique identifier.
* `kind`: `"action"` for deterministic work or `"oracle"` for nondeterministic LLM work.
* `inputs`: artifacts this rule reads. Inputs must exist at build start or be produced by an earlier rule.
* `outputs`: artifacts this rule must produce.
* `run`: action-only shell command to execute (cwd is the site directory).
* `prompt`: oracle-only instruction.
* `tools`: oracle-only tool allowlist. Core tools: `read-file`, `write-file`, `list-dir`, `tree`.
* `fuel`: oracle-only maximum number of LLM/tool-call steps.

## The Permanent Object

The flat design you write is **not the permanent artifact**. It is an ergonomic input that the engine elaborates into a canonical s-expression (CSE). The CSE is what gets hashed, sealed, and verified:

```
design.json  ──elaborate──▸  CSE AST  ──encode──▸  .husk bytes
                                                    │
                                         sealed, content-addressed,
                                         verifiable without the engine
```

The .husk file is the residue. It can be verified by any reader that implements the CSE spec — no Python, no Hy, no engine required. The design that produced it can be discarded.

## Constraints

* Every design must have a `target` naming the terminal rule.
* Every rule must declare at least one output.
* Every input must either exist at build start or be produced by a prior rule.
* Oracle rules must have `fuel > 0`, a prompt, and an explicit tool allowlist.
* Total oracle fuel must not exceed the build fuel budget.
* A rule may run only after its declared inputs are available.
* Validation must be a deterministic action (`run`), not an oracle. Oracles produce; actions verify.
* Every oracle rule must have a downstream action that validates its output (see Working Structure).
* A validator must gate on content derived from the oracle's output, not on a constant or output-independent check. If the validator passes regardless of what the oracle wrote, it is not a gate.
* The build should fail rather than invent undeclared inputs, outputs, or tools.
* The target rule should depend on all required deliverables. "Done" is explicit, not implicit.

## Principles

* **Action for deterministic work.** Copying files, parsing data, running validators, packaging artifacts.
* **Oracle for judgment.** Writing code, making design decisions, generating content, or resolving ambiguity.
* **Fuel bounds everything.** Every stale rule that fires costs one unit of global fuel. Every oracle additionally has a local fuel limit bounding its agentic steps. No unbounded loops.
* **Outputs are the contract.** The build records hashes for declared outputs and uses them for sealing, reuse, and traceability.
* **Show the design first.** The user should see the build graph, not a prose promise.
* **The .husk outlives the engine.** Verification is by content, never by instrumentation. The seal keys on what was asked and what came back, never on who answered.

## Output Discipline

Do not substitute a prose design for `design.json`. The required designning artifact is the JSON file. Prose may summarize the design only after the JSON has passed `check`.

Do not run additional commands after the build to verify results outside the design. If verification is needed, it belongs inside the design as an action rule with `run`. The build is self-contained. The one post-build verification is the .husk root recomputation, which proves permanence.
