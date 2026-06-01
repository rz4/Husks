# Canonical S-Expression Encoding (CSE) — v1

**Status:** Frozen. This document is never edited after its initial commit.

## 1. Overview

CSE is a binary serialization format for tree-structured data used by Husks
to compute deterministic seals and Merkle digests. Any conformant
implementation in any language can reproduce the same hashes from the same
inputs.

CSE values are either **atoms** (byte strings) or **lists** (ordered
sequences of CSE values).

## 2. Atoms (Netstring-style)

An atom is encoded as:

```
<length>:<bytes>
```

- `<length>` is the decimal ASCII representation of the byte count.
- Leading zeros are forbidden (e.g., `05:hello` is invalid).
- `<length>` is followed by a single colon (`0x3A`), then exactly
  `<length>` bytes of raw content.

**NIL** is the empty atom: `0:` (zero bytes of content).

### Examples

| Value          | Encoding          |
|----------------|-------------------|
| (empty)        | `0:`              |
| `hello`        | `5:hello`         |
| `1`            | `1:1`             |
| 256 zero bytes | `256:<256 × 0x00>`|

## 3. Lists

A list is encoded as:

```
( <child₁> <child₂> … <childₙ> )
```

- Open paren `0x28`, then zero or more CSE-encoded children concatenated
  with no separators, then close paren `0x29`.
- Empty list: `()`.

### Examples

| Value              | Encoding               |
|--------------------|------------------------|
| `[]`               | `()`                   |
| `[b"a"]`           | `(1:a)`                |
| `[b"seal", [b"x"]]`| `(4:seal(1:x))`       |

## 4. Positional Forms

CSE uses positional (not tagged) fields. The following forms are defined:

### 4.1 Husk (top-level wrapper)

```
(4:husk <version> <build>)
```

- `version`: atom, currently `1:1`.
- `build`: a build form.

### 4.2 Build

```
(5:build <name> <fuel> <target-node>)
```

- `name`: atom, the build name.
- `fuel`: atom, decimal ASCII fuel budget.
- `target-node`: a rule form (the root of the DAG).

### 4.3 Rule

```
(4:rule <name> <recipe> <inputs> <outputs> <child>*)
```

- `name`: atom, the rule name.
- `recipe`: a recipe form (action, oracle, or trial).
- `inputs`: list of name atoms `( name₁ name₂ … )`.
- `outputs`: list of name atoms `( name₁ name₂ … )`.
- Zero or more child rule forms follow outputs.

### 4.4 Action recipe

```
(6:action)
```

No fields. An action is a deterministic function.

### 4.5 Oracle recipe

```
(6:oracle <name> <prompt> <tools> <fuel>)
```

- `name`: atom (use `0:` for nil/anonymous).
- `prompt`: atom, the prompt text.
- `tools`: list of tool-name atoms `( tool₁ tool₂ … )`.
- `fuel`: atom, decimal ASCII fuel budget for the oracle.

### 4.6 Trial recipe

```
(5:trial <branch>*)
```

- Zero or more branch recipe forms.

## 5. Seal Preimage

```
seal-preimage = (4:seal <version> <recipe-digest> <input-bindings>)
```

- `version`: atom, CSE version (`1:1`).
- `recipe-digest`: atom, lowercase hex SHA-256 of `CSE(recipe-form)`.
- `input-bindings`: list of pairs `( (name hash) (name hash) … )`.
  - `name`: atom, the input file name.
  - `hash`: atom, lowercase hex SHA-256 of file content, or `6:absent`.

**Seal** = lowercase hex SHA-256 of `CSE(seal-preimage)`.

## 6. Merkle Node Digest

```
node-form = (4:node <name> <seal> <output-bindings> <child-digests>)
```

- `name`: atom, the rule name.
- `seal`: atom, the seal hex string.
- `output-bindings`: list of pairs `( (name hash) (name hash) … )`.
  - `hash`: atom, lowercase hex SHA-256 of output content, or `6:absent`.
- `child-digests`: list of digest atoms `( digest₁ digest₂ … )`.

**Node digest** = lowercase hex SHA-256 of `CSE(node-form)`.

The **build-root** is the node digest of the target node.

## 7. Child Ordering

Children appear in the order their names are first referenced scanning
the parent's input list left-to-right. This ensures deterministic
ordering without requiring explicit sorting.

## 8. Sorting Rules

- Input bindings in the seal preimage preserve the order from the rule's
  input list (which is the canonical order in the husk file).
- Output bindings in the node form preserve the order from the rule's
  output list.
- No additional sorting is applied; the husk file itself is the
  canonical source of order.

## 9. Verification

To verify a husk:

1. Parse the husk bytes using CSE.
2. Extract the build's target node.
3. Walk the DAG depth-first:
   a. Recursively verify all children.
   b. Hash each input file (or mark absent).
   c. Compute the seal from version, recipe, and input bindings.
   d. Hash each output file (or mark absent).
   e. Compute the node digest from name, seal, output bindings,
      and child digests.
4. The root node's digest is the **build-root**.
5. Compare against the expected root.

## 10. Conformance

A conformant reader MUST:

- Reject leading zeros in atom lengths.
- Treat atoms as raw bytes (not strings).
- Use SHA-256 for all hashes.
- Produce lowercase hex for all hash outputs.
- Reproduce `demo.root` from `demo.husk` + `demo.site/`.
