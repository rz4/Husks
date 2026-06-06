# Canonical S-Expression Encoding (CSE) — v2

**Status:** Frozen. This document is never edited after its initial commit.

**Origin:** Level-0 self-hosting (bootstrap-core). A cold-start oracle,
given only CSE-v1.md, produced a reader that parsed correctly but computed
wrong roots. Root cause: §7 describes tree *construction* ordering, but a
verifier read it as *traversal* instructions and implemented a name-matching
loop against input filenames instead of recursing into positional children.
Two independent trusted readers (Python, JavaScript) agreed on the correct
roots; the generated reader diverged on every node with depth.

---

## E1. Verifier/Elaborator Boundary

A CSE husk file is a complete, self-contained tree. A **verifier** (reader)
receives this tree as already-constructed CSE bytes and traverses it as-is.
It does not run elaboration, does not re-derive child relationships, and
does not match children against input names.

The elaborator (writer) is responsible for constructing the tree — resolving
dependencies, ordering children, and emitting canonical CSE bytes. The
verifier's job is to parse those bytes, walk the tree it finds, and
recompute hashes. These are distinct roles; the spec sections that govern
each are:

| Section | Addresses | Role |
|---------|-----------|------|
| §4.3 (Rule form) | Both | Structural: children are elements at indices 5+ |
| §7 (Child Ordering) | **Elaborator only** | How to order children during construction |
| §8 (Sorting Rules) | **Verifier** | Husk file is the canonical source of order |
| §9 (Verification) | **Verifier** | The algorithm a reader executes |

**§7 is not addressed to verifiers.** A verifier that re-derives child order
by scanning input names will produce wrong digests whenever child rule names
do not happen to match input filenames — which is the common case, since
rule names name *tasks* and input names name *files*.

## E2. Clarified Verification Algorithm

To verify a husk (replacing §9 in reader-facing context):

1. **Parse** the husk bytes using the CSE codec (§2–§3).
2. **Extract** the build's target node: `husk[2][3]` (the build form's
   fourth element).
3. **Walk** the target node depth-first by calling `recompute(node)`:

   a. Let `name` = `node[1]`, `recipe` = `node[2]`, `inputs` = `node[3]`,
      `outputs` = `node[4]`, `children` = `node[5], node[6], …`

   b. For each child in `children` **in positional order** (index 5, 6, …),
      recursively call `recompute(child)` and collect the returned digest.
      Do not reorder. Do not filter. Do not match against input names.

   c. For each name in `inputs` (in list order), hash the corresponding
      file from the site directory (SHA-256, lowercase hex), or use
      `absent` if the file does not exist. These are the **input bindings**:
      a list of `(name, hash)` pairs.

   d. Compute the **recipe digest**: SHA-256 of `CSE(recipe)`, as a
      lowercase hex string.

   e. Construct the **seal preimage** and compute the **seal**:
      ```
      seal-preimage = (4:seal <version> <recipe-digest> <input-bindings>)
      ```
      where `<recipe-digest>` is a 64-byte atom (the hex string), and
      `<input-bindings>` is a list of pairs. Seal = SHA-256 of
      `CSE(seal-preimage)`, lowercase hex.

   f. For each name in `outputs` (in list order), hash the corresponding
      file. These are the **output bindings**.

   g. Construct the **node form** and compute the **node digest**:
      ```
      node-form = (4:node <name> <seal> <output-bindings> <child-digests>)
      ```
      where `<seal>` is a 64-byte atom (hex string), `<output-bindings>`
      is a list of pairs, and `<child-digests>` is a list of 64-byte atoms
      (the hex digests from step b, in the same positional order).
      Node digest = SHA-256 of `CSE(node-form)`, lowercase hex.

   h. Return the node digest.

4. The value returned by `recompute(target)` is the **build-root**.
5. Compare against the expected root.

**Key point in step 3b:** the children are the CSE values at positions 5+
in the parsed rule list. The verifier iterates them in the order they
appear. §7's first-reference rule governs how the *writer* placed them
there; the reader does not re-execute that logic.

## E3. Worked Example — `demo.husk`

The demo vector has two rules: `greet` (leaf) and `combine` (parent with
one child). Site files:

