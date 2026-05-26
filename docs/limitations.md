# Current Limitations

Concrete gaps in what the engine can express or execute today.

## 1. No parallelism

The engine walks the dependency tree depth-first, one rule at a time.
Independent branches (e.g. `left` and `right` in a diamond DAG) execute
sequentially even though the graph says they could run concurrently.

## 2. Limited predicate vocabulary for JSON cond rules

`cond`, `let`, and `trial` all compile from JSON.  `cond` predicates can
be specified as built-in strings (`file-exists:<path>`,
`file-nonempty:<path>`, `exit-zero:<command>`) or looked up from the
optional `predicates` dict.  Custom predicates that don't fit these
patterns still require Python.

## 3. No incremental output within a rule

A rule either fully commits or fully halts.  If an oracle writes 3 of 4
declared outputs and then exhausts fuel, all work is discarded.  There
is no partial sealing.

## 4. No remote or distributed execution

The site directory is a local filesystem path.  The oracle backend, tool
sandbox, and seal I/O all assume local disk.  There is no mechanism for
running rules on different machines or sharing sealed artifacts across
builds.

**Partial mitigation:** read-only imports (`"imports"` in a design) allow
referencing external files and directories.  The engine symlinks them
into the site at build start and the sandbox permits reads through those
symlinks while blocking writes.  This covers shared datasets, config
from another repo, and prior build outputs — but the external paths must
still be on the local filesystem.

## 5. No artifact caching across sites

Freshness checks compare against `.traces/<rule>.seal` in the current
site.  If you run the same design against a fresh site directory, every
rule re-fires even if the inputs and recipe are identical to a previous
build elsewhere.  Content-addressed storage could enable this but
doesn't exist.

## 6. Actions can't fail gracefully

An action rule runs a shell command or Python callable.  If it returns a
nonzero exit code, the build halts.  There is no retry, no fallback, no
way to express "try this action, and if it fails, do something else"
without `trial`.

## 7. No streaming or progress from oracles

The oracle backend returns a complete result.  There is no callback for
partial output, token streaming, or intermediate checkpoints.  For
long-running oracle calls, the user sees nothing until the rule either
commits or exhausts fuel.

## 8. ~~Single-target builds only~~ (resolved)

Multi-target builds are now supported.  A design may specify
`"targets": ["rule-a", "rule-b"]` to commit multiple independent DAG
roots in a single build.  The legacy `"target": "x"` (string) form is
still accepted and treated as a one-element targets list.  The build-root
for multi-target builds is the SHA-256 of the sorted per-target roots
concatenated together.

## 9. No dynamic graph construction

The rule graph is static — fully determined before execution.  A rule
can't spawn new rules based on what it discovers.  If an oracle finds it
needs to decompose work further, that decomposition has to happen in a
new design, not within the current build.

## 10. Hy dependency is mandatory

`pyproject.toml` lists `hy>=1.0.0` as a hard dependency even though the
Hy backend is optional and wrapped in a try/except.  Users who only want
JSON designs still need Hy installed.
