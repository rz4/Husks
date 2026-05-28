# CLI Reference

Complete command reference for the `husks` CLI.

---

## Global options

| Flag | Description |
| :--- | :--- |
| `--color auto\|always\|never` | Color output mode |
| `--quiet`, `-q` | Suppress non-essential output |
| `--version` | Print version and exit |

---

## Exit codes

| Code | Meaning |
| :--- | :--- |
| 0 | Success |
| 1 | Build or check failure |
| 2 | Usage error (bad arguments) |
| 3 | Missing dependency |
| 4 | Dirty or stale (from `--fail-if-dirty` / `--fail-if-stale`) |
| 5 | Internal error |

---

## Commands

### husks check

Validate a design statically.

```text
husks check design.json [--verbose] [--json]
```

| Flag | Description |
| :--- | :--- |
| `--verbose`, `-v` | Print compiled graph after validation (replaces old `show`) |
| `--json` | Output categorized check results as JSON |

Default output shows per-category pass/fail:

```text
  ✓ syntax
  ✓ names
  ✓ paths
  ✓ inputs
  ✓ outputs
  ✓ fuel
  ✓ targets
  ✓ imports
  ✓ other
```

Exit 1 if any category has errors.

---

### husks run

Check, compile, and execute a design.

```text
husks run design.json [--site DIR] [--model MODEL] [--stub] [--hy]
                      [--verbose] [--json] [--soft-fail]
```

| Flag | Description |
| :--- | :--- |
| `--site DIR` | Override site directory |
| `--model MODEL` | LLM model for oracle rules (default: `anthropic/claude-haiku-4-5-20251001`) |
| `--stub` | Use stub oracle (no LLM, placeholder outputs) |
| `--hy` | Use original Hy kernel backend |
| `--verbose`, `-v` | Full trace + detailed report table |
| `--json` | Output full Report as JSON |
| `--soft-fail` | Exit 0 even when the build halts |

Default output is concise (one line per rule):

```text
  ✓ scaffold-package  (oracle)  $0.0012
  ✓ package-complete  (action)

  committed  root 511c1b7e25  fuel 28/30  $0.0012
```

Symbols: `✓` fired, `●` sealed (reused), `✗` failed.

---

### husks status

Show freshness state of a built site.

```text
husks status [design.json] --site DIR [--json]
             [--fail-if-dirty] [--fail-if-stale]
```

| Flag | Description |
| :--- | :--- |
| `--site DIR` | Site directory (required) |
| `--json` | Output as JSON |
| `--fail-if-dirty` | Exit 4 if any artifact is modified |
| `--fail-if-stale` | Exit 4 if any rule is stale |

Reads the build manifest from `.traces/build.manifest.json`.  For
each rule: reads its seal, compares input/output hashes against
current files.  Reports states: `fresh`, `stale`, `dirty`, `missing`.

---

### husks diff

Show differences between sealed and current artifacts.

```text
husks diff [design.json] --site DIR [artifact...] [--json]
```

| Flag | Description |
| :--- | :--- |
| `--site DIR` | Site directory (required) |
| `artifact...` | Filter to specific artifacts (default: all) |
| `--json` | Output as JSON |

Compares sealed hash (from `.traces/<rule>.seal`) against current
file content hash.  Categorizes artifacts as `modified`, `missing`,
or `undeclared`.

---

### husks explain

Explain a rule, artifact, or the build root.

```text
husks explain subject --site DIR [--json]
```

| Flag | Description |
| :--- | :--- |
| `--site DIR` | Site directory (required) |
| `--json` | Output as JSON |

Subject can be:
- A **rule name**: shows kind, inputs, outputs, state, seal, history summary
- An **artifact path**: shows producing rule, state, sealed hash, current hash
- `"root"`: shows build root hash, creation time, all rules

---

### husks graph

Render the dependency graph of a design.

```text
husks graph design.json [--format text|mermaid|dot|json] [--site DIR]
```

| Flag | Description |
| :--- | :--- |
| `--format FMT` | Output format: `text` (default), `mermaid`, `dot`, `json` |
| `--site DIR` | Overlay freshness state symbols from a built site |

---

### husks history

Show convergence history for rules.

```text
husks history design.json [rule] [--site DIR] [-n N]
```

| Flag | Description |
| :--- | :--- |
| `rule` | Specific rule name (omit for summary of all rules) |
| `--site DIR` | Override site directory |
| `-n N` | Number of recent entries to show (default: 5) |

Classifications: `converging`, `prompt-loading`, `stable`, `volatile`.

---

### husks gate

Run the conformance gate against an external CSE reader.

```text
husks gate "reader_cmd" [--stamp-dir DIR] [--no-cross-check]
                        [--json] [--verbose]
```

| Flag | Description |
| :--- | :--- |
| `--stamp-dir DIR` | Write `VERIFIED` stamp here on pass |
| `--no-cross-check` | Disable JS cross-check |
| `--json` | Output as JSON |
| `--verbose`, `-v` | Verbose output |

The reader command must accept `<husk-file> <site-dir>` as arguments
and print the lowercase-hex build root to stdout.

Also available as the standalone `husks-gate` entry point.

---

### husks doctor

Check environment and dependencies.

```text
husks doctor [--json]
```

Checks 8 items:

| Check | What it tests |
| :--- | :--- |
| `husks` | Package importable |
| `conformance` | Vectors found and counted |
| `selftest` | Frozen roots reproduced |
| `hy` | Hy importable (optional) |
| `litellm` | LiteLLM importable |
| `ANTHROPIC_API_KEY` | Environment variable set |
| `git` | Found on PATH |
| `node` | Found on PATH |

Symbols: `✓` pass, `✗` fail, `○` optional and absent.

---

### husks selftest

Verify the engine against frozen conformance vectors.

```text
husks selftest [--conformance DIR]
```

| Flag | Description |
| :--- | :--- |
| `--conformance DIR` | Override conformance vector directory |

Recomputes frozen roots with the bundled Python reader.  Confirms
malformed vectors are correctly rejected.  No network, no model.

---

### husks init

Wire a project to drive Husks from Claude Code.

```text
husks init [target] [--no-claude-code] [--force]
```

| Flag | Description |
| :--- | :--- |
| `target` | Target directory (default: `.`) |
| `--no-claude-code` | Skip Claude Code skill hookup |
| `--force` | Overwrite existing skill and CLAUDE.md |

Steps performed:
1. Soundness gate (runs selftest)
2. API key check (confirms `ANTHROPIC_API_KEY` or writes `.env` placeholder)
3. Skill hookup (installs skill at `.claude/skills/husks`)
4. CLAUDE.md emission (stance file versioned with engine)

Idempotent: re-running reports "exists" rather than clobbering.