| File | Content | SHA-256 |
|------|---------|---------|
| `config.txt` | `mode=demo\n` (10 bytes) | `a4f1b926508b79fe…` |
| `greeting.txt` | `Hello, world!\n` (14 bytes) | `d9014c4624844aa5…` |
| `hello.txt` | `Hello from demo!\n` (17 bytes) | `c52a2871827c6eba…` |
| `result.txt` | `Combined: Hello from demo!\n` (27 bytes) | `479614c63c438afa…` |

### E3.1 Leaf node: `greet`

**Recipe:** `(6:action)` — 10 bytes of CSE.

**Recipe digest:** SHA-256 of those 10 bytes:
```
904bc800959f5729a05c6a89b9adb23870273beffbde8724ae91286fe8824008
```

**Input bindings** (from rule's input list, in order):
```
config.txt   → a4f1b926508b79fe73a391d9c8a0ed1ae795ea8dd4e45d1ee74dd89b22d23de7
greeting.txt → d9014c4624844aa5bac314773d6b689ad467fa4e1d1a50a1b8a99d5a95f72ff5
```

**Seal preimage** (CSE bytes, 228 bytes):
```
(4:seal 1:1 64:<recipe-digest> ((10:config.txt 64:<hash>)(12:greeting.txt 64:<hash>)))
```
Note: `<recipe-digest>` is a **64-byte atom** — the hex string encoded as
a netstring `64:904bc800…`. Not raw bytes, not 32 bytes. The hex string
*is* the atom content.

**Seal:** SHA-256 of the seal preimage CSE bytes:
```
8f7b476739161fe52487ef6001c3f8c29b0ddabdca546045dbb20d122533af1f
```

**Output bindings:**
```
hello.txt → c52a2871827c6ebae0bb17321d5c79c4519d2e25ed58768266d02ba59850f156
```

**Child digests:** empty list `()` — `greet` has no children (nothing at
index 5+).

**Node form** (CSE, 166 bytes):
```
(4:node 5:greet 64:<seal> ((9:hello.txt 64:<hash>)) ())
```

**Node digest:** SHA-256 of the node form CSE bytes:
```
3f00f48af91210c9518a227904bb467edfc722cb8e132c816ff0526ff147713d
```

### E3.2 Parent node: `combine`

**Recipe:** `(6:oracle 0: 18:Combine the files. (9:read-file 10:write-file) 1:3)` — 62 bytes of CSE.

**Recipe digest:**
```
2b1e0eaf4d6a5853299707caca43acbd878cb4fa5ffea3c7afe477a2a703cad4
```

**Input bindings:**
```
hello.txt → c52a2871827c6ebae0bb17321d5c79c4519d2e25ed58768266d02ba59850f156
```

**Seal preimage** (CSE, 160 bytes):
```
(4:seal 1:1 64:<recipe-digest> ((9:hello.txt 64:<hash>)))
```

**Seal:**
```
6e115a61fcbcab6b63a0dceeb649548ff65b9d20431e6e654945a6d39c155fe6
```

**Output bindings:**
```
result.txt → 479614c63c438afa1b0e3909b5a0298b30c71f8903d7444eab200ad5a916f197
```

**Child digests:** `combine` has one child (`greet`, at index 5 in the
parsed rule list). The child-digests list contains greet's node digest as
a single 64-byte atom:
```
(64:3f00f48af91210c9518a227904bb467edfc722cb8e132c816ff0526ff147713d)
```

This is the critical point: the digest `3f00f48a…` appears here because
`greet` is the CSE value at position 5 in `combine`'s rule form. The
verifier recursed into it in step 3b and collected the returned digest.
It did **not** scan `combine`'s input list for `hello.txt`, find a child
named `hello.txt` (there is none — the child is named `greet`), or
perform any name matching.

**Node form** (CSE, 237 bytes — the full bytes):
```
(4:node 7:combine 64:<seal> ((10:result.txt 64:<hash>)) (64:<greet-digest>))
```

Exact CSE encoding:
```
(4:node7:combine64:6e115a61fcbcab6b63a0dceeb649548ff65b9d20431e6e
654945a6d39c155fe6((10:result.txt64:479614c63c438afa1b0e3909b5a029
8b30c71f8903d7444eab200ad5a916f197))(64:3f00f48af91210c9518a227904
bb467edfc722cb8e132c816ff0526ff147713d))
```

**Node digest (build-root):** SHA-256 of the above:
```
9977239d5eb0131a0eeeeb0dca4320e212e197ced1c8f0c41a6269929ed6cc51
```

This matches `demo.root`, confirming the worked example is consistent with
the frozen conformance vector.

### E3.3 The bug this example prevents

A reader that interprets §7 as a verification instruction would, at
`combine`, scan its input list `[hello.txt]`, look for a child *named*
`hello.txt`, find none (the child is named `greet`), and produce an empty
child-digests list. The resulting node form:

```
(4:node 7:combine 64:<seal> ((10:result.txt 64:<hash>)) ())
```

This hashes to a *different, definite* root — not a crash, not an error,
just a clean wrong answer that silently passes every structural check. The
only thing that catches it is the root hash comparison against the frozen
vector. The worked example above makes the correct child-digests list
unambiguous: it contains `greet`'s digest because `greet` is at index 5,
not because of any name relationship.

## E4. Digest Encoding Convention

All intermediate digests (recipe-digest, seal, child digests) are
**lowercase hex strings** encoded as CSE atoms. A recipe digest is a
64-character ASCII string, encoded as a 64-byte atom: `64:<hex>`. It is
never the raw 32-byte SHA-256 output.

This applies uniformly:
- `recipe-digest` in the seal preimage: `64:<hex>`
- `seal` in the node form: `64:<hex>`
- Each entry in `child-digests`: `64:<hex>`
- Each `hash` in input/output bindings: `64:<hex>` (or `6:absent`)

## E5. Recipe Identity and Host-Language Symbols

### E5.1 v1 recipe identity (CSE version `1`)

v1 action recipes seal as `(action <qualname> <cmd>)`, where `qualname`
is the Python function's `__qualname__` attribute and `cmd` is the shell
command string (empty for callable actions).  Cond predicates seal the
predicate callable's `__qualname__`.

This has two defects:

1. Renaming or relocating a Python function changes the seal and root
   even when behavior is identical, causing spurious re-fires.
2. Built-in JSON predicates (`file-exists:<path>`, `exit-zero:<cmd>`)
   compile to closures whose `__qualname__` is identical regardless of
   the argument — so `file-exists:/A` and `file-exists:/B` produce the
   same seal, causing false freshness.

v1 conformance vectors (`demo`, `adversarial`, `unsorted`) are frozen
with version atom `1` and remain verifiable under any conformant reader.

### E5.2 v2 recipe identity (CSE version `2`)

v2 recipe forms eliminate host-language symbols in favor of
behavior-based identity.  New builds emit version atom `2` in the husk
and seal preimage.

**Shell actions** (`run: "..."`): identity is the command string alone.

    recipe-form = (6:action <cmd>)

The `__qualname__` is dropped.  The command string is the sole identity
and is portable across producers.

**Callable actions** (Python callable, no shell command): identity is a
SHA-256 digest of the function's source code (via `inspect.getsource`),
or of `co_code + repr(co_consts)` if source is unavailable.

    recipe-form = (6:action 64:<behavior-digest>)

Renaming or relocating the function no longer changes the seal — only
changing the function's body does.

**Oracle and trial recipes**: unchanged from v1.

**Built-in cond predicates** (`file-exists:<path>`, `file-nonempty:<path>`,
`exit-zero:<cmd>`): identity is the full spec string.

    cond-form = (4:cond <spec-string> <then-node> <else-node>)

The compiler stamps `_husks_pred_spec` on each built-in closure with the
original spec string (e.g. `"file-exists:config.txt"`).  The engine
serializes this attribute instead of `__qualname__`.

**Custom Python cond predicates**: identity is a SHA-256 source/bytecode
digest, same scheme as callable actions.

### E5.3 Version negotiation

The version atom is embedded in the husk file: `(4:husk <version> ...)`.
A conformant reader extracts the version from the husk and uses it in
the seal preimage.  It must accept both `1` and `2`.

The engine uses version `2` for all new builds.  Existing v1 seal files
will mismatch on the first build after upgrade, causing a one-time
re-fire of all rules.  This is expected and correct: the recipe identity
schema changed.
