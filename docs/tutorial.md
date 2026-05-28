# Running Claude Code with Husks

A tutorial for driving the Husks build calculus from a Claude Code instance.

By the end you will have Claude Code authoring **designs** instead of running an
unbounded agent loop: it writes a build graph, you read the contract before any
model touches anything, the runtime fires only what is stale, and every claim
the system makes is a claim about sealed residue you can recompute yourself.

> Install is a single `pip install` from the GitHub URL — no checkout required.
> Setup is two commands after that: `husks selftest` and `husks init`.

---

## 0. The mental model (read this first)

There are **three** roles, and keeping them separate is the whole point.

| Role | Who plays it | What it does |
| :--- | :--- | :--- |
| **Author** | the Claude Code instance | reads your task, writes `design.json`, runs the CLI, reports |
| **Producer** | the husks `oracle` (a litellm call, default `claude-haiku-4-5`) | the one nondeterministic step — generates bytes inside a bounded workspace |
| **Verifier** | the deterministic engine + frozen roots | seals, reuses, recomputes hashes; grades neither author nor producer on its say-so |

The author and the producer are **different model calls**. Claude Code writes
the contract; a separate, fuel-bounded oracle inside the design produces the
residue. The verifier is not a model at all. A model can write a verifier; it
cannot grade its own verifier — that separation is what you are setting up.

---

## 1. Prerequisites

- **Python ≥ 3.10**
- **Node.js** (optional — only for the independent JavaScript reader / gate cross-check)
- **Claude Code** — `npm install -g @anthropic-ai/claude-code`
- **An Anthropic API key** — needed only for *live* oracle runs, not for `--stub`

---

## 2. Install Husks

