---
name: husks
description: Decompose a task into a Husks plan — an auditable, fuel-bounded build graph.
allowed-tools: Bash(python -m husks.cli *) Bash(./husks *) Bash(cd *) Bash(source *) Read Write
---

You are working with **Husks**, a fuel-bounded build calculus. Do not execute tasks as an unbounded agent loop. Decompose the task into a **plan**: a machine-checkable build graph with declared inputs, outputs, recipes, and fuel bounds.

**The plan is a Husk.** Not prose. Not vibes. A build contract the user can inspect before execution and trace after execution.

## Workflow

Your first tool call must be writing `plan.json`. No exploring, no reading files, no running commands first.

1. Read the user's task description. Do NOT explore the codebase, read files, search, or run commands. Work only from what the user told you. If you need more information, ask — do not go looking.

2. Write `plan.json` immediately. This is your first and only action before check.

3. Check and show the plan in one step:

   ```bash
   python -m husks.cli check plan.json && python -m husks.cli show plan.json
   ```

   If `check` fails, repair `plan.json` and re-check. Only show a passing plan.

4. Ask for approval. Do not run unless the user explicitly approves or explicitly requested automatic execution in the same turn.

5. Run the plan:

   ```bash
   python -m husks.cli run plan.json --site /tmp/husks-<name>
   ```

6. After the build completes, summarize the result:

   - **Status**: committed or halted
   - **Rules fired / reused**: which rules ran, which were sealed
   - **Artifacts produced**: list with hashes
   - **Fuel**: used / total
   - **Cost**: total oracle cost
   - If **halted**: read the trace, identify which rule failed and why, and suggest a revised plan. Do not re-run without approval.
   - If **committed**: report success. If any validation action wrote failure output, note it and suggest a repair plan.

Do not run additional commands after the build to verify results. The build trace IS the verification. If validation should happen, it must be an action rule inside the plan.

## Plan IR Format

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

## Constraints

* Every plan must have a `target` naming the terminal rule.
* Every rule must declare at least one output.
* Every input must either exist at build start or be produced by a prior rule.
* Oracle rules must have `fuel > 0`, a prompt, and an explicit tool allowlist.
* Total oracle fuel must not exceed the build fuel budget.
* A rule may run only after its declared inputs are available.
* Validation must be a deterministic action (`run`), not an oracle. Oracles produce; actions verify.
* The build should fail rather than invent undeclared inputs, outputs, or tools.
* The target rule should depend on all required deliverables. "Done" is explicit, not implicit.

## Principles

* **Action for deterministic work.** Copying files, parsing data, running validators, packaging artifacts.
* **Oracle for judgment.** Writing code, making design decisions, generating content, or resolving ambiguity.
* **Fuel bounds everything.** Every oracle has a local fuel limit. The build has a global fuel limit. No unbounded loops.
* **Outputs are the contract.** The build records hashes for declared outputs and uses them for sealing, reuse, and traceability.
* **Show the plan first.** The user should see the build graph, not a prose promise.

## Output Discipline

Do not substitute a prose plan for `plan.json`. The required planning artifact is the JSON file. Prose may summarize the plan only after the JSON has passed `check`.

Do not run additional commands after the build to verify results outside the plan. If verification is needed, it belongs inside the plan as an action rule with `run`. The build is self-contained.
