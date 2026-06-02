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

## Working structure
Three processes that cannot inspect each other: the user (sets the acceptance
condition), you (writes the design), and the oracle (produces output). None can
verify another by looking inside it. They coordinate only through deterministic
gates: action rules whose pass/fail does not depend on who produced the input.
Your job is to move as much of "correct" as possible into deterministic gates.
You do not decide what "done" means; the user does. You do not trust the oracle;
a deterministic action must check it.

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

def _load_template_file(filename: str) -> str:
    """Load a template file from examples/templates/."""
    from husks.resources import templates_dir
    template_file = templates_dir() / filename
    return template_file.read_text()

_DEMO_DESIGN = None
_DEMO_CHECK_GREETING = None
_DEMO_SPEC_MD = None

def _get_demo_design():
    global _DEMO_DESIGN
    if _DEMO_DESIGN is None:
        _DEMO_DESIGN = json.loads(_load_template_file("demo.json"))
    return _DEMO_DESIGN

def _get_demo_check_greeting():
    global _DEMO_CHECK_GREETING
    if _DEMO_CHECK_GREETING is None:
        _DEMO_CHECK_GREETING = _load_template_file("check-greeting.py")
    return _DEMO_CHECK_GREETING

def _get_demo_spec_md():
    global _DEMO_SPEC_MD
    if _DEMO_SPEC_MD is None:
        _DEMO_SPEC_MD = _load_template_file("demo-spec.md")
    return _DEMO_SPEC_MD

# ── core-bootstrap template ─────────────────────────────────────────
def _load_core_bootstrap_design():
    """Load core-bootstrap template from examples/templates/."""
    return json.loads(_load_template_file("core-bootstrap.json"))

_CORE_BOOTSTRAP_DESIGN = None  # Lazy-loaded via _get_core_bootstrap_design()

def _get_core_bootstrap_design():
    """Get core-bootstrap design, loading it on first access."""
    global _CORE_BOOTSTRAP_DESIGN
    if _CORE_BOOTSTRAP_DESIGN is None:
        _CORE_BOOTSTRAP_DESIGN = _load_core_bootstrap_design()
    return _CORE_BOOTSTRAP_DESIGN

_CORE_BOOTSTRAP_HY = None

def _get_core_bootstrap_hy():
    global _CORE_BOOTSTRAP_HY
    if _CORE_BOOTSTRAP_HY is None:
        _CORE_BOOTSTRAP_HY = _load_template_file("core-bootstrap.hy")
    return _CORE_BOOTSTRAP_HY


def _write_if(path: Path, content: str, force: bool, verbose: bool = False) -> bool:
    """Write content to path if it doesn't exist or force is set. Returns True if written."""
    if path.exists() and not force:
        if verbose:
            print(f"        {path.name} exists (use --force to overwrite)")
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if verbose:
        print(f"        wrote {path.relative_to(path.parent.parent) if path.parent.parent != path.parent else path.name}")
    return True


def _copy_spec_files(target: Path, verbose: bool = False) -> bool:
    """Copy CSE spec files from the package to the target spec/ directory."""
    # Find the spec files - they should be in the repo or bundled with the package
    pkg_root = Path(__file__).resolve().parent

    # Try multiple locations
    spec_sources = [
        pkg_root.parents[1] / "spec",  # repo: src/husks -> src -> repo
        pkg_root / "_resources" / "spec",  # bundled in wheel
    ]

    spec_dir = None
    for candidate in spec_sources:
        if candidate.exists() and (candidate / "CSE-v1.md").exists():
            spec_dir = candidate
            break

    if spec_dir is None:
        if verbose:
            print("  warning: could not find CSE spec files, creating placeholders", file=sys.stderr)
        # Create minimal placeholders
        (target / "spec").mkdir(parents=True, exist_ok=True)
        (target / "spec" / "CSE-v1.md").write_text("# CSE v1 specification\n\n(Placeholder - install husks with spec files)\n")
        (target / "spec" / "CSE-v2.md").write_text("# CSE v2 clarifications\n\n(Placeholder - install husks with spec files)\n")
        if verbose:
            print("        created spec/ directory with placeholders")
        return True

    # Copy the actual spec files
    import shutil
    (target / "spec").mkdir(parents=True, exist_ok=True)
    for fname in ["CSE-v1.md", "CSE-v2.md"]:
        src = spec_dir / fname
        dst = target / "spec" / fname
        if dst.exists():
            if verbose:
                print(f"        spec/{fname} exists")
        else:
            shutil.copy2(src, dst)
            if verbose:
                print(f"        copied spec/{fname}")
    return True


