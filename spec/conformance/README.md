# Conformance Vectors

Any conformant CSE v1 reader must reproduce all frozen roots from the corresponding `.husk` and `.site/`.

## Vectors

### demo — two-rule build (sorted inputs)

- **`demo.husk`** — Canonical CSE bytes (binary). A two-rule build with an action and an oracle.
- **`demo.root`** — Single line: the lowercase hex build-root digest.
- **`demo.site/`** — Byte-exact site files (both inputs and outputs):
  - `greeting.txt` (14 bytes): `Hello, world!\n`
  - `config.txt` (10 bytes): `mode=demo\n`
  - `hello.txt` (17 bytes): `Hello from demo!\n`
  - `result.txt` (27 bytes): `Combined: Hello from demo!\n`

### unsorted — reverse-sorted inputs (CSE-v1 §8 ordering)

Tests that the reader preserves declared input order rather than sorting.
Per CSE-v1 §8, input bindings appear in the rule's declared order; no
additional sorting is applied.

- **`unsorted.husk`** — Single action rule with inputs `["z_input.txt", "a_input.txt"]` (reverse-sorted).
- **`unsorted.root`** — The correct build-root when input order is honored.
- **`unsorted.site/`** — Site files:
  - `z_input.txt` (10 bytes): `payload-z\n`
  - `a_input.txt` (10 bytes): `payload-a\n`
  - `merged.txt` (20 bytes): concatenation of both inputs

### adversarial — negative vector

- **`adversarial.husk`** — Structurally valid but with crafted content.
- **`adversarial.root`** — Expected root.

### malformed — rejection vectors

- **`malformed-leadingzero.husk`** — Must be rejected (leading zero in atom length).
- **`malformed-truncated.husk`** — Must be rejected (truncated atom).

## Verification

```bash
python -m husks selftest
```

Or with pytest:

```bash
python -m pytest tests/ -v
```

A conformant reader must reproduce all positive roots and reject all malformed vectors.

> **Note:** `verify.mjs` enforces a 10 MB file-size limit on `.husk` input. Files
> exceeding this limit are rejected with a non-zero exit code. This prevents the
> reader from hanging or consuming excessive memory on malformed/oversized input.
