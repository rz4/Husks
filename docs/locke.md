# Locke: Discovery and Design

Locke is the surface language for Husks build designs.  It emerged from
a series of design conversations that progressively stripped away
complexity until two operators and a type distinction were enough to
express the full CSE build graph.

This document records the discovery path and the reasoning behind each
decision.

---

## The Problem

Husks designs were originally authored in JSON.  JSON is verbose and
structurally flat — every rule is a top-level dict, dependencies are
inferred from filename matching, shared sub-graphs are implicit.  The
JSON surface does not make the build tree visible in the source.

The goal: a minimal language that compiles to the same CSE bytes, with
no runtime dependency, where the tree structure is expressed by nesting.

---

## Discovery

### Step 1: Square-Lisp with `:-`

The first iteration borrowed from Lisp — square brackets, `:-` as the
binding operator, `@path` for file inclusion, bare words as atoms:

```
name     :- "core-bootstrap"
fuel     :- 20
target   :- "validate"

generate :- oracle [
  inputs  [CSE-v1.md CSE-v2.md]
  prompt  @prompts/generate-reader.txt
  fuel    15
]
```

This worked but was essentially JSON with different punctuation.  Three
problems:

1. `name`, `fuel`, `target` are metadata, not bindings — using the same
   operator for everything obscured intent.
2. `@path` was a third mechanism alongside strings and atoms.
3. Rules were flat.  The tree was still invisible.

### Step 2: Realization operator `:=`

The insight: build metadata (`name`, `fuel`, `target`) is *realized* —
it declares something concrete and deterministic.  Rules are
*compositional* — they wire together to form a tree.  Two different
things deserve two different operators.

`:=` became the realization operator.  Value on the left, label on the
right — the concrete thing *is the* label:

```
"core-bootstrap"  :=  public
20                :=  fuel
```

A rule bound with `:=` implicitly becomes the build target:

```
validate := action [...]
```

Only the first occurrence of each `:=` keyword is trusted.  Duplicates
are silently ignored — the first declaration wins.

### Step 3: `@` is redundant — atoms are files, strings are data

The `@path` syntax was a separate mechanism to say "read this file."
But the type system already carries that distinction:

- **Atom** (bare word): `prompts/generate-reader.txt` — a file on disk
- **String** (quoted): `"Do the thing."` — inline data

Once this clicked, `@` disappeared entirely.  The prompt field became:

```
prompts/generate-reader.txt  := prompt    # reads the file
"Write a parser."            := prompt    # inline text
```

No special syntax for file inclusion.  The type *is* the mechanism.

### Step 4: Value `:=` label inside blocks

The same realization pattern works inside rule blocks.  The
deterministic parts of a rule — inputs, outputs, free, exact, run,
prompt — are concrete declarations:

```
validate := action [
  [readers/generated_reader.py]  := inputs
  [readers/gate-report.txt]      := free
  [readers/VERIFIED]             := exact
  "python3 gate.py '...'"  := run
]
```

Reading left-to-right: "this list of files *is the* inputs."

### Step 5: Nesting — the tree is the source

The flat rule list meant dependencies were invisible.  Locke makes the
tree structural — child rules are nested inside their parents:

```
validate := action [
  [readers/generated_reader.py]  := inputs
  [readers/VERIFIED]             := exact
  "python3 gate.py '...'"  := run

  generate :- oracle [
    [CSE-v1.md CSE-v2.md]          := inputs
    [readers/generated_reader.py]  := free
    prompts/generate-reader.txt    := prompt
    [read-file write-file]         := tools
    15                             := fuel
  ]
]
```

Reading top-down traces the DAG from target to leaves.  The tree
structure is visible in indentation.  The compiler flattens nested rules
depth-first into the flat design dict that `elaborate()` expects.

### Step 6: `let` for shared sub-trees

Diamond DAGs need a node referenced by multiple parents.  Without
sharing, you'd duplicate the definition:

```
merge := action [
  left :- action [
    shared :- action [...]   # copy 1
  ]
  right :- action [
    shared :- action [...]   # copy 2
  ]
]
```

`let` introduces a scope where bindings are defined once and visible to
all siblings — following Lisp's `let` semantics:

```
merge := action [
  [left.txt right.txt]  := inputs
  [merged.txt]          := outputs
  "cat left.txt right.txt > merged.txt"  := run

  :- let [
    shared :- action [
      [seed.txt]     := inputs
      [common.txt]   := outputs
      "python3 init.py seed.txt > common.txt"  := run
    ]

    left :- action [
      [common.txt]  := inputs
      [left.txt]    := outputs
      "python3 transform.py --side left"  := run
    ]

    right :- action [
      [common.txt]  := inputs
      [right.txt]   := outputs
      "python3 transform.py --side right"  := run
    ]
  ]
]
```

Multiple bindings, then the body that uses them.  One definition, one
node in the CSE tree, multiple references.

### Step 7: `cond` as rule evaluation

Conditions don't use synthetic predicate strings.  The predicate *is* a
rule — did it produce its outputs?  The build DAG is the control flow:

```
evaluation :- cond [
  validate                        # rule to evaluate

  benchmark :- action [...]       # then: on success
  skip :- halt [                  # else: on failure
    "validation failed" := reason
  ]
]
```

Three positional parts: the predicate rule (bare reference), the then
branch, the else branch.

---

## Final Syntax

Two operators:

| Operator | Name | Direction | Meaning |
|----------|------|-----------|---------|
| `:=` | Realization | value := label | Deterministic, concrete |
| `:-` | Composition | name :- kind [...] | Compositional, structural |

Type semantics:

| Type | Syntax | Meaning |
|------|--------|---------|
| Atom | `bare/word.txt` | File reference (resolved at parse time) |
| String | `"quoted text"` | Inline data |
| Int | `20` | Numeric literal |
| Float | `0.5` | Numeric literal |
| Cell | `[a b c]` | List of values |

Top-level declarations:

| Form | Example |
|------|---------|
| Build name | `"core-bootstrap" := public` |
| Fuel budget | `20 := fuel` |
| Site inputs | `["a" "path/a" "b" "path/b"] := site-inputs` |
| Cost tolerance | `[0.5 2.0] := cost-tolerance` |
| Target rule | `validate := action [...]` |

Rule kinds:

| Kind | Purpose |
|------|---------|
| `action` | Deterministic shell command |
| `oracle` | LLM-backed generation |
| `trial` | Try multiple branches, pick the best |
| `cond` | Conditional on rule evaluation |
| `let` | Shared sub-tree binding |
| `commit` | Terminal success |
| `halt` | Terminal failure |

---

## Compilation Pipeline

```
.locke source
    |  tokenize (hand-rolled lexer, zero deps)
    v
Token list
    |  parse (recursive descent)
    v
AST (DeclNode, RuleNode, LetNode, BindNode)
    |  resolve (flatten tree, merge free/exact, resolve files)
    v
Flat design dict (same shape as JSON)
    |  elaborate()          <-- forms.py
    v
CseValue tree
    |  kernel.encode()      <-- kernel.py
    v
.husk CSE bytes
```

---

## Invariant

`core-bootstrap.locke` produces byte-identical CSE output to
`core-bootstrap.json`.  This is tested in `tests/test_locke.py`.
