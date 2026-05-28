# Husks CLI

The Husks CLI has seven primary verbs.

```text
husks init       create a runnable project
husks check      validate a design
husks run        execute a design
husks status     show freshness and local changes
husks explain    explain a rule, artifact, root, graph, seal, or diff
husks history    show prior runs and convergence
husks doctor     diagnose the local environment
```

This grammar is organized around user questions.

```text
init      How do I start?
check     Is this design valid?
run       What builds?
status    What is fresh, stale, dirty, or missing?
explain   Why?
history   What happened before?
doctor    Why is my setup broken?
```

Everything else should be an option, mode, or compatibility alias until users prove it deserves a top-level verb.

## First run

A clean checkout should have one path that works.

```bash
pip install -e .
husks doctor
husks init demo
cd demo
husks check design.json
husks run design.json
husks status
husks history
```

The first run should leave the user with a built site, a visible root, a small history, and enough local files to edit and rerun.

## Global options

```text
husks [--color auto|always|never] [--quiet] [--version] COMMAND ...
```

| Option | Meaning |
| :--- | :--- |
| `--color auto\|always\|never` | Control color output. |
| `--quiet`, `-q` | Suppress nonessential output. |
| `--version` | Print the installed version. |

## Exit codes

| Code | Meaning |
| :--- | :--- |
| `0` | Success. |
| `1` | Build, validation, or conformance failure. |
| `2` | Usage error. |
| `3` | Missing dependency. |
| `4` | Dirty or stale state when a failure flag is set. |
| `5` | Internal error. |

## `husks init`

Create a runnable Husks project.

```text
husks init [target] [--example NAME] [--force]
```

| Option | Meaning |
| :--- | :--- |
| `target` | Target directory. Defaults to the current directory. |
| `--example NAME` | Start from a bundled example. Defaults to `minimal`. |
| `--force` | Replace files that Husks owns. |

`init` should create a complete first project, not a placeholder. The generated project should include a design, a prompt or input file, a small action rule, a site directory convention, and short local instructions.

Expected output:

```text
created demo
  design.json
  inputs/spec.md
  scripts/check.py
  .husks/

next:
  cd demo
  husks check design.json
  husks run design.json
```

`init` may also install editor or agent hints, but that should not be the main contract. The main contract is a runnable Husks project.

## `husks check`

Validate a design without executing it.

```text
husks check [design] [--verbose] [--json]
```

| Option | Meaning |
| :--- | :--- |
| `design` | Design file. Defaults to `design.json` when present. |
| `--verbose`, `-v` | Show the compiled design after validation. |
| `--json` | Emit machine-readable validation results. |

The default output should answer one question: can this design run?

```text
checking design.json
  ✓ syntax
  ✓ names
  ✓ paths
  ✓ inputs
  ✓ outputs
  ✓ fuel
  ✓ targets

ok
```

On failure, show the smallest useful repair.

```text
checking design.json
  ✓ syntax
  ✓ names
  ✗ inputs
    rule build-tests reads tests/spec.md, but no rule produces it and it is not listed as a site input

failed
```

## `husks run`

Check, compile, and execute a design.

```text
husks run [design] [--site DIR] [--model MODEL] [--stub] [--json] [--verbose] [--soft-fail]
```

| Option | Meaning |
| :--- | :--- |
| `design` | Design file. Defaults to `design.json` when present. |
| `--site DIR` | Override the site directory. |
| `--model MODEL` | Model name for live oracle rules. |
| `--stub` | Replace live oracle calls with deterministic placeholder output. |
| `--json` | Emit the full run report as JSON. |
| `--verbose`, `-v` | Show the full trace and report table. |
| `--soft-fail` | Return exit code 0 even if the build halts. |

Default output should be short and operational.

```text
site: .husks-site
root: pending

✓ write-spec        rebuilt    action completed
● write-tests       reused     seal unchanged
✓ write-solution    rebuilt    oracle anthropic/claude-haiku-4-5
✓ score             rebuilt    action completed

build complete
4 rules checked, 3 rebuilt, 1 reused
root: 2ab73f4a1c0d9e44...
fuel: 18/30
cost: $0.0012
```

Symbols:

| Symbol | Meaning |
| :--- | :--- |
| `✓` | Rule ran in this build. |
| `●` | Rule was reused from a previous seal. |
| `✗` | Rule failed. |
| `○` | Rule was skipped after an upstream failure. |

A second run with no changes should be visibly boring.

```text
site: .husks-site
root: 2ab73f4a1c0d9e44...

● write-spec        reused     seal unchanged
● write-tests       reused     seal unchanged
● write-solution    reused     seal unchanged
● score             reused     seal unchanged

nothing to rebuild
root: 2ab73f4a1c0d9e44...
```

## `husks status`

Show the state of the current site.

```text
husks status [design] [--site DIR] [--json] [--fail-if-dirty] [--fail-if-stale]
```

| Option | Meaning |
| :--- | :--- |
| `design` | Design file. Defaults to `design.json` when present. |
| `--site DIR` | Override the site directory. |
| `--json` | Emit status as JSON. |
| `--fail-if-dirty` | Exit `4` if any sealed artifact was modified. |
| `--fail-if-stale` | Exit `4` if any rule is stale or missing. |

`status` answers what would happen if the user ran the design now.

```text
site: .husks-site
root: 2ab73f4a1c0d9e44...

rules
  fresh   write-spec
  stale   write-tests       input changed: inputs/spec.md
  stale   write-solution    upstream stale: write-tests
  stale   score             upstream stale: write-solution

artifacts
  fresh   spec.md
  dirty   tests.py          current hash differs from sealed hash
  fresh   solution.py
  fresh   scores.json
```

