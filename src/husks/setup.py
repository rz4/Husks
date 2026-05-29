#- setup.py — install streamlining: `husks selftest` and `husks init`
#
# selftest: recompute the frozen conformance roots with the Python reader.
#           No network, no model, no pytest dependency. Soundness in one call.
# init:     wire a project to drive Husks from Claude Code — check the API key,
#           symlink the shipped skill into .claude/skills/, and emit CLAUDE.md.

import os
import sys
from pathlib import Path

from husks.core import recompute_root
from husks.resources import skill_dir as _skill_dir
from husks.resources import skill_is_packaged


# ── the canonical stance, versioned with the engine ─────────────────────
# Emitted into a project's CLAUDE.md by `husks init`. Encodes the workflow
# the skill assumes, plus the recipe-hygiene lessons that only surface once
# a live agent has actually run a design.
CLAUDE_MD = """\
# Project conventions — Husks

This project uses **Husks** for any task that produces artifacts: code
generation, scaffolding, content, multi-step builds. Do not run as an unbounded
agent loop. Use the `husks` skill — decompose the task into a `design.json` build
graph, then check, show, and run it.

## Workflow
- Write `design.json` first. No exploring or running commands before that.
- `check` then `show` the design. **Wait for approval before `run`.**
- Run `--stub` first when the shape is new; go live only after the stub commits.
- On `run`: the CLI prints a structured Report (status, root, fuel, cost, delta,
  per-node table, diagnosis). Use `--json` for machine-readable output.

## Two forms to start
- Use `action` (deterministic) and `oracle` (one bounded model call).
- The JSON IR also supports `let`, `cond`, and `trial`, but start with
  `action` + `oracle` until the simpler forms are routine.

## Recipes must be portable
The `.husk` is permanent and meant to verify and re-run anywhere. Action `run`
commands therefore must not bake in machine-specific state:
- **No absolute paths** (no `/home/<user>/...`). A leaked path lives in the seal forever.
- **Do not activate a venv inside `run`** (`source .../activate`). The build already
  runs in your environment; `source` is also non-portable under `/bin/sh`. Call
  tools directly: `python -m pytest -q > test-results.txt 2>&1`.

## Validation is a deterministic action, never an oracle
- Oracles produce; actions verify. Never let a model grade its own output.
- Gate on **exit code**, not fragile text matches. A nonzero `run` halts the build,
  so `python -m pytest ...` already fails the build on a test failure. Avoid
  `grep -q passed` style checks — they pass on "1 passed, 3 failed".

## Spec independence (correctness-critical builds)
Do not let the test oracle read the implementation it is testing — that verifies
self-consistency, not correctness. Declare the spec as its own artifact and give
the **same** spec to both the implementation oracle and the test oracle as input,
so the tests check the spec, not whatever the implementation happened to do.
"""


# ── conformance resolution ─────────────────────────────────────────────
def _resolve_conformance(override=None) -> Path:
    """Resolve the conformance vector directory via fallback chain.

    1. Explicit override (from --conformance flag)
    2. HUSKS_CONFORMANCE_DIR env var
    3. husks_conformance.conformance_dir() (if installed)
    4. spec/conformance relative to repo root
    5. Error
    """
    # 1. Explicit argument
    if override is not None:
        p = Path(override).resolve()
        if p.exists():
            return p
        raise FileNotFoundError(f"Conformance directory not found: {p}")

    # 2. Environment variable
    env = os.environ.get("HUSKS_CONFORMANCE_DIR")
    if env:
        p = Path(env).resolve()
        if p.exists():
            return p
        raise FileNotFoundError(
            f"HUSKS_CONFORMANCE_DIR points to nonexistent path: {p}"
        )

    # 3. husks_conformance package
    try:
        from husks_conformance import conformance_dir
        return conformance_dir()
    except (ImportError, FileNotFoundError):
        pass

    # 3.5. Bundled in wheel (force-included by pyproject.toml)
    _PKG = Path(__file__).resolve().parent
    bundled = _PKG / "_resources" / "conformance"
    if bundled.exists():
        return bundled

    # 4. Repo-relative fallback
    repo = Path(__file__).resolve().parent.parents[1]  # src/husks -> src -> repo
    candidate = repo / "spec" / "conformance"
    if candidate.exists():
        return candidate

    raise FileNotFoundError(
        "Conformance vectors not found. Install husks-conformance, "
        "set HUSKS_CONFORMANCE_DIR, or pass --conformance."
    )


