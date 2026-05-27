<p align="center">
  <img src="assets/logo/husks-banner.png" alt="Husks" width="900">
</p>

# Husks

**Build Husks, not vibes.**

Husks is a deterministic build calculus for nondeterministic work.

A model call is an event. You were not in the room. You do not get the event — you get what it leaves behind, and Husks forces it to leave something you can hold: sealed, content-addressed residue. The call is the event. The husk is the carcass.

The language gives uncertainty exactly one form: `oracle`. Everything else is structure.

---

## Quickstart

```bash
git clone https://github.com/rz4/Husks.git
cd Husks
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Check a design against its contract:

```bash
husks check examples/husks-demo.design.json
```

Run it with a stub oracle — no model, no key, just the machinery:

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo --stub
```

Run it again. Fresh seals skip work already done:

```bash
husks run examples/husks-demo.design.json --site /tmp/husks-demo --stub
```

Read how a node has moved across runs:

```bash
husks history examples/husks-demo.design.json --site /tmp/husks-demo
```

---

## The language

Nine forms. That is the whole language.

| Category | Form | Function |
| :--- | :--- | :--- |
| **Structural** | `build` | Bounded top-level evaluation. |
| | `rule` | A work node with declared inputs and outputs. |
| | `let` | Shared subtrees — the diamonds in the DAG. |
| | `cond` | Conditional structure. |
| **Recipes** | `action` | Deterministic function. |
| | `oracle` | Bounded model call. The one source of uncertainty. |
| | `trial` | Speculative fork; one winner survives. |
| **Terminal** | `commit` | Accepted residue. |
| | `halt` | Failed residue, with a reason. |

Nesting expresses dependency. `let` expresses sharing. A recipe expresses production. `commit` and `halt` record which residue was kept and which was thrown away. You start with two — `action` and `oracle` — and reach for the rest only when the shape of the work demands it.

The JSON design IR compiles all nine forms: `action`, `oracle`, `trial`, `let`, `cond`, `commit`, and `halt`. Built-in cond predicates (`file-exists:<path>`, `file-nonempty:<path>`, `exit-zero:<cmd>`) are specified as strings in the JSON and resolved at compile time. Custom predicates and callable actions use behavior-based identity (CSE v2 §E5).

---

## Verify it yourself

Nothing here asks for trust. Recompute the frozen roots with the shipped Python reader:

```bash
python -c "
import sys; sys.path.insert(0, 'src')
from husks.core import recompute_root
for name in ('demo', 'adversarial'):
    husk = open(f'spec/conformance/{name}.husk', 'rb').read()
    want = open(f'spec/conformance/{name}.root').read().strip()
    got  = recompute_root(husk, f'spec/conformance/{name}.site')
    print(name, got[:16] + '...', 'PASS' if got == want else 'FAIL')
"
```

Recompute them again with the independent JavaScript reader — different language, same bytes, same root:

```bash
node spec/conformance/verify.mjs spec/conformance/demo.husk \
     spec/conformance/demo.site "$(cat spec/conformance/demo.root)"
node spec/conformance/verify.mjs spec/conformance/adversarial.husk \
     spec/conformance/adversarial.site "$(cat spec/conformance/adversarial.root)"
```

Run the suite:

```bash
pip install -e .
python -m pytest tests/ -q
```

And run the cold bootstrap — a reader written from the spec alone, judged by the gate:

```bash
rm -rf /tmp/bootstrap-core && mkdir -p /tmp/bootstrap-core
cp spec/CSE-v1.md        /tmp/bootstrap-core/CSE-v1.md
cp spec/CSE-v2.md /tmp/bootstrap-core/CSE-v2.md
husks run examples/bootstrap-core.json --site /tmp/bootstrap-core
```

A successful run writes `readers/VERIFIED` and prints `GATE PASS`.

---

## Project status

What stands today:

- JSON designs with deterministic lowering into the symbolic build form;
- sealed artifact reuse and full trace recording;
- CSE v1 and v2, both frozen;
- independent Python and JavaScript readers;
- frozen conformance vectors and adversarial parser fixtures;
- Level 0 bootstrap validation, passing.

The next test is recursive: a Husk design that builds more of Husks itself — including its own verifier — while the final root stays independently checkable. That is the work, and it is named at the end for a reason.

---

For the design philosophy, execution model, and formal semantics, see [Theory](docs/Theory.md).

---

**License:** Apache-2.0