def _scaffold_core_bootstrap(target: Path, force: bool, emit_hy: bool, verbose: bool = False) -> bool:
    """Scaffold the core-bootstrap beta seed project."""
    # 1. Create core-bootstrap.json
    _write_if(
        target / "core-bootstrap.json",
        json.dumps(_get_core_bootstrap_design(), indent=2) + "\n",
        force, verbose=verbose,
    )

    # 2. Copy spec files
    _copy_spec_files(target, verbose=verbose)

    # 3. Create .gitignore
    gitignore_content = textwrap.dedent("""\
        # Husks build artifacts
        *.husk
        .env

        # Site directories
        m1/
        m2/
        m3/
        site/

        # Generated outputs
        readers/
        cache.tar.gz
        *.json.report

        # Python
        __pycache__/
        *.pyc
        """)
    _write_if(target / ".gitignore", gitignore_content, force, verbose=verbose)

    # 4. Optionally create bootstrap.hy
    if emit_hy:
        _write_if(target / "bootstrap.hy", _get_core_bootstrap_hy(), force, verbose=verbose)

    return True


def _scaffold_template(target: Path, template: str, force: bool, emit_hy: bool = False, verbose: bool = False) -> bool:
    """Scaffold project files for the given template. Returns True on success."""
    if template == "core-bootstrap":
        return _scaffold_core_bootstrap(target, force, emit_hy, verbose=verbose)
    elif template == "demo":
        _write_if(target / "design.json",
                  json.dumps(_get_demo_design(), indent=2) + "\n", force, verbose=verbose)
        _write_if(target / "check-greeting.py", _get_demo_check_greeting(), force, verbose=verbose)
        # Also write a gitignore for build artifacts
        gitignore_content = textwrap.dedent("""\
            # Husks build artifacts
            .husk/
            greeting.txt
            validation-report.txt
            VERIFIED
            """)
        _write_if(target / ".gitignore", gitignore_content, force, verbose=verbose)
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


def init(target=".", template="core-bootstrap", emit_hy=False, claude_code=True, force=False, verbose=False):
    """Scaffold a Husks project and wire it to Claude Code.

    Default: silent on success (prints nothing except errors).
    With --verbose: shows diamond banner and step-by-step detail.
    """
    from husks.utils.console import BOLD, DIM, CYAN, RESET, render_banner

    target = Path(target).resolve()
    target.mkdir(parents=True, exist_ok=True)

    # Determine design name from template
    design_file = "core-bootstrap.json" if template == "core-bootstrap" else "design.json"
    design_name = template

    # ── verbose: banner ──────────────────────────────────────────────
    if verbose:
        banner = render_banner("dry", [
            f"{BOLD}name{RESET}:  {design_name}",
            f"{BOLD}state{RESET}: {DIM}init{RESET}",
            "",
            "",
            f"{BOLD}site{RESET}:  {target}",
        ])
        print(banner)
        print()

    # 1. scaffold template files
    if verbose:
        print(f"  {BOLD}scaffold{RESET}")
        print(f"  {DIM}{'─' * 58}{RESET}")
    if not _scaffold_template(target, template, force, emit_hy, verbose=verbose):
        return 1

    # 2. soundness gate
    if verbose:
        print(f"  {DIM}selftest{RESET}", end="", flush=True)
    if not selftest(verbose=False):
        print("\n  error: engine selftest failed", file=sys.stderr)
        return 1
    if verbose:
        print(f"  {CYAN}ok{RESET}")

    # 3. API key
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_key:
        env = target / ".env"
        if not env.exists():
            env.write_text("ANTHROPIC_API_KEY=\n")
        _ensure_gitignored(target, ".env")
    if verbose:
        if has_key:
            print(f"  {DIM}api key{RESET}  {CYAN}ok{RESET}")
        else:
            print(f"  {DIM}api key{RESET}  not set (fill .env for live runs)")

    # 4. Claude Code skill hookup
    if claude_code:
        skill_src = _skill_dir()
        if not (skill_src / "SKILL.md").exists():
            print(f"  error: skill not found at {skill_src}", file=sys.stderr)
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
                link = None
        if link is not None:
            import shutil
            if skill_is_packaged():
                shutil.copytree(skill_src, link)
            else:
                try:
                    link.symlink_to(skill_src, target_is_directory=True)
                except OSError:
                    shutil.copytree(skill_src, link)
        if verbose:
            print(f"  {DIM}skill{RESET}    {CYAN}ok{RESET}")

    # 5. CLAUDE.md
    claude_md = target / "CLAUDE.md"
    if not claude_md.exists() or force:
        claude_md.write_text(CLAUDE_MD)
    if verbose:
        print(f"  {DIM}CLAUDE.md{RESET} {CYAN}ok{RESET}")

    # ── footer ───────────────────────────────────────────────────────
    if verbose:
        print(f"  {DIM}{'─' * 58}{RESET}")

    rel = os.path.relpath(target)
    print()
    print(f"  {DIM}cd {rel}{RESET}")
    print(f"  {DIM}husks check {design_file} --verbose{RESET}")
    print(f"  {DIM}husks run {design_file} --site m1 --stub{RESET}")
    print()
    return 0