# ── selftest ────────────────────────────────────────────────────────────
def selftest(verbose=True, conformance=None):
    """Recompute the frozen conformance roots. Returns True iff all match."""
    try:
        conf = _resolve_conformance(conformance)
    except FileNotFoundError as e:
        print(f"  error: {e}", file=sys.stderr)
        return False

    vectors = sorted(p.stem for p in conf.glob("*.husk"))
    if not vectors:
        print(f"  error: no .husk vectors in {conf}", file=sys.stderr)
        return False

    all_ok = True
    for name in vectors:
        husk = (conf / f"{name}.husk").read_bytes()
        root_file = conf / f"{name}.root"

        if root_file.exists():
            # positive vector: reader must reproduce the frozen root
            want = root_file.read_text().strip()
            site = str(conf / f"{name}.site")
            try:
                got = recompute_root(husk, site)
                ok, detail = (got == want), got[:16] + "..."
            except Exception as e:  # noqa: BLE001
                ok, detail = False, f"error: {e}"
        else:
            # negative vector: reader must REJECT malformed input
            try:
                got = recompute_root(husk, str(conf))
                ok, detail = False, f"accepted ({got[:16]}...)"  # accepting is failure
            except Exception:  # noqa: BLE001
                ok, detail = True, "correctly rejected"

        all_ok &= ok
        if verbose:
            print(f"  {name:<26s} {'PASS' if ok else 'FAIL'}  {detail}")
    return all_ok


# ── template scaffolding ──────────────────────────────────────────────
import json
import textwrap

_DEMO_DESIGN = {
    "name": "demo",
    "fuel": 10,
    "target": "write-message",
    "rules": [
        {
            "name": "write-message",
            "kind": "oracle",
            "inputs": [],
            "outputs": ["message.txt"],
            "prompt": "Write a friendly greeting to message.txt. Make it warm and welcoming.",
            "tools": ["write-file"],
            "fuel": 5,
        },
    ],
}

_DEMO_CHECK_GREETING = textwrap.dedent("""\
    #!/usr/bin/env python3
    \"\"\"Validate that greeting.txt follows the spec.\"\"\"
    import sys
    from pathlib import Path

    greeting_file = Path("greeting.txt")
    if not greeting_file.exists():
        print("ERROR: greeting.txt not found", file=sys.stderr)
        Path("result.txt").write_text("fail: file not found\\n")
        sys.exit(1)

    text = greeting_file.read_text().strip()
    lines = text.splitlines()

    errors = []
    if not lines:
        errors.append("empty file")
    elif len(lines) != 1:
        errors.append(f"expected 1 line, got {len(lines)}")
    else:
        line = lines[0]
        if not line.startswith("Hello"):
            errors.append("must start with 'Hello'")
        if not line.endswith("!"):
            errors.append("must end with '!'")

    if errors:
        for err in errors:
            print(f"FAIL: {err}", file=sys.stderr)
        Path("result.txt").write_text("fail\\n")
        sys.exit(1)
    else:
        print("PASS: greeting validated")
        Path("result.txt").write_text("pass\\n")
        sys.exit(0)
""")

_DEMO_SPEC_MD = textwrap.dedent("""\
    # Greeting Spec

    Write a short, friendly greeting that:
    - Starts with "Hello"
    - Is exactly one line
    - Ends with an exclamation mark
""")


