# Conditional Seed Semantics

**Beta Gate A4**: Conditional seed portability semantics.

## Semantic Decision

**Runtime Execution**: Only the selected branch executes (determined by predicate evaluation).

**Design Identity**: Both branches are bound into the seed identity (CSE form).

**Build Root**: Includes actual output content, so it differs when different branches produce different outputs.

## Why This Matters

This semantic choice enables seed portability while maintaining reproducibility:

```
Machine 1 (file exists)    →  executes 'then' branch  →  output A
Machine 2 (file missing)   →  executes 'else' branch  →  output B

Same seed design (same CSE form)
Different build outputs (different build-roots)
Both valid, both reproducible
```

## Key Principle

The **seed design** is portable and complete. The **build outputs** depend on the environment and predicate evaluation.

###  Design Identity (CSE Form)

When a `cond` node is serialized to CSE, it includes:
- The predicate identity
- The complete 'then' branch subtree
- The complete 'else' branch subtree

```python
[b"cond", predicate_id, then_cse, else_cse]
```

Both branches are part of the design, making it:
- **Complete**: All execution paths are specified
- **Portable**: The design can move between machines
- **Deterministic**: Same design → same CSE hash

### Build Root (Merkle DAG)

The build-root is computed AFTER execution and includes:
- Which branch actually executed
- The actual output content hashes
- The seals of rules that fired

Different branches produce different outputs, so:
```
Build-root = f(design, inputs, environment, predicate_result)
```

## Implications for Seed Portability

### ✓ Valid: Same seed, different outputs

Machine 1 and Machine 2 can run the **same seed** and produce **different outputs** if the predicate evaluates differently.

```json
{
  "name": "portable-build",
  "fuel": 10,
  "target": "result",
  "rules": [
    {
      "name": "with-cache",
      "kind": "action",
      "outputs": ["result.txt"],
      "run": "use-cache > result.txt"
    },
    {
      "name": "without-cache",
      "kind": "action",
      "outputs": ["result.txt"],
      "run": "compute-fresh > result.txt"
    },
    {
      "name": "result",
      "kind": "cond",
      "predicate": "file-exists:cache.db",
      "then": "with-cache",
      "else": "without-cache"
    }
  ]
}
```

- Machine 1 (has cache): executes `with-cache`, fast
- Machine 2 (no cache): executes `without-cache`, slow
- Both run the SAME seed design
- Different outputs are expected and valid

### ✗ Invalid: Different seeds, same outputs

If only the executed branch were bound into identity:
- Machine 1 would have a different "seed" than Machine 2
- The design would be incomplete
- Portability would break

## Three-Machine Proof

For the beta three-machine proof:

**Scenario**: Machine 1 and Machine 3 take different branches

- Machine 1: `predicate=True` → executes then branch → output A
- Machine 3: `predicate=False` → executes else branch → output B

**Expected behavior**:
- ✓ Same design (CSE hash matches)
- ✓ Different build-roots (outputs differ)
- ✓ Both valid and reproducible
- ✓ Seed is portable

**Not expected**:
- ✗ Same build-root (outputs are different)
- ✗ Build-root verification fails (different is expected)

## Comparison with Cache Reuse (Machine 2)

Machine 2 uses cache from Machine 1:
- Same design (CSE hash matches)
- Same branch executed (cache hit requires same recipe)
- Same build-root (reused outputs)
- Zero oracle cost

This is different from the conditional scenario where different branches execute.

## Design Completeness Requirement

A conditional design is complete only if both branches are specified:

```json
{
  "kind": "cond",
  "predicate": "test",
  "then": "branch-a",
  "else": "branch-b"  // Required
}
```

Missing either branch makes the design incomplete and non-portable.

## Implementation

### CSE Serialization (node_to_cse)

```python
if ntype == "cond":
    return [
        b"cond",
        atom(_pred_identity(node["predicate"])),
        node_to_cse(node["then"]),    # Both branches
        node_to_cse(node["else"]),     # included
    ]
```

### Runtime Evaluation (eval_cond)

```python
def eval_cond(S: Store, node: Node) -> None:
    predicate = node["predicate"]
    if predicate(S):
        eval_node(S, node["then"])   # Only one branch
    else:
        eval_node(S, node["else"])   # executes
```

### Build Root Computation (compute_build_root)

```python
if ntype == "cond":
    then_digest = compute_build_root(S, node["then"])
    else_digest = compute_build_root(S, node["else"])
    cse_form = [
        b"cond",
        atom(_pred_identity(node["predicate"])),
        atom(then_digest),    # Both digests
        atom(else_digest),    # in build-root
    ]
    return hashlib.sha256(encode(cse_form)).hexdigest()
```

The build-root includes digests of both branches, but those digests include actual output content from execution.

## Summary

**Semantic Choice**: Both branches bind into design identity (CSE form).

**Runtime**: Only one branch executes.

**Build-root**: Reflects actual execution and outputs.

**Portability**: The seed design is portable; the build outputs depend on environment.

This semantic enables conditional logic while maintaining seed portability and reproducibility.