The default status view should include the reason for staleness. Hashes belong in `explain`, not the default status view.

## `husks explain`

Explain one thing in the build.

```text
husks explain SUBJECT [--site DIR] [--json]
husks explain --graph [design] [--format text|mermaid|dot|json] [--site DIR]
husks explain --diff [artifact ...] [--site DIR] [--json]
husks explain --seal SUBJECT [--site DIR] [--json]
```

| Form | Meaning |
| :--- | :--- |
| `husks explain RULE` | Explain a rule. |
| `husks explain ARTIFACT` | Explain an artifact and its producing rule. |
| `husks explain root` | Explain the current build root. |
| `husks explain --graph` | Render the dependency graph. |
| `husks explain --diff` | Compare sealed and current artifacts. |
| `husks explain --seal SUBJECT` | Show seal material for a rule, artifact, or root. |

`explain` is the escape hatch. It is where the CLI may show internals: seals, recipe digests, artifact hashes, dependency edges, trial reports, reader roots, and exact mismatch reasons.

Rule example:

```text
rule: write-solution  oracle
state: stale
reason: input changed: tests.py

inputs
  spec.md
  tests.py

outputs
  solution.py

seal
  current: none
  previous: 91fd1ad6e4d091d2...
  recipe:  36b62c39115eea0f...

history
  5 runs
  last output hash: 9b40c4d6f0...
```

Artifact example:

```text
artifact: tests.py
state: dirty
rule: write-tests

sealed hash:  01ab8d57e1c7...
current hash: 74dd230191c4...

repair
  rerun: husks run design.json
  inspect diff: husks explain --diff tests.py
```

Graph example:

```bash
husks explain --graph --format mermaid > graph.md
```

Diff example:

```bash
husks explain --diff tests.py
```

Seal example:

```bash
husks explain --seal write-solution
```

## `husks history`

Show prior runs.

```text
husks history [design] [rule] [--site DIR] [-n N] [--json]
```

| Option | Meaning |
| :--- | :--- |
| `design` | Design file. Defaults to `design.json` when present. |
| `rule` | Optional rule name. If omitted, show all rules. |
| `--site DIR` | Override the site directory. |
| `-n N` | Number of entries to show. Defaults to `5`. |
| `--json` | Emit history as JSON. |

Default summary:

```text
history: .husks-site

write-spec        3 runs   stable
write-tests       3 runs   converging
write-solution    5 runs   volatile
score             5 runs   stable
```

Single-rule view:

```text
history: write-solution  5 runs

run          fuel   prompt   reads   output hash    result
8d3a9b1c     8      1421     2       9b40c4d6       pass
1f02cace     6      1310     2       9b40c4d6       pass
c71db50a     9      1604     3       aa29e731       fail

classification: volatile
```

History should help the user decide whether a rule is stabilizing, prompt-loading, or still wandering.

## `husks doctor`

Diagnose the local environment.

```text
husks doctor [--json] [--selftest] [--conformance] [--live]
```

| Option | Meaning |
| :--- | :--- |
| `--json` | Emit diagnostics as JSON. |
| `--selftest` | Run frozen conformance vectors. |
| `--conformance` | Include external reader and cross-language checks. |
| `--live` | Check live oracle readiness. |

Default output should avoid network calls.

```text
✓ husks                 importable
✓ conformance vectors   6 found
✓ selftest              pass
○ hy                    not installed, optional
✓ litellm               importable
○ ANTHROPIC_API_KEY     not set, needed for live oracle rules
✓ git                   found
✓ node                  found
```

`doctor --selftest` replaces a separate top-level `selftest` command in the minimal grammar.

```bash
husks doctor --selftest
```

`doctor --conformance` replaces a separate top-level `gate` command in the minimal grammar.

```bash
husks doctor --conformance --reader "python readers/generated_reader.py" --stamp-dir readers
```

## Compatibility aliases

The implementation may keep older top-level commands as aliases. They should be documented as compatibility surfaces, not as the primary grammar.

| Compatibility command | Preferred form |
| :--- | :--- |
| `husks selftest` | `husks doctor --selftest` |
| `husks gate ...` | `husks doctor --conformance ...` |
| `husks diff ...` | `husks explain --diff ...` |
| `husks graph ...` | `husks explain --graph ...` |
| `husks seal ...` | `husks explain --seal ...` |

Aliases are useful for scripts. The user-facing grammar should remain small.

## Design defaults

Commands that accept a design should default to `design.json` if it exists in the current directory. Commands that accept a site should use this order:

1. `--site DIR`
2. site declared in the design
3. `.husks-site` if it exists

This makes the common loop short.

```bash
husks check
husks run
husks status
husks explain write-tests
husks history
```

## Output rules

Default output is for humans. JSON output is for tools.

Human output should follow five rules.

1. Show the site and root when they matter.
2. Show one line per rule unless the command is `explain`.
3. Show the reason for every stale, dirty, missing, or failed state.
4. Hide full hashes by default. Use short hashes unless the user asks for seal material.
5. End with a useful next action when the command fails.

Machine output should be stable and versioned.

```json
{
  "schema": "husks.report.v1",
  "status": "complete",
  "site": ".husks-site",
  "root": "2ab73f4a1c0d9e44...",
  "rules": []
}
```

## Command ownership

Each verb owns one domain.

| Verb | Owns |
| :--- | :--- |
| `init` | Project creation. |
| `check` | Static validation. |
| `run` | Execution and committing new sealed state. |
| `status` | Freshness and local mutation. |
| `explain` | Causality, internals, graphs, hashes, and diffs. |
| `history` | Prior runs and convergence. |
| `doctor` | Environment, conformance, and backend readiness. |

A new top-level verb should be added only when it answers a user question that none of these verbs can own cleanly.
