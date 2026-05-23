# Conformance Vector

Any conformant CSE v1 reader reproduces `demo.root` from `demo.husk` and `demo.site/`.

## Files

- **`demo.husk`** — Canonical CSE bytes (binary). A two-rule build with an action and an oracle.
- **`demo.root`** — Single line: the lowercase hex build-root digest.
- **`demo.site/`** — Byte-exact site files (both inputs and outputs):
  - `greeting.txt` (14 bytes): `Hello, world!\n`
  - `config.txt` (10 bytes): `mode=demo\n`
  - `hello.txt` (17 bytes): `Hello from demo!\n`
  - `result.txt` (27 bytes): `Combined: Hello from demo!\n`

## Verification

```bash
python tests/test_conformance.py
```

Or with pytest:

```bash
python -m pytest tests/test_conformance.py -v
```

The gate passes when `test_build_root` reports PASS.