def _write_if(path: Path, content: str, force: bool) -> bool:
    """Write content to path if it doesn't exist or force is set. Returns True if written."""
    if path.exists() and not force:
        print(f"        {path.name} exists (use --force to overwrite)")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    print(f"        wrote {path.relative_to(path.parent.parent) if path.parent.parent != path.parent else path.name}")
    return True


def _scaffold_template(target: Path, template: str, force: bool) -> bool:
    """Scaffold project files for the given template. Returns True on success."""
    if template == "demo":
        _write_if(target / "design.json",
                  json.dumps(_DEMO_DESIGN, indent=2) + "\n", force)
        return True
    else:
        print(f"  error: unknown template '{template}'", file=sys.stderr)
        return False


# ── init ────────────────────────────────────────────────────────────────
def _ensure_gitignored(target: Path, entry: str):
    gi = target / ".gitignore"
    lines = gi.read_text().splitlines() if gi.exists() else []
    if entry not in lines:
        with gi.open("a") as f:
            f.write(("" if not lines or lines[-1] == "" else "\n") + entry + "\n")


def init(target=".", template="demo", claude_code=True, force=False):
    """Scaffold a Husks project and wire it to Claude Code."""
    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)
    print(f"  husks init → {target}\n")

    # 1. scaffold template files
    print(f"  [1/5] scaffolding '{template}' template")
    if not _scaffold_template(target, template, force):
        return 1
    print()

    # 2. soundness gate — refuse to wire up an engine that doesn't verify
    print("  [2/5] verifying engine soundness")
    if not selftest():
        print("\n  aborted: engine selftest failed. Fix conformance before wiring up.",
              file=sys.stderr)
        return 1
    print()

    # 3. API key
    print("  [3/5] checking ANTHROPIC_API_KEY")
    if os.environ.get("ANTHROPIC_API_KEY"):
        print("        present in environment ✓")
    else:
        env = target / ".env"
        if not env.exists():
            env.write_text("ANTHROPIC_API_KEY=\n")
        _ensure_gitignored(target, ".env")
        print("        not set. Wrote .env placeholder (gitignored).")
        print("        Fill it in, then:  set -a && source .env")
        print("        (needed only for live runs, not --stub)")
    print()

    # 4. Claude Code skill hookup
    print("  [4/5] wiring the husks skill into Claude Code")
    if claude_code:
        skill_src = _skill_dir()
        if not (skill_src / "SKILL.md").exists():
            print(f"        error: skill not found at {skill_src}", file=sys.stderr)
            return 1
        skills_dir = target / ".claude" / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        link = skills_dir / "husks"
        if link.exists() or link.is_symlink():
            if force:
                if link.is_symlink() or link.is_file():
                    link.unlink()
                else:
                    import shutil
                    shutil.rmtree(link)
            else:
                print(f"        {link} exists (use --force to replace)")
                link = None
        if link is not None:
            import shutil
            if skill_is_packaged():
                # wheel install: copy out of site-packages (don't symlink into it)
                shutil.copytree(skill_src, link)
                print(f"        copied skill → .claude/skills/husks")
            else:
                try:
                    link.symlink_to(skill_src, target_is_directory=True)
                    print(f"        symlinked .claude/skills/husks → {skill_src}")
                except OSError:
                    shutil.copytree(skill_src, link)
                    print(f"        copied skill → .claude/skills/husks (symlink unavailable)")
    else:
        print("        skipped (--no-claude-code)")
    print()

    # 5. CLAUDE.md
    print("  [5/5] emitting CLAUDE.md (canonical stance)")
    claude_md = target / "CLAUDE.md"
    if claude_md.exists() and not force:
        print(f"        {claude_md} exists (use --force to overwrite)")
    else:
        claude_md.write_text(CLAUDE_MD)
        print("        wrote CLAUDE.md")
    print()

    rel = os.path.relpath(target)
    print("  done. Next:")
    print(f"    cd {rel}")
    print("    husks check")
    print("    husks run --stub")
    return 0
