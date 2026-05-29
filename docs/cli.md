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
husks run design.json [--site DIR] [--model MODEL] [--stub] [--reuse-only]
                      [--hy] [--verbose] [--json] [--soft-fail]
```

| Flag | Description |
| :--- | :--- |
| `--site DIR` | Override site directory |
| `--model MODEL` | LLM model for oracle rules (default: `anthropic/claude-haiku-4-5-20251001`) |
| `--stub` | Use stub oracle (no LLM, placeholder outputs) |
| `--reuse-only` | Only use cached results, never call oracle (Beta Gate D5) |
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

### husks explain

Explain a rule, artifact, graph, diff, or seal.

```text
husks explain [subject] [--site DIR] [--json]
              [--graph] [--diff] [--seal SUBJECT]
              [--format text|mermaid|dot|json]
              [--artifact ARTIFACT]
```

| Flag | Description |
| :--- | :--- |
| `subject` | Rule name, artifact path, or design file for --graph mode |
| `--site DIR` | Site directory |
| `--json` | Output as JSON |
| `--graph` | Render dependency graph |
| `--diff` | Show differences between sealed and current artifacts |
| `--seal SUBJECT` | Show seal material for rule, artifact, or root |
| `--format FMT` | Output format for --graph: `text`, `mermaid`, `dot`, `json` |
| `--artifact ARTIFACT` | Specific artifact for --diff (can be repeated) |

**Modes:**

**Explain a rule or artifact:**
```bash
husks explain generate --site ./site
husks explain response.txt --site ./site
```

**Show dependency graph:**
```bash
husks explain design.json --graph --format mermaid
```

**Show diff between sealed and current:**
```bash
husks explain --diff --site ./site
husks explain --diff --site ./site --artifact response.txt
```

**Show seal material:**
```bash
husks explain --seal generate --site ./site
husks explain --seal root --site ./site
```

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

### husks compare

Compare artifact equivalence across sites.

```text
husks compare site1 site2 [site3 ...] [--json] [--roots-only] [--hashes-only]
```

| Flag | Description |
| :--- | :--- |
| `sites` | Site directories to compare (2 or more) |
| `--json` | Output comparison result as JSON |
| `--roots-only` | Compare build roots only (skip output hash checks) |
| `--hashes-only` | Compare output hashes only (skip root checks) |

Compares artifact equivalence across multiple built sites. Checks:
- Build root equality (cryptographic seal of entire build)
- Output artifact hash equality (file-by-file comparison)

Used for validating cross-machine reproducibility.

---

### husks compare-runs

Compare JSON reports from multiple runs (three-machine proof).

```text
husks compare-runs report1.json report2.json [report3.json ...] [--json]
```

| Flag | Description |
| :--- | :--- |
| `reports` | JSON report files from `husks run --json` (2 or more) |
| `--json` | Output comparison result as JSON |

Validates the three-machine proof pattern:
- **M1**: Pays oracle cost, produces valid build
- **M2**: Reuses cache, zero oracle cost, equivalent artifacts
- **M3**: Rebuilds independently, pays cost, equivalent artifacts

Checks:
- Root equivalence across all runs
- M1 paid non-zero oracle cost
- M2 has zero oracle calls and zero cost (cache hit)
- M2 has explicit cache evidence (`cached=true` nodes)
- M3 paid non-zero oracle cost
- All reports conform to beta schema

---

### husks doctor

Check environment and dependencies, run conformance tests.

```text
husks doctor [--json] [--selftest] [--conformance] [--live]
             [--reader CMD] [--stamp-dir DIR] [--no-cross-check]
             [--verbose]
```

| Flag | Description |
| :--- | :--- |
| `--json` | Output as JSON |
| `--selftest` | Run frozen conformance vectors (replaces old `husks selftest`) |
| `--conformance` | Run external reader conformance gate (replaces old `husks gate`) |
| `--live` | Check live oracle readiness (API key, litellm, oracle ping, dev tools) |
| `--reader CMD` | Reader command for --conformance (e.g., `"python my_reader.py"`) |
| `--stamp-dir DIR` | Write VERIFIED stamp here on conformance pass |
| `--no-cross-check` | Disable JS cross-check (with --conformance) |
| `--verbose`, `-v` | Verbose output |

**Default mode** (no flags): Checks 8 items:

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

**Selftest mode** (`--selftest`): Verifies engine against frozen conformance vectors.
Recomputes frozen roots with bundled Python reader. Confirms malformed vectors are
correctly rejected. No network, no model.

**Conformance mode** (`--conformance`): Runs conformance gate against external CSE reader.
Reader command must accept `<husk-file> <site-dir>` and print lowercase-hex build root
to stdout.

**Live mode** (`--live`): Checks live oracle readiness (API key, litellm, oracle ping).

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

---

### husks cache

Manage oracle cache for cross-machine transfer.

#### cache export

Export cache to tarball for cross-machine transfer.

```text
husks cache export <file> --site DIR [--json]
```

| Flag | Description |
| :--- | :--- |
| `file` | Path to write .tar.gz archive |
| `--site DIR` | Site directory containing cache (required) |
| `--json` | Output result as JSON |

Exports the `.cache` directory from a built site to a portable tarball.
Used in the three-machine proof to transfer oracle results from M1 to M2.

**Example:**
```bash
husks cache export cache.tar.gz --site ./m1-site
```

#### cache import

Import cache from tarball.

```text
husks cache import <file> --site DIR [--no-merge] [--json]
```

| Flag | Description |
| :--- | :--- |
| `file` | Path to .tar.gz archive |
| `--site DIR` | Site directory to import into (required) |
| `--no-merge` | Clear existing cache before import (default: merge) |
| `--json` | Output result as JSON |

Imports a cache tarball into a site directory. By default, merges with
existing cache entries. Use `--no-merge` to replace the entire cache.

**Example:**
```bash
husks cache import cache.tar.gz --site ./m2-site
husks run design.json --site ./m2-site --reuse-only
```