Into a virtual environment, straight from GitHub:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip                                          # PEP 508 direct refs
pip install "husks[llm] @ git+https://github.com/rz4/Husks.git"
```

That's the whole install. The `[llm]` extra pulls in `litellm` for live oracle
calls. Without it, `check`, `selftest`, `init`, and `--stub` runs still work —
only live oracle execution requires `litellm`. The wheel also ships the
conformance vectors and the skill.

> **Hy backend (experimental).** The `--hy` flag activates the original Hy
> kernel backend. This requires `pip install hy` and a source checkout with `.hy`
> design files. The CLI currently only loads JSON designs; Hy design loading is
> experimental and may not work end-to-end from the CLI.

> **Contributing to Husks itself?** Use an editable checkout instead —
> `git clone …` then `pip install -e ".[llm]"`. Both install modes are fully
> supported; the editable one just lets you hack on the engine in place.

---

## 3. Confirm the engine is sound

Recompute the frozen conformance roots. One command, no model, no network:

```bash
husks selftest
```

Expected: every positive vector reproduces its frozen root (`demo` →
`9977239d…`, `adversarial` → `5382838c…`) and every malformed vector is
**correctly rejected**, with exit code 0. This mirrors the level-0 conformance
gate and reads the vectors bundled in the install. If anything here is not green,
stop — the permanence property is what the rest of this rests on.

(`python -m pytest tests/ -q` runs the full suite, but that needs a source
checkout; `selftest` is the install-level soundness check.)

---

## 4. Wire a project to Claude Code

From the project directory where you'll run Claude Code (or pass it as an
argument):

```bash
husks init                     # sets up the current directory
# or:  husks init /path/to/project
```

`husks init` does four things, and refuses to continue past the first if the
engine doesn't verify:

1. **Soundness gate** — runs `selftest`; aborts if the engine doesn't reproduce
   its roots.
2. **API key check** — confirms `ANTHROPIC_API_KEY` if it's in your environment;
   otherwise writes a gitignored `.env` placeholder and prints the
   `set -a && source .env` line to fill in. (It can't set your parent shell's
   environment, so it guides rather than pretends. The key is needed only for
   live runs.)
3. **Skill hookup** — installs the skill at `.claude/skills/husks`. On a
   non-editable install it **copies** the skill out of the package; from a source
   checkout it symlinks instead, so it stays in sync with the repo.
4. **CLAUDE.md** — emits the canonical stance file (see §5).

It's idempotent: re-running reports "exists" rather than clobbering. Use
`--force` to overwrite, `--no-claude-code` to skip the skill hookup.

> Because the skill is **copied** on a non-editable install, upgrading Husks
> later won't update an already-installed copy. After
> `pip install -U "husks @ git+…"`, re-run `husks init --force` to refresh the
> project's skill and CLAUDE.md.

Then confirm Claude Code sees the skill:

```bash
claude doctor                  # look for "husks" under loaded skills
```

---

## 5. What the emitted CLAUDE.md says (and why it's emitted)

The stance file is written by the CLI, not copied from this tutorial, on purpose:
it's versioned with the engine, so it can't drift, and it's where lessons from
real runs get encoded. The current stance:

- **Design first.** Write `design.json` before exploring or running anything.
- **Check, wait.** `check` the design (add `--verbose` to print the compiled
  graph); wait for your approval before `run`. Stub-first when the shape is new.
- **Two forms to start.** `action` (deterministic) and `oracle` (one bounded
  model call). The JSON IR also supports `let`, `cond`, and `trial`, but start
  with `action` + `oracle` until the simpler forms are routine.
- **Recipes must be portable.** No absolute paths (a leaked `/home/<user>/…` path
  lives in the seal forever), and no `source .../activate` inside a `run` — the
  build already runs in your environment, and `source` is non-portable under
  `/bin/sh`. Call tools directly: `python -m pytest -q > test-results.txt 2>&1`.
- **Validation is a deterministic action, never an oracle.** Gate on exit code,
  not text matches — a nonzero `run` already halts the build.
- **Spec independence.** For correctness-critical builds, don't let the test
  oracle read the implementation it tests (that verifies self-consistency, not
  correctness). Declare the spec as its own artifact and give the *same* spec to
  both the implementation oracle and the test oracle.

The last two lines came directly out of the first live agent run — they are
findings turned into standing policy.

---

## 6. First session — drive it end to end

With the venv active and the project wired, start Claude Code:

```bash
source .venv/bin/activate
claude
```

Give it a small, self-contained task — one deterministic step and one generated
step is ideal:

> Use the husks skill. Write a Python module `slugify.py` with a `slugify(s)`
> function, plus a pytest file that checks several cases. Validate with pytest as
> an action. Target a `.complete` marker.

What you should see, in order:

1. **It writes `design.json` first** — before reading files or running anything.
2. **`check --verbose`** — validates the design and prints the compiled graph for
   you to read. This is the contract: inputs, outputs, prompts, tools, and fuel,
   all visible *before* any model call.
3. **It stops and asks approval.** Approve.
4. **Stub run** (if requested): `husks run design.json --site /tmp/husks-slug --stub`
   — confirms the graph executes and seals.
5. **Live run:** drop `--stub`. The oracle fires `claude-haiku-4-5` via litellm,
   produces the module, the `pytest` action verifies it, the build commits or
   halts.
6. **Root recomputation** — the skill recomputes the `.husk` root as its single
   post-build check, proving the residue is self-verifying.

If the build **halts**, the trace names the failing rule and why. The skill is
told to read it and propose a revised design rather than silently re-running.

---

## 7. Read what happened

```bash
husks history design.json --site /tmp/husks-slug              # all nodes
husks history design.json scaffold --site /tmp/husks-slug     # one rule, in detail
```

`history` classifies each node:

- **Converging** — fuel falling/flat, prompt flat. Settling toward its minimal
  form; may be ready to become an `action`.
- **Prompt-loading** — fuel falling, **prompt rising**. The alarm. The agent is
  hand-migrating determined work into the prompt and paying the oracle to read it
  back. The cost didn't leave; it moved to your hands.
- **Stable** — output hashes identical across runs. A fixed specimen — make it an
  action.
- **Volatile** — no settled trend. Not converged.

The work you do across re-runs is **program extraction against nondeterminism**:
every node you can reduce to a deterministic rule should stop being an oracle. An
oracle whose output is fixed by its inputs is transcription you haven't extracted
yet.

You can also recompute the root yourself — no engine required, just bytes and
SHA-256:

```bash
python -c "
from husks.core import recompute_root
import pathlib
site='/tmp/husks-slug'
husk=pathlib.Path(site,'<build-name>.husk').read_bytes()
print(recompute_root(husk, site))
"
```

---

## 8. What the engine enforces for you

You don't have to police all of this by hand — `check` and the runtime do:

- **Fuel is a real budget.** Each stale rule that fires costs one unit of global
  fuel. Each oracle also has a local fuel cap that bounds its agentic steps.
  `check` rejects a design whose total oracle fuel exceeds the global budget.
- **Actions halt on failure.** A nonzero `run` raises and halts the build, so a
  failing validator stops the build before the terminal rule fires.
- **Empty oracle outputs halt.** An oracle that produces a missing or zero-byte
  declared output halts rather than sealing — an empty residue is not evidence
  the work happened, so it isn't sealed as if it were. (Actions are exempt:
  zero-byte markers like `touch .complete` are legitimate.)
- **Seals are content-addressed.** Same inputs + same recipe = same seal = same
  root. Change content and the root changes; change nothing and the rule is free.

---

## 9. Troubleshooting

| Symptom | Cause | Fix |
| :--- | :--- | :--- |
| `pip install "husks @ git+…"` rejects the spec | old pip without PEP 508 direct-reference support | `pip install -U pip`, retry |
| `No module named litellm` on a live run | installed without the `[llm]` extra | reinstall with `pip install "husks[llm] @ git+…"` |
| `AuthenticationError` / 401 from the oracle | no key in env | fill `.env`, then `set -a && source .env` |
| Claude Code doesn't use Husks | skill not loaded | `claude doctor`; confirm `.claude/skills/husks/SKILL.md` exists; restart session |
| Skill seems out of date after upgrading Husks | non-editable install copies the skill | `husks init --force` to refresh it |
| `check` rejects the design | missing `target`/output, oracle fuel/tools, or undeclared input | read the error; the skill repairs and re-checks |
| Build halts on "empty or missing output" | an oracle wrote nothing or a 0-byte file | refine the oracle prompt; this guard is working as intended |
| Design uses `let`/`cond`/`trial` unexpectedly | advanced forms need care | start with `action`+`oracle`; use advanced forms only when needed |

---

## 10. Where this goes next

Two experiments, in order of reach:

**Spec-independence in practice.** Have Claude Code author a design where the spec
is a declared artifact fed to *both* the implementation oracle and the test
oracle, and check whether the emitted CLAUDE.md actually changes the shape of what
it produces versus a naive run. This tells you the encoded lessons are
load-bearing, not decoration.

**The recursive case.** Have an oracle emit *more of Husks itself* — including a
verifier — while the final root stays independently checkable by a reader that
never saw the producing engine. That is the test the whole design is built to
pass, and it's the natural endpoint once a live agent is reliably authoring
two-form designs.

For the engine internals, see [`architecture.md`](architecture.md).  For the
permanence argument, see [`Theory.md`](Theory.md).  For the full CLI reference,
see [`cli.md`](cli.md).  For the CSE wire format specs, see `spec/CSE-v1.md`
and `spec/CSE-v2.md`.
